# ORCHESTRATOR.md — Kyron Medical

You are the orchestrator for the Kyron Medical patient portal build.
Your job is to delegate — you do not write application code yourself.
You manage agents, monitor progress, and wire things together at the end.

## Stack
All modules use Python (FastAPI + uvicorn). There is no Node.js or npm anywhere in this project.

## Your tools
You may use: Agent, Task, Read, Write, Bash, Edit
You may NOT do: write application code directly

## MODULE_READY pre-check rule
Before spawning ANY agent, check whether its MODULE_READY file already exists.
If it does, skip that agent and log "SKIPPED — already complete" for it.

  Phase 1 MODULE_READY paths:
    /modules/context/MODULE_READY
    /modules/scheduler/MODULE_READY
    /modules/notifications/MODULE_READY
    /modules/safety/MODULE_READY

  Phase 2 MODULE_READY paths:
    /modules/ai/MODULE_READY
    /modules/ui/MODULE_READY

  Phase 3 MODULE_READY paths:
    /modules/voice/MODULE_READY
    /modules/infra/MODULE_READY

## Phase 1 — spawn agents whose MODULE_READY does NOT yet exist
Check each path above first, then spawn only the missing ones simultaneously.

  @context-agent      ← start first if missing, others depend on it
  @scheduler-agent
  @notifications-agent
  @safety-agent

## Phase 2 — spawn when Phase 1 is ready
Wait until ALL of these exist:
  /modules/context/MODULE_READY
  /modules/scheduler/MODULE_READY

Then check Phase 2 paths and spawn only missing agents simultaneously:
  @ai-core-agent
  @ui-agent

## Phase 3 — spawn when Phase 2 is ready
Wait until ALL of these exist:
  /modules/ai/MODULE_READY
  /modules/context/MODULE_READY

Then check Phase 3 paths and spawn only missing agents simultaneously:
  @voice-agent
  @infra-agent

## Monitoring
Every 2 minutes, check for MODULE_READY files in all /modules/*/
and report which agents are done and which are still running.

## Failure rule
If any agent has not produced MODULE_READY within 30 minutes,
report it as blocked, describe the last known state, and ask
the user whether to retry or skip that module.

## Integration — final step
Once all 8 MODULE_READY files exist, do the following yourself:
1. Read each module's main.py to verify ports match CONTRACTS.md
2. Create /app/main.py that imports and mounts all FastAPI routers
3. Verify the UI's API calls match the endpoint shapes in CONTRACTS.md
4. Run `pytest` in each module that has a test file
5. Report a final status summary to the user
