# Reconciliation Worker Audit Report

**Date**: 2025-10-12
**Auditor**: Claude Code
**Component**: `src/gleitzeit/workers/reconciliation_worker.py`
**Severity**: CRITICAL - Worker is non-functional

---

## Executive Summary

The reconciliation worker contains **5 critical bugs** that render it completely non-functional. The most severe issue is that the worker uses incorrect Redis key patterns throughout, causing it to never find any workflows to reconcile. Additionally, the worker lacks proper support for the `waiting` task status, which will cause workflows waiting for signals or timers to be incorrectly flagged and potentially failed.

**Impact**:
- Reconciliation worker cannot find workflows to reconcile (0% effectiveness)
- Stuck workflows are never detected or recovered
- Workflows waiting for signals/timers will be marked as "zombie" and failed after 10 minutes
- Task count inconsistencies are not properly detected when waiting tasks exist

---

## Bug #1: Incorrect Redis Key Patterns (CRITICAL)

### Location
- Line 358: `get_workflow()`
- Line 492: `recalculate_task_counts()`
- Line 525: `get_task()`
- Line 536: `mark_workflow_failed()`
- Line ~576: `mark_workflow_completed()` (not audited but likely affected)

### Issue
The reconciliation worker uses **wrong Redis key patterns** that don't match the actual keys used by other workers.

**Current (WRONG)**:
```python
# Line 358 - get_workflow()
key = f"{{shard:{shard}}}:workflow:status:{workflow_id}"

# Line 525 - get_task()
task_key = f"{{shard:{shard}}}:task:status:{task_id}"
```

**Expected (CORRECT)**:
```python
# Should use get_workflow_key() helper
key = default_sharding.get_workflow_key("state", workflow_id)
# Evaluates to: f"{{shard:{shard}}}:workflow:state:{workflow_id}"

# Should use get_task_key() helper
task_key = default_sharding.get_task_key(task_id, workflow_id)
# Evaluates to: f"{{shard:{shard}}}:task:{task_id}"
```

### Evidence
```python
# From dependency_worker.py line 190:
await self.redis.hset(
    default_sharding.get_workflow_key("state", workflow_id).encode(),  # ✅ CORRECT
    mapping={...}
)

# From reconciliation_worker.py line 358:
key = f"{{shard:{shard}}}:workflow:status:{workflow_id}"  # ❌ WRONG KEY
```

### Root Cause
The reconciliation worker was written before the key structure was standardized. It uses hardcoded key patterns instead of the helper functions (`get_workflow_key()`, `get_task_key()`).

### Impact
- `get_workflow()` returns `None` for all workflows → worker sees no workflows to reconcile
- `get_task()` returns `None` for all tasks → recalculation fails
- `mark_workflow_failed()` writes to wrong keys → status updates don't persist
- Reconciliation worker is **100% non-functional**

### Recommended Fix
Replace all hardcoded key patterns with the standard helper functions:

```python
# Fix get_workflow() - Line 358
key = default_sharding.get_workflow_key("state", workflow_id)

# Fix get_task() - Line 525
task_key = default_sharding.get_task_key(task_id, workflow_id)

# Fix mark_workflow_failed() - Line 536
workflow_key = default_sharding.get_workflow_key("state", workflow_id)

# Fix recalculate_task_counts() - Line 492
workflow_key = default_sharding.get_workflow_key("state", workflow_id)
```

---

## Bug #2: Missing `waiting_tasks` in Consistency Check

### Location
Line 392: `check_workflow_consistency()`

### Issue
The task count consistency check doesn't include `waiting_tasks` when verifying totals.

**Current**:
```python
# Line 392
total_accounted = completed_tasks + failed_tasks + running_tasks + pending_tasks
if total_accounted != total_tasks:
    inconsistencies.append("task_count_mismatch: ...")
```

**Expected**:
```python
# Lines 385-390 - need to add
waiting_tasks = get_int(b'waiting_tasks', 0)

# Line 392 - need to update
total_accounted = (completed_tasks + failed_tasks + running_tasks +
                   pending_tasks + waiting_tasks)
```

### Impact
- Any workflow with waiting tasks will be flagged as having `task_count_mismatch`
- Triggers unnecessary `recalculate_task_counts()` calls
- Performance degradation and unnecessary Redis operations
- False positive inconsistency reports

### Recommended Fix
```python
# Add to line 390
waiting_tasks = get_int(b'waiting_tasks', 0)

# Update line 392
total_accounted = (completed_tasks + failed_tasks + running_tasks +
                   pending_tasks + waiting_tasks)

# Update line 394 error message
inconsistencies.append(
    f"task_count_mismatch: total={total_tasks} but "
    f"accounted={total_accounted} "
    f"(completed={completed_tasks}, failed={failed_tasks}, "
    f"running={running_tasks}, pending={pending_tasks}, "
    f"waiting={waiting_tasks})"
)
```

---

## Bug #3: Zombie Detection Triggers on Waiting Workflows

### Location
Line 416: `check_workflow_consistency()`

### Issue
The zombie workflow detection doesn't account for `waiting_tasks`, causing workflows legitimately waiting for signals or timers to be marked as stalled.

**Current**:
```python
# Line 416
if running_tasks == 0 and pending_tasks == 0 and completed_tasks < total_tasks:
    # Check last activity and potentially mark as zombie
```

**Problem**: A workflow with tasks in WAITING status has:
- `running_tasks = 0` ✓
- `pending_tasks = 0` ✓ (waiting tasks aren't pending)
- `completed_tasks < total_tasks` ✓
- **Result**: Flagged as zombie after 10 minutes and marked as FAILED

### Impact
- Workflows waiting for signals will be incorrectly failed after 10 minutes
- Timer-based workflows will be killed prematurely
- Valid long-running workflows will be terminated
- This breaks the signal and timer functionality entirely

### Recommended Fix
```python
# Line 416 - Update condition
if running_tasks == 0 and pending_tasks == 0 and waiting_tasks == 0 and completed_tasks < total_tasks:
    # Now only triggers if truly no active work
```

---

## Bug #4: `waiting_tasks` Not Extracted from Workflow State

### Location
Lines 385-390: `check_workflow_consistency()`

### Issue
The consistency checker reads all task counts from Redis except `waiting_tasks`.

**Current**:
```python
# Lines 385-390
total_tasks = get_int(b'total_tasks', 0)
completed_tasks = get_int(b'completed_tasks', 0)
failed_tasks = get_int(b'failed_tasks', 0)
running_tasks = get_int(b'running_tasks', 0)
pending_tasks = get_int(b'pending_tasks', 0)
# ❌ Missing: waiting_tasks
```

**Note**: Interestingly, `recalculate_task_counts()` at line 500 DOES write `waiting_tasks`:
```python
# Line 500
b'waiting_tasks': str(counts.get('waiting', 0)).encode(),
```

### Impact
- The worker writes `waiting_tasks` but never reads it
- Consistency checks use an incomplete view of workflow state
- Related to Bugs #2 and #3

### Recommended Fix
```python
# Add after line 390
waiting_tasks = get_int(b'waiting_tasks', 0)
```

---

## Bug #5: Workflow Index Not Populated by Other Workers

### Location
Line 280: `scan_running_workflows()` expects `{shard:N}:workflows:by_status:running` sorted set

### Issue
The reconciliation worker scans for workflows using a sorted set index that was never populated by other workers.

**Expected behavior**:
```python
# Line 280 - reconciliation_worker.py
key = f"{{shard:{shard}}}:workflows:by_status:running"
workflow_ids = await self.redis.zrange(key.encode(), offset, limit)
```

**Actual behavior**:
- `dependency_worker.py` line 199 sets `b"status": b"running"` in workflow state HASH
- But **never** adds the workflow ID to the sorted set index
- Result: `zrange` returns empty list, so no workflows are scanned

### Root Cause
When the dependency worker was refactored to use consolidated workflow state (`:workflow:state:` key), the sorted set indexing was not implemented.

### Partial Fix Applied
In the current session, added code to `dependency_worker.py` lines 218-224:
```python
# Add workflow to running index for reconciliation worker
shard = default_sharding.get_shard(workflow_id)
running_index_key = f"{{shard:{shard}}}:workflows:by_status:running"
await self.redis.zadd(
    running_index_key.encode(),
    {workflow_id.encode(): datetime.utcnow().timestamp()}
)
```

### Impact
- Reconciliation worker finds 0 workflows (even if Bug #1 is fixed)
- New workflows (after fix) will be indexed, but old "stuck" workflows won't be
- Need migration/backfill for existing workflows

### Recommended Fix
1. Keep the fix in `dependency_worker.py` (already applied)
2. Add similar indexing when workflow status changes:
   - When marking workflow as failed
   - When marking workflow as completed
3. Create a migration script to backfill existing workflows:

```python
# Migration pseudocode
for each workflow in Redis:
    status = workflow.status
    shard = get_shard(workflow_id)
    if status == "running":
        zadd f"{shard:{shard}}:workflows:by_status:running", workflow_id, timestamp
    elif status == "failed":
        zadd f"{shard:{shard}}:workflows:by_status:failed", workflow_id, timestamp
    elif status == "completed":
        zadd f"{shard:{shard}}:workflows:by_status:completed", workflow_id, timestamp
```

---

## Bug #6: Status Transition Logic Missing (NEW FINDING)

### Location
Throughout the codebase - no code exists to transition workflows to "waiting" status

### Issue
Even with all above bugs fixed, there's no logic to set workflow status to `"waiting"` when all running tasks transition to WAITING.

**Current State**:
- Workflows are initialized with `status: "running"` (dependency_worker.py:199)
- Tasks can transition to `status: "waiting"` (task_execution_worker.py:591)
- But workflow status **never** changes to `"waiting"`

### Impact
- UI shows "running" instead of "waiting" (user's reported Issue #1)
- Workflows appear active when they're actually idle
- Monitoring/observability issues

### Recommended Fix
Add status transition logic in the reconciliation worker:

```python
# In check_workflow_consistency() or as a new check
if running_tasks == 0 and pending_tasks == 0 and waiting_tasks > 0:
    # Workflow should be in "waiting" status
    current_status = workflow.get(b'status', b'unknown').decode()
    if current_status == 'running':
        inconsistencies.append(
            f"status_should_be_waiting: workflow has {waiting_tasks} waiting tasks "
            f"but status is '{current_status}'"
        )
```

Then in `fix_workflow_state()`:
```python
if status_should_be_waiting:
    await self.mark_workflow_waiting(workflow_id, shard)
```

And implement:
```python
async def mark_workflow_waiting(self, workflow_id: str, shard: int):
    """Mark workflow as waiting for signals/timers"""
    workflow_key = default_sharding.get_workflow_key("state", workflow_id)

    await self.redis.hset(
        workflow_key.encode(),
        mapping={
            b'status': b'waiting',
            b'updated_at': datetime.utcnow().isoformat().encode()
        }
    )

    # Move from running to waiting index (if we want separate index)
    running_key = f"{{shard:{shard}}}:workflows:by_status:running"
    await self.redis.zrem(running_key.encode(), workflow_id.encode())
```

---

## Additional Observations

### 1. Inconsistent Error Handling
- `get_workflow()` returns `None` on error (line 364)
- `get_task()` returns `None` on error (line 531)
- Callers don't always check for `None` before accessing

### 2. Missing Workflow State Consistency
The workflow uses two different key patterns in different places:
- `:workflow:state:` (used by dependency_worker, task_execution_worker)
- `:workflow:status:` (used by reconciliation_worker - WRONG)

### 3. Task Status Enum Not Used Consistently
- Some code uses `TaskStatus.WAITING` enum
- Reconciliation worker uses string `'waiting'` directly
- Should standardize on enum usage

---

## Recommended Fix Priority

### Priority 1: Critical (Blocks All Functionality)
1. **Bug #1**: Fix all Redis key patterns to use helper functions
2. **Bug #5**: Ensure workflow sorted set indexing is working

### Priority 2: High (Breaks Signal/Timer Features)
3. **Bug #3**: Fix zombie detection to account for waiting tasks
4. **Bug #4**: Extract `waiting_tasks` from workflow state
5. **Bug #2**: Include `waiting_tasks` in consistency check

### Priority 3: Medium (UX Issue)
6. **Bug #6**: Implement workflow status transition to "waiting"

---

## Testing Recommendations

After fixes are applied, test the following scenarios:

1. **Basic Reconciliation**
   - Submit workflow
   - Verify it appears in `{shard:N}:workflows:by_status:running`
   - Verify reconciliation worker can find and process it

2. **Waiting Task Handling**
   - Submit workflow with signal/wait task
   - Task transitions to WAITING
   - Verify workflow status changes to "waiting"
   - Verify workflow NOT marked as zombie
   - Wait > 10 minutes, verify workflow still alive

3. **Task Count Consistency**
   - Submit workflow with mixed task states (running, waiting, pending)
   - Verify no false `task_count_mismatch` inconsistencies
   - Verify `recalculate_task_counts()` produces correct counts

4. **Stuck Workflow Recovery**
   - Create a workflow stuck in "running" with no active tasks
   - Verify reconciliation worker detects and fixes it
   - Verify appropriate action taken (mark failed, mark completed, etc.)

5. **Key Migration**
   - Run backfill script for existing workflows
   - Verify old workflows now appear in sorted set indices
   - Verify reconciliation worker processes them

---

## Files Requiring Changes

1. `src/gleitzeit/workers/reconciliation_worker.py` - Fix all 6 bugs
2. `src/gleitzeit/workers/dependency_worker.py` - Already fixed (sorted set indexing)
3. `src/gleitzeit/workers/task_execution_worker.py` - Need to update `waiting_tasks` counter (simple hincrby)
4. Migration script (new file) - Backfill sorted set indices

---

## Estimated Effort

- **Bug Fixes**: 2-3 hours
- **Testing**: 2-3 hours
- **Migration Script**: 1-2 hours
- **Total**: 5-8 hours

---

## Bug #7: Incomplete Task Status Handling in `recalculate_task_counts`

### Location
Lines 475-489: `recalculate_task_counts()`

### Issue
The function only tracks 5 task statuses but the system defines 17 different statuses.

**Currently tracked statuses** (line 475-481):
```python
counts = {
    'pending': 0,
    'running': 0,
    'completed': 0,
    'failed': 0,
    'waiting': 0
}
```

**All TaskStatus enum values** (from models.py:18-36):
- PENDING = "pending" ✓ (tracked)
- QUEUED = "queued" ❌
- ROUTED = "routed" ❌
- VALIDATING = "validating" ❌
- EXECUTING = "executing" ❌ (probably equivalent to "running")
- PAUSED = "paused" ❌
- SLEEPING = "sleeping" ❌ (deprecated but may exist)
- WAITING = "waiting" ✓ (tracked)
- SCHEDULED = "scheduled" ❌
- WAITING_SIGNAL = "waiting_signal" ❌ (deprecated but may exist)
- COMPLETED = "completed" ✓ (tracked)
- FAILED = "failed" ✓ (tracked)
- CANCELLED = "cancelled" ❌
- RETRY_PENDING = "retry_pending" ❌
- REWOUND = "rewound" ❌
- SKIPPED = "skipped" ❌ (tracked in workflow state but NOT in recalculate)
- BLOCKED = "blocked" ❌ (tracked in workflow state but NOT in recalculate)

**Workflow state tracks** (from dependency_worker.py:205-211):
- `total_tasks`
- `completed_tasks` ✓ (recalculated)
- `failed_tasks` ✓ (recalculated)
- `skipped_tasks` ❌ (NOT recalculated)
- `blocked_tasks` ❌ (NOT recalculated)
- `waiting_tasks` ✓ (recalculated)
- `pending_tasks` ✓ (recalculated)
- `running_tasks` ✓ (recalculated)

### Impact
- Tasks with status `blocked` or `skipped` are not counted during recalculation
- Line 488: `if status in counts:` will be False for most task statuses
- These tasks become "lost" - not counted anywhere
- Task count mismatches will persist even after recalculation
- Workflow state becomes permanently inconsistent

### Example Scenario
1. Workflow has 10 tasks
2. 5 completed, 3 blocked, 2 skipped
3. Recalculation counts: `completed=5, blocked=0, skipped=0`
4. Total accounted = 5, but total_tasks = 10
5. Mismatch persists, triggering infinite recalculation loops

### Recommended Fix
```python
# Line 475-481 - Update counts dictionary
counts = {
    'pending': 0,
    'running': 0,     # Also count 'executing', 'queued', 'routed', 'validating'
    'completed': 0,
    'failed': 0,
    'waiting': 0,     # Also count 'waiting_signal', 'scheduled'
    'blocked': 0,
    'skipped': 0,
    'cancelled': 0,   # New
    'paused': 0,      # New
    'other': 0        # Catch-all for unknown statuses
}

# Line 487-489 - Update counting logic
status = task.get(b'status', b'pending').decode() if isinstance(task.get(b'status'), bytes) else task.get('status', 'pending')

# Map statuses to workflow counters
if status in ['pending']:
    counts['pending'] += 1
elif status in ['running', 'executing', 'queued', 'routed', 'validating']:
    counts['running'] += 1
elif status in ['waiting', 'waiting_signal', 'scheduled']:
    counts['waiting'] += 1
elif status == 'completed':
    counts['completed'] += 1
elif status == 'failed':
    counts['failed'] += 1
elif status == 'blocked':
    counts['blocked'] += 1
elif status == 'skipped':
    counts['skipped'] += 1
elif status == 'cancelled':
    counts['cancelled'] += 1
elif status in ['paused', 'sleeping']:
    counts['paused'] += 1
else:
    counts['other'] += 1
    logger.warning(f"Unknown task status '{status}' for task {task_id}")

# Line 496-501 - Update hset to include all counters
await self.redis.hset(
    workflow_key.encode(),
    mapping={
        b'pending_tasks': str(counts['pending']).encode(),
        b'running_tasks': str(counts['running']).encode(),
        b'completed_tasks': str(counts['completed']).encode(),
        b'failed_tasks': str(counts['failed']).encode(),
        b'waiting_tasks': str(counts['waiting']).encode(),
        b'blocked_tasks': str(counts['blocked']).encode(),
        b'skipped_tasks': str(counts['skipped']).encode(),
        b'updated_at': datetime.utcnow().isoformat().encode()
    }
)
```

---

## Bug #8: Inconsistent Stream Key Patterns for Events

### Location
- Line 561: `mark_workflow_failed()` emits to `{shard:N}:workflow:failed`
- Line 601: `mark_workflow_completed()` emits to `{shard:N}:workflow:completed`

### Issue
The reconciliation worker uses hardcoded stream keys that don't match the pattern used by other workers.

**Reconciliation worker** (lines 561, 601):
```python
# WRONG - missing workflow_id in stream key
f"{{shard:{shard}}}:workflow:failed".encode()
f"{{shard:{shard}}}:workflow:completed".encode()
```

**Dependency worker** (line 626):
```python
# CORRECT - includes workflow_id for proper sharding
default_sharding.get_stream_key("workflow:completed", workflow_id).encode()
# Produces: {shard:N}:workflow:completed:{workflow_id}
```

### Root Cause
Reconciliation worker hardcodes stream keys instead of using `get_stream_key()` helper.

### Impact
- Events emitted by reconciliation worker go to wrong streams
- WorkflowMonitorWorker expects streams with workflow_id suffix
- Reconciliation-triggered completions/failures are not processed
- Parent workflows waiting for child workflows never get notified
- Workflow completion/failure events are lost

### Recommended Fix
```python
# Line 560-561 - Fix mark_workflow_failed()
await self.redis.xadd(
    default_sharding.get_stream_key("workflow:failed", workflow_id).encode(),
    {
        b'workflow_id': workflow_id.encode(),
        b'error': reason.encode(),
        b'reconciliation': b'true',
        b'timestamp': datetime.utcnow().isoformat().encode()
    }
)

# Line 600-601 - Fix mark_workflow_completed()
await self.redis.xadd(
    default_sharding.get_stream_key("workflow:completed", workflow_id).encode(),
    {
        b'workflow_id': workflow_id.encode(),
        b'status': b'completed',
        b'reconciliation': b'true',
        b'timestamp': datetime.utcnow().isoformat().encode()
    }
)
```

---

## Bug #9: Missing `blocked_tasks` and `skipped_tasks` in Consistency Check

### Location
Lines 385-390: `check_workflow_consistency()` doesn't read these fields

### Issue
Similar to Bug #4, the consistency checker doesn't read `blocked_tasks` and `skipped_tasks` from workflow state.

**Currently reads**:
```python
total_tasks = get_int(b'total_tasks', 0)
completed_tasks = get_int(b'completed_tasks', 0)
failed_tasks = get_int(b'failed_tasks', 0)
running_tasks = get_int(b'running_tasks', 0)
pending_tasks = get_int(b'pending_tasks', 0)
# Missing: waiting_tasks, blocked_tasks, skipped_tasks
```

### Impact
- Bug #2 is even worse - consistency check missing 3 counters, not just 1
- Total accounted calculation is always wrong when blocked/skipped tasks exist
- False positive mismatch errors on every reconciliation

### Recommended Fix
```python
# Add after line 390
waiting_tasks = get_int(b'waiting_tasks', 0)
blocked_tasks = get_int(b'blocked_tasks', 0)
skipped_tasks = get_int(b'skipped_tasks', 0)

# Update line 392
total_accounted = (completed_tasks + failed_tasks + running_tasks +
                   pending_tasks + waiting_tasks + blocked_tasks + skipped_tasks)
```

---

## Bug #10: `check_workflow_consistency` Doesn't Use WorkflowStatus Enum

### Location
Line 317: `if status != 'running':`

### Issue
Uses hardcoded string instead of enum, inconsistent with other workers.

**Current**:
```python
status = workflow.get('status', '').decode() if isinstance(workflow.get('status'), bytes) else workflow.get('status', '')
if status != 'running':
    return
```

**Should be**:
```python
from ..core.models import WorkflowStatus

status_bytes = workflow.get(b'status', b'unknown')
status_str = status_bytes.decode() if isinstance(status_bytes, bytes) else str(status_bytes)

if status_str != WorkflowStatus.RUNNING.value:
    return
```

### Impact
- Minor: Works but inconsistent with codebase standards
- If WorkflowStatus enum values change, this code breaks
- Harder to maintain

---

## Bug #11: Race Condition in `mark_workflow_failed` and `mark_workflow_completed`

### Location
Lines 534-573 (`mark_workflow_failed`) and Lines 575-613 (`mark_workflow_completed`)

### Issue
Multiple operations on workflow state without atomicity:
1. Update workflow state HASH
2. Remove from running index
3. Add to failed/completed index
4. Emit event

If worker crashes between steps, workflow ends up in inconsistent state.

### Example Failure Scenario
1. `mark_workflow_failed` updates workflow state to "failed" (line 539-547)
2. Worker crashes before removing from running index (line 553)
3. Result: Workflow has `status: failed` but is still in `:workflows:by_status:running` sorted set
4. Next reconciliation scan picks it up again, but line 318 skips it (`if status != 'running': return`)
5. Workflow stuck in limbo - marked failed but indexed as running

### Impact
- Workflows can be in multiple status indices simultaneously
- Sorted set indices become polluted with workflows that shouldn't be there
- Reconciliation scan wastes time on workflows that shouldn't be scanned

### Recommended Fix
Use Lua script for atomicity:

```python
async def mark_workflow_failed(self, workflow_id: str, shard: int, reason: str):
    """Mark workflow as failed atomically"""
    workflow_key = default_sharding.get_workflow_key("state", workflow_id)
    running_key = f"{{shard:{shard}}}:workflows:by_status:running"
    failed_key = f"{{shard:{shard}}}:workflows:by_status:failed"

    lua_script = """
    -- Update workflow state
    redis.call('hset', KEYS[1],
        'status', ARGV[1],
        'error', ARGV[2],
        'failed_at', ARGV[3],
        'updated_at', ARGV[3])

    -- Move between indices atomically
    redis.call('zrem', KEYS[2], ARGV[4])
    redis.call('zadd', KEYS[3], ARGV[5], ARGV[4])

    return 1
    """

    try:
        now = datetime.utcnow()
        await self.redis.eval(
            lua_script.encode(),
            3,
            workflow_key.encode(),
            running_key.encode(),
            failed_key.encode(),
            WorkflowStatus.FAILED.value.encode(),
            reason.encode(),
            now.isoformat().encode(),
            workflow_id.encode(),
            str(now.timestamp()).encode()
        )

        # Emit event after atomic update succeeds
        await self.redis.xadd(
            default_sharding.get_stream_key("workflow:failed", workflow_id).encode(),
            {
                b'workflow_id': workflow_id.encode(),
                b'error': reason.encode(),
                b'reconciliation': b'true',
                b'timestamp': now.isoformat().encode()
            }
        )

        logger.info(f"Marked workflow {workflow_id} as failed: {reason}")

    except Exception as e:
        logger.error(f"Failed to mark workflow {workflow_id} as failed: {e}")
```

---

## Bug #12: No Handling for `SCHEDULED` Workflow Status

### Location
Throughout - no code handles workflows in "scheduled" state

### Issue
`WorkflowStatus` enum defines `SCHEDULED = "scheduled"` (models.py:44) but reconciliation worker doesn't handle it.

### Impact
- Workflows with scheduled tasks should have status "scheduled"
- Reconciliation worker will try to scan them as "running" (won't find them)
- Or if they are marked "scheduled", reconciliation won't scan them at all
- Need separate check for workflows that should be "scheduled"

### Recommended Fix
Add scheduled status handling similar to waiting status:

```python
# In check_workflow_consistency()
if running_tasks == 0 and pending_tasks == 0 and waiting_tasks == 0 and scheduled_tasks > 0:
    inconsistencies.append(
        f"status_should_be_scheduled: workflow has {scheduled_tasks} scheduled tasks "
        f"but status is 'running'"
    )

# In fix_workflow_state()
if status_should_be_scheduled:
    await self.mark_workflow_scheduled(workflow_id, shard)
```

---

## Summary of All Bugs

| # | Severity | Component | Description |
|---|----------|-----------|-------------|
| 1 | CRITICAL | Key Patterns | Wrong Redis keys throughout (`:status:` instead of `:state:`) |
| 2 | HIGH | Consistency Check | Missing `waiting_tasks` in total accounted calculation |
| 3 | HIGH | Zombie Detection | Doesn't account for `waiting_tasks`, kills waiting workflows |
| 4 | HIGH | Consistency Check | `waiting_tasks` not extracted from workflow state |
| 5 | CRITICAL | Indexing | Workflow sorted set index never populated |
| 6 | MEDIUM | Status Transitions | No logic to transition workflow to "waiting" status |
| 7 | CRITICAL | Task Counting | Only tracks 5 of 17 task statuses, loses blocked/skipped tasks |
| 8 | HIGH | Event Streams | Wrong stream key patterns, events go to wrong streams |
| 9 | HIGH | Consistency Check | Missing `blocked_tasks` and `skipped_tasks` in total calculation |
| 10 | LOW | Code Quality | Hardcoded strings instead of enum values |
| 11 | MEDIUM | Atomicity | Race conditions in workflow state transitions |
| 12 | MEDIUM | Scheduled Status | No handling for scheduled workflow status |

---

## Conclusion

The reconciliation worker has **12 major bugs** that make it completely non-functional:

**Critical Issues** (Blocks All Functionality):
- Bug #1: Wrong Redis keys prevent finding any workflows
- Bug #5: Index never populated means nothing to scan
- Bug #7: Task recalculation loses most task statuses

**High-Priority Issues** (Breaks Core Features):
- Bugs #2, #3, #4, #9: Waiting tasks not properly handled
- Bug #8: Events emitted to wrong streams

**Medium-Priority Issues** (Data Consistency):
- Bugs #6, #11, #12: Missing status transitions and race conditions

The fixes require:
1. Systematic replacement of all hardcoded key patterns with helper functions
2. Complete rewrite of task status counting logic
3. Addition of missing status transition logic
4. Atomicity improvements with Lua scripts
5. Stream key pattern fixes

**Estimated Total Effort**: 12-16 hours (up from 5-8 hours in original estimate)

---

## Bug #13: Incorrect Task Key Pattern in `get_task()`

### Location
Line 525: `get_task()`

### Issue
The `get_task()` method uses the wrong key pattern that differs from `get_task_key()` helper.

**Current (reconciliation_worker.py:525)**:
```python
task_key = f"{{shard:{shard}}}:task:status:{task_id}"
```

**Expected (from sharding.py:81-93)**:
```python
# get_task_key signature:
def get_task_key(self, task_id: str, workflow_id: str) -> str:
    shard = self.get_shard(workflow_id)
    return f"{{shard:{shard}}}:task:status:{task_id}"
```

### Problem
While the key pattern is technically correct, the reconciliation worker constructs it manually instead of using the helper. More critically, **the `get_task()` method doesn't have access to workflow_id** to call the helper properly.

### Impact
- Inconsistent with codebase standards
- If task key pattern changes, this breaks
- Cannot use the standard helper function

### Root Cause
The `get_task()` method signature is:
```python
async def get_task(self, task_id: str, workflow_id: str, shard: int) -> Optional[Dict]:
```

It receives `workflow_id` but doesn't use the helper. Should be:
```python
task_key = default_sharding.get_task_key(task_id, workflow_id)
```

### Recommended Fix
```python
# Line 525
task_key = default_sharding.get_task_key(task_id, workflow_id)
```

---

## Bug #14: Missing Index Cleanup When Workflows Transition Status

### Location
Lines 549-557 (`mark_workflow_failed`) and Lines 589-597 (`mark_workflow_completed`)

### Issue
The worker adds workflows to `failed` and `completed` indices but never cleans up old indices.

**Current behavior**:
```python
# Line 553-556
await self.redis.zrem(running_key.encode(), workflow_id.encode())
await self.redis.zadd(
    failed_key.encode(),
    {workflow_id.encode(): datetime.utcnow().timestamp()}
)
```

**Problem**: If a workflow was previously indexed elsewhere (e.g., in `waiting` or `scheduled` index), it remains there.

### Impact
- Workflows can appear in multiple status indices simultaneously
- Memory leak - indices grow without bounds
- Reconciliation scans duplicate workflows
- Sorted sets never shrink

### Recommended Fix
Use Lua script to atomically clean up all indices:

```python
async def mark_workflow_failed(self, workflow_id: str, shard: int, reason: str):
    """Mark workflow as failed and clean up indices"""

    lua_script = """
    -- Update workflow state
    redis.call('hset', KEYS[1],
        'status', ARGV[1],
        'error', ARGV[2],
        'failed_at', ARGV[3],
        'updated_at', ARGV[3])

    -- Remove from all possible status indices
    for i=2,#KEYS do
        redis.call('zrem', KEYS[i], ARGV[4])
    end

    -- Add to failed index
    redis.call('zadd', KEYS[2], ARGV[5], ARGV[4])

    return 1
    """

    workflow_key = default_sharding.get_workflow_key("state", workflow_id)
    failed_key = f"{{shard:{shard}}}:workflows:by_status:failed"
    running_key = f"{{shard:{shard}}}:workflows:by_status:running"
    waiting_key = f"{{shard:{shard}}}:workflows:by_status:waiting"
    scheduled_key = f"{{shard:{shard}}}:workflows:by_status:scheduled"
    completed_key = f"{{shard:{shard}}}:workflows:by_status:completed"

    await self.redis.eval(
        lua_script.encode(),
        6,  # number of keys
        workflow_key.encode(),
        failed_key.encode(),
        running_key.encode(),
        waiting_key.encode(),
        scheduled_key.encode(),
        completed_key.encode(),
        WorkflowStatus.FAILED.value.encode(),
        reason.encode(),
        datetime.utcnow().isoformat().encode(),
        workflow_id.encode(),
        str(datetime.utcnow().timestamp()).encode()
    )
```

---

## Bug #15: Task Set Key Pattern Mismatch

### Location
Line 514: `get_workflow_task_ids()`

### Issue
Uses key pattern `{shard:N}:workflow:tasks:{workflow_id}` which is not used anywhere else in the codebase.

**Current**:
```python
tasks_key = f"{{shard:{shard}}}:workflow:tasks:{workflow_id}"
```

**Question**: Where is this set populated?

### Investigation
Searching the codebase shows **no worker populates this set**. The dependency worker uses:
- `{shard:N}:workflow:state:{workflow_id}` (hash) - stores `total_tasks` count
- `{shard:N}:task:{task_id}` (hash) - individual task data

But there's **no sorted set or set tracking all task IDs for a workflow**.

### Impact
- `get_workflow_task_ids()` returns empty list for all workflows
- `recalculate_task_counts()` always calculates 0 for all counters
- Task count recalculation is completely broken
- Bug #7 is even worse - even if we fix the status counting, we get no tasks

### Root Cause
The architecture changed to use consolidated workflow state, but the reconciliation worker still assumes the old architecture with a task ID set.

### Recommended Fix
The reconciliation worker needs to reconstruct task IDs from workflow data:

```python
async def get_workflow_task_ids(self, workflow_id: str, shard: int) -> List[str]:
    """Get all task IDs for a workflow from workflow data"""
    try:
        # Get workflow data which contains the original task definitions
        data_key = default_sharding.get_workflow_key("data", workflow_id)
        workflow_data_json = await self.redis.get(data_key.encode())

        if not workflow_data_json:
            logger.warning(f"No workflow data found for {workflow_id}")
            return []

        workflow_data = json.loads(workflow_data_json.decode())
        tasks = workflow_data.get('tasks', [])

        # Extract task IDs
        task_ids = []
        for task in tasks:
            task_id = task.get('id')
            if task_id:
                task_ids.append(task_id)

        return task_ids

    except Exception as e:
        logger.error(f"Failed to get task IDs for workflow {workflow_id}: {e}")
        return []
```

---

## Bug #16: No Handling for Workflow Status Indices Besides "running"

### Location
Line 280-296: `scan_running_workflows()`

### Issue
The reconciliation worker only scans workflows in `by_status:running` index but ignores:
- `by_status:waiting` - workflows waiting for signals/timers
- `by_status:scheduled` - workflows with scheduled tasks
- `by_status:failed` - may need cleanup or archival
- `by_status:completed` - may need cleanup or archival

### Impact
- Workflows stuck in WAITING status never get reconciled
- Scheduled workflows never checked
- Failed/completed workflows accumulate forever
- Only "running" workflows get any attention

### Recommended Fix
Add separate scan methods for each status:

```python
async def reconcile_all_shards(self):
    """Scan and reconcile all assigned shards"""
    logger.debug(f"Starting reconciliation scan for {len(self.assigned_shards)} shards")

    for shard in self.assigned_shards:
        try:
            async with self.acquire_shard_lock(shard) as lock:
                # Reconcile running workflows
                await self.reconcile_shard(shard, status='running')

                # Reconcile waiting workflows (may be stuck)
                await self.reconcile_shard(shard, status='waiting')

                # Clean up old completed workflows (optional)
                await self.cleanup_old_workflows(shard, status='completed', ttl=86400)

                # Clean up old failed workflows (optional)
                await self.cleanup_old_workflows(shard, status='failed', ttl=86400)

        except LockAcquisitionError:
            logger.debug(f"Could not acquire lock for shard {shard}, skipping")
            continue
        except Exception as e:
            logger.error(f"Error reconciling shard {shard}: {e}", exc_info=True)
            await self.log_worker_error("shard_reconciliation_failed", e, shard=shard)

    logger.debug("Reconciliation scan completed")

async def reconcile_shard(self, shard: int, status: str = 'running'):
    """Reconcile workflows with specific status on a shard"""
    offset = 0
    shard_workflows_scanned = 0

    while True:
        # Scan for workflows with given status
        workflow_ids = await self.scan_workflows_by_status(shard, status, offset, self.batch_size)

        if not workflow_ids:
            break

        # Reconcile workflows concurrently
        tasks = []
        for workflow_id in workflow_ids:
            task = asyncio.create_task(
                self._reconcile_workflow_with_semaphore(workflow_id, shard)
            )
            tasks.append(task)

        await asyncio.gather(*tasks, return_exceptions=True)

        shard_workflows_scanned += len(workflow_ids)
        offset += self.batch_size

    logger.debug(f"Shard {shard} status={status} reconciliation: {shard_workflows_scanned} workflows")

async def scan_workflows_by_status(
    self, shard: int, status: str, offset: int, limit: int
) -> List[str]:
    """Scan for workflows with specific status on a shard"""
    key = f"{{shard:{shard}}}:workflows:by_status:{status}"

    try:
        workflow_ids = await self.redis.zrange(
            key.encode(),
            offset,
            offset + limit - 1
        )
        return [wf_id.decode() for wf_id in workflow_ids]
    except Exception as e:
        logger.error(f"Failed to scan {status} workflows on shard {shard}: {e}")
        return []

async def cleanup_old_workflows(self, shard: int, status: str, ttl: int):
    """Remove workflows from index after TTL expires"""
    key = f"{{shard:{shard}}}:workflows:by_status:{status}"
    cutoff = datetime.utcnow().timestamp() - ttl

    try:
        # Remove workflows older than TTL
        removed = await self.redis.zremrangebyscore(
            key.encode(),
            0,
            cutoff
        )

        if removed > 0:
            logger.info(f"Cleaned up {removed} old {status} workflows from shard {shard}")

    except Exception as e:
        logger.error(f"Failed to cleanup old {status} workflows on shard {shard}: {e}")
```

---

## Bug #17: `updated_at` Timestamp Not Updated in All Workflow Operations

### Location
Multiple locations in reconciliation_worker.py

### Issue
The `get_last_workflow_activity()` method relies on `updated_at` timestamp (line 626), but not all workflow state updates include this field.

**Updates that set `updated_at`**:
- `recalculate_task_counts()` - line 501 ✓
- `mark_workflow_failed()` - line 545 ✓
- `mark_workflow_completed()` - line 585 ✓

**Updates that DON'T set `updated_at`**:
- When checking workflow consistency (none)
- When fixing workflow state (depends on fix type)

**External workers that may not update `updated_at`**:
- `dependency_worker.py` - Need to check all hset operations
- `task_execution_worker.py` - Need to check task status updates

### Impact
- Zombie detection may use stale timestamps
- Workflows appear inactive when they're actually progressing
- False positive zombie detections

### Recommended Fix
1. Add `updated_at` to ALL workflow state updates
2. Create a helper method to ensure consistency:

```python
async def update_workflow_state(
    self,
    workflow_id: str,
    updates: Dict[bytes, bytes]
) -> None:
    """Update workflow state with automatic timestamp"""
    workflow_key = default_sharding.get_workflow_key("state", workflow_id)

    # Always include updated_at
    updates[b'updated_at'] = datetime.utcnow().isoformat().encode()

    await self.redis.hset(workflow_key.encode(), mapping=updates)
```

---

## Bug #18: No Protection Against Concurrent Reconciliation of Same Workflow

### Location
Lines 301-354: `reconcile_workflow()`

### Issue
While the worker uses shard-level locks (line 200), multiple workers could still reconcile the same workflow if:
1. Workflow changes status during reconciliation
2. Worker crashes mid-reconciliation and another picks it up
3. Inconsistency fixes trigger multiple reconciliations

### Impact
- Race conditions in workflow state updates
- Duplicate event emissions
- Conflicting state modifications
- Wasted resources

### Recommended Fix
Add workflow-level locks for reconciliation:

```python
async def reconcile_workflow(self, workflow_id: str, shard: int):
    """Reconcile a single workflow with per-workflow locking"""

    # Try to acquire workflow-specific lock
    lock_key = f"{{shard:{shard}}}:reconciliation:workflow:{workflow_id}"
    lock_value = f"{self.config.worker_id}:{uuid.uuid4()}"

    acquired = await self.redis.set(
        lock_key.encode(),
        lock_value.encode(),
        nx=True,
        ex=30  # Short TTL for workflow-level lock
    )

    if not acquired:
        logger.debug(f"Workflow {workflow_id} already being reconciled, skipping")
        return

    try:
        self.workflows_scanned += 1

        # ... existing reconciliation logic ...

    finally:
        # Release workflow lock
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        await self.redis.eval(
            lua_script.encode(),
            1,
            lock_key.encode(),
            lock_value.encode()
        )
```

---

## Updated Bug Summary

| # | Severity | Component | Description |
|---|----------|-----------|-------------|
| 1 | CRITICAL | Key Patterns | Wrong Redis keys throughout (`:status:` instead of `:state:`) |
| 2 | HIGH | Consistency Check | Missing `waiting_tasks` in total accounted calculation |
| 3 | HIGH | Zombie Detection | Doesn't account for `waiting_tasks`, kills waiting workflows |
| 4 | HIGH | Consistency Check | `waiting_tasks` not extracted from workflow state |
| 5 | CRITICAL | Indexing | Workflow sorted set index never populated |
| 6 | MEDIUM | Status Transitions | No logic to transition workflow to "waiting" status |
| 7 | CRITICAL | Task Counting | Only tracks 5 of 17 task statuses, loses blocked/skipped tasks |
| 8 | HIGH | Event Streams | Wrong stream key patterns, events go to wrong streams |
| 9 | HIGH | Consistency Check | Missing `blocked_tasks` and `skipped_tasks` in total calculation |
| 10 | LOW | Code Quality | Hardcoded strings instead of enum values |
| 11 | MEDIUM | Atomicity | Race conditions in workflow state transitions |
| 12 | MEDIUM | Scheduled Status | No handling for scheduled workflow status |
| 13 | LOW | Code Quality | Task key not using helper function |
| 14 | HIGH | Index Cleanup | Workflows never removed from old status indices |
| 15 | CRITICAL | Task Discovery | Task ID set never populated, cannot find tasks |
| 16 | MEDIUM | Reconciliation Scope | Only scans "running" workflows, ignores other statuses |
| 17 | MEDIUM | Timestamp Management | `updated_at` not set consistently |
| 18 | LOW | Concurrency | No workflow-level locking |

---

## Critical Path to Functionality

To make the reconciliation worker functional, these bugs MUST be fixed in order:

### Phase 1: Basic Functionality (Blocks Everything)
1. **Bug #1**: Fix all key patterns to use `get_workflow_key("state", ...)`
2. **Bug #5**: Ensure workflow indices are populated
3. **Bug #15**: Fix task ID discovery (read from workflow data)
4. **Bug #13**: Use helper for task keys

**Result**: Worker can now find workflows and their tasks

### Phase 2: Correct Counting (Fixes Data Corruption)
5. **Bug #7**: Fix task status counting to include all statuses
6. **Bug #2, #4, #9**: Extract and include all task counters in consistency check
7. **Bug #14**: Clean up old indices to prevent duplicates

**Result**: Task counts are accurate, no data corruption

### Phase 3: Waiting Task Support (Prevents Killing Valid Workflows)
8. **Bug #3**: Fix zombie detection for waiting workflows
9. **Bug #6**: Implement workflow status transition to "waiting"

**Result**: Workflows with waiting tasks function correctly

### Phase 4: Event Propagation (Enables Completion Flow)
10. **Bug #8**: Fix stream key patterns for events

**Result**: Workflow completion/failure events reach monitoring workers

### Phase 5: Polish (Robustness)
11. **Bug #11, #18**: Add atomicity and locking
12. **Bug #16**: Scan all workflow statuses
13. **Bug #17**: Consistent timestamp management
14. **Bugs #10, #12**: Code quality and enum usage

---

## Final Estimated Effort

- **Phase 1** (Critical): 4-5 hours
- **Phase 2** (Data Integrity): 3-4 hours
- **Phase 3** (Waiting Support): 2-3 hours
- **Phase 4** (Events): 1-2 hours
- **Phase 5** (Polish): 2-3 hours
- **Testing & Validation**: 4-6 hours
- **Total**: 16-23 hours

---

## Conclusion

The reconciliation worker audit has identified **18 major bugs** across critical, high, medium, and low severity levels. The worker is currently **100% non-functional** due to:

1. Wrong Redis key patterns preventing any data access
2. Missing workflow indices preventing workflow discovery
3. Broken task ID discovery preventing task counting
4. Incomplete status tracking losing workflow state

The recommended fix pathway follows a phased approach over 16-23 hours to restore full functionality.

---

## Bug #19: Stateful Metrics Violate Stateless Design Principle

### Location
Lines 104-108: `__init__()`
Lines throughout: metric increments

### Issue
The reconciliation worker maintains in-memory state via metrics counters, making it stateful and non-idempotent.

**Current (Lines 104-108)**:
```python
# Metrics
self.workflows_scanned = 0
self.inconsistencies_found = 0
self.workflows_fixed = 0
self.scan_errors = 0
```

**Used throughout the code**:
```python
# Line 307
self.workflows_scanned += 1

# Line 325
self.inconsistencies_found += len(inconsistencies)

# Line 338
self.workflows_fixed += 1

# Line 181
self.scan_errors += 1
```

### Why This Is A Problem

**1. State Lost On Restart**
- Worker crashes → all metrics reset to 0
- No historical visibility into reconciliation activity
- Cannot track trends over time

**2. Not Distributed**
- Multiple worker instances each have their own counters
- No way to aggregate metrics across workers
- Total reconciliation activity is unknown

**3. Violates Stateless Pattern**
Unlike stream-based workers that use Redis consumer groups for state, the reconciliation worker:
- Has no state recovery mechanism
- Cannot resume where it left off (though it doesn't need to)
- Metrics are ephemeral and non-persistent

**4. Already Have Better Observability**
The worker uses `LoggingMixin` for structured logging:
```python
# Line 327-333
await self.log_worker_warning(
    "workflow_inconsistency_detected",
    f"Workflow {workflow_id} has {len(inconsistencies)} inconsistencies",
    workflow_id=workflow_id,
    shard=shard,
    inconsistencies=inconsistencies
)
```

These logs are:
- Persisted to Redis
- Queryable and aggregatable
- Provide more detail than simple counters
- Distributed across all workers

### Impact
- **Minor functional issue** - metrics are "nice to have" not critical
- **Architectural inconsistency** - other workers are stateless
- **Misleading metrics** - only show current worker instance activity
- **Complexity** - extra code that duplicates logging functionality

### Recommended Fix

**Remove all in-memory metrics and rely on structured logging:**

```python
# Before (Lines 104-108) - REMOVE
# Metrics
self.workflows_scanned = 0
self.inconsistencies_found = 0
self.workflows_fixed = 0
self.scan_errors = 0

# After - NO METRICS

# Before (Lines 162-175) - REMOVE metric logging
await self.log_worker_info(
    "reconciliation_cycle_completed",
    f"Scanned {self.workflows_scanned} workflows, "
    f"found {self.inconsistencies_found} inconsistencies, "
    f"fixed {self.workflows_fixed} workflows in {scan_duration:.2f}s",
    scan_duration=scan_duration,
    workflows_scanned=self.workflows_scanned,
    inconsistencies_found=self.inconsistencies_found,
    workflows_fixed=self.workflows_fixed
)

# After - Just log cycle completion
await self.log_worker_info(
    "reconciliation_cycle_completed",
    f"Reconciliation cycle completed in {scan_duration:.2f}s",
    scan_duration=scan_duration
)
```

**Remove all metric increments:**

```python
# Before (Line 307)
self.workflows_scanned += 1
# After - REMOVE (logged elsewhere if needed)

# Before (Line 325)
self.inconsistencies_found += len(inconsistencies)
# After - REMOVE (already logged in log_worker_warning)

# Before (Line 338)
self.workflows_fixed += 1
# After - REMOVE (already logged in log_worker_info)

# Before (Line 181)
self.scan_errors += 1
# After - REMOVE (already logged in log_worker_error)
```

### Querying Metrics From Logs

With structured logging, you can aggregate metrics by querying Redis logs:

```python
# Count workflows scanned
logs_key = "{shard:0}:logs:reconciliation_worker"
scanned_count = await redis.llen(logs_key.encode())

# Or query specific event types
# Example: Count all "workflow_reconciled" events in last hour
async def count_reconciliations(redis, since: datetime) -> int:
    logs = await redis.lrange(logs_key.encode(), 0, -1)
    count = 0
    for log_entry in logs:
        log = json.loads(log_entry.decode())
        if log['event'] == 'workflow_reconciled':
            timestamp = datetime.fromisoformat(log['timestamp'])
            if timestamp >= since:
                count += 1
    return count
```

### Benefits of This Approach

1. **Truly Stateless** - Worker has no mutable state
2. **Restartable** - Can restart anytime without losing data
3. **Distributed** - Metrics aggregatable across all workers
4. **Historical** - Logs persist beyond worker lifetime
5. **Detailed** - More context than simple counters
6. **Idempotent** - Rescanning workflows is safe
7. **Simpler Code** - Less state to manage

### Alternative: Redis-Backed Metrics (Not Recommended)

If you really want real-time metrics, store them in Redis:

```python
async def increment_metric(self, metric_name: str, amount: int = 1):
    """Store metrics in Redis for persistence"""
    # All workers write to same metric keys
    metric_key = f"{{shard:0}}:metrics:reconciliation:{metric_name}"
    await self.redis.hincrby(metric_key.encode(), b'count', amount)
    await self.redis.hset(
        metric_key.encode(),
        b'last_updated',
        datetime.utcnow().isoformat().encode()
    )

# Usage
await self.increment_metric('workflows_scanned')
```

**However, this is not recommended because:**
- Adds Redis operations to hot path
- Still duplicates information already in logs
- More complex than just querying logs
- Timer-based reconciliation doesn't need real-time metrics

---

## Revised Bug Summary

| # | Severity | Component | Description |
|---|----------|-----------|-------------|
| 1 | CRITICAL | Key Patterns | Wrong Redis keys throughout (`:status:` instead of `:state:`) |
| 2 | HIGH | Consistency Check | Missing `waiting_tasks` in total accounted calculation |
| 3 | HIGH | Zombie Detection | Doesn't account for `waiting_tasks`, kills waiting workflows |
| 4 | HIGH | Consistency Check | `waiting_tasks` not extracted from workflow state |
| 5 | CRITICAL | Indexing | Workflow sorted set index never populated |
| 6 | MEDIUM | Status Transitions | No logic to transition workflow to "waiting" status |
| 7 | CRITICAL | Task Counting | Only tracks 5 of 17 task statuses, loses blocked/skipped tasks |
| 8 | HIGH | Event Streams | Wrong stream key patterns, events go to wrong streams |
| 9 | HIGH | Consistency Check | Missing `blocked_tasks` and `skipped_tasks` in total calculation |
| 10 | LOW | Code Quality | Hardcoded strings instead of enum values |
| 11 | MEDIUM | Atomicity | Race conditions in workflow state transitions |
| 12 | MEDIUM | Scheduled Status | No handling for scheduled workflow status |
| 13 | LOW | Code Quality | Task key not using helper function |
| 14 | HIGH | Index Cleanup | Workflows never removed from old status indices |
| 15 | CRITICAL | Task Discovery | Task ID set never populated, cannot find tasks |
| 16 | MEDIUM | Reconciliation Scope | Only scans "running" workflows, ignores other statuses |
| 17 | MEDIUM | Timestamp Management | `updated_at` not set consistently |
| 18 | LOW | Concurrency | No workflow-level locking |
| 19 | LOW | Stateful Design | In-memory metrics make worker stateful and non-idempotent |

---

## Revised Critical Path to Functionality

To make the reconciliation worker functional, these bugs MUST be fixed in order:

### Phase 1: Basic Functionality (Blocks Everything)
1. **Bug #1**: Fix all key patterns to use `get_workflow_key("state", ...)`
2. **Bug #5**: Ensure workflow indices are populated
3. **Bug #15**: Fix task ID discovery (read from workflow data)
4. **Bug #13**: Use helper for task keys
5. **Bug #19**: Remove in-memory metrics

**Result**: Worker can now find workflows and their tasks, is truly stateless

### Phase 2: Correct Counting (Fixes Data Corruption)
6. **Bug #7**: Fix task status counting to include all statuses
7. **Bug #2, #4, #9**: Extract and include all task counters in consistency check
8. **Bug #14**: Clean up old indices to prevent duplicates

**Result**: Task counts are accurate, no data corruption

### Phase 3: Waiting Task Support (Prevents Killing Valid Workflows)
9. **Bug #3**: Fix zombie detection for waiting workflows
10. **Bug #6**: Implement workflow status transition to "waiting"

**Result**: Workflows with waiting tasks function correctly

### Phase 4: Event Propagation (Enables Completion Flow)
11. **Bug #8**: Fix stream key patterns for events

**Result**: Workflow completion/failure events reach monitoring workers

### Phase 5: Polish (Robustness)
12. **Bug #11, #18**: Add atomicity and locking
13. **Bug #16**: Scan all workflow statuses
14. **Bug #17**: Consistent timestamp management
15. **Bugs #10, #12**: Code quality and enum usage

---

## Final Revised Estimated Effort

- **Phase 1** (Critical): 4-5 hours (includes removing metrics)
- **Phase 2** (Data Integrity): 3-4 hours
- **Phase 3** (Waiting Support): 2-3 hours
- **Phase 4** (Events): 1-2 hours
- **Phase 5** (Polish): 2-3 hours
- **Testing & Validation**: 4-6 hours
- **Total**: 16-23 hours

---

## Revised Conclusion

The reconciliation worker audit has identified **19 major bugs** across critical, high, medium, and low severity levels. The worker is currently **100% non-functional** due to:

1. Wrong Redis key patterns preventing any data access
2. Missing workflow indices preventing workflow discovery
3. Broken task ID discovery preventing task counting
4. Incomplete status tracking losing workflow state
5. Stateful design with in-memory metrics

The recommended fix pathway follows a phased approach over 16-23 hours to restore full functionality and achieve a truly stateless, idempotent design.

### Key Architectural Improvement

**After fixes, the reconciliation worker will be:**
- ✅ **Stateless** - No in-memory state, can restart anytime
- ✅ **Idempotent** - Safe to rescan workflows multiple times
- ✅ **Distributed** - Multiple instances coordinate via Redis locks
- ✅ **Observable** - All activity tracked via structured logs
- ✅ **Consistent** - Uses standard key patterns and helpers throughout
