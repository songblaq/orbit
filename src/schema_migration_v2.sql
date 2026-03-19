-- ORBIT schema migration v2 — Week-2 준비
-- 추가: cron_job_id 매핑, consecutive_successes, system_config

PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;

-- ─────────────────────────────────────────────
-- task_defs 컬럼 추가
-- ─────────────────────────────────────────────
ALTER TABLE task_defs ADD COLUMN cron_job_id TEXT;          -- openclaw cron job UUID
ALTER TABLE task_defs ADD COLUMN consecutive_successes INTEGER DEFAULT 0;  -- 연속 성공 횟수
ALTER TABLE task_defs ADD COLUMN last_dispatched_at TEXT;   -- 마지막 dispatch 시각
ALTER TABLE task_defs ADD COLUMN orbit_managed INTEGER DEFAULT 0;  -- 1=ORBIT dispatch, 0=cron

-- ─────────────────────────────────────────────
-- system_config 테이블 — 운영 모드 등 전역 설정
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS system_config (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  note       TEXT
);

INSERT OR IGNORE INTO system_config(key, value, note) VALUES
  ('orbit_mode',        'shadow',     'shadow=Week-1, active=Week-2+'),
  ('week',              '1',          '현재 week'),
  ('shadow_start_at',   datetime('now'), 'shadow 시작 시각'),
  ('dispatch_tiers',    '',           'active 시 dispatch할 tier 목록 (예: 4,5)'),
  ('freeze_count',      '0',          'scheduler freeze 발생 횟수'),
  ('sla_miss_count',    '0',          'SLA miss 횟수');

-- ─────────────────────────────────────────────
-- cron_job_id 매핑 업데이트
-- ─────────────────────────────────────────────
UPDATE task_defs SET cron_job_id = '8d567769-8176-4b6c-a954-cb614215b217' WHERE id = 'ops-anomaly-detection';
UPDATE task_defs SET cron_job_id = 'd625e54e-e013-4f04-bf9d-c4737d0531e3' WHERE id = 'ops-alert-router';
UPDATE task_defs SET cron_job_id = 'fc199d9c-4095-45b0-a6d1-3ee58d989f07' WHERE id = 'ha003-healthcheck';
UPDATE task_defs SET cron_job_id = 'b9501906-b56c-4889-9822-1c8a29c88960' WHERE id = 'ai-collection';
UPDATE task_defs SET cron_job_id = '51ea9815-abf0-4a51-b4f3-73b63dc5d924' WHERE id = 'morning-checkin';
UPDATE task_defs SET cron_job_id = '929eb8b3-35e2-4abe-8f78-c8267b9c069c' WHERE id = 'luca-ai-expert';
UPDATE task_defs SET cron_job_id = '343ed6a1-a19b-43b4-aab6-c192b95f9dd1' WHERE id = 'investment-monitor';
UPDATE task_defs SET cron_job_id = '744e339e-2495-4f25-b357-a9eed0f44bed' WHERE id = 'daily-retrospective';
UPDATE task_defs SET cron_job_id = 'e8cc7735-ea06-4c5b-a06b-9c7e8fca3b26' WHERE id = 'sns-content';
UPDATE task_defs SET cron_job_id = '0bc7adf9-7025-4cb9-b3ad-823069aaf31e' WHERE id = 'botmadang-activity';
UPDATE task_defs SET cron_job_id = '7db751e2-1719-4830-a073-690eab2ff46d' WHERE id = 'maltbook-activity';
UPDATE task_defs SET cron_job_id = 'f5e8310c-26a8-4f7b-a680-0e5d2b8a3737' WHERE id = 'x-twitter-activity';
UPDATE task_defs SET cron_job_id = '5fe03fb0-2db2-482c-9e0e-95d25c360d11' WHERE id = 'ops-skill-audit';
UPDATE task_defs SET cron_job_id = '39e7688b-e32b-4e1d-a887-fe1000984899' WHERE id = 'infra-check';
UPDATE task_defs SET cron_job_id = '5e600d34-54ee-4049-9435-241ecf61f8bc' WHERE id = 'project-check';
UPDATE task_defs SET cron_job_id = '16c8c1be-eba5-46a3-be20-876762c8d655' WHERE id = 'drift-daily-checkin';
UPDATE task_defs SET cron_job_id = '3616418c-a5e0-47cd-b48b-5d5f55b0a3a3' WHERE id = 'drift-weekly-report';
UPDATE task_defs SET cron_job_id = 'd978afdc-ff2a-4951-a566-934a9539d13e' WHERE id = 'drift-alert-check';
UPDATE task_defs SET cron_job_id = '8773e41a-bf22-4937-b539-2a1bd0aaad33' WHERE id = 'ops-weekly-audit';
UPDATE task_defs SET cron_job_id = '9c47d1f3-c993-4970-98ba-500f652f2dab' WHERE id = 'cafe-backup';
UPDATE task_defs SET cron_job_id = '71329f0a-8ae5-4608-9255-4d4a19ac0976' WHERE id = 'exercise-rd';
UPDATE task_defs SET cron_job_id = '08b07f1e-2a1e-4e6a-8640-b39d09e76568' WHERE id = 'deepcron-manager';
UPDATE task_defs SET cron_job_id = 'e0e1e56c-f36d-4dd6-906f-e6b1b617efac' WHERE id = 'deepwork-nexusops';
UPDATE task_defs SET cron_job_id = '940f3b00-2920-4e73-8021-a5487c1ba42e' WHERE id = 'deepwork-agent-300';
UPDATE task_defs SET cron_job_id = 'ad404cf6-e0bd-48e4-9e54-dd5e3b7377b0' WHERE id = 'ha004-daily-report';
UPDATE task_defs SET cron_job_id = '58a439f0-eeb7-46a9-a1c3-b118e163fbd5' WHERE id = 'ha004-weekly-report';

-- migration 버전 기록
INSERT OR IGNORE INTO schema_migrations(version, description)
VALUES (2, 'Week-2: cron_job_id mapping, consecutive_successes, system_config table');
