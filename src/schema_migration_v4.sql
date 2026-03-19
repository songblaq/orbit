-- ORBIT schema migration v4 — AgentHive Integration
-- Adds: agenthive_project, agenthive_task_id, ah_sync_* columns + audit log table
-- Date: 2026-03-18

PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;

-- ─────────────────────────────────────────────
-- task_defs: AgentHive metadata columns
-- ─────────────────────────────────────────────
ALTER TABLE task_defs ADD COLUMN agenthive_project TEXT;           -- AH project slug (nullable)
ALTER TABLE task_defs ADD COLUMN agenthive_task_id TEXT;           -- AH task UUID (nullable)
ALTER TABLE task_defs ADD COLUMN ah_sync_enabled INTEGER DEFAULT 1;    -- 1=track AH status, 0=disabled
ALTER TABLE task_defs ADD COLUMN ah_status_last_checked_at TEXT;       -- when AH status was last checked
ALTER TABLE task_defs ADD COLUMN ah_status_last_result TEXT;           -- cached result: 'pending', 'active', 'blocked', 'completed', 'failed', 'error', 'unknown'

-- ─────────────────────────────────────────────
-- system_config: AgentHive API settings
-- ─────────────────────────────────────────────
INSERT OR IGNORE INTO system_config(key, value, note) VALUES
  ('agenthive_api_url',          'http://localhost:8100',  'AgentHive API base URL (OpenJarvis default)'),
  ('agenthive_api_timeout_sec',  '5',                      'AH API request timeout in seconds'),
  ('agenthive_sync_interval_min','30',                     'Minimum interval between AH status checks (minutes)');

-- ─────────────────────────────────────────────
-- agenthive_sync_log: Audit trail for AH sync operations
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agenthive_sync_log (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id           TEXT NOT NULL,
  checked_at        TEXT NOT NULL,
  ah_project        TEXT,
  ah_task_id        TEXT,
  ah_status         TEXT,                           -- result from AH API
  dispatch_decision TEXT CHECK(dispatch_decision IN ('proceeded', 'skipped', 'error')),
  reason            TEXT,
  error_message     TEXT,
  created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_agenthive_sync_log_task_id ON agenthive_sync_log(task_id, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_agenthive_sync_log_at ON agenthive_sync_log(checked_at DESC);

-- ─────────────────────────────────────────────
-- Record migration version
-- ─────────────────────────────────────────────
INSERT OR IGNORE INTO schema_migrations(version, description)
VALUES (4, 'AgentHive: agenthive_project, agenthive_task_id, ah_sync_* columns + agenthive_sync_log');
