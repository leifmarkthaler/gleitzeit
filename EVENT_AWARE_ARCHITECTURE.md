# Event-Aware Architecture Documentation

## Overview

Gleitzeit now supports both centralized and distributed event architectures, with automatic persistence of event handler errors for complete traceability ("Nachvollziehbarkeit").

## Architecture Modes

### 1. Centralized Event Architecture (Default)
- Single EventBus instance per process
- ExecutionEngine emits all events
- Best for single-instance deployments
- Lower complexity, easier debugging

### 2. Distributed Event Architecture (Optional)
- Redis pub/sub for event distribution
- Events propagate across all instances
- Required for horizontal scaling
- Enables multi-instance coordination

## Enabling Event-Aware Persistence

### Via Environment Variable
```bash
# Enable distributed events
export GLEITZEIT_ENABLE_DISTRIBUTED_EVENTS=true

# With Redis persistence (recommended)
export GLEITZEIT_PERSISTENCE_TYPE=redis
export GLEITZEIT_REDIS_URL=redis://localhost:6379/0
```

### Via Configuration
```python
from gleitzeit.client import GleitzeitClient

client = await GleitzeitClient.create(
    config={
        'enable_distributed_events': True,
        'persist_event_errors': True,  # Default: True
        'redis_url': 'redis://localhost:6379/0'
    }
)
```

## Event Error Persistence

All event handler errors are automatically persisted for traceability:

### Features
- **Automatic Error Capture**: Handler exceptions are caught and saved
- **Rich Context**: Includes traceback, event data, timestamps
- **Unified Storage**: Uses same backend as tasks (Redis/SQL/Memory)
- **Retention Policy**: Configurable retention period (default: 30 days)
- **Query Support**: Retrieve errors by ID, type, or time range

### Accessing Error History

```python
from gleitzeit.core.event_error_persistence import get_event_error_persistence

# Get the global error persistence
error_persistence = get_event_error_persistence()

# Get recent errors
recent_errors = await error_persistence.get_recent_errors(limit=10)

# Get errors for specific event type
workflow_errors = await error_persistence.get_recent_errors(
    limit=10,
    event_type='WORKFLOW_COMPLETED'
)

# Get specific error by ID
error = await error_persistence.get_error(error_id)

# Cleanup old errors
removed = await error_persistence.cleanup_old_errors()
```

### Error Record Structure
```python
@dataclass
class PersistedEventError:
    id: str                         # Unique error ID
    handler_name: str              # Handler that failed
    event_type: str                # Event type being handled
    event_id: Optional[str]        # Event ID if available
    error_type: str                # Exception class name
    error_message: str             # Error message
    error_traceback: Optional[str] # Full traceback
    timestamp: datetime            # When error occurred
    metadata: Optional[Dict]       # Additional context
```

## Event-Aware Persistence Adapters

### UnifiedRedisEventsAdapter
- Extends `UnifiedRedisAdapter`
- Adds Redis pub/sub for event distribution
- Automatic event serialization/deserialization
- Channel-based event routing

### UnifiedMemoryEventsAdapter  
- Extends `UnifiedInMemoryAdapter`
- Local event distribution via asyncio Queue
- Useful for testing and development

### HybridSQLAdapter
- Already supports event_bus parameter
- Combines memory runtime with SQL archival

## How Events Flow

### With Centralized Architecture (Default)
```
1. Task completes in ExecutionEngine
2. ExecutionEngine saves to persistence
3. ExecutionEngine emits event to local EventBus
4. EventBus distributes to local handlers
5. Errors saved to persistence if they occur
```

### With Distributed Architecture
```
1. Task completes in ExecutionEngine (Instance A)
2. ExecutionEngine saves to persistence
3. ExecutionEngine emits event to local EventBus
4. Event-aware adapter publishes to Redis pub/sub
5. All instances receive event via Redis
6. Each instance's EventBus distributes to local handlers
7. Errors saved to persistence if they occur
```

## Configuration Examples

### Single Instance (Default)
```python
# No special configuration needed
client = await GleitzeitClient.create()
```

### Multi-Instance with Redis
```python
client = await GleitzeitClient.create(
    config={
        'enable_distributed_events': True,
        'persistence_type': 'redis',
        'redis_url': 'redis://localhost:6379/0'
    }
)
```

### Development with Memory
```python
client = await GleitzeitClient.create(
    config={
        'enable_distributed_events': True,
        'persistence_type': 'memory',
        'persist_event_errors': True
    }
)
```

## Benefits

### Traceability (Nachvollziehbarkeit)
- Complete audit trail of all event handler failures
- Persistent error records for debugging
- Rich context including tracebacks

### Scalability
- Seamless transition from single to multi-instance
- Event distribution across instances
- Proper dependency resolution in distributed systems

### Reliability
- Isolated error handling (one handler's failure doesn't affect others)
- Automatic error persistence
- Configurable retention policies

## Migration Guide

### From Centralized to Distributed

1. **Enable Redis persistence**:
   ```bash
   export GLEITZEIT_PERSISTENCE_TYPE=redis
   export GLEITZEIT_REDIS_URL=redis://localhost:6379/0
   ```

2. **Enable distributed events**:
   ```bash
   export GLEITZEIT_ENABLE_DISTRIBUTED_EVENTS=true
   ```

3. **Restart all instances** - they will now share events

### Monitoring

Check event bus error statistics:
```python
# From EventBus
event_bus.get_error_stats()

# From persistence
error_persistence = get_event_error_persistence()
errors = await error_persistence.get_recent_errors()
```

## Performance Considerations

### Centralized Mode
- **Latency**: Minimal (in-memory)
- **Throughput**: High
- **CPU**: Low overhead
- **Network**: None

### Distributed Mode
- **Latency**: ~1-5ms (Redis pub/sub)
- **Throughput**: Depends on Redis
- **CPU**: Slightly higher (serialization)
- **Network**: Redis traffic

## Best Practices

1. **Start with centralized** architecture unless you need multi-instance
2. **Enable error persistence** for production environments
3. **Set appropriate retention** based on compliance requirements
4. **Monitor error rates** to identify problematic handlers
5. **Use distributed mode** only when horizontal scaling is required

## Troubleshooting

### Events Not Propagating
- Check Redis connection: `redis-cli ping`
- Verify `enable_distributed_events` is True
- Check event_bus is passed to PersistenceFactory

### Errors Not Persisting
- Verify `persist_event_errors` is True (default)
- Check persistence adapter is initialized
- Look for warnings in logs about persistence failures

### High Error Rates
- Check `event_bus.get_error_stats()` for patterns
- Review specific handlers that are failing
- Consider adjusting `isolate_errors` setting