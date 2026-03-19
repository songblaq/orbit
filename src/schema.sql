-- ORBIT control-plane schema v1.0
-- Week-1 범위: task_defs, task_runs, tick_log, lock_lease, system_metrics
-- Vector Mode 컬럼(p_luca, p_internal, p_depth, initial_weight_hint)은 schema-only
-- dispatch 로직에서 읽기/쓰기 절대 금지 (Phase-2 이전)

PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;

-- ─────────────────────────────────────────────
-- 1. task_defs — 태스크 정의
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS task_defs (
  id             TEXT PRIMARY KEY,           -- 예: 'ai-collection', 'session-backup'
  name           TEXT NOT NULL,
  tier           INTEGER NOT NULL CHECK(tier BETWEEN 1 AND 5),  -- T1~T5 레이블 유지
  sla_type       TEXT NOT NULL DEFAULT 'soft' CHECK(sla_type IN ('hard','soft','none')),
  interval_ms    INTEGER NOT NULL,           -- 기대 실행 주기 (ms)
  max_duration_ms INTEGER DEFAULT 300000,   -- 최대 허용 실행 시간
  enabled        INTEGER NOT NULL DEFAULT 1,

  -- Vector Mode 컬럼 (schema-only, Week-1 dispatch에서 사용 금지)
  p_luca         REAL DEFAULT 0.0,
  p_internal     REAL DEFAULT 0.0,
  p_depth        REAL DEFAULT 0.0,
  initial_weight_hint REAL DEFAULT 1.0,

  created_at     TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_task_defs_tier ON task_defs(tier, enabled);

-- ─────────────────────────────────────────────
-- 2. task_runs — 실행 이력
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS task_runs (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id        TEXT NOT NULL REFERENCES task_defs(id),
  tick_id        INTEGER,                    -- tick_log.id 참조 (nullable, shadow 기간)
  status         TEXT NOT NULL CHECK(status IN ('running','success','failed','skipped','timeout')),
  started_at     TEXT NOT NULL,
  finished_at    TEXT,
  duration_ms    INTEGER,
  error_message  TEXT,

  -- Vector Mode 컬럼 (schema-only, Week-1에서 쓰기 금지)
  mode           TEXT DEFAULT 'tier' CHECK(mode IN ('tier','vector')),
  score          REAL,
  score_breakdown TEXT,                      -- JSON: {mode, w, p, total_score, notes}

  created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_task_runs_task_id ON task_runs(task_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_task_runs_status  ON task_runs(status, started_at DESC);

-- ─────────────────────────────────────────────
-- 3. tick_log — master tick 이력 (10분 주기)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tick_log (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  tick_at        TEXT NOT NULL,
  mode           TEXT NOT NULL DEFAULT 'shadow' CHECK(mode IN ('shadow','active')),
  tasks_evaluated INTEGER DEFAULT 0,
  tasks_dispatched INTEGER DEFAULT 0,        -- shadow 기간: 항상 0
  decision_log   TEXT,                       -- JSON array: shadow 판단 근거
  duration_ms    INTEGER,
  created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tick_log_tick_at ON tick_log(tick_at DESC);

-- ─────────────────────────────────────────────
-- 4. lock_lease — 분산 lock (expire_at 필수)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lock_lease (
  lock_key       TEXT PRIMARY KEY,           -- 예: 'orbit-master-tick'
  holder         TEXT NOT NULL,             -- 프로세스 ID 또는 식별자
  acquired_at    TEXT NOT NULL,
  expire_at      TEXT NOT NULL,             -- 반드시 설정 (orphan lock 방지)
  heartbeat_at   TEXT
);

-- ─────────────────────────────────────────────
-- 5. system_metrics — 시스템 상태 스냅샷
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS system_metrics (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  measured_at    TEXT NOT NULL,
  cpu_pct        REAL,
  mem_free_mb    REAL,
  mem_total_mb   REAL,
  active_tasks   INTEGER DEFAULT 0,
  pending_tasks  INTEGER DEFAULT 0,
  created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_system_metrics_at ON system_metrics(measured_at DESC);

-- ─────────────────────────────────────────────
-- 마이그레이션 버전 관리
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_migrations (
  version        INTEGER PRIMARY KEY,
  applied_at     TEXT NOT NULL DEFAULT (datetime('now')),
  description    TEXT
);

INSERT OR IGNORE INTO schema_migrations(version, description)
VALUES (1, 'Initial ORBIT Week-1 schema: task_defs, task_runs, tick_log, lock_lease, system_metrics');
