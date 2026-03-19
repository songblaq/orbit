#!/usr/bin/env python3
"""
orbit-status CLI — WS-3 확장 버전
사용법: python3 orbit-status.py [--json] [--top N]
WS-3 추가 필드: lock_owner/age, orphan_lock_count, shadow_gap,
               shadow_age_days, skip_reason_top, orbit_managed_count
"""

import json
import os
import sys
import time
import argparse
import importlib.util
from datetime import datetime, timezone

from orbit_db import (
    get_db, get_config, BACKEND, close_db,
)

_DIR = os.path.dirname(os.path.abspath(__file__))

P = "%s" if BACKEND == "postgres" else "?"


def _load_orbit_lock():
    spec = importlib.util.spec_from_file_location(
        "orbit_lock", os.path.join(_DIR, "orbit-lock.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def get_latest_tick(conn):
    return conn.execute("SELECT * FROM tick_log ORDER BY id DESC LIMIT 1").fetchone()


def get_task_summary(conn):
    return conn.execute("""
        SELECT tier, sla_type,
               COUNT(*) as cnt,
               SUM(CASE WHEN enabled THEN 1 ELSE 0 END) as active,
               SUM(CASE WHEN orbit_managed THEN 1 ELSE 0 END) as orbit_managed
        FROM task_defs GROUP BY tier, sla_type ORDER BY tier
    """).fetchall()


def get_recent_runs(conn, limit=5):
    if BACKEND == "postgres":
        return conn.execute("""
            SELECT r.task_id, r.status, r.started_at, r.duration_ms, d.tier
            FROM task_runs r
            JOIN task_defs d ON d.id = r.task_id
            ORDER BY r.started_at DESC LIMIT %s
        """, (limit,)).fetchall()
    else:
        return conn.execute("""
            SELECT r.task_id, r.status, r.started_at, r.duration_ms, d.tier
            FROM task_runs r
            JOIN task_defs d ON d.id = r.task_id
            ORDER BY r.started_at DESC LIMIT ?
        """, (limit,)).fetchall()


def get_shadow_gap(conn):
    """tick_log에서 10분 초과 gap 횟수 계산 (24h 기준)."""
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
        return 0, len(rows)
    gaps = 0
    for i in range(1, len(rows)):
        try:
            raw1, raw2 = rows[i-1]["tick_at"], rows[i]["tick_at"]
            t1 = raw1 if isinstance(raw1, datetime) else datetime.fromisoformat(str(raw1).replace("Z", "+00:00"))
            t2 = raw2 if isinstance(raw2, datetime) else datetime.fromisoformat(str(raw2).replace("Z", "+00:00"))
            diff_min = (t2 - t1).total_seconds() / 60
            if diff_min > 12:  # 10분 + 20% 버퍼
                gaps += 1
        except Exception:
            pass
    return gaps, len(rows)


def get_tick_completeness(conn):
    """24h 기준 tick_log completeness (기대 144틱 대비)."""
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
    expected = 144  # 24h ÷ 10min
    pct = round(count / expected * 100, 1)
    return count, expected, pct


def get_orphan_lock_count(conn):
    """만료된 DB lock_lease 수."""
    try:
        if BACKEND == "postgres":
            row = conn.execute("""
                SELECT COUNT(*) as cnt FROM lock_lease
                WHERE expire_at < NOW()
            """).fetchone()
        else:
            row = conn.execute("""
                SELECT COUNT(*) as cnt FROM lock_lease
                WHERE expire_at < datetime('now')
            """).fetchone()
        return row["cnt"] if row else 0
    except Exception:
        return 0


def get_shadow_age_days(conn):
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


def format_status(conn, top_n=5, as_json=False):
    # lock 상태 (WS-3) — only available via orbit-lock.py for SQLite
    lock_info = {}
    if BACKEND == "sqlite":
        orbit_lock = _load_orbit_lock()
        db_path = os.path.expanduser("~/.openclaw/data/orbit/orbit.db")
        lock = orbit_lock.OrbitLock(db_path, "orbit-master-tick")
        lock_info = lock.get_info()

    tick = get_latest_tick(conn)
    task_summary = get_task_summary(conn)
    recent_runs = get_recent_runs(conn, top_n)
    shadow_gap, tick_24h = get_shadow_gap(conn)
    tick_count, tick_expected, tick_pct = get_tick_completeness(conn)
    orphan_count = get_orphan_lock_count(conn)
    shadow_age = get_shadow_age_days(conn)

    # orbit_managed 집계
    managed = conn.execute(
        "SELECT COUNT(*) as cnt FROM task_defs WHERE orbit_managed"
    ).fetchone()["cnt"]
    total_enabled = conn.execute(
        "SELECT COUNT(*) as cnt FROM task_defs WHERE enabled"
    ).fetchone()["cnt"]

    # top scores
    top_scores = []
    if tick and tick["decision_log"]:
        dl = tick["decision_log"]
        decisions = json.loads(dl) if isinstance(dl, str) else dl
        top_scores = decisions[:top_n]

    mode = get_config(conn, "orbit_mode", "shadow")
    week = get_config(conn, "week", "1")

    if as_json:
        return json.dumps({
            "mode": mode, "week": week,
            "latest_tick": dict(tick) if tick else None,
            "top_scores": top_scores,
            "task_summary": [dict(r) for r in task_summary],
            "recent_runs": [dict(r) for r in recent_runs],
            "lock": lock_info,
            "orphan_lock_count": orphan_count,
            "shadow_gap_24h": shadow_gap,
            "tick_count_24h": tick_count,
            "tick_completeness_pct": tick_pct,
            "shadow_age_days": shadow_age,
            "orbit_managed": managed,
            "cron_managed": total_enabled - managed,
        }, ensure_ascii=False, indent=2, default=str)

    lines = []
    lines.append("═══════════════════════════════════════════════")
    lines.append(f"  ORBIT Status  mode={mode}  Week-{week}")
    lines.append("═══════════════════════════════════════════════")

    # Last Tick
    if tick:
        lines.append(f"\n[Last Tick]")
        lines.append(f"  at:          {tick['tick_at']}")
        lines.append(f"  mode:        {tick['mode']}")
        lines.append(f"  evaluated:   {tick['tasks_evaluated']} tasks | {tick['duration_ms']}ms")
    else:
        lines.append("\n[Last Tick] — no tick yet")

    # WS-3: Lock 상태
    lines.append(f"\n[Lock Status]")
    if lock_info.get("held"):
        stale_tag = " ⚠️ STALE" if lock_info.get("stale") else ""
        lines.append(f"  held:        YES — PID {lock_info.get('pid')} age={lock_info.get('age_ms')}ms{stale_tag}")
    else:
        lines.append(f"  held:        NO")
    lines.append(f"  orphan_locks: {orphan_count} {'⚠️' if orphan_count > 0 else '✅'}")

    # WS-3: Shadow 관찰 지표
    lines.append(f"\n[Shadow Observation]")
    age_str = f"{shadow_age:.1f}일" if shadow_age is not None else "unknown"
    lines.append(f"  shadow_age:  {age_str}")
    lines.append(f"  tick_24h:    {tick_count}/{tick_expected} ({tick_pct}%) {'✅' if tick_pct >= 99 else '⚠️'}")
    lines.append(f"  shadow_gap:  {shadow_gap}회 {'✅' if shadow_gap == 0 else '⚠️'}")

    # Task Registry
    lines.append(f"\n[Task Registry]  orbit={managed} / cron={total_enabled - managed}")
    tier_labels = {1: "T1 VITAL", 2: "T2 CRITICAL", 3: "T3 ROUTINE", 4: "T4 DEFERRED", 5: "T5 BACKGROUND"}
    for row in task_summary:
        label = tier_labels.get(row["tier"], f"T{row['tier']}")
        om = row["orbit_managed"]
        lines.append(f"  {label:16s} | {row['sla_type']:4s} | {row['active']}/{row['cnt']} active | orbit={om}")

    # Top dispatch
    if top_scores:
        lines.append(f"\n[Top {len(top_scores)} Dispatch Order]")
        for i, d in enumerate(top_scores, 1):
            flag = "→" if d.get("would_dispatch") else "·"
            lines.append(f"  {i}. {flag} {d['task_id']:38s} score={d['score']}")

    # Recent Runs
    if recent_runs:
        lines.append(f"\n[Recent Runs]")
        for r in recent_runs:
            raw_ts = r["started_at"]
            ts = (raw_ts.strftime("%Y-%m-%dT%H:%M:%S") if isinstance(raw_ts, datetime) else str(raw_ts)[:19]) if raw_ts else "?"
            dur = f"{r['duration_ms']}ms" if r["duration_ms"] else "-"
            lines.append(f"  [{r['status']:7s}] T{r['tier']} {r['task_id']:32s} {ts} {dur}")
    else:
        lines.append(f"\n[Recent Runs] — no runs yet (shadow mode)")

    lines.append("\n═══════════════════════════════════════════════")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="ORBIT status CLI (WS-3)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()

    try:
        conn = get_db()
        print(format_status(conn, top_n=args.top, as_json=args.json))
        close_db(conn)
    except Exception as e:
        print(f"[orbit-status ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
