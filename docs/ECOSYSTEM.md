# Ecosystem Integration Guide

## Overview

Three independent tools that form a complete AI agent automation stack when combined:
- **AgentHive**: Project/task registry (WHAT needs to be done)
- **ORBIT**: R4 스케줄러 — R4 좌표계: p_luca(인간 긴급도 0.35), p_lord(AI 판단 0.25), p_internal(시스템 중요도 0.25), p_depth(복잡도 0.15) — (WHEN to do it)
- **ARIA**: Agent/runtime infrastructure (WHO does it, HOW)

## The Three Systems

### AgentHive
Registry for projects, tasks, and agents. Defines work scope, priorities, and collaboration workflows across teams and runtimes.

### ORBIT
Intelligent scheduler that scores tasks using **R4 좌표계: p_luca(인간 긴급도 0.35), p_lord(AI 판단 0.25), p_internal(시스템 중요도 0.25), p_depth(복잡도 0.15)**, dispatches to runtimes, and manages execution timing based on system load and dependencies.

### ARIA
Agent-runtime integration architecture. Manages Nyx agents, Khala messaging, runtime adapters, and skill execution across Claude Code, OpenClaw, and external providers.

## Data Flow

```
AgentHive "TASK ready" 
  ↓
ORBIT scores + prioritizes + dispatches
  ↓
ARIA routes to appropriate runtime via Nyx agents
  ↓
Runtime executes (Claude Code / OpenClaw / External)
  ↓
Result returned
  ↓
AgentHive status update + Khala notification  <!-- planned: fully automated close-the-loop -->
```

## Integration Pairs

> **구현 상태 범례**: [✅ 구현됨] 작동 확인 | [🚧 개발 중] 부분 구현 또는 알려진 이슈 | [📋 계획됨] 미구현

### AgentHive ↔ ORBIT
- ORBIT polls AgentHive task status (ready/doing/blocked/done) [🚧 개발 중]
- Skips blocked and completed tasks [✅ 구현됨]
- Maps ORBIT dispatch tiers to AgentHive task priorities [✅ 구현됨]
- Task metadata (effort, deps) informs **R4 좌표계: p_luca(인간 긴급도 0.35), p_lord(AI 판단 0.25), p_internal(시스템 중요도 0.25), p_depth(복잡도 0.15)** 기반 스코어링 [📋 계획됨]

### AgentHive ↔ ARIA
- Collab messages backed by Khala channels (27 channels across runtime boundaries) [🚧 개발 중]
- Nyx agents assigned AgentHive roles: builder (implementation), planner (strategy), arbiter (review) [✅ 구현됨]
- AR Adapters generate runtime-specific task files and environment bindings [✅ 구현됨]
- Agent profiles stored in AgentHive, executed via ARIA harnesses [📋 계획됨]

### ORBIT ↔ ARIA
- ORBIT dispatches via Khala backend (async, persistent) [✅ 구현됨]
- Nyx keyword routing guides task assignment to specialized agents [✅ 구현됨]
- ARIA health checks (runtime uptime, available agents) inform dispatch decisions [📋 계획됨]
- Feedback loop: task completion → ORBIT learning → smarter scheduling [📋 계획됨]

## Using Without the Others

Each tool works independently:

- **AgentHive alone**: Manual project/task board with collab messaging. No scheduling or runtime integration.
- **ORBIT alone**: Standalone R4 scheduler backed by a task DB under `ORBIT_HOME` (default `~/.aria/orbit`); SQLite가 기본이며 PostgreSQL 백엔드(orbit_db.py 듀얼 경로)는 [🚧 개발 중 — ADR-004 참조]. CLI dispatches via `orbit-tick.py` / `orbit-dispatch.py` and related scripts.
- **ARIA alone**: Agent sharing and skill execution across runtimes. No task registry or scheduling.

## Quick Start

### Install All Three
```bash
# AgentHive (planned: npm global once published; for now use the repo)
npm install -g agenthive
# or: git clone https://github.com/songblaq/agent-hive && cd agent-hive && npm install -g .

# ORBIT (Python CLI: `orbit/bin/orbit`; no root npm package in this layout)
git clone https://github.com/songblaq/orbit
cd orbit && export PATH="$PWD/bin:$PATH"   # then: orbit version

# ARIA
git clone https://github.com/songblaq/aria
cd aria && ./install.sh
```

### Enable Integration
```bash
# ARIA — CLI: status, khala, bus (alias → khala), nyx, knowledge, registry, tui, web, version
aria status

# ORBIT — subcommands: tick, dispatch, status, gate, migrate, observer, dashboard, config, version
# Config is positional: `orbit config`, `orbit config <key>`, or `orbit config <key> <value>` (not `config set`).
# Khala/AgentHive wiring is task-level and DB config (see orbit/docs/INTEGRATION.md).
orbit config backend khala://localhost:8100       # (planned) — requires key support in DB
orbit config agenthive-hub ~/.agenthive           # (planned)

orbit status
```

### First Task Flow
1. Create task in AgentHive: from a registered project dir, `agenthive task create "Build API"` (top-level: init, project, task, status, setup, web, collab, harness, sync; `task`: create, claim, complete, list).
2. Set task status to ready (e.g. edit `task.yaml`) (planned: `agenthive task update --status ready`).
3. Run `orbit tick` on a schedule (cron/launchd); ORBIT does not ship a built-in daemon (planned: automatic tick loop / fixed-interval polling as a single command).
4. Nyx router assigns to builder agent based on keywords (planned: end-to-end automation from ORBIT dispatch alone).
5. Agent executes, writes result to Khala channel.
6. AgentHive status auto-updates from Khala notification (planned).

## Architecture Files

| Repo | Key Docs |
|------|----------|
| **agent-hive** | `README.md`, `docs/architecture.md`, `docs/collab.md` |
| **orbit** | `README.md`, `docs/r4-scoring.md`, `docs/dispatch.md` |
| **aria** | `README.md`, `nyx/README.md`, `docs/architecture.md` |

## Common Questions

**Q: Can I use ORBIT without AgentHive?**
Yes. ORBIT reads task rows from its own database (SQLite 기본; PostgreSQL [🚧 개발 중 — ADR-004 참조]) and optional file/HTTP sync. (planned: a single `--task-source` flag pointing at JSON or an HTTP endpoint — today configure tasks via DB/SQL and `orbit/docs/INTEGRATION.md`.)

**Q: What if ARIA runtime goes down?**
With `run_backend = khala`, ORBIT publishes to Khala; consumption and retry depend on your subscriber setup. (planned: guaranteed queue semantics and AgentHive auto-`blocked` from runtime health.)

**Q: How do I run this on multiple machines?**
- ARIA: Deploy Nyx agents to different runtime machines, register with shared Khala broker
- ORBIT: Single scheduler, reads from remote AgentHive API or shared task directory
- AgentHive: Local file hub under `~/.agenthive`; dashboard via `agenthive web`. (planned: `agenthive serve` as a REST API hub for network clients.)

**Q: Minimal setup for one machine?**
```bash
# ARIA — no `aria install` subcommand; use repo install + plugins
cd aria && ./install.sh   # or aria/plugins/*/install.sh  # (planned: aria install --runtime …)

orbit start --local                 # (planned) — use: cron/launchd + `orbit tick`, see orbit/docs/INTEGRATION.md
agenthive web --port 4173           # dashboard (default port 4173); not `serve`
# Then e.g. orbit config set agenthive_api_url …  # (planned) HTTP sync story; file hub needs no URL
```

## Support

- **AgentHive Issues**: github.com/songblaq/agent-hive/issues
- **ORBIT Issues**: github.com/songblaq/orbit/issues
- **ARIA Issues**: github.com/songblaq/aria/issues

Join the community in the AgentHive Hub for cross-tool questions.
