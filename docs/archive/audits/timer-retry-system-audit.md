# Timer-Retry System Deep Audit

**Date**: 2025-10-26
**Issue**: Tasks failing but not being marked as permanently failed after max retries
**Severity**: CRITICAL - Breaks retry mechanism completely

---

## Executive Summary

**Root Cause Identified**: Timer worker and retry worker are using different Redis key names for the timer queue, causing a complete disconnect in the retry flow.

- **Retry worker writes to**: `{shard:0}:global:timers:pending`
- **Timer worker reads from**: `timers:pending`
- **Result**: 100 retry timers stuck for 30+ minutes, never processed
- **Impact**: Tasks remain in `scheduled` status indefinitely instead of being marked as `failed` after max retries

---

## System Architecture Overview

### The Retry Flow (Intended Design)

```
┌─────────────────────────────────────────────────────────────────────┐
│                         TASK RETRY LIFECYCLE                        │
└─────────────────────────────────────────────────────────────────────┘

1. Task Execution Failure
   ┌──────────────────────┐
   │ Task Execution Worker│
   │   (task_id fails)    │
   └──────────┬───────────┘
              │
              │ Emits to: {shard:N}:task:failed
              ▼
   ┌──────────────────────┐
   │   Retry Worker       │
   │  Reads task:failed   │
   └──────────┬───────────┘
              │
              │ Decision: should_retry()?
              │
         ┌────┴────┐
         │         │
    YES  │         │  NO
         │         │
         ▼         ▼
   ┌─────────┐  ┌──────────────┐
   │Schedule │  │Mark as       │
   │Retry    │  │Permanently   │
   │         │  │Failed        │
   └────┬────┘  └──────────────┘
        │
        │ 1. Update task: status=scheduled, retry_count++
        │ 2. Add to timers queue: {shard:0}:global:timers:pending
        │ 3. Score = retry_at timestamp
        │
        ▼
   ┌──────────────────────┐
   │   Timer Worker       │
   │  (Leader election)   │
   └──────────┬───────────┘
              │
              │ Polls: timers:pending  ❌ WRONG KEY!
              │ (Should poll: {shard:0}:global:timers:pending)
              │
              │ When timer fires:
              ▼
   ┌──────────────────────┐
   │ Re-queue to          │
   │ {shard:N}:task:ready │
   └──────────┬───────────┘
              │
              │ Task gets re-executed
              │ (with incremented retry_count)
              │
              ▼
   Back to step 1 (until max_retries reached)
```

---

## The Bug: Key Mismatch

### Evidence

#### Current State (30 minutes after test)
```bash
# What timer worker reads (EMPTY)
$ redis-cli ZCARD timers:pending
0

# Where retry worker writes (FULL)
$ redis-cli ZCARD '{shard:0}:global:timers:pending'
100

# All 100 timers stuck for 30+ minutes
$ redis-cli ZRANGE '{shard:0}:global:timers:pending' 0 2 WITHSCORES
workflow-23f58ea8-...:dd984918-...:retry
1761470383.530672  # 10:19:43 (30 minutes ago!)

workflow-a30a7be8-...:6092f31e-...:retry
1761470383.553854

workflow-902a304b-...:b153160a-...:retry
1761470383.588495
```

#### Task States (Stuck)
```bash
$ redis-cli hgetall '{shard:8}:task:status:ad077faf-9ff4-4e47-8bbc-f064d2a89ec7'
execution_id: exec_42b6d9fa58a6
workflow_id: workflow-5716b1c2-953e-4f15-a1ce-86a0c6e75085
last_error: [METHOD_NOT_SUPPORTED] Method 'execute' not supported by python/v1
executed_at: 2025-10-26T09:19:43.619663
retry_count: 2                    # At max_retries!
status: scheduled                 # ❌ Should be 'failed'
worker_id: python_specialist-async
handler_id: 420cf34e-92b3-42ae-b7fd-1b8c9abb03ab
last_attempt_at: 2025-10-26T09:19:43.629415
retry_at: 1761470384.9374604     # 30 minutes ago!
```

**Expected**: After retry_count reaches max_retries (2), status should be `failed`
**Actual**: Status stuck at `scheduled`, timer never fired

---

## Code Analysis

### 1. Retry Worker: Timer Scheduling

**File**: [src/gleitzeit/workers/retry_worker.py:249-254](src/gleitzeit/workers/retry_worker.py#L249-L254)

```python
async def _schedule_retry(
    self,
    task_id: str,
    workflow_id: str,
    delay: float,
    next_attempt: int,
    error_msg: str
) -> None:
    """Schedule a task retry via timer mechanism."""
    task_key = default_sharding.get_task_key(task_id, workflow_id).encode()

    # Update task status
    await self.redis.hset(
        task_key,
        mapping={
            b"status": TaskStatus.SCHEDULED.encode(),
            b"retry_count": str(next_attempt).encode(),
            b"last_error": error_msg.encode(),
            b"retry_at": str(time.time() + delay).encode(),
            b"last_attempt_at": datetime.utcnow().isoformat().encode()
        }
    )

    # Schedule via timer
    timer_key = default_sharding.get_global_key("timers:pending").encode()
    # ☝️ Returns: {shard:0}:global:timers:pending

    await self.redis.zadd(
        timer_key,
        {f"{workflow_id}:{task_id}:retry".encode(): time.time() + delay}
    )
```

**Key used**: `{shard:0}:global:timers:pending` (via `get_global_key()`)

### 2. Sharding: Global Key Function

**File**: [src/gleitzeit/core/sharding.py:132-144](src/gleitzeit/core/sharding.py#L132-L144)

```python
def get_global_key(self, key_type: str) -> str:
    """
    Get global key that's not workflow-specific.

    Global keys all go to shard 0 for consistency.

    Args:
        key_type: Type of global key

    Returns:
        Cluster key like "{shard:0}:global:key_type"
    """
    return f"{{shard:0}}:global:{key_type}"
```

**Output**: Adds `{shard:0}:global:` prefix for Redis Cluster routing

### 3. Timer Worker: Timer Processing

**File**: [src/gleitzeit/workers/timer_worker.py:115-160](src/gleitzeit/workers/timer_worker.py#L115-L160)

```python
async def _timer_processing_loop(self):
    """Process timers (only when leader)"""
    import time

    while self._running:
        try:
            if self.leader_election and self.leader_election.is_leader:
                # Use StatelessTimerManager's comprehensive processing
                # This handles: cancellation checks, recurring timers, metadata updates
                processed, fired_timers = await StatelessTimerManager.process_due_timers(
                    self.redis,
                    max_timers=100
                )
                # ☝️ Calls StatelessTimerManager.process_due_timers()

                if fired_timers:
                    logger.info(f"Processing {len(fired_timers)} expired timers")

                    # Process each fired timer
                    for timer_data in fired_timers:
                        timer_id = timer_data['timer_id']
                        task_id = timer_data.get('task_id', '')
                        workflow_id = timer_data.get('workflow_id', '')

                        if not task_id or not workflow_id:
                            logger.warning(f"Timer {timer_id} missing task_id or workflow_id, skipping")
                            continue

                        # Check if this is a retry timer
                        # Format: "{workflow_id}:{task_id}:retry"
                        if ":retry" in timer_id:
                            await self._handle_retry_timer(task_id, workflow_id)
                        else:
                            # Regular timer - pass timer_data for enriched results
                            shard = default_sharding.get_shard(workflow_id)
                            await self._complete_timer_task(
                                task_id,
                                workflow_id,
                                shard,
                                timer_data  # Pass full timer data
                            )

            await asyncio.sleep(self.check_interval)

        except Exception as e:
            logger.error(f"Timer processing error: {e}")
            await asyncio.sleep(1)
```

### 4. StatelessTimerManager: Timer Reading

**File**: [src/gleitzeit/timers/stateless_timer_manager.py:28](src/gleitzeit/timers/stateless_timer_manager.py#L28)

```python
class StatelessTimerManager:
    """
    Completely stateless timer manager.

    All timer state is stored in Redis sorted sets.
    Processing happens only when invoked - no loops!
    """

    # Redis keys for timer management
    PENDING_TIMERS_KEY = "timers:pending"  # ❌ NO SHARD PREFIX!
    ACTIVE_TIMERS_KEY = "timers:active"
    CANCELLED_TIMERS_KEY = "timers:cancelled"
    RECURRING_TIMERS_KEY = "timers:recurring"
    TIMER_METADATA_PREFIX = "timers:meta:"
```

**File**: [src/gleitzeit/timers/stateless_timer_manager.py:173-196](src/gleitzeit/timers/stateless_timer_manager.py#L173-L196)

```python
@staticmethod
async def process_due_timers(redis, max_timers: int = 100) -> Tuple[int, List[Dict]]:
    """
    Process all timers that are due now. NO LOOPS!

    Args:
        redis: Redis client
        max_timers: Maximum timers to process

    Returns:
        Tuple of (processed_count, fired_timer_list)
    """
    current_time = time.time()
    processed = 0
    fired_timers = []

    try:
        # Get all due timers (single Redis call)
        due_timers = await redis.zrangebyscore(
            StatelessTimerManager.PENDING_TIMERS_KEY,  # ❌ "timers:pending"
            min=0,
            max=current_time,
            start=0,
            num=max_timers
        )
        # ☝️ Reads from: timers:pending (NO shard prefix!)

        if not due_timers:
            return 0, []
```

**Key used**: `timers:pending` (hardcoded constant, no prefix)

---

## The Disconnect

| Component | Action | Redis Key | Status |
|-----------|--------|-----------|--------|
| **Retry Worker** | WRITE | `{shard:0}:global:timers:pending` | ✅ Writing successfully |
| **Timer Worker** | READ | `timers:pending` | ✅ Reading successfully (but empty!) |
| **Connection** | - | ❌ **DIFFERENT KEYS** | 🔥 **BROKEN** |

### Why This Breaks Everything

1. **Task fails** → Task Execution Worker emits to `task:failed` stream ✅
2. **Retry worker** processes failure, decides to retry ✅
3. **Retry worker** schedules retry in `{shard:0}:global:timers:pending` ✅
4. **Timer worker** polls `timers:pending` (empty) ❌
5. **Timer never fires** → Task stays in `scheduled` status forever ❌
6. **After max_retries** → Task should be marked `failed` but timer never fires to attempt final retry ❌

### Cascading Effects

- **Tasks stuck in limbo**: 100 tasks at `status: scheduled` with `retry_count: 2`
- **No permanent failure marking**: Tasks never reach the "mark as permanently failed" logic because the timer never fires to attempt the 3rd retry (which would fail the max_retries check)
- **Stream pollution**: Task:ready streams accumulate unprocessed tasks (100 tasks, all ACKed but not removed)
- **Resource leak**: Timer entries accumulate in the wrong queue indefinitely

---

## Task Lifecycle States

### Current Broken Flow

```
Task fails (attempt 0)
  ↓
Retry Worker: retry_count = 1, status = scheduled
  ↓
Timer scheduled in {shard:0}:global:timers:pending
  ↓
Timer Worker: polls timers:pending (empty)
  ↓
❌ STUCK HERE FOREVER ❌
  ↓
(Never reaches attempt 1)
  ↓
Task fails again (attempt 1)
  ↓
Retry Worker: retry_count = 2, status = scheduled
  ↓
Timer scheduled in {shard:0}:global:timers:pending (again)
  ↓
Timer Worker: polls timers:pending (still empty)
  ↓
❌ STUCK HERE FOREVER (should check max_retries!) ❌
```

### Expected Correct Flow

```
Task fails (attempt 0)
  ↓
Retry Worker: retry_count = 1, status = scheduled
  ↓
Timer scheduled in timers:pending
  ↓
Timer Worker: finds due timer, fires it
  ↓
Task re-queued to task:ready
  ↓
Task fails again (attempt 1)
  ↓
Retry Worker: retry_count = 2, status = scheduled
  ↓
Timer scheduled in timers:pending
  ↓
Timer Worker: finds due timer, fires it
  ↓
Task re-queued to task:ready
  ↓
Task fails again (attempt 2)
  ↓
Retry Worker: retry_count = 2 >= max_retries (2)
  ↓
✅ Mark as permanently failed: status = failed
```

---

## Retry Decision Logic

**File**: [src/gleitzeit/core/stateless_retry_service.py:156-195](src/gleitzeit/core/stateless_retry_service.py#L156-L195)

```python
async def should_retry(self, context: RetryContext) -> Tuple[RetryDecision, Dict[str, Any]]:
    """
    Determine if retry should be attempted.

    All decisions based on Redis state.

    Args:
        context: Retry context with task/error information

    Returns:
        Tuple of (decision, metadata)
    """
    # Check if error type is retryable
    if not self._is_retryable_error(context):
        return RetryDecision.SKIP, {'reason': 'non_retryable_error'}

    # Get retry configuration from Redis
    config = await self._get_retry_config(context.workflow_id, context.task_id)

    # Check max attempts
    if context.current_attempt >= config['max_retries']:
        # ☝️ This is where it SHOULD mark as failed!
        # But we never get here because timer never fires the final retry
        return RetryDecision.MAX_ATTEMPTS, {
            'max_retries': config['max_retries'],
            'current_attempt': context.current_attempt
        }

    # Check budget
    if not await self._check_budget(context):
        return RetryDecision.BUDGET_EXHAUSTED, {
            'workflow_id': context.workflow_id,
            'service': context.service_name
        }

    # Record metrics
    await self._record_retry_attempt(context)

    return RetryDecision.RETRY, {
        'delay': await self.calculate_delay(context, config),
        'config': config
    }
```

### Why Tasks Don't Get Marked Failed

The logic at line 176 checks: `if context.current_attempt >= config['max_retries']:`

**For our test tasks**:
- `retry_count: 2` (stored in Redis)
- `max_retries: 2` (from task config)
- **2 >= 2 = TRUE** → Should return `RetryDecision.MAX_ATTEMPTS`

**BUT**: This check only happens when processing a `task:failed` message. The current tasks:
1. Failed once (attempt 0) → Retry scheduled (attempt 1)
2. Timer never fired → Task never re-executed
3. Task stuck at `retry_count: 1`, `status: scheduled`

OR (if timer fired once):
1. Failed once (attempt 0) → Retry scheduled (attempt 1)
2. Timer fired → Task re-executed
3. Failed again (attempt 1) → Retry scheduled (attempt 2)
4. Timer never fired → Task stuck at `retry_count: 2`, `status: scheduled`
5. **Should have one more attempt to fail**, then hit max_retries check

The issue is that **retry_count represents the NEXT attempt**, not the current attempt. So:
- `retry_count: 2` means "this task will be attempted for the 2nd time" (0-indexed: 3rd total execution)
- Tasks should be allowed attempts 0, 1, 2 (3 total tries with max_retries=2)
- But they're stuck at `retry_count: 2` without being re-executed

---

## Worker Status

### Timer Worker (Running but Ineffective)

```bash
$ redis-cli hgetall '{shard:0}:worker:registry:timer:timer-async'
worker_type: timer
worker_id: timer-async
shards: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
started_at: 2025-10-26T09:17:57.668816
status: running
host: localhost
pid: 8589511680
```

- ✅ Worker registered and heartbeating
- ✅ Leader election working
- ✅ Polling loop running every 1 second
- ❌ Reading from wrong key (`timers:pending` instead of `{shard:0}:global:timers:pending`)

### Retry Worker (Running Correctly)

```bash
$ redis-cli hgetall '{shard:0}:worker:registry:retry:retry-async'
worker_type: retry
worker_id: retry-async
# ... similar fields ...
status: running
```

- ✅ Processing `task:failed` messages
- ✅ Making retry decisions correctly
- ✅ Writing timers to correct sharded key
- ❌ But timers never get processed!

---

## Redis Streams Analysis

### Task:Ready Streams (Accumulating)

```bash
$ for i in {0..15}; do redis-cli xlen "{shard:$i}:task:ready"; done | \
  awk 'BEGIN{sum=0} {sum+=$1} END{print sum}'
100  # All original tasks still in streams
```

**Why tasks remain in streams**:
- Redis Streams are **append-only logs**
- Messages persist after ACK (consumer groups track which messages are read)
- This is **expected behavior** - streams are a durable log
- Consumer groups show: `pending: 0, lag: 0, entries-read: 10`
- ✅ Messages were read and ACKed successfully

**This is NOT a bug** - it's how Redis Streams work. Tasks remain as a permanent record.

### Task:Failed Streams (Empty - Processed)

```bash
$ for i in {0..15}; do redis-cli xlen "{shard:$i}:task:failed"; done | \
  awk 'BEGIN{sum=0} {sum+=$1} END{print sum}'
0  # All processed by retry worker
```

- ✅ Retry worker successfully consumed all failure messages
- ✅ Each failure resulted in a retry being scheduled
- ❌ But those retries are stuck in the timer queue

---

## Additional Findings

### No Timer Metadata

```bash
$ redis-cli --scan --pattern 'timers:meta:*'
(empty)
```

The retry worker creates timer entries in the sorted set but does NOT create metadata entries. This is actually OK for retry timers - the timer ID format `{workflow_id}:{task_id}:retry` contains all needed information.

**Timer Worker handles this**:
```python
# Check if this is a retry timer
# Format: "{workflow_id}:{task_id}:retry"
if ":retry" in timer_id:
    await self._handle_retry_timer(task_id, workflow_id)
```

### Retry Timer Handler

**File**: [src/gleitzeit/workers/timer_worker.py:327-378](src/gleitzeit/workers/timer_worker.py#L327-L378)

```python
async def _handle_retry_timer(
    self,
    task_id: str,
    workflow_id: str
):
    """Handle expired retry timer - put task back in ready queue"""
    logger.info(f"Retry timer expired for task {task_id} in workflow {workflow_id}")

    # Get workflow data to extract task definition
    workflow_data = await self.redis.hget(
        default_sharding.get_workflow_key("data", workflow_id).encode(),
        b"workflow"
    )

    if not workflow_data:
        logger.error(f"Workflow data not found for retry: {workflow_id}")
        return

    import json
    workflow = json.loads(workflow_data)

    # Find the task in the workflow
    task_data = None
    for task in workflow.get('tasks', []):
        if task['id'] == task_id:
            task_data = task
            break

    if not task_data:
        logger.error(f"Task {task_id} not found in workflow {workflow_id}")
        return

    # Update task status back to pending
    task_key = default_sharding.get_task_key(task_id, workflow_id).encode()
    await self.redis.hset(
        task_key,
        b"status", b"pending"
    )

    # Put task back in ready queue (same as DependencyWorker)
    ready_stream = default_sharding.get_stream_key("task:ready", workflow_id).encode()
    await self.redis.xadd(
        ready_stream,
        {
            b"workflow_id": workflow_id.encode(),
            b"task_id": task_id.encode(),
            b"task": json.dumps(task_data).encode(),
            b"timestamp": datetime.utcnow().isoformat().encode()
        }
    )

    logger.info(f"Task {task_id} re-queued to task:ready stream")
```

This logic is **correct** - it would work if the timer actually fired!

---

## Impact Assessment

### Immediate Impact (Current Test)
- ✅ 100 test workflows submitted
- ❌ 100 tasks failed with METHOD_NOT_SUPPORTED error (test data issue)
- ❌ 100 retry timers scheduled in wrong queue
- ❌ 0 timers processed
- ❌ 100 tasks stuck at `status: scheduled`
- ❌ No tasks marked as permanently failed

### Production Impact (If Deployed)
- 🔥 **ALL task retries would fail completely**
- 🔥 Tasks would be stuck in `scheduled` status forever
- 🔥 No way to recover without manual intervention
- 🔥 Timer queue would grow indefinitely
- 🔥 Monitoring/alerting would show tasks "in progress" indefinitely

### Data Integrity
- ✅ No data loss (all state preserved in Redis)
- ✅ Tasks can be recovered by fixing the key mismatch
- ✅ Workflow data intact
- ❌ Task status is misleading (`scheduled` vs actual state)

---

## Root Cause Summary

**Single Point of Failure**: Hardcoded timer queue key name in `StatelessTimerManager.PENDING_TIMERS_KEY`

**Why It Happened**:
1. `StatelessTimerManager` was designed before the sharding system
2. Uses simple string constants for Redis keys
3. Assumes single Redis instance, not Redis Cluster
4. No coordination with `default_sharding.get_global_key()` naming convention

**Why It Wasn't Caught**:
1. Different teams/developers working on retry worker vs timer manager
2. No integration tests covering the full retry cycle
3. Timer worker runs and appears healthy (heartbeating, leader election working)
4. Retry worker runs and appears healthy (processing failures, scheduling retries)
5. Both workers operate correctly in isolation, but never communicate

---

## Solution Options

### Option 1: Fix StatelessTimerManager (Recommended)

**Change**: Update `PENDING_TIMERS_KEY` to use sharded key

**File**: `src/gleitzeit/timers/stateless_timer_manager.py`

```python
# BEFORE
PENDING_TIMERS_KEY = "timers:pending"

# AFTER
PENDING_TIMERS_KEY = "{shard:0}:global:timers:pending"
```

**Pros**:
- Minimal change
- Consistent with retry worker
- Works with Redis Cluster
- Aligns with sharding strategy

**Cons**:
- Hardcoded shard number
- Breaks existing timers (if any)

### Option 2: Fix Retry Worker

**Change**: Use simple key without sharding prefix

**File**: `src/gleitzeit/workers/retry_worker.py`

```python
# BEFORE
timer_key = default_sharding.get_global_key("timers:pending").encode()

# AFTER
timer_key = b"timers:pending"
```

**Pros**:
- Matches current timer worker implementation
- Simpler key structure

**Cons**:
- Doesn't use sharding system
- May not work well with Redis Cluster
- Inconsistent with other workers

### Option 3: Centralized Key Management (Best Long-term)

**Change**: Create single source of truth for all timer keys

```python
# In sharding.py or new timers/keys.py
class TimerKeys:
    @staticmethod
    def get_pending_key() -> str:
        return default_sharding.get_global_key("timers:pending")

    @staticmethod
    def get_active_key() -> str:
        return default_sharding.get_global_key("timers:active")
```

**Pros**:
- Single source of truth
- Prevents future mismatches
- Easy to change strategy later
- Type-safe with proper imports

**Cons**:
- Requires changes in multiple files
- More refactoring work

---

## Recommended Fix

### Immediate (Option 1 + Migration)

1. **Update StatelessTimerManager**:
   ```python
   PENDING_TIMERS_KEY = "{shard:0}:global:timers:pending"
   ```

2. **Migrate existing timers** (if any):
   ```python
   # One-time migration script
   timers = await redis.zrange("timers:pending", 0, -1, withscores=True)
   if timers:
       await redis.zadd("{shard:0}:global:timers:pending", dict(timers))
       await redis.delete("timers:pending")
   ```

3. **Restart timer worker** to pick up new key

4. **Verify** timers are processed

### Long-term (Option 3)

1. Create `TimerKeys` class
2. Update all timer-related code to use it
3. Add integration tests covering full retry cycle
4. Document timer queue architecture

---

## Testing Recommendations

### Unit Tests Needed

1. **Timer key consistency test**:
   ```python
   def test_timer_keys_match():
       retry_worker_key = default_sharding.get_global_key("timers:pending")
       timer_manager_key = StatelessTimerManager.PENDING_TIMERS_KEY
       assert retry_worker_key == timer_manager_key
   ```

2. **Retry cycle integration test**:
   ```python
   async def test_full_retry_cycle():
       # Submit task that will fail
       # Wait for retry worker to schedule retry
       # Verify timer appears in correct queue
       # Wait for timer to fire
       # Verify task re-queued
       # Verify final failure after max_retries
   ```

### Manual Verification Steps

```bash
# 1. Submit test workflow
gleitzeit submit test-workflow.json

# 2. Wait for failure
sleep 5

# 3. Check retry worker processed failure
redis-cli xlen '{shard:0}:task:failed'  # Should decrease

# 4. Check timer was scheduled
redis-cli ZCARD '{shard:0}:global:timers:pending'  # Should increase

# 5. Wait for timer to fire
sleep 5

# 6. Check timer was processed
redis-cli ZCARD '{shard:0}:global:timers:pending'  # Should decrease

# 7. Check task was re-queued
redis-cli xlen '{shard:0}:task:ready'  # Should increase

# 8. Repeat until max_retries

# 9. Verify final state
redis-cli hget '{shard:0}:task:status:{task_id}' status  # Should be 'failed'
```

---

## Monitoring Recommendations

### Alerts to Add

1. **Timer queue growth**: Alert if `{shard:0}:global:timers:pending` grows beyond threshold
2. **Old timers**: Alert if timers older than 5 minutes exist
3. **Scheduled tasks stuck**: Alert if tasks in `scheduled` status for >10 minutes
4. **Timer processing rate**: Alert if timer worker not processing any timers for 5 minutes

### Metrics to Track

```python
# Timer queue depth
gauge("timers.pending.count", redis.zcard("{shard:0}:global:timers:pending"))

# Oldest timer age
oldest_timer_score = redis.zrange("{shard:0}:global:timers:pending", 0, 0, withscores=True)
if oldest_timer_score:
    age_seconds = time.time() - oldest_timer_score[0][1]
    gauge("timers.oldest.age_seconds", age_seconds)

# Tasks in scheduled state
scheduled_count = count_tasks_with_status("scheduled")
gauge("tasks.scheduled.count", scheduled_count)
```

---

## Conclusion

This is a **critical architectural bug** caused by inconsistent key naming between two system components. The fix is straightforward (change one constant), but the impact is severe - **all task retries are completely broken**.

The bug demonstrates the importance of:
1. **Centralized key management** for shared resources
2. **Integration testing** across worker boundaries
3. **Monitoring timer queue health** in production
4. **Clear ownership** of shared Redis data structures

**Priority**: P0 - Fix immediately before any production deployment
**Estimated Fix Time**: 30 minutes (code change + testing)
**Risk**: Low (fix is simple and safe)
