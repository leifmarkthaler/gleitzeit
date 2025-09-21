# Redis Streams Event Bus Implementation

## Overview
Implemented Redis Streams as an alternative to Redis Pub/Sub for event-driven architecture in Gleitzeit, providing message durability, guaranteed delivery, and failure recovery.

## Key Components

### 1. StreamEventBus (`src/gleitzeit/events/stream_event_bus.py`)
Complete Redis Streams-based event bus implementation with:
- **Consumer Groups**: Distributed processing with multiple workers
- **Message Acknowledgment**: Ensures at-least-once delivery
- **Automatic Recovery**: Claims idle messages from failed consumers
- **Stream Management**: Automatic trimming to prevent unbounded growth

### 2. GleitzeitStreamEvent
Data class that ensures proper serialization for Redis Streams:
```python
@dataclass
class GleitzeitStreamEvent:
    event_type: str
    timestamp: str
    data: str  # JSON string
    source: str
    correlation_id: str
    severity: str
    metadata: str  # JSON string
```

### 3. StreamTransport (`src/gleitzeit/transport/stream_transport.py`)
Drop-in replacement for pub/sub transport:
- Maintains same interface for easy swapping
- Supports message acknowledgment
- Handles pending message reclaim

## Configuration

### Environment Variables
```bash
# Enable Redis Streams event bus
export GLEITZEIT_EVENT_BUS=streams

# Configure consumer group (default: gleitzeit-workers)
export GLEITZEIT_CONSUMER_GROUP=my_workers

# Set consumer ID (auto-generated if not set)
export GLEITZEIT_CONSUMER_ID=worker_001
```

### Starting the Server
```bash
# With Redis Streams
GLEITZEIT_EVENT_BUS=streams gleitzeit serve --port 8082

# With traditional Pub/Sub (default)
gleitzeit serve --port 8082
```

## Benefits Over Pub/Sub

| Feature | Pub/Sub | Streams |
|---------|---------|---------|
| Message Persistence | ❌ | ✅ |
| Guaranteed Delivery | ❌ | ✅ |
| Message History | ❌ | ✅ |
| Failure Recovery | ❌ | ✅ |
| Consumer Groups | ❌ | ✅ |
| Message Replay | ❌ | ✅ |

## Architecture Changes

### Event Flow with Streams
1. Event emitted → Serialized to GleitzeitStreamEvent
2. Added to Redis Stream with XADD
3. Consumer group reads with XREADGROUP
4. Event processed → ACK sent with XACK
5. Failed messages automatically reclaimed after idle timeout

### SystemManager Integration
Modified `SystemManager._create_event_bus()` to support:
- Auto-detection of Redis availability
- Environment-based bus selection
- Backward compatibility with existing PubSubEventBus

## Bug Fixes Included

### 1. Task Status Enum Serialization
**Problem**: Task status saved as `"TaskStatus.COMPLETED"` instead of `"completed"`
**Solution**: Use `task.status.value` for proper enum serialization

### 2. Missing Event Timestamp
**Problem**: GleitzeitEvent lacked timestamp field
**Solution**: Added optional timestamp field with automatic generation

### 3. Redis Streams None Values
**Problem**: Redis XADD doesn't accept None values
**Solution**: GleitzeitStreamEvent ensures all fields are strings

## Implementation Details

### Consumer Groups
- Automatic group creation on first use
- Multiple consumers can process events in parallel
- Failed consumers' messages are reclaimed after 60 seconds

### Message Acknowledgment
- Messages must be explicitly ACKed after processing
- Unacknowledged messages are retried
- Max retry limit prevents infinite loops

### Stream Trimming
- Automatic trimming to ~1000 messages per stream
- Prevents unbounded memory growth
- Configurable via `trim_stream()` method

## Testing

### Manual Test
```python
# test_stream_event_bus.py
- Tests event emission to streams
- Verifies consumer group processing
- Validates failure recovery
```

### Integration Test
```yaml
# test_workflow_streams.yaml
- Multi-task workflow
- Tests task dependencies
- Validates enum serialization fix
```

## Future Enhancements

1. **Dead Letter Queue**: Handle permanently failed messages
2. **Metrics Collection**: Track processing times and failure rates
3. **Dynamic Scaling**: Auto-scale consumers based on pending messages
4. **Stream Compaction**: Archive old messages to secondary storage

## Migration Guide

### From Pub/Sub to Streams
1. Set environment variable: `GLEITZEIT_EVENT_BUS=streams`
2. Restart server
3. No code changes required - same event interface

### Rollback
1. Remove environment variable or set: `GLEITZEIT_EVENT_BUS=pubsub`
2. Restart server
3. Returns to original pub/sub behavior

## Status
✅ **Production Ready** - Successfully integrated and tested with Gleitzeit v0.0.6