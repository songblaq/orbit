# ORBIT Integration Guide

ORBIT works fully standalone. Every integration described here is **optional**. You can use any combination, or none at all.

---

## Integration Overview

| System | What ORBIT gains | Required? |
|--------|-----------------|-----------|
| AgentHive | Task status guard, project mapping | No |
| ARIA / Khala | Message-based dispatch to remote runtimes | No |
| OpenClaw | Delegate to OpenClaw cron runner | No |
| launchd (macOS) | Trigger LaunchAgents as dispatch targets | No |
| systemd (Linux) | Trigger systemd units as dispatch targets | No |
| crontab | Use cron to trigger ORBIT ticks | No |

---

## With AgentHive

AgentHive is a task tracking system. When integrated, ORBIT checks AgentHive task status before dispatching — skipping tasks that are blocked, under review, or already complete.

### What it does

ORBIT reads three extra columns on `task_defs`:

```sql
agenthive_project   TEXT    -- AgentHive project slug (e.g. 'ops', 'research-lab')
agenthive_task_id   TEXT    -- AgentHive task ID for this task
agenthive_status    TEXT    -- Cached AgentHive status (refreshed each tick)
```

Before dispatching a task, ORBIT checks `agenthive_status`. If the status is `blocked`, `done`, or `review`, the task is skipped that tick.

### Setup

These columns are added by migration v4 (already included in `orbit-migrate`):

```bash
bin/orbit migrate
```

Map a task to an AgentHive project:

```sql
UPDATE task_defs
SET agenthive_project = 'my-project',
    agenthive_task_id = 'task-abc-123'
WHERE id = 'my-task-id';
```

### Project mapping

ORBIT can auto-map tasks to AgentHive projects by ID prefix pattern. Update `run_v4()` in `orbit-migrate.py` with your own patterns, or set `agenthive_project` directly on each row.

### Without AgentHive

If `agenthive_project` and `agenthive_task_id` are NULL (the default), ORBIT ignores the AgentHive check entirely and dispatches based on score and tier alone.

---

## With ARIA / Khala

ARIA is a multi-runtime agent orchestration system. Khala is its messaging bus. When integrated, ORBIT can dispatch tasks as Khala messages — letting remote runtimes (agents, services) pick them up and execute them.

### How it works

Set `run_backend = 'khala'` on a task definition:

```sql
UPDATE task_defs
SET run_backend = 'khala',
    run_command = 'channel-name'   -- Khala channel to publish to
WHERE id = 'my-task-id';
```

When ORBIT dispatches this task, it publishes a message to the specified Khala channel. A Khala subscriber on that channel handles actual execution.

### Nyx routing (optional)

If your ARIA setup includes Nyx agent routing, you can route tasks to specific agents by publishing to an agent-specific channel (e.g. `nyx-ops/inbox`). ORBIT itself has no knowledge of Nyx — it just publishes; routing is handled by the Khala subscriber.

### Without ARIA

Tasks with `run_backend = 'script'` or `run_backend = 'launchd'` do not require ARIA at all. ARIA is only needed if you want message-based remote dispatch.

---

## With OpenClaw

OpenClaw is an agent gateway that manages its own cron job registry. When integrated, ORBIT can delegate execution to OpenClaw's cron runner instead of running tasks directly.

### How it works

Set `run_backend = 'openclaw'` and provide the OpenClaw cron job ID:

```sql
UPDATE task_defs
SET run_backend = 'openclaw',
    cron_job_id = 'your-openclaw-cron-job-uuid'
WHERE id = 'my-task-id';
```

ORBIT will call `openclaw cron run <cron_job_id>` when dispatching.

### ORBIT as a cron meta-manager

ORBIT can also observe OpenClaw's `jobs.json` (or similar cron registries) to detect duplicate scheduling and report unified status. The `orbit observer` command performs this scan.

```bash
bin/orbit observer
```

This is purely observational — ORBIT does not modify external cron registries.

### Without OpenClaw

Use `run_backend = 'script'` to run tasks directly. No OpenClaw dependency.

---

## With Any Cron System

ORBIT does not daemonize. It expects to be triggered periodically by an external scheduler. The tick itself is idempotent — running it more frequently than your shortest task interval is safe.

### macOS launchd

ORBIT can be triggered by a LaunchAgent. It can also dispatch tasks by triggering *other* LaunchAgents.

**Triggering ORBIT via launchd:**

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

```bash
launchctl load ~/Library/LaunchAgents/com.orbit.tick.plist
```

**Dispatching tasks via launchd:**

Set `run_backend = 'launchd'` and `run_command` to the LaunchAgent label:

```sql
UPDATE task_defs
SET run_backend = 'launchd',
    run_command  = 'com.myapp.backup'
WHERE id = 'my-backup-task';
```

ORBIT will call `launchctl kickstart gui/$UID/com.myapp.backup` when dispatching.

### Linux systemd

**Triggering ORBIT via systemd timer:**

```ini
# ~/.config/systemd/user/orbit-tick.service
[Unit]
Description=ORBIT scheduler tick

[Service]
Type=oneshot
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

```bash
systemctl --user enable --now orbit-tick.timer
```

**Dispatching tasks via systemd:**

Set `run_backend = 'script'` and invoke `systemctl` as the command:

```sql
UPDATE task_defs
SET run_backend = 'script',
    run_command  = 'systemctl --user start myapp-backup.service'
WHERE id = 'my-backup-task';
```

### crontab

The simplest setup. Trigger ORBIT from crontab; ORBIT handles the prioritization internally.

```
# Run ORBIT tick every 10 minutes
*/10 * * * * ORBIT_DB_BACKEND=sqlite ORBIT_HOME=~/.orbit python3 /path/to/orbit/src/orbit-tick.py
```

For tasks you want ORBIT to dispatch as standalone scripts:

```sql
UPDATE task_defs
SET run_backend = 'script',
    run_command  = '/home/you/scripts/my-backup.sh'
WHERE id = 'my-backup-task';
```

---

## Choosing Backends per Task

You can mix backends freely. Each `task_def` row has its own `run_backend`:

```sql
-- This task runs a local script directly
UPDATE task_defs SET run_backend='script', run_command='/scripts/check.sh' WHERE id='infra-check';

-- This task triggers a LaunchAgent
UPDATE task_defs SET run_backend='launchd', run_command='com.myapp.sync' WHERE id='data-sync';

-- This task delegates to OpenClaw (if available)
UPDATE task_defs SET run_backend='openclaw', cron_job_id='...' WHERE id='ai-summary';
```

ORBIT dispatches each task using its own backend — no global setting required.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ORBIT_DB_BACKEND` | `postgres` | `sqlite` or `postgres` |
| `ORBIT_HOME` | `~/.orbit` | Directory for SQLite DB and scripts |
| `ORBIT_PG_DSN` | `dbname=openclaw` | PostgreSQL connection string |

For standalone use, set `ORBIT_DB_BACKEND=sqlite` and `ORBIT_HOME` to a directory you control.
