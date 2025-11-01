# Timer System Refactor: Event-Driven Design

**Date**: 2025-10-26
**Status**: Design Draft
**Goal**: Refactor timer system to use event-driven architecture similar to signals, eliminating sorted set polling and fixing key mismatch bugs

---

## Executive Summary

**Current Problem**: Timer system uses polling-based sorted sets with inconsistent key naming, causing retry timers to fail completely.

**Proposed Solution**: Refactor timers to use event-driven architecture similar to signals, with registry + streams instead of sorted sets + polling.

**Benefits**:
- ✅ Fixes retry timer key mismatch bug
- ✅ Consistent sharding throughout
- ✅ Event-driven (no polling sorted sets)
- ✅ Better observability (streams as audit log)
- ✅ Unified architecture with signals
- ✅ Native timeout support
- ✅ Simpler mental model

**Trade-offs**:
- ⚠️ More complex than sorted sets
- ⚠️ Requires background "time advance" worker
- ⚠️ More Redis data structures

---

## Current Timer Architecture (Broken)

### Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CURRENT TIMER SYSTEM (BROKEN)                    │
└─────────────────────────────────────────────────────────────────────┘

1. Task returns SCHEDULED status
   ↓
2. Task Execution Worker creates timer
   Writes to: "timers:pending" (regular) ❌
           or "{shard:0}:global:timers:pending" (retry) ❌
   ↓
3. Timer Worker polls sorted set every 1 second
   ZRANGEBYSCORE "timers:pending" -inf current_time
   ↓
4. Finds expired timers, marks tasks completed
```

### Problems

1. **Key mismatch**: Regular vs retry timers use different keys
2. **Polling overhead**: ZRANGEBYSCORE every second on all workers
3. **No observability**: Can't see timer history/audit trail
4. **Leader-only**: Only leader can process timers (no horizontal scaling)
5. **No native timeout support**: Timers can't fail/timeout
6. **Hardcoded keys**: `StatelessTimerManager.PENDING_TIMERS_KEY` not using sharding

---

## Proposed Timer Architecture (Event-Driven)

### Core Concept

**Instead of polling sorted sets for expired timers, use a "time advance" event stream that triggers timer processing.**

Similar to how signals work:
- **Signals**: Wait for named event → Event arrives → Task wakes
- **Timers**: Wait for time → Time advances → Task wakes

### High-Level Design

```
┌─────────────────────────────────────────────────────────────────────┐
│                   NEW TIMER SYSTEM (EVENT-DRIVEN)                   │
└─────────────────────────────────────────────────────────────────────┘

1. Task returns SCHEDULED status
   ↓
2. Task Execution Worker registers timer
   - Add to registry: timer:registry:{wake_bucket}  (bucketed by time)
   - Store metadata: {shard:N}:timer:metadata:{workflow}:{task}
   - Add to pending set: {shard:N}:timer:pending:{workflow}
   ↓
3. Time Advance Worker (heartbeat every 1 second)
   - Calculate current time bucket
   - Check registry for expired buckets
   - Emit "time advanced to bucket X" event to stream
   ↓
4. Timer Worker consumes time advance stream
   - For each bucket in event:
     - Find all timers in that bucket's registry
     - Check metadata for actual wake_time (bucket = minute, metadata = exact time)
     - Mark tasks as completed
     - Emit to task:completed stream
   ↓
5. Dependency Worker sees completion, continues workflow
```

### Key Innovation: Time Buckets

Instead of storing exact timestamps in sorted sets, **bucket timers by minute** (or configurable interval):

```python
# Current (polling sorted set):
"timers:pending" → {
    "timer-abc": 1761470383.5,  # Exact timestamp
    "timer-def": 1761470383.7,
    "timer-ghi": 1761470443.2
}

# Proposed (bucketed registry):
"timer:registry:1761470340" → ""  # Bucket for minute 29:00-29:59
"timer:registry:1761470400" → ""  # Bucket for minute 30:00-30:59
"timer:registry:1761470460" → ""  # Bucket for minute 31:00-31:59

# Exact wake times in metadata:
"{shard:5}:timer:metadata:workflow123:task-abc" → {
    "workflow_id": "workflow123",
    "task_id": "task-abc",
    "wake_time": "1761470383.5",  # Exact time
    "timer_type": "sleep",
    "bucket": "1761470340",
    "created_at": "2025-10-26T10:00:00"
}
```

**Why buckets?**
- Registry keys are cheap (just existence check)
- Exact times stored in metadata (only read when bucket expires)
- Easy to scan for expired buckets: `SCAN timer:registry:*` and parse timestamp
- Reduces registry churn (one key per minute, not per timer)

---

## Detailed Architecture

### 1. Data Structures

#### Timer Registry (Bucketed by Time)

**Key**: `timer:registry:{bucket_timestamp}`
**Type**: Key with empty value (existence = bucket has timers)
**TTL**: Set to bucket expiry time + 60 seconds
**Purpose**: Fast check for which time buckets have pending timers

```redis
# Example: Bucket for 10:30:00-10:30:59
timer:registry:1761470400 → "" (TTL: 120s after 10:31:00)

# Multiple buckets can exist simultaneously
timer:registry:1761470340 → ""  # 10:29:xx
timer:registry:1761470400 → ""  # 10:30:xx
timer:registry:1761470460 → ""  # 10:31:xx
```

**Bucket calculation**:
```python
def get_timer_bucket(wake_time: float, bucket_size: int = 60) -> int:
    """Get the bucket timestamp for a wake time."""
    return int(wake_time // bucket_size) * bucket_size

# Example:
# wake_time = 1761470383.5 (10:29:43.5)
# bucket_size = 60
# bucket = 1761470340 (10:29:00)
```

#### Timer Pending Set (Per Workflow)

**Key**: `{shard:N}:timer:pending:{workflow_id}`
**Type**: SET
**Members**: Task IDs with pending timers in this workflow
**Purpose**: Track which tasks are waiting for timers per workflow

```redis
{shard:5}:timer:pending:workflow123 → {
    "task-abc",
    "task-def"
}
```

#### Timer Metadata (Per Task)

**Key**: `{shard:N}:timer:metadata:{workflow_id}:{task_id}`
**Type**: HASH
**Purpose**: Store complete timer information with exact wake time

```redis
{shard:5}:timer:metadata:workflow123:task-abc → {
    "workflow_id": "workflow123",
    "task_id": "task-abc",
    "shard": "5",
    "wake_time": "1761470383.5",  # Exact Unix timestamp
    "timer_type": "sleep",        # sleep, wait_until, retry
    "bucket": "1761470340",       # Which bucket this timer is in
    "created_at": "2025-10-26T10:00:00",
    "duration_seconds": "300",
    "timer_id": "timer-workflow123-abc"  # For compatibility
}
```

#### Time Advance Stream (Global)

**Key**: `{shard:0}:global:timer:time_advance`
**Type**: STREAM
**Purpose**: Notify timer workers when time buckets expire

```redis
{shard:0}:global:timer:time_advance → [
    {
        "bucket": "1761470340",
        "bucket_time": "2025-10-26T10:29:00",
        "current_time": "1761470401.2",
        "timestamp": "2025-10-26T10:30:01.2"
    },
    {
        "bucket": "1761470400",
        "bucket_time": "2025-10-26T10:30:00",
        "current_time": "1761470461.5",
        "timestamp": "2025-10-26T10:31:01.5"
    }
]
```

#### Timer Timeout Queue (Optional - for timer timeouts)

**Key**: `{shard:0}:global:timer:timeouts`
**Type**: SORTED SET
**Score**: Timeout timestamp
**Members**: `{workflow_id}:{task_id}`
**Purpose**: Support maximum wait time for timers (fail if timer doesn't complete in time)

```redis
{shard:0}:global:timer:timeouts → {
    "workflow123:task-abc": 1761473600.0  # Timeout at 11:00:00
}
```

---

### 2. Components

#### TimeAdvanceWorker (New)

**Purpose**: Generate time advance events to trigger timer processing

**Responsibilities**:
- Run on leader only (leader election)
- Every 1 second (or configurable):
  - Calculate current time bucket
  - Scan for expired bucket registry keys
  - Emit time advance event to stream for each expired bucket
  - Clean up old bucket registry keys

**Pseudo-code**:
```python
class TimeAdvanceWorker(BaseWorker):
    """Worker that emits time advance events."""

    def __init__(self, config: WorkerConfig):
        super().__init__(config)
        self.bucket_size = 60  # seconds
        self.check_interval = 1  # seconds
        self.leader_election = None

    async def run(self):
        """Main loop - only run as leader"""
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        election_task = asyncio.create_task(self._leader_election_loop())
        advance_task = asyncio.create_task(self._time_advance_loop())

        await asyncio.gather(heartbeat_task, election_task, advance_task)

    async def _time_advance_loop(self):
        """Emit time advance events for expired buckets"""
        while self._running:
            try:
                if self.leader_election and self.leader_election.is_leader:
                    await self._process_time_advance()

                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Time advance error: {e}")
                await asyncio.sleep(1)

    async def _process_time_advance(self):
        """Check for expired buckets and emit events"""
        current_time = time.time()
        current_bucket = self.get_bucket(current_time)

        # Scan for timer registry keys
        registry_pattern = "timer:registry:*"
        cursor = 0
        expired_buckets = []

        while True:
            cursor, keys = await self.redis.scan(
                cursor,
                match=registry_pattern,
                count=100
            )

            for key in keys:
                # Parse bucket timestamp from key
                key_str = key.decode() if isinstance(key, bytes) else key
                bucket_ts = int(key_str.split(":")[-1])

                # Check if bucket has expired
                if bucket_ts <= current_bucket:
                    expired_buckets.append(bucket_ts)

            if cursor == 0:
                break

        # Emit time advance event for each expired bucket
        for bucket_ts in expired_buckets:
            await self._emit_time_advance(bucket_ts, current_time)

            # Delete registry key (bucket processed)
            await self.redis.delete(f"timer:registry:{bucket_ts}")

    async def _emit_time_advance(self, bucket: int, current_time: float):
        """Emit time advance event to stream"""
        stream_key = default_sharding.get_global_key("timer:time_advance")

        await self.redis.xadd(
            stream_key.encode(),
            {
                b"bucket": str(bucket).encode(),
                b"bucket_time": datetime.fromtimestamp(bucket).isoformat().encode(),
                b"current_time": str(current_time).encode(),
                b"timestamp": datetime.utcnow().isoformat().encode()
            }
        )

        logger.info(f"Time advanced to bucket {bucket} ({datetime.fromtimestamp(bucket)})")

    def get_bucket(self, timestamp: float) -> int:
        """Get bucket for a timestamp"""
        return int(timestamp // self.bucket_size) * self.bucket_size
```

#### TimerWorker (Refactored)

**Purpose**: Process time advance events and wake waiting tasks

**Responsibilities**:
- Subscribe to time advance stream (multiple workers can subscribe)
- For each time advance event:
  - Find all timers in that bucket (scan for metadata keys with that bucket)
  - Check exact wake_time in metadata
  - Mark tasks as completed if wake_time <= current_time
  - Emit to task:completed stream
  - Clean up metadata and pending sets

**Pseudo-code**:
```python
class TimerWorker(BaseWorker):
    """Worker that processes timer expirations from time advance events."""

    def get_base_streams(self) -> List[str]:
        """Streams this worker consumes"""
        return ["timer:time_advance"]  # Global stream

    async def process_message(
        self,
        stream: str,
        message_id: str,
        data: Dict
    ) -> bool:
        """Process time advance event"""
        try:
            if "timer:time_advance" in stream:
                return await self._handle_time_advance(data)
            return True
        except Exception as e:
            logger.error(f"Error processing time advance: {e}")
            return False

    async def _handle_time_advance(self, data: Dict) -> bool:
        """Handle time advance event - wake all timers in this bucket"""
        bucket = int(data.get('bucket', '0'))
        current_time = float(data.get('current_time', time.time()))

        logger.info(f"Processing time advance for bucket {bucket}")

        # Find all timer metadata keys
        # We need to scan all shards for metadata
        fired_count = 0

        for shard in range(16):  # Assuming 16 shards
            metadata_pattern = f"{{shard:{shard}}}:timer:metadata:*"
            cursor = 0

            while True:
                cursor, keys = await self.redis.scan(
                    cursor,
                    match=metadata_pattern,
                    count=100
                )

                for key in keys:
                    # Get timer metadata
                    metadata = await self.redis.hgetall(key)

                    if not metadata:
                        continue

                    # Check if timer is in this bucket
                    timer_bucket = int(metadata.get(b"bucket", b"0").decode())
                    if timer_bucket != bucket:
                        continue

                    # Check exact wake time
                    wake_time = float(metadata.get(b"wake_time", b"0").decode())
                    if wake_time > current_time:
                        # Not yet expired, skip
                        continue

                    # Timer expired! Process it
                    workflow_id = metadata.get(b"workflow_id", b"").decode()
                    task_id = metadata.get(b"task_id", b"").decode()
                    timer_type = metadata.get(b"timer_type", b"sleep").decode()

                    if timer_type == "retry":
                        await self._handle_retry_timer(workflow_id, task_id)
                    else:
                        await self._complete_timer_task(workflow_id, task_id, metadata)

                    # Clean up
                    await self.redis.delete(key)

                    # Remove from pending set
                    pending_key = default_sharding.get_timer_key("pending", workflow_id)
                    await self.redis.srem(pending_key, task_id)

                    fired_count += 1

                if cursor == 0:
                    break

        logger.info(f"Fired {fired_count} timers from bucket {bucket}")
        return True

    async def _complete_timer_task(
        self,
        workflow_id: str,
        task_id: str,
        metadata: Dict
    ):
        """Mark timer task as completed"""
        logger.info(f"Completing timer task {task_id} for workflow {workflow_id}")

        # Update task status
        await self.redis.hset(
            default_sharding.get_task_key(task_id, workflow_id).encode(),
            mapping={
                b"status": b"completed",
                b"completed_at": datetime.utcnow().isoformat().encode(),
                b"result": json.dumps({
                    "timer_fired": True,
                    "timer_type": metadata.get(b"timer_type", b"").decode()
                }).encode()
            }
        )

        # Emit completion event
        await self.redis.xadd(
            default_sharding.get_stream_key("task:completed", workflow_id).encode(),
            {
                b"workflow_id": workflow_id.encode(),
                b"task_id": task_id.encode(),
                b"result": json.dumps({"timer_fired": True}).encode(),
                b"timestamp": datetime.utcnow().isoformat().encode()
            }
        )

        # Emit event
        await self.event_store.store_event(
            event_type=EventType.TIMER_FIRED,
            workflow_id=workflow_id,
            task_id=task_id,
            level=EventLevel.IMPORTANT,
            data={"timer_type": metadata.get(b"timer_type", b"").decode()}
        )

    async def _handle_retry_timer(self, workflow_id: str, task_id: str):
        """Handle retry timer - re-queue task"""
        logger.info(f"Retry timer fired for task {task_id}")

        # Get workflow to extract task definition
        workflow_data = await self.redis.hget(
            default_sharding.get_workflow_key("data", workflow_id).encode(),
            b"workflow"
        )

        if not workflow_data:
            logger.error(f"Workflow not found: {workflow_id}")
            return

        workflow = json.loads(workflow_data)
        task_data = None

        for task in workflow.get('tasks', []):
            if task['id'] == task_id:
                task_data = task
                break

        if not task_data:
            logger.error(f"Task not found in workflow: {task_id}")
            return

        # Update status to pending
        await self.redis.hset(
            default_sharding.get_task_key(task_id, workflow_id).encode(),
            b"status",
            b"pending"
        )

        # Re-queue to task:ready
        await self.redis.xadd(
            default_sharding.get_stream_key("task:ready", workflow_id).encode(),
            {
                b"workflow_id": workflow_id.encode(),
                b"task_id": task_id.encode(),
                b"task": json.dumps(task_data).encode(),
                b"timestamp": datetime.utcnow().isoformat().encode()
            }
        )

        logger.info(f"Task {task_id} re-queued for retry")
```

#### Task Execution Worker (Modified)

**Changes**: When task returns `SCHEDULED` status, register timer using new system

**Pseudo-code**:
```python
async def emit_task_scheduled(
    self,
    task_id: str,
    workflow_id: str,
    result: TaskResult
):
    """Register timer in event-driven system"""
    wake_time = result.metadata.get('wake_time', 0)
    shard = default_sharding.get_shard(workflow_id)

    # Calculate bucket
    bucket = get_timer_bucket(wake_time)

    # Update task status
    await self.redis.hset(
        default_sharding.get_task_key(task_id, workflow_id).encode(),
        mapping={
            b"status": TaskStatus.SCHEDULED.encode(),
            b"wake_time": str(wake_time).encode(),
            b"timer_type": result.metadata.get('timer_type', 'sleep').encode(),
            b"bucket": str(bucket).encode(),
            b"scheduled_at": datetime.utcnow().isoformat().encode()
        }
    )

    # Store timer metadata
    metadata_key = default_sharding.get_timer_key("metadata", workflow_id, task_id)
    await self.redis.hset(
        metadata_key.encode(),
        mapping={
            b"workflow_id": workflow_id.encode(),
            b"task_id": task_id.encode(),
            b"shard": str(shard).encode(),
            b"wake_time": str(wake_time).encode(),
            b"timer_type": result.metadata.get('timer_type', 'sleep').encode(),
            b"bucket": str(bucket).encode(),
            b"created_at": datetime.utcnow().isoformat().encode(),
            b"duration_seconds": str(result.metadata.get('duration', 0)).encode()
        }
    )

    # Add to pending set
    pending_key = default_sharding.get_timer_key("pending", workflow_id)
    await self.redis.sadd(pending_key, task_id)

    # Register bucket (creates registry key if not exists)
    registry_key = f"timer:registry:{bucket}"
    await self.redis.set(registry_key, "", ex=int(wake_time - time.time() + 120))
    # ☝️ TTL ensures old buckets auto-cleanup

    # Optional: Add timeout support
    timeout = result.metadata.get('max_wait_time')
    if timeout:
        timeout_time = wake_time + timeout
        await self.redis.zadd(
            default_sharding.get_global_key("timer:timeouts").encode(),
            {f"{workflow_id}:{task_id}".encode(): timeout_time}
        )

    logger.info(
        f"Timer registered for task {task_id}: "
        f"wake_time={wake_time}, bucket={bucket}"
    )
```

#### Retry Worker (Modified)

**Changes**: Schedule retry timers using new system instead of sorted set

**Pseudo-code**:
```python
async def _schedule_retry(
    self,
    task_id: str,
    workflow_id: str,
    delay: float,
    next_attempt: int,
    error_msg: str
):
    """Schedule retry using timer system"""
    wake_time = time.time() + delay
    bucket = get_timer_bucket(wake_time)
    shard = default_sharding.get_shard(workflow_id)

    # Update task status
    await self.redis.hset(
        default_sharding.get_task_key(task_id, workflow_id).encode(),
        mapping={
            b"status": TaskStatus.SCHEDULED.encode(),
            b"retry_count": str(next_attempt).encode(),
            b"last_error": error_msg.encode(),
            b"wake_time": str(wake_time).encode(),
            b"timer_type": b"retry",
            b"bucket": str(bucket).encode(),
            b"last_attempt_at": datetime.utcnow().isoformat().encode()
        }
    )

    # Store timer metadata (same as regular timers)
    metadata_key = default_sharding.get_timer_key("metadata", workflow_id, task_id)
    await self.redis.hset(
        metadata_key.encode(),
        mapping={
            b"workflow_id": workflow_id.encode(),
            b"task_id": task_id.encode(),
            b"shard": str(shard).encode(),
            b"wake_time": str(wake_time).encode(),
            b"timer_type": b"retry",
            b"bucket": str(bucket).encode(),
            b"created_at": datetime.utcnow().isoformat().encode(),
            b"retry_attempt": str(next_attempt).encode(),
            b"last_error": error_msg.encode()
        }
    )

    # Add to pending set
    pending_key = default_sharding.get_timer_key("pending", workflow_id)
    await self.redis.sadd(pending_key, task_id)

    # Register bucket
    registry_key = f"timer:registry:{bucket}"
    await self.redis.set(registry_key, "", ex=int(delay + 120))

    # Emit event
    await self.event_store.store_event(
        event_type=EventType.TASK_RETRY_SCHEDULED,
        workflow_id=workflow_id,
        task_id=task_id,
        level=EventLevel.IMPORTANT,
        data={
            'attempt': next_attempt,
            'delay': delay,
            'wake_time': wake_time,
            'bucket': bucket,
            'error': error_msg
        }
    )

    logger.info(f"Retry scheduled for {task_id} in {delay:.2f}s (bucket={bucket})")
```

---

### 3. Sharding Helper Methods

Add to `src/gleitzeit/core/sharding.py`:

```python
def get_timer_key(
    self,
    timer_type: str,
    workflow_id: str,
    task_id: str = None
) -> str:
    """
    Get timer-related key with cluster routing.

    Args:
        timer_type: Type of timer key (metadata, pending, etc.)
        workflow_id: Workflow identifier
        task_id: Optional task ID

    Returns:
        Cluster key like "{shard:5}:timer:metadata:workflow123:task-abc"
    """
    shard = self.get_shard(workflow_id)
    base_key = f"{{shard:{shard}}}:timer:{timer_type}:{workflow_id}"

    if task_id:
        return f"{base_key}:{task_id}"
    return base_key

def get_timer_bucket(wake_time: float, bucket_size: int = 60) -> int:
    """
    Get the time bucket for a timer wake time.

    Args:
        wake_time: Unix timestamp when timer should fire
        bucket_size: Bucket size in seconds (default 60 = 1 minute)

    Returns:
        Bucket timestamp (aligned to bucket_size)

    Example:
        >>> get_timer_bucket(1761470383.5, 60)
        1761470340  # Bucket for 10:29:00-10:29:59
    """
    return int(wake_time // bucket_size) * bucket_size
```

---

## Migration Strategy

### Phase 1: Add New System (Parallel Operation)

1. **Deploy new components** (TimeAdvanceWorker, refactored TimerWorker)
2. **Keep old system running** (StatelessTimerManager still works)
3. **New timers use new system**
4. **Old timers processed by old system**
5. **Monitor both systems**

**Config flag**: `timer_system_version: "v2"` (default: "v1")

### Phase 2: Migrate Existing Timers

**One-time migration script**:

```python
async def migrate_timers():
    """Migrate existing timers from sorted set to registry system"""

    # Read all timers from old sorted set
    old_timers = await redis.zrange(
        "timers:pending",
        0, -1,
        withscores=True
    )

    for timer_id, wake_time in old_timers:
        # Parse timer ID: "timer-workflow123-abc" or "workflow123:task-abc:retry"
        if ":retry" in timer_id:
            # Retry timer format
            parts = timer_id.split(":")
            workflow_id = parts[0]
            task_id = parts[1]
            timer_type = "retry"
        else:
            # Regular timer - need to get metadata
            timer_meta = await redis.hgetall(f"timers:meta:{timer_id}")
            workflow_id = timer_meta.get(b"workflow_id", b"").decode()
            task_id = timer_meta.get(b"task_id", b"").decode()
            timer_type = timer_meta.get(b"timer_type", b"sleep").decode()

        if not workflow_id or not task_id:
            logger.warning(f"Skipping invalid timer: {timer_id}")
            continue

        # Calculate bucket
        bucket = get_timer_bucket(wake_time)
        shard = default_sharding.get_shard(workflow_id)

        # Create new metadata
        metadata_key = default_sharding.get_timer_key("metadata", workflow_id, task_id)
        await redis.hset(
            metadata_key.encode(),
            mapping={
                b"workflow_id": workflow_id.encode(),
                b"task_id": task_id.encode(),
                b"shard": str(shard).encode(),
                b"wake_time": str(wake_time).encode(),
                b"timer_type": timer_type.encode(),
                b"bucket": str(bucket).encode(),
                b"migrated_from": b"v1"
            }
        )

        # Add to pending set
        pending_key = default_sharding.get_timer_key("pending", workflow_id)
        await redis.sadd(pending_key, task_id)

        # Register bucket
        registry_key = f"timer:registry:{bucket}"
        await redis.set(registry_key, "", ex=int(wake_time - time.time() + 120))

        logger.info(f"Migrated timer {timer_id} to bucket {bucket}")

    logger.info(f"Migration complete: {len(old_timers)} timers migrated")
```

### Phase 3: Remove Old System

1. **Verify all timers migrated**
2. **Stop writing to old sorted set**
3. **Remove StatelessTimerManager**
4. **Remove old timer worker code**
5. **Clean up Redis keys**

---

## Comparison: Old vs New

| Feature | Old (Sorted Set) | New (Event-Driven) |
|---------|------------------|-------------------|
| **Data Structure** | Sorted set + hash | Registry + stream + set + hash |
| **Polling** | ✅ ZRANGEBYSCORE every 1s | ⚠️ SCAN registry every 1s (lighter) |
| **Key Consistency** | ❌ Broken for retries | ✅ Uses sharding throughout |
| **Horizontal Scaling** | ❌ Leader only | ✅ Multiple workers consume stream |
| **Observability** | ❌ No audit trail | ✅ Stream = audit log |
| **Timeout Support** | ❌ No | ✅ Yes (optional sorted set) |
| **Complexity** | Low | Medium |
| **Redis Ops/timer** | 2 (ZADD + HSET) | 4 (SET + HSET + SADD + XADD) |
| **Time Resolution** | 1 second | Configurable (bucket size) |

---

## Alternative: Hybrid Approach

**Keep sorted sets but fix key naming**:

### Pros
- Minimal changes (just fix key constants)
- Proven sorted set approach
- Simple to understand

### Cons
- Still requires polling
- No audit trail
- No horizontal scaling
- Sorted sets can get large

### Implementation

Just change `StatelessTimerManager` constants:

```python
# In stateless_timer_manager.py
from ..core.sharding import default_sharding

# Before:
PENDING_TIMERS_KEY = "timers:pending"

# After:
@staticmethod
def get_pending_key() -> str:
    return default_sharding.get_global_key("timers:pending")
```

And update all usages to call `get_pending_key()` instead of using the constant.

**This is the quick fix**. Event-driven is the long-term solution.

---

## Recommendations

### Short-term (Fix the Bug)

**Use Hybrid Approach**:
1. Update `StatelessTimerManager` to use `default_sharding.get_global_key()`
2. Migrate existing timers from `timers:pending` to `{shard:0}:global:timers:pending`
3. Test thoroughly
4. Deploy

**Timeline**: 1-2 days

### Long-term (Better Architecture)

**Refactor to Event-Driven**:
1. Implement TimeAdvanceWorker
2. Refactor TimerWorker to consume events
3. Update Task Execution Worker and Retry Worker
4. Add migration script
5. Parallel operation period (both systems running)
6. Migrate all timers
7. Remove old system

**Timeline**: 2-3 weeks

### Recommended Path

1. **Immediate**: Fix key mismatch with hybrid approach (unblocks retries)
2. **Q1 2026**: Refactor to event-driven architecture (better long-term)

---

## Open Questions

1. **Bucket size**: 60 seconds optimal? Trade-off between registry size and time resolution
2. **Timeout support**: Should timers have max wait time? (signals have this)
3. **Horizontal scaling**: How many timer workers can we run? (Limited by stream throughput)
4. **Cleanup**: How to clean up stale timers if task/workflow deleted?
5. **Monitoring**: What metrics to track? (bucket lag, fired timers/sec, etc.)
6. **Backwards compatibility**: Support both systems during migration?

---

## Success Criteria

### Functional Requirements

- ✅ Regular timers work (timer/sleep, timer/wait_until)
- ✅ Retry timers work (no key mismatch)
- ✅ Timers fire within 1 second of wake_time
- ✅ No timers lost during system restart
- ✅ Timers work across all shards

### Non-Functional Requirements

- ✅ Horizontal scaling: 3+ timer workers
- ✅ Throughput: 1000+ timers/second
- ✅ Latency: <1 second from wake_time to task completion
- ✅ Observability: Complete audit trail in streams
- ✅ Monitoring: Metrics for timer lag, throughput, errors

### Testing Requirements

- ✅ Unit tests for all components
- ✅ Integration test: end-to-end timer flow
- ✅ Load test: 10,000 concurrent timers
- ✅ Failure test: timer worker crashes and recovers
- ✅ Migration test: migrate 1000 timers from old to new system

---

## Appendix: Code Samples

### A. Timer Helper Functions

```python
# In timers/helpers.py

def get_timer_bucket(wake_time: float, bucket_size: int = 60) -> int:
    """Get the bucket timestamp for a wake time."""
    return int(wake_time // bucket_size) * bucket_size

def get_bucket_range(bucket: int, bucket_size: int = 60) -> tuple[float, float]:
    """Get the time range for a bucket."""
    return (float(bucket), float(bucket + bucket_size))

def is_timer_expired(wake_time: float, current_time: float) -> bool:
    """Check if a timer has expired."""
    return wake_time <= current_time

async def cleanup_timer(redis, workflow_id: str, task_id: str):
    """Clean up all timer data for a task."""
    # Remove metadata
    metadata_key = default_sharding.get_timer_key("metadata", workflow_id, task_id)
    await redis.delete(metadata_key.encode())

    # Remove from pending set
    pending_key = default_sharding.get_timer_key("pending", workflow_id)
    await redis.srem(pending_key, task_id)

    # Remove from timeout queue if exists
    timeout_key = default_sharding.get_global_key("timer:timeouts")
    await redis.zrem(timeout_key.encode(), f"{workflow_id}:{task_id}")
```

### B. Timer Metrics

```python
# In timers/metrics.py

class TimerMetrics:
    """Track timer system metrics."""

    @staticmethod
    async def record_timer_created(redis, workflow_id: str, timer_type: str):
        """Increment timer created counter."""
        key = f"metrics:timers:created:{timer_type}"
        await redis.incr(key)

    @staticmethod
    async def record_timer_fired(redis, workflow_id: str, latency: float):
        """Record timer fired with latency."""
        await redis.incr("metrics:timers:fired")

        # Track latency histogram
        bucket = int(latency * 10)  # 100ms buckets
        await redis.hincrby("metrics:timers:latency_histogram", bucket, 1)

    @staticmethod
    async def get_pending_timer_count(redis) -> int:
        """Get total pending timer count across all workflows."""
        count = 0
        for shard in range(16):
            pattern = f"{{shard:{shard}}}:timer:pending:*"
            cursor = 0
            while True:
                cursor, keys = await redis.scan(cursor, match=pattern, count=100)
                for key in keys:
                    count += await redis.scard(key)
                if cursor == 0:
                    break
        return count
```

---

## Conclusion

**Event-driven timer architecture** eliminates the key mismatch bug, provides better observability, and enables horizontal scaling. While more complex than sorted sets, it aligns with the signal system's proven architecture.

**Recommended approach**:
1. **Quick fix**: Update StatelessTimerManager to use sharded keys
2. **Long-term**: Refactor to event-driven architecture with time buckets

This design draft provides a complete roadmap for either approach.
