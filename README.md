# ORBIT — Operational Runtime for Background Intelligence Tasks

> Each task follows its orbit, scored by gravity, dispatched by momentum.

ORBIT is an autonomous task scheduler that uses R4 coordinate scoring to prioritize and dispatch tasks across heterogeneous runtimes. It replaces rigid cron schedules with intelligent, score-based dispatch.

## Quick Start

```bash
git clone https://github.com/songblaq/orbit.git
cd orbit
chmod +x bin/orbit

# Initialize database
bin/orbit migrate

# Check status
bin/orbit status

# Run a tick (shadow mode by default)
bin/orbit tick

# View config
bin/orbit config
```

## Architecture

```
AgentHive (WHAT)  →  ORBIT (WHEN)  →  ARIA (WHO/HOW)  →  Runtimes (DO)
                     ┌─────────────┐
                     │ R4 Scoring   │  p_luca (human interest)
                     │              │  p_lord (AI judgment)
                     │ Tick Loop    │  p_internal (system importance)
                     │              │  p_depth (complexity)
                     │ Multi-Backend│
                     │ Dispatch     │  script | openclaw | khala | launchd
                     └─────────────┘
```

## R4 Coordinate System

Each task is scored using 4 dimensions:

| Axis | Weight | Range | Description |
|------|--------|-------|-------------|
| `p_luca` | 0.35 | [0, 1] | Human explicit interest |
| `p_lord` | 0.25 | [0, 1] | AI autonomous judgment |
| `p_internal` | 0.25 | [0, 1] | System infrastructure importance |
| `p_depth` | 0.15 | [0, 1] | Processing complexity |

**Score** = `TIER_BONUS[tier] + W · P`

## Tiers

| Tier | Label | Bonus | SLA |
|------|-------|-------|-----|
| T1 | VITAL | 1.0 | hard |
| T2 | CRITICAL | 0.75 | hard |
| T3 | ROUTINE | 0.5 | soft |
| T4 | DEFERRED | 0.25 | soft |
| T5 | BACKGROUND | 0.0 | none |

## Modes

- **Shadow**: Score and log only. No dispatch. Build confidence data.
- **Active**: Score, dispatch, track. Progressive takeover from cron.

## Dispatch Backends

| Backend | Description | Dependency |
|---------|-------------|------------|
| `script` | Direct subprocess execution | None |
| `openclaw` | `openclaw cron run <id>` | OpenClaw Gateway |
| `khala` | Publish task to Khala channel | ARIA Khala |
| `launchd` | `launchctl kickstart` | macOS |

## CLI

```bash
orbit tick          # Run scheduler tick
orbit dispatch      # Manual dispatch (--tier, --dry-run)
orbit status        # Show ORBIT status
orbit gate check    # Run activation gate checks
orbit migrate       # Run DB migrations
orbit observer      # Cron meta-observer
orbit config        # View/set config
orbit dashboard     # CLI dashboard
orbit version       # Version info
```

## Integration

### With AgentHive
ORBIT reads AgentHive task status and skips blocked/done/review tasks.
```sql
-- task_defs columns
agenthive_project   -- AH project slug
agenthive_task_id   -- AH task ID
agenthive_status    -- Cached AH status
```

### With ARIA
ORBIT dispatches via Khala channels and can leverage Nyx agent routing.

### Standalone
ORBIT works without AgentHive or ARIA. Use `script` backend with `run_command` for self-contained scheduling.

## Database

Supports SQLite (default) and PostgreSQL.

```bash
# SQLite (default)
export ORBIT_DB=~/.orbit/orbit.db

# PostgreSQL
export ORBIT_BACKEND=postgres
export ORBIT_PG_SCHEMA=orbit
```

## LaunchAgent (macOS)

```xml
<!-- ~/Library/LaunchAgents/com.orbit.tick.plist -->
<dict>
  <key>Label</key><string>com.orbit.tick</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/path/to/orbit/src/orbit-tick.py</string>
  </array>
  <key>StartInterval</key><integer>600</integer>
</dict>
```

## License

MIT
