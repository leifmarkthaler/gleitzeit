# Task Status Persistence Bug Report

## Summary
Task statuses are not being persisted correctly when tasks complete. While events are emitted correctly and the WorkflowProgressHandler tracks completion, the actual task status in persistence remains "pending".

## Evidence

### 1. Task Execution Works
```
2025-09-12 18:33:54,975 - Task task-6fafe8ab4a4c496783fede43f2d5d3e0 completed successfully (duration: 0.02664)
```

### 2. WorkflowProgressHandler Tracks Correctly
```
2025-09-12 18:33:54,985 - Workflow workflow-5c60698cedb54679837ed2dc67c6c1e6 progress updated: 1/3 completed
```

### 3. But Task Status Remains "Pending"
When querying `/workflows/{id}`:
```json
{
  "tasks": [
    {
      "name": "start_workflow",
      "status": "pending",  // Should be "completed"
      "started_at": null,    // Should have timestamp
      "completed_at": null   // Should have timestamp
    }
  ]
}
```

## Root Cause Analysis

Looking at `TaskExecutor._update_task_status()` (lines 249-266):
```python
async def _update_task_status(self, task: Task, status: TaskStatus, ...):
    task.status = status
    if self.persistence:
        await self.persistence.save_task(task)
```

The issue is that:
1. TaskExecutor updates the task object in memory
2. It calls `persistence.save_task(task)` 
3. But the persistence layer may not be correctly updating the task in the workflow's task list

## Impact
- Task counts show incorrectly (0/3 completed instead of 1/3)
- Signal tasks appear pending even when waiting
- Workflow completion detection may fail
- User sees incorrect progress

## Related Issues
1. **Signal Task Issue**: Signal tasks that return SLEEPING status also remain "pending"
2. **Signal Waiter Registration**: Signal waiters are registered but tasks don't show as "sleeping"

## Fix Required
The persistence layer needs to properly update task statuses when `save_task()` is called, ensuring the task status in the workflow's task list is updated.