# ORBIT v2 — 독립 스케줄러 + 크론 메타 관리자

**날짜**: 2026-03-19
**배경**: 기존 ORBIT은 `openclaw cron run`만 호출 가능 → 크론이 삭제되면 디스패치 실패

## 설계 원칙

1. **자체 실행 우선** — OpenClaw 의존 없이 직접 스크립트/명령 실행
2. **다중 백엔드** — 필요시 OpenClaw cron, Claude Code, macOS launchd 등 연결
3. **메타 관리** — 여러 크론 시스템을 통합 관리, 중복 방지
4. **재발 방지** — 로그 로테이션, 타임아웃 관리, 실패 추적

## 실행 백엔드 (run_backend)

| backend | 설명 | 의존성 |
|---------|------|--------|
| `script` | Python/Bash 스크립트 직접 실행 | 없음 (subprocess) |
| `openclaw` | `openclaw cron run <id>` | OpenClaw Gateway |
| `khala` | Khala 메시지로 런타임에 위임 | Khala 채널 |
| `launchd` | macOS LaunchAgent 트리거 | launchctl |

## task_defs 스키마 확장

```sql
ALTER TABLE task_defs ADD COLUMN run_backend TEXT DEFAULT 'script';
ALTER TABLE task_defs ADD COLUMN run_command TEXT;       -- script: 실행할 명령
ALTER TABLE task_defs ADD COLUMN run_timeout INTEGER DEFAULT 120;
```

## dispatch 흐름

```
기존: ORBIT tick → R4 스코어 → openclaw cron run <id> → 결과
신규: ORBIT tick → R4 스코어 → run_backend 판단
      ├─ script: subprocess.run(run_command)
      ├─ openclaw: openclaw cron run <cron_job_id>
      ├─ khala: Khala publish (런타임에 위임)
      └─ launchd: launchctl kickstart <label>
```

## 크론 메타 관리

ORBIT이 다른 크론 시스템도 관찰/관리:

```
외부 크론 소스:
  ├─ OpenClaw cron (jobs.json) — 14개 비활성
  ├─ macOS LaunchAgents — com.aria.orbit-tick 등
  └─ (향후) Claude Code 크론

ORBIT 역할:
  1. 외부 크론 목록을 주기적으로 스캔
  2. task_defs와 대조 → 중복 감지
  3. 통합 상태 보고 (orbit-status.py)
```
