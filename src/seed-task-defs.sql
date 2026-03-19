-- ORBIT task_defs 초기 시딩 (2026-02-20)
-- 기존 26개 cron job → tier 분류 후 삽입
-- T1(VITAL/hard), T2(CRITICAL/hard), T3(ROUTINE/soft), T4(DEFERRED/soft), T5(BACKGROUND/none)

INSERT OR IGNORE INTO task_defs(id, name, tier, sla_type, interval_ms, max_duration_ms, enabled) VALUES

-- T1: VITAL (hard SLA) — 절대 누락 불가
('ops-anomaly-detection',   'ops-초단기-이상탐지-v1',           1, 'hard',   900000,  120000, 1),
('ops-alert-router',        'ops-alert-router-v1',               1, 'hard',   900000,  120000, 1),
('ha003-healthcheck',       'HA003-매시-healthcheck-v1',         1, 'hard',  3600000,   60000, 1),

-- T2: CRITICAL (hard SLA) — 누락 시 즉시 알림
('ai-collection',           'cron-5-ai수집 v2',                  2, 'hard',  3600000,  300000, 1),
('morning-checkin',         '아침 체크인',                        2, 'hard', 86400000,  180000, 1),
('luca-ai-expert',          '루카ai전문가-채널-1시간-요약점검',    2, 'hard',  3600000,  240000, 1),
('investment-monitor',      '투자-재테크 장기 모니터링',           2, 'hard', 10800000,  300000, 1),
('daily-retrospective',     '매일 회고+학습 루틴',                2, 'hard', 86400000,  300000, 1),

-- T3: ROUTINE (soft SLA) — 지연 허용, 누락 시 다음 틱 재시도
('sns-content',             'sns-콘텐츠-생성-v1',                3, 'soft', 86400000,  300000, 1),
('botmadang-activity',      '봇마당-활동-v3',                     3, 'soft', 43200000,  300000, 1),
('maltbook-activity',       '몰트북-활동-v3',                     3, 'soft', 43200000,  300000, 1),
('x-twitter-activity',      'x-twitter-활동-v3',                 3, 'soft', 86400000,  300000, 1),
('ops-skill-audit',         'ops-일간-스킬감사-v1',               3, 'soft', 86400000,  300000, 1),
('infra-check',             '인프라-점검-v3',                     3, 'soft', 43200000,  180000, 1),
('project-check',           '프로젝트-진행-점검-v1',              3, 'soft', 86400000,  300000, 1),
('drift-daily-checkin',     'drift-일일체크인-v1',                3, 'soft', 86400000,  120000, 1),
('drift-weekly-report',     'drift-주간리포트-v1',                3, 'soft', 604800000, 180000, 1),
('drift-alert-check',       'drift-알림점검-v1',                  3, 'soft', 86400000,   60000, 1),
('ops-weekly-audit',        'ops-주간-힐러감사-v1',               3, 'soft', 604800000, 300000, 1),

-- T4: DEFERRED (soft SLA) — 여유 시 처리
('cafe-backup',             '상명학-카페-백업-v3',                4, 'soft', 86400000,  600000, 1),
('exercise-rd',             '운동기기-장기R&D',                   4, 'soft', 86400000,  600000, 1),
('deepcron-manager',        '딥크론 매니저-v2',                   4, 'soft', 43200000,  300000, 1),

-- T5: BACKGROUND (none) — 유휴 시간에만
('deepwork-nexusops',       'deep-work-nexusops-205',            5, 'none',  1800000, 3600000, 0),
('deepwork-agent-300',      'deepwork-autonomous-agent-300',     5, 'none',  1800000, 3600000, 0),
('ha004-daily-report',      'HA004-매일-보고',                   5, 'none', 86400000,  300000, 0),
('ha004-weekly-report',     'HA004-주간-보고',                   5, 'none', 604800000, 300000, 0);
