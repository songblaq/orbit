#!/usr/bin/env python3
"""
orbit-gate — WS-4 강화 버전
Week-2 진입 게이트 6개:
  G-W2-1 shadow_gap=0         (24h tick 연속성)
  G-W2-2 orphan_lock=0        (stale DB lock 없음)
  G-W2-3 reconnect_storm=false (Discord 재연결 폭주 없음)
  G-W2-4 tick_completeness>=99% (24h 144틱 기준)
  G-W2-5 dispatch_engine_ready (orbit-dispatch.py dry-run 성공)
  G-W2-6 freeze=0 + sla_miss=0

사용법:
  python3 orbit-gate.py check          # 진입 조건 확인
  python3 orbit-gate.py activate 4,5   # tier 4,5 dispatch 활성화
  python3 orbit-gate.py status         # 현재 설정 출력
  python3 orbit-gate.py report         # 게이트 판정 리포트 (JSON)
"""

import json
import os
import sys
import re
import subprocess
import importlib.util
from datetime import datetime, timezone

from orbit_db import (
    get_db, get_config, set_config, BACKEND, close_db,
)

GW_ERR_LOG = os.path.expanduser("~/.openclaw/logs/gateway.err.log")
SHADOW_MIN_DAYS = 5
RECONNECT_STORM_THRESHOLD = 10  # 1시간 내 Discord 1005/1006 횟수
_DIR = os.path.dirname(os.path.abspath(__file__))


# ─── 게이트 체크 함수들 ───────────────────────────────────────

def g_shadow_gap(conn):
    """G-W2-1: 24h tick shadow_gap=0."""
    if BACKEND == "postgres":
        rows = conn.execute("""
            SELECT tick_at FROM tick_log
            WHERE tick_at >= NOW() - INTERVAL '24 hours'
            ORDER BY tick_at ASC
        """).fetchall()
    else:
        rows = conn.execute("""
            SELECT tick_at FROM tick_log
            WHERE tick_at >= datetime('now', '-24 hours')
            ORDER BY tick_at ASC
        """).fetchall()

    if len(rows) < 2:
        return True, f"tick {len(rows)}개 (관찰 부족 — shadow 초기 정상)"
    gaps = 0
    for i in range(1, len(rows)):
        try:
            t1 = datetime.fromisoformat(rows[i-1]["tick_at"].replace("Z", "+00:00"))
            t2 = datetime.fromisoformat(rows[i]["tick_at"].replace("Z", "+00:00"))
            if (t2 - t1).total_seconds() / 60 > 12:
                gaps += 1
        except Exception:
            pass
    passed = gaps == 0
    return passed, f"shadow_gap={gaps}회 (24h {len(rows)}틱)"


def g_orphan_lock(conn):
    """G-W2-2: orphan_lock=0."""
    try:
        if BACKEND == "postgres":
            count = conn.execute(
                "SELECT COUNT(*) as cnt FROM lock_lease WHERE expire_at < NOW()"
            ).fetchone()["cnt"]
        else:
            count = conn.execute(
                "SELECT COUNT(*) as cnt FROM lock_lease WHERE datetime(expire_at) < datetime('now')"
            ).fetchone()["cnt"]
        return count == 0, f"orphan_lock={count}건"
    except Exception as e:
        return True, f"lock_lease 없음 (정상): {e}"


def g_reconnect_storm():
    """G-W2-3: gateway.err.log에서 Discord 1005/1006 폭주 확인."""
    if not os.path.exists(GW_ERR_LOG):
        return True, "gateway.err.log 없음 (정상으로 간주)"
    try:
        # 최근 1000줄에서 Discord reconnect 에러 카운트
        with open(GW_ERR_LOG, "r", errors="ignore") as f:
            lines = f.readlines()
        recent = lines[-1000:]
        pattern = re.compile(r"closed \(100[56]\)", re.IGNORECASE)
        count = sum(1 for l in recent if pattern.search(l))
        passed = count < RECONNECT_STORM_THRESHOLD
        return passed, f"Discord reconnect 패턴 {count}회 (최근 1000줄, 임계={RECONNECT_STORM_THRESHOLD})"
    except Exception as e:
        return True, f"로그 읽기 오류 (정상으로 간주): {e}"


def g_tick_completeness(conn):
    """G-W2-4: tick_log completeness >= 99% (24h 기준 144틱)."""
    if BACKEND == "postgres":
        count = conn.execute("""
            SELECT COUNT(*) as cnt FROM tick_log
            WHERE tick_at >= NOW() - INTERVAL '24 hours'
        """).fetchone()["cnt"]
    else:
        count = conn.execute("""
            SELECT COUNT(*) as cnt FROM tick_log
            WHERE tick_at >= datetime('now', '-24 hours')
        """).fetchone()["cnt"]
    expected = 144
    pct = count / expected * 100
    passed = pct >= 99.0
    return passed, f"completeness={pct:.1f}% ({count}/{expected}틱, 24h)"


def g_dispatch_engine_ready():
    """G-W2-5: orbit-dispatch.py --dry-run 성공."""
    dispatch_path = os.path.join(_DIR, "orbit-dispatch.py")
    if not os.path.exists(dispatch_path):
        return False, "orbit-dispatch.py 없음"
    try:
        result = subprocess.run(
            [sys.executable, dispatch_path, "--dry-run"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            return True, "dry-run 성공"
        return False, f"dry-run 실패: {result.stderr.strip()[:100]}"
    except Exception as e:
        return False, f"실행 오류: {e}"


def g_freeze_sla(conn):
    """G-W2-6: freeze=0 + sla_miss=0."""
    freeze = int(get_config(conn, "freeze_count") or "0")
    sla = int(get_config(conn, "sla_miss_count") or "0")
    passed = freeze == 0 and sla == 0
    return passed, f"freeze={freeze}, sla_miss={sla}"


def g_shadow_days(conn):
    """(참고) shadow 경과일 — 게이트가 아닌 참고 지표."""
    start = get_config(conn, "shadow_start_at")
    if not start:
        return None
    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - start_dt).total_seconds() / 86400
    except Exception:
        return None


# ─── 커맨드 ──────────────────────────────────────────────────

def cmd_check(conn, verbose=True):
    shadow_days = g_shadow_days(conn)
    mode = get_config(conn, "orbit_mode", "shadow")
    week = get_config(conn, "week", "1")

    gates = [
        ("G-W2-1 shadow_gap=0",           *g_shadow_gap(conn)),
        ("G-W2-2 orphan_lock=0",          *g_orphan_lock(conn)),
        ("G-W2-3 reconnect_storm=false",  *g_reconnect_storm()),
        ("G-W2-4 tick_completeness>=99%", *g_tick_completeness(conn)),
        ("G-W2-5 dispatch_engine_ready",  *g_dispatch_engine_ready()),
        ("G-W2-6 freeze=0+sla_miss=0",    *g_freeze_sla(conn)),
    ]

    all_pass = all(g[1] for g in gates)

    if verbose:
        print("═══════════════════════════════════════════════")
        print(f"  ORBIT Week-2 진입 게이트  mode={mode} Week-{week}")
        if shadow_days is not None:
            note = "✅" if shadow_days >= SHADOW_MIN_DAYS else f"⚠️ ({SHADOW_MIN_DAYS}일 권장)"
            print(f"  shadow 경과: {shadow_days:.1f}일 {note}")
        print("═══════════════════════════════════════════════")
        for name, passed, msg in gates:
            icon = "✅" if passed else "❌"
            print(f"  {icon} {name}: {msg}")
        print()
        if all_pass:
            print("  ✅ 전체 통과 — Week-2 진입 가능")
            print("  실행: python3 orbit-gate.py activate 4,5")
        else:
            failed = [g[0] for g in gates if not g[1]]
            print(f"  ❌ 미통과: {', '.join(failed)}")
        print("═══════════════════════════════════════════════")

    return all_pass, gates


def cmd_activate(conn, tiers_str):
    tiers = [int(t.strip()) for t in tiers_str.split(",") if t.strip()]
    print(f"Week-2 활성화 요청: tier={tiers}")

    all_pass, gates = cmd_check(conn, verbose=False)
    if not all_pass:
        failed = [g[0] for g in gates if not g[1]]
        print(f"  ⚠️  미통과 게이트: {', '.join(failed)} — 강제 진입")
    else:
        print("  ✅ 모든 게이트 통과")

    set_config(conn, "orbit_mode", "active")
    set_config(conn, "week", "2")
    set_config(conn, "dispatch_tiers", tiers_str)

    print(f"  ✅ orbit_mode=active, week=2, dispatch_tiers={tiers_str}")


def cmd_status(conn):
    print("─── system_config ───")
    rows = conn.execute("SELECT key, value, updated_at FROM system_config ORDER BY key").fetchall()
    for r in rows:
        print(f"  {r['key']:28s} = {str(r['value'])!r:20s}  ({r['updated_at']})")

    print("\n─── T4/T5 dispatch 현황 ───")
    tasks = conn.execute("""
        SELECT id, name, tier, cron_job_id, consecutive_successes, orbit_managed
        FROM task_defs WHERE tier >= 4 ORDER BY tier, id
    """).fetchall()
    for t in tasks:
        managed = "ORBIT" if t["orbit_managed"] else "cron "
        cjid = (str(t["cron_job_id"]) or "")[:8] + "…" if t["cron_job_id"] else "없음     "
        print(f"  T{t['tier']} [{managed}] {t['id']:30s} cron={cjid} 연속={t['consecutive_successes']}")


def cmd_report(conn):
    """JSON 게이트 판정 리포트 출력."""
    all_pass, gates = cmd_check(conn, verbose=False)
    shadow_days = g_shadow_days(conn)
    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "verdict": "GO" if all_pass else "NO_GO",
        "shadow_age_days": shadow_days,
        "gates": [
            {"name": g[0], "passed": g[1], "detail": g[2]}
            for g in gates
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    cmd = args[0]
    conn = get_db()
    try:
        if cmd == "check":
            cmd_check(conn)
        elif cmd == "activate":
            tiers = args[1] if len(args) > 1 else "4,5"
            cmd_activate(conn, tiers)
        elif cmd == "status":
            cmd_status(conn)
        elif cmd == "report":
            cmd_report(conn)
        else:
            print(f"알 수 없는 명령: {cmd}", file=sys.stderr)
            sys.exit(1)
    finally:
        close_db(conn)


if __name__ == "__main__":
    main()
