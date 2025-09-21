# Event System Integration Audit

## Current Architecture Analysis

After reviewing the codebase, here's what we have and what's needed:

## ✅ What Already Exists

### 1. **ScalableRedisAdapter Has Event Support**
```python
# In scalable_redis.py:
- enable_events: bool = True
- event_stream_key configuration
- Uses Redis XADD for events
- emit_task_event() and emit_workflow_event() methods exist
```

### 2. **Redis Streams Already Used**
```python
# Found multiple uses of xadd:
await self._execute("xadd", stream_key, event_data, id="*")
```

### 3. **Event Infrastructure Present**
- `GleitzeitEvent` model exists
- Event types defined (TaskStatus, WorkflowStatus)
- Event bus concept in persistence layer

## ❌ What's Missing for Provider Events

### 1. **Provider → Persistence Connection**
```python
# Current: Providers don't have access to persistence
class ProtocolProvider:
    def __init__(self, ...):
        # No persistence parameter!
        self.resource_manager = resource_manager
        self.hub = hub
```

**GAP**: Providers can't emit events because they don't have persistence access!

### 2. **Task Context Not Passed to Providers**
```python
# In TaskExecutor:
async def execute_task(self, task: Task):
    # Uses pooling_adapter, but doesn't pass context
    result = await self.pooling_adapter.execute(...)
    # No event context passed to provider!
```

**GAP**: Providers don't know workflow_id or task_id for events!

### 3. **No Event Listener Registration System**
```python
# Missing:
- No way to register event listeners at workflow start
- No storage of listener → task mappings
- No event pattern matching system
```

### 4. **No Event-Triggered Task Creation**
```python
# Missing:
- No mechanism to create tasks from events
- No way to add tasks to queue based on events
```

## 🔧 Required Changes

### 1. **Add Persistence to Provider Context**

```python
# Option A: Pass through pooling adapter
class PoolingAdapter:
    async def execute(self, protocol, method, params, context=None):
        # Add context with persistence
        provider_context = {
            "task_id": context.get("task_id"),
            "workflow_id": context.get("workflow_id"),
            "persistence": self.persistence  # NEW
        }
        
# Option B: Add to provider initialization
class ProtocolProvider:
    def __init__(self, ..., persistence=None):
        self.persistence = persistence
```

### 2. **Create Event Emission Helper**

```python
# In base provider:
class ProtocolProvider:
    async def emit(self, event_name: str, data: dict = None):
        if not self.persistence or not self.context:
            return
        
        # Use existing emit_task_event
        await self.persistence.emit_task_event(
            task_id=self.context["task_id"],
            workflow_id=self.context["workflow_id"],
            event_type=f"{self.protocol_id}.{event_name}",
            event_data=data
        )
```

### 3. **Event Listener Registration**

```python
# New method in ScalableRedisAdapter:
async def register_event_listener(
    self,
    workflow_id: str,
    event_pattern: str,
    task_template: dict
):
    """Store event listener in Redis"""
    key = f"{self.key_prefix}:listeners:{event_pattern}"
    await self.redis.hset(
        key,
        f"{workflow_id}:{task_template['id']}",
        json.dumps(task_template)
    )
```

### 4. **Event Processing Loop**

```python
# New component or extend existing:
class EventProcessor:
    async def process_events(self, workflow_id: str):
        """Read events and trigger tasks"""
        # Read from Redis Stream
        events = await self.redis.xread({
            f"events:workflow:{workflow_id}": "$"
        })
        
        for event in events:
            # Find matching listeners
            listeners = await self.find_listeners(event)
            
            # Create tasks
            for listener in listeners:
                await self.create_triggered_task(listener, event)
```

## 🚨 Critical Issues

### 1. **Stateless Challenge**
- Providers are stateless between calls
- Can't maintain event handlers in memory
- **Solution**: All event config must be in Redis

### 2. **Provider Pooling**
- Providers are pooled and reused
- Can't store workflow-specific state
- **Solution**: Pass context per execution

### 3. **No Task Queue Access**
- Providers can't directly add tasks to queue
- **Solution**: Use persistence layer as intermediary

## 📊 Feasibility Assessment

### What Works with Current Architecture:
✅ Redis Streams for events
✅ Event emission from persistence layer
✅ Basic event types and structures

### What Requires Significant Changes:
❌ Provider access to persistence (moderate change)
❌ Event listener registration system (new feature)
❌ Event-to-task creation (new feature)
❌ Pattern matching for events (new feature)

## 🎯 Minimal Implementation Path

### Phase 1: Provider Events (2-3 hours)
1. Add persistence to provider context
2. Add emit() method to base provider
3. Test with simple events

### Phase 2: Event Listeners (4-6 hours)
1. Create listener registration in Redis
2. Add event processor component
3. Wire into workflow execution

### Phase 3: Task Creation (2-3 hours)
1. Add task creation from events
2. Test end-to-end flow

## Conclusion

**The event system is partially there but needs significant wiring:**

1. **Infrastructure exists** (Redis Streams, basic events)
2. **Major gap**: Providers can't emit events (no persistence access)
3. **Missing entirely**: Event listener registration and task creation
4. **Complexity**: Medium - requires changes across multiple layers

**Recommendation**: 
- The simplified syntax (task chaining) is valuable enough to implement
- But event listeners need foundational work first (1-2 days)
- Consider implementing without events initially, add events in v2