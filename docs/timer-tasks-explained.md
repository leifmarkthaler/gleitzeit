# Timer Tasks: How They Work

**Date**: 2025-10-26
**Context**: Understanding regular timer tasks vs retry timers

---

## Overview

Gleitzeit supports two types of timers:

1. **Regular Timer Tasks** - User-facing timer functionality (sleep, wait_until, schedule)
2. **Retry Timers** - Internal retry mechanism for failed tasks

Both use the same timer infrastructure but have **different creation paths** and **the same critical bug**.

---

## Regular Timer Tasks Flow

### 1. Task Submission

A user submits a workflow with a timer task:

```json
{
  "tasks": [
    {
      "id": "sleep-task",
      "protocol": "timer/v1",
      "method": "timer/sleep",
      "params": {
        "duration": 5.0
      }
    }
  ]
}
```

### 2. Task Execution Worker Processes Task

**File**: [src/gleitzeit/handlers/timer.py:193-221](src/gleitzeit/handlers/timer.py#L193-L221)

The `TimerHandler` validates the task and returns a `SCHEDULED` status:

```python
async def _handle_sleep(self, task: Task) -> TaskResult:
    """Handle sleep task"""
    duration = task.params['duration']

    if duration <= 0:
        # Immediate completion for zero/negative duration
        return self.create_result(
            task=task,
            status=TaskStatus.COMPLETED,
            result={'slept': 0, 'actual_duration': 0}
        )

    # Calculate wake time
    wake_time = time.time() + duration

    logger.info(f"Task {task.id} scheduled to wake in {duration}s at {wake_time}")

    # Return SCHEDULED status for TimerWorker to handle
    return self.create_result(
        task=task,
        status=TaskStatus.SCHEDULED,
        metadata={
            'wake_time': wake_time,
            'duration': duration,
            'timer_type': 'sleep',
            'scheduled_at': time.time()
        }
    )
```

**Key Point**: The handler does **NOT** actually sleep. It just calculates the wake time and returns `SCHEDULED` status.

### 3. Task Execution Worker Emits Scheduled Event

**File**: [src/gleitzeit/workers/task_execution_worker.py:536-586](src/gleitzeit/workers/task_execution_worker.py#L536-L586)

When a task returns `SCHEDULED` status, the task execution worker:

```python
async def emit_task_scheduled(
    self,
    task_id: str,
    workflow_id: str,
    result: TaskResult
):
    """Emit task scheduled event for TimerWorker"""
    shard = default_sharding.get_shard(workflow_id)
    wake_time = result.metadata.get('wake_time', 0)

    # Calculate duration for logging only
    current_time = time.time()
    duration_seconds = wake_time - current_time

    # Update task status
    await self.redis.hset(
        default_sharding.get_task_key(task_id, workflow_id).encode(),
        mapping={
            b"status": TaskStatus.SCHEDULED.encode(),
            b"wake_time": str(wake_time).encode(),
            b"timer_type": result.metadata.get('timer_type', 'sleep').encode(),
            b"scheduled_at": datetime.utcnow().isoformat().encode()
        }
    )

    # Use StatelessTimerManager to create timer in sorted set
    # ⚠️ THIS IS WHERE THE BUG HAPPENS!
    timer_id = await StatelessTimerManager.create_timer(
        redis=self.redis,
        workflow_id=workflow_id,
        wake_time=wake_time,  # Use absolute time - more accurate
        task_id=task_id,
        timer_type=result.metadata.get('timer_type', 'sleep'),
        payload=result.metadata
    )
    # ☝️ Writes to: "timers:pending" (no shard prefix!)

    logger.info(f"Task {task_id} scheduled for timer execution with timer_id {timer_id}")
```

### 4. StatelessTimerManager Creates Timer

**File**: [src/gleitzeit/timers/stateless_timer_manager.py:35-137](src/gleitzeit/timers/stateless_timer_manager.py#L35-L137)

```python
@staticmethod
async def create_timer(
    redis,
    workflow_id: str,
    duration_seconds: float = None,
    task_id: Optional[str] = None,
    timer_type: str = "delay",
    payload: Optional[Dict[str, Any]] = None,
    timer_id: Optional[str] = None,
    wake_time: Optional[float] = None
) -> str:
    """Create a new timer with accurate timing and no drift."""

    if not timer_id:
        timer_id = f"timer-{workflow_id}-{uuid.uuid4().hex[:8]}"

    # Use wake_time if provided (absolute timestamp)
    if wake_time is not None:
        scheduled_time = datetime.fromtimestamp(wake_time)
        if duration_seconds is None:
            duration_seconds = wake_time - time.time()
    else:
        if duration_seconds is None:
            raise ValueError("Either wake_time or duration_seconds must be provided")
        wake_time = time.time() + duration_seconds
        scheduled_time = datetime.fromtimestamp(wake_time)

    # Timer data
    timer_data = {
        "timer_id": timer_id,
        "workflow_id": workflow_id,
        "task_id": task_id or "",
        "timer_type": timer_type,
        "duration_seconds": duration_seconds,
        "payload": json.dumps(payload or {}),
        "created_at": datetime.utcnow().isoformat(),
        "scheduled_time": scheduled_time.isoformat(),
        "status": "pending"
    }

    # Store timer metadata
    timer_key = f"{StatelessTimerManager.TIMER_METADATA_PREFIX}{timer_id}"
    await redis.hset(timer_key, mapping=timer_data)
    # ☝️ Writes to: "timers:meta:{timer_id}"

    # Add to pending timers sorted set with scheduled time as score
    await redis.zadd(
        StatelessTimerManager.PENDING_TIMERS_KEY,  # ❌ "timers:pending"
        {timer_id: scheduled_time.timestamp()}
    )

    logger.info(f"Created timer {timer_id} scheduled for {scheduled_time}")
    return timer_id
```

**Key Constants** (line 28-32):
```python
PENDING_TIMERS_KEY = "timers:pending"  # ❌ NO SHARD PREFIX!
ACTIVE_TIMERS_KEY = "timers:active"
CANCELLED_TIMERS_KEY = "timers:cancelled"
RECURRING_TIMERS_KEY = "timers:recurring"
TIMER_METADATA_PREFIX = "timers:meta:"
```

### 5. Timer Worker Processes Timer

**File**: [src/gleitzeit/workers/timer_worker.py:115-160](src/gleitzeit/workers/timer_worker.py#L115-L160)

```python
async def _timer_processing_loop(self):
    """Process timers (only when leader)"""

    while self._running:
        try:
            if self.leader_election and self.leader_election.is_leader:
                # Use StatelessTimerManager's comprehensive processing
                processed, fired_timers = await StatelessTimerManager.process_due_timers(
                    self.redis,
                    max_timers=100
                )
                # ☝️ Reads from: "timers:pending" ✅ MATCHES!

                if fired_timers:
                    logger.info(f"Processing {len(fired_timers)} expired timers")

                    # Process each fired timer
                    for timer_data in fired_timers:
                        timer_id = timer_data['timer_id']
                        task_id = timer_data.get('task_id', '')
                        workflow_id = timer_data.get('workflow_id', '')

                        if ":retry" in timer_id:
                            await self._handle_retry_timer(task_id, workflow_id)
                        else:
                            # Regular timer - complete the task
                            shard = default_sharding.get_shard(workflow_id)
                            await self._complete_timer_task(
                                task_id,
                                workflow_id,
                                shard,
                                timer_data
                            )

            await asyncio.sleep(self.check_interval)
```

### 6. Timer Fires - Task Completed

**File**: [src/gleitzeit/workers/timer_worker.py:233-326](src/gleitzeit/workers/timer_worker.py#L233-L326)

```python
async def _complete_timer_task(
    self,
    task_id: str,
    workflow_id: str,
    shard: int,
    timer_data: Dict = None
):
    """Mark timer task as completed and emit completion event."""

    # Validate task state before completion
    task_key = default_sharding.get_task_key(task_id, workflow_id)
    task_state = await self.redis.hgetall(task_key.encode())

    if not task_state:
        logger.warning(f"Task {task_id} no longer exists, skipping timer completion")
        return

    current_status = task_state.get(b"status", b"").decode()
    if current_status in ["cancelled", "completed", "failed"]:
        logger.info(f"Task {task_id} is {current_status}, skipping timer completion")
        return

    logger.info(f"Completing timer task {task_id} for workflow {workflow_id}")

    # Build enriched result with timer metadata
    result_data = {"timer_fired": True, "message": "Timer expired"}
    if timer_data:
        result_data.update({
            "timer_type": timer_data.get('timer_type', 'unknown'),
            "duration_seconds": timer_data.get('duration_seconds', 0),
            "scheduled_time": timer_data.get('scheduled_time'),
            "fired_at": timer_data.get('fired_at'),
            "created_at": timer_data.get('created_at')
        })

    # Publish timer fired event
    await self.event_store.store_event(
        event_type=EventType.TIMER_FIRED,
        workflow_id=workflow_id,
        task_id=task_id,
        level=EventLevel.IMPORTANT,
        data=result_data
    )

    # Mark timer task as completed
    completion_time = datetime.utcnow().isoformat()
    await self.redis.hset(
        task_key.encode(),
        mapping={
            b"status": b"completed",
            b"completed_at": completion_time.encode(),
            b"timer_fired_at": completion_time.encode(),
            b"result": json.dumps(result_data).encode()
        }
    )

    # Emit completion event to dependency worker
    await self.redis.xadd(
        default_sharding.get_stream_key("task:completed", workflow_id).encode(),
        {
            b"workflow_id": workflow_id.encode(),
            b"task_id": task_id.encode(),
            b"result": json.dumps(result_data).encode(),
            b"timestamp": datetime.utcnow().isoformat().encode()
        }
    )

    logger.info(f"Timer task {task_id} marked as completed")
```

---

## Regular Timer Tasks: Summary Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                    REGULAR TIMER TASK FLOW                          │
└─────────────────────────────────────────────────────────────────────┘

1. User submits workflow with timer/sleep task
   ↓
2. Task Execution Worker picks up task
   ↓
3. TimerHandler.execute() validates and calculates wake_time
   Returns: TaskResult(status=SCHEDULED, metadata={'wake_time': ...})
   ↓
4. Task Execution Worker sees SCHEDULED status
   Calls: emit_task_scheduled()
   ↓
5. emit_task_scheduled() calls StatelessTimerManager.create_timer()
   Writes to: "timers:pending" (sorted set)  ❌ NO SHARD PREFIX
   Writes to: "timers:meta:{timer_id}" (hash)
   ↓
6. Timer Worker (leader) polls: "timers:pending" every 1 second
   Calls: StatelessTimerManager.process_due_timers()
   Reads from: "timers:pending"  ✅ MATCHES!
   ↓
7. When timer expires (wake_time <= current_time):
   Timer Worker finds it in process_due_timers()
   ↓
8. Timer Worker calls _complete_timer_task()
   Updates task status: "scheduled" → "completed"
   Emits to: {shard:N}:task:completed stream
   ↓
9. Dependency Worker sees completion
   Workflow continues...
```

**Status**: ✅ **Regular timer tasks WORK** because both write and read use the same key: `"timers:pending"`

---

## Retry Timers Flow

### How Retry Timers Are Created

**File**: [src/gleitzeit/workers/retry_worker.py:226-272](src/gleitzeit/workers/retry_worker.py#L226-L272)

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
    # ☝️ Returns: "{shard:0}:global:timers:pending"  ❌ WRONG!

    await self.redis.zadd(
        timer_key,
        {f"{workflow_id}:{task_id}:retry".encode(): time.time() + delay}
    )
    # ☝️ Writes timer ID directly to sorted set (no metadata hash)

    # Emit retry scheduled event
    if hasattr(self, 'event_store'):
        await self.event_store.store_event(
            event_type=EventType.TASK_RETRY_SCHEDULED,
            workflow_id=workflow_id,
            task_id=task_id,
            level=EventLevel.IMPORTANT,
            data={
                'attempt': next_attempt,
                'delay': delay,
                'retry_at': time.time() + delay,
                'error': error_msg
            }
        )

    logger.info(f"Scheduled retry for {task_id} in {delay:.2f}s (attempt {next_attempt})")
```

**Key Difference**:
- Regular timers: Call `StatelessTimerManager.create_timer()` → writes to `"timers:pending"`
- Retry timers: Call `default_sharding.get_global_key("timers:pending")` → writes to `"{shard:0}:global:timers:pending"`

### Why Retry Timers Don't Work

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

**Result**: Retry worker writes to `{shard:0}:global:timers:pending` but timer worker reads from `timers:pending`

---

## Retry Timer Flow (BROKEN)

```
┌─────────────────────────────────────────────────────────────────────┐
│                    RETRY TIMER FLOW (BROKEN)                        │
└─────────────────────────────────────────────────────────────────────┘

1. Task fails during execution
   ↓
2. Task Execution Worker calls handle_task_failure()
   Emits to: {shard:N}:task:failed stream
   ↓
3. Retry Worker consumes from task:failed
   Calls: should_retry(context)
   Decision: RETRY (if under max_retries)
   ↓
4. Retry Worker calls _schedule_retry()
   Writes to: "{shard:0}:global:timers:pending"  ❌ WRONG KEY!
   Timer ID format: "{workflow_id}:{task_id}:retry"
   Score: retry_at timestamp
   ↓
5. Timer Worker (leader) polls: "timers:pending" every 1 second
   Reads from: "timers:pending"  ❌ DIFFERENT KEY!
   Finds: (nothing)
   ↓
6. ❌ Timer never fires
   ↓
7. ❌ Task stuck at status="scheduled", retry_count=N
   ↓
8. ❌ Never reaches max_retries check
   ↓
9. ❌ Task never marked as "failed"
```

**Status**: ❌ **Retry timers BROKEN** because write and read use different keys

---

## The Bug: Two Different Approaches

### Regular Timer Tasks (WORKS)

| Step | Component | Action | Key Used |
|------|-----------|--------|----------|
| Write | Task Execution Worker | `StatelessTimerManager.create_timer()` | `timers:pending` |
| Read | Timer Worker | `StatelessTimerManager.process_due_timers()` | `timers:pending` |
| **Result** | ✅ | **Keys match** | **Works!** |

### Retry Timers (BROKEN)

| Step | Component | Action | Key Used |
|------|-----------|--------|----------|
| Write | Retry Worker | `default_sharding.get_global_key("timers:pending")` | `{shard:0}:global:timers:pending` |
| Read | Timer Worker | `StatelessTimerManager.process_due_timers()` | `timers:pending` |
| **Result** | ❌ | **Keys DON'T match** | **Broken!** |

---

## Why The Inconsistency?

### Design History

1. **StatelessTimerManager** was created first
   - Simple design for single Redis instance
   - Hardcoded key names: `"timers:pending"`, `"timers:active"`, etc.
   - No awareness of sharding or Redis Cluster

2. **Sharding system** added later
   - Introduced `default_sharding.get_global_key()` for cluster-aware keys
   - Adds `{shard:0}:global:` prefix for Redis Cluster routing
   - Most workers adopted this pattern

3. **Task Execution Worker** uses `StatelessTimerManager` directly
   - Calls `StatelessTimerManager.create_timer()`
   - Writes to hardcoded `"timers:pending"`
   - Works because timer worker reads from same key

4. **Retry Worker** uses sharding system
   - Calls `default_sharding.get_global_key("timers:pending")`
   - Writes to prefixed `"{shard:0}:global:timers:pending"`
   - Broken because timer worker reads from unprefixed key

### Why Wasn't This Caught?

1. **Different development paths**: Regular timers and retry timers implemented by different developers/at different times
2. **Both appear to work in isolation**: Each worker runs successfully and heartbeats
3. **No integration tests**: No tests covering the full retry cycle end-to-end
4. **Silent failure**: Timers just accumulate in the wrong queue, no errors logged
5. **Regular timers work**: So the timer system appears healthy

---

## Evidence from Current System

### Regular Timer Queue (EMPTY - but this is where timer worker reads)

```bash
$ redis-cli ZCARD timers:pending
0

$ redis-cli --scan --pattern 'timers:meta:*'
(no results)
```

**Note**: No regular timer tasks were submitted in our test, only retry timers

### Retry Timer Queue (FULL - but timer worker doesn't read this)

```bash
$ redis-cli ZCARD '{shard:0}:global:timers:pending'
100

$ redis-cli ZRANGE '{shard:0}:global:timers:pending' 0 2 WITHSCORES
workflow-23f58ea8-...:dd984918-...:retry
1761470383.530672

workflow-a30a7be8-...:6092f31e-...:retry
1761470383.553854

workflow-902a304b-...:b153160a-...:retry
1761470383.588495
```

All 100 retry timers stuck for 30+ minutes.

---

## Retry Timer Handler

When a retry timer WOULD fire (if it was in the right queue), the timer worker has logic to handle it:

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

**This logic is correct** - it would work if the timer ever fired!

The timer worker detects retry timers by the `:retry` suffix in the timer ID:
```python
if ":retry" in timer_id:
    await self._handle_retry_timer(task_id, workflow_id)
```

---

## Retry Timer Metadata

Unlike regular timers, retry timers do NOT create metadata entries:

**Regular Timer**:
- Sorted set entry: `timers:pending` → `{timer_id: wake_time}`
- Metadata hash: `timers:meta:{timer_id}` → full timer data

**Retry Timer**:
- Sorted set entry: `{shard:0}:global:timers:pending` → `{workflow_id:task_id:retry: retry_at}`
- Metadata hash: (none)

This is actually **OK** because:
1. The timer ID format `{workflow_id}:{task_id}:retry` contains all needed information
2. The timer worker can parse the ID to extract workflow_id and task_id
3. Workflow data is fetched from Redis when timer fires

But it doesn't matter because **the timer never gets processed anyway** due to the key mismatch!

---

## Solution

### Fix Option 1: Update StatelessTimerManager (Affects Regular Timers)

Change the hardcoded keys to use sharding:

```python
# In stateless_timer_manager.py
PENDING_TIMERS_KEY = "{shard:0}:global:timers:pending"  # Add prefix
ACTIVE_TIMERS_KEY = "{shard:0}:global:timers:active"
CANCELLED_TIMERS_KEY = "{shard:0}:global:timers:cancelled"
RECURRING_TIMERS_KEY = "{shard:0}:global:timers:recurring"
TIMER_METADATA_PREFIX = "{shard:0}:global:timers:meta:"
```

**Pros**:
- Fixes both regular and retry timers
- Consistent with sharding strategy
- Works with Redis Cluster

**Cons**:
- Breaks existing regular timer tasks (if any)
- Hardcodes shard 0 (not flexible)

### Fix Option 2: Update Retry Worker (Affects Only Retry Timers)

Change retry worker to use simple key:

```python
# In retry_worker.py _schedule_retry()
# BEFORE:
timer_key = default_sharding.get_global_key("timers:pending").encode()

# AFTER:
timer_key = b"timers:pending"
```

**Pros**:
- Minimal change
- Only affects retry timers
- Doesn't break regular timers

**Cons**:
- Inconsistent with rest of retry worker
- Doesn't use sharding system
- May not work well with Redis Cluster

### Fix Option 3: Centralized Timer Key Management (Best)

Create a single source of truth for timer keys:

```python
# New file: timers/keys.py
from ..core.sharding import default_sharding

class TimerKeys:
    """Centralized timer key management"""

    @staticmethod
    def get_pending_queue() -> str:
        """Get key for pending timers queue"""
        # Use sharded key for Redis Cluster compatibility
        return default_sharding.get_global_key("timers:pending")

    @staticmethod
    def get_metadata_key(timer_id: str) -> str:
        """Get key for timer metadata"""
        return f"{default_sharding.get_global_key('timers:meta')}:{timer_id}"

# Update all timer code to use TimerKeys
```

**Pros**:
- Single source of truth
- Prevents future mismatches
- Easy to change strategy later
- Type-safe with proper imports

**Cons**:
- More refactoring work
- Requires changes in 3+ files

---

## Recommended Fix

**Immediate** (Option 1): Update StatelessTimerManager constants
**Long-term** (Option 3): Create centralized TimerKeys class

### Migration Steps

1. **Check for existing timers**:
   ```bash
   redis-cli ZCARD timers:pending
   redis-cli ZCARD '{shard:0}:global:timers:pending'
   ```

2. **Update StatelessTimerManager**:
   ```python
   PENDING_TIMERS_KEY = "{shard:0}:global:timers:pending"
   ```

3. **Migrate existing regular timers** (if any):
   ```python
   timers = await redis.zrange("timers:pending", 0, -1, withscores=True)
   if timers:
       await redis.zadd("{shard:0}:global:timers:pending", dict(timers))
   ```

4. **Restart timer worker**

5. **Verify** timers are processed:
   ```bash
   # Wait 5 seconds
   redis-cli ZCARD '{shard:0}:global:timers:pending'  # Should decrease
   ```

---

## Conclusion

**Regular timer tasks work** because both the task execution worker and timer worker use `StatelessTimerManager` directly, which has hardcoded keys.

**Retry timers are broken** because the retry worker uses the sharding system (`get_global_key()`) while the timer worker still uses the hardcoded keys.

The fix is straightforward but requires careful coordination to avoid breaking existing timer tasks.

**Priority**: P0 - Critical bug affecting all retries
**Impact**: Regular timers ✅ work | Retry timers ❌ completely broken
**Fix complexity**: Low (one constant change + optional migration)
