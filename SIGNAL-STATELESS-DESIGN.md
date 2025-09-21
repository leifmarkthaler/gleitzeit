# Stateless Signal System Design

## Core Principle: Event-Driven, Not Monitor-Based

Instead of a background monitor service, signals should be processed through the existing task queue infrastructure.

## Architecture

```
Signal Sent → Redis Stream → Task Queue → Worker Processes → Wake Waiting Task
```

## Implementation Strategy

### 1. SignalProvider (signal/v1)
The provider handles signal operations as tasks:

```python
async def execute(self, method: str, params: Dict) -> Any:
    if method == "signal/wait":
        # Register waiter in Redis
        await self.register_waiter(workflow_id, task_id, signal_name)
        # Return SLEEPING status
        return TaskStatus.SLEEPING
    
    elif method == "signal/send":
        # Create wake task for the signal
        await self.create_wake_task(signal_name, payload)
        return {"sent": True}
```

### 2. Signal Wake Tasks
When a signal is sent, create a task to wake waiters:

```python
# Instead of monitor service processing signals
# Create a task that wakes the appropriate waiters
wake_task = {
    "protocol": "signal/v1",
    "method": "signal/wake",
    "params": {
        "signal": signal_name,
        "payload": payload
    }
}
# Submit to task queue for processing
```

### 3. Redis Data Structures (Stateless)

All state in Redis, no in-memory tracking:

```python
# Waiters set - who's waiting for each signal
signal:{signal_name}:waiters -> SET of waiter_ids

# Waiter metadata - details about each waiter  
signal:waiter:{waiter_id} -> HASH {
    workflow_id, task_id, signal, timeout, created_at
}

# Consumer group for signal streams
workflow:signals:{workflow_id} -> STREAM with consumer group
```

### 4. Consumer Groups for Scaling

Use Redis Streams consumer groups for horizontal scaling:

```python
# Create consumer group for signal processing
await redis.xgroup_create(
    f"workflow:signals:{workflow_id}",
    "signal-processors",
    id="0"
)

# Each instance reads from group
messages = await redis.xreadgroup(
    "signal-processors",
    consumer_id,
    {stream_key: ">"},
    block=1000
)

# Acknowledge processed messages
await redis.xack(stream_key, "signal-processors", message_id)
```

### 5. No Background Services

Remove SignalMonitorService entirely. Instead:
- Signals processed as tasks
- Workers handle signal operations
- No separate monitoring needed

## Benefits

1. **Truly Stateless**: No in-memory state
2. **Horizontally Scalable**: Consumer groups distribute work
3. **Fault Tolerant**: Redis persists all state
4. **No Duplicate Processing**: Consumer groups ensure once-only
5. **Integrated**: Uses existing task infrastructure

## Migration Path

### Phase 1: Make Current Implementation Stateless
- Store stream positions in Redis
- Use consumer groups
- Remove in-memory state

### Phase 2: Event-Driven Refactor
- Convert monitor to task-based
- Use task queue for processing
- Remove background service

### Phase 3: Full Integration
- Signals as first-class tasks
- Complete provider implementation
- Remove SignalMonitorService

## Code Example: Stateless Signal Wake

```python
async def process_signal_wake(self, signal_name: str, payload: Dict):
    """Process signal wake as a task - completely stateless"""
    
    # Get waiters from Redis (not memory!)
    waiters_key = f"signal:{signal_name}:waiters"
    waiter_ids = await self.redis.smembers(waiters_key)
    
    for waiter_id in waiter_ids:
        # Get waiter metadata from Redis
        waiter_key = f"signal:waiter:{waiter_id}"
        waiter_data = await self.redis.hgetall(waiter_key)
        
        if not waiter_data:
            continue
            
        workflow_id = waiter_data.get("workflow_id")
        task_id = waiter_data.get("task_id")
        
        # Wake the task through task queue
        await self.wake_task(workflow_id, task_id, {
            "signal": signal_name,
            "payload": payload
        })
        
        # Clean up Redis
        await self.redis.srem(waiters_key, waiter_id)
        await self.redis.delete(waiter_key)
```

## Testing for Scalability

1. **Multi-Instance Test**:
   - Start 3 instances
   - Send 100 signals
   - Verify no duplicates
   - Check distribution

2. **Failover Test**:
   - Kill instance processing signals
   - Verify another takes over
   - No signal loss

3. **State Persistence Test**:
   - Process signals
   - Restart all instances
   - Verify state recovered

## Summary

The current signal implementation is NOT stateless or scalable. It needs:
1. Remove ALL in-memory state
2. Use Redis consumer groups
3. Process signals as tasks
4. No background monitor service

This will make signals truly stateless and horizontally scalable, aligning with Gleitzeit's architecture.