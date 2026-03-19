-- ORBIT schema migration v4: AgentHive 연동 컬럼 추가
-- 날짜: 2026-03-18
-- 목적: task_defs에 AgentHive 프로젝트/태스크 매핑 추가

-- task_defs에 AgentHive 연동 컬럼 추가
ALTER TABLE task_defs ADD COLUMN agenthive_project TEXT;     -- AH 프로젝트 slug (e.g., 'openclaw', 'ops')
ALTER TABLE task_defs ADD COLUMN agenthive_task_id TEXT;     -- AH 태스크 ID (e.g., 'TASK-042')
ALTER TABLE task_defs ADD COLUMN agenthive_status TEXT;      -- 캐시된 AH 상태 (backlog/ready/doing/review/done/blocked)
ALTER TABLE task_defs ADD COLUMN agenthive_synced_at TEXT;   -- 마지막 AH 동기화 시각

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_task_defs_ah_project ON task_defs(agenthive_project);

-- Orbit Tier → AgentHive Priority 매핑 참고:
--   T1 = critical
--   T2 = high
--   T3 = medium
--   T4 = low
--   T5 = low

-- 마이그레이션 이력 기록
INSERT INTO schema_migrations(version, description)
VALUES (4, 'AgentHive integration: agenthive_project, agenthive_task_id, agenthive_status, agenthive_synced_at columns on task_defs');
