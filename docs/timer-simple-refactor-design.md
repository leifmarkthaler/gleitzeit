# Timer System Refactor: Remove Buckets, Direct Scanning

## Problem Statement

The current bucket-based timer system has fundamental flaws:

1. **Silent failures**: Registry keys with TTL expire, timers get lost
2. **Poor granularity**: Timers only fire once per 60-second bucket
3. **Complex coordination**: Requires time_advance_worker + timer_worker + registry keys
4. **Not auditable**: When timers fail, there's no clear audit trail
5. **Violates Gleitzeit principles**: System should be reproducible with full audit

## Current Architecture (BROKEN)

```
Task Execution → Creates timer metadata + bucket + registry key (with TTL)
                          ↓
TimeAdvanceWorker → Scans registry keys every 1s
                  → Only processes once per 60s bucket
                  → Emits time_advance event to stream
                          ↓
TimerWorker → Consumes time_advance events
            → Scans all timer metadata for matching bucket
            → Fires timers where wake_time <= current_time
            → Deletes timer metadata

Problem: Registry keys expire before processing, timers lost forever
Problem: 60-second bucket granularity breaks short timers
Problem: Complex, hard to audit, prone to silent failures
```

## New Architecture (SIMPLE)

```
Task Execution → Creates timer metadata ONLY
                 - No buckets
                 - No registry keys
                 - No TTLs
                 - Just: {workflow_id, task_id, wake_time, timer_type}
                          ↓
TimerWorker → Wakes every 1 second
            → Scans ALL timer metadata across shards
            → Fires timers where wake_time <= current_time
            → Deletes timer metadata
            → Emits events for full audit

TimeAdvanceWorker → DELETED (not needed)
```

## Data Structures

### Timer Metadata (per timer)
**Key**: `{shard:N}:timer:metadata:{workflow_id}:{task_id}`

**Fields**:
```
workflow_id: <uuid>
task_id: <uuid>
shard: <0-15>
wake_time: <unix_timestamp_float>
timer_type: "sleep" | "retry"
created_at: <iso8601>
# For retry timers only:
retry_attempt: <int>
last_error: <string>
```

**NO TTL** - Explicit deletion only after firing

### Timer Pending Set (per workflow)
**Key**: `{shard:N}:timer:pending:{workflow_id}`

**Members**: Set of task_ids with pending timers

**Purpose**: Quick lookup of which workflows have timers, reconciliation

### Task Status
**Key**: `{shard:N}:task:{task_id}:{workflow_id}`

**Relevant Fields**:
```
status: "scheduled"  # When timer is waiting
wake_time: <unix_timestamp>
timer_type: "sleep" | "retry"
scheduled_at: <iso8601>
```

## TimerWorker Behavior

### Main Loop (every 1 second)

```python
async def run(self):
    while running:
        current_time = time.time()

        # Scan all shards for expired timers
        for shard in range(16):
            await self._scan_shard_for_expired_timers(shard, current_time)

        await asyncio.sleep(1)  # 1 second granularity

async def _scan_shard_for_expired_timers(self, shard: int, current_time: float):
    """Scan one shard for expired timers"""
    pattern = f"{{shard:{shard}}}:timer:metadata:*"

    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match=pattern, count=100)

        for key in keys:
            metadata = await redis.hgetall(key)
            wake_time = float(metadata['wake_time'])

            if wake_time <= current_time:
                # Timer expired!
                await self._fire_timer(metadata)
                await redis.delete(key)

        if cursor == 0:
            break

async def _fire_timer(self, metadata):
    """Fire an expired timer"""
    workflow_id = metadata['workflow_id']
    task_id = metadata['task_id']
    timer_type = metadata['timer_type']

    # Emit audit event
    await event_store.store_event(
        event_type=EventType.TIMER_FIRED,
        workflow_id=workflow_id,
        task_id=task_id,
        level=EventLevel.IMPORTANT,
        data={
            'wake_time': metadata['wake_time'],
            'fired_at': time.time(),
            'timer_type': timer_type
        }
    )

    if timer_type == "retry":
        await self._handle_retry_timer(workflow_id, task_id, metadata)
    else:
        await self._complete_timer_task(workflow_id, task_id, metadata)

    # Remove from pending set
    pending_key = f"{{shard:N}}:timer:pending:{workflow_id}"
    await redis.srem(pending_key, task_id)
```

## Horizontal Scaling

**Problem**: Multiple timer workers scanning the same timers would fire them multiple times.

**Solution**: Use Redis Lua script for atomic check-and-delete:

```lua
-- get_and_delete_if_expired.lua
local key = KEYS[1]
local current_time = tonumber(ARGV[1])

local metadata = redis.call('HGETALL', key)
if #metadata == 0 then
    return nil  -- Already deleted
end

-- Parse metadata
local wake_time = nil
for i = 1, #metadata, 2 do
    if metadata[i] == 'wake_time' then
        wake_time = tonumber(metadata[i+1])
        break
    end
end

if wake_time and wake_time <= current_time then
    -- Expired! Delete and return metadata
    redis.call('DEL', key)
    return metadata
else
    -- Not expired yet
    return nil
end
```

Each timer worker calls this script. Only one worker gets the metadata, others get nil. Race-free!

## Performance Analysis

### Scan Overhead

**Worst case**:
- 16 shards
- 1000 timers per shard = 16,000 total timers
- SCAN with count=100 → ~160 SCAN calls per second
- Each timer: HGETALL (1 round-trip)
- If expired: Lua script (1 round-trip)

**With Redis pipelining**:
- Batch SCAN results
- Pipeline Lua script calls
- Estimated: ~200-300ms total per scan cycle at 16K timers

**Optimization**: Index timers by wake_time range using sorted set:
```
ZADD timer:wake_index {wake_time} "{shard}:{workflow_id}:{task_id}"
ZRANGEBYSCORE timer:wake_index -inf {current_time}
```

This reduces scan to O(log N + K) where K = expired timers.

## Migration Path

1. **Phase 1**: Deploy new TimerWorker alongside old system
   - New timers use simple metadata
   - Old timers continue with buckets
   - Both workers run

2. **Phase 2**: Stop creating bucket-based timers
   - Update task_execution_worker
   - Update retry_worker
   - Let old timers drain

3. **Phase 3**: Remove old system
   - Delete TimeAdvanceWorker
   - Delete registry keys
   - Clean up old timer metadata

## Auditability

Every timer operation emits events:

1. **TIMER_CREATED** - When timer is scheduled
   - workflow_id, task_id, wake_time, timer_type, duration_seconds

2. **TIMER_FIRED** - When timer expires
   - workflow_id, task_id, wake_time, fired_at, timer_type

3. **TASK_COMPLETED** - When timer task completes
   - workflow_id, task_id, result

Full audit trail: Created → Fired → Completed (or Failed)

## Reconciliation

Reconciliation worker can detect stuck timers:

```sql
SELECT * FROM timer:metadata
WHERE wake_time < (current_time - 300)  -- 5 min old
AND task still in 'scheduled' status

→ Alert: Timer stuck, never fired
→ Action: Manually fire or mark as failed
→ Root cause: TimerWorker crashed/stuck
```

## Benefits

✅ **Simple**: One worker, direct scan, no complex coordination
✅ **Reliable**: No TTLs, explicit cleanup only
✅ **Auditable**: Full event trail for every timer
✅ **Fast**: 1-second granularity, fires timers on time
✅ **Scalable**: Lua script prevents duplicate firing
✅ **Reproducible**: Reconciliation detects stuck timers

## Implementation Checklist

- [ ] Create Lua script for atomic get-and-delete
- [ ] Rewrite TimerWorker with direct scanning
- [ ] Remove bucket/registry logic from task_execution_worker
- [ ] Remove bucket/registry logic from retry_worker
- [ ] Remove TimeAdvanceWorker entirely
- [ ] Update gleitzeit.yaml to remove time_advance worker
- [ ] Add reconciliation checks for stuck timers
- [ ] Test with 5-second timers (should fire at exactly 5s ± 1s)
- [ ] Test horizontal scaling (multiple timer workers)
- [ ] Verify full audit trail in event store
