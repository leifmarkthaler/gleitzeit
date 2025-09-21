# Component-Level Task Status Usage Report
Generated: 2025-09-16

## Executive Summary
This report documents how task status is actually used across all components in the Gleitzeit system, revealing significant discrepancies between the 15-status model and actual implementation.

## Component Analysis

### 1. TaskQueue (task_queue/task_queue.py)
**Primary Status Manager for Queue Operations**

#### Sets These Statuses:
- `PENDING` (lines 123, 338, 720) - When dependencies not satisfied
- `QUEUED` (lines 135, 330, 593, 601, 768) - When ready for execution
- `EXECUTING` (line 217) - When task picked up from queue
- `COMPLETED` (line 212) - Fixing inconsistent states
- `CANCELLED` (lines 261, 508) - On cancellation
- `FAILED` (line 293) - On task failure

#### Checks These Statuses:
- Line 110: `existing_task.status == TaskStatus.QUEUED`
- Line 195: `fresh_task.status != TaskStatus.QUEUED`
- Line 235/238: `dep_task.status != TaskStatus.COMPLETED`
- Line 257: `task.status not in [TaskStatus.QUEUED, TaskStatus.PENDING]`
- Line 275: `task.status == TaskStatus.COMPLETED`
- Line 317: `fresh_task.status != TaskStatus.PENDING`
- Line 361: `fresh_task.status == TaskStatus.COMPLETED`
- Line 371: `fresh_task.status == TaskStatus.FAILED`
- Line 383: `fresh_task.status not in [TaskStatus.CANCELLED]`
- Line 579/592: `fresh_task.status == TaskStatus.PENDING`
- Line 836: `task.status == TaskStatus.QUEUED`

**NEVER SETS: VALIDATED, ROUTED, PAUSED, WAITING, SCHEDULED, RETRY_PENDING, REWOUND**

---

### 2. TaskExecutor (core/task_executor.py)
**Primary Execution Manager**

#### Sets These Statuses:
- `EXECUTING` (line 96) - Via _update_task_status before execution
- `FAILED` (line 295) - Via _update_task_status on error

#### Key Method:
```python
async def _update_task_status(self, task, status, started_at=None, completed_at=None):
    task.status = status
    if started_at:
        task.started_at = started_at
    if completed_at:
        task.completed_at = completed_at
    if self.persistence:
        await self.persistence.save_task(task)
```

**ISSUE**: TaskExecutor sets EXECUTING but doesn't set COMPLETED directly - relies on events or providers

---

### 3. StatelessDependencyManager (core/stateless_dependency_manager.py)
**Dependency Resolution Component**

#### Sets These Statuses:
- `PENDING` (line 338) - When task initialized
- `EXECUTING` (line 370) - When execution starts
- `COMPLETED` (line 409) - On completion
- `FAILED` (line 468) - On failure

**PROBLEM**: Duplicates status management with other components, causing race conditions

---

### 4. PersistenceHandlers (events/persistence_handlers.py)
**Event-Driven Status Updates**

#### Sets These Statuses:
- `COMPLETED` (line 56) - On TASK_COMPLETED event
- `FAILED` (line 109) - On TASK_FAILED event
- `EXECUTING` (line 141) - On TASK_STARTED event

**ISSUE**: Event-based updates may arrive out of order or be missed

---

### 5. RedisPubSubBus (events/redis_pubsub_bus.py)
**Message Bus Status Updates**

#### Sets These Statuses:
- `EXECUTING` (line 297) - During task execution
- `COMPLETED` (line 307) - On task completion

**PROBLEM**: Another duplicate path for status updates

---

### 6. StatelessTaskOrchestrator (core/stateless_task_orchestrator.py)
**Workflow Orchestration**

#### Sets These Statuses:
- `FAILED` (line 345) - When TaskExecutor fails

#### Checks These Statuses:
- Line 299: `current_task.status == TaskStatus.COMPLETED`
- Line 467: `task.status == TaskStatus.COMPLETED`

---

### 7. EventDrivenRetryManager (core/event_driven_retry_manager.py)
**Retry Logic Manager**

#### Sets These Statuses:
- `FAILED` (line 134) - Permanent failure
- `RETRY_PENDING` (line 172) - Scheduling retry
- `QUEUED` (line 249) - Re-queuing for retry

#### Checks These Statuses:
- Line 244: `task.status != TaskStatus.RETRY_PENDING`
- Line 300: `task.status == TaskStatus.FAILED`
- Line 302: `task.status not in [TaskStatus.COMPLETED, TaskStatus.CANCELLED]`

**ACTUALLY USES RETRY_PENDING!**

---

### 8. ReplayManager (replay/manager.py)
**Replay and Recovery**

#### Sets These Statuses:
- `PENDING` (lines 226, 331, 392, 435) - Reset for replay
- `COMPLETED` (line 386) - Mark as already completed

#### Checks These Statuses:
- Line 365: `task.status in [TaskStatus.COMPLETED, TaskStatus.SKIPPED]`
- Line 367: `task.status == TaskStatus.FAILED`

**NOTE**: References non-existent SKIPPED status!

---

### 9. Client Adapters (client/adapters/)
**API and Native Client Interfaces**

#### API Adapter Checks:
- Line 713: `task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]`

#### Native Adapter:
- Sets `CANCELLED` (line 317)
- Checks same terminal states (line 316, 693)

---

### 10. Persistence Layers (persistence/)
**Storage Components**

#### UnifiedPersistence:
- Sets `EXECUTING` (line 1282) - But checks for string values "pending", "ready"
- Checks mixed string/enum values throughout

**CRITICAL ISSUE**: Inconsistent string vs enum handling!

---

## Status Usage Summary

### Actually Used Statuses (11 of 15):
1. **PENDING** ✅ - Widely used as initial state
2. **QUEUED** ✅ - Core queue status
3. **EXECUTING** ✅ - Set by multiple components (race condition!)
4. **COMPLETED** ✅ - Terminal success state
5. **FAILED** ✅ - Terminal failure state
6. **CANCELLED** ✅ - User cancellation
7. **RETRY_PENDING** ✅ - Used by retry manager
8. **WAITING** ⚠️ - Set by signal provider only
9. **SCHEDULED** ⚠️ - Set by timer provider only
10. **PAUSED** ❌ - Defined but never used
11. **REWOUND** ❌ - Defined but never used

### Never Set Statuses (4 of 15):
1. **VALIDATED** ❌ - No component sets this
2. **ROUTED** ❌ - No component sets this
3. **SLEEPING** ❌ - Deprecated
4. **WAITING_SIGNAL** ❌ - Deprecated

### Status Transition Reality

#### Actual Flow (Most Common):
```
PENDING → QUEUED → EXECUTING → COMPLETED/FAILED
```

#### What Should Happen:
```
PENDING → QUEUED → VALIDATED → ROUTED → EXECUTING → COMPLETED/FAILED
```

#### Fast Task Problem:
```
PENDING → QUEUED → [execution] → COMPLETED (never hits EXECUTING!)
```

## Critical Issues Found

### 1. Multiple Components Set EXECUTING
- TaskQueue (line 217)
- TaskExecutor (line 96)
- StatelessDependencyManager (line 370)
- PersistenceHandlers (line 141)
- RedisPubSubBus (line 297)
- UnifiedPersistence (line 1282)

**Result**: Race conditions and timing issues

### 2. String vs Enum Inconsistency
- UnifiedPersistence checks for string "pending", "ready"
- Some components use TaskStatus.PENDING.value
- Others use TaskStatus.PENDING directly

### 3. Missing Status Transitions
- VALIDATED never set
- ROUTED never set
- Tasks jump from QUEUED to EXECUTING

### 4. Fast Task Completion Issue
- Tasks complete before EXECUTING is set
- atomic_transition_task_status fails because task not in EXECUTING

### 5. Duplicate Status Management
- At least 6 different components manage status
- No single source of truth
- Event-based and direct updates conflict

## Recommendations

### Immediate Fixes:
1. **Centralize Status Updates**
   - Create single StatusManager component
   - All status changes go through this manager
   - Remove duplicate status updates from other components

2. **Fix Fast Task Issue**
   - Allow QUEUED → COMPLETED transition
   - Or ensure EXECUTING is set synchronously before execution

3. **Remove Unused Statuses**
   - Remove VALIDATED, ROUTED from enum
   - Or implement them properly in the flow

4. **Standardize String/Enum Usage**
   - Always use TaskStatus enum, never strings
   - Fix persistence layer string checks

### Architecture Changes:
1. **Single Status Update Path**
   - TaskExecutor should be sole status manager during execution
   - Events should trigger status checks, not updates

2. **Synchronous Status Updates**
   - Status must be updated before async operations
   - Prevent race conditions

3. **Status Transition Validation**
   - Implement state machine with valid transitions
   - Reject invalid status changes

## Conclusion

The task status system has evolved beyond its original design, with 15 defined statuses but only 11 actually used. Multiple components compete to manage status, creating race conditions and inconsistencies. The system needs consolidation to a single status management component with clear transition rules and proper handling of fast-executing tasks.