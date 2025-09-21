# Stream Transport Architecture Documentation

## Overview

The Stream Transport implementation provides Redis Streams as a **transport-layer-only** replacement for Redis Pub/Sub, maintaining the exact same execution architecture while adding reliability features.

## Core Principle

**Streams are ONLY a transport mechanism** - they replace pub/sub for message delivery but do not change:
- Task execution logic
- Workflow orchestration
- Event handling
- Error propagation
- Component interactions

## Architecture Flow

```
┌─────────────────────────────────────────────────────────────┐
│                        API Layer                             │
│                   /workflows/ endpoint                       │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    SystemManager                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  if GLEITZEIT_STREAM_MODE == "enabled":             │    │
│  │      transport = StreamTransport(redis)             │    │
│  │  else:                                              │    │
│  │      transport = None  # Use pub/sub               │    │
│  └─────────────────────────────────────────────────────┘    │
│                         │                                    │
│                         ▼                                    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  QueueManager(transport=transport)                  │    │
│  └─────────────────────────────────────────────────────┘    │
│                         │                                    │
│                         ▼                                    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  ExecutionEngineV2(queue_manager=queue_manager)     │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   TaskOrchestrator                           │
│              (UNCHANGED - same as original)                  │
└─────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    QueueManager                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  if self.transport:                                 │    │
│  │      # Use stream transport                         │    │
│  │      await self.transport.publish(channel, task)   │    │
│  │  else:                                              │    │
│  │      # Use regular pub/sub                          │    │
│  │      await redis.publish(channel, task)            │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

### StreamTransport (`/src/gleitzeit/transport/stream_transport.py`)
- **Purpose**: Drop-in replacement for pub/sub transport
- **Interface**: Same as pub/sub (publish, subscribe, get_message)
- **Features**:
  - Message persistence via Redis Streams
  - Consumer groups for distributed processing
  - Automatic ACK/retry mechanism
  - Message replay capability

### SystemManager
- **Change**: Conditionally creates StreamTransport when enabled
- **Code Location**: `/src/gleitzeit/system/system_manager.py`
```python
if os.environ.get("GLEITZEIT_STREAM_MODE") == "enabled":
    transport = StreamTransport(redis_client)
queue_manager = QueueManager(transport=transport)
```

### QueueManager
- **Change**: Accepts optional transport parameter
- **Behavior**: Uses transport.publish() if available, otherwise pub/sub
- **No changes** to task management logic

### ExecutionEngineV2
- **No changes** - Uses same TaskOrchestrator
- **No stream-specific code paths**

### TaskOrchestrator
- **No changes** - Completely unaware of transport layer

## Event Flow with Stream Transport

### Task Submission
1. API receives workflow → routes to SystemManager.ExecutionEngine
2. ExecutionEngine → TaskOrchestrator.submit_workflow()
3. TaskOrchestrator schedules tasks → QueueManager.enqueue_task()
4. QueueManager:
   - With transport: `transport.publish("task_queue", task_data)`
   - Without: Regular pub/sub publish

### Task Execution
1. Worker listens via transport.get_message() or pub/sub
2. Receives task → TaskExecutor.execute_task()
3. Task result → Persistence layer
4. Events emitted normally through EventBus

### Error Handling
- Transport errors (Redis connection, etc.) bubble up normally
- Task execution errors handled by TaskOrchestrator as usual
- Failed messages in streams remain in pending list for retry
- No special error handling code for streams

## Event System Integration

Events flow through the same EventBus regardless of transport:
- TASK_READY
- TASK_STARTED
- TASK_COMPLETED
- TASK_FAILED
- WORKFLOW_STARTED
- WORKFLOW_COMPLETED
- WORKFLOW_FAILED

The transport layer is **completely orthogonal** to the event system.

## Configuration

### Environment Variables
```bash
# Enable stream transport
GLEITZEIT_STREAM_MODE=enabled

# Optional: Consumer group name
GLEITZEIT_STREAM_CONSUMER_GROUP=gleitzeit-workers

# Optional: Stream key prefix
GLEITZEIT_STREAM_PREFIX=gleitzeit:stream:
```

### Running with Streams
```bash
# Start server with stream transport
GLEITZEIT_STREAM_MODE=enabled gleitzeit serve --port 8000

# Client connects normally - no changes needed
gleitzeit submit workflow.yaml
```

## Benefits vs Pub/Sub

| Feature | Pub/Sub | Stream Transport |
|---------|---------|------------------|
| Message Persistence | ❌ | ✅ |
| Guaranteed Delivery | ❌ | ✅ |
| Message Replay | ❌ | ✅ |
| Consumer Groups | ❌ | ✅ |
| Backpressure | ❌ | ✅ |
| Architecture Changes | - | None |

## Error Scenarios

### Redis Connection Loss
- **With Pub/Sub**: Messages lost during downtime
- **With Streams**: Messages persisted, processed when connection restored

### Worker Crash
- **With Pub/Sub**: In-flight message lost
- **With Streams**: Message remains in pending list, reclaimed by another worker

### Task Failure
- **Both**: Same retry logic via TaskOrchestrator
- **Streams Advantage**: Failed message history preserved

## Implementation Stats

| Metric | Complex Streams | Simple Transport |
|--------|-----------------|------------------|
| Files Changed | 15+ | 4 |
| Lines of Code | ~2500 | ~400 |
| New Components | 8 | 1 |
| Architecture Impact | Major refactor | None |
| Testing Required | Extensive | Minimal |

## Testing Strategy

### Unit Tests
- Test StreamTransport in isolation
- Verify publish/subscribe/ack operations
- Test consumer group management

### Integration Tests
- Run same test suite with GLEITZEIT_STREAM_MODE on/off
- Verify identical behavior
- Test failure scenarios

### Performance Tests
- Compare latency pub/sub vs streams
- Measure throughput under load
- Test backpressure handling

## Migration Guide

### From Pub/Sub to Streams
```bash
# 1. Ensure Redis 5.0+ 
redis-cli INFO server | grep redis_version

# 2. Set environment variable
export GLEITZEIT_STREAM_MODE=enabled

# 3. Restart servers
systemctl restart gleitzeit

# Done - no code changes needed
```

### Rollback
```bash
# 1. Unset environment variable
unset GLEITZEIT_STREAM_MODE

# 2. Restart servers
systemctl restart gleitzeit

# Back to pub/sub
```

## Conclusion

The Stream Transport implementation achieves the goal of making task and workflow processing more failsafe **without creating a different execution path**. It demonstrates that reliability improvements can be achieved through surgical, transport-layer changes rather than architectural overhauls.

Key achievement: **The same code executes tasks whether using pub/sub or streams** - the only difference is the transport mechanism for message delivery.