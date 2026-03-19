#!/usr/bin/env python3
"""
ORBIT ↔ AgentHive 동기화 스크립트

기능:
1. AgentHive ready 태스크를 ORBIT task_defs에 등록 (없으면 생성)
2. ORBIT 실행 결과를 AgentHive Collab에 자동 기록
3. AgentHive 태스크 상태를 ORBIT agenthive_status에 캐싱

사용법:
  python3 orbit-hive-sync.py sync      # 전체 동기화
  python3 orbit-hive-sync.py status     # 동기화 상태 보기
  python3 orbit-hive-sync.py register   # AH 태스크 → ORBIT 등록만
"""
import json
import os
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from orbit_db import get_db, BACKEND

AGENTHIVE_HUB = Path.home() / ".agenthive" / "projects"
KHALA_COLLAB = Path.home() / ".aria" / "khala" / "channels" / "collab"

P = "%s" if BACKEND == "postgres" else "?"


def scan_agenthive_tasks():
    """AgentHive 전체 태스크 스캔."""
    tasks = []
    for proj_dir in sorted(AGENTHIVE_HUB.iterdir()):
        if proj_dir.name.startswith("Users") or not proj_dir.is_dir():
            continue
        tasks_dir = proj_dir / "tasks"
        if not tasks_dir.exists():
            continue
        for task_dir in sorted(tasks_dir.iterdir()):
            yaml_path = task_dir / "task.yaml"
            if not yaml_path.exists():
                # Follow symlinks
                if task_dir.is_symlink():
                    target = task_dir.resolve()
                    yaml_path = target / "task.yaml"
                if not yaml_path or not yaml_path.exists():
                    continue
            content = yaml_path.read_text(errors='replace')
            task = {}
            for line in content.split('\n'):
                if ':' in line:
                    key = line.split(':')[0].strip()
                    val = line.split(':', 1)[1].strip().strip('"').strip("'")
                    if key in ('id', 'status', 'priority', 'owner', 'title'):
                        task[key] = val
            task['project'] = proj_dir.name
            task['dir'] = str(task_dir)
            tasks.append(task)
    return tasks


def sync_status_to_orbit(conn):
    """AgentHive 태스크 상태를 ORBIT task_defs.agenthive_status에 캐싱."""
    tasks = scan_agenthive_tasks()
    updated = 0
    now = datetime.now(timezone.utc).isoformat()

    for task in tasks:
        ah_project = task.get('project', '')
        ah_id = task.get('id', '')
        ah_status = task.get('status', '')

        if not ah_project or not ah_status:
            continue

        # ORBIT task_defs에서 agenthive_project가 매칭되는 것들 업데이트
        conn.execute(f"""
            UPDATE task_defs
            SET agenthive_status = {P}, agenthive_synced_at = {P}
            WHERE agenthive_project = {P} AND agenthive_task_id = {P}
        """, (ah_status, now, ah_project, ah_id))

    conn.commit()
    return len(tasks)


def post_to_collab(project, content, msg_type="standup"):
    """ORBIT 결과를 AgentHive Collab(Khala)에 기록."""
    collab_dir = KHALA_COLLAB / project
    collab_dir.mkdir(parents=True, exist_ok=True)
    msg_file = collab_dir / "general.jsonl"

    msg = {
        "id": f"orbit-sync-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "channel": f"collab/{project}/general",
        "from": {"runtime": "orbit", "agent": "orbit-hive-sync"},
        "type": "message",
        "collab_type": msg_type,
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ttl": 0,
    }

    with open(msg_file, "a") as f:
        f.write(json.dumps(msg, ensure_ascii=False) + "\n")


def sync_runs_to_collab(conn):
    """최근 ORBIT 실행 결과를 해당 프로젝트 Collab에 기록."""
    # 최근 1시간 내 실행된 것만
    rows = conn.execute("""
        SELECT r.task_id, r.status, r.duration_ms, r.error_message, r.finished_at,
               d.agenthive_project
        FROM task_runs r
        JOIN task_defs d ON d.id = r.task_id
        WHERE r.finished_at > datetime('now', '-1 hour')
        ORDER BY r.finished_at DESC
        LIMIT 20
    """).fetchall() if BACKEND == "sqlite" else conn.execute("""
        SELECT r.task_id, r.status, r.duration_ms, r.error_message, r.finished_at,
               d.agenthive_project
        FROM task_runs r
        JOIN task_defs d ON d.id = r.task_id
        WHERE r.finished_at > NOW() - INTERVAL '1 hour'
        ORDER BY r.finished_at DESC
        LIMIT 20
    """).fetchall()

    posted = 0
    for r in rows:
        project = r["agenthive_project"]
        if not project:
            continue
        icon = "✅" if r["status"] == "success" else "❌"
        content = f"[orbit] {icon} {r['task_id']}: {r['status']} ({r['duration_ms']}ms)"
        if r["error_message"]:
            content += f" — {r['error_message'][:100]}"
        post_to_collab(project, content, "message")
        posted += 1

    return posted


def cmd_sync(conn):
    """전체 동기화."""
    print("[orbit-hive-sync] 동기화 시작")

    # 1. AH → ORBIT 상태 캐싱
    count = sync_status_to_orbit(conn)
    print(f"  AH → ORBIT: {count} tasks 상태 캐싱")

    # 2. ORBIT → Collab 실행 결과
    posted = sync_runs_to_collab(conn)
    print(f"  ORBIT → Collab: {posted} runs 기록")

    print("[orbit-hive-sync] 동기화 완료")


def cmd_status(conn):
    """동기화 상태."""
    ah_tasks = scan_agenthive_tasks()
    orbit_defs = conn.execute("SELECT COUNT(*) as c FROM task_defs").fetchone()["c"]
    mapped = conn.execute(f"SELECT COUNT(*) as c FROM task_defs WHERE agenthive_project IS NOT NULL AND agenthive_project != ''").fetchone()["c"]

    print(f"AgentHive 태스크: {len(ah_tasks)}")
    print(f"ORBIT task_defs: {orbit_defs}")
    print(f"매핑됨: {mapped}/{orbit_defs}")

    # Per-project
    print("\n프로젝트별:")
    by_proj = {}
    for t in ah_tasks:
        p = t.get('project', '?')
        by_proj.setdefault(p, {"total": 0, "doing": 0, "done": 0})
        by_proj[p]["total"] += 1
        if t.get("status") == "doing": by_proj[p]["doing"] += 1
        if t.get("status") == "done": by_proj[p]["done"] += 1

    for proj, s in sorted(by_proj.items()):
        print(f"  {proj:<20s} total={s['total']} doing={s['doing']} done={s['done']}")


def main():
    parser = argparse.ArgumentParser(description="ORBIT ↔ AgentHive Sync")
    parser.add_argument("command", choices=["sync", "status", "register"], default="status", nargs="?")
    args = parser.parse_args()

    conn = get_db()
    try:
        if args.command == "sync":
            cmd_sync(conn)
        elif args.command == "status":
            cmd_status(conn)
        elif args.command == "register":
            count = sync_status_to_orbit(conn)
            print(f"등록/캐싱: {count} tasks")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
