# ReconciliationManager with TimerManager Integration

## Overview

The ReconciliationManager has been refactored to use the distributed TimerManager for scheduling reconciliation runs, eliminating duplicate scheduling logic and creating a cleaner, more maintainable architecture.

## Architecture

### Before (Duplicate Scheduling)
```
ReconciliationManager
├── Leader Election (Redis locks)
├── Reconciliation Loop (asyncio.sleep) ← DUPLICATE
└── ReconciliationService (business logic)

TimerManager
├── Timer Scheduling (Redis sorted sets)
├── Timer Monitoring (distributed)
└── Wake Event Distribution
```

### After (Unified Timer System)
```
TimerManager (Centralized Scheduling)
├── Timer Scheduling (Redis sorted sets)
├── Timer Monitoring (distributed with leader election)
└── Wake Event Distribution
    └── Sends to: workflow:{workflow_id}:events

ReconciliationManager (Coordination Only)
├── Leader Election (Redis locks)
├── Timer Event Listener (Redis streams)
└── ReconciliationService (business logic)
```

## Implementation Details

### 1. Timer Creation

When ReconciliationManager becomes the leader, it schedules a reconciliation timer:

```python
# ReconciliationManager._schedule_next_reconciliation()
async def _schedule_next_reconciliation(self):
    # Create unique timer ID
    self._timer_id = f"reconciliation:{self.instance_id}:{uuid.uuid4().hex[:8]}"
    
    # Calculate wake time
    wake_at = time.time() + self.reconciliation_interval
    
    # Store timer in Redis sorted set (same as TimerTaskHandler)
    await self.redis_client.zadd("timers:pending", {self._timer_id: wake_at})
    
    # Store timer metadata as hash (compatible with TimerMonitorService)
    timer_data = {
        "timer_type": "reconciliation",
        "instance_id": self.instance_id,
        "workflow_id": f"system:reconciliation:{self.instance_id}",
        "task_id": "reconciliation_timer"
    }
    await self.redis_client.hset(f"timer:{self._timer_id}", mapping=timer_data)
```

### 2. Timer Monitoring

The TimerMonitorService (part of TimerManager) continuously monitors for expired timers:

```python
# TimerMonitorService._process_expired_timers()
expired = await self.redis.zrangebyscore("timers:pending", min=0, max=now)

for timer_id in expired:
    # Get timer metadata
    timer_data = await self.redis.hgetall(f"timer:{timer_id}")
    
    # Send wake event to workflow stream
    event_data = {
        "event": "timer_wake",
        "timer_id": timer_id,
        "task_id": task_id,
        "type": timer_type
    }
    await self.redis.xadd(f"workflow:{workflow_id}:events", event_data)
```

### 3. Event Listening

ReconciliationManager listens for timer wake events on its workflow stream:

```python
# ReconciliationManager._timer_event_listener()
async def _timer_event_listener(self):
    stream_key = f"workflow:system:reconciliation:{self.instance_id}:events"
    
    while self.is_running:
        events = await self.redis_client.xread({stream_key: "$"}, block=1000)
        
        for stream, messages in events:
            for msg_id, data in messages:
                if data.get("event") == "timer_wake":
                    if data.get("type") == "reconciliation":
                        await self._handle_timer_expiry()
```

### 4. Reconciliation Execution

When a timer expires, reconciliation runs and schedules the next timer:

```python
# ReconciliationManager._handle_timer_expiry()
async def _handle_timer_expiry(self):
    # Only run if still leader
    if self.role != ReconciliationRole.LEADER:
        return
    
    # Run reconciliation
    await self._run_reconciliation()
    
    # Schedule next run
    await self._schedule_next_reconciliation()
```

## Redis Data Structures

### Timers Sorted Set
```
Key: timers:pending
Format: ZSET
Members: timer_id -> wake_timestamp
Example: "reconciliation:instance_abc:1234" -> 1736592000.5
```

### Timer Metadata Hash
```
Key: timer:{timer_id}
Format: HASH
Fields:
  - timer_type: "reconciliation"
  - instance_id: "instance_abc"
  - workflow_id: "system:reconciliation:instance_abc"
  - task_id: "reconciliation_timer"
  - wake_at: "1736592000.5"
```

### Workflow Event Stream
```
Key: workflow:system:reconciliation:{instance_id}:events
Format: STREAM
Message: {
  "event": "timer_wake",
  "timer_id": "reconciliation:instance_abc:1234",
  "task_id": "reconciliation_timer",
  "type": "reconciliation",
  "timestamp": "1736592000.5"
}
```

## Configuration

### Environment Variables
- `GLEITZEIT_TIMER_DISTRIBUTED`: Enable distributed timer monitoring (default: true)
- `GLEITZEIT_TIMER_MONITOR_INTERVAL`: Timer check interval in seconds (default: 0.1)
- `GLEITZEIT_RECONCILIATION_INTERVAL`: Seconds between reconciliation runs (default: 60)

## Benefits

### 1. Unified Timer Management
- All scheduled tasks use the same timer system
- Consistent behavior across different components
- Single place to monitor and manage timers

### 2. Eliminated Code Duplication
- Removed `_reconciliation_loop` with `asyncio.sleep`
- No more duplicate scheduling implementations
- Reduced maintenance burden

### 3. Better Scalability
- Leverages distributed timer system with leader election
- Timer monitoring can scale independently
- Reconciliation can scale independently

### 4. Cleaner Architecture
- **TimerManager**: Handles all timer scheduling and monitoring
- **ReconciliationManager**: Handles leader election and coordination
- **ReconciliationService**: Contains business logic for reconciliation
- Clear separation of concerns

### 5. Improved Observability
- All timers visible in Redis sorted sets
- Timer history in completed set
- Event stream provides audit trail

## Testing

### Verify Timer Creation
```python
# Check pending timers
redis-cli ZRANGE timers:pending 0 -1 WITHSCORES

# Check timer metadata
redis-cli HGETALL timer:reconciliation:*
```

### Simulate Timer Expiry
```python
# Run test script
python test_reconciliation_timer.py
```

### Monitor Events
```python
# Watch reconciliation events
redis-cli XREAD BLOCK 0 STREAMS workflow:system:reconciliation:* $
```

## Migration Notes

### For Existing Deployments
1. The change is backward compatible
2. No data migration required
3. Simply restart servers with updated code
4. Reconciliation will automatically use timer system

### Key Changes from Previous Implementation
1. Removed `_reconciliation_task` background task
2. Removed `_reconciliation_loop()` method
3. Added `_timer_event_listener()` background task
4. Added `_schedule_next_reconciliation()` method
5. Modified `_handle_timer_expiry()` to schedule next timer

## Troubleshooting

### No Reconciliation Timers Created
- Check ReconciliationManager is leader: `redis-cli GET gleitzeit:reconciliation:leader_info`
- Verify TimerManager is running: Check for "TimerManager initialized" in logs
- Ensure Redis connection is available

### Reconciliation Not Running
- Check timer is in pending set: `redis-cli ZRANGE timers:pending 0 -1`
- Verify TimerMonitorService is leader: Look for "TimerManager {id} became leader" in logs
- Check event stream for wake events: `redis-cli XLEN workflow:system:reconciliation:*:events`

### Timer Wake Events Not Received
- Verify stream key format matches: `workflow:system:reconciliation:{instance_id}:events`
- Check ReconciliationManager listener is running: Look for "Starting timer event listener" in logs
- Ensure Redis streams are working: `redis-cli XINFO STREAM workflow:*`

## Future Enhancements

1. **Dynamic Interval Adjustment**: Allow changing reconciliation interval without restart
2. **Priority Timers**: Add priority levels for different timer types
3. **Timer Metrics**: Export timer statistics to monitoring systems
4. **Timer Batching**: Process multiple expired timers in single operation
5. **Timer Persistence**: Backup timer state for disaster recovery