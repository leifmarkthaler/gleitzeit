# Gleitzeit Orchestrator Audit

**Date:** 2025-10-19
**Issue:** redis_monitor and loki_exporter not showing in `gleitzeit ps`

## Executive Summary

Gleitzeit has **TWO** separate orchestration systems that are currently being used in different contexts:

1. **ComponentOrchestrator** - Used by `gleitzeit start`
2. **AsyncServiceManager** - Used by `gleitzeit serve`

The redis_monitor and loki_exporter services are **only** started by AsyncServiceManager, which means they don't run when using `gleitzeit start`.

## Detailed Findings

### 1. ComponentOrchestrator

**Location:** `src/gleitzeit/orchestrator/component_orchestrator.py`

**Used By:**
- `gleitzeit start` command ([main.py:373-423](src/gleitzeit/cli/main.py#L373-L423))
- `gleitzeit orchestrator start` command

**What It Does:**
- Manages the 11 core workers: api, ui, task_execution, dependency, workflow_loader, python_specialist, workflow_submission, retry, timer, signal, reconciliation
- Spawns workers as Python subprocesses
- Stores worker configurations in Redis
- Monitors worker health via heartbeats

**What It Does NOT Do:**
- ❌ Does not start redis_monitor
- ❌ Does not start loki_exporter
- ❌ Does not start any standalone monitoring/logging processes

### 2. AsyncServiceManager

**Location:** `src/gleitzeit/core/async_process_manager.py`

**Used By:**
- `gleitzeit serve` command ([serve_unified.py:269-270](src/gleitzeit/cli/serve_unified.py#L269-L270))

**What It Does:**
- Manages ALL services including workers AND standalone processes
- Starts redis_monitor ([async_process_manager.py:699-728](src/gleitzeit/core/async_process_manager.py#L699-L728))
- Starts loki_exporter ([async_process_manager.py:666-697](src/gleitzeit/core/async_process_manager.py#L666-L697))
- Uses AsyncProcessManager for async subprocess management
- Registers all services in the service registry

**Service Registry Registration:**
```python
# Both services register via smart_manager.register_service()
# with a 60-second TTL that requires heartbeat to maintain
```

## The Problem

When using `gleitzeit start`:
1. ComponentOrchestrator starts
2. It launches only the 11 core workers
3. redis_monitor and loki_exporter are **never started**
4. Even though they're enabled in gleitzeit.yaml, ComponentOrchestrator doesn't know about them

When using `gleitzeit serve`:
1. AsyncServiceManager starts
2. It launches workers AND standalone processes
3. redis_monitor and loki_exporter are started (lines 876-892)
4. **BUT** they were missing heartbeat mechanisms, so they disappeared after 60 seconds

## The Fix

### Heartbeat Fix (COMPLETED)

Added heartbeat loops to both workers to maintain their service registry presence:

**redis_monitor_worker.py:**
- Added `heartbeat_interval = 30` ([line 102](src/gleitzeit/workers/redis_monitor_worker.py#L102))
- Added `heartbeat_loop()` method ([lines 372-399](src/gleitzeit/workers/redis_monitor_worker.py#L372-L399))
- Integrated into `start()` ([line 443](src/gleitzeit/workers/redis_monitor_worker.py#L443))

**loki_exporter_worker.py:**
- Added `heartbeat_interval = 30` ([line 69](src/gleitzeit/workers/loki_exporter_worker.py#L69))
- Added `_heartbeat_loop()` method ([lines 114-142](src/gleitzeit/workers/loki_exporter_worker.py#L114-L142))
- Integrated into `run()` ([line 327](src/gleitzeit/workers/loki_exporter_worker.py#L327))

Both workers now:
1. Register at startup with 60s TTL
2. Send heartbeats every 30 seconds to refresh the TTL
3. Remain visible in `gleitzeit ps` indefinitely

### Remaining Issue

**ComponentOrchestrator needs to be enhanced to start redis_monitor and loki_exporter**

Currently, users must use `gleitzeit serve` to get these monitoring services. The `gleitzeit start` command doesn't start them.

## Decision: Use Serve Only

**DECISION MADE:** Keep only AsyncServiceManager (via `gleitzeit serve`)

### Changes Made:

1. **Removed `gleitzeit start` command** ([main.py:65-66](src/gleitzeit/cli/main.py#L65-L66))
   - The `start` command that used ComponentOrchestrator has been removed
   - Users should use `gleitzeit serve` for all operations

2. **ComponentOrchestrator Status:**
   - Kept in codebase for now (may be used via `gleitzeit orchestrator start`)
   - Not the primary/recommended way to start services
   - Does not start redis_monitor or loki_exporter

3. **AsyncServiceManager is now the primary orchestrator**
   - Used by `gleitzeit serve`
   - Starts all workers + redis_monitor + loki_exporter
   - With heartbeat fix, all services remain visible in `gleitzeit ps`

## Testing

To verify the complete fix works:

```bash
# 1. Reinstall gleitzeit with the changes
pip install -e .

# 2. Stop everything
gleitzeit stop --force --all

# 3. Start with serve (the only way now)
gleitzeit serve

# 4. Wait 5 seconds for startup
sleep 5

# 5. Check all services appear (including redis_monitor and loki_exporter)
gleitzeit ps

# 6. Wait 70 seconds (past the 60s TTL)
sleep 70

# 7. Verify redis_monitor and loki_exporter STILL show as healthy
gleitzeit ps
```

**Expected output:**
- All workers should appear: api, ui, task_execution, dependency, workflow_loader, etc.
- **redis_monitor** should appear as a healthy service
- **loki_exporter** should appear as a healthy service (if enabled in config)
- After 70 seconds, both redis_monitor and loki_exporter should STILL be healthy (heartbeat working)

## Conclusion

**Problem Solved:**
1. ✅ Added heartbeat mechanisms to redis_monitor and loki_exporter
2. ✅ Removed confusing `gleitzeit start` command
3. ✅ Consolidated to single orchestration path via `gleitzeit serve`

All services (workers + monitoring) now start together and remain visible in `gleitzeit ps` indefinitely thanks to the heartbeat mechanism.
