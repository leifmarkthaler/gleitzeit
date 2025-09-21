# Streaming Event System Integration Audit

## Executive Summary
**STATUS: ⚠️ PARTIAL INTEGRATION - Key Mismatch Between Layers**

The Gleitzeit streaming event system has a fundamental disconnect:
- **ScalableRedisAdapter** emits all events to a single stream: `{prefix}:events:stream`
- **StreamEventBus** expects per-event-type streams: `gleitzeit:events:stream:{event_type}`
- This mismatch means events from persistence layer are NOT consumed by StreamEventBus

## Architecture Overview

### Component Layers
```
┌─────────────────────────────────────────┐
│     ScalableRedisAdapter (Persistence)  │
│     Emits to: prefix:events:stream      │
└────────────────────┬────────────────────┘
                     │
                     ↓ (workflow.saved only)
┌─────────────────────────────────────────┐
│        Redis Streams (Storage)          │
│   Single stream vs Multiple streams     │
└────────────────────┬────────────────────┘
                     │
                     ↓ ❌ Mismatch!
┌─────────────────────────────────────────┐
│      StreamEventBus (Consumer)          │
│  Reads from: gleitzeit:events:stream:*  │
└─────────────────────────────────────────┘
```

## Key Findings

### 1. Stream Key Mismatch

#### ScalableRedisAdapter Configuration
```python
# In scalable_redis.py line 164
self.event_stream_key = event_stream_key or f"{key_prefix}:events:stream"
# Example: "gleitzeit:events:stream" (single stream for ALL events)
```

#### StreamEventBus Configuration
```python
# In stream_event_bus.py line 418-419
def _get_stream_key(self, event_type: str) -> str:
    return f"gleitzeit:events:stream:{event_type}"
# Example: "gleitzeit:events:stream:task.started" (stream PER event type)
```

### 2. Event Emission Analysis

#### Current State in ScalableRedisAdapter
- **Total Events Emitted**: 1 (workflow.saved)
- **Stream Used**: Single stream for all events
- **Method**: `_emit_workflow_event()`

```python
# Line 499 in scalable_redis.py
await self._emit_workflow_event("workflow.saved", workflow)

# Line 673-677
await self._execute(
    "xadd",
    self.event_stream_key,  # Single stream key!
    event_data,
    id="*"
)
```

#### Expected by StreamEventBus
- **Expects**: Separate stream per event type
- **Pattern**: `gleitzeit:events:stream:{event_type}`
- **Consumer Groups**: Created per stream/event type

```python
# Line 255-257 in stream_event_bus.py
for event_type in self._handlers.keys():
    stream_key = self._get_stream_key(event_type)
    streams[stream_key] = ">"  # Read from type-specific stream
```

### 3. Integration Points

#### System Manager Integration
```python
# system_manager.py line 1097-1109
from ..events.stream_event_bus import StreamEventBus

event_bus = StreamEventBus(
    self.persistence.redis,  # Uses same Redis client
    event_store=event_store,
    consumer_group=consumer_group,
    consumer_id=consumer_id
)
```

System Manager correctly creates StreamEventBus but the bus won't receive events from persistence due to key mismatch.

### 4. Event Flow Breakdown

#### Working Flow (Other Components)
1. Task Orchestrator emits to correct stream keys
2. StreamEventBus consumes from type-specific streams
3. Handlers process events successfully

#### Broken Flow (Persistence Layer)
1. ScalableRedisAdapter emits to single stream
2. StreamEventBus looks for type-specific streams
3. Events are never consumed ❌

## Impact Analysis

### Critical Issues
1. **Lost Events**: All persistence events go to wrong stream
2. **No Task Tracking**: Task lifecycle events never reach handlers
3. **No Workflow Updates**: Workflow state changes not propagated
4. **Broken Retry Logic**: Retry manager won't see task failures
5. **Missing Metrics**: Can't track performance or SLIs

### Components Affected
- **Workflow Manager**: Won't see task completions from persistence
- **Task Orchestrator**: Won't see task state changes
- **Retry Manager**: Won't trigger retries on failures
- **Monitoring**: No visibility into persistence operations
- **UI/WebSocket**: Real-time updates broken

## Root Cause Analysis

The issue stems from two different design philosophies:

1. **ScalableRedisAdapter**: Designed for simplicity
   - Single event stream for all events
   - Easier to manage and configure
   - Less Redis keys to track

2. **StreamEventBus**: Designed for scalability
   - Separate streams per event type
   - Allows selective consumption
   - Better parallelization and filtering
   - Independent consumer groups per type

## Recommended Solutions

### Option 1: Fix ScalableRedisAdapter (Recommended)
**Modify persistence to emit to type-specific streams**

```python
async def _emit_event(self, event_type: str, data: dict):
    """Emit event to type-specific Redis Stream."""
    if not self.enable_events:
        return
    
    # Use same pattern as StreamEventBus
    stream_key = f"gleitzeit:events:stream:{event_type}"
    
    event_data = {
        "event_type": event_type,
        "timestamp": datetime.utcnow().isoformat(),
        **data
    }
    
    await self._execute(
        "xadd",
        stream_key,  # Type-specific stream!
        event_data,
        id="*"
    )
```

### Option 2: Add Stream Router
**Create middleware to route from single stream to multiple**

```python
class StreamRouter:
    """Routes events from single stream to type-specific streams."""
    
    async def route_events(self):
        while True:
            # Read from single stream
            events = await redis.xread({self.source_stream: ">"})
            
            for event in events:
                # Route to type-specific stream
                event_type = event["event_type"]
                target_stream = f"gleitzeit:events:stream:{event_type}"
                await redis.xadd(target_stream, event)
```

### Option 3: Modify StreamEventBus
**Allow reading from single stream (loses benefits)**

Not recommended as it removes per-type scalability.

## Implementation Plan

### Phase 1: Fix Event Emission (2 days)
1. Update `_emit_workflow_event()` to use type-specific streams
2. Add `_emit_task_event()` method
3. Emit proper events on all state changes
4. Test end-to-end event flow

### Phase 2: Add Missing Events (3 days)
1. Task lifecycle events (submitted, started, completed, failed)
2. Workflow state events (validated, paused, resumed)
3. Queue events (enqueued, dequeued)
4. System events (health, metrics)

### Phase 3: Verify Integration (2 days)
1. Test StreamEventBus consumption
2. Verify handler invocation
3. Check consumer group processing
4. Validate acknowledgments

## Testing Requirements

### Unit Tests
```python
async def test_event_stream_keys():
    """Verify events go to correct streams."""
    adapter = ScalableRedisAdapter()
    
    # Save task
    task = Task(id="test-1", status=TaskStatus.PENDING)
    await adapter.save_task(task)
    
    # Check stream key
    stream_key = "gleitzeit:events:stream:task.submitted"
    messages = await redis.xread({stream_key: "0"})
    assert len(messages) > 0
    assert messages[0]["task_id"] == "test-1"
```

### Integration Tests
```python
async def test_persistence_to_eventbus_flow():
    """Test full flow from persistence to event bus."""
    
    # Track handler calls
    handler_called = False
    
    async def handler(event):
        nonlocal handler_called
        handler_called = True
    
    # Register handler
    event_bus.register(EventType.TASK_COMPLETED, handler)
    
    # Update task to completed
    task.status = TaskStatus.COMPLETED
    await adapter.save_task(task)
    
    # Wait for processing
    await asyncio.sleep(1)
    
    # Verify handler was called
    assert handler_called
```

## Migration Strategy

### Step 1: Parallel Emission (Safe)
```python
# Emit to both old and new streams temporarily
await self._execute("xadd", self.event_stream_key, event_data)  # Old
await self._execute("xadd", type_specific_key, event_data)      # New
```

### Step 2: Update Consumers
- Deploy StreamEventBus consumers
- Verify they're processing events
- Monitor for issues

### Step 3: Remove Old Stream
- Stop emitting to old stream
- Clean up old stream data
- Update documentation

## Monitoring & Observability

### Key Metrics to Track
1. **Stream Lag**: Messages pending per stream
2. **Consumer Group Health**: Active consumers per group
3. **Event Processing Rate**: Events/second per type
4. **Acknowledgment Rate**: ACKs/second
5. **Failed Message Count**: Retries and dead letters

### Redis Commands for Monitoring
```bash
# Check stream info
XINFO STREAM gleitzeit:events:stream:task.started

# Check consumer group info
XINFO GROUPS gleitzeit:events:stream:task.started

# Check pending messages
XPENDING gleitzeit:events:stream:task.started gleitzeit-workers

# Read stream contents
XRANGE gleitzeit:events:stream:task.started - +
```

## Performance Considerations

### Current (Single Stream)
- **Pros**: Simple, single point of management
- **Cons**: All consumers process all events, no parallelization

### Proposed (Per-Type Streams)
- **Pros**: 
  - Parallel processing per event type
  - Selective consumption
  - Better scalability
  - Independent trimming policies
- **Cons**:
  - More Redis keys
  - More complex monitoring

### Benchmarks Needed
1. Event emission overhead (single vs multiple streams)
2. Consumer processing rate
3. Redis memory usage
4. Network traffic patterns

## Conclusion

The streaming event system has solid infrastructure but a critical integration flaw:

**The Problem**: ScalableRedisAdapter and StreamEventBus use incompatible stream key patterns, preventing event flow from persistence to consumers.

**The Solution**: Modify ScalableRedisAdapter to emit events to type-specific streams matching StreamEventBus expectations.

**The Impact**: Without this fix, the system loses all persistence-layer observability, breaking monitoring, retries, and real-time updates.

**Priority**: HIGH - This blocks the entire event-driven architecture from functioning correctly.

## Immediate Actions Required

1. **Fix stream key pattern** in ScalableRedisAdapter
2. **Add missing event emissions** for task/workflow state changes
3. **Test end-to-end flow** from persistence to handlers
4. **Deploy monitoring** to track stream health
5. **Document the pattern** for future development

Without these fixes, Gleitzeit operates with severely limited observability, making production operations risky and debugging nearly impossible.