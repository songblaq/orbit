# ORBIT — Operational Runtime for Background Intelligence Tasks

> Each task follows its orbit, scored by gravity, dispatched by momentum.

ORBIT is an autonomous task scheduler that uses R4 coordinate scoring to prioritize and dispatch background tasks. It replaces rigid cron schedules with intelligent, score-based dispatch — and works fully standalone with a local SQLite database.

---

## What ORBIT Does

- Maintains a **task registry** (SQLite or PostgreSQL) with tier, interval, and priority metadata
- Runs a **tick loop** that evaluates which tasks are due and dispatches them
- Scores tasks on 4 axes (R4) to determine urgency beyond simple time-based scheduling
- Operates in **shadow mode** by default: scores and logs decisions without actually dispatching, so you can build confidence before going live
- Supports multiple **dispatch backends**: direct script execution, macOS launchd, or optional integrations

---

## Quick Start

See [docs/QUICKSTART.md](docs/QUICKSTART.md) for a full 5-minute walkthrough. The short version:

```bash
git clone https://github.com/songblaq/orbit.git
cd orbit
chmod +x bin/orbit

# Use SQLite (simplest, no external dependencies)
export ORBIT_DB_BACKEND=sqlite
export ORBIT_HOME=~/.orbit

mkdir -p ~/.orbit
cp src/schema.sql ~/.orbit/
sqlite3 ~/.orbit/orbit.db < src/schema.sql

# Run migrations and check status
bin/orbit migrate
bin/orbit status

# Run a tick (shadow mode — scores tasks, does not dispatch)
bin/orbit tick
```

---

## R4 Coordinate System

Each task is scored across 4 dimensions. The score determines dispatch priority within a tier.

| Axis | Weight | Range | Description |
|------|--------|-------|-------------|
| `p_luca` | 0.35 | [0, 1] | Explicit human interest / urgency |
| `p_lord` | 0.25 | [0, 1] | AI autonomous judgment |
| `p_internal` | 0.25 | [0, 1] | System infrastructure importance |
| `p_depth` | 0.15 | [0, 1] | Processing complexity |

**Score** = `TIER_BONUS[tier] + weighted_sum(p_luca, p_lord, p_internal, p_depth)`

---

## Tiers

Tasks are assigned a tier that determines SLA guarantees and dispatch priority.

| Tier | Label | Bonus | SLA |
|------|-------|-------|-----|
| T1 | VITAL | 1.0 | hard — never miss |
| T2 | CRITICAL | 0.75 | hard — alert on miss |
| T3 | ROUTINE | 0.5 | soft — retry on next tick |
| T4 | DEFERRED | 0.25 | soft — best effort |
| T5 | BACKGROUND | 0.0 | none — idle time only |

---

## Modes

| Mode | Behavior |
|------|----------|
| **shadow** | Score and log only. No dispatch. Default for new installs. |
| **active** | Score, dispatch, track outcomes. Switch when confident. |

Switch modes via config:

```bash
bin/orbit config orbit_mode active
```

---

## Dispatch Backends

| Backend | Description | Requires |
|---------|-------------|---------|
| `script` | Direct subprocess execution of `run_command` | Nothing — works standalone |
| `launchd` | Trigger a macOS LaunchAgent via `launchctl kickstart` | macOS |
| `openclaw` | Delegate to OpenClaw cron runner | OpenClaw Gateway (optional) |
| `khala` | Publish task to a Khala message channel | ARIA Khala (optional) |

The `script` backend requires no external dependencies and is the right choice for standalone use.

---

## CLI Reference

```
orbit tick                  Run one scheduler tick
orbit dispatch              Manually dispatch tasks
  --tier 1,2,3              Filter by tier
  --dry-run                 Show what would be dispatched
orbit status                Show scheduler and task status
  --brief                   One-line summary
  --json                    JSON output
orbit gate check            Check activation gate conditions
orbit gate activate [tiers] Activate specific tiers
orbit migrate               Apply DB schema migrations
  --status                  Show applied migrations
orbit observer              Run cron meta-observer
orbit config [key] [value]  View or set config values
orbit dashboard             CLI dashboard view
orbit version               Version info
```

---

## Database

ORBIT supports SQLite (default for standalone use) and PostgreSQL.

```bash
# SQLite — no dependencies, data lives in a single file
export ORBIT_DB_BACKEND=sqlite
export ORBIT_HOME=~/.orbit           # directory containing orbit.db

# PostgreSQL — for multi-machine or production use
export ORBIT_DB_BACKEND=postgres
export ORBIT_PG_DSN="dbname=mydb host=localhost user=myuser"
```

The SQLite database file is created at `$ORBIT_HOME/orbit.db`.

---

## Scheduling ORBIT Itself

ORBIT needs to be triggered on a schedule (it does not daemonize itself).

**macOS LaunchAgent** — runs every 10 minutes:

```xml
<!-- ~/Library/LaunchAgents/com.orbit.tick.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.orbit.tick</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/env</string>
    <string>python3</string>
    <string>/path/to/orbit/src/orbit-tick.py</string>
  </array>
  <key>StartInterval</key><integer>600</integer>
  <key>EnvironmentVariables</key>
  <dict>
    <key>ORBIT_DB_BACKEND</key><string>sqlite</string>
    <key>ORBIT_HOME</key><string>/Users/you/.orbit</string>
  </dict>
</dict>
</plist>
```

**systemd** (Linux):

```ini
# ~/.config/systemd/user/orbit-tick.service
[Unit]
Description=ORBIT scheduler tick

[Service]
ExecStart=python3 /path/to/orbit/src/orbit-tick.py
Environment=ORBIT_DB_BACKEND=sqlite
Environment=ORBIT_HOME=/home/you/.orbit
```

```ini
# ~/.config/systemd/user/orbit-tick.timer
[Unit]
Description=Run ORBIT tick every 10 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=10min

[Install]
WantedBy=timers.target
```

**crontab**:

```
*/10 * * * * ORBIT_DB_BACKEND=sqlite ORBIT_HOME=~/.orbit python3 /path/to/orbit/src/orbit-tick.py
```

---

## Integration (Optional)

ORBIT works standalone out of the box. Integrations with AgentHive, ARIA, and OpenClaw are all optional. See [docs/INTEGRATION.md](docs/INTEGRATION.md).

---

## License

MIT
