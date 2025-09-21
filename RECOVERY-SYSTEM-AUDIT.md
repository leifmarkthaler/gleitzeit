# Gleitzeit Recovery System Audit

## Executive Summary
The current recovery system has fundamental architectural issues that violate stateless, scalable design principles.

## Critical Issues Found

### 1. ANTI-PATTERN: Persistent Loops
**Location**: `src/gleitzeit/events/stream_event_bus.py`

The system uses persistent async loops that violate stateless architecture:
- `_consume_events()` - Persistent while loop
- `_claim_idle_messages()` - Runs every 30 seconds in a loop
- These loops create state that persists with the instance

**Problem**: In a horizontally scaled environment, each instance maintains its own loops, leading to:
- Resource waste
- Potential race conditions
- Inability to scale down cleanly

### 2. MISSING: Idempotency Checks
**Critical Gap**: No verification if messages can be safely rerun

The `_process_event()` method blindly reprocesses messages without checking:
- Whether the task has already been completed
- Whether the task is idempotent
- Whether rerunning would cause side effects

**Code Analysis**:
```python
# Line 494-497 in stream_event_bus.py
success = await self._process_event(event_type, data, msg_id, stream_key)
if success:
    await self.redis.xack(stream_key, self.consumer_group, msg_id)
```

No checks for:
- Task completion status
- Duplicate processing
- Side effect safety

### 3. INCORRECT: Consumer Group Management
**Issue**: Dead consumers accumulate but aren't cleaned up properly

Evidence from Redis:
- 24 consumers in `gleitzeit-workers` group
- Most are dead (from crashed instances)
- No automatic cleanup mechanism
- No consumer heartbeat/TTL

### 4. ARCHITECTURAL VIOLATION: Stateful Recovery
The current recovery mechanisms maintain state:
- Consumer IDs persist with instances
- Loops maintain internal state
- No external coordination for recovery

## Correct Stateless Recovery Architecture

### 1. Event-Driven Recovery (No Loops)
```python
# Instead of loops, use Redis keyspace notifications or external triggers
async def handle_recovery_trigger(event):
    """Triggered by external event, not a loop"""
    # Check for stuck messages
    # Claim if eligible
    # Process once
    # Exit
```

### 2. Idempotency Protection
```python
async def can_safely_rerun(task_id: str) -> bool:
    """Check if task can be safely rerun"""
    # Check task status
    task = await persistence.get_task(task_id)

    if task.status == 'completed':
        return False  # Already done

    if task.status == 'executing':
        # Check if executor is still alive
        if await is_executor_alive(task.executor_id):
            return False  # Still being processed

    # Check idempotency flag
    if not task.is_idempotent:
        if task.attempt_count > 0:
            return False  # Can't safely retry non-idempotent tasks

    return True
```

### 3. Stateless Consumer Cleanup
```python
# Use Redis EXPIRE on consumer registration
async def register_consumer(consumer_id: str):
    """Register with TTL, auto-cleanup on death"""
    await redis.setex(
        f"consumer:{consumer_id}",
        ttl=60,  # 60 second TTL
        value="alive"
    )

# Consumer heartbeat (called on each message process)
async def heartbeat(consumer_id: str):
    """Extend TTL on activity"""
    await redis.expire(f"consumer:{consumer_id}", 60)
```

### 4. External Recovery Coordinator
Instead of each instance running loops:
- Use Redis timers/cron
- Use Kubernetes CronJobs
- Use external monitoring that triggers recovery

## Impact Analysis

### Current Problems Caused
1. **Workflow Stuck in Pending**: Dead consumers holding messages
2. **Multiple Server Instances**: Each trying to recover independently
3. **Resource Waste**: Multiple loops checking same data
4. **Race Conditions**: Multiple instances claiming same messages

### Required Changes

1. **Remove Persistent Loops**
   - Replace with event-driven triggers
   - Use Redis keyspace notifications
   - Implement proper TTLs

2. **Add Idempotency Checks**
   - Check task status before rerun
   - Implement idempotency flags
   - Track processing attempts

3. **Implement Proper Consumer Lifecycle**
   - Consumer registration with TTL
   - Automatic cleanup on expiry
   - Heartbeat mechanism

4. **Stateless Recovery Service**
   - External trigger (timer/cron)
   - Single recovery attempt per trigger
   - No persistent state

## Recommendations

### Immediate Actions
1. Kill all stale consumers manually (temporary fix)
2. Reduce claim_idle_time to detect dead consumers faster
3. Add task status checks before reprocessing

### Long-term Architecture
1. Implement stateless recovery service
2. Add idempotency metadata to tasks
3. Use Redis TTLs for consumer lifecycle
4. Remove all persistent loops
5. Implement external recovery coordinator

## Conclusion

The current recovery system violates stateless architecture principles and lacks critical safety checks. It maintains persistent state through loops, doesn't verify if tasks can be safely rerun, and allows dead consumers to accumulate indefinitely. This leads to stuck workflows, resource waste, and potential data corruption from unsafe reruns.

The system needs fundamental restructuring to:
- Eliminate persistent loops
- Add idempotency protection
- Implement proper consumer lifecycle management
- Move to event-driven, stateless recovery