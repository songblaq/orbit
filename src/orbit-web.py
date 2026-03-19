#!/usr/bin/env python3
"""
orbit-web — ORBIT Scheduler Web Dashboard
Single-file HTTP server with embedded HTML/CSS/JS.
Usage: python3 orbit-web.py [--port 4176] [--host 127.0.0.1]
"""

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

# ── DB bootstrap ─────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from orbit_db import get_db, get_config, set_config, BACKEND, close_db

P = "%s" if BACKEND == "postgres" else "?"

# ── R4 score ─────────────────────────────────────────────────────────────────
TIER_BONUS = {1: 1.0, 2: 0.75, 3: 0.5, 4: 0.25, 5: 0.0}

def r4_score(tier, p_luca, p_lord, p_internal, p_depth):
    b = TIER_BONUS.get(int(tier), 0.0)
    return round(b + 0.35 * (p_luca or 0) + 0.25 * (p_lord or 0)
                   + 0.25 * (p_internal or 0) + 0.15 * (p_depth or 0), 4)

# ── Data helpers ──────────────────────────────────────────────────────────────
def row_to_dict(row):
    if row is None:
        return None
    if BACKEND == "postgres":
        return dict(row)
    return dict(row)   # sqlite3.Row also supports dict()

def rows_to_list(rows):
    return [row_to_dict(r) for r in rows]

def _str(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)

def get_tasks(conn):
    rows = conn.execute(
        "SELECT * FROM task_defs ORDER BY tier ASC, id ASC"
    ).fetchall()
    result = []
    for r in rows:
        d = row_to_dict(r)
        d["r4_score"] = r4_score(d["tier"], d.get("p_luca"), d.get("p_lord"),
                                  d.get("p_internal"), d.get("p_depth"))
        d["last_dispatched_at"] = _str(d.get("last_dispatched_at"))
        result.append(d)
    return result

def get_runs(conn, limit=20):
    rows = conn.execute(f"""
        SELECT r.id, r.task_id, r.status, r.started_at, r.finished_at,
               r.duration_ms, r.error_message, d.tier
        FROM task_runs r
        LEFT JOIN task_defs d ON d.id = r.task_id
        ORDER BY r.started_at DESC LIMIT {P}
    """, (limit,)).fetchall()
    result = []
    for r in rows:
        d = row_to_dict(r)
        d["started_at"] = _str(d.get("started_at"))
        d["finished_at"] = _str(d.get("finished_at"))
        result.append(d)
    return result

def get_config_all(conn):
    rows = conn.execute(
        "SELECT key, value, updated_at, note FROM system_config ORDER BY key"
    ).fetchall()
    result = []
    for r in rows:
        d = row_to_dict(r)
        d["updated_at"] = _str(d.get("updated_at"))
        result.append(d)
    return result

def get_status(conn):
    tick = row_to_dict(conn.execute(
        "SELECT * FROM tick_log ORDER BY id DESC LIMIT 1"
    ).fetchone())
    if tick:
        tick["tick_at"] = _str(tick.get("tick_at"))
        tick["created_at"] = _str(tick.get("created_at"))

    # Postgres stores enabled/orbit_managed as boolean; SQLite as integer
    bool_true = "true" if BACKEND == "postgres" else "1"
    total   = conn.execute("SELECT COUNT(*) as c FROM task_defs").fetchone()["c"]
    enabled = conn.execute(f"SELECT COUNT(*) as c FROM task_defs WHERE enabled={bool_true}").fetchone()["c"]
    managed = conn.execute(f"SELECT COUNT(*) as c FROM task_defs WHERE orbit_managed={bool_true}").fetchone()["c"]
    runs    = conn.execute("SELECT COUNT(*) as c FROM task_runs").fetchone()["c"]
    mode    = get_config(conn, "orbit_mode", "shadow")
    tiers   = get_config(conn, "dispatch_tiers", "")
    tick_interval = get_config(conn, "tick_interval_ms", "600000")

    # 24h tick health
    if BACKEND == "postgres":
        tick_24h = conn.execute(
            "SELECT COUNT(*) as c FROM tick_log WHERE tick_at >= NOW() - INTERVAL '24 hours'"
        ).fetchone()["c"]
    else:
        tick_24h = conn.execute(
            "SELECT COUNT(*) as c FROM tick_log WHERE tick_at >= datetime('now','-24 hours')"
        ).fetchone()["c"]

    return {
        "total_tasks": total,
        "enabled": enabled,
        "managed": managed,
        "total_runs": runs,
        "mode": mode,
        "dispatch_tiers": tiers,
        "tick_interval_ms": tick_interval,
        "tick_24h": tick_24h,
        "latest_tick": tick,
        "backend": BACKEND,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }

# ── HTML template ─────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ORBIT — Scheduler Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Syne:wght@700;800&display=swap" rel="stylesheet">
<style>
  :root {
    --bg:        #0d1117;
    --surface:   #161b22;
    --surface2:  #1c2333;
    --border:    #21262d;
    --border2:   #30363d;
    --blue:      #58a6ff;
    --blue-dim:  #1f6feb;
    --green:     #3fb950;
    --green-dim: #196c2e;
    --yellow:    #d29922;
    --red:       #f85149;
    --orange:    #e3b341;
    --purple:    #bc8cff;
    --text:      #e6edf3;
    --text-muted:#7d8590;
    --text-dim:  #484f58;

    /* tier rail colors */
    --t1: #f85149;
    --t2: #ff7b72;
    --t3: #58a6ff;
    --t4: #d29922;
    --t5: #484f58;

    --mono: 'JetBrains Mono', monospace;
    --display: 'Syne', sans-serif;
    --radius: 6px;
    --radius-sm: 4px;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--mono);
    font-size: 13px;
    line-height: 1.5;
    min-height: 100vh;
  }

  /* ── Layout ── */
  .layout {
    max-width: 1440px;
    margin: 0 auto;
    padding: 0 24px 48px;
  }

  /* ── Header ── */
  .header {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 20px 0 18px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 24px;
  }
  .header-logo {
    font-family: var(--display);
    font-size: 22px;
    font-weight: 800;
    letter-spacing: 0.08em;
    color: var(--text);
    text-transform: uppercase;
  }
  .header-logo span { color: var(--blue); }
  .mode-badge {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    padding: 3px 8px;
    border-radius: 20px;
    border: 1px solid;
  }
  .mode-shadow { color: var(--yellow); border-color: var(--yellow); background: rgba(210,153,34,.08); }
  .mode-active { color: var(--green); border-color: var(--green); background: rgba(63,185,80,.08); }
  .header-meta {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 20px;
    color: var(--text-muted);
    font-size: 11px;
  }
  .header-meta .kv { display: flex; flex-direction: column; align-items: flex-end; gap: 1px; }
  .header-meta .k  { color: var(--text-dim); font-size: 9px; text-transform: uppercase; letter-spacing: .08em; }
  .header-meta .v  { color: var(--text); font-size: 12px; }
  .refresh-btn {
    background: var(--surface);
    border: 1px solid var(--border2);
    color: var(--text-muted);
    padding: 5px 12px;
    border-radius: var(--radius);
    cursor: pointer;
    font-family: var(--mono);
    font-size: 11px;
    letter-spacing: .04em;
    transition: border-color .15s, color .15s;
  }
  .refresh-btn:hover { border-color: var(--blue); color: var(--blue); }

  /* ── Stats row ── */
  .stats-row {
    display: grid;
    grid-template-columns: repeat(6, 1fr);
    gap: 12px;
    margin-bottom: 24px;
  }
  .stat-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 14px 16px;
    position: relative;
    overflow: hidden;
  }
  .stat-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: var(--blue);
  }
  .stat-card.green::before { background: var(--green); }
  .stat-card.yellow::before { background: var(--yellow); }
  .stat-card.purple::before { background: var(--purple); }
  .stat-card.red::before { background: var(--red); }
  .stat-label {
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: .1em;
    color: var(--text-dim);
    margin-bottom: 6px;
  }
  .stat-value {
    font-size: 24px;
    font-weight: 700;
    color: var(--text);
    line-height: 1;
  }
  .stat-value.small { font-size: 16px; }
  .stat-sub {
    font-size: 10px;
    color: var(--text-muted);
    margin-top: 4px;
  }

  /* ── Section ── */
  .section {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    margin-bottom: 16px;
    overflow: hidden;
  }
  .section-header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
    background: var(--surface2);
    cursor: pointer;
    user-select: none;
  }
  .section-title {
    font-family: var(--display);
    font-size: 12px;
    font-weight: 700;
    letter-spacing: .1em;
    text-transform: uppercase;
    color: var(--text);
  }
  .section-count {
    font-size: 10px;
    color: var(--text-muted);
    background: var(--border);
    padding: 2px 7px;
    border-radius: 20px;
  }
  .section-chevron {
    margin-left: auto;
    color: var(--text-dim);
    transition: transform .2s;
    font-size: 11px;
  }
  .section-chevron.open { transform: rotate(180deg); }
  .section-body { padding: 0; }
  .section-body.collapsed { display: none; }

  /* ── Tables ── */
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
  }
  thead th {
    padding: 8px 12px;
    text-align: left;
    font-size: 9px;
    font-weight: 600;
    letter-spacing: .1em;
    text-transform: uppercase;
    color: var(--text-dim);
    border-bottom: 1px solid var(--border);
    background: var(--surface2);
    white-space: nowrap;
    cursor: pointer;
    user-select: none;
  }
  thead th:hover { color: var(--blue); }
  thead th .sort-icon { margin-left: 4px; opacity: .4; }
  thead th.sorted .sort-icon { opacity: 1; color: var(--blue); }
  tbody tr {
    border-bottom: 1px solid var(--border);
    transition: background .1s;
  }
  tbody tr:last-child { border-bottom: none; }
  tbody tr:hover { background: rgba(88,166,255,.03); }
  td {
    padding: 8px 12px;
    vertical-align: middle;
    color: var(--text);
    white-space: nowrap;
  }
  td.wrap { white-space: normal; word-break: break-all; }

  /* ── Tier badges ── */
  .tier-badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 10px;
    font-weight: 700;
    padding: 2px 7px;
    border-radius: var(--radius-sm);
    border: 1px solid;
    letter-spacing: .04em;
  }
  .t1 { color: var(--t1); border-color: var(--t1); background: rgba(248,81,73,.08); }
  .t2 { color: var(--t2); border-color: var(--t2); background: rgba(255,123,114,.08); }
  .t3 { color: var(--t3); border-color: var(--t3); background: rgba(88,166,255,.08); }
  .t4 { color: var(--t4); border-color: var(--t4); background: rgba(210,153,34,.08); }
  .t5 { color: var(--t5); border-color: var(--t5); background: rgba(72,79,88,.08); }

  /* ── Status dots / badges ── */
  .status-pill {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 10px;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 20px;
  }
  .dot {
    width: 6px; height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .pill-success { color: var(--green); background: rgba(63,185,80,.1); }
  .pill-failed  { color: var(--red);   background: rgba(248,81,73,.1);  }
  .pill-running { color: var(--blue);  background: rgba(88,166,255,.1); }
  .pill-skipped, .pill-timeout { color: var(--yellow); background: rgba(210,153,34,.1); }
  .dot-success { background: var(--green); }
  .dot-failed  { background: var(--red);   }
  .dot-running { background: var(--blue); box-shadow: 0 0 6px var(--blue); }
  .dot-skipped, .dot-timeout { background: var(--yellow); }

  .enabled-on  { color: var(--green); }
  .enabled-off { color: var(--text-dim); }

  .backend-badge {
    font-size: 9px;
    padding: 2px 6px;
    border-radius: var(--radius-sm);
    background: var(--surface2);
    border: 1px solid var(--border2);
    color: var(--text-muted);
  }

  /* ── Score bar ── */
  .score-cell { display: flex; align-items: center; gap: 8px; }
  .score-bar-wrap {
    flex: 1;
    height: 4px;
    background: var(--border);
    border-radius: 2px;
    overflow: hidden;
    min-width: 40px;
  }
  .score-bar { height: 100%; border-radius: 2px; background: var(--blue); transition: width .3s; }
  .score-num { font-size: 11px; font-weight: 600; color: var(--text-muted); width: 32px; text-align: right; }

  /* ── Config editor ── */
  .config-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
    gap: 1px;
    background: var(--border);
  }
  .config-item {
    background: var(--surface);
    padding: 12px 16px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .config-key   { font-size: 11px; font-weight: 600; color: var(--blue); }
  .config-note  { font-size: 10px; color: var(--text-dim); margin-bottom: 4px; }
  .config-edit  {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .config-input {
    flex: 1;
    background: var(--bg);
    border: 1px solid var(--border2);
    border-radius: var(--radius-sm);
    color: var(--text);
    font-family: var(--mono);
    font-size: 12px;
    padding: 5px 8px;
    outline: none;
    transition: border-color .15s;
  }
  .config-input:focus { border-color: var(--blue); }
  .config-save {
    background: var(--blue-dim);
    border: none;
    color: var(--text);
    font-family: var(--mono);
    font-size: 11px;
    padding: 5px 12px;
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition: background .15s;
    white-space: nowrap;
  }
  .config-save:hover { background: var(--blue); }
  .config-save.saved { background: var(--green-dim); color: var(--green); }
  .config-updated { font-size: 9px; color: var(--text-dim); }

  /* ── Schedule info ── */
  .sched-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 16px;
    padding: 16px;
  }
  .sched-item .k { font-size: 9px; text-transform: uppercase; letter-spacing: .1em; color: var(--text-dim); margin-bottom: 4px; }
  .sched-item .v { font-size: 14px; font-weight: 600; color: var(--text); }

  /* ── Error/empty state ── */
  .empty {
    padding: 32px;
    text-align: center;
    color: var(--text-dim);
    font-size: 12px;
  }

  /* ── Spinner ── */
  .loading {
    display: inline-block;
    width: 10px; height: 10px;
    border: 1.5px solid var(--border2);
    border-top-color: var(--blue);
    border-radius: 50%;
    animation: spin .6s linear infinite;
    vertical-align: middle;
    margin-right: 6px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── Footer ── */
  .footer {
    padding: 16px 0 0;
    border-top: 1px solid var(--border);
    color: var(--text-dim);
    font-size: 10px;
    display: flex;
    justify-content: space-between;
  }

  /* ── Tooltip ── */
  [data-tip] { position: relative; cursor: default; }
  [data-tip]::after {
    content: attr(data-tip);
    position: absolute;
    bottom: calc(100% + 6px);
    left: 50%;
    transform: translateX(-50%);
    background: #2d333b;
    border: 1px solid var(--border2);
    color: var(--text);
    font-size: 10px;
    padding: 4px 8px;
    border-radius: var(--radius-sm);
    white-space: nowrap;
    pointer-events: none;
    opacity: 0;
    transition: opacity .15s;
    z-index: 100;
  }
  [data-tip]:hover::after { opacity: 1; }

  @media (max-width: 1024px) {
    .stats-row { grid-template-columns: repeat(3, 1fr); }
  }
  @media (max-width: 640px) {
    .stats-row { grid-template-columns: repeat(2, 1fr); }
    .header { flex-wrap: wrap; }
    .header-meta { margin-left: 0; width: 100%; }
  }
</style>
</head>
<body>
<div class="layout">

  <!-- HEADER -->
  <header class="header">
    <div class="header-logo">OR<span>BIT</span></div>
    <span class="mode-badge mode-shadow" id="modeBadge">shadow</span>
    <div class="header-meta">
      <div class="kv">
        <span class="k">Tick Interval</span>
        <span class="v" id="tickInterval">—</span>
      </div>
      <div class="kv">
        <span class="k">Last Tick</span>
        <span class="v" id="lastTick">—</span>
      </div>
      <div class="kv">
        <span class="k">Backend</span>
        <span class="v" id="dbBackend">—</span>
      </div>
      <div class="kv" id="serverTimeWrap">
        <span class="k">Server Time</span>
        <span class="v" id="serverTime">—</span>
      </div>
      <button class="refresh-btn" onclick="refreshAll()">
        <span id="refreshSpinner" style="display:none" class="loading"></span>Refresh
      </button>
    </div>
  </header>

  <!-- STATS ROW -->
  <div class="stats-row" id="statsRow">
    <div class="stat-card">
      <div class="stat-label">Task Defs</div>
      <div class="stat-value" id="statTotal">—</div>
      <div class="stat-sub">total registered</div>
    </div>
    <div class="stat-card green">
      <div class="stat-label">Enabled</div>
      <div class="stat-value" id="statEnabled">—</div>
      <div class="stat-sub">active tasks</div>
    </div>
    <div class="stat-card purple">
      <div class="stat-label">Orbit Managed</div>
      <div class="stat-value" id="statManaged">—</div>
      <div class="stat-sub">ORBIT dispatched</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Total Runs</div>
      <div class="stat-value" id="statRuns">—</div>
      <div class="stat-sub">all time</div>
    </div>
    <div class="stat-card yellow">
      <div class="stat-label">Mode</div>
      <div class="stat-value small" id="statMode">—</div>
      <div class="stat-sub">dispatch mode</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Dispatch Tiers</div>
      <div class="stat-value small" id="statTiers">—</div>
      <div class="stat-sub">active tier gates</div>
    </div>
  </div>

  <!-- TASK TABLE -->
  <div class="section" id="sectionTasks">
    <div class="section-header" onclick="toggleSection('tasks')">
      <span class="section-title">Task Registry</span>
      <span class="section-count" id="taskCount">—</span>
      <span class="section-chevron open" id="chevronTasks">&#9660;</span>
    </div>
    <div class="section-body" id="bodyTasks">
      <table id="taskTable">
        <thead>
          <tr>
            <th onclick="sortTasks('id')">ID <span class="sort-icon">&#8597;</span></th>
            <th onclick="sortTasks('tier')">Tier <span class="sort-icon">&#8597;</span></th>
            <th onclick="sortTasks('r4_score')">R4 Score <span class="sort-icon">&#8597;</span></th>
            <th>Backend</th>
            <th>AH Project</th>
            <th>Status</th>
            <th onclick="sortTasks('last_dispatched_at')">Last Run <span class="sort-icon">&#8597;</span></th>
            <th onclick="sortTasks('consecutive_successes')">Streak <span class="sort-icon">&#8597;</span></th>
          </tr>
        </thead>
        <tbody id="taskBody">
          <tr><td colspan="8" class="empty">Loading…</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- RECENT RUNS -->
  <div class="section" id="sectionRuns">
    <div class="section-header" onclick="toggleSection('runs')">
      <span class="section-title">Recent Runs</span>
      <span class="section-count" id="runsCount">—</span>
      <span class="section-chevron open" id="chevronRuns">&#9660;</span>
    </div>
    <div class="section-body" id="bodyRuns">
      <table id="runsTable">
        <thead>
          <tr>
            <th>Task ID</th>
            <th>Tier</th>
            <th>Status</th>
            <th>Duration</th>
            <th>Started At</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody id="runsBody">
          <tr><td colspan="6" class="empty">Loading…</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- CONFIG -->
  <div class="section" id="sectionConfig">
    <div class="section-header" onclick="toggleSection('config')">
      <span class="section-title">System Config</span>
      <span class="section-count" id="configCount">—</span>
      <span class="section-chevron open" id="chevronConfig">&#9660;</span>
    </div>
    <div class="section-body" id="bodyConfig">
      <div class="config-grid" id="configGrid">
        <div class="config-item"><div class="empty">Loading…</div></div>
      </div>
    </div>
  </div>

  <!-- SCHEDULE INFO -->
  <div class="section" id="sectionSched">
    <div class="section-header" onclick="toggleSection('sched')">
      <span class="section-title">Schedule Info</span>
      <span class="section-chevron open" id="chevronSched">&#9660;</span>
    </div>
    <div class="section-body" id="bodySched">
      <div class="sched-grid" id="schedGrid">
        <div class="empty">Loading…</div>
      </div>
    </div>
  </div>

  <footer class="footer">
    <span>ORBIT Scheduler Dashboard</span>
    <span id="footerTime">—</span>
  </footer>
</div>

<script>
// ── State ──────────────────────────────────────────────────────────────────
let tasksData = [];
let sortKey = 'tier';
let sortAsc = true;

// ── Fetch helpers ──────────────────────────────────────────────────────────
async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return r.json();
}

// ── Format helpers ─────────────────────────────────────────────────────────
function fmtDur(ms) {
  if (ms == null) return '—';
  if (ms < 1000) return ms + 'ms';
  if (ms < 60000) return (ms/1000).toFixed(1) + 's';
  return Math.floor(ms/60000) + 'm' + Math.floor((ms%60000)/1000) + 's';
}

function fmtDate(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    const now = Date.now();
    const diff = now - d.getTime();
    if (diff < 60000)  return Math.floor(diff/1000) + 's ago';
    if (diff < 3600000) return Math.floor(diff/60000) + 'm ago';
    if (diff < 86400000) return Math.floor(diff/3600000) + 'h ago';
    return d.toISOString().slice(0,16).replace('T',' ');
  } catch { return iso.slice(0,16); }
}

function fmtInterval(ms) {
  if (!ms) return '—';
  const n = parseInt(ms);
  if (n < 60000) return (n/1000) + 's';
  if (n < 3600000) return (n/60000) + 'min';
  if (n < 86400000) return (n/3600000) + 'h';
  return (n/86400000) + 'd';
}

function tierBadge(tier) {
  const labels = {1:'T1 VITAL',2:'T2 CRITICAL',3:'T3 ROUTINE',4:'T4 DEFER',5:'T5 BG'};
  const t = parseInt(tier);
  return `<span class="tier-badge t${t}">${labels[t]||'T'+t}</span>`;
}

function statusPill(st) {
  const s = (st||'').toLowerCase();
  return `<span class="status-pill pill-${s}"><span class="dot dot-${s}"></span>${st||'—'}</span>`;
}

function scoreBar(score) {
  const pct = Math.min(100, Math.round((score / 2.0) * 100));
  const col = score >= 1.5 ? 'var(--t1)' : score >= 1.0 ? 'var(--t2)' : score >= 0.7 ? 'var(--blue)' : score >= 0.4 ? 'var(--t4)' : 'var(--t5)';
  return `<div class="score-cell">
    <div class="score-bar-wrap"><div class="score-bar" style="width:${pct}%;background:${col}"></div></div>
    <span class="score-num">${score.toFixed(3)}</span>
  </div>`;
}

// ── Status ─────────────────────────────────────────────────────────────────
async function loadStatus() {
  const s = await fetchJSON('/api/status');

  // header
  const mode = s.mode || 'shadow';
  const badge = document.getElementById('modeBadge');
  badge.textContent = mode;
  badge.className = 'mode-badge mode-' + (mode === 'active' ? 'active' : 'shadow');

  const tick = s.latest_tick;
  document.getElementById('lastTick').textContent = tick ? fmtDate(tick.tick_at) : 'no tick yet';
  document.getElementById('tickInterval').textContent = fmtInterval(s.tick_interval_ms || 600000);
  document.getElementById('dbBackend').textContent = (s.backend || '—').toUpperCase();
  document.getElementById('serverTime').textContent = fmtDate(s.server_time);

  // stats
  document.getElementById('statTotal').textContent = s.total_tasks ?? '—';
  document.getElementById('statEnabled').textContent = s.enabled ?? '—';
  document.getElementById('statManaged').textContent = s.managed ?? '—';
  document.getElementById('statRuns').textContent = s.total_runs ?? '—';
  document.getElementById('statMode').textContent = mode;
  document.getElementById('statTiers').textContent = s.dispatch_tiers || '—';

  // schedule info
  const nextMs = parseInt(s.tick_interval_ms || 600000);
  const lastAt = tick ? new Date(tick.tick_at).getTime() : null;
  const nextEst = lastAt ? new Date(lastAt + nextMs).toISOString().slice(0,19).replace('T',' ') : '—';
  const tick24h = s.tick_24h ?? 0;
  const expected24h = Math.floor(86400000 / nextMs);
  const completePct = expected24h > 0 ? (tick24h / expected24h * 100).toFixed(1) : '—';

  document.getElementById('schedGrid').innerHTML = `
    <div class="sched-item"><div class="k">Tick Interval</div><div class="v">${fmtInterval(nextMs)}</div></div>
    <div class="sched-item"><div class="k">Next Est. Tick</div><div class="v">${nextEst}</div></div>
    <div class="sched-item"><div class="k">Ticks (24h)</div><div class="v">${tick24h} / ${expected24h} <small style="color:var(--text-muted)">(${completePct}%)</small></div></div>
    <div class="sched-item"><div class="k">Last Tick Mode</div><div class="v">${tick ? tick.mode : '—'}</div></div>
    <div class="sched-item"><div class="k">Tasks Evaluated</div><div class="v">${tick ? tick.tasks_evaluated : '—'}</div></div>
    <div class="sched-item"><div class="k">Tasks Dispatched</div><div class="v">${tick ? tick.tasks_dispatched : '—'}</div></div>
    <div class="sched-item"><div class="k">Dispatch Tiers</div><div class="v">${s.dispatch_tiers || 'none set'}</div></div>
    <div class="sched-item"><div class="k">DB Backend</div><div class="v">${(s.backend||'').toUpperCase()}</div></div>
  `;
}

// ── Tasks ──────────────────────────────────────────────────────────────────
async function loadTasks() {
  const data = await fetchJSON('/api/tasks');
  tasksData = data;
  document.getElementById('taskCount').textContent = data.length;
  renderTasks();
}

function sortTasks(key) {
  if (sortKey === key) sortAsc = !sortAsc;
  else { sortKey = key; sortAsc = (key !== 'r4_score'); }
  renderTasks();

  document.querySelectorAll('#taskTable thead th').forEach(th => th.classList.remove('sorted'));
  const ths = document.querySelectorAll('#taskTable thead th');
  const keyMap = ['id','tier','r4_score','','','','last_dispatched_at','consecutive_successes'];
  const idx = keyMap.indexOf(key);
  if (idx >= 0 && ths[idx]) ths[idx].classList.add('sorted');
}

function renderTasks() {
  const sorted = [...tasksData].sort((a, b) => {
    let va = a[sortKey], vb = b[sortKey];
    if (va == null) va = sortAsc ? '\uffff' : '';
    if (vb == null) vb = sortAsc ? '\uffff' : '';
    if (typeof va === 'number' && typeof vb === 'number')
      return sortAsc ? va - vb : vb - va;
    return sortAsc
      ? String(va).localeCompare(String(vb))
      : String(vb).localeCompare(String(va));
  });

  const tbody = document.getElementById('taskBody');
  if (!sorted.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty">No tasks found.</td></tr>';
    return;
  }

  tbody.innerHTML = sorted.map(t => {
    const enabled  = t.enabled  ? '<span class="enabled-on">&#10003; enabled</span>'  : '<span class="enabled-off">&#8212; disabled</span>';
    const managed  = t.orbit_managed ? ' <span class="backend-badge">orbit</span>' : '';
    const backend  = `<span class="backend-badge">${t.run_backend || 'openclaw'}</span>`;
    const ah       = t.agenthive_project ? `<span style="color:var(--purple);font-size:11px">${t.agenthive_project}</span>` : '<span style="color:var(--text-dim)">—</span>';
    const streak   = (t.consecutive_successes || 0);
    const streakHtml = streak > 0
      ? `<span style="color:var(--green)">&#10003; ${streak}</span>`
      : `<span style="color:var(--text-dim)">0</span>`;
    return `<tr>
      <td style="font-weight:500;color:var(--text)">${t.id}</td>
      <td>${tierBadge(t.tier)}</td>
      <td>${scoreBar(t.r4_score)}</td>
      <td>${backend}</td>
      <td>${ah}</td>
      <td>${enabled}${managed}</td>
      <td style="color:var(--text-muted);font-size:11px">${fmtDate(t.last_dispatched_at)}</td>
      <td>${streakHtml}</td>
    </tr>`;
  }).join('');
}

// ── Runs ───────────────────────────────────────────────────────────────────
async function loadRuns() {
  const data = await fetchJSON('/api/runs');
  document.getElementById('runsCount').textContent = data.length;
  const tbody = document.getElementById('runsBody');
  if (!data.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty">No runs yet (shadow mode).</td></tr>';
    return;
  }
  tbody.innerHTML = data.map(r => {
    const err = r.error_message
      ? `<span style="color:var(--red);font-size:10px" title="${r.error_message}">${r.error_message.slice(0,40)}${r.error_message.length>40?'…':''}</span>`
      : '<span style="color:var(--text-dim)">—</span>';
    return `<tr>
      <td style="font-weight:500">${r.task_id}</td>
      <td>${r.tier != null ? tierBadge(r.tier) : '—'}</td>
      <td>${statusPill(r.status)}</td>
      <td style="color:var(--text-muted)">${fmtDur(r.duration_ms)}</td>
      <td style="color:var(--text-muted);font-size:11px">${fmtDate(r.started_at)}</td>
      <td class="wrap" style="max-width:260px">${err}</td>
    </tr>`;
  }).join('');
}

// ── Config ─────────────────────────────────────────────────────────────────
async function loadConfig() {
  const data = await fetchJSON('/api/config');
  document.getElementById('configCount').textContent = data.length;
  const grid = document.getElementById('configGrid');
  grid.innerHTML = data.map(c => `
    <div class="config-item">
      <div class="config-key">${c.key}</div>
      ${c.note ? `<div class="config-note">${c.note}</div>` : ''}
      <div class="config-edit">
        <input class="config-input" id="cfg_${c.key}" value="${escHtml(c.value)}" data-key="${c.key}">
        <button class="config-save" id="savebtn_${c.key}" onclick="saveConfig('${c.key}')">Save</button>
      </div>
      <div class="config-updated" id="cfgupdated_${c.key}">${c.updated_at ? 'updated ' + fmtDate(c.updated_at) : ''}</div>
    </div>
  `).join('');
}

async function saveConfig(key) {
  const input = document.getElementById('cfg_' + key);
  const btn   = document.getElementById('savebtn_' + key);
  const label = document.getElementById('cfgupdated_' + key);
  if (!input) return;
  btn.disabled = true;
  try {
    const r = await fetch('/api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({key, value: input.value})
    });
    if (!r.ok) throw new Error(await r.text());
    btn.classList.add('saved');
    btn.textContent = 'Saved';
    label.textContent = 'saved just now';
    setTimeout(() => {
      btn.classList.remove('saved');
      btn.textContent = 'Save';
      btn.disabled = false;
    }, 2000);
  } catch (e) {
    btn.textContent = 'Error';
    btn.style.background = 'var(--red)';
    setTimeout(() => {
      btn.textContent = 'Save';
      btn.style.background = '';
      btn.disabled = false;
    }, 2000);
  }
}

// ── Collapse ───────────────────────────────────────────────────────────────
function toggleSection(id) {
  const body = document.getElementById('body' + id.charAt(0).toUpperCase() + id.slice(1));
  const chev = document.getElementById('chevron' + id.charAt(0).toUpperCase() + id.slice(1));
  if (!body) return;
  const collapsed = body.classList.toggle('collapsed');
  if (chev) chev.classList.toggle('open', !collapsed);
}

// ── Refresh ────────────────────────────────────────────────────────────────
async function refreshAll() {
  const spinner = document.getElementById('refreshSpinner');
  spinner.style.display = 'inline-block';
  try {
    await Promise.all([loadStatus(), loadTasks(), loadRuns(), loadConfig()]);
  } catch(e) {
    console.error('Refresh error:', e);
  } finally {
    spinner.style.display = 'none';
    document.getElementById('footerTime').textContent =
      'last updated ' + new Date().toISOString().slice(0,19).replace('T',' ') + ' UTC';
  }
}

// ── Utils ──────────────────────────────────────────────────────────────────
function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Boot ───────────────────────────────────────────────────────────────────
refreshAll();
// auto-refresh every 30s
setInterval(refreshAll, 30000);
</script>
</body>
</html>"""

# ── Request handler ───────────────────────────────────────────────────────────
class OrbitHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # quiet unless error
        if args and len(args) >= 2:
            code = str(args[1])
            if code.startswith(('4', '5')):
                super().log_message(fmt, *args)

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def _html(self, body: str):
        b = body.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _err(self, msg, status=500):
        self._json({'error': msg}, status)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/')

        if path in ('', '/'):
            self._html(HTML)
            return

        try:
            conn = get_db()
            if path == '/api/status':
                self._json(get_status(conn))
            elif path == '/api/tasks':
                self._json(get_tasks(conn))
            elif path == '/api/runs':
                self._json(get_runs(conn, 20))
            elif path == '/api/config':
                self._json(get_config_all(conn))
            else:
                self._err('not found', 404)
            close_db(conn)
        except Exception as e:
            traceback.print_exc()
            self._err(str(e))

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/')

        if path == '/api/config':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body)
                key = payload.get('key', '').strip()
                value = payload.get('value', '')
                if not key:
                    self._err('key required', 400)
                    return
                conn = get_db()
                set_config(conn, key, value)
                close_db(conn)
                self._json({'ok': True, 'key': key, 'value': value})
            except json.JSONDecodeError:
                self._err('invalid JSON', 400)
            except Exception as e:
                traceback.print_exc()
                self._err(str(e))
        else:
            self._err('not found', 404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='ORBIT Web Dashboard')
    parser.add_argument('--port', type=int, default=4176)
    parser.add_argument('--host', default='127.0.0.1')
    args = parser.parse_args()

    # smoke-test DB
    try:
        conn = get_db()
        n = conn.execute("SELECT COUNT(*) as c FROM task_defs").fetchone()["c"]
        close_db(conn)
        print(f"[orbit-web] DB OK — {n} task_defs ({BACKEND})")
    except Exception as e:
        print(f"[orbit-web] DB error: {e}", file=sys.stderr)
        sys.exit(1)

    server = HTTPServer((args.host, args.port), OrbitHandler)
    print(f"[orbit-web] Listening on http://{args.host}:{args.port}")
    print(f"[orbit-web] Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[orbit-web] Stopped.")


if __name__ == '__main__':
    main()
