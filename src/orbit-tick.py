#!/usr/bin/env python3
"""
ORBIT Master Tick — WS-1 업데이트 (orbit-lock 통합)
실행 주기: */10
Week-1: shadow only. Week-2 이후: active 모드에서 dispatch 호출.
"""

import json
import os
import sys
import time
import importlib.util
from datetime import datetime, timezone

from orbit_db import (
    get_db, get_config, BACKEND, now_utc, SQLITE_PATH,
    try_advisory_lock, release_advisory_lock, close_db,
)

LOCK_KEY = "orbit-master-tick"
_DIR = os.path.dirname(os.path.abspath(__file__))

P = "%s" if BACKEND == "postgres" else "?"


def _load_orbit_lock():
    spec = importlib.util.spec_from_file_location(
        "orbit_lock", os.path.join(_DIR, "orbit-lock.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def compute_tier_score(task):
    """ℝ⁴ 좌표계 내적 기반 dispatch score.
    score = TIER_BONUS[tier] + W·P  (범위: 0.0 ~ 2.0)
    """
    W = {"w_luca": 0.35, "w_lord": 0.25, "w_internal": 0.25, "w_depth": 0.15}
    TIER_BONUS = {1: 1.0, 2: 0.75, 3: 0.5, 4: 0.25, 5: 0.0}
    tier = task.get("tier", 5)
    tier_bonus = TIER_BONUS.get(tier, 0.0)
    coord_score = (
        W["w_luca"]     * (task.get("p_luca")     or 0.0) +
        W["w_lord"]     * (task.get("p_lord")     or 0.5) +
        W["w_internal"] * (task.get("p_internal") or 0.0) +
        W["w_depth"]    * (task.get("p_depth")    or 0.0)
    )
    return round(tier_bonus + coord_score, 4)


def run_shadow_tick(conn, mode="shadow"):
    tick_start = time.time()
    tasks = conn.execute(
        "SELECT * FROM task_defs WHERE enabled ORDER BY tier ASC"
    ).fetchall()

    decisions = []
    for task in tasks:
        score = compute_tier_score(dict(task))
        decisions.append({
            "task_id": task["id"],
            "tier": task["tier"],
            "sla_type": task["sla_type"],
            "score": score,
            "would_dispatch": score >= 1.0,  # T1(1.7)/T2(1.435) dispatch, T3(0.9) 이하 skip
            "reason": f"tier={task['tier']}, sla={task['sla_type']}, score={score}",
        })
    decisions.sort(key=lambda d: d["score"], reverse=True)
    duration_ms = int((time.time() - tick_start) * 1000)

    if BACKEND == "postgres":
        conn.execute("""
            INSERT INTO tick_log(tick_at, mode, tasks_evaluated, tasks_dispatched, decision_log, duration_ms)
            VALUES (NOW(), %s, %s, 0, %s, %s)
        """, (mode, len(tasks), json.dumps(decisions, ensure_ascii=False), duration_ms))
    else:
        conn.execute("""
            INSERT INTO tick_log(tick_at, mode, tasks_evaluated, tasks_dispatched, decision_log, duration_ms)
            VALUES (?, ?, ?, 0, ?, ?)
        """, (now_utc(), mode, len(tasks), json.dumps(decisions, ensure_ascii=False), duration_ms))
    conn.commit()
    return decisions, duration_ms


def run_active_dispatch():
    """Week-2+: orbit-dispatch.py 호출."""
    import subprocess
    dispatch_path = os.path.join(_DIR, "orbit-dispatch.py")
    result = subprocess.run(
        [sys.executable, dispatch_path],
        capture_output=True, text=True, timeout=120
    )
    if result.stdout:
        print(result.stdout.strip())
    if result.returncode != 0:
        print(f"[tick] dispatch 오류: {result.stderr.strip()}", file=sys.stderr)


def main():
    conn = None

    if BACKEND == "postgres":
        conn = get_db()
        acquired, msg = try_advisory_lock(conn, LOCK_KEY)
        if not acquired:
            print(f"[ORBIT tick] Skip: {msg}", file=sys.stderr)
            close_db(conn)
            sys.exit(0)
        try:
            mode = get_config(conn, "orbit_mode", "shadow")
            decisions, duration_ms = run_shadow_tick(conn, mode)
            top = decisions[:5]

            print(f"[ORBIT tick] {now_utc()} | mode={mode} | {len(decisions)} tasks | {duration_ms}ms")
            print(f"  Top: {[d['task_id'] for d in top]}")

            if mode == "active":
                run_active_dispatch()

        except Exception as e:
            print(f"[ORBIT tick ERROR] {e}", file=sys.stderr)
            release_advisory_lock(conn, LOCK_KEY)
            close_db(conn)
            sys.exit(1)
        finally:
            release_advisory_lock(conn, LOCK_KEY)
            close_db(conn)
    else:
        # SQLite: file-based lock via orbit-lock.py
        orbit_lock = _load_orbit_lock()
        db_path = SQLITE_PATH
        lock = orbit_lock.OrbitLock(db_path, LOCK_KEY)
        acquired, msg = lock.acquire()
        if not acquired:
            print(f"[ORBIT tick] Skip: {msg}", file=sys.stderr)
            sys.exit(0)

        try:
            conn = get_db()

            # stale lock 정리
            cleaned = orbit_lock.cleanup_stale(db_path)
            if cleaned:
                print(f"[tick] stale lock {cleaned}건 정리")

            mode = get_config(conn, "orbit_mode", "shadow")
            decisions, duration_ms = run_shadow_tick(conn, mode)
            top = decisions[:5]

            print(f"[ORBIT tick] {now_utc()} | mode={mode} | {len(decisions)} tasks | {duration_ms}ms")
            print(f"  Top: {[d['task_id'] for d in top]}")

            if mode == "active":
                run_active_dispatch()

            close_db(conn)
        except Exception as e:
            print(f"[ORBIT tick ERROR] {e}", file=sys.stderr)
            sys.exit(1)
        finally:
            lock.release()


if __name__ == "__main__":
    main()
