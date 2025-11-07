# Worker and Service Lifecycle Management Audit

**Date:** 2025-10-22
**Version:** 0.0.7
**Status:** Critical Issues Found

## Executive Summary

This audit documents critical issues in worker lifecycle management, specifically around the heartbeat mechanism that maintains worker registry entries. The primary issue is that certain workers (workflow_loader, ui_worker) experience silent heartbeat failures, causing them to become invisible to the system despite continuing to run.

## Critical Issues

### 1. Workflow Loader Worker Heartbeat Failure

**Severity:** CRITICAL - Blocks all workflow processing
**Status:** UNRESOLVED - Unretryable Error

#### Symptoms
- Worker process starts successfully and registers with 60s TTL
- Initial registration succeeds (visible in logs)
- Heartbeat loop silently fails after initial registration
- Registry entry expires after 60 seconds
- Worker process continues running but disappears from `gleitzeit ps`
- Workflows cannot be processed without active registry entry

#### Evidence
```bash
# Process is running
$ ps aux | grep workflow_loader
leifmarkthaler    7788   0.0  0.3 411193312  56000   ??  SNs   9:37PM   0:00.34 /opt/homebrew/Caskroom/miniconda/base/bin/python -m gleitzeit.workers.runner --config-key worker:config:workflow_loader-async:c30ee1b0 --redis-url redis://localhost:6379

# But NOT in registry
$ gleitzeit ps
# workflow_loader missing from output

# Registry key doesn't exist
$ redis-cli exists "{shard:0}:worker:registry:workflow_loader:workflow_loader-async"
(integer) 0

$ redis-cli ttl "{shard:0}:worker:registry:workflow_loader:workflow_loader-async"
(integer) -2  # Key doesn't exist
```

#### Logs Analysis
```
2025-10-22 21:37:09,441 - INFO - ✅ Started worker_workflow_loader (PID: 7788, Logs: Redis only)
2025-10-22 21:37:09,442 - INFO - Registered service worker_workflow_loader in registry with 60s TTL
# After this, no further heartbeat updates
# Worker becomes invisible after 60 seconds
```

#### Impact
- **10,000 workflow stress test:** All workflows stuck in pending state
- **Zero completion rate** over 2 minutes of monitoring
- Worker restart temporarily fixes issue but failure recurs
- System appears healthy but workflows cannot execute

#### Affected Files
- [src/gleitzeit/workers/workflow_loader_worker_v2.py](../src/gleitzeit/workers/workflow_loader_worker_v2.py) - Worker implementation
- [src/gleitzeit/workers/base.py](../src/gleitzeit/workers/base.py):491 - Heartbeat loop implementation
- [src/gleitzeit/core/async_process_manager.py](../src/gleitzeit/core/async_process_manager.py) - Process startup

### 2. UI Worker Heartbeat Failure

**Severity:** HIGH - Affects UI availability
**Status:** RECURRING - Same pattern as workflow_loader

#### Symptoms
- Identical pattern to workflow_loader issue
- Process running but not sending heartbeats
- Killed by signal -30 (SIGUSR1) during investigation
- Auto-restart successful

#### Evidence
```
2025-10-22 17:28:24,921 - ERROR - Process worker_ui died with code -30
2025-10-22 17:28:24,921 - ERROR - Worker worker_ui died with exit code -30
2025-10-22 17:28:24,921 - INFO - Attempting to restart worker_ui (attempt 1/3)
2025-10-22 17:28:25,427 - INFO - ✅ Started worker_ui (PID: 84039, Logs: Redis only)
```

## Worker Lifecycle Components

### 1. Process Manager (async_process_manager.py)

**Responsibilities:**
- Start worker processes
- Monitor process health
- Restart failed workers (up to 3 attempts)
- Register workers in service registry with 60s TTL

**Key Patterns:**
```python
# Worker startup
INFO - Starting worker workflow_loader-async with config key worker:config:workflow_loader-async:36778286
INFO - Starting worker_workflow_loader: /opt/homebrew/Caskroom/miniconda/base/bin/python -m gleitzeit.workers.runner --config-key worker:config:workflow_loader-async:36778286 --redis-url redis://localhost:6379
INFO - ✅ Started worker_workflow_loader (PID: 77885, Logs: Redis only)
INFO - Registered service worker_workflow_loader in registry with 60s TTL
```

**Issues Found:**
- Initial registration succeeds
- No detection of heartbeat failures
- Process appears "running" even when heartbeat fails
- No automatic recovery when heartbeat stops

### 2. BaseWorker Heartbeat (_heartbeat_loop)

**Location:** [src/gleitzeit/workers/base.py:491](../src/gleitzeit/workers/base.py#L491)

**Mechanism:**
```python
async def _heartbeat_loop(self):
    """Periodically refresh worker registration"""
    while self.running:
        try:
            await self._register_worker()  # Refresh TTL
            await self.redis.hset()        # Update metrics
            await asyncio.sleep(self.config.heartbeat_interval)  # Default: 60s
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")
            # Retries on next iteration
```

**Expected Behavior:**
- Loop runs every 60 seconds
- Calls `_register_worker()` to refresh TTL
- Updates metrics in Redis
- Continues indefinitely while worker is running

**Actual Behavior (workflow_loader):**
- Initial registration succeeds
- Loop appears to stop executing
- No errors logged to Redis or stdout/stderr
- Silent failure - no exception handling triggers

### 3. Worker Registration

**Registry Keys:**
```
{shard:0}:worker:registry:<worker_type>:<worker_id>
```

**Registry Data (HSET):**
```python
{
    "worker_type": "workflow_loader",
    "worker_id": "workflow_loader-async",
    "shards": [0, 1, 2, ...],
    "started_at": "2025-10-22T15:11:29.693766",
    "status": "running",
    "host": "localhost",
    "pid": 8589511680
}
```

**TTL Mechanism:**
- Each worker has 60-second TTL
- Must be refreshed by heartbeat every ~60 seconds
- If TTL expires, key disappears from Redis
- Worker becomes invisible to `gleitzeit ps`

## Worker-Specific Patterns

### API Worker (Working Correctly)

**Implementation:** [src/gleitzeit/workers/api_worker.py](../src/gleitzeit/workers/api_worker.py)

**Pattern:**
```python
class APIWorker(BaseWorker):
    async def run(self):
        # Create heartbeat task independently
        self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        # Start Uvicorn server
        config = uvicorn.Config(app, host=host, port=port)
        server = uvicorn.Server(config)
        await server.serve()
```

**Status:** Healthy - appears in registry consistently

### Workflow Loader Worker (Failing)

**Implementation:** [src/gleitzeit/workers/workflow_loader_worker_v2.py](../src/gleitzeit/workers/workflow_loader_worker_v2.py)

**Pattern:**
```python
class WorkflowLoaderWorkerV2(BaseWorker):
    # Does NOT override run()
    # Uses default BaseWorker.run() implementation

    def get_base_streams(self):
        return ["workflow:load", "workflow:reload"]

    async def process_message(self, stream, message_id, data):
        # Process workflow loading
        ...
```

**Status:** Heartbeat fails - disappears from registry after 60s

### Task Execution Worker (Working Correctly)

**Status:** Healthy - appears in registry consistently

### Dependency Worker (Working Correctly)

**Status:** Healthy - appears in registry consistently

## System Statistics

### Stress Test Results

**10k Workflow Submission Test:**
- Submitted: 10,000 workflows
- Submission time: 7.60 seconds
- Submission rate: 1,316 workflows/second
- Errors: 0

**10k Workflow Completion Test:**
- Initial queue: 10,000 workflows (post stress test)
- After workflow_loader restart: 0 workflows (all processed)
- Completion rate: Could not measure - workflows stuck when heartbeat fails

**20 Workflow Test (Earlier):**
- Completed: 20 workflows
- Time: 1.69 seconds
- Rate: 84ms per workflow

### Worker Registry Health

**Healthy Workers (Consistent in `gleitzeit ps`):**
- worker_api (PID 77858)
- worker_task_execution (PID 77864)
- worker_dependency (PID 77882)
- worker_python_specialist (PID 77889)
- worker_workflow_submission (PID 77897)
- worker_retry (PID 77909)
- worker_timer (PID 77930)
- worker_signal (PID 77933)
- worker_reconciliation (PID 77936)
- redis_monitor

**Unhealthy Workers (Disappear from registry):**
- worker_workflow_loader (PID 7788) - CRITICAL
- worker_ui (Previously PID 84039) - HIGH

## Timeline of Investigation

**17:11:27** - System startup, 11 workers started
**17:11:30** - workflow_loader started (PID 77885), registered with 60s TTL
**17:28:24** - UI worker died (exit code -30, caused by debugging signal)
**17:28:25** - UI worker auto-restarted (PID 84039)
**~17:12:30** - workflow_loader likely disappeared from registry (60s after startup)
**17:40:00** - 10k stress test submitted successfully
**17:42:00** - Monitoring shows 89,212 workflows pending, zero completing
**17:42:00** - Investigation: workflow_loader process running but not in registry
**21:37:08** - Killed workflow_loader (exit code -9)
**21:37:09** - workflow_loader auto-restarted (PID 7788), registered with 60s TTL
**21:37:15** - All 10k workflows processed (queue cleared to 0)
**21:38:30** - workflow_loader disappeared from registry again
**21:39:00** - New test workflow stuck in pending state

## Root Cause Analysis

### Hypothesis 1: BaseWorker.run() Implementation Difference

**Theory:** Workers that override `run()` method handle heartbeat differently

**Evidence:**
- API worker overrides `run()` - creates heartbeat task explicitly
- workflow_loader does NOT override `run()` - uses default BaseWorker implementation
- Need to examine BaseWorker.run() to see default heartbeat handling

**Status:** Requires code review of [src/gleitzeit/workers/base.py](../src/gleitzeit/workers/base.py)

### Hypothesis 2: Stream Processing Blocking Heartbeat

**Theory:** Long-running `process_message()` blocks heartbeat loop

**Evidence:**
- workflow_loader processes from streams: "workflow:load", "workflow:reload"
- process_message() does significant work (loading, transforming, validating workflows)
- If process_message() is blocking and heartbeat is in same event loop, heartbeat could be delayed

**Counterevidence:**
- Heartbeat should be separate asyncio task
- No workflows in queue when issue occurs, so nothing to block

**Status:** Less likely, but worth investigating async task management

### Hypothesis 3: Exception in _register_worker()

**Theory:** Heartbeat loop encounters exception in _register_worker() that isn't logged

**Evidence:**
- BaseWorker._heartbeat_loop() has try/except around registration
- Exceptions should be logged, but no errors visible in Redis logs
- Possibly exception handling is too broad or logging fails

**Next Steps:**
- Add DEBUG logging to _register_worker()
- Add DEBUG logging to _heartbeat_loop() iteration
- Check if logging itself is failing

**Status:** Most likely - requires adding instrumentation

### Hypothesis 4: Redis Connection Issues

**Theory:** Worker's Redis connection becomes stale/broken for heartbeat

**Evidence:**
- Process has multiple Redis connections (6 shown by lsof)
- If heartbeat uses a specific connection that fails, registration would stop
- Other Redis operations might still work

**Counterevidence:**
- Would expect connection errors to be logged
- Other workers using similar patterns work fine

**Status:** Possible - check Redis connection pooling

## Recommendations

### Immediate Actions

1. **Add Comprehensive Heartbeat Logging**
   - Add DEBUG logs at start of each _heartbeat_loop() iteration
   - Add DEBUG logs in _register_worker() showing TTL refresh
   - Add exception details with traceback to error logs
   - Location: [src/gleitzeit/workers/base.py:491](../src/gleitzeit/workers/base.py#L491)

2. **Implement Heartbeat Health Check**
   - Add timestamp of last successful heartbeat to worker metrics
   - Process manager should monitor heartbeat timestamps
   - Alert/restart when heartbeat hasn't updated in >60 seconds
   - Location: [src/gleitzeit/core/async_process_manager.py](../src/gleitzeit/core/async_process_manager.py)

3. **Add Heartbeat Recovery Mechanism**
   - If heartbeat fails, attempt to recreate Redis connection
   - If heartbeat fails 3 times, exit worker process (trigger auto-restart)
   - Better to restart than run invisible to system

### Short-term Fixes

1. **Worker Health Monitoring Service**
   - Create dedicated service that checks registry every 30 seconds
   - Compare running processes to registry entries
   - Alert on mismatches
   - Automatically restart workers missing from registry

2. **Graceful Degradation**
   - Workers should exit if they detect heartbeat failure
   - Better to crash and restart than run in degraded state
   - Add self-health check every 2-3 heartbeat intervals

3. **Enhanced Process Manager**
   - Monitor not just process existence, but registry presence
   - Detect "zombie" workers (process running, no registry entry)
   - Automatic kill+restart for zombie workers

### Long-term Improvements

1. **Unified Worker Lifecycle Pattern**
   - Standardize how all workers handle run() method
   - Ensure heartbeat is always independent asyncio task
   - Document required patterns for custom workers

2. **Distributed Worker Registry**
   - Consider using Redis Sentinel or separate health check service
   - Reduce dependency on single TTL mechanism
   - Add redundancy for critical worker tracking

3. **Observability Improvements**
   - Metrics for heartbeat success/failure rates
   - Alerts for workers missing from registry
   - Dashboard showing worker health over time
   - Integrate with Loki for centralized logging

4. **Testing Infrastructure**
   - Unit tests for heartbeat mechanism
   - Integration tests that verify workers stay registered
   - Chaos testing: kill Redis connections, delay heartbeats
   - Automated detection of heartbeat regressions

## Configuration Review

### Current Heartbeat Configuration

**Default Interval:** 60 seconds
**Registry TTL:** 60 seconds
**Problem:** No buffer between heartbeat interval and TTL

**Recommendation:**
- Change TTL to 90 or 120 seconds
- Keep heartbeat interval at 60 seconds
- Provides buffer for transient issues

### Worker Configuration Files

**Location:** Redis keys
```
worker:config:workflow_loader-async:<hash>
```

**Issues:**
- Configuration stored in Redis (ephemeral)
- No version control of worker configs
- Difficult to audit configuration changes

**Recommendation:**
- Move core worker config to gleitzeit.yaml
- Keep only instance-specific data in Redis
- Enable configuration auditing

## Testing Recommendations

### Heartbeat Stress Test

```python
# Test continuous heartbeat under load
async def test_heartbeat_under_load():
    """Submit 10k workflows and verify worker stays registered"""
    # Submit 10k workflows
    # Monitor worker registry every 10 seconds for 5 minutes
    # Assert worker never disappears from registry
    # Assert all workflows complete
```

### Heartbeat Recovery Test

```python
# Test heartbeat recovery from Redis connection failure
async def test_heartbeat_recovery():
    """Simulate Redis connection failure during heartbeat"""
    # Start worker
    # Verify registered
    # Block Redis connection
    # Wait 70 seconds
    # Unblock Redis connection
    # Verify worker recovers and re-registers
```

### Zombie Worker Detection Test

```python
# Test detection of zombie workers
async def test_zombie_detection():
    """Verify system detects workers without registry entries"""
    # Start worker
    # Manually delete registry entry
    # Wait for detection (should be < 60 seconds)
    # Verify worker is restarted
    # Verify new worker has registry entry
```

## Related Issues

### Timezone Bug (RESOLVED)

**Issue:** Workers showed incorrect uptime due to UTC/local time mismatch
**Fix:** Changed [src/gleitzeit/cli/ps_command.py:80,127](../src/gleitzeit/cli/ps_command.py#L80) to use `datetime.utcnow()`
**Impact:** Display only, did not affect worker functionality

### Hardcoded Docker Mode (RESOLVED)

**Issue:** All workers showed `mode='docker'` regardless of actual deployment
**Fix:** Changed [src/gleitzeit/cli/ps_command.py:142](../src/gleitzeit/cli/ps_command.py#L142) to read from worker_info
**Impact:** Display only, did not affect worker functionality

## Conclusion

The worker lifecycle management system has a critical unresolved issue with heartbeat failures in specific workers (workflow_loader, ui_worker). The pattern is:

1. Worker starts successfully
2. Initial registration succeeds
3. Heartbeat loop silently fails
4. Registry entry expires after 60 seconds
5. Worker continues running but is invisible to system

**This is classified as an UNRETRYABLE ERROR** per CLAUDE.md project instructions.

The root cause requires deeper investigation into the BaseWorker._heartbeat_loop() implementation and why it fails for certain worker types. Immediate mitigation requires adding comprehensive logging and implementing health monitoring that detects zombie workers.

**Priority:** CRITICAL - Blocks core workflow processing functionality

## Files Referenced

- [src/gleitzeit/workers/base.py](../src/gleitzeit/workers/base.py) - BaseWorker heartbeat implementation
- [src/gleitzeit/workers/workflow_loader_worker_v2.py](../src/gleitzeit/workers/workflow_loader_worker_v2.py) - Failing worker
- [src/gleitzeit/workers/api_worker.py](../src/gleitzeit/workers/api_worker.py) - Working pattern reference
- [src/gleitzeit/workers/ui_worker.py](../src/gleitzeit/workers/ui_worker.py) - Also experiencing failures
- [src/gleitzeit/core/async_process_manager.py](../src/gleitzeit/core/async_process_manager.py) - Process lifecycle
- [src/gleitzeit/cli/ps_command.py](../src/gleitzeit/cli/ps_command.py) - Registry monitoring
- [gleitzeit.yaml](../gleitzeit.yaml) - System configuration

## Appendix: Commands Used During Investigation

```bash
# Check worker registry
gleitzeit ps

# Check running processes
ps aux | grep workflow_loader

# Check Redis registry keys
redis-cli keys "*workflow_loader*"
redis-cli exists "{shard:0}:worker:registry:workflow_loader:workflow_loader-async"
redis-cli ttl "{shard:0}:worker:registry:workflow_loader:workflow_loader-async"

# Check pending workflows
redis-cli llen "{shard:0}:workflows:pending"

# Check worker connections
lsof -p <PID> | grep Redis

# Monitor workflow completion
python monitor_completion.py

# Restart worker
kill -9 <PID>  # Process manager auto-restarts
```
