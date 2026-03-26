#!/usr/bin/env python3
"""
ORBIT T1 Watchdog — WS-1/WS-2 업데이트
실행 주기: */5 (master tick lock bypass — 독립 실행)
WS-1: orbit-lock으로 tick lock 상태 조회
WS-2: watchdog_log 테이블에 모든 실행 증적 기록
"""

import json
import os
import sys
import time
import importlib.util
from datetime import datetime, timezone

from orbit_db import get_db, BACKEND, now_utc, SQLITE_PATH

TICK_LOCK_KEY = "orbit-master-tick"
T1_ALERT_THRESHOLD_MS = 20 * 60 * 1000
_DIR = os.path.dirname(os.path.abspath(__file__))

P = "%s" if BACKEND == "postgres" else "?"


def _load_orbit_lock():
    spec = importlib.util.spec_from_file_location(
        "orbit_lock", os.path.join(_DIR, "orbit-lock.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_t1_tasks(conn):
    t1_tasks = conn.execute(
        "SELECT * FROM task_defs WHERE tier = 1 AND enabled"
    ).fetchall()
    alerts = []

    for task in t1_tasks:
        last_run = conn.execute(f"""
            SELECT started_at FROM task_runs
            WHERE task_id = {P} AND status = 'success'
            ORDER BY started_at DESC LIMIT 1
        """, (task["id"],)).fetchone()

        if last_run is None:
            alerts.append({"task_id": task["id"], "level": "INFO",
                           "msg": "no run history (normal in shadow mode)"})
        else:
            try:
                last_dt = datetime.fromisoformat(
                    last_run["started_at"].replace("Z", "+00:00")
                )
                elapsed_ms = (datetime.now(timezone.utc) - last_dt).total_seconds() * 1000
                if elapsed_ms > T1_ALERT_THRESHOLD_MS:
                    alerts.append({"task_id": task["id"], "level": "ALERT",
                                   "elapsed_min": int(elapsed_ms / 60000),
                                   "msg": f"T1 overdue {int(elapsed_ms/60000)}min"})
            except Exception as e:
                alerts.append({"task_id": task["id"], "level": "WARN", "msg": str(e)})

    return [dict(t) for t in t1_tasks], alerts


def record_watchdog_log(conn, pid, lock_info, alerts, action, bypass_reason=None):
    """WS-2: 실행 증적을 watchdog_log에 기록."""
    conn.execute(f"""
        INSERT INTO watchdog_log(
            checked_at, owner_pid, lock_held, lock_owner_pid,
            lock_age_ms, bypass_reason, action, t1_task_ids, alert_count, notes
        ) VALUES ({P}, {P}, {P}, {P}, {P}, {P}, {P}, {P}, {P}, {P})
    """, (
        now_utc(), pid,
        True if lock_info.get("held") else False,
        lock_info.get("pid"),
        lock_info.get("age_ms"),
        bypass_reason, action,
        json.dumps([a["task_id"] for a in alerts], ensure_ascii=False),
        sum(1 for a in alerts if a.get("level") == "ALERT"),
        json.dumps(alerts, ensure_ascii=False),
    ))
    conn.commit()


def main():
    pid = os.getpid()
    orbit_lock = _load_orbit_lock()

    try:
        conn = get_db()

        # WS-1: tick lock 상태 조회 (bypass — 점검만, 획득 안 함)
        # db_path 인자는 SQLite 호환성을 위해 전달하되 postgres에서는 무시됨
        db_path = SQLITE_PATH
        tick_lock = orbit_lock.OrbitLock(db_path, TICK_LOCK_KEY)
        lock_info = tick_lock.get_info()

        bypass_reason = None
        action = "check"

        if lock_info.get("stale"):
            bypass_reason = f"stale_lock pid={lock_info.get('pid')} age={lock_info.get('age_ms')}ms"
            action = "bypass"
            # stale lock 정리
            orbit_lock.cleanup_stale(db_path)
            print(f"[watchdog] ⚠️  stale lock 감지 + 정리 (age={lock_info.get('age_ms')}ms)")

        # T1 점검
        t1_tasks, alerts = check_t1_tasks(conn)
        alert_count = sum(1 for a in alerts if a.get("level") == "ALERT")

        ts = now_utc()
        if alert_count > 0:
            action = "alert"
            print(f"[ORBIT watchdog] {ts} | ⚠️  T1 ALERT: {alert_count}건")
            for a in alerts:
                if a.get("level") == "ALERT":
                    print(f"  ALERT: {a['task_id']} — {a['msg']}")
        else:
            if action == "check":
                action = "ok"
            print(f"[ORBIT watchdog] {ts} | T1 OK ({len(t1_tasks)}개)"
                  + (f" | lock_held={lock_info.get('held')} pid={lock_info.get('pid')}" if lock_info.get("held") else ""))
            for a in alerts:
                if a.get("level") == "INFO":
                    print(f"  INFO: {a['task_id']} — {a['msg']}")

        # WS-2: 증적 기록
        record_watchdog_log(conn, pid, lock_info, alerts, action, bypass_reason)
        conn.close()

    except Exception as e:
        print(f"[ORBIT watchdog ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
