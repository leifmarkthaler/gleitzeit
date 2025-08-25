# Centralized Event-Driven Architecture Implementation

## Overview

This document describes the implementation of a centralized event-driven architecture for Gleitzeit, where the ExecutionEngine serves as the single source of truth for all task lifecycle events. This architecture eliminates circular dependencies, ensures data consistency, and provides a clean separation of concerns.

## Architecture Principles

### 1. Single Source of Truth
- **ExecutionEngine** is the ONLY component that emits task lifecycle events
- All state changes are persisted BEFORE events are emitted
- No events are emitted from persistence adapters

### 2. Event-Driven Components
- Components respond to events rather than being directly called
- Each component has a single responsibility
- No circular dependencies between components

### 3. Data Consistency
- Save-Before-Emit pattern ensures data is always persisted before events
- Event handlers can safely read from persistence
- No race conditions between event emission and data persistence

## Component Architecture

```
┌─────────────────────┐
│  ExecutionEngine    │ ← Single source of task events
└──────────┬──────────┘
           │ Emits events
           ▼
    ┌──────────────┐
    │   EventBus   │ ← Central event distribution
    └──────┬───────┘
           │ Distributes to handlers
           ▼
┌──────────────────────────────────────────┐
│          Event-Driven Components         │
├──────────────────────────────────────────┤
│ • EventDrivenQueueManager                │
│ • EventDrivenRetryManager                │
│ • EventDrivenWorkflowManager             │
│ • TaskCompletedHandler                   │
│ • WorkflowCompletedHandler               │
└──────────────────────────────────────────┘
           │ Read/Write
           ▼
    ┌──────────────┐
    │  Persistence │ ← Shared data store
    └──────────────┘
```

## Implementation Details

### Phase 1: Centralized Event Emission

#### Modified Files:
1. **`src/gleitzeit/persistence/factory.py`**
   - Removed event-driven adapter usage
   - Always returns base adapters (Redis/SQL) without event emission
   ```python
   # Always use base adapter (no event emission from persistence layer)
   logger.info("Creating Redis adapter (centralized event architecture)")
   adapter = UnifiedRedisAdapter(...)
   ```

2. **`src/gleitzeit/core/execution_engine.py`**
   - Saves task state to persistence BEFORE emitting events
   - Ensures data consistency
   ```python
   # Save to persistence FIRST (before emitting events)
   if self.persistence:
       await self.persistence.save_task(task)
       await self.persistence.save_task_result(task_result)
   
   # Then emit task completion event for other components
   if hasattr(self, 'event_bus') and self.event_bus:
       await self.event_bus.emit(completion_event)
   ```

### Phase 2: Event-Driven Queue Manager

#### New Component:
**`src/gleitzeit/task_queue/event_driven_queue_manager.py`**

Responds to events:
- `TASK_SUBMITTED` → Enqueues task if dependencies satisfied
- `TASK_COMPLETED` → Checks for newly ready tasks
- `TASK_FAILED` → Updates queue state
- `RETRY_SCHEDULED` → Tracks retry scheduling
- `TASK_READY_FOR_RETRY` → Enqueues retry tasks

Key features:
- No direct task submission (responds to events only)
- Emits `TASK_READY` events when tasks are ready for execution
- Handles dependency resolution through events

### Phase 3: Event-Driven Retry Manager

#### New Component:
**`src/gleitzeit/core/event_driven_retry_manager.py`**

Responds to events:
- `TASK_FAILED` → Evaluates if task should be retried
- Calculates backoff delays (exponential, linear, fixed)
- Schedules retries using scheduler or asyncio
- Emits `RETRY_SCHEDULED` and `TASK_READY_FOR_RETRY` events

Key features:
- Configurable retry strategies
- Jitter support to prevent thundering herd
- Max retry limit enforcement
- Non-retryable error detection

### Phase 4: Event-Driven Workflow Manager

#### New Component:
**`src/gleitzeit/core/event_driven_workflow_manager.py`**

Responds to events:
- `WORKFLOW_SUBMITTED` → Initializes workflow tracking
- `TASK_STARTED` → Marks workflow as RUNNING on first task
- `TASK_COMPLETED` → Checks for workflow completion
- `TASK_FAILED` → Evaluates workflow failure conditions

Emits events:
- `WORKFLOW_STARTED` → When first task begins
- `WORKFLOW_COMPLETED` → When all tasks complete
- `WORKFLOW_FAILED` → When critical task fails
- `WORKFLOW_PROGRESS` → Progress updates

## Event Flow Examples

### 1. Simple Task Execution
```
ExecutionEngine.execute_task()
  ├─→ Save task status to persistence
  ├─→ Emit TASK_STARTED event
  ├─→ Execute task via provider
  ├─→ Save task result to persistence
  └─→ Emit TASK_COMPLETED event
      ├─→ EventDrivenQueueManager: Check for ready tasks
      ├─→ EventDrivenWorkflowManager: Update workflow state
      └─→ TaskCompletedHandler: Resolve dependencies
```

### 2. Task with Retry
```
Task fails in ExecutionEngine
  ├─→ Save failed status to persistence
  └─→ Emit TASK_FAILED event
      └─→ EventDrivenRetryManager receives event
          ├─→ Check retry configuration
          ├─→ Calculate backoff delay
          ├─→ Update task metadata with retry info
          ├─→ Save to persistence
          └─→ Emit RETRY_SCHEDULED event
              └─→ After delay: Emit TASK_READY_FOR_RETRY
                  └─→ EventDrivenQueueManager: Re-enqueue task
```

### 3. Workflow with Dependencies
```
Workflow submitted
  ├─→ ExecutionEngine.submit_workflow()
  ├─→ Submit all tasks
  └─→ Emit WORKFLOW_SUBMITTED event
      └─→ EventDrivenWorkflowManager: Track workflow
      
Task A completes
  └─→ Emit TASK_COMPLETED event
      └─→ EventDrivenQueueManager: Check dependencies
          └─→ Task B now ready
              └─→ Emit TASK_READY event
                  └─→ ExecutionEngine: Execute Task B
```

## Configuration

### Client Configuration with Retry
```python
client = GleitzeitClient(
    mode='native',
    native_config={
        'persistence': {
            'type': 'redis',
            'redis_url': 'redis://localhost:6379/0'
        },
        'retry': {
            'enabled': True,
            'max_attempts': 3,
            'backoff_strategy': 'exponential',
            'base_delay': 2.0,
            'max_delay': 30.0,
            'jitter': True
        }
    }
)
```

### Workflow YAML with Retry
```yaml
tasks:
  - name: "task_with_retry"
    method: "python/execute"
    retry_config:  # or 'retry' - both supported
      max_attempts: 3
      backoff_strategy: "exponential"
      base_delay: 2
      max_delay: 10
      jitter: true
```

## Testing

### Test Files Created:
1. **`tests/test_retry_manager.py`** - Event-driven retry manager tests
2. **`tests/test_workflow_manager.py`** - Event-driven workflow manager tests
3. **`test_redis_event_architecture.py`** - Integration test with Redis
4. **`test_complex_workflow_redis.py`** - Complex workflow tests

### Test Coverage:
- ✅ Simple workflow execution
- ✅ Retry with backoff strategies
- ✅ Parallel task execution
- ✅ Task dependencies
- ✅ Parameter substitution
- ✅ Workflow state tracking
- ✅ Event flow validation

## Benefits

### 1. Clean Architecture
- No circular dependencies
- Clear separation of concerns
- Single responsibility principle

### 2. Data Consistency
- Guaranteed persistence before event emission
- No race conditions
- Reliable event replay possible

### 3. Scalability
- Components can be distributed
- Event bus can be replaced with message queue
- Horizontal scaling friendly

### 4. Maintainability
- Clear event flow
- Easy to debug
- Component isolation

### 5. Extensibility
- New event handlers easily added
- Components loosely coupled
- Event-driven plugins possible

## Migration Guide

### For Existing Code:
1. **Remove direct calls to queue/retry managers** - They now respond to events
2. **Use ExecutionEngine.submit_task()** - This triggers the event chain
3. **Don't emit events from persistence** - Only ExecutionEngine emits events
4. **Register event handlers properly** - Use EventBus.register()

### For New Features:
1. **Create event handlers, not direct integrations**
2. **Follow Save-Before-Emit pattern**
3. **Use existing event types when possible**
4. **Document event dependencies**

## Troubleshooting

### Common Issues:

1. **Tasks stuck in PENDING**
   - Check if TASK_SUBMITTED event is being emitted
   - Verify EventDrivenQueueManager is registered

2. **Retries not working**
   - Ensure retry configuration is set (client or workflow level)
   - Check if EventDrivenRetryManager is registered
   - Verify TASK_FAILED events include attempt_number

3. **Workflow not completing**
   - Check if all tasks are emitting TASK_COMPLETED
   - Verify EventDrivenWorkflowManager is registered
   - Look for workflow completion events in logs

4. **Duplicate event emissions**
   - Ensure only ExecutionEngine emits task events
   - Check for multiple event handler registrations
   - Verify persistence adapters aren't emitting events

## Future Enhancements

1. **Event Sourcing**
   - Store all events for replay
   - Event-based debugging
   - Time-travel debugging

2. **Distributed Event Bus**
   - Replace with RabbitMQ/Kafka
   - Multi-node execution
   - Event persistence

3. **Monitoring & Metrics**
   - Event flow visualization
   - Performance metrics per event type
   - Bottleneck detection

4. **Advanced Retry Strategies**
   - Circuit breaker pattern
   - Adaptive retry delays
   - Error classification

## Conclusion

The centralized event-driven architecture provides a robust, scalable foundation for Gleitzeit's workflow execution. By maintaining ExecutionEngine as the single source of truth and using event-driven components, we achieve clean separation of concerns, data consistency, and excellent maintainability.