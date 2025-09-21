# Component Architecture Audit

## Overview
The system has a dual event architecture - old event bus (EventType enums) and new stream-based (string events). Components need to be bridged to work with both systems.

## Current Architecture

### Components with Stream Registration ✅
1. **StatelessTaskOrchestrator**
   - Has `register_with_stream_manager()` method
   - Registers handlers for: `workflow:submitted`, `task:ready`, `task:completed`, `task:failed`

2. **ExecutionEngineV2**
   - Has `register_with_stream_manager()` method
   - Delegates to StatelessTaskOrchestrator

### Components with Old Event Bus Only ❌
1. **WorkflowManager**
   - Has `_setup_event_handlers()` using old EventType
   - Registers: `TASK_COMPLETED`, `TASK_FAILED`, `WORKFLOW_COMPLETED`, `WORKFLOW_FAILED`
   - **MISSING**: `register_with_stream_manager()` method

2. **QueueManager**
   - Has event handlers using old EventType
   - Registers: `TASK_SUBMITTED`, `TASK_READY_FOR_RETRY`, `WORKFLOW_SUBMITTED`
   - **MISSING**: `register_with_stream_manager()` method

## Event Contract Requirements

### Critical Contracts (Blocking Server Startup)
```python
# From event_contracts.py
WORKFLOW_CONTRACTS = {
    'workflow:completed': required=['WorkflowManager'], critical=True
    'workflow:failed': required=['WorkflowManager'], critical=True
}

QUEUE_CONTRACTS = {
    'task:submitted': required=['QueueManager'], critical=True
    'task:ready_for_retry': required=['QueueManager'], critical=True
}
```

## Registration Pattern

### How Components Register (Working Example)
```python
# StatelessTaskOrchestrator
async def register_with_stream_manager(self, stream_manager):
    component_name = 'StatelessTaskOrchestrator'
    stream_manager.register_event_handler('workflow:submitted', self._handle_workflow_submitted, component_name)
    stream_manager.register_event_handler('task:ready', self._handle_task_ready, component_name)
    # etc...
```

### System Manager Calls
```python
# StreamSystemManager calls during startup
if hasattr(self.execution_engine, 'register_with_stream_manager'):
    self.execution_engine.register_with_stream_manager(self)

# MISSING: Similar calls for WorkflowManager and QueueManager
```

## Required Implementation

### 1. Add to WorkflowManager
```python
async def register_with_stream_manager(self, stream_manager):
    """Register handlers with StreamSystemManager for stream-based events."""
    component_name = 'WorkflowManager'

    # Map old handlers to new event types
    stream_manager.register_event_handler('task:completed', self._on_task_completed, component_name)
    stream_manager.register_event_handler('task:failed', self._on_task_failed, component_name)
    stream_manager.register_event_handler('workflow:completed', self._on_workflow_completed, component_name)
    stream_manager.register_event_handler('workflow:failed', self._on_workflow_failed, component_name)

    logger.info("WorkflowManager registered handlers with StreamSystemManager")
```

### 2. Add to QueueManager
```python
async def register_with_stream_manager(self, stream_manager):
    """Register handlers with StreamSystemManager for stream-based events."""
    component_name = 'QueueManager'

    # Map old handlers to new event types
    stream_manager.register_event_handler('task:submitted', self._on_task_submitted, component_name)
    stream_manager.register_event_handler('task:ready_for_retry', self._on_task_ready_for_retry, component_name)
    stream_manager.register_event_handler('workflow:submitted', self._on_workflow_submitted, component_name)

    logger.info("QueueManager registered handlers with StreamSystemManager")
```

### 3. Update SystemManager to Call Registration
```python
# In StreamSystemManager.start_system() Phase 2
if self.workflow_manager and hasattr(self.workflow_manager, 'register_with_stream_manager'):
    await self.workflow_manager.register_with_stream_manager(self)

if self.queue_manager and hasattr(self.queue_manager, 'register_with_stream_manager'):
    await self.queue_manager.register_with_stream_manager(self)
```

## Event Flow Summary

### Current Flow (Partial)
1. API → SystemManager.submit_workflow_authenticated()
2. WorkflowManager.submit_workflow() → emits old EventType.WORKFLOW_SUBMITTED
3. ExecutionEngineV2.submit_workflow()
4. StatelessTaskOrchestrator.submit_workflow() → emits "workflow:submitted" (stream)
5. MultiplexedStreamConsumer routes to handlers

### After Fix
- WorkflowManager and QueueManager will receive stream events
- Event contracts will be satisfied
- Server can start without violations

## Testing Strategy

1. Add registration methods to WorkflowManager and QueueManager
2. Update SystemManager to call them during startup
3. Verify server starts without contract violations
4. Submit test workflow and verify execution

## Alternative: Relax Contracts

If implementation is blocked, temporarily set `critical=False` in event_contracts.py for:
- `workflow:completed`
- `workflow:failed`
- `task:submitted`
- `task:ready_for_retry`

This allows testing while proper handlers are implemented.