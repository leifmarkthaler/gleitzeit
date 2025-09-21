# Gleitzeit Status System Documentation

## Overview
The Gleitzeit status system provides clear, semantic status values for both tasks and workflows, indicating their current state in the execution lifecycle.

## Task Status Values

### Status Definitions
- **`PENDING`** - Task is waiting for dependencies to be resolved
- **`QUEUED`** - Task has been added to the execution queue
- **`VALIDATED`** - Task parameters and configuration have been validated
- **`ROUTED`** - Task has been routed to a provider
- **`EXECUTING`** - Task is currently being executed by a provider
- **`WAITING`** - Task is waiting for an external signal
- **`SCHEDULED`** - Task is scheduled to run at a specific time (timer)
- **`PAUSED`** - Task has been explicitly paused
- **`COMPLETED`** - Task has completed successfully
- **`FAILED`** - Task execution failed
- **`CANCELLED`** - Task was explicitly cancelled
- **`RETRY_PENDING`** - Task is pending retry after failure
- **`REWOUND`** - Task has been rewound for re-execution
- **`SLEEPING`** - **Deprecated** - Use PAUSED instead

### Task Status Transitions

#### Initial Submission
**Location**: `/src/gleitzeit/task_queue/task_queue.py`
- New tasks start as `PENDING` if they have dependencies (line 122)
- Tasks without dependencies go to `QUEUED` (line 114)

#### Queue Processing
**Location**: `/src/gleitzeit/task_queue/task_queue.py`
- `PENDING` → `QUEUED` when dependencies are satisfied (line 598)
- `QUEUED` → `VALIDATED` after validation (line 326)
- `VALIDATED` → `ROUTED` when sent to provider (line 333)

#### Execution Phase
**Location**: `/src/gleitzeit/core/task_executor.py`
- `ROUTED` → `EXECUTING` when execution begins (line 96)
- `EXECUTING` → `COMPLETED` on successful completion (line 162)
- `EXECUTING` → `FAILED` on error (lines 179-208)
- `EXECUTING` → `WAITING` when waiting for signal (line 135)
- `EXECUTING` → `SCHEDULED` when scheduled with timer (line 135)
- `EXECUTING` → `PAUSED` when explicitly paused (line 135)

#### Provider-Specific Status Changes

**Signal Provider** (`/src/gleitzeit/providers/signal_provider.py`)
- Returns `TaskStatus.WAITING` for tasks waiting on signals (line 183)

**Timer Provider** (`/src/gleitzeit/providers/timer_provider.py`)
- Returns `TaskStatus.SCHEDULED` for scheduled tasks (line 164)

#### Task Cancellation
**Location**: `/src/gleitzeit/client/adapters/native.py`
- `cancel_task` method sets status to `CANCELLED` (line 594)

**Location**: `/src/gleitzeit/task_queue/task_queue.py`
- Queue can mark tasks as `CANCELLED` (lines 261, 517)
- Cancelled tasks are skipped during processing (line 392)

#### Retry Logic
**Location**: `/src/gleitzeit/core/event_driven_retry_manager.py`
- `FAILED` → `RETRY_PENDING` when retry is scheduled
- `RETRY_PENDING` → `QUEUED` when retry is executed

## Workflow Status Values

### Status Definitions
- **`PENDING`** - Workflow created but no tasks have started
- **`RUNNING`** - Workflow has actively executing tasks or mixed states
- **`WAITING`** - All remaining tasks are waiting for signals
- **`SCHEDULED`** - All remaining tasks are scheduled (timers)
- **`PAUSED`** - Workflow has been explicitly paused
- **`COMPLETED`** - All tasks completed successfully
- **`FAILED`** - Workflow has failed tasks and no more work to do
- **`CANCELLED`** - Workflow was explicitly cancelled

### Workflow Status Determination

#### Primary Logic
**Location**: `/src/gleitzeit/core/workflow_progress_handler.py`
Method: `_calculate_workflow_status` (lines 190-255)

The workflow status is determined by:
1. **Terminal States** (lines 197-205):
   - If all tasks finished and some failed → `FAILED`
   - If all tasks completed successfully → `COMPLETED`

2. **Active States Priority** (lines 207-254):
   The workflow status reflects the highest priority state of its tasks:
   - If ANY task is paused → `PAUSED` (highest priority)
   - If ANY task is waiting for signal → `WAITING`
   - If ANY task is scheduled (timer) → `SCHEDULED`
   - If there are executing tasks or progress → `RUNNING`
   - If no tasks started → `PENDING` (lowest priority)

#### Status Update Triggers
**Location**: `/src/gleitzeit/core/workflow_progress_handler.py`
- Status recalculated on task completion (line 89)
- Status recalculated on task failure (line 119)
- Updates persisted when status changes (line 180)

#### Alternative Status Updates

**Task Queue** (`/src/gleitzeit/task_queue/task_queue.py`)
- Sets workflow to `FAILED` if critical task fails (line 405)
- Sets workflow to `COMPLETED` when all tasks done (line 407)

**Native Adapter** (`/src/gleitzeit/client/adapters/native.py`)
- `cancel_workflow`: Sets to `CANCELLED` (line 277)
- `pause_workflow`: Sets to `PAUSED` (line 331)
- `resume_workflow`: Sets to `RUNNING` (line 365)

## Event Flow for Status Changes

### Task Status Change Events
1. **Task Submission** → `PENDING`/`QUEUED`
2. **Queue Processing** → `VALIDATED` → `ROUTED`
3. **Execution Start** → `EXECUTING` → Event: `TASK_STARTED`
4. **Execution End**:
   - Success → `COMPLETED` → Event: `TASK_COMPLETED`
   - Failure → `FAILED` → Event: `TASK_FAILED`
   - Waiting → `WAITING`/`SCHEDULED`/`PAUSED`

### Workflow Status Change Events
1. **Workflow Submission** → `PENDING` → Event: `WORKFLOW_SUBMITTED`
2. **First Task Starts** → `RUNNING` → Event: `WORKFLOW_STARTED`
3. **Task Completions** → Status recalculated → Event: `WORKFLOW_PROGRESS`
4. **Final State**:
   - All tasks done → `COMPLETED` → Event: `WORKFLOW_COMPLETED`
   - Has failures → `FAILED` → Event: `WORKFLOW_FAILED`

## Status Persistence

### Task Status Storage
**Location**: `/src/gleitzeit/persistence/unified_redis.py`
- Task status stored in hash: `task:{task_id}` field `status`
- TaskResult status stored in hash: `task_result:{task_id}` field `status`

### Workflow Status Storage
**Location**: `/src/gleitzeit/persistence/unified_redis.py`
- Workflow status stored in hash: `workflow:{workflow_id}` field `status`
- Status snapshots stored for recovery

## Status Consistency Rules

### Task Level
- Tasks in `WAITING`, `SCHEDULED`, or `PAUSED` states are considered "active" not failed
- Only `COMPLETED` and `FAILED` are terminal states for progress calculation
- `SLEEPING` is deprecated but mapped to `PAUSED` for backward compatibility

### Workflow Level
- Workflow status reflects the highest priority state among its active tasks
- Priority order: `PAUSED` > `WAITING` > `SCHEDULED` > `RUNNING` > `PENDING`
- If ANY task is in a special state (paused/waiting/scheduled), workflow shows that state
- `WAITING` and `SCHEDULED` workflow statuses provide clarity about why workflow isn't progressing
- Workflow only reaches terminal state (`COMPLETED`/`FAILED`) when all tasks are done

## CLI Status Display

**Location**: `/src/gleitzeit/cli/main.py`
Status emoji mapping:
- ✅ `COMPLETED`
- ❌ `FAILED`
- 🔄 `RUNNING`
- ⏳ `PENDING`
- ⚠️ `CANCELLED`
- ⏸️ `PAUSED`

## API Status Responses

**Location**: `/src/gleitzeit/api/routes/workflows.py`
- GET `/workflows/{id}` returns current workflow status
- GET `/workflows/{id}/status` returns detailed status with task breakdown
- POST `/workflows/{id}/cancel` sets workflow to `CANCELLED` (line 130)
- Status changes trigger WebSocket events for real-time updates

**Location**: `/src/gleitzeit/api/routes/tasks.py`
- GET `/tasks/{id}` returns current task status
- POST `/tasks/{id}/cancel` sets task to `CANCELLED` (line 66)

## Best Practices

1. **Status Checks**: Always check both task and workflow status for complete picture
2. **Event Handling**: Subscribe to status change events for reactive behavior
3. **Error Recovery**: Use status to determine if retry/resume is appropriate
4. **Progress Tracking**: Combine status with completed/total counts for progress bars
5. **Waiting States**: Use `WAITING`/`SCHEDULED` to show why workflow isn't progressing