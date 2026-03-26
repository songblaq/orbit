-- 8.0 로드맵 항목을 ORBIT T3 태스크로 등록
--
-- 원안(스키마 확장 전 참고용 — 현재 task_defs에는 run_backend/run_command 없음, sla_type은 hard|soft|none):
-- INSERT OR IGNORE INTO task_defs (id, tier, sla_type, enabled, run_backend, run_command, p_luca, p_lord, p_internal, p_depth)
-- VALUES
--   ('roadmap-web-auth-test', 3, 'best', 1, 'khala', 'AgentHive 웹 서버 인증 통합 테스트 (supertest)', 0.6, 0.7, 0.8, 0.4),
--   ('roadmap-ci-pg-smoke', 3, 'best', 1, 'khala', 'CI에서 PG 컨테이너 스키마 smoke test', 0.4, 0.6, 0.9, 0.5),
--   ('roadmap-aria-plugin-sign', 3, 'best', 0, 'khala', 'ARIA 플러그인 서명 검증', 0.3, 0.5, 0.7, 0.6),
--   ('roadmap-prometheus', 3, 'best', 0, 'khala', 'Prometheus /metrics 엔드포인트', 0.3, 0.4, 0.6, 0.5),
--   ('roadmap-api-reference', 3, 'best', 1, 'khala', 'TypeDoc + pdoc API 레퍼런스 자동 생성', 0.5, 0.5, 0.5, 0.3),
--   ('roadmap-orbit-dispatch-e2e', 3, 'best', 1, 'khala', 'ORBIT dispatch E2E (실제 SQLite + subprocess)', 0.5, 0.7, 0.8, 0.5),
--   ('roadmap-khala-schema-version', 3, 'best', 0, 'khala', 'Khala schema_version 필드 + 하위 호환', 0.4, 0.6, 0.7, 0.6),
--   ('roadmap-central-logging', 3, 'best', 0, 'khala', '중앙 집중 로그 수집 (fluentd/vector)', 0.3, 0.4, 0.5, 0.4);
--
-- 아래는 schema.sql + v2~v4 마이그레이션 적용 DB에 대한 실행 가능 시드 (name/interval_ms/max_duration_ms 필수, sla_type=soft).
INSERT OR IGNORE INTO task_defs (id, name, tier, sla_type, interval_ms, max_duration_ms, enabled, p_luca, p_lord, p_internal, p_depth)
VALUES
  ('roadmap-web-auth-test', 'AgentHive 웹 서버 인증 통합 테스트 (supertest)', 3, 'soft', 86400000, 300000, 1, 0.6, 0.7, 0.8, 0.4),
  ('roadmap-ci-pg-smoke', 'CI에서 PG 컨테이너 스키마 smoke test', 3, 'soft', 86400000, 300000, 1, 0.4, 0.6, 0.9, 0.5),
  ('roadmap-aria-plugin-sign', 'ARIA 플러그인 서명 검증', 3, 'soft', 86400000, 300000, 0, 0.3, 0.5, 0.7, 0.6),
  ('roadmap-prometheus', 'Prometheus /metrics 엔드포인트', 3, 'soft', 86400000, 300000, 0, 0.3, 0.4, 0.6, 0.5),
  ('roadmap-api-reference', 'TypeDoc + pdoc API 레퍼런스 자동 생성', 3, 'soft', 86400000, 300000, 1, 0.5, 0.5, 0.5, 0.3),
  ('roadmap-orbit-dispatch-e2e', 'ORBIT dispatch E2E (실제 SQLite + subprocess)', 3, 'soft', 86400000, 300000, 1, 0.5, 0.7, 0.8, 0.5),
  ('roadmap-khala-schema-version', 'Khala schema_version 필드 + 하위 호환', 3, 'soft', 86400000, 300000, 0, 0.4, 0.6, 0.7, 0.6),
  ('roadmap-central-logging', '중앙 집중 로그 수집 (fluentd/vector)', 3, 'soft', 86400000, 300000, 0, 0.3, 0.4, 0.5, 0.4);
