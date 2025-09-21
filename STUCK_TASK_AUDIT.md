# Stuck Task Execution Audit

## Issue Summary

Tasks can become stuck in `EXECUTING` state without proper timeout enforcement or cleanup, leading to:
- Workflows appearing "stuck" indefinitely
- No automatic recovery mechanism
- Resource leaks in provider pools
- Poor user experience

## Root Cause Analysis

### 1. Task Execution Flow Gap

**Current Flow:**
```
TaskOrchestrator._schedule_task()
  → _execute_task_with_semaphore()
    → TaskExecutor.execute_task()
      → _update_task_status(EXECUTING) ✅ COMPLETED
      → _route_and_execute()
        → pooling_adapter.execute_task()
          → ProviderPoolManager.get_provider() ⚠️ CAN HANG HERE
            → ProviderPool.acquire() ⚠️ CAN HANG HERE
```

**Problem:** Task status is updated to `EXECUTING` BEFORE provider acquisition, but timeouts only apply AFTER successful acquisition.

### 2. Timeout Mechanism Analysis

#### Where Timeouts Work:
- `TaskExecutor._route_and_execute()` line 225: `asyncio.wait_for(timeout=300s)`
- Applied to `pooling_adapter.execute_task()`

#### Where Timeouts DON'T Work:
- Provider pool acquisition can hang indefinitely
- No timeout on `ProviderPool.acquire()` semaphore wait
- No timeout on provider instance creation
- Redis operations can hang without timeout

### 3. Provider Pool Bottlenecks

From `provider_pool.py:165-173`:
```python
await self._acquire_semaphore.acquire()  # ⚠️ NO TIMEOUT
```

From `provider_pool_manager.py:318`:
```python
return await pool.acquire(timeout)  # ⚠️ timeout passed but not enforced at semaphore level
```

## Specific Failure Points

### Point 1: Provider Creation Timeout Missing ⚠️ CRITICAL
**File:** `src/gleitzeit/providers/provider_pool.py:241-279` 
**Issue:** `_create_provider()` has NO timeout - can hang indefinitely
**Root Cause:** Provider creation involves:
- ProviderFactory creation and validation
- Provider class instantiation  
- Provider initialization
- None of these have timeouts
**Impact:** Task stuck waiting for provider that never gets created

### Point 2: Timeout Hierarchy Mismatch
**Files:** 
- `task_executor.py:227` - 300s timeout
- `pooling_adapter.py:237` - 30s timeout  
**Issue:** TaskExecutor expects 5min, but provider acquisition times out at 30s
**Impact:** Confusing timeout behavior, tasks fail unexpectedly

### Point 3: Semaphore Acquisition (ACTUALLY WORKS)
**File:** `src/gleitzeit/providers/provider_pool.py:167-171`  
**Status:** ✅ Timeout is properly implemented via `asyncio.wait_for`
**Note:** This was initially misidentified - the timeout IS enforced

### Point 4: ReconciliationService Detection Gap
**File:** `src/gleitzeit/system/reconciliation_service.py:322`
**Issue:** Only detects tasks stuck > 1 hour (3600s)
**Problem:** Tasks stuck in provider creation never get detected/cleaned up
**Current Stuck Task:** Been running 18+ minutes, won't be cleaned until 1 hour

## Current State Analysis

### ReconciliationService Limitations
- **Timeout:** 3600s (1 hour) - too long for stuck tasks
- **Scope:** Only checks tasks that have `started_at` timestamp
- **Frequency:** STARTUP mode runs once, PERIODIC every 5 minutes
- **Issue:** Tasks stuck in provider acquisition never get `started_at` set

### Task Status Inconsistency
```python
# TaskExecutor.execute_task() line 96
await self._update_task_status(task, TaskStatus.EXECUTING, task_start_time)
# ✅ Task marked as EXECUTING with started_at

# But if provider acquisition fails/hangs:
# ❌ Task never actually executes
# ❌ No timeout applies
# ❌ No cleanup occurs
```

## Audit Findings

### Critical Issues

1. **Gap Between Status Update and Execution**
   - Status updated optimistically before resource acquisition
   - No rollback mechanism if acquisition fails
   - Creates "zombie" EXECUTING tasks

2. **Missing Timeout Enforcement**
   - Semaphore acquisition has no timeout
   - Provider creation has no timeout  
   - Redis operations have no timeout

3. **Insufficient Cleanup**
   - ReconciliationService timeout too long (1 hour)
   - Doesn't detect tasks stuck in acquisition phase
   - No distinction between "executing" vs "acquiring resources"

4. **Resource Pool Exhaustion**
   - Failed provider creation reduces available pool
   - No health monitoring or recovery
   - Can lead to permanent service degradation

### Design Problems

1. **Pessimistic vs Optimistic Status Updates**
   - Current: Update status first, then try to execute
   - Better: Acquire resources first, then update status

2. **No Task State Machine**
   - Missing intermediate states like "ACQUIRING_RESOURCES"
   - Binary PENDING → EXECUTING transition hides complexity

3. **Timeout Hierarchy Issues**
   - Different timeout values at different layers
   - Some timeouts not enforced
   - No coordinated timeout strategy

## Impact Assessment

### Severity: HIGH

**User Impact:**
- Workflows appear stuck indefinitely
- No feedback on actual status
- Manual intervention required

**System Impact:**
- Resource leaks in provider pools
- Reduced system capacity over time
- Cascade failures as pools become exhausted

**Operational Impact:**
- Requires manual cleanup
- Difficult to diagnose
- No automated recovery

## Evidence from Current System

From Redis inspection:
```
Task ID: task-e74704a9
Status: executing  
Started: 2025-09-08T11:11:51.748542
Running for: 18+ minutes
Timeout: 0 (not set)
```

**Analysis:**
- Task has `started_at` timestamp (status update succeeded)
- But has been "executing" for 18+ minutes (way beyond 5min timeout)
- This proves execution never actually started
- Task is stuck in resource acquisition phase

## Root Cause Confirmed ✅

**Primary Issue:** `ProviderPool._create_provider()` has NO timeout

When a task tries to execute:
1. Status updated to EXECUTING ✅
2. TaskExecutor calls pooling_adapter.execute_task() with 300s timeout ✅  
3. PoolingAdapter calls get_provider() with 30s timeout ✅
4. ProviderPool.acquire() waits for semaphore with 30s timeout ✅
5. No available providers, so calls `_create_provider()` ❌ NO TIMEOUT
6. Provider creation hangs (ProviderFactory, instantiation, initialization)
7. Task appears "stuck in executing" forever

**Current Case:** Python provider creation likely hanging during initialization

## Immediate Fixes Required

### 1. Add Provider Creation Timeout ⚡ CRITICAL
```python
# In ProviderPool._create_provider()
async def _create_provider(self) -> PooledProvider:
    try:
        # Wrap entire creation process in timeout
        return await asyncio.wait_for(
            self._create_provider_impl(),
            timeout=30.0  # Match pooling adapter timeout
        )
    except asyncio.TimeoutError:
        raise ResourceExhaustedError(
            f"Provider creation timed out after 30s", 
            "provider_creation_timeout"
        )
```

### 2. Fix Timeout Hierarchy
- TaskExecutor: 300s (keep for actual execution)
- PoolingAdapter: 30s (for provider acquisition) 
- ProviderPool: 30s (for provider creation) ✅ NEW
- ReconciliationService: 300s (reduce from 3600s) ✅ NEW

### 3. Reduce ReconciliationService Timeout
```python
# In system_manager.py
task_timeout=300,  # 5 minutes instead of 1 hour
```

### 4. Add Provider Creation Monitoring
- Log provider creation attempts
- Track creation failures
- Monitor pool health

## Long-term Improvements

### 1. Provider Health Checks
- Periodic validation of provider instances
- Auto-restart failed providers
- Circuit breaker pattern for failing providers

### 2. Better Task States
```python
class TaskStatus(Enum):
    PENDING = "pending"
    ACQUIRING_RESOURCES = "acquiring_resources"  # NEW
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
```

### 3. Comprehensive Timeout Strategy
- Consistent timeout values across all layers
- Configurable timeouts per provider type
- Timeout monitoring and alerting

## Implementation Priority

**P0 (Critical - Deploy Today):**
- Add provider creation timeout
- Reduce reconciliation timeout

**P1 (High - This Week):**
- Fix timeout hierarchy consistency
- Add provider creation monitoring

**P2 (Medium - Next Sprint):**
- Provider health checks
- Enhanced task states
- Timeout configurability