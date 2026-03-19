#!/usr/bin/env python3
"""
orbit-cron-observer — Unified cron meta-observer
Scans OpenClaw crons, macOS LaunchAgents, and ORBIT task_defs.
Usage: python3 orbit-cron-observer.py
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

# ── paths ────────────────────────────────────────────────────────────────────
CRON_JOBS_PATH  = os.path.expanduser("~/.openclaw/cron/jobs.json")
LAUNCH_AGENTS   = os.path.expanduser("~/Library/LaunchAgents")
LA_PREFIXES     = ("com.aria.", "com.openclaw.")

# ── helpers ──────────────────────────────────────────────────────────────────

def now_utc():
    return datetime.now(timezone.utc)


def ms_ago(ms):
    if not ms:
        return "never"
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    diff = (now_utc() - dt).total_seconds()
    if diff < 3600:
        return f"{int(diff // 60)}m ago"
    if diff < 86400:
        return f"{int(diff // 3600)}h ago"
    return f"{int(diff // 86400)}d ago"


# ── section 1: OpenClaw crons ─────────────────────────────────────────────────

def scan_openclaw_crons():
    result = {"enabled": [], "disabled": [], "error": [], "raw": []}
    try:
        with open(CRON_JOBS_PATH) as f:
            data = json.load(f)
    except FileNotFoundError:
        return result, f"NOT FOUND: {CRON_JOBS_PATH}"
    except Exception as e:
        return result, str(e)

    for job in data.get("jobs", []):
        entry = {
            "id":     job.get("id", "?")[:8],
            "name":   job.get("name", "?"),
            "enabled": job.get("enabled", False),
            "errors": job.get("state", {}).get("consecutiveErrors", 0),
            "last_status": job.get("state", {}).get("lastStatus", "?"),
            "last_run_ms": job.get("state", {}).get("lastRunAtMs"),
            "last_error": job.get("state", {}).get("lastError"),
            "disabled_reason": job.get("_disabled_reason"),
            "schedule": job.get("schedule", {}),
        }
        result["raw"].append(entry)
        if not entry["enabled"]:
            result["disabled"].append(entry)
        elif entry["errors"] >= 2 or entry["last_status"] == "error":
            result["error"].append(entry)
        else:
            result["enabled"].append(entry)

    return result, None


# ── section 2: macOS LaunchAgents ────────────────────────────────────────────

def _launchctl_loaded():
    """Return set of labels currently loaded in launchctl."""
    try:
        out = subprocess.check_output(["launchctl", "list"], text=True, stderr=subprocess.DEVNULL)
        loaded = set()
        for line in out.splitlines():
            parts = line.strip().split("\t")
            if len(parts) == 3:
                loaded.add(parts[2])
        return loaded
    except Exception:
        return set()


def scan_launch_agents():
    loaded = _launchctl_loaded()
    agents = []
    try:
        for fname in sorted(os.listdir(LAUNCH_AGENTS)):
            if not any(fname.startswith(p) for p in LA_PREFIXES):
                continue
            label = fname.replace(".plist", "")
            is_loaded = label in loaded
            agents.append({"label": label, "loaded": is_loaded, "file": fname})
    except FileNotFoundError:
        pass
    return agents


# ── section 3: ORBIT task_defs ────────────────────────────────────────────────

def scan_orbit_tasks():
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from orbit_db import get_db, close_db, BACKEND
    except ImportError as e:
        return None, f"orbit_db import failed: {e}"

    try:
        conn = get_db()
        P = "%s" if BACKEND == "postgres" else "?"
        rows = conn.execute("""
            SELECT tier, run_backend, enabled, orbit_managed, COUNT(*) as cnt
            FROM task_defs
            GROUP BY tier, run_backend, enabled, orbit_managed
            ORDER BY tier, run_backend
        """).fetchall()
        summary = [dict(r) for r in rows]

        # total counts
        totals = conn.execute("""
            SELECT
              COUNT(*) as total,
              SUM(CASE WHEN enabled THEN 1 ELSE 0 END) as active,
              SUM(CASE WHEN NOT enabled THEN 1 ELSE 0 END) as inactive,
              SUM(CASE WHEN orbit_managed THEN 1 ELSE 0 END) as orbit_managed
            FROM task_defs
        """).fetchone()

        close_db(conn)
        return {"summary": summary, "totals": dict(totals)}, None
    except Exception as e:
        return None, str(e)


# ── duplicate detection ───────────────────────────────────────────────────────

_PURPOSE_KEYWORDS = {
    "heartbeat":    ["heartbeat", "poller"],
    "security":     ["security", "audit"],
    "backup":       ["backup", "pg-backup", "memory-backup"],
    "sessions":     ["sessions", "session-cleanup"],
    "watchdog":     ["watchdog", "gateway-watchdog"],
    "skill-eval":   ["skill-eval", "skill_eval"],
    "agenthive":    ["agenthive"],
}

def detect_duplicates(oc_raw, la_agents):
    dupes = []
    for purpose, keywords in _PURPOSE_KEYWORDS.items():
        matches = []
        for job in oc_raw:
            if any(k in job["name"].lower() for k in keywords):
                matches.append(f"openclaw:{job['name']}")
        for ag in la_agents:
            if any(k in ag["label"].lower() for k in keywords):
                matches.append(f"launchagent:{ag['label']}")
        if len(matches) >= 2:
            dupes.append({"purpose": purpose, "entries": matches})
    return dupes


# ── issue flags ───────────────────────────────────────────────────────────────

def collect_issues(oc, la_agents):
    issues = []

    # OpenClaw: disabled with errors
    for job in oc.get("disabled", []):
        if job["errors"] > 0:
            issues.append(f"[OC] '{job['name']}' disabled but has {job['errors']} consecutive errors — {job.get('last_error', '')}")

    # OpenClaw: enabled jobs with errors
    for job in oc.get("error", []):
        issues.append(f"[OC] '{job['name']}' ENABLED but in error state (errors={job['errors']}, last={job.get('last_error', '?')})")

    # OpenClaw: disabled with _disabled_reason containing Unknown Channel
    for job in oc.get("disabled", []):
        if job.get("disabled_reason") and "Unknown Channel" in job["disabled_reason"]:
            issues.append(f"[OC] '{job['name']}' disabled: Unknown Channel — delivery target invalid")

    # LaunchAgents: plist exists but not loaded
    for ag in la_agents:
        if not ag["loaded"]:
            issues.append(f"[LA] '{ag['label']}' plist exists but NOT loaded in launchctl")

    return issues


# ── report ────────────────────────────────────────────────────────────────────

def print_report(oc, oc_err, la_agents, orbit, orbit_err, dupes, issues):
    sep = "─" * 54
    print("═" * 54)
    print("  ORBIT CRON OBSERVER — Unified Status Report")
    print(f"  {now_utc().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("═" * 54)

    # ── OpenClaw Crons ──
    print(f"\n[1] OpenClaw Crons  ({CRON_JOBS_PATH})")
    print(sep)
    if oc_err:
        print(f"  ERROR: {oc_err}")
    else:
        total = len(oc["enabled"]) + len(oc["disabled"]) + len(oc["error"])
        print(f"  total={total}  enabled={len(oc['enabled'])}  disabled={len(oc['disabled'])}  error={len(oc['error'])}")

        if oc["enabled"]:
            print("\n  Enabled:")
            for j in oc["enabled"]:
                print(f"    + {j['name']:42s}  last={ms_ago(j['last_run_ms'])}")

        if oc["error"]:
            print("\n  Error (enabled but failing):")
            for j in oc["error"]:
                print(f"    ! {j['name']:42s}  errors={j['errors']}  last={ms_ago(j['last_run_ms'])}")

        if oc["disabled"]:
            print("\n  Disabled:")
            for j in oc["disabled"]:
                reason = f"  [{j['disabled_reason']}]" if j.get("disabled_reason") else ""
                print(f"    - {j['name']:42s}  last={ms_ago(j['last_run_ms'])}{reason}")

    # ── LaunchAgents ──
    print(f"\n[2] macOS LaunchAgents  (com.aria.* / com.openclaw.*)")
    print(sep)
    loaded_count = sum(1 for a in la_agents if a["loaded"])
    print(f"  total={len(la_agents)}  loaded={loaded_count}  not_loaded={len(la_agents) - loaded_count}")
    for ag in la_agents:
        status = "LOADED" if ag["loaded"] else "NOT LOADED"
        mark = "+" if ag["loaded"] else "!"
        print(f"    {mark} [{status:10s}] {ag['label']}")

    # ── ORBIT task_defs ──
    print(f"\n[3] ORBIT task_defs")
    print(sep)
    if orbit_err:
        print(f"  ERROR: {orbit_err}")
    elif orbit:
        t = orbit["totals"]
        print(f"  total={t.get('total',0)}  active={t.get('active',0)}  inactive={t.get('inactive',0)}  orbit_managed={t.get('orbit_managed',0)}")
        tier_labels = {1:"T1-VITAL", 2:"T2-CRITICAL", 3:"T3-ROUTINE", 4:"T4-DEFERRED", 5:"T5-BACKGROUND"}
        by_tier = {}
        for row in orbit["summary"]:
            tier = row.get("tier") or row.get("TIER") or 0
            key = tier_labels.get(tier, f"T{tier}")
            if key not in by_tier:
                by_tier[key] = {"active": 0, "inactive": 0, "backends": set(), "orbit_managed": 0}
            cnt = row.get("cnt") or row.get("CNT") or 0
            enabled = row.get("enabled") or row.get("ENABLED") or False
            om = row.get("orbit_managed") or row.get("ORBIT_MANAGED") or False
            backend = row.get("run_backend") or row.get("RUN_BACKEND") or "?"
            if enabled:
                by_tier[key]["active"] += cnt
            else:
                by_tier[key]["inactive"] += cnt
            if om:
                by_tier[key]["orbit_managed"] += cnt
            by_tier[key]["backends"].add(backend)
        for label, v in sorted(by_tier.items()):
            backends = ",".join(sorted(v["backends"]))
            print(f"    {label:14s}  active={v['active']}  inactive={v['inactive']}  orbit={v['orbit_managed']}  backends=[{backends}]")

    # ── Duplicates ──
    print(f"\n[4] Duplicate Detection")
    print(sep)
    if dupes:
        for d in dupes:
            print(f"  DUPE purpose={d['purpose']}:")
            for e in d["entries"]:
                print(f"       {e}")
    else:
        print("  No duplicates detected.")

    # ── Issues ──
    print(f"\n[5] Issues & Flags")
    print(sep)
    if issues:
        for iss in issues:
            print(f"  {iss}")
    else:
        print("  No issues detected.")

    print("\n" + "═" * 54)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    oc, oc_err = scan_openclaw_crons()
    la_agents   = scan_launch_agents()
    orbit, orbit_err = scan_orbit_tasks()
    dupes  = detect_duplicates(oc.get("raw", []), la_agents)
    issues = collect_issues(oc, la_agents)
    print_report(oc, oc_err, la_agents, orbit, orbit_err, dupes, issues)


if __name__ == "__main__":
    main()
