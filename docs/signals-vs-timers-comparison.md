# Signals vs Timers: Architecture Comparison

**Date**: 2025-10-26
**Context**: Understanding different async coordination mechanisms in Gleitzeit

---

## Executive Summary

Gleitzeit has **two completely different mechanisms** for async task coordination:

1. **Timers** - Time-based task waking (polling sorted sets) ⚠️ HAS KEY MISMATCH BUG
2. **Signals** - Event-based task waking (registry + streams) ✅ USES PROPER SHARDING

**Key Insight**: Signals work correctly because they use the sharding system properly throughout. Timers are broken for retries because they have inconsistent key naming.

---

## Architecture Comparison

### Timer-Based Tasks (timer/sleep, timer/wait_until)

**Use Case**: Wait for a specific duration or until a specific time

**Mechanism**: Polling sorted sets

```
┌─────────────────────────────────────────────────────────────────────┐
│                       TIMER-BASED COORDINATION                      │
└─────────────────────────────────────────────────────────────────────┘

1. Handler returns SCHEDULED status
   ↓
2. Task Execution Worker calls StatelessTimerManager.create_timer()
   Writes to SORTED SET: "timers:pending" ❌ (no shard prefix)
   Score = wake_time (Unix timestamp)
   ↓
3. Timer Worker (leader) polls every 1 second
   ZRANGEBYSCORE "timers:pending" -inf current_time
   ↓
4. Finds expired timers (score <= current_time)
   ↓
5. For each expired timer:
   - If ":retry" in timer_id: re-queue to task:ready
   - Else: mark task as completed
   ↓
6. Dependency Worker sees completion, continues workflow
```

**Data Structures**:
```python
# Sorted set (score = wake timestamp)
"timers:pending" → {
    "timer-workflow123-abc123": 1761470500.0,
    "timer-workflow456-def456": 1761470600.0
}

# Hash (timer metadata)
"timers:meta:{timer_id}" → {
    "timer_id": "timer-workflow123-abc123",
    "workflow_id": "workflow123",
    "task_id": "task-abc",
    "timer_type": "sleep",
    "duration_seconds": 5.0,
    "created_at": "2025-10-26T10:00:00",
    "scheduled_time": "2025-10-26T10:00:05",
    "status": "pending"
}
```

**Key Characteristics**:
- ✅ Simple to understand
- ✅ Works for arbitrary delays
- ✅ No coordination required
- ❌ Requires polling (every 1 second)
- ❌ Key naming inconsistency (bug)
- ❌ Leader election required (only one worker polls)

### Signal-Based Tasks (signal/wait, signal/send)

**Use Case**: Wait for a named event to occur

**Mechanism**: Registry + Streams (event-driven)

```
┌─────────────────────────────────────────────────────────────────────┐
│                      SIGNAL-BASED COORDINATION                      │
└─────────────────────────────────────────────────────────────────────┘

1. Handler returns WAITING status
   ↓
2. Task Execution Worker registers waiter
   Writes to SET: {shard:N}:signal:waiters:workflow123:signal-name ✅
   Writes to HASH: {shard:N}:signal:metadata:workflow123:task-id ✅
   Optionally adds to SORTED SET: {shard:0}:global:signal:timeouts ✅
   ↓
3. Another task sends signal
   Writes to STREAM: {shard:N}:workflow:signals:workflow123 ✅
   Writes to REGISTRY: signal:registry:workflow123:signal-name ✅
   ↓
4. Signal Worker (leader) polls registry every 0.5 seconds
   SCAN "signal:registry:*"
   ↓
5. For each registry entry:
   - Check waiters SET
   - Read signal from workflow stream
   - Match signal_name
   ↓
6. For each waiting task:
   - Mark task as completed
   - Emit to task:completed stream
   - Clean up waiters SET and metadata HASH
   ↓
7. Dependency Worker sees completion, continues workflow
```

**Data Structures**:
```python
# Set (waiting tasks for specific signal in specific workflow)
"{shard:5}:signal:waiters:workflow123:signal-name" → {
    "task-abc",
    "task-def"
}

# Hash (metadata for waiting task)
"{shard:5}:signal:metadata:workflow123:task-abc" → {
    "shard": "5",
    "signal_name": "signal-name",
    "signal_type": "wait",
    "waiting_since": "2025-10-26T10:00:00",
    "timeout": "30"
}

# Registry key (indicates signal is ready)
"signal:registry:workflow123:signal-name" → "" (key existence is the flag)

# Stream (workflow-specific signals)
"{shard:5}:workflow:signals:workflow123" → [
    {
        "signal": "signal-name",
        "payload": '{"data": "value"}',
        "timestamp": "2025-10-26T10:00:05"
    }
]

# Sorted set (timeouts, score = timeout timestamp)
"{shard:0}:global:signal:timeouts" → {
    "workflow123:task-abc": 1761470530.0
}
```

**Key Characteristics**:
- ✅ Event-driven (no polling of task state)
- ✅ Proper sharding throughout
- ✅ Supports multiple waiters for same signal
- ✅ Supports timeouts
- ✅ Workflow-scoped isolation
- ⚠️ Still requires polling (registry scan every 0.5s)
- ⚠️ More complex data structures
- ⚠️ Leader election required

---

## Code Walkthrough

### Timer Flow: Task Execution Worker

**File**: [src/gleitzeit/workers/task_execution_worker.py:536-586](src/gleitzeit/workers/task_execution_worker.py#L536-L586)

When a task returns `SCHEDULED` status:

```python
async def emit_task_scheduled(
    self,
    task_id: str,
    workflow_id: str,
    result: TaskResult
):
    """Emit task scheduled event for TimerWorker"""
    wake_time = result.metadata.get('wake_time', 0)

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

    # Create timer in sorted set
    timer_id = await StatelessTimerManager.create_timer(
        redis=self.redis,
        workflow_id=workflow_id,
        wake_time=wake_time,
        task_id=task_id,
        timer_type=result.metadata.get('timer_type', 'sleep'),
        payload=result.metadata
    )
    # ☝️ Writes to: "timers:pending" ❌ NO SHARD PREFIX
```

### Signal Flow: Task Execution Worker

**File**: [src/gleitzeit/workers/task_execution_worker.py:588-667](src/gleitzeit/workers/task_execution_worker.py#L588-L667)

When a task returns `WAITING` status:

```python
async def emit_task_waiting(
    self,
    task_id: str,
    workflow_id: str,
    result: TaskResult
):
    """Emit task waiting event for SignalWorker"""
    shard = default_sharding.get_shard(workflow_id)
    signal_name = result.metadata.get('signal_name', '')

    # Update task status
    await self.redis.hset(
        default_sharding.get_task_key(task_id, workflow_id).encode(),
        mapping={
            b"status": TaskStatus.WAITING.encode(),
            b"signal_type": result.metadata.get('signal_type', 'wait').encode(),
            b"signal_name": signal_name.encode(),
            b"waiting_since": datetime.utcnow().isoformat().encode()
        }
    )

    # Register task in waiters SET
    waiting_key = default_sharding.get_signal_key("waiters", workflow_id, signal_name)
    # ☝️ Returns: "{shard:N}:signal:waiters:workflow123:signal-name" ✅
    await self.redis.sadd(waiting_key, task_id)

    # Store metadata
    metadata_key = default_sharding.get_signal_key("metadata", workflow_id, task_id)
    # ☝️ Returns: "{shard:N}:signal:metadata:workflow123:task-id" ✅
    await self.redis.hset(
        metadata_key.encode(),
        mapping={
            b"shard": str(shard).encode(),
            b"signal_name": signal_name.encode(),
            b"signal_type": result.metadata.get('signal_type', 'wait').encode(),
            b"waiting_since": datetime.utcnow().isoformat().encode(),
            b"timeout": str(result.metadata.get('timeout', 0)).encode()
        }
    )

    # Handle timeout if specified
    timeout = result.metadata.get('timeout')
    if timeout:
        timeout_time = time.time() + timeout
        await self.redis.zadd(
            default_sharding.get_global_key("signal:timeouts").encode(),
            # ☝️ Returns: "{shard:0}:global:signal:timeouts" ✅
            {f"{workflow_id}:{task_id}".encode(): timeout_time}
        )
```

**Key Difference**: Signal flow uses `default_sharding.get_signal_key()` and `default_sharding.get_global_key()` throughout, ensuring consistent sharded keys.

### Timer Worker: Processing Loop

**File**: [src/gleitzeit/workers/timer_worker.py:115-160](src/gleitzeit/workers/timer_worker.py#L115-L160)

```python
async def _timer_processing_loop(self):
    """Process timers (only when leader)"""
    while self._running:
        try:
            if self.leader_election and self.leader_election.is_leader:
                # Poll sorted set for expired timers
                processed, fired_timers = await StatelessTimerManager.process_due_timers(
                    self.redis,
                    max_timers=100
                )
                # ☝️ Reads from: "timers:pending" ✅ (matches write for regular timers)
                #                                    ❌ (doesn't match write for retry timers)

                if fired_timers:
                    for timer_data in fired_timers:
                        timer_id = timer_data['timer_id']
                        task_id = timer_data.get('task_id', '')
                        workflow_id = timer_data.get('workflow_id', '')

                        if ":retry" in timer_id:
                            await self._handle_retry_timer(task_id, workflow_id)
                        else:
                            await self._complete_timer_task(
                                task_id, workflow_id, shard, timer_data
                            )

            await asyncio.sleep(self.check_interval)  # 1 second
```

### Signal Worker: Processing Loop

**File**: [src/gleitzeit/workers/signal_worker.py:109-247](src/gleitzeit/workers/signal_worker.py#L109-L247)

```python
async def _signal_processing_loop(self):
    """Process signals (only when leader)"""
    while self._running:
        try:
            if self.leader_election and self.leader_election.is_leader:
                # Process workflow signals
                await self._process_workflow_signals()

                # Check for timeouts
                await self._check_signal_timeouts()

            await asyncio.sleep(self.check_interval)  # 0.5 seconds
```

```python
async def _process_workflow_signals(self):
    """Process signals using global registry"""
    # Scan for registry keys: "signal:registry:workflow_id:signal_name"
    registry_pattern = "signal:registry:*"
    registry_keys = []

    cursor = 0
    while True:
        cursor, keys = await self.redis.scan(cursor, match=registry_pattern, count=100)
        registry_keys.extend(keys)
        if cursor == 0:
            break

    for registry_key in registry_keys:
        # Parse: "signal:registry:workflow_id:signal_name"
        parts = registry_key.split(":", 3)
        workflow_id = parts[2]
        signal_name = parts[3]

        # Check for waiters
        waiting_key = default_sharding.get_signal_key("waiters", workflow_id, signal_name)
        # ☝️ Returns: "{shard:N}:signal:waiters:workflow_id:signal_name" ✅
        waiting_tasks = await self.redis.smembers(waiting_key)

        if not waiting_tasks:
            continue

        # Read signal from workflow stream
        workflow_stream_key = default_sharding.get_all_keys_for_workflow(workflow_id)["workflow_signals"]
        # ☝️ Returns: "{shard:N}:workflow:signals:workflow_id" ✅

        messages = await self.redis.xreadgroup(
            "signal-workers",
            self.config.worker_id,
            {workflow_stream_key: b">"},
            count=100,
            block=0
        )

        # Match signal_name and wake waiting tasks
        for stream_key, stream_messages in messages:
            for msg_id, signal_data in stream_messages:
                msg_signal_name = signal_data.get(b"signal", b"").decode()

                if msg_signal_name == signal_name:
                    await self._handle_signal(workflow_id, msg_id, signal_data)
                    await self.redis.delete(registry_key)
                    break
```

### Signal Timeout Handling

**File**: [src/gleitzeit/workers/signal_worker.py:324-394](src/gleitzeit/workers/signal_worker.py#L324-L394)

```python
async def _check_signal_timeouts(self):
    """Check for signal timeouts"""
    now = time.time()

    # Get expired timeout entries
    expired = await self.redis.zrangebyscore(
        default_sharding.get_global_key("signal:timeouts").encode(),
        # ☝️ Returns: "{shard:0}:global:signal:timeouts" ✅
        0,
        now,
        start=0,
        num=10
    )

    for entry in expired:
        # Format: "workflow_id:task_id"
        parts = entry.split(":")
        workflow_id = parts[0]
        task_id = parts[1]

        # Mark task as failed
        await self.redis.hset(
            default_sharding.get_task_key(task_id, workflow_id).encode(),
            mapping={
                b"status": b"failed",
                b"error": b"Signal wait timed out",
                b"failed_at": datetime.utcnow().isoformat().encode()
            }
        )

        # Emit to task:failed stream
        await self.redis.xadd(
            default_sharding.get_stream_key("task:failed", workflow_id).encode(),
            # ☝️ Uses sharding system properly ✅
            {
                b"workflow_id": workflow_id.encode(),
                b"task_id": task_id.encode(),
                b"error": b"Signal wait timed out",
                b"timestamp": datetime.utcnow().isoformat().encode()
            }
        )

        # Remove from timeouts
        await self.redis.zrem(
            default_sharding.get_global_key("signal:timeouts").encode(),
            entry
        )
```

**Key Point**: Signal timeouts use `get_global_key()` consistently for both writes and reads ✅

---

## Key Naming Comparison

### Timer Keys

| Key Type | Writer | Key Used | Correct? |
|----------|--------|----------|----------|
| **Regular Timer Queue** | StatelessTimerManager.create_timer() | `timers:pending` | ✅ (read matches) |
| **Regular Timer Queue** | Timer Worker (reader) | `timers:pending` | ✅ (write matches) |
| **Retry Timer Queue** | Retry Worker._schedule_retry() | `{shard:0}:global:timers:pending` | ❌ (read doesn't match) |
| **Retry Timer Queue** | Timer Worker (reader) | `timers:pending` | ❌ (write doesn't match) |
| **Timer Metadata** | StatelessTimerManager.create_timer() | `timers:meta:{timer_id}` | ✅ |
| **Timer Timeouts** | ❌ NOT IMPLEMENTED | N/A | ❌ |

**Problem**: Inconsistent use of `get_global_key()` for timers

### Signal Keys

| Key Type | Writer | Key Used | Correct? |
|----------|--------|----------|----------|
| **Waiters Set** | Task Execution Worker | `{shard:N}:signal:waiters:{wf}:{sig}` | ✅ |
| **Waiters Set** | Signal Worker (reader) | `{shard:N}:signal:waiters:{wf}:{sig}` | ✅ |
| **Metadata Hash** | Task Execution Worker | `{shard:N}:signal:metadata:{wf}:{task}` | ✅ |
| **Metadata Hash** | Signal Worker (reader) | `{shard:N}:signal:metadata:{wf}:{task}` | ✅ |
| **Signal Registry** | Signal emitter | `signal:registry:{wf}:{sig}` | ✅ |
| **Signal Registry** | Signal Worker (reader) | `signal:registry:{wf}:{sig}` | ✅ |
| **Workflow Signals Stream** | Signal emitter | `{shard:N}:workflow:signals:{wf}` | ✅ |
| **Workflow Signals Stream** | Signal Worker (reader) | `{shard:N}:workflow:signals:{wf}` | ✅ |
| **Timeout Queue** | Task Execution Worker | `{shard:0}:global:signal:timeouts` | ✅ |
| **Timeout Queue** | Signal Worker (reader) | `{shard:0}:global:signal:timeouts` | ✅ |

**Result**: All signal keys use sharding system consistently ✅

---

## Why Signals Work and Retry Timers Don't

### Signals: Consistent Sharding

**All signal operations use helper methods**:
- `default_sharding.get_signal_key()` - Returns `{shard:N}:signal:{type}:{workflow}...`
- `default_sharding.get_global_key()` - Returns `{shard:0}:global:{key_type}`
- `default_sharding.get_stream_key()` - Returns `{shard:N}:{stream_type}:{workflow}`

**Example from code**:
```python
# Task Execution Worker
waiting_key = default_sharding.get_signal_key("waiters", workflow_id, signal_name)
# → "{shard:5}:signal:waiters:workflow123:signal-name"

# Signal Worker
waiting_key = default_sharding.get_signal_key("waiters", workflow_id, signal_name)
# → "{shard:5}:signal:waiters:workflow123:signal-name"

# ✅ KEYS MATCH!
```

### Regular Timers: Consistent (but unsharded)

**All timer operations use StatelessTimerManager**:
- Both writer and reader use `StatelessTimerManager.PENDING_TIMERS_KEY`
- Hardcoded to `"timers:pending"`

**Example from code**:
```python
# Task Execution Worker
timer_id = await StatelessTimerManager.create_timer(...)
# Writes to: StatelessTimerManager.PENDING_TIMERS_KEY
#         → "timers:pending"

# Timer Worker
await StatelessTimerManager.process_due_timers(...)
# Reads from: StatelessTimerManager.PENDING_TIMERS_KEY
#          → "timers:pending"

# ✅ KEYS MATCH! (but not sharded)
```

### Retry Timers: INCONSISTENT ❌

**Writer uses sharding, reader doesn't**:

**Example from code**:
```python
# Retry Worker
timer_key = default_sharding.get_global_key("timers:pending").encode()
# → "{shard:0}:global:timers:pending"
await self.redis.zadd(timer_key, {...})

# Timer Worker
await StatelessTimerManager.process_due_timers(...)
# Reads from: StatelessTimerManager.PENDING_TIMERS_KEY
#          → "timers:pending"

# ❌ KEYS DON'T MATCH!
```

---

## Architectural Lessons

### What Signals Got Right

1. **Centralized key management**: `default_sharding.get_signal_key()` as single source of truth
2. **Consistent helper usage**: All code uses the helper methods
3. **Proper sharding**: Keys include `{shard:N}` for Redis Cluster routing
4. **Event-driven where possible**: Registry acts as a trigger
5. **Timeout support built-in**: Separate sorted set for timeouts with proper sharding

### What Timers Got Wrong

1. **Hardcoded keys**: `StatelessTimerManager` has string constants
2. **No sharding awareness**: Built before sharding system, never updated
3. **Split codebase**: Regular timers use StatelessTimerManager, retry timers use sharding
4. **No timeout support**: Timer tasks can't timeout (only signal tasks can)
5. **Polling-heavy**: Sorted set must be polled every second

### Design Recommendations

#### For Timers (Immediate Fix)

**Option 1**: Update `StatelessTimerManager` to use sharded keys:
```python
# In stateless_timer_manager.py
from ..core.sharding import default_sharding

PENDING_TIMERS_KEY = default_sharding.get_global_key("timers:pending")
# → "{shard:0}:global:timers:pending"
```

**Option 2**: Create TimerKeys helper (like SignalKeys):
```python
# New file: timers/keys.py
class TimerKeys:
    @staticmethod
    def get_pending_queue() -> str:
        return default_sharding.get_global_key("timers:pending")

    @staticmethod
    def get_active_queue() -> str:
        return default_sharding.get_global_key("timers:active")
```

#### For Future Architecture

**Consider**: Could retry timers use signal mechanism instead?

```python
# Instead of scheduling a timer with delay
await self._schedule_retry(task_id, workflow_id, delay, ...)

# Could we use internal signal with timeout?
await self._schedule_retry_signal(task_id, workflow_id, delay)
```

**Pros**:
- Reuses proven signal infrastructure
- Consistent sharding throughout
- Timeout handling already built-in
- Event-driven (no polling sorted sets)

**Cons**:
- More complex (signals have more moving parts)
- Sorted sets are simpler for time-based delays
- Would need "internal" signals separate from user signals

---

## Timeout Handling Comparison

### Timers: No Native Timeout Support

Timer tasks themselves cannot timeout. If a timer is scheduled, it will eventually fire (unless the timer worker dies or Redis loses data).

**Workaround**: You could manually add timeout logic by checking task age, but this is not built-in.

### Signals: Built-in Timeout Support

Signal wait tasks support timeouts natively:

```python
# Task with timeout
{
    "method": "signal/wait",
    "params": {
        "signal_name": "approval-received",
        "timeout": 30  # seconds
    }
}
```

**Flow**:
1. Task Execution Worker adds entry to `{shard:0}:global:signal:timeouts` sorted set
2. Signal Worker polls this sorted set every 0.5 seconds
3. When timeout expires, task is marked as **failed** and emitted to `task:failed` stream
4. Retry Worker can then handle the failure (with retry logic if configured)

**This is a KEY difference**: Signal timeouts result in task failures that go through the retry system. Timer delays do not timeout - they always eventually fire.

---

## Performance Characteristics

### Timers

| Metric | Value | Notes |
|--------|-------|-------|
| Polling interval | 1 second | Configured in timer_worker.py |
| Time resolution | ~1 second | Can't fire faster than polling interval |
| Scale limit | ~10,000/sec | Limited by ZRANGEBYSCORE performance |
| Leader required | Yes | Only one worker processes timers |
| Redis operations/poll | 1 (ZRANGEBYSCORE) | Very efficient |

### Signals

| Metric | Value | Notes |
|--------|-------|-------|
| Polling interval | 0.5 seconds | Configured in signal_worker.py |
| Time resolution | ~0.5 seconds | Registry scan + stream read |
| Scale limit | ~1,000/sec | Limited by SCAN + XREADGROUP |
| Leader required | Yes | Only one worker processes signals |
| Redis operations/poll | 2-3 per signal | SCAN + XREADGROUP + (optional ACK) |

**Timeout checks** (signal only):
- Interval: Every 0.5 seconds
- Resolution: ~0.5 seconds
- Operation: ZRANGEBYSCORE (same as timers)

---

## Example Workflows

### Timer Example: Simple Delay

```json
{
  "tasks": [
    {
      "id": "notify",
      "protocol": "http/v1",
      "method": "http/post",
      "params": {
        "url": "https://api.example.com/notify",
        "json": {"status": "starting"}
      }
    },
    {
      "id": "wait",
      "protocol": "timer/v1",
      "method": "timer/sleep",
      "params": {
        "duration": 300
      },
      "dependencies": ["notify"]
    },
    {
      "id": "check",
      "protocol": "http/v1",
      "method": "http/get",
      "params": {
        "url": "https://api.example.com/status"
      },
      "dependencies": ["wait"]
    }
  ]
}
```

**Flow**:
1. `notify` task completes
2. `wait` task handler returns `SCHEDULED` with `wake_time = now + 300`
3. Task Execution Worker creates timer in `timers:pending`
4. Timer Worker polls every 1 second, finds timer after 300 seconds
5. Timer Worker marks `wait` as completed
6. Dependency Worker unblocks `check` task

### Signal Example: Approval Workflow

```json
{
  "tasks": [
    {
      "id": "submit_request",
      "protocol": "http/v1",
      "method": "http/post",
      "params": {
        "url": "https://api.example.com/requests",
        "json": {"type": "deployment"}
      }
    },
    {
      "id": "wait_approval",
      "protocol": "signal/v1",
      "method": "signal/wait",
      "params": {
        "signal_name": "deployment-approved",
        "timeout": 3600
      },
      "dependencies": ["submit_request"]
    },
    {
      "id": "deploy",
      "protocol": "kubernetes/v1",
      "method": "kubernetes/apply",
      "params": {
        "manifest": "deployment.yaml"
      },
      "dependencies": ["wait_approval"]
    }
  ]
}
```

**Flow**:
1. `submit_request` task completes
2. `wait_approval` handler returns `WAITING` with `signal_name = "deployment-approved"`
3. Task Execution Worker registers waiter in `{shard:N}:signal:waiters:...`
4. Task Execution Worker adds timeout entry to `{shard:0}:global:signal:timeouts`
5. (External system sends signal via API: POST /workflows/{id}/signal/deployment-approved)
6. API writes to stream `{shard:N}:workflow:signals:{workflow_id}`
7. API writes to registry `signal:registry:{workflow_id}:deployment-approved`
8. Signal Worker polls registry, finds entry, matches with waiters
9. Signal Worker marks `wait_approval` as completed
10. Dependency Worker unblocks `deploy` task

**If timeout occurs**:
- Signal Worker finds expired entry in `{shard:0}:global:signal:timeouts`
- Marks `wait_approval` as **failed**
- Emits to `task:failed` stream
- Retry Worker handles failure (retry if configured, else mark workflow failed)

---

## Summary Table

| Feature | Timers | Signals |
|---------|--------|---------|
| **Use Case** | Time-based delays | Event-based coordination |
| **Mechanism** | Sorted set + polling | Registry + streams |
| **Sharding** | ❌ Inconsistent (bug) | ✅ Consistent |
| **Polling Interval** | 1 second | 0.5 seconds |
| **Timeout Support** | ❌ No | ✅ Yes |
| **Scale Limit** | ~10K/sec | ~1K/sec |
| **Complexity** | Low | Medium |
| **Data Structures** | Sorted set, hash | Set, hash, stream, registry, sorted set |
| **Leader Election** | Yes | Yes |
| **Status** | ⚠️ Regular timers work, retry timers broken | ✅ Working correctly |

---

## Conclusion

**Signals and timers are completely different architectures**:

1. **Timers** use sorted sets and polling - simple but has key mismatch bug for retries
2. **Signals** use registry + streams - more complex but properly sharded throughout

**Why signals work and retry timers don't**: Signals use the sharding system (`get_signal_key()`, `get_global_key()`) consistently throughout the codebase. Retry timers mix sharded keys (writer) with unsharded keys (reader).

**Key lesson**: When building distributed systems, **centralized key management** (like `get_signal_key()`) prevents bugs like the timer key mismatch. Hardcoded string constants (like `PENDING_TIMERS_KEY = "timers:pending"`) are dangerous when mixed with dynamic key generation.

**Fix priority**: Update timer keys to use sharding system consistently (either all sharded or all unsharded, but not mixed).
