# Task Status Transitions Audit
Generated: 2025-09-16

## Executive Summary
This audit examines the task and workflow status transition system in Gleitzeit, documenting all status values, their meanings, transition rules, and identifying critical issues preventing proper workflow execution.

## 1. Task Status Values (TaskStatus Enum)

### Current Status List (from models.py - after commit 633f209):
```python
class TaskStatus(str, Enum):
    PENDING = "pending"           # Initial state, awaiting dependencies
    QUEUED = "queued"             # Dependencies met, ready for execution
    VALIDATED = "validated"        # Task params validated
    ROUTED = "routed"             # Assigned to provider
    EXECUTING = "executing"        # Currently running
    PAUSED = "paused"             # Task paused (reserved for pause functionality)
    SLEEPING = "sleeping"          # Deprecated - use PAUSED
    WAITING = "waiting"           # Waiting for signal
    SCHEDULED = "scheduled"        # Scheduled (timer)
    WAITING_SIGNAL = "waiting_signal"  # Deprecated - use WAITING
    COMPLETED = "completed"        # Successfully finished
    FAILED = "failed"             # Execution failed
    CANCELLED = "cancelled"        # User cancelled
    RETRY_PENDING = "retry_pending"  # Failed, awaiting retry
    REWOUND = "rewound"           # Rewound (rewind feature)
```

### Previous Status List (before commit 633f209):
```python
class TaskStatus(str, Enum):
    QUEUED = "queued"             # Was the initial state
    VALIDATED = "validated"
    ROUTED = "routed"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRY_PENDING = "retry_pending"
    # Note: No PENDING, PAUSED, WAITING, SCHEDULED, etc.
```

### Key Changes in Recent Refactor:
- **Added PENDING**: New initial state (previously tasks started in QUEUED)
- **Added PAUSED**: For pause/resume functionality
- **Added WAITING**: For signal waiting
- **Added SCHEDULED**: For timer-based tasks
- **Added deprecated statuses**: SLEEPING, WAITING_SIGNAL
- **Added REWOUND**: For rewind functionality
- **Changed default**: From QUEUED to PENDING

### Status Categories:
- **Initial States**: PENDING
- **Ready States**: QUEUED, VALIDATED, ROUTED
- **Active States**: EXECUTING
- **Blocked States**: PAUSED, WAITING, SCHEDULED
- **Terminal States**: COMPLETED, FAILED, CANCELLED
- **Recovery States**: RETRY_PENDING, REWOUND
- **Deprecated**: SLEEPING (→ PAUSED), WAITING_SIGNAL (→ WAITING)

## 2. Expected Status Transition Flow

### Normal Execution Path:
```
PENDING → QUEUED → VALIDATED → ROUTED → EXECUTING → COMPLETED
```

### Alternative Paths:
- **With Signals**: PENDING → WAITING → QUEUED → ... → COMPLETED
- **With Timers**: PENDING → SCHEDULED → QUEUED → ... → COMPLETED
- **With Failure**: EXECUTING → FAILED → RETRY_PENDING → QUEUED
- **With Pause**: EXECUTING → PAUSED → EXECUTING → COMPLETED

## 3. Detailed Status Transition Map

### Status: PENDING
**When Set:**
- Task creation during workflow submission
- After task rewind operation

**Where Set:**
1. `stateless_task_orchestrator.py:submit_workflow()` - Initial task creation
2. `workflow_loader.py:load_workflow()` - Creates tasks with PENDING
3. `models.py:Task.__init__()` - Default status for new tasks

**Should Transition To:** QUEUED (when dependencies met) or WAITING/SCHEDULED

---

### Status: QUEUED
**When Set:**
- Dependencies satisfied
- Task ready for execution
- After retry decision

**Where Set:**
1. `task_queue.py:enqueue_task()` - Main queueing point
2. `stateless_task_orchestrator.py:_handle_workflow_submitted()` - For ready tasks
3. `dependency_manager.py:check_dependencies()` - When deps satisfied
4. `retry_manager.py:schedule_retry()` - After retry delay

**Should Transition To:** VALIDATED → ROUTED → EXECUTING

**ACTUAL ISSUE:** Often skips directly to execution without proper transition

---

### Status: VALIDATED
**When Set:**
- Task parameters validated
- Provider requirements checked

**Where Set:**
1. **MISSING** - No code actually sets this status!
2. Should be in provider validation flow

**Should Transition To:** ROUTED

**CRITICAL ISSUE:** This status is never actually set in the codebase

---

### Status: ROUTED
**When Set:**
- Provider assigned
- Task routed to execution backend

**Where Set:**
1. `provider_hub.py:route_task()` - Should set but doesn't
2. **MISSING** - Not consistently set

**Should Transition To:** EXECUTING

**CRITICAL ISSUE:** This status is rarely set, causing transition gaps

---

### Status: EXECUTING
**When Set:**
- Task execution begins
- Provider starts processing

**Where Set (Supposed To):**
1. `task_executor.py:96` - `await self._update_task_status(task, TaskStatus.EXECUTING)`
2. `task_queue.py:217` - `fresh_task.status = TaskStatus.EXECUTING`
3. `stateless_dependency_manager.py:370` - `task.status = TaskStatus.EXECUTING`
4. `models.py:200` - `mark_started()` method
5. `persistence_handlers.py:141` - Event handler sets EXECUTING
6. `redis_pubsub_bus.py:297` - PubSub handler sets EXECUTING
7. `unified_persistence.py:1282` - Persistence layer sets EXECUTING

**Should Transition To:** COMPLETED, FAILED, or PAUSED

**CRITICAL ISSUE:** Multiple places try to set this, but timing issues cause it to be missed

---

### Status: PAUSED
**When Set:**
- User pauses task
- System pause for resource management

**Where Set:**
1. **NOT IMPLEMENTED** - Feature planned but not active
2. Would be in pause/resume handlers

**Should Transition To:** EXECUTING (on resume)

---

### Status: WAITING
**When Set:**
- Task waiting for signal
- External event required

**Where Set:**
1. `signal_provider.py:wait_for_signal()` - Sets WAITING status
2. `signals/stream_signal_manager.py` - Signal wait handling

**Should Transition To:** QUEUED (when signal received)

---

### Status: SCHEDULED
**When Set:**
- Timer scheduled
- Delayed execution

**Where Set:**
1. `timer_provider.py:schedule_timer()` - Timer scheduling
2. `timers/stream_timer_manager.py` - Timer management

**Should Transition To:** QUEUED (when timer expires)

---

### Status: COMPLETED
**When Set:**
- Task execution successful
- Result stored

**Where Set:**
1. `task_executor.py:_update_task_status()` - After successful execution
2. `atomic_operations.py:atomic_transition_task_status()` - Atomic transition
3. `models.py:mark_completed()` - Task model method
4. **PROBLEM:** Often set directly without proper transition

**Should Transition From:** EXECUTING only

**CRITICAL ISSUE:** Transition fails if not in EXECUTING state

---

### Status: FAILED
**When Set:**
- Task execution error
- Provider failure
- Timeout

**Where Set:**
1. `task_executor.py:execute()` - On exception
2. `provider error handlers` - Provider-specific failures
3. `timeout handlers` - Task timeout

**Should Transition To:** RETRY_PENDING or terminal

---

### Status: CANCELLED
**When Set:**
- User cancellation
- Workflow cancellation cascades

**Where Set:**
1. `workflow_manager.py:cancel_workflow()` - Cascade cancellation
2. API cancel endpoints

**Should Transition From:** Any non-terminal state

---

### Status: RETRY_PENDING
**When Set:**
- After failure with retries remaining
- Before retry delay

**Where Set:**
1. `retry_manager.py:handle_task_failure()` - Retry decision
2. `event_driven_retry_manager.py` - Event-based retry

**Should Transition To:** QUEUED (after retry delay)

## 4. Critical Issues Identified

### Issue 1: Missing Status Transition to EXECUTING
**Problem**: Tasks complete without proper EXECUTING status
**Impact**: atomic_transition_task_status fails with warning:
```
Task {task_id} not in expected status TaskStatus.EXECUTING
```
**Root Cause**: Multiple execution paths, inconsistent status updates

### Issue 2: Race Condition in Status Updates
**Problem**: Task completion may occur before EXECUTING status is set
**Locations**:
- Fast-executing tasks complete before status update
- Async status updates not synchronized

### Issue 3: Multiple Status Update Points
**Problem**: Status updates scattered across multiple components
**Components with EXECUTING updates**:
1. TaskExecutor
2. QueueManager
3. StatelessDependencyManager
4. Task model itself
5. PersistenceHandlers
6. RedisPubSubBus
7. UnifiedPersistence

### Issue 4: Inconsistent Status Checking
**Problem**: Different components check different status combinations
**Examples**:
- `redis_task_queue.py:212` checks: `[COMPLETED, EXECUTING, QUEUED]`
- `dependency_resolver.py:242` checks: `[EXECUTING, ROUTED]`
- `workflow_progress_handler.py:229` checks: `[EXECUTING, QUEUED]`

## 5. Workflow Status Values

### Complete List from models.py:
```python
class WorkflowStatus(str, Enum):
    PENDING = "pending"       # Initial state
    RUNNING = "running"       # Has active tasks
    WAITING = "waiting"       # Tasks waiting for signals
    SCHEDULED = "scheduled"   # Has scheduled tasks
    PAUSED = "paused"        # Workflow paused
    COMPLETED = "completed"   # All tasks complete
    FAILED = "failed"        # Workflow failed
    CANCELLED = "cancelled"   # User cancelled
```

## 6. Status Transition Enforcement

### Atomic Operations (atomic_operations.py)
The `atomic_transition_task_status` function enforces transitions:
```lua
-- Check current status matches expected
if current_status ~= ARGV[1] then
    return -2  -- Wrong status error
end
```

### Problems with Enforcement:
1. **Too Strict**: Requires exact status match
2. **No Flexibility**: Can't handle multiple valid source states
3. **Silent Failures**: Transitions fail without proper error handling

## 7. Status Persistence Issues

### Redis Storage
Tasks stored with status field in hash:
- Key: `gleitzeit:task:{task_id}`
- Field: `status`
- Value: String representation of status

### Issues:
1. **String vs Enum**: Inconsistent handling of status as string vs enum
2. **Case Sensitivity**: Some checks use `.value`, others use enum directly
3. **Missing Validation**: Status can be set to invalid values

## 8. Deprecated Status Values

### Deprecated Task Statuses:
- `SLEEPING` → Use `PAUSED` instead
- `WAITING_SIGNAL` → Use `WAITING` instead

### Impact:
- Legacy code may still reference deprecated values
- Migration path not clearly defined

## 9. Recommendations

### Immediate Fixes Required:

1. **Fix Status Transition to EXECUTING**
   - Ensure task status is set to EXECUTING before execution
   - Add status check before completion
   - Handle fast-executing tasks

2. **Centralize Status Management**
   - Create single StatusManager component
   - All status changes go through this manager
   - Enforce transition rules consistently

3. **Relax Atomic Transition Requirements**
   - Allow multiple valid source states
   - Add transition from QUEUED → COMPLETED for fast tasks
   - Handle edge cases gracefully

4. **Add Status Transition Logging**
   - Log all status changes with timestamp
   - Track which component initiated change
   - Help debug transition issues

### Long-term Improvements:

1. **State Machine Implementation**
   - Define valid transitions explicitly
   - Reject invalid transitions
   - Provide clear error messages

2. **Status Audit Trail**
   - Store status history
   - Track transition timestamps
   - Enable debugging of status issues

3. **Remove Deprecated Statuses**
   - Migrate away from SLEEPING and WAITING_SIGNAL
   - Update all references
   - Clean up codebase

## 10. Testing Requirements

### Test Cases Needed:
1. Fast task execution (completes before EXECUTING set)
2. Slow task execution (normal flow)
3. Task failure during status transition
4. Concurrent status updates
5. Recovery from invalid status

### Current Test Coverage:
- Limited status transition testing
- No race condition tests
- Missing edge case coverage

## Conclusion

The task status transition system has critical issues preventing proper workflow execution, particularly around the EXECUTING status requirement. The distributed nature of status updates across multiple components creates race conditions and inconsistencies. Immediate fixes are needed to ensure tasks can complete successfully, followed by architectural improvements to centralize and strengthen status management.