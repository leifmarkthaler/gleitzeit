# Signal Handler Fix - COMPLETE

## Summary
Successfully fixed two critical issues that were preventing proper task status tracking and signal handling in workflows.

## Issues Fixed

### 1. Task Status Persistence Bug
**Problem**: Task statuses remained "pending" even after completion
**Root Cause**: `get_workflow` in `unified_redis.py` was returning stored snapshots instead of current task states
**Fix**: Modified to fetch current task states from Redis before falling back to snapshot
**Location**: `/src/gleitzeit/persistence/unified_redis.py` lines 588-605

### 2. Signal Handler Registration/Lookup Mismatch
**Problem**: Signals couldn't wake waiting tasks due to key mismatch
**Root Cause**: Signal monitor was looking for non-workflow-scoped keys while handler registered workflow-scoped keys
**Fix**: Updated monitor to use workflow-scoped keys matching registration pattern
**Location**: `/src/gleitzeit/signals/monitor.py` lines 227-228, 253, 267, 301

## Verification Results

### Signal Workflow Test
```
✅ Workflow submitted: workflow-9ce1c3024e3d462c92a0959347d7e317
✅ Status: RUNNING → COMPLETED
✅ Tasks: 1/3 → 3/3 completed
```

### Task Status Display
- First task: `"status": "completed"` with timestamps ✅
- Signal task: `"status": "sleeping"` while waiting ✅
- Final task: `"status": "completed"` after signal ✅

### Signal Handling
- Signal registration: Working with workflow-scoped keys ✅
- Signal waking: Successfully woke 1 task ✅
- Workflow completion: All tasks completed in sequence ✅

## Technical Details

### Workflow-Scoped Signal Keys
The fix ensures signals use workflow-scoped keys to prevent cross-workflow interference:
- Registration: `signal:{workflow_id}:{signal_name}:waiters`
- Lookup: Same pattern (was incorrectly using `signal:{signal_name}:waiters`)

### Task Status Fetching
The fix ensures task statuses are fetched from Redis in real-time:
```python
# Try to get the current task state from Redis
task_id = task_data.get('id')
if task_id:
    current_task = await self.get_task(task_id)
    if current_task:
        # Use the current task state from Redis
        tasks.append(current_task)
        continue
```

## Impact
These fixes ensure:
1. Task progress is accurately reflected in API responses
2. CLI shows correct task counts (e.g., "1/3 completed")
3. Signal workflows function properly with tasks waking on signal
4. No cross-workflow signal interference
5. Real-time status updates for monitoring tools

## Files Modified
- `/src/gleitzeit/persistence/unified_redis.py`
- `/src/gleitzeit/signals/monitor.py`