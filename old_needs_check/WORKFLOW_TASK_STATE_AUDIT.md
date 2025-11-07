# Workflow and Task State Transition Audit

**Date**: 2025-10-12
**Issue**: Workflow status not transitioning correctly from "running" to "waiting"/"scheduled"

---

## Current Problems

1. **Negative task counters**: `running_tasks` and `pending_tasks` going negative
2. **Status not transitioning**: Workflows stay "running" even when only timer/signal tasks remain
3. **Counter mismatch**: Incrementing one counter (e.g., `scheduled_tasks`) when task becomes ready, but decrementing a different counter (`running_tasks`) when it completes

---

## Task State Lifecycle

### Task States (from TaskStatus enum)
- **PENDING**: Task waiting for dependencies
- **QUEUED**: Task queued for execution
- **ROUTED**: Task routed to handler
- **VALIDATING**: Task being validated
- **EXECUTING**: Task actively executing
- **WAITING**: Task waiting for signal
- **SCHEDULED**: Task waiting for timer
- **COMPLETED**: Task finished successfully
- **FAILED**: Task finished with error
- **CANCELLED**: Task cancelled
- **BLOCKED**: Task blocked by validation
- **SKIPPED**: Task skipped due to validation

### Task State Transitions

```
PENDING (task created, has dependencies)
  ↓ (dependencies satisfied)
PENDING → Ready for execution
  ↓ (emitted to task:ready stream)
  ↓
  ├→ EXECUTING (python/http/file tasks)
  ├→ SCHEDULED (timer tasks)
  └→ WAITING (signal tasks)
  ↓
COMPLETED/FAILED/CANCELLED
```

---

## Workflow Task Counters

### Current Counters in workflow:state
- `total_tasks`: Total number of tasks in workflow
- `completed_tasks`: Tasks that finished successfully
- `failed_tasks`: Tasks that failed
- `pending_tasks`: Tasks waiting for dependencies
- `running_tasks`: Tasks actively executing
- `waiting_tasks`: Tasks waiting for signals
- `scheduled_tasks`: Tasks waiting for timers
- `blocked_tasks`: Tasks blocked by validation
- `skipped_tasks`: Tasks skipped by validation

### Counter Invariant
**MUST ALWAYS BE TRUE**:
```
total_tasks = completed_tasks + failed_tasks + pending_tasks +
              running_tasks + waiting_tasks + scheduled_tasks +
              blocked_tasks + skipped_tasks + cancelled_tasks
```

---

## Current Implementation Issues

### Issue 1: Counter Update Locations

**Where counters are updated**:

1. **Dependency Worker - Initial submission** ([dependency_worker.py:217-240](src/gleitzeit/workers/dependency_worker.py#L217-L240)):
   - Sets initial `pending_tasks`, `running_tasks`, `waiting_tasks`, `scheduled_tasks`
   - ✅ Uses task protocol to determine initial counter

2. **Dependency Worker - Task completion** ([dependency_worker.py:278-290](src/gleitzeit/workers/dependency_worker.py#L278-L290)):
   - Increments `completed_tasks`
   - Decrements `running_tasks` (ALWAYS, regardless of task type) ❌
   - **PROBLEM**: Decrements wrong counter for timer/signal tasks

3. **Dependency Worker - Ready tasks** ([dependency_worker.py:559-596](src/gleitzeit/workers/dependency_worker.py#L559-L596)):
   - Increments counter based on task protocol (running/waiting/scheduled)
   - Decrements `pending_tasks`
   - ✅ Correctly uses protocol to determine counter

4. **Dependency Worker - Task failure** ([dependency_worker.py:378-423](src/gleitzeit/workers/dependency_worker.py#L378-L423)):
   - Increments `failed_tasks`
   - Decrements `running_tasks` (ALWAYS) ❌
   - **PROBLEM**: Same issue as completion

### Issue 2: Who Manages Task Status?

**Current reality**:
- Timer tasks: Timer worker sets status to `scheduled`
- Signal tasks: Signal worker sets status to `waiting`
- Other tasks: Task execution worker sets status to `executing`

**But dependency worker doesn't know this!**
- Dependency worker increments counter when emitting to `task:ready` stream
- But actual task status is set later by the protocol-specific worker
- Creates race condition and mismatch

### Issue 3: No Single Source of Truth

**Multiple workers update task counters**:
- Dependency worker: On ready, completion, failure
- Reconciliation worker: Recalculates from scratch periodically
- No coordination between them

---

## Workflow Status Lifecycle

### Workflow States (from WorkflowStatus enum)
- **PENDING**: Workflow submitted but not started
- **RUNNING**: Has actively executing tasks
- **WAITING**: All remaining tasks waiting for signals
- **SCHEDULED**: All remaining tasks waiting for timers
- **COMPLETED**: All tasks finished successfully
- **FAILED**: Has failed tasks
- **CANCELLED**: Workflow cancelled

### Workflow Status Transitions

```
PENDING (workflow submitted)
  ↓ (initial tasks emitted)
RUNNING (has active/executing tasks)
  ↓
  ├→ WAITING (only signal tasks remain)
  ├→ SCHEDULED (only timer tasks remain)
  └→ RUNNING (back to running when tasks activate)
  ↓
COMPLETED/FAILED/CANCELLED
```

### When Should Status Transition?

**To RUNNING**:
- `running_tasks > 0` OR `pending_tasks > 0`

**To WAITING**:
- `running_tasks == 0` AND `pending_tasks == 0` AND `waiting_tasks > 0` AND `scheduled_tasks == 0`

**To SCHEDULED**:
- `running_tasks == 0` AND `pending_tasks == 0` AND `scheduled_tasks > 0` AND `waiting_tasks == 0`

**To COMPLETED**:
- `completed_tasks == total_tasks` (ignoring skipped/blocked)

**To FAILED**:
- `failed_tasks > 0` (hard fail policy)

---

## Root Cause Analysis

### The Core Problem

**Task lifecycle has 3 phases**:
1. **Ready**: Task emitted to task:ready stream (dependency worker)
2. **Processing**: Task picked up by protocol worker (timer/signal/execution worker)
3. **Complete**: Task finishes (protocol worker emits completion event)

**Counter updates happen in phases 1 and 3, but...**:
- Phase 1: Dependency worker increments counter based on protocol
- Phase 3: Dependency worker decrements counter based on... protocol? ❌ NO, it always decrements `running_tasks`

**The mismatch**:
```
Timer task lifecycle:
  Ready: scheduled_tasks++ (correct)
  Complete: running_tasks-- (WRONG! Should be scheduled_tasks--)

Result: scheduled_tasks = 1, running_tasks = -1
```

---

## Proposed Solutions

### Option 1: Store Task Type with Task State ⭐ **RECOMMENDED**

**Store the counter type with each task when it becomes ready**:

```python
# When task becomes ready
await redis.hset(
    task_key,
    b"counter_type",
    counter_field  # b"running_tasks" | b"scheduled_tasks" | b"waiting_tasks"
)

# When task completes
counter_type = await redis.hget(task_key, b"counter_type")
await redis.hincrby(workflow_state_key, counter_type, -1)
```

**Pros**:
- Simple and reliable
- Single source of truth
- No race conditions
- Counters guaranteed to balance

**Cons**:
- Slight memory overhead per task

### Option 2: Let Protocol Workers Manage Counters

**Move counter management to protocol workers**:
- Timer worker increments/decrements `scheduled_tasks`
- Signal worker increments/decrements `waiting_tasks`
- Task execution worker increments/decrements `running_tasks`

**Pros**:
- Protocol workers know their task type
- More distributed responsibility

**Cons**:
- More complex coordination
- Multiple workers touching same counters
- Harder to debug counter mismatches

### Option 3: Real-time Reconciliation

**Don't track counters - compute them on demand**:
- Query all task statuses when needed
- No counters to get out of sync

**Pros**:
- No counter mismatch possible
- Always accurate

**Cons**:
- Performance overhead
- More Redis queries

### Option 4: Reconciliation Worker Only

**Remove all counter updates from dependency worker**:
- Only reconciliation worker manages counters
- Runs frequently (every 5-10 seconds)

**Pros**:
- Single source of truth
- No coordination needed

**Cons**:
- Delayed status transitions
- Not real-time

---

## CRITICAL DISCOVERY: Task Status Already Stored!

**Task states are already in Redis**: `{shard:X}:task:status:{task_id}`

Fields include:
- `status`: "completed", "scheduled", "waiting", "executing", "failed"
- `workflow_id`
- `result`
- `completed_at`

**We can read the task's status to know which counter to decrement!**

---

## Revised Recommendation

**Read task status from Redis on completion to determine counter**

No need to store extra data - task status already tells us what counter was used.

---

## Revised Implementation Plan

1. Update `handle_task_completion` to read task status and decrement appropriate counter
2. Update `handle_task_failure` similarly
3. Remove hacky protocol-based logic
4. Test with timer/signal workflows
5. Verify counters balance

---

## Files to Modify

1. **src/gleitzeit/workers/dependency_worker.py**:
   - `handle_task_completion`: Read task status, map to counter, decrement correct one
   - `handle_task_failure`: Same approach

2. **Tests**:
   - Verify counter balance after operations
