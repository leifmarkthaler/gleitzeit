# Gleitzeit 0.0.7 Cancellation Implementation Audit

## Executive Summary
The cancellation functionality for tasks and workflows is **partially implemented** in Gleitzeit 0.0.7. The API endpoints exist and emit events, but workers do not actively listen for cancellation events, meaning cancellation only prevents future execution rather than stopping running tasks.

## Current Implementation Status

### ✅ What's Already Implemented

1. **Event Definitions** (`src/gleitzeit/core/events.py`)
   - `TASK_CANCELLED = "task:cancelled"` (line 37)
   - `WORKFLOW_CANCELLED = "workflow:cancelled"` (line 50)
   - Both events are properly defined in the EventType enum

2. **API Endpoints**

   **Task Cancellation** (`src/gleitzeit/api/routes/tasks.py`)
   - `POST /tasks/{task_id}/cancel` endpoint exists
   - Sets task status to "cancelled"
   - Adds task to `tasks:cancelled` set
   - Emits event to `task:cancelled` stream
   - Prevents retry of cancelled tasks (similar to blocked)

   **Workflow Cancellation** (`src/gleitzeit/api/routes/workflows.py`)
   - `POST /workflows/{workflow_id}/cancel` endpoint exists
   - Sets workflow status to "cancelled"
   - Cancels all non-terminal tasks
   - Emits events to `workflow:cancelled` and `task:cancelled` streams

3. **Task Execution Checks** (`src/gleitzeit/workers/task_execution_worker.py`)
   - Checks if task status is "cancelled" before execution
   - Skips execution if cancelled
   - Emits cancellation confirmation event

## 🔴 What's Missing

### 1. No Active Cancellation Stream Consumption
Workers are NOT consuming from cancellation streams:
- No worker subscribes to `task:cancelled` stream
- No worker subscribes to `workflow:cancelled` stream
- Cancellation events are emitted but not actively processed

### 2. No Running Task Interruption
Currently running tasks cannot be interrupted:
- Task execution worker only checks status BEFORE execution
- No mechanism to stop a task mid-execution
- Long-running tasks will complete even after cancellation

### 3. No Cancellation Worker
Unlike retry functionality which has a dedicated RetryWorker, there's no CancellationWorker to:
- Monitor cancellation events
- Propagate cancellation to dependent tasks
- Handle cleanup of cancelled workflows

## Comparison with task:blocked Implementation

The `task:blocked` implementation (lines 278-294 in `dependency_worker.py`):
```python
# When dependency fails:
- Adds task to tasks:blocked set
- Sets task status to "blocked"
- Stores blocked_by and blocked_reason
- Does NOT emit to a stream (passive blocking)
- Prevents task from entering ready queue
- Excluded from retry attempts
```

Current `task:cancelled` implementation:
```python
# When cancellation requested:
- Adds task to tasks:cancelled set  ✅
- Sets task status to "cancelled"    ✅
- Stores cancellation reason          ✅
- Emits to task:cancelled stream     ✅ (but not consumed)
- Prevents retry attempts             ✅
- Does NOT interrupt running tasks    ❌
```

## Recommended Implementation Plan

### Phase 1: Cancellation Event Listener
Create a dedicated cancellation listener in workers that need to respond to cancellation:

1. **DependencyWorker Enhancement**
   - Subscribe to `task:cancelled` and `workflow:cancelled` streams
   - When task is cancelled, mark dependent tasks as blocked
   - Prevent cancelled tasks from becoming ready

2. **TaskExecutionWorker Enhancement**
   - Subscribe to `task:cancelled` stream for its shard
   - Maintain a set of cancelled task IDs
   - Check cancellation status during long-running operations
   - Implement graceful interruption points

### Phase 2: Running Task Interruption
For tasks that are currently executing:

1. **Subprocess-based Tasks (Python Handler)**
   - Store subprocess PID when starting execution
   - On cancellation, send SIGTERM to subprocess
   - Wait for graceful shutdown, then SIGKILL if needed

2. **HTTP Tasks**
   - Store request context
   - Cancel ongoing HTTP requests using aiohttp cancellation

3. **Handler-level Cancellation**
   - Add `cancel()` method to base handler
   - Each handler implements appropriate cancellation logic

### Phase 3: Cascading Cancellation
Similar to how blocked tasks cascade:

1. When a task is cancelled:
   - Mark all dependent tasks as "blocked" with reason "dependency_cancelled"
   - Emit events for audit trail
   - Update workflow completion logic to account for cancelled tasks

## Testing Requirements

1. **Unit Tests**
   - Cancel pending task → verify it never executes
   - Cancel running task → verify it stops execution
   - Cancel workflow → verify all tasks cancelled

2. **Integration Tests**
   - Submit workflow, cancel immediately → no tasks execute
   - Submit workflow, cancel during execution → running tasks stop
   - Cancel task with dependencies → dependents blocked

3. **Load Tests**
   - Cancel 1000+ workflows simultaneously
   - Verify no resource leaks
   - Verify Redis streams don't accumulate unconsumed messages

## Implementation Priority

**HIGH PRIORITY**:
- Add cancellation stream consumption to prevent unconsumed message accumulation
- Implement dependency blocking for cancelled tasks

**MEDIUM PRIORITY**:
- Add running task interruption for long-running tasks
- Implement handler-level cancellation support

**LOW PRIORITY**:
- Add cancellation metrics and monitoring
- Implement cancellation deadlines (force kill after timeout)

## Code Changes Required

### 1. DependencyWorker (`src/gleitzeit/workers/dependency_worker.py`)
```python
# Add to streams list in run() method:
streams.append(f"task:cancelled")
streams.append(f"workflow:cancelled")

# Add handler method:
async def handle_task_cancelled(self, data: Dict):
    task_id = data['task_id']
    workflow_id = data['workflow_id']
    # Block dependent tasks
    await self.block_dependents(workflow_id, task_id, "dependency_cancelled")
```

### 2. TaskExecutionWorker (`src/gleitzeit/workers/task_execution_worker.py`)
```python
# Add cancellation check during execution:
async def execute_task(self, task_data: Dict):
    # Periodically check if cancelled
    if await self.is_task_cancelled(task_id):
        raise TaskCancelledException()
```

## Conclusion

The cancellation feature has a solid foundation with API endpoints and event definitions, but lacks the critical worker-side implementation to make it fully functional. The most urgent need is to add stream consumers to prevent message accumulation and implement proper task blocking for cancelled dependencies, similar to how failed dependencies are handled.

The implementation should follow the existing pattern of task:blocked but with active event consumption to enable real-time cancellation response.