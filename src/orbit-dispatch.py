#!/usr/bin/env python3
"""
ORBIT Dispatch Engine — Week-2
동작: T5/T4 (또는 설정된 tier) 잡을 실제로 openclaw cron run <id> 로 실행
- task_runs에 실행 이력 기록
- 3회 연속 성공 시 cron 비활성화 후 orbit_managed=1 전환
- orbit-tick.py에서 호출됨 (직접 실행 가능)
"""

import json
import os
import shlex
import sys
import subprocess
import time
import uuid
from datetime import datetime, timezone

from orbit_db import (
    get_db, get_config, set_config, BACKEND, now_utc, json_dumps, close_db,
    ORBIT_HOME_DEFAULT,
)

CONSECUTIVE_SUCCESS_THRESHOLD = 3  # 연속 성공 후 cron 비활성화

# AgentHive 상태 가드: 이 상태면 dispatch 스킵
AH_SKIP_STATUSES = {"blocked", "done", "review"}

# Orbit Tier → AgentHive Priority 매핑
TIER_TO_AH_PRIORITY = {1: "critical", 2: "high", 3: "medium", 4: "low", 5: "low"}

# ℝ⁴ dispatch score 가중치 (W 벡터)
# dispatch_score = w_luca*p_luca + w_lord*p_lord + w_internal*p_internal + w_depth*p_depth
# 가중치는 system_config에서 읽거나 아래 기본값 사용
DEFAULT_WEIGHTS = {
    "w_luca":     0.35,  # 루카 명시적 관심도
    "w_lord":     0.25,  # 로드(Claude) 자율 판단
    "w_internal": 0.25,  # 시스템 내부 중요도
    "w_depth":    0.15,  # 처리 깊이/복잡도
}
# tier 보너스: 좌표계 점수에 더해지는 기본 우선순위
TIER_BONUS = {1: 1.0, 2: 0.75, 3: 0.5, 4: 0.25, 5: 0.0}

P = "%s" if BACKEND == "postgres" else "?"


def compute_dispatch_score(task, weights=None):
    """ℝ⁴ 좌표계 내적으로 dispatch_score 계산.
    score = tier_bonus + W·P
          = TIER_BONUS[tier] + w_luca*p_luca + w_lord*p_lord + w_internal*p_internal + w_depth*p_depth
    반환값 범위: 0.0 ~ 2.0 (tier_bonus 1.0 + 좌표 내적 최대 1.0)
    """
    w = weights or DEFAULT_WEIGHTS
    tier = task["tier"] if task["tier"] in TIER_BONUS else 5
    tier_bonus = TIER_BONUS[tier]

    p_luca     = task["p_luca"]     or 0.0
    p_lord     = task["p_lord"]     or 0.5
    p_internal = task["p_internal"] or 0.0
    p_depth    = task["p_depth"]    or 0.0

    coord_score = (
        w["w_luca"]     * p_luca +
        w["w_lord"]     * p_lord +
        w["w_internal"] * p_internal +
        w["w_depth"]    * p_depth
    )
    return round(tier_bonus + coord_score, 4)


def get_dispatch_tiers(conn):
    """dispatch_tiers 설정 읽기 (예: '4,5' → [4, 5])."""
    val = get_config(conn, "dispatch_tiers", "")
    if not val:
        return []
    try:
        return [int(t.strip()) for t in val.split(",") if t.strip()]
    except ValueError:
        return []


def run_cron_job(cron_job_id, dry_run=False):
    """(레거시) openclaw cron run <id> 실행. 결과: (success, duration_ms, error)"""
    if dry_run:
        return True, 0, None

    start = time.time()
    try:
        result = subprocess.run(
            ["openclaw", "cron", "run", cron_job_id],
            capture_output=True, text=True, timeout=60
        )
        duration_ms = int((time.time() - start) * 1000)
        if result.returncode == 0:
            return True, duration_ms, None
        else:
            err = result.stderr.strip() or result.stdout.strip()
            return False, duration_ms, err[:500]
    except subprocess.TimeoutExpired:
        duration_ms = int((time.time() - start) * 1000)
        return False, duration_ms, "timeout (60s)"
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        return False, duration_ms, str(e)


def _command_has_shell_meta(command: str) -> bool:
    """True if command likely needs a shell (pipes, redirects, compound lists, etc.)."""
    triggers = (
        "|", "$(", "`", "${", ">", "<", "&&", "||", ";", "\n", "\r",
    )
    return any(t in command for t in triggers)


def run_script(command, timeout=120, dry_run=False):
    """스크립트/명령 직접 실행. 항상 shell=False argv 실행.
    셸 메타문자가 있으면 ORBIT_ALLOW_SHELL이 있을 때만 [\"/bin/bash\", \"-c\", command]로 실행.
    결과: (success, duration_ms, error, output)"""
    if dry_run:
        if _command_has_shell_meta(command) and not os.environ.get("ORBIT_ALLOW_SHELL"):
            return (
                False,
                0,
                "shell metacharacters require ORBIT_ALLOW_SHELL",
                "[dry-run]",
            )
        return True, 0, None, "[dry-run]"

    start = time.time()
    try:
        if _command_has_shell_meta(command):
            if not os.environ.get("ORBIT_ALLOW_SHELL"):
                return (
                    False,
                    0,
                    "shell metacharacters in command require ORBIT_ALLOW_SHELL",
                    "",
                )
            print(
                "[orbit-dispatch] WARNING: executing script command with shell "
                "metacharacters via /bin/bash -c (ORBIT_ALLOW_SHELL is set)",
                file=sys.stderr,
            )
            cmd_list = ["/bin/bash", "-c", command]
        else:
            try:
                cmd_list = shlex.split(command)
            except ValueError as e:
                duration_ms = int((time.time() - start) * 1000)
                return False, duration_ms, f"invalid command: {e}", ""
            if not cmd_list:
                duration_ms = int((time.time() - start) * 1000)
                return False, duration_ms, "empty command", ""

        result = subprocess.run(
            cmd_list,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.path.expanduser(
                os.environ.get("ORBIT_HOME", ORBIT_HOME_DEFAULT)
            ),
        )
        duration_ms = int((time.time() - start) * 1000)
        output = result.stdout.strip()[:1000]
        if result.returncode == 0:
            return True, duration_ms, None, output
        err = result.stderr.strip() or output
        return False, duration_ms, err[:500], output
    except subprocess.TimeoutExpired:
        duration_ms = int((time.time() - start) * 1000)
        return False, duration_ms, f"timeout ({timeout}s)", ""
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        return False, duration_ms, str(e), ""


def run_khala(task_id, command, project=None):
    """Khala 메시지로 런타임에 작업 위임. 결과: (success, duration_ms, error, output)"""
    start = time.time()
    try:
        khala_dir = os.path.expanduser("~/.aria/khala/channels/global")
        tasks_file = os.path.join(khala_dir, "tasks.jsonl")
        nonce = str(uuid.uuid4())[:8]
        msg = {
            "id": f"orbit-dispatch-{task_id}-{int(time.time())}",
            "channel": "global/tasks",
            "from": {"instance": "orbit", "agent": "orbit-dispatch"},
            "to": {"instance": None, "agent": None},
            "mention": [],
            "content": f"[orbit-dispatch] {task_id}: {command}",
            "type": "task",
            "priority": "normal",
            "reply_to": None,
            "artifacts": [],
            "correlation_id": f"orbit-{task_id}",
            "context": {"project": project, "task_id": task_id},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ttl": 3600,
            "nonce": nonce,
        }
        with open(tasks_file, "a") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        duration_ms = int((time.time() - start) * 1000)
        return True, duration_ms, None, f"Khala published: {msg['id']}"
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        return False, duration_ms, str(e), ""


def run_task(task, dry_run=False):
    """다중 백엔드 디스패치. task dict에서 run_backend/run_command/run_timeout 읽기.
    결과: (success, duration_ms, error)
    """
    backend = task.get("run_backend") or "openclaw"
    command = task.get("run_command") or ""
    timeout = task.get("run_timeout") or 120
    task_id = task["id"]

    if backend == "script" and command:
        success, dur, err, output = run_script(command, timeout=timeout, dry_run=dry_run)
        if output and not err:
            print(f"    output: {output[:100]}")
        return success, dur, err

    elif backend == "khala" and command:
        success, dur, err, output = run_khala(task_id, command, task.get("agenthive_project"))
        return success, dur, err

    elif backend == "openclaw" and task.get("cron_job_id"):
        return run_cron_job(str(task["cron_job_id"]), dry_run=dry_run)

    elif backend == "launchd" and command:
        # launchctl kickstart — shell 인젝션 방지: 직접 리스트 구성
        if dry_run:
            return True, 0, None
        start = time.time()
        try:
            uid = str(os.getuid())
            result = subprocess.run(
                ["launchctl", "kickstart", f"gui/{uid}/{command}"],
                capture_output=True, text=True, timeout=30, shell=False
            )
            dur = int((time.time() - start) * 1000)
            return result.returncode == 0, dur, result.stderr.strip()[:200] if result.returncode != 0 else None
        except Exception as e:
            dur = int((time.time() - start) * 1000)
            return False, dur, str(e)

    else:
        return False, 0, f"no executable config: backend={backend}, command={command!r}, cron_job_id={task.get('cron_job_id')}"


def record_run(conn, task_id, tick_id, status, started_at, duration_ms, error=None):
    """task_runs에 실행 이력 기록."""
    finished_at = now_utc()
    if BACKEND == "postgres":
        conn.execute("""
            INSERT INTO task_runs(task_id, tick_id, status, started_at, finished_at, duration_ms, error_message, mode)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'tier')
        """, (task_id, tick_id, status, started_at, finished_at, duration_ms, error))
    else:
        conn.execute("""
            INSERT INTO task_runs(task_id, tick_id, status, started_at, finished_at, duration_ms, error_message, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'tier')
        """, (task_id, tick_id, status, started_at, finished_at, duration_ms, error))
    conn.commit()


def update_consecutive(conn, task_id, success):
    """연속 성공 횟수 업데이트."""
    if BACKEND == "postgres":
        if success:
            conn.execute("""
                UPDATE task_defs
                SET consecutive_successes = consecutive_successes + 1,
                    last_dispatched_at = NOW()
                WHERE id = %s
            """, (task_id,))
        else:
            conn.execute("""
                UPDATE task_defs
                SET consecutive_successes = 0,
                    last_dispatched_at = NOW()
                WHERE id = %s
            """, (task_id,))
    else:
        if success:
            conn.execute("""
                UPDATE task_defs
                SET consecutive_successes = consecutive_successes + 1,
                    last_dispatched_at = datetime('now')
                WHERE id = ?
            """, (task_id,))
        else:
            conn.execute("""
                UPDATE task_defs
                SET consecutive_successes = 0,
                    last_dispatched_at = datetime('now')
                WHERE id = ?
            """, (task_id,))
    conn.commit()


def maybe_decommission(conn, task_id, dry_run=False):
    """연속 성공 3회 이상이면 cron 비활성화 + orbit_managed=1."""
    task = conn.execute(
        f"SELECT * FROM task_defs WHERE id={P}", (task_id,)
    ).fetchone()
    if not task:
        return False

    if task["consecutive_successes"] >= CONSECUTIVE_SUCCESS_THRESHOLD and not task["orbit_managed"]:
        backend = task.get("run_backend") or "openclaw"
        cron_job_id = task.get("cron_job_id")
        print(f"    [decommission] {task_id}: 연속 {task['consecutive_successes']}회 성공 → orbit_managed 전환")

        if dry_run:
            print(f"    [dry-run] 디커미션 건너뜀")
            return True

        # script/khala/launchd 백엔드: cron 비활성화 불필요, 바로 orbit_managed
        if backend != "openclaw" or not cron_job_id:
            conn.execute(
                f"UPDATE task_defs SET orbit_managed=TRUE WHERE id={P}", (task_id,)
            )
            conn.commit()
            print(f"    ✅ orbit_managed=1 (backend={backend}, cron 비활성화 불필요)")
            return True

        # openclaw 백엔드: 기존 방식 (cron 비활성화)
        result = subprocess.run(
            ["openclaw", "cron", "disable", str(cron_job_id)],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            conn.execute(
                f"UPDATE task_defs SET orbit_managed=TRUE WHERE id={P}", (task_id,)
            )
            conn.commit()
            print(f"    ✅ cron {str(cron_job_id)[:8]}… 비활성화 완료, orbit_managed=1")
            return True
        else:
            print(f"    ⚠️  cron 비활성화 실패: {result.stderr.strip()[:200]}")
    return False


def _publish_dispatch_alert(results):
    """Khala global/alerts.jsonl에 dispatch 요약 append (관측성)."""
    try:
        aria_home = os.path.expanduser(os.environ.get("ARIA_HOME", "~/.aria"))
        alerts_dir = os.path.join(aria_home, "khala", "channels", "global")
        alerts_file = os.path.join(alerts_dir, "alerts.jsonl")
        task_count = len(results)
        success = sum(1 for r in results if r.get("status") == "success")
        failed = sum(1 for r in results if r.get("status") == "failed")
        line = json.dumps(
            {
                "type": "dispatch-summary",
                "task_count": task_count,
                "success": success,
                "failed": failed,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
        )
        os.makedirs(alerts_dir, exist_ok=True)
        with open(alerts_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        print(f"[orbit-dispatch] alerts append failed: {e}", file=sys.stderr)


def dispatch_tier(conn, tick_id=None, dry_run=False):
    """설정된 tier의 enabled 태스크를 dispatch."""
    results = []
    try:
        mode = get_config(conn, "orbit_mode", "shadow")
        if mode != "active" and not dry_run:
            print(f"[dispatch] orbit_mode={mode} — dispatch 생략 (active 모드 필요)", file=sys.stderr)
            return results

        tiers = get_dispatch_tiers(conn)
        if not tiers:
            print("[dispatch] dispatch_tiers 미설정 — dispatch 생략", file=sys.stderr)
            return results

        # 해당 tier의 enabled 태스크 조회 (orbit_managed가 아직 0인 것만)
        if BACKEND == "postgres":
            placeholders = ",".join(["%s"] * len(tiers))
        else:
            placeholders = ",".join(["?"] * len(tiers))

        tasks = conn.execute(f"""
            SELECT * FROM task_defs
            WHERE tier IN ({placeholders}) AND enabled AND NOT orbit_managed
                  AND (cron_job_id IS NOT NULL OR run_command IS NOT NULL)
            ORDER BY tier ASC, id
        """, tiers).fetchall()

        if not tasks:
            print(f"[dispatch] tier {tiers} — dispatch할 태스크 없음 (전부 orbit_managed 또는 disabled)")
            return results

        # ℝ⁴ dispatch_score 기반 정렬 (높을수록 먼저)
        tasks = sorted(tasks, key=lambda t: compute_dispatch_score(t), reverse=True)
        if tasks:
            print(f"[dispatch] score 순서: " + ", ".join(
                f"{t['id'][:20]}({compute_dispatch_score(t):.3f})" for t in tasks[:5]
            ))

        for task in tasks:
            started_at = now_utc()
            task_id = task["id"]
            cron_job_id = str(task["cron_job_id"])

            # AgentHive 상태 가드: blocked/done/review이면 스킵
            ah_status = task.get("agenthive_status") if hasattr(task, "get") else (task["agenthive_status"] if "agenthive_status" in task.keys() else None)
            if ah_status and ah_status in AH_SKIP_STATUSES:
                print(f"  ⏭️  skip T{task['tier']} {task_id} (agenthive_status={ah_status})")
                continue

            backend = task.get("run_backend") or "openclaw"
            print(f"  → dispatch T{task['tier']} {task_id} (backend={backend})")
            success, duration_ms, error = run_task(task, dry_run=dry_run)

            status = "success" if success else "failed"
            record_run(conn, task_id, tick_id, status, started_at, duration_ms, error)
            update_consecutive(conn, task_id, success)
            maybe_decommission(conn, task_id, dry_run=dry_run)

            result = {
                "task_id": task_id,
                "tier": task["tier"],
                "status": status,
                "duration_ms": duration_ms,
                "error": error,
            }
            results.append(result)

            icon = "✅" if success else "❌"
            print(f"    {icon} {status} ({duration_ms}ms){' — ' + error if error else ''}")

        return results
    finally:
        _publish_dispatch_alert(results)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="ORBIT dispatch engine (Week-2)")
    parser.add_argument("--dry-run", action="store_true", help="실제 dispatch 없이 시뮬레이션")
    parser.add_argument("--tier", help="dispatch할 tier 오버라이드 (예: 4,5)")
    parser.add_argument("--json", action="store_true", help="JSON 출력")
    args = parser.parse_args()

    conn = get_db()
    try:
        if args.tier:
            # 임시 오버라이드 — set_config handles upsert for both backends
            set_config(conn, "dispatch_tiers", args.tier)

        mode = get_config(conn, "orbit_mode", "shadow")
        tiers = get_dispatch_tiers(conn)
        ts = now_utc()

        print(f"[ORBIT dispatch] {ts} | mode={mode} | tiers={tiers} | dry_run={args.dry_run}")
        results = dispatch_tier(conn, dry_run=args.dry_run)

        if args.json:
            print(json.dumps({"ts": ts, "mode": mode, "tiers": tiers, "results": results}, ensure_ascii=False))

    finally:
        close_db(conn)


if __name__ == "__main__":
    main()
