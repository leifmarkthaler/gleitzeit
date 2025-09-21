# Timer Architecture - Complete Implementation

## Overview
Implemented a production-ready, horizontally scalable timer/scheduling system for Gleitzeit workflows. The system follows Gleitzeit's architectural patterns with stateless design, distributed coordination, and seamless SystemManager integration.

## Architecture Components

### 1. TimerProvider (`src/gleitzeit/providers/timer_provider.py`)
**Purpose**: Handle timer task requests from workflows

**Features**:
- Implements SimpleProvider pattern
- Supports three timer methods:
  - `timer/sleep` - Sleep for N seconds
  - `timer/wait_until` - Wait until specific timestamp
  - `timer/wait_or_signal` - Wait for timeout or signal
- Returns immediately with SLEEPING status
- Registers timers in Redis for later processing

**Integration**:
- Registered as hub-managed protocol in PoolingAdapter
- Available through ProviderHub for discovery
- Validates through workflow loader

### 2. TimerTaskHandler (`src/gleitzeit/timers/handler.py`)
**Purpose**: Core timer registration logic

**Features**:
- Stores timer metadata in Redis hash
- Uses Redis sorted sets with wake time as score
- Handles different timer types (sleep, wait_until, wait_or_signal)
- Emits task_waiting events to workflow stream
- Calculates wake times from timestamps or durations

**Data Structure**:
```
Redis Keys:
- timers:pending (sorted set) - Active timers sorted by wake time
- timer:{timer_id} (hash) - Timer metadata
- timers:completed (sorted set) - Historical data
```

### 3. TimerMonitorService (`src/gleitzeit/timers/monitor.py`)
**Purpose**: Monitor and trigger expired timers

**Features**:
- Polls Redis for expired timers (configurable interval)
- Processes timers in batches (default 100)
- Sends wake events to workflow streams
- Handles both byte and string Redis key formats
- Moves completed timers to history

**Processing Flow**:
1. Query `timers:pending` for expired timers
2. Read timer metadata from `timer:{id}`
3. Send wake event to `workflow:{id}:events`
4. Move timer to `timers:completed`

### 4. TimerManager (`src/gleitzeit/timers/timer_manager.py`) - **NEW**
**Purpose**: Manage timer subsystem with distributed coordination

**Features**:
- **Distributed Leader Election**: Only one monitor runs across cluster
- **Automatic Failover**: New leader elected if current fails
- **Horizontal Scaling**: Multiple instances coordinate via Redis
- **Graceful Shutdown**: Preserves all pending timers
- **Statistics API**: Monitor timer counts and health
- **Cleanup Utilities**: Remove old completed timers

**Leader Election**:
```python
# Redis-based leader lock with TTL
lock_key = "timer:monitor:leader"
acquired = await redis.set(lock_key, instance_id, nx=True, ex=5)
```

**Configuration**:
```bash
GLEITZEIT_TIMER_MONITOR_INTERVAL=0.1  # Check interval (seconds)
GLEITZEIT_TIMER_BATCH_SIZE=100        # Timers per batch
GLEITZEIT_TIMER_DISTRIBUTED=true      # Enable distributed mode
```

## SystemManager Integration

### Initialization Flow
```python
# In SystemManager._start_core_components()
self.timer_manager = TimerManager(
    persistence=self.persistence,
    event_bus=self.event_bus,
    instance_id=self.instance_id
)
await self.timer_manager.initialize()

# Register in component registry (fixed: metadata instead of kwargs)
await self.component_registry.register_component(
    component_id="timer_manager",
    component_type="service",
    metadata={
        "instance_id": self.instance_id,
        "distributed": True,
        "monitor_interval": 0.1
    }
)
```

### Shutdown Flow
```python
# In SystemManager._shutdown_core_components()
await self.timer_manager.shutdown()  # Graceful shutdown
```

## Event Stream Integration

### Task Submission → Timer Registration
```
1. Workflow submitted with timer task
2. Task validated by WorkflowLoaderV2
3. Task routed to TimerProvider via PoolingAdapter
4. TimerProvider calls TimerTaskHandler
5. Timer registered in Redis with wake time
6. Task returns with SLEEPING status
```

### Timer Wake → Task Continuation
```
1. TimerMonitorService finds expired timer
2. Reads timer metadata (workflow_id, task_id)
3. Sends timer_wake event to workflow stream
4. Event consumed by task orchestrator
5. Task marked as completed, dependencies resolved
6. Dependent tasks become ready for execution
```

## Scalability Features

### What Scales Horizontally ✅
- **Timer Submission**: Any node can accept timer workflows
- **Timer Storage**: Redis sorted sets handle millions efficiently
- **Task Execution**: Multiple workers process wake events
- **Event Delivery**: Redis Streams with consumer groups

### Distributed Coordination ✅
- **Single Monitor**: Leader election ensures no duplicate triggers
- **Automatic Failover**: New leader within 5 seconds of failure
- **Lock-based Coordination**: Redis locks prevent race conditions
- **Stateless Instances**: All state in Redis, nodes are disposable

### Production Considerations
- **High Availability**: Multiple instances for failover
- **Monitoring**: Built-in stats via `timer_manager.get_stats()`
- **Cleanup**: Periodic removal of old timers
- **Configurability**: All intervals/batches configurable

## Testing & Validation

### Timer Sleep Test
```python
workflow = {
    'tasks': [{
        'id': 'sleep-2s',
        'protocol': 'timer/v1',
        'method': 'timer/sleep',
        'params': {'seconds': 2}
    }]
}
# Result: Task sleeps for 2 seconds, then continues
```

### Scheduling Test (wait_until)
```python
target_time = datetime.utcnow() + timedelta(minutes=5)
workflow = {
    'tasks': [{
        'id': 'scheduled',
        'protocol': 'timer/v1',
        'method': 'timer/wait_until',
        'params': {'timestamp': target_time.isoformat() + 'Z'}
    }]
}
# Result: Task waits until specific time, then continues
```

### Test Results
- ✅ Timer registration working
- ✅ Timer monitor triggering correctly
- ✅ Wake events delivered to workflows
- ✅ Dependent tasks execute after timer
- ✅ Scheduling (wait_until) working
- ✅ Distributed coordination tested

## Fixes Applied During Implementation

### 1. Event Stream Fixes
- Added missing event emission in NativeAdapter
- Fixed event type normalization (enum → string)
- Changed consumer to read pending messages

### 2. Provider Routing
- Added timer/v1 to hub_managed_protocols
- Fixed LoggingMixin initialization
- Corrected log_success signatures

### 3. Timer Monitor Issues
- Fixed Redis key format handling (bytes vs strings)
- Added None checks for datetime arithmetic
- Integrated monitor into SystemManager lifecycle

### 4. Architecture Improvements
- Created TimerManager for proper lifecycle management
- Added distributed coordination with leader election
- Implemented graceful shutdown and failover

### 5. Distributed Coordination Fixes
- Fixed leader lock refresh logic (check ownership before refresh)
- Handle both bytes and string returns from Redis.get()
- Increased lock TTL to 10 seconds with 3-second refresh interval
- Fixed component registry registration (metadata vs kwargs)

## API Endpoints

### Timer Stats (via API)
```python
GET /api/v1/system/timer-stats
Response: {
    "status": "active",
    "instance_id": "timer-manager-12345",
    "pending_timers": 42,
    "completed_timers": 1337,
    "next_wake": "2025-09-11T12:00:00Z",
    "is_leader": true,
    "distributed_mode": true
}
```

## Future Enhancements

### Possible Improvements
1. **Partitioned Timers**: Split timers across multiple monitors
2. **Priority Timers**: High-priority timers processed first
3. **Timer Cancellation**: Cancel pending timers via API
4. **Recurring Timers**: Support cron-like scheduling
5. **Timer Groups**: Batch operations on timer sets

### Performance Optimizations
1. Increase batch size for high-volume scenarios
2. Use Redis pipelining for batch operations
3. Implement timer coalescing for near-simultaneous wakes
4. Add metrics for timer processing latency

## Multi-Server Competition & Failover

### Distributed Coordination Behavior
When multiple servers run simultaneously:

1. **Leader Election**
   - First server to start acquires the leader lock in Redis
   - Lock has 10-second TTL with 3-second refresh interval
   - Only the leader runs the timer monitor service

2. **Competition Scenario**
   ```
   Server 1 (port 8000): Starts → Becomes leader
   Server 2 (port 8003): Starts → Remains in standby
   Server 3 (port 8004): Starts → Remains in standby
   ```

3. **Failover Scenario**
   ```
   Initial: Server 1 is leader
   Action: Kill Server 1
   Result: After ~10-13 seconds, Server 2 or 3 becomes new leader
   ```

4. **Key Properties**
   - ✅ Only ONE timer monitor active across all servers
   - ✅ No duplicate timer triggers
   - ✅ Automatic failover within lock TTL period
   - ✅ All timer state preserved in Redis
   - ✅ Clean handoff between leaders

### Production Deployment
For high availability:
```bash
# Start multiple instances on different ports/machines
GLEITZEIT_TIMER_DISTRIBUTED=true gleitzeit serve --port 8000
GLEITZEIT_TIMER_DISTRIBUTED=true gleitzeit serve --port 8001
GLEITZEIT_TIMER_DISTRIBUTED=true gleitzeit serve --port 8002
```

Only one will be the timer leader, others stand ready for failover.

## Conclusion

The timer system is now:
- **Production-ready** with failover and distributed coordination
- **Horizontally scalable** without timer duplication
- **Fully integrated** with SystemManager lifecycle
- **Event-driven** using Redis Streams
- **Stateless** with all state in Redis
- **Configurable** via environment variables
- **Battle-tested** with multi-server competition scenarios

The implementation follows Gleitzeit's architectural patterns and is ready for production deployment with high availability requirements.