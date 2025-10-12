# Key Findings - Workflow Status Investigation

**Date**: 2025-10-12
**Status**: Investigation complete, solution identified but not implemented

---

## What We Discovered

### 1. Task States ARE Stored in Redis
- Location: `{shard:X}:task:status:{task_id}`
- Contains: status, result, completion time, handler info
- Task statuses: `completed`, `scheduled`, `waiting`, `failed`

### 2. EXECUTING Status is Never Used
- `TaskStatus.EXECUTING` exists in enum but is never set
- Tasks go directly from no status → `completed` (or `scheduled`/`waiting`)
- This means we can't use task status to determine which counter to decrement

### 3. Counters Are Fundamentally Flawed
- Trying to maintain `running_tasks`, `scheduled_tasks`, `waiting_tasks` counters
- Counters are derived state that gets out of sync with actual task states
- Counter increment/decrement mismatch causes negative values

### 4. Hard Fail Policy Assumes "running" Status
- Currently only triggers when `current_status == "running"`
- Should trigger for ANY active state: running, waiting, scheduled, paused, pending
- **Fixed**: Changed check to `if current_status not in ["completed", "failed", "cancelled"]`

### 5. Reconciliation Worker Already Computes Status Correctly
- Queries all task states and counts them
- Doesn't rely on counters - computes from source of truth
- Runs periodically (every 60 seconds)

---

## The Core Problem

**Architecture flaw**: Maintaining derived state (counters) separately from source state (task statuses in Redis).

**Why it breaks**:
1. Dependency worker increments counter based on task protocol when task becomes ready
2. Dependency worker decrements `running_tasks` when task completes (regardless of actual type)
3. Mismatch: increment `scheduled_tasks`, decrement `running_tasks` → negative values

**Why we can't easily fix it**:
- Task status doesn't help (regular tasks never get intermediate status)
- Protocol lookup requires extra queries
- Still fragile and error-prone

---

## The Correct Solution

### Stop Maintaining Counters

**Instead**: Compute workflow status from task states when needed

**How**:
1. Query all task states from Redis
2. Count by status/protocol
3. Determine workflow status from counts
4. No counters = no sync issues

**Performance**: Not a concern
- Typical workflow: 10-100 tasks
- Redis queries: microseconds each
- Total: < 10ms for 100 tasks
- Worth it for correctness

---

## What Was Fixed Today

### 1. Hard Fail Policy (DONE ✓)
**File**: `src/gleitzeit/workers/dependency_worker.py:409`

**Before**:
```python
if current_status == "running":
    # Apply hard fail
```

**After**:
```python
if current_status not in ["completed", "failed", "cancelled"]:
    # Apply hard fail - works for running/waiting/scheduled/paused/pending
```

**Why**: Hard fail must trigger for workflows in ANY active state, not just "running"

---

## What Still Needs To Be Done

### Short Term (Keeps Current Architecture)

1. **Remove counter updates from dependency worker**
   - Comment out all `hincrby` calls for task counters
   - Keep initial counter setup for backward compatibility

2. **Let reconciliation worker handle status**
   - It already computes correctly from task states
   - Runs every 60 seconds
   - Accept slight delay in status transitions

### Long Term (Clean Architecture)

1. **Create `compute_workflow_status()` function**
   - Queries task states
   - Computes workflow status
   - Single source of truth

2. **Use computed status everywhere**
   - Dependency worker after task completion
   - API endpoints
   - Reconciliation worker

3. **Remove counter maintenance**
   - Stop trying to keep counters in sync
   - Counters become read-only computed values

---

## Key Lessons Learned

1. **Don't maintain derived state separately** - compute from source of truth
2. **Task statuses are already stored** - use them!
3. **Performance concerns were premature optimization** - correctness first
4. **Single source of truth principle** - task states in Redis, everything else computed
5. **Hard fail policy must work regardless of workflow state** - check for active vs terminal states

---

## Questions For User

1. Should workflow status transitions be real-time or is periodic (60s) acceptable?
2. Are there performance requirements that prevent querying task states?
3. Is there a reason counters exist besides perceived performance optimization?

---

## Status

- ✅ Hard fail policy fixed
- ✅ Root cause identified
- ✅ Solution designed
- ❌ Solution not yet implemented
- ❌ Tests not written
- ❌ Negative counter issue still exists

**Next Steps**: Implement compute_workflow_status() or remove counter updates
