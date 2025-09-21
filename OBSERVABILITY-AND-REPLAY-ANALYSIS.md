# Observability and Replay Analysis for Streaming Solutions

## Executive Summary
**YES** - The proposed streaming solutions will maintain and actually **enhance** both observability and replay capabilities through Redis Streams' built-in persistence and replay features.

## Current State vs Proposed State

### Current State (Broken)
- Events emitted to wrong stream key
- Events never consumed by StreamEventBus
- No observability of task/workflow state changes
- Replay manager has limited visibility

### Proposed State (Fixed)
- Events properly routed to type-specific streams
- Full event consumption and processing
- Complete observability of all state changes
- Enhanced replay capabilities with event sourcing

## Redis Streams Features for Observability & Replay

### 1. Built-in Persistence
```bash
# Redis Streams are persistent by default
# Events are stored on disk and survive restarts
XADD gleitzeit:events:stream:task.started * \
  task_id "task-123" \
  timestamp "2024-01-01T10:00:00" \
  status "EXECUTING"

# Message ID format: <timestamp>-<sequence>
# Example: 1704106800000-0
```

### 2. Time-Based Replay
```python
# Read all events from a specific time
async def replay_from_timestamp(event_type: str, start_time: str):
    stream_key = f"gleitzeit:events:stream:{event_type}"
    
    # XRANGE reads messages between time ranges
    messages = await redis.xrange(
        stream_key,
        min=start_time,  # e.g., "1704106800000-0"
        max="+"          # To end of stream
    )
    
    for msg_id, data in messages:
        # Process historical event
        await process_event(data)
```

### 3. Event Sourcing Capabilities
```python
# Reconstruct workflow state from events
async def reconstruct_workflow_state(workflow_id: str):
    """Rebuild workflow state from event stream."""
    
    state = {"tasks": {}, "status": "PENDING"}
    
    # Read all workflow events
    events = await redis.xrange(
        f"gleitzeit:events:stream:workflow.*",
        min="-",
        max="+"
    )
    
    for msg_id, event_data in events:
        if event_data["workflow_id"] != workflow_id:
            continue
            
        # Apply event to state
        if event_data["event_type"] == "workflow.started":
            state["status"] = "RUNNING"
            state["started_at"] = event_data["timestamp"]
        elif event_data["event_type"] == "task.completed":
            state["tasks"][event_data["task_id"]] = "COMPLETED"
        # ... etc
    
    return state
```

## Observability Benefits

### 1. Complete Audit Trail
```python
# Every state change is recorded
Task Created  → task.submitted   → Stream: task.submitted
Task Queued   → task.queued      → Stream: task.queued
Task Started  → task.started     → Stream: task.started
Task Complete → task.completed   → Stream: task.completed
```

### 2. Real-time Monitoring
```python
# Monitor specific task in real-time
async def monitor_task(task_id: str):
    """Stream all events for a specific task."""
    
    # Follow multiple streams
    streams = {
        "gleitzeit:events:stream:task.started": "$",
        "gleitzeit:events:stream:task.completed": "$",
        "gleitzeit:events:stream:task.failed": "$"
    }
    
    while True:
        messages = await redis.xread(streams, block=1000)
        
        for stream, entries in messages:
            for msg_id, data in entries:
                if data["task_id"] == task_id:
                    yield {"event": stream, "data": data, "id": msg_id}
```

### 3. Historical Analysis
```python
# Analyze task performance over time
async def analyze_task_performance(start_date: str, end_date: str):
    """Analyze task execution times from events."""
    
    started_events = await redis.xrange(
        "gleitzeit:events:stream:task.started",
        min=start_date,
        max=end_date
    )
    
    completed_events = await redis.xrange(
        "gleitzeit:events:stream:task.completed",
        min=start_date,
        max=end_date
    )
    
    # Calculate metrics
    task_durations = {}
    for task_id in started_tasks:
        if task_id in completed_tasks:
            duration = completed_time - started_time
            task_durations[task_id] = duration
    
    return {
        "avg_duration": statistics.mean(task_durations.values()),
        "p95_duration": statistics.quantiles(task_durations.values(), n=20)[18],
        "total_tasks": len(task_durations)
    }
```

## Replay Capabilities Enhanced

### 1. Point-in-Time Recovery
```python
class EnhancedReplayManager(ReplayManager):
    """Replay manager with event stream support."""
    
    async def replay_to_point_in_time(self, workflow_id: str, timestamp: str):
        """Replay workflow up to specific timestamp."""
        
        # Get all events up to timestamp
        events = []
        for event_type in ["task.*", "workflow.*"]:
            stream_events = await redis.xrange(
                f"gleitzeit:events:stream:{event_type}",
                min="-",
                max=timestamp
            )
            events.extend(stream_events)
        
        # Sort by timestamp
        events.sort(key=lambda x: x[0])  # msg_id is timestamp-based
        
        # Replay events in order
        for msg_id, event_data in events:
            if event_data["workflow_id"] == workflow_id:
                await self._apply_event(event_data)
```

### 2. Selective Event Replay
```python
async def replay_failed_tasks_only(workflow_id: str):
    """Replay only failed tasks from event stream."""
    
    # Get failed task events
    failed_events = await redis.xrange(
        "gleitzeit:events:stream:task.failed",
        min="-",
        max="+"
    )
    
    tasks_to_replay = []
    for msg_id, data in failed_events:
        if data["workflow_id"] == workflow_id:
            tasks_to_replay.append(data["task_id"])
    
    # Re-execute only failed tasks
    for task_id in tasks_to_replay:
        await retry_task(task_id)
```

### 3. Event Stream Debugging
```python
async def debug_workflow_execution(workflow_id: str):
    """Step through workflow execution via events."""
    
    # Get all events for workflow
    all_events = await get_workflow_events(workflow_id)
    
    for event in all_events:
        print(f"Event: {event['event_type']} at {event['timestamp']}")
        print(f"Data: {event['data']}")
        
        # Allow stepping through
        input("Press Enter to continue...")
        
        # Apply event to see state change
        await apply_event(event)
        print(f"New state: {await get_workflow_state(workflow_id)}")
```

## Stream Retention and Management

### 1. Configurable Retention
```python
# Keep events for specific duration
async def configure_stream_retention():
    """Set retention policies per event type."""
    
    retention_policies = {
        "task.started": 7 * 24 * 3600 * 1000,     # 7 days
        "task.completed": 30 * 24 * 3600 * 1000,  # 30 days
        "task.failed": 90 * 24 * 3600 * 1000,     # 90 days
        "workflow.completed": 365 * 24 * 3600 * 1000  # 1 year
    }
    
    for event_type, retention_ms in retention_policies.items():
        stream_key = f"gleitzeit:events:stream:{event_type}"
        
        # Trim to time-based retention
        await redis.xtrim(
            stream_key,
            minid=f"{int(time.time() * 1000) - retention_ms}-0"
        )
```

### 2. Event Archival
```python
async def archive_old_events():
    """Archive old events to long-term storage."""
    
    cutoff_time = datetime.now() - timedelta(days=30)
    cutoff_ms = int(cutoff_time.timestamp() * 1000)
    
    for event_type in EVENT_TYPES:
        stream_key = f"gleitzeit:events:stream:{event_type}"
        
        # Read old events
        old_events = await redis.xrange(
            stream_key,
            min="-",
            max=f"{cutoff_ms}-0"
        )
        
        # Save to archive (S3, etc)
        await save_to_archive(event_type, old_events)
        
        # Remove from Redis
        for msg_id, _ in old_events:
            await redis.xdel(stream_key, msg_id)
```

## Comparison: Single Stream vs Type-Specific Streams

### Observability

| Aspect | Single Stream | Type-Specific Streams |
|--------|--------------|----------------------|
| Event Discovery | Scan entire stream | Direct stream access |
| Filtering Performance | O(n) for all events | O(n) for type only |
| Monitoring Complexity | Simple | Per-type monitoring |
| Storage Efficiency | Better | More overhead |
| Query Speed | Slower | Faster |

### Replay Capabilities

| Feature | Single Stream | Type-Specific Streams |
|---------|--------------|----------------------|
| Full Replay | Easy - single stream | Merge multiple streams |
| Selective Replay | Requires filtering | Direct access |
| Time-based Replay | Single XRANGE | Multiple XRANGE |
| Event Ordering | Natural | Requires merging |
| Parallel Processing | Limited | Excellent |

## Implementation Recommendations

### 1. Add Stream Metadata
```python
# Enhanced event structure for better observability
event_data = {
    "event_type": "task.completed",
    "timestamp": datetime.utcnow().isoformat(),
    "task_id": task.id,
    "workflow_id": task.workflow_id,
    "correlation_id": workflow.correlation_id,
    "causation_id": previous_event_id,  # Link events
    "version": "1.0",
    "source": "persistence",
    "actor": user_id,
    "metadata": {
        "duration_ms": execution_time,
        "retry_count": task.retry_count,
        "provider": task.provider
    }
}
```

### 2. Event Replay Service
```python
class EventReplayService:
    """Service for event-based replay operations."""
    
    async def create_replay_checkpoint(self, workflow_id: str):
        """Create checkpoint for replay."""
        
        # Get current position in all streams
        checkpoint = {}
        for event_type in EVENT_TYPES:
            stream_key = f"gleitzeit:events:stream:{event_type}"
            info = await redis.xinfo_stream(stream_key)
            checkpoint[event_type] = info["last-generated-id"]
        
        # Save checkpoint
        await redis.hset(
            f"replay:checkpoints:{workflow_id}",
            mapping=checkpoint
        )
    
    async def replay_from_checkpoint(self, workflow_id: str, checkpoint_id: str):
        """Replay from saved checkpoint."""
        
        checkpoint = await redis.hgetall(f"replay:checkpoints:{checkpoint_id}")
        
        for event_type, last_id in checkpoint.items():
            stream_key = f"gleitzeit:events:stream:{event_type}"
            
            # Read events after checkpoint
            events = await redis.xrange(
                stream_key,
                min=f"({last_id}",  # Exclusive
                max="+"
            )
            
            # Process events
            for msg_id, data in events:
                if data["workflow_id"] == workflow_id:
                    await self.process_replay_event(data)
```

## Conclusion

The proposed streaming solutions **significantly enhance** both observability and replay capabilities:

### Observability Improvements
✅ **Complete audit trail** - Every state change recorded
✅ **Real-time monitoring** - Stream events as they happen
✅ **Historical analysis** - Query past events by time
✅ **Performance metrics** - Calculate from event timestamps
✅ **Debugging support** - Step through execution history

### Replay Enhancements
✅ **Event sourcing** - Reconstruct state from events
✅ **Point-in-time recovery** - Replay to specific timestamp
✅ **Selective replay** - Re-run only specific events
✅ **Checkpoint/restore** - Save and restore positions
✅ **Parallel replay** - Process event types independently

### Key Benefits of Fix
1. **No data loss** - Redis Streams persist events to disk
2. **Time-travel debugging** - Navigate through execution history
3. **Audit compliance** - Complete record of all operations
4. **Performance analysis** - Detailed timing from events
5. **Failure recovery** - Replay from last known good state

The move to type-specific streams not only maintains existing capabilities but provides a **massive upgrade** in observability and replay functionality through Redis Streams' native features.