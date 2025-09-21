# Event Stream Misalignment Audit - Task Scheduling Issue

## Executive Summary
Tasks remain in pending state because of a critical **disconnect in the event stream pathway** between task submission and task scheduling. The system has event streaming infrastructure but **tasks are not being emitted to the event stream** when submitted.

## Critical Finding: Missing Event Emission in Task Submission Flow

### 1. Task Submission Path Analysis

#### API Layer (`/tasks/` endpoint)
- **File**: `src/gleitzeit/api/routes/tasks.py:40`
- Receives task submission request
- Delegates to `client.submit_task()`

#### Client Layer
- **File**: `src/gleitzeit/client/mixins/task.py:31`
- Forwards to adapter's `submit_task()`

#### Native Adapter Layer
- **File**: `src/gleitzeit/client/adapters/native.py:542-553`
- **PROBLEM**: Directly saves task to persistence
- **MISSING**: No event emission to notify system of new task
```python
async def submit_task(self, task: Task) -> Dict[str, Any]:
    # Saves task directly to persistence
    await self.persistence.create_task(task_dict)
    # Returns immediately - NO EVENT EMITTED
    return {"success": True, "task_id": task_dict.get("id")}
```

### 2. Event Stream Infrastructure (Working but Disconnected)

#### StreamEventBus
- **File**: `src/gleitzeit/events/stream_event_bus.py`
- Properly configured with consumer groups
- Listening for events on Redis streams
- Has handlers registered for task events

#### TaskOrchestrator Event Handlers
- **File**: `src/gleitzeit/core/task_orchestrator.py:94-101`
- Registered to handle:
  - `WORKFLOW_SUBMITTED` → enqueue initial tasks
  - `TASK_READY` → schedule task execution
  - `TASK_COMPLETED/FAILED` → workflow progression

#### QueueManager Event Handlers  
- **File**: `src/gleitzeit/task_queue/task_queue.py:684-703`
- Registered to handle `TASK_SUBMITTED` events
- Would enqueue task and emit `TASK_READY` event
- **BUT NEVER RECEIVES EVENTS** because they're not emitted

### 3. The Missing Link

The execution engine (`execution_engine_v2.py:335`) **does emit** `TASK_SUBMITTED` events when tasks are submitted through it, but:

1. **Direct task submission** via API/Client bypasses the execution engine
2. Tasks go straight to persistence without event notification
3. No component is aware that a new task needs scheduling
4. Task remains in PENDING state indefinitely

### 4. Event Flow Comparison

#### Current (Broken) Flow:
```
API → Client → NativeAdapter → Persistence
                                    ↓
                              Task saved (PENDING)
                                    ↓
                                 [DEAD END]
```

#### Expected Flow:
```
API → Client → NativeAdapter → Persistence
                      ↓              ↓
                Emit TASK_SUBMITTED  Task saved
                      ↓
                 StreamEventBus
                      ↓
                 QueueManager
                      ↓
                Emit TASK_READY
                      ↓
               TaskOrchestrator
                      ↓
                Execute Task
```

## Root Cause
The native adapter's `submit_task()` method only persists the task but doesn't emit any events to notify the system. This breaks the event-driven architecture where components rely on events to trigger actions.

## Recommendations

### Immediate Fix
Modify `NativeAdapter.submit_task()` to emit a `TASK_SUBMITTED` event:

```python
async def submit_task(self, task: Task) -> Dict[str, Any]:
    if not self.initialized:
        await self.initialize()
        
    try:
        task_dict = task.dict() if hasattr(task, 'dict') else task
        await self.persistence.create_task(task_dict)
        
        # CRITICAL: Emit event to trigger scheduling
        if self.event_bus:
            await self.event_bus.emit(GleitzeitEvent(
                event_type=EventType.TASK_SUBMITTED,
                data={
                    "task_id": task_dict.get("id"),
                    "task_name": task_dict.get("name"),
                    "status": "pending"
                },
                source="native_adapter"
            ))
        
        return {"success": True, "task_id": task_dict.get("id")}
    except Exception as e:
        logger.error(f"Error submitting task: {e}")
        return {"success": False, "error": str(e)}
```

### Additional Improvements

1. **Add event bus to NativeAdapter initialization**
   - Ensure NativeAdapter has access to the event bus
   - Pass through SystemManager's event bus instance

2. **Verify event consumption**
   - Ensure StreamEventBus is running (`await event_bus.start()`)
   - Confirm consumer groups are created for task event streams

3. **Add monitoring**
   - Log event emission in submit_task
   - Log event reception in QueueManager
   - Track task state transitions

## Verification Steps

1. Check if tasks are being saved to persistence ✓
2. Check if TASK_SUBMITTED events are emitted ✗
3. Check if QueueManager receives events ✗ (no events to receive)
4. Check if TASK_READY events are emitted ✗ (depends on #2)
5. Check if TaskOrchestrator schedules tasks ✗ (depends on #4)

## Impact
This misalignment affects:
- All direct task submissions via API
- Task scheduling and execution
- Workflow progression (tasks never complete)
- System observability (no event trail)

## Priority: CRITICAL
Without this fix, the entire task execution system is non-functional for API-submitted tasks.