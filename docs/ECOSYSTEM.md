# Ecosystem Integration Guide

## Overview

Three independent tools that form a complete AI agent automation stack when combined:
- **AgentHive**: Project/task registry (WHAT needs to be done)
- **ORBIT**: R4 scoring scheduler (WHEN to do it)
- **ARIA**: Agent/runtime infrastructure (WHO does it, HOW)

## The Three Systems

### AgentHive
Registry for projects, tasks, and agents. Defines work scope, priorities, and collaboration workflows across teams and runtimes.

### ORBIT
Intelligent scheduler that scores tasks using R4 metrics (Readiness, Requirements, Resources, Risks), dispatches to runtimes, and manages execution timing based on system load and dependencies.

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
AgentHive status update + Khala notification
```

## Integration Pairs

### AgentHive ↔ ORBIT
- ORBIT polls AgentHive task status (ready/doing/blocked/done)
- Skips blocked and completed tasks
- Maps ORBIT dispatch tiers to AgentHive task priorities
- Task metadata (effort, deps) informs R4 scoring

### AgentHive ↔ ARIA
- Collab messages backed by Khala channels (27 channels across runtime boundaries)
- Nyx agents assigned AgentHive roles: builder (implementation), planner (strategy), arbiter (review)
- AR Adapters generate runtime-specific task files and environment bindings
- Agent profiles stored in AgentHive, executed via ARIA harnesses

### ORBIT ↔ ARIA
- ORBIT dispatches via Khala backend (async, persistent)
- Nyx keyword routing guides task assignment to specialized agents
- ARIA health checks (runtime uptime, available agents) inform dispatch decisions
- Feedback loop: task completion → ORBIT learning → smarter scheduling

## Using Without the Others

Each tool works independently:

- **AgentHive alone**: Manual project/task board with collab messaging. No scheduling or runtime integration.
- **ORBIT alone**: Standalone scheduler with shell script backend. Reads JSON task files, executes, logs results.
- **ARIA alone**: Agent sharing and skill execution across runtimes. No task registry or scheduling.

## Quick Start

### Install All Three
```bash
# AgentHive
npm install -g agenthive
# or: git clone https://github.com/songblaq/agent-hive && cd agent-hive && npm install -g .

# ORBIT
git clone https://github.com/songblaq/orbit
cd orbit && npm install

# ARIA
git clone https://github.com/songblaq/aria
cd aria && ./install.sh
```

### Enable Integration
```bash
# Start ARIA first (manages runtimes)
aria status

# Configure ORBIT to use Khala backend
orbit config set backend khala://localhost:8100

# Link AgentHive hub to ORBIT
orbit config set agenthive-hub ~/.agenthive

# Verify connectivity
orbit health
```

### First Task Flow
1. Create task in AgentHive: `agenthive task create --project myapp --title "Build API"`
2. Set task status to ready: `agenthive task update --status ready`
3. ORBIT picks it up on next tick (default 10s), scores it, dispatches
4. Nyx router assigns to builder agent based on keywords
5. Agent executes, writes result to Khala channel
6. AgentHive status auto-updates from Khala notification

## Architecture Files

| Repo | Key Docs |
|------|----------|
| **agent-hive** | `README.md`, `docs/architecture.md`, `docs/collab.md` |
| **orbit** | `README.md`, `docs/r4-scoring.md`, `docs/dispatch.md` |
| **aria** | `README.md`, `nyx/README.md`, `docs/architecture.md` |

## Common Questions

**Q: Can I use ORBIT without AgentHive?**
Yes. ORBIT reads task files directly from disk or HTTP. Point `--task-source` to a JSON file or API endpoint.

**Q: What if ARIA runtime goes down?**
ORBIT queues tasks in Khala. When runtime returns, ARIA consumes the queue in order. AgentHive shows "blocked" status until runtime is live.

**Q: How do I run this on multiple machines?**
- ARIA: Deploy Nyx agents to different runtime machines, register with shared Khala broker
- ORBIT: Single scheduler, reads from remote AgentHive API or shared task directory
- AgentHive: Runs as REST API (`agenthive serve`) or local hub; both support network clients

**Q: Minimal setup for one machine?**
```bash
aria install --runtime claude-code  # Or: --runtime openclaw
orbit start --local                 # Single-process mode
agenthive serve --port 3000        # Local hub
# Then: orbit config set agenthive-hub http://localhost:3000
```

## Support

- **AgentHive Issues**: github.com/songblaq/agent-hive/issues
- **ORBIT Issues**: github.com/songblaq/orbit/issues
- **ARIA Issues**: github.com/songblaq/aria/issues

Join the community in the AgentHive Hub for cross-tool questions.
