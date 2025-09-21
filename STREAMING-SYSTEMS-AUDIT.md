# Gleitzeit Streaming Systems Audit

## Executive Summary
Gleitzeit contains **FOUR separate streaming systems** that are not properly aligned, leading to potential confusion, maintenance issues, and performance overhead.

## Identified Streaming Systems

### 1. Redis Streams Event Bus (`stream_event_bus.py`)
- **Purpose**: Durable event delivery with consumer groups
- **Location**: `/src/gleitzeit/events/stream_event_bus.py`
- **Key Features**:
  - Message persistence and durability
  - Consumer groups for distributed processing
  - Automatic failure recovery with ACK mechanism
  - Message replay capability
  - Idle message claiming for stuck messages
- **Status**: Active, enabled by default via config

### 2. Redis Pub/Sub Event Bus (`pubsub_event_bus.py`)
- **Purpose**: Fire-and-forget event broadcasting
- **Location**: `/src/gleitzeit/events/pubsub_event_bus.py`
- **Key Features**:
  - Real-time message broadcasting
  - Pattern subscriptions with wildcards
  - No persistence (messages lost if no subscribers)
  - Simple pub/sub model
- **Status**: Still referenced in code but superseded by Streams

### 3. WebSocket Streaming (`websocket.py`)
- **Purpose**: Real-time UI updates and log streaming
- **Location**: `/src/gleitzeit/ui/api/routes/websocket.py`
- **Key Features**:
  - Real-time browser communication
  - Channel-based subscriptions
  - Connection management
  - Used for logs, events, workflow updates
- **Status**: Active, used by UI components

### 4. Stream Transport Adapter (`stream_transport.py`)
- **Purpose**: Drop-in replacement for Pub/Sub with Streams
- **Location**: `/src/gleitzeit/transport/stream_transport.py`
- **Key Features**:
  - Minimal Redis Streams wrapper
  - Maintains pub/sub interface
  - Adds persistence and ACK
  - Consumer group support
- **Status**: Exists but unclear integration

## Alignment Issues

### 1. **Event Bus Confusion**
- System Manager creates event bus based on `GLEITZEIT_STREAM_MODE`
- Two implementations (`StreamEventBus` vs `PubSubEventBus`) with different guarantees
- No clear migration path or deprecation notice
- Code still references both implementations

### 2. **Configuration Inconsistency**
```python
# In config.py
"stream_mode": os.getenv("GLEITZEIT_STREAM_MODE", "enabled")

# In system_manager.py
if config.get("stream_mode", True):
    # Uses StreamEventBus
else:
    # Uses PubSubEventBus (StatelessEventBus)
```
- Default changed to enabled, but old code paths remain
- No validation that all components use same transport

### 3. **WebSocket Isolation**
- WebSocket system operates independently
- No integration with Redis Streams/Pub-Sub events
- Separate channel management and subscription logic
- Could benefit from unified event stream

### 4. **Transport Layer Redundancy**
- `StreamTransport` class duplicates `StreamEventBus` functionality
- Unclear when to use transport vs event bus
- Both provide similar consumer group features

## Impact Analysis

### Performance Impact
- **Memory**: Multiple event systems consume more memory
- **CPU**: Redundant message processing across systems
- **Network**: Duplicate Redis connections and subscriptions
- **Latency**: Event propagation delays between systems

### Maintenance Impact
- **Complexity**: Developers must understand 4 different streaming models
- **Bugs**: Inconsistent behavior between streaming systems
- **Testing**: Need to test all streaming pathways
- **Debugging**: Hard to trace events across systems

### Reliability Impact
- **Message Loss**: Pub/Sub messages lost during transitions
- **Ordering**: No guarantee of consistent event ordering across systems
- **Delivery**: Mixed guarantees (at-most-once vs at-least-once)

## Recommended Actions

### Short-term (Immediate)
1. **Deprecate Pub/Sub Event Bus**
   - Mark `PubSubEventBus` as deprecated
   - Add migration warnings in logs
   - Document migration path

2. **Unify Configuration**
   - Single config flag for all streaming
   - Validate consistency at startup
   - Clear defaults and documentation

### Medium-term (1-2 weeks)
1. **Consolidate Event Buses**
   - Remove `StreamTransport` or merge with `StreamEventBus`
   - Migrate all code to single event bus implementation
   - Ensure backward compatibility during transition

2. **WebSocket Integration**
   - Connect WebSocket to Redis Streams
   - Use consumer groups for WebSocket scaling
   - Unified event format across systems

### Long-term (1 month)
1. **Single Streaming Architecture**
   - One event bus for all internal events
   - WebSocket as presentation layer only
   - Clear separation of concerns
   - Comprehensive documentation

2. **Performance Optimization**
   - Single Redis connection pool
   - Efficient consumer group management
   - Stream trimming and retention policies

## Code Examples of Misalignment

### Example 1: Event Bus Creation
```python
# system_manager.py - Line 1134
async def _create_event_bus(self):
    if config.get("stream_mode", True):
        # Creates StreamEventBus
        from gleitzeit.events.stream_event_bus import StreamEventBus
        event_bus = StreamEventBus(redis_client, ...)
    else:
        # Creates StatelessEventBus (wraps PubSub)
        from gleitzeit.events.stateless_event_bus import StatelessEventBus
        event_bus = StatelessEventBus(persistence=self.persistence, ...)
```

### Example 2: Client Streaming Mixin
```python
# streaming.py - WebSocket only, no Redis Streams integration
async def stream_events(self, filter=None):
    if not hasattr(self._adapter, 'stream_events'):
        # Falls back to polling instead of Redis Streams
        while True:
            events = await self._adapter.get_event_stream(filter, follow=True)
            ...
```

### Example 3: Duplicate Transport
```python
# stream_transport.py - Duplicates StreamEventBus functionality
class StreamTransport:
    async def publish(self, channel: str, message: Dict[str, Any]):
        # Same as StreamEventBus.emit()
        stream_key = self._get_stream_key(channel)
        data = {"data": json.dumps(message)}
        message_id = await self.redis.xadd(stream_key, data)
```

## Conclusion

Gleitzeit's multiple streaming systems create unnecessary complexity and potential reliability issues. The system would benefit from:

1. **Single unified event streaming system** based on Redis Streams
2. **WebSocket as pure presentation layer** consuming from Redis Streams
3. **Clear deprecation** of legacy Pub/Sub code
4. **Consistent configuration** across all components

This consolidation would improve performance, reliability, and maintainability while reducing the cognitive load on developers.