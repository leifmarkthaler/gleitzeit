# Timer and Signal Systems Stateless Redesign

## Current State Analysis

Both the Timer and Signal systems in Gleitzeit have critical stateless and scalability issues that prevent horizontal scaling.

## Timer System Issues

### 1. Stateful Components in TimerMonitorService
```python
# src/gleitzeit/timers/monitor.py
self.running = False  # Line 31 - instance state
self._monitor_task: Optional[asyncio.Task] = None  # Line 32 - local task reference
```

### 2. Stateful Components in TimerManager
```python
# src/gleitzeit/timers/timer_manager.py
self._monitor_task: Optional[asyncio.Task] = None  # Line 68 - local task
self._is_leader = False  # Line 69 - instance state
```

### 3. Distributed Mode Issues
- Uses leader election but leader state is in-memory (`self._is_leader`)
- If leader crashes, state is lost
- No consumer groups for work distribution
- All-or-nothing approach (one leader processes all)

## Signal System Issues

### 1. Critical Stateful Components in SignalMonitorService
```python
# src/gleitzeit/signals/monitor.py
self.running = False  # Line 32 - instance state
self._monitor_task: Optional[asyncio.Task] = None  # Line 33 - local task
self._stream_positions: Dict[str, str] = {}  # Line 34 - CRITICAL: stream positions in memory!
```

### 2. No Consumer Groups
- Uses basic `xread` instead of `xreadgroup`
- Multiple instances would read same messages
- Stream positions lost on restart
- No acknowledgment mechanism

### 3. No Distributed Coordination
- Every instance runs its own monitor
- No leader election at all
- Guaranteed duplicate processing with multiple instances

## Why This Breaks Horizontal Scaling

### Timer System
1. **Leader Failover**: If leader crashes, `_is_leader` state lost
2. **No Work Distribution**: Only one instance processes all timers
3. **Memory State**: Local variables prevent seamless failover

### Signal System
1. **Stream Position Loss**: Positions in memory = lost on restart
2. **Duplicate Processing**: No consumer groups = all instances process same signals
3. **No Coordination**: Every instance processes everything

## Required Architecture: Event-Driven Task Queue

### Core Principle
Both timers and signals should be processed as tasks through the existing task queue infrastructure, not as separate background services.

### Architecture Flow
```
Timer/Signal Created → Redis Event → Task Queue → Worker Processes → Action
```

## Redesign Plan

### Phase 1: Make Current Implementation Stateless

#### Timer System
1. Store leader state in Redis, not memory
2. Store monitor task ID in Redis
3. Use Redis for all coordination

```python
# Instead of:
self._is_leader = False

# Use:
await redis.hset(f"timer:manager:{instance_id}", "is_leader", "true")
```

#### Signal System
1. **Use Consumer Groups** (CRITICAL)
```python
# Create consumer group
await redis.xgroup_create(
    f"workflow:signals:{workflow_id}",
    "signal-processors",
    id="0"
)

# Read with consumer group (instead of xread)
messages = await redis.xreadgroup(
    "signal-processors",
    instance_id,
    {stream_key: ">"},
    count=100,
    block=1000
)

# Acknowledge processed messages
await redis.xack(stream_key, "signal-processors", message_id)
```

2. **Remove _stream_positions dict**
   - Consumer groups track positions automatically
   - Positions persist in Redis
   - Survive restarts

### Phase 2: Event-Driven Architecture

#### Convert Timer Monitoring to Tasks
```python
# When timer expires, create a wake task
wake_task = {
    "protocol": "timer/v1",
    "method": "timer/wake",
    "params": {
        "timer_id": timer_id,
        "workflow_id": workflow_id,
        "task_id": task_id
    }
}
# Submit to task queue
await task_queue.submit(wake_task)
```

#### Convert Signal Processing to Tasks
```python
# When signal sent, create processing task
signal_task = {
    "protocol": "signal/v1",
    "method": "signal/process",
    "params": {
        "signal": signal_name,
        "payload": payload,
        "workflow_id": workflow_id
    }
}
# Submit to task queue
await task_queue.submit(signal_task)
```

### Phase 3: Remove Background Services

1. **Remove TimerMonitorService**
   - Timer checks become scheduled tasks
   - Workers process timer wake events

2. **Remove SignalMonitorService**
   - Signals processed as tasks
   - Workers handle signal wake events

3. **Simplify Managers**
   - No background tasks to manage
   - Just coordinate task submission

## Implementation Priority

### Immediate Fixes (Phase 1)
1. **Signal System Consumer Groups** (CRITICAL)
   - Prevents duplicate processing
   - Required for any multi-instance deployment

2. **Remove In-Memory State**
   - Store all state in Redis
   - Use Redis for coordination

### Medium Term (Phase 2)
3. **Event-Driven Refactor**
   - Convert to task-based processing
   - Leverage existing infrastructure

### Long Term (Phase 3)
4. **Remove Background Services**
   - Simplify architecture
   - True stateless operation

## Testing Requirements

### Multi-Instance Tests
```python
# Start 3 instances
instance1 = start_server(port=8001)
instance2 = start_server(port=8002)
instance3 = start_server(port=8003)

# Send 100 signals
for i in range(100):
    client.send_signal(f"test-{i}", {"data": i})

# Verify:
# - No duplicate processing
# - Signals distributed across instances
# - All signals processed exactly once
```

### Failover Tests
```python
# Start processing
start_signal_processing()

# Kill leader instance
kill_instance(leader_id)

# Verify:
# - Another instance takes over
# - No signals lost
# - Processing continues
```

### State Persistence Tests
```python
# Process some signals
process_signals()

# Restart all instances
restart_all_instances()

# Verify:
# - Stream positions recovered
# - Processing continues from correct position
# - No reprocessing of old signals
```

## Code Examples

### Stateless Signal Monitor (Fixed)
```python
class StatelessSignalMonitor:
    """Truly stateless signal monitor using consumer groups"""
    
    def __init__(self, redis_client, instance_id: str):
        self.redis = redis_client
        self.instance_id = instance_id
        self.consumer_group = "signal-processors"
    
    async def process_signals(self):
        """Process signals using consumer group - no in-memory state!"""
        
        # Find all signal streams
        streams = {}
        async for key in self.redis.scan_iter("workflow:signals:*"):
            # Consumer group tracks position automatically
            streams[key] = ">"
        
        if not streams:
            return 0
        
        # Read with consumer group (distributed, exactly-once)
        messages = await self.redis.xreadgroup(
            self.consumer_group,
            self.instance_id,
            streams,
            count=100,
            block=1000
        )
        
        for stream_key, stream_messages in messages.items():
            for message_id, data in stream_messages:
                try:
                    # Process signal
                    await self.process_signal(data)
                    
                    # Acknowledge (removes from pending)
                    await self.redis.xack(
                        stream_key,
                        self.consumer_group,
                        message_id
                    )
                except Exception as e:
                    # Failed messages stay in pending list
                    # Will be retried by another consumer
                    logger.error(f"Failed to process {message_id}: {e}")
```

### Stateless Timer Monitor (Fixed)
```python
class StatelessTimerMonitor:
    """Truly stateless timer monitor with Redis coordination"""
    
    def __init__(self, redis_client, instance_id: str):
        self.redis = redis_client
        self.instance_id = instance_id
    
    async def acquire_leadership(self) -> bool:
        """Try to become leader - state in Redis, not memory"""
        
        # Atomic operation with TTL
        acquired = await self.redis.set(
            "timer:monitor:leader",
            self.instance_id,
            nx=True,  # Only if not exists
            ex=10     # 10 second TTL
        )
        return bool(acquired)
    
    async def is_leader(self) -> bool:
        """Check leadership from Redis - no local state"""
        
        leader = await self.redis.get("timer:monitor:leader")
        if isinstance(leader, bytes):
            leader = leader.decode()
        return leader == self.instance_id
    
    async def process_timers(self):
        """Process timers only if leader - stateless check"""
        
        if not await self.is_leader():
            return
        
        # Process expired timers
        # ...
```

## Summary

Both Timer and Signal systems need fundamental redesign:

1. **Immediate**: Fix Signal system with consumer groups
2. **Critical**: Remove ALL in-memory state
3. **Strategic**: Move to event-driven task-based architecture
4. **Goal**: True stateless, horizontally scalable operation

The current implementations will fail in any multi-instance deployment. These changes are required for production readiness.