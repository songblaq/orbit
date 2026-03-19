-- schema_migration_v3_add_plord.sql
-- ORBIT ℝ⁴ 확장: p_lord 축 추가
-- 주의: SQLite는 ADD COLUMN IF NOT EXISTS를 지원하지 않으므로,
--       이미 p_lord가 존재하면 실행 전 스키마를 먼저 확인해야 함.

ALTER TABLE task_defs ADD COLUMN p_lord REAL DEFAULT 0.5;
