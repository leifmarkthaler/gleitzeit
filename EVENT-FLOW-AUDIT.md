# Event Flow Audit - Redis Streams Architecture

## Overview
Complete audit of the event flow in the stateless Redis Streams architecture to identify why workflows stay in pending state and tasks don't execute.

## Current Architecture

### Event-Driven Flow (No Polling)
1. **Workflow Submission**: API → SystemManager → WorkflowManager → ExecutionEngine → StatelessTaskOrchestrator
2. **Event Emission**: StatelessTaskOrchestrator emits `workflow:submitted` to Redis stream
3. **Event Consumption**: MultiplexedStreamConsumer reads from streams, routes to handlers
4. **Task Execution**: StatelessTaskOrchestrator processes tasks atomically via events
5. **Workflow Completion**: All tasks complete → workflow marked complete

### Current Status
1. **Workflow Submission**: ✅ Works (workflow saved to persistence)
2. **Event Emission**: ✅ Works (`workflow:submitted` emitted)
3. **Handler Registration**: ✅ Works (handlers registered with StreamSystemManager)
4. **Server Startup**: ❌ **BLOCKED** - Event contract violations prevent startup
5. **Task Execution**: ❌ **UNTESTED** - Can't test due to startup failure

## Event Flow Components

### 1. Workflow Submission Flow

#### API → SystemManager → WorkflowManager
```python
# API: routes/workflows.py
await system_manager.submit_workflow_authenticated(workflow, session_id)

# SystemManager: system_manager.py:958
await self.workflow_manager.submit_workflow(validated_workflow)

# WorkflowManager: workflow_manager.py:223-246
# - Saves workflow to persistence
# - Emits EventType.WORKFLOW_SUBMITTED (old event bus)
# - Calls execution_engine.submit_workflow(workflow)
```

#### ExecutionEngineV2 → StatelessTaskOrchestrator
```python
# ExecutionEngineV2: execution_engine_v2.py:389
await self.task_orchestrator.submit_workflow(workflow)

# StatelessTaskOrchestrator: stateless_task_orchestrator.py:373-382
# - Saves workflow to persistence (duplicate)
# - Emits "workflow:submitted" event to stream
await self.event_bus.emit(GleitzeitEvent(
    event_type="workflow:submitted",
    data={...}
))
```

### 2. Event Registration & Handling

#### Handler Registration
```python
# StatelessTaskOrchestrator registers with StreamSystemManager:
stream_manager.register_event_handler('workflow:submitted', self._handle_workflow_submitted, 'StatelessTaskOrchestrator')
stream_manager.register_event_handler('task:ready', self._handle_task_ready, 'StatelessTaskOrchestrator')
stream_manager.register_event_handler('task:completed', self._handle_task_completed, 'StatelessTaskOrchestrator')
stream_manager.register_event_handler('task:failed', self._handle_task_failed, 'StatelessTaskOrchestrator')
```

#### MultiplexedStreamConsumer
- Reads from Redis streams using XREADGROUP
- Routes events to registered handlers
- Two-phase acknowledgment (only ACK after successful processing)

### 3. Event Contract System

#### Critical Event Contracts (from event_contracts.py)
```python
WORKFLOW_CONTRACTS = {
    'workflow:completed': EventContract(
        required_handlers=['WorkflowManager'],
        critical=True  # BLOCKING - prevents startup
    ),
    'workflow:failed': EventContract(
        required_handlers=['WorkflowManager'],
        critical=True  # BLOCKING - prevents startup
    )
}

QUEUE_CONTRACTS = {
    'task:submitted': EventContract(
        required_handlers=['QueueManager'],
        critical=True  # BLOCKING - prevents startup
    ),
    'task:ready_for_retry': EventContract(
        required_handlers=['QueueManager'],
        critical=True  # BLOCKING - prevents startup
    )
}
```

## Event Flow Issues

### Issue 1: Event Contract Violations (CRITICAL BLOCKER)
**Problem**: Server fails to start with "EVENT CONTRACT VIOLATIONS DETECTED!"

**Missing Handlers**:
- WorkflowManager doesn't register for `workflow:completed/failed`
- QueueManager doesn't register for `task:submitted/ready_for_retry`

**Impact**: System cannot start, making all other fixes untestable

### Issue 2: Duplicate Event Processing (FIXED)
**Problem**: TASK_READY events processed multiple times
**Solution**: Added idempotency checks in StatelessTaskOrchestrator

### Issue 3: Event Type Mismatch (RESOLVED)
**Problem**: WorkflowManager emits old EventType, StatelessTaskOrchestrator expects string
**Status**: Both use string-based events now

## Complete Event Flow Mapping

### Working Events ✅
```
workflow:submitted → StatelessTaskOrchestrator._handle_workflow_submitted ✅
task:ready → StatelessTaskOrchestrator._handle_task_ready ✅
task:completed → StatelessTaskOrchestrator._handle_task_completed ✅
task:failed → StatelessTaskOrchestrator._handle_task_failed ✅
```

### Missing Handlers (Contract Violations) ❌
```
workflow:completed → WorkflowManager (NO HANDLER) ❌
workflow:failed → WorkflowManager (NO HANDLER) ❌
task:submitted → QueueManager (NO HANDLER) ❌
task:ready_for_retry → QueueManager (NO HANDLER) ❌
```

### Event Emission Points
- `workflow:submitted` - StatelessTaskOrchestrator.submit_workflow() ✅
- `task:ready` - StatelessTaskOrchestrator._handle_workflow_submitted() ✅
- `task:completed` - TaskExecutor after task execution ✅
- `workflow:completed` - StatelessTaskOrchestrator when all tasks done ✅

## Required Fixes

### Priority 1: Fix Event Contract Violations (BLOCKING)

**Option A: Make contracts non-critical**
```python
# In event_contracts.py, change critical=True to critical=False for:
- workflow:completed
- workflow:failed
- task:submitted
- task:ready_for_retry
```

**Option B: Add missing handlers to WorkflowManager**
```python
async def register_with_stream_manager(self, stream_manager):
    stream_manager.register_event_handler('workflow:completed', self._handle_workflow_completed, 'WorkflowManager')
    stream_manager.register_event_handler('workflow:failed', self._handle_workflow_failed, 'WorkflowManager')

async def _handle_workflow_completed(self, event):
    # Update workflow status, cleanup resources
    pass
```

**Option C: Add missing handlers to QueueManager**
```python
async def register_with_stream_manager(self, stream_manager):
    stream_manager.register_event_handler('task:submitted', self._handle_task_submitted, 'QueueManager')
    stream_manager.register_event_handler('task:ready_for_retry', self._handle_ready_for_retry, 'QueueManager')

### Priority 2: Remove Duplicate Operations

**Issue**: Both WorkflowManager and StatelessTaskOrchestrator save workflow
```python
# WorkflowManager.submit_workflow() line 212:
await self.persistence.save_workflow(workflow)

# StatelessTaskOrchestrator.submit_workflow() line 371:
await self.persistence.save_workflow(workflow)  # DUPLICATE
```

### Priority 3: Ensure Proper Event Flow

**Expected sequence**:
1. workflow:submitted → triggers initial task enqueueing
2. task:ready → triggers task execution
3. task:completed → checks dependencies, enqueues next tasks
4. workflow:completed → when all tasks done

## Testing Strategy

### Step 1: Fix Contract Violations
- Choose Option A, B, or C above
- Verify server starts without violations

### Step 2: Submit Test Workflow
```python
workflow = {
    "id": "test-1",
    "name": "Simple Test",
    "tasks": [{
        "id": "task-1",
        "name": "Add Numbers",
        "protocol": "python/v1",
        "method": "python/execute",
        "params": {...}
    }]
}
```

### Step 3: Verify Event Flow
- Check workflow:submitted emitted
- Check task:ready emitted
- Check task execution starts
- Check task:completed emitted
- Check workflow:completed emitted

## Summary

### Current State
- ✅ Event flow architecture is correct
- ✅ Handlers are properly registered
- ✅ Events are being emitted
- ❌ **BLOCKED**: Event contract violations prevent server startup
- ❌ **UNTESTED**: Workflow execution blocked by startup failure

### Root Cause
The event contracts system requires handlers that don't exist:
- WorkflowManager needs workflow:completed/failed handlers
- QueueManager needs task:submitted/ready_for_retry handlers

These are marked as critical, preventing system startup.

### Recommended Fix
Option A: Make the missing handler contracts non-critical to allow system to start and test the actual workflow execution flow.

---

**Next Steps**:
1. Fix event contract violations
2. Start server successfully
3. Test workflow execution
4. Add missing handlers if actually needed