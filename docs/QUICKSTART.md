# ORBIT Quick Start — 5 Minutes to Your First Scheduled Task

This guide gets ORBIT running locally with SQLite. No external dependencies required.

---

## Prerequisites

- Python 3.9+
- Git
- SQLite3 (included with Python and most OS installs)

---

## Step 1 — Clone and Set Up

```bash
git clone https://github.com/songblaq/orbit.git
cd orbit
chmod +x bin/orbit
```

---

## Step 2 — Configure for Standalone SQLite Use

ORBIT defaults to PostgreSQL. Override this with environment variables. Add these to your shell profile (`~/.zshrc`, `~/.bashrc`, etc.) or set them for the session:

```bash
export ORBIT_DB_BACKEND=sqlite
export ORBIT_HOME=~/.orbit
```

Create the data directory:

```bash
mkdir -p ~/.orbit
```

---

## Step 3 — Initialize the Database

Apply the base schema, then run migrations to add all tables and config defaults:

```bash
sqlite3 ~/.orbit/orbit.db < src/schema.sql
bin/orbit migrate
```

Expected output:

```
[orbit-migrate] DB: /Users/you/.orbit/orbit.db
  v2 migration running...
  system_config table created
  v2 migration complete
  v4 migration running...
  v4 migration complete
─── schema_migrations ───
  v1: Initial ORBIT schema
  v2: system_config, cron_job_id, consecutive_successes
  v4: AgentHive integration columns
─── system_config ───
  dispatch_tiers           = ''
  orbit_mode               = 'shadow'
  week                     = '1'
```

---

## Step 4 — Add a Sample Task

Insert a task definition directly via SQLite. This example registers a daily backup task:

```bash
sqlite3 ~/.orbit/orbit.db <<'SQL'
INSERT INTO task_defs (
  id, name, tier, sla_type, interval_ms, max_duration_ms, enabled
) VALUES (
  'sample-backup',
  'Daily Backup',
  3,                    -- T3: ROUTINE (soft SLA)
  'soft',
  86400000,             -- 24 hours in milliseconds
  300000,               -- 5 minute max runtime
  1                     -- enabled
);
SQL
```

Verify it was inserted:

```bash
sqlite3 ~/.orbit/orbit.db "SELECT id, name, tier, enabled FROM task_defs;"
```

---

## Step 5 — Run a Tick

```bash
bin/orbit tick
```

By default, ORBIT runs in **shadow mode**: it evaluates which tasks are due and logs its decisions, but does not actually dispatch anything. This lets you observe scoring behavior before committing to live execution.

Expected output:

```
[orbit-tick] mode=shadow
[orbit-tick] evaluated 1 task(s)
[orbit-tick] sample-backup → score=0.50 (T3, due)
[orbit-tick] shadow: would dispatch sample-backup
[orbit-tick] tick complete (0 dispatched, 1 scored)
```

---

## Step 6 — Check Status

```bash
bin/orbit status
```

Shows the current mode, task counts, recent tick history, and any pending SLA issues.

```bash
# Brief one-liner
bin/orbit status --brief

# JSON output for scripting
bin/orbit status --json
```

---

## Step 7 — Enable Live Dispatch (Optional)

When you're ready for ORBIT to actually run your tasks:

```bash
bin/orbit config orbit_mode active
```

On the next tick, tasks that are due will be dispatched via their `run_backend`. For `script` tasks, the `run_command` is executed as a subprocess.

---

## Scheduling ORBIT Automatically

ORBIT does not daemonize — it needs to be triggered on a schedule. Quick options:

**crontab** (simplest):
```bash
crontab -e
# Add:
*/10 * * * * ORBIT_DB_BACKEND=sqlite ORBIT_HOME=~/.orbit python3 /path/to/orbit/src/orbit-tick.py
```

**Manual test** (run once now):
```bash
ORBIT_DB_BACKEND=sqlite ORBIT_HOME=~/.orbit python3 src/orbit-tick.py
```

See [README.md](../README.md) for macOS LaunchAgent and systemd timer examples.

---

## Next Steps

- Add more tasks with different tiers and intervals
- Review scoring with `orbit dispatch --dry-run`
- Check the gate conditions before enabling a tier: `orbit gate check`
- See [docs/INTEGRATION.md](INTEGRATION.md) for connecting ORBIT to external systems (all optional)
