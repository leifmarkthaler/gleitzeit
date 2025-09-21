# Event System Architecture Audit

## Executive Summary

**Status: ⚠️ PARTIALLY STATELESS - NEEDS IMPROVEMENTS**

The Gleitzeit event system is **mostly stateless** but has several **stateful components** that violate pure stateless design:

1. **In-memory handler storage** - Handlers stored in memory, lost on restart
2. **Error history tracking** - Errors kept in memory arrays
3. **Subscription metadata** - Call counts and metrics stored in memory
4. **No distributed handler registry** - Can't share handlers across instances

## 1. Current Architecture

### A. Core Event Bus (`/events/base.py`)
**Status: ❌ STATEFUL**

```python
class EventBus:
    def __init__(self):
        self._handlers: Dict[str, List[EventHandler]] = {}  # IN-MEMORY STATE!
        self.handler_errors: List[HandlerError] = []        # IN-MEMORY STATE!
```

**Issues:**
- Handlers stored in `_handlers` dictionary (in-memory)
- Error history in `handler_errors` list (in-memory)
- Lost on restart/crash
- Can't scale horizontally

### B. Event Persistence (`/events/store.py`)
**Status: ✅ STATELESS**

```python
class EventStore:
    def __init__(self, persistence):
        self.persistence = persistence  # Delegates to backend
```

**Good:**
- Properly delegates to persistence backend
- No internal state
- Works with Redis or InMemory adapters

### C. Client Event Bus (`/client/events/client_event_bus.py`)
**Status: ❌ HIGHLY STATEFUL**

```python
class ClientEventBus:
    def __init__(self):
        self._handlers: Dict[str, List[EventHandler]] = {}
        self._subscriptions: Dict[str, EventSubscription] = {}
        self._metrics: Dict[str, EventMetrics] = {}
        # ... lots of in-memory state
```

**Issues:**
- Subscription tracking in memory
- Metrics collection in memory
- Handler registration in memory
- One-time handler tracking

## 2. Persistence Backend Support

### A. InMemory Backend (`UnifiedInMemoryAdapter`)
**Status: ⚠️ STATEFUL BY DESIGN**

```python
# Uses deques with maxlen for automatic trimming
self.events_global = deque(maxlen=10000)
self.events_by_workflow = {}
self.events_by_task = {}
```

**Notes:**
- Stateful but that's expected for in-memory
- Has event support with `save_event()` and `get_events()`
- Auto-trims old events with deque maxlen

### B. Redis Backend (`UnifiedRedisEventsAdapter`)
**Status: ✅ STATELESS**

```python
async def emit_event(self, event):
    # Publishes to Redis pub/sub
    await self.redis.publish(channel, json.dumps(event_data))
```

**Good:**
- Uses Redis pub/sub for events
- No local state storage
- Properly distributed

## 3. State Storage Analysis

### What's Stored In-Memory (BAD):

1. **Handler Registrations**
   - Location: `EventBus._handlers`
   - Impact: Handlers lost on restart
   - Fix: Store in Redis/persistence

2. **Error History**
   - Location: `EventBus.handler_errors`
   - Impact: Debugging info lost
   - Fix: Persist to backend

3. **Subscription Metadata**
   - Location: `ClientEventBus._subscriptions`
   - Impact: Can't resume subscriptions
   - Fix: Store in Redis

4. **Handler Metrics**
   - Location: `EventHandler.call_count`, `error_count`
   - Impact: Metrics lost on restart
   - Fix: Use Redis counters

### What's Properly Persisted (GOOD):

1. **Events** - Saved to persistence backend
2. **Task Results** - Stored in persistence
3. **Workflow State** - Persisted properly

## 4. Problems with Current Design

### A. Cannot Scale Horizontally
- Handlers registered on instance A won't exist on instance B
- No shared handler registry
- Each instance has isolated event bus

### B. Lost State on Restart
- All handler registrations lost
- Error history gone
- Metrics reset to zero
- One-time handlers forgotten

### C. No Handler Persistence
```python
# Current problematic code:
self._handlers[event_type].append(handler)  # Only in memory!
```

### D. Stateful Subscription Tracking
```python
@dataclass
class EventSubscription:
    call_count: int = 0  # Stateful!
    last_called: Optional[datetime] = None  # Stateful!
    error_count: int = 0  # Stateful!
```

## 5. Required Fixes for Stateless Design

### Priority 1: Handler Registry in Redis
```python
class StatelessEventBus:
    async def register(self, event_type: str, handler_id: str):
        # Store in Redis instead of memory
        await self.redis.sadd(f"handlers:{event_type}", handler_id)
        
    async def get_handlers(self, event_type: str):
        # Retrieve from Redis
        handler_ids = await self.redis.smembers(f"handlers:{event_type}")
        return self._load_handlers(handler_ids)
```

### Priority 2: Distributed Error Tracking
```python
async def track_error(self, handler_id: str, error: Exception):
    # Store in Redis with TTL
    error_data = {
        'handler_id': handler_id,
        'error': str(error),
        'timestamp': datetime.utcnow().isoformat()
    }
    await self.redis.lpush("event:errors", json.dumps(error_data))
    await self.redis.ltrim("event:errors", 0, 999)  # Keep last 1000
```

### Priority 3: Stateless Metrics
```python
async def increment_handler_metrics(self, handler_id: str):
    # Use Redis counters
    await self.redis.hincrby(f"metrics:{handler_id}", "call_count", 1)
    await self.redis.hset(f"metrics:{handler_id}", "last_called", datetime.utcnow().isoformat())
```

### Priority 4: Persistent Subscriptions
```python
async def subscribe(self, event_type: str, handler_config: dict):
    # Store subscription in Redis
    sub_id = str(uuid.uuid4())
    await self.redis.hset(
        f"subscription:{sub_id}",
        mapping={
            'event_type': event_type,
            'handler_class': handler_config['class'],
            'priority': handler_config['priority'],
            'filter': handler_config.get('filter', ''),
            'once': handler_config.get('once', False)
        }
    )
```

## 6. Event Flow Issues

### Current Flow (Problematic):
1. Event emitted → In-memory handlers called
2. Handler fails → Error stored in memory
3. System restarts → All state lost

### Desired Flow (Stateless):
1. Event emitted → Redis pub/sub
2. Workers pull handler configs from Redis
3. Handler fails → Error persisted to Redis
4. System restarts → State preserved

## 7. Recommendations

### Immediate Actions
1. **Move handler registry to Redis** - Critical for scaling
2. **Persist error history** - Needed for debugging
3. **Store metrics in Redis** - Use Redis counters
4. **Make subscriptions persistent** - Store in backend

### Architecture Changes
1. **Separate handler storage from execution**
   - Store handler configs in Redis
   - Load and execute dynamically

2. **Use Redis pub/sub for all events**
   - Don't store handlers locally
   - Subscribe to Redis channels

3. **Implement handler workers**
   - Pull events from Redis
   - Load handler configs
   - Execute and track metrics

### Code Example - Stateless Event Bus
```python
class StatelessEventBus:
    def __init__(self, redis_client):
        self.redis = redis_client
        # NO local state storage!
        
    async def register_handler(self, event_type: str, handler_config: dict):
        """Register handler in Redis."""
        handler_id = f"handler:{uuid.uuid4()}"
        await self.redis.hset(handler_id, mapping=handler_config)
        await self.redis.sadd(f"handlers:{event_type}", handler_id)
        
    async def emit(self, event: GleitzeitEvent):
        """Emit event via Redis pub/sub."""
        await self.redis.publish(
            f"events:{event.event_type}",
            event.to_json()
        )
        
    async def process_events(self):
        """Worker to process events from Redis."""
        pubsub = self.redis.pubsub()
        await pubsub.psubscribe("events:*")
        
        async for message in pubsub.listen():
            if message['type'] == 'pmessage':
                event_type = message['channel'].decode().split(':')[1]
                await self._execute_handlers(event_type, message['data'])
```

## 8. Testing Requirements

### What to Test:
1. Handler persistence across restarts
2. Distributed handler execution
3. Error tracking persistence
4. Metrics aggregation from Redis
5. Subscription resumption

### Test Scenario:
```python
# 1. Register handlers
await event_bus.register("TASK_COMPLETED", handler1)

# 2. Emit event
await event_bus.emit(task_completed_event)

# 3. Simulate restart
event_bus = StatelessEventBus(redis)

# 4. Verify handler still registered
handlers = await event_bus.get_handlers("TASK_COMPLETED")
assert handler1 in handlers  # Should still exist!
```

## 9. Migration Path

### Phase 1: Add Redis Storage (1 day)
- Add Redis handler storage alongside in-memory
- Dual-write to both systems
- Read from Redis with memory fallback

### Phase 2: Remove Memory Storage (1 day)
- Remove in-memory handler storage
- Use only Redis for handlers
- Update all registration code

### Phase 3: Distributed Processing (2 days)
- Implement event workers
- Use Redis pub/sub exclusively
- Remove local event processing

## 10. Conclusion

The event system is **NOT fully stateless** and needs significant refactoring:

**Current State:**
- ❌ Handlers stored in memory
- ❌ Metrics tracked locally
- ❌ Errors kept in memory arrays
- ❌ Cannot scale horizontally
- ✅ Events properly persisted
- ✅ Redis backend available

**Required Changes:**
1. Move ALL handler storage to Redis
2. Use Redis for metrics and errors
3. Implement stateless event workers
4. Remove all in-memory state

**Effort Estimate:** 3-4 days for full stateless implementation

**Risk:** HIGH - Current system will lose all event handlers on restart