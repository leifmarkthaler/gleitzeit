# Task Status Persistence Fix - COMPLETE

## Problem
Tasks were executing successfully but their statuses were not being reflected in the API responses. All tasks showed as "pending" even when they had completed or were in other states.

## Root Cause
The `get_workflow` method in `UnifiedRedisAdapter` was returning tasks from a stored snapshot created when the workflow was first saved, rather than fetching the current task states from Redis.

### How it worked before:
1. Workflow submitted → All tasks saved as snapshot in workflow hash
2. Task executes → Individual task hash updated with new status
3. API calls `get_workflow` → Returns tasks from original snapshot (all "pending")

## Solution
Modified `get_workflow` in `/src/gleitzeit/persistence/unified_redis.py` (lines 588-605) to:
1. First try to fetch each task's current state from its individual Redis hash
2. Only use the stored snapshot as a fallback if the task isn't found

```python
for task_data in tasks_data:
    # Try to get the current task state from Redis
    task_id = task_data.get('id')
    if task_id:
        current_task = await self.get_task(task_id)
        if current_task:
            # Use the current task state from Redis
            tasks.append(current_task)
            continue
    
    # Fallback to stored task data if not found in Redis
    # ...existing code...
```

## Verification
After fix, the workflow status correctly shows:
- ✅ First task: "completed" with proper timestamps
- ✅ Signal task: "sleeping" (waiting for signal)
- ✅ Dependent task: "pending" (waiting for dependencies)

## Impact
This fix ensures that:
- Task progress is accurately reflected in API responses
- The CLI shows correct task counts (1/3 completed instead of 0/3)
- Users can see real-time task status updates
- WorkflowProgressHandler events align with displayed statuses