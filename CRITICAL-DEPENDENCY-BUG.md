# Critical Dependency Manager Bug - Workflow Execution Blocker

## Executive Summary

A **CRITICAL BUG** has been identified that prevents ALL workflows from progressing beyond their first task. The `UnifiedDependencyManager` is missing the `get_dependent_tasks()` method that `StatelessTaskOrchestrator` requires for task completion handling.

## The Bug

### Error Message
```
Handler error for task:completed: 'UnifiedDependencyManager' object has no attribute 'get_dependent_tasks'
```

### Location
**File**: `src/gleitzeit/core/stateless_task_orchestrator.py`
**Line**: 501
**Method**: `_handle_task_completed()`

### Code Causing the Issue
```python
# src/gleitzeit/core/stateless_task_orchestrator.py:499-503
# Check for newly ready tasks
if self.dependency_manager:
    newly_ready = await self.dependency_manager.get_dependent_tasks(task_id)  # ❌ METHOD DOESN'T EXIST
    for dependent_task_id in newly_ready:
        # Enqueue newly ready task
```

## Impact

### Immediate Effects
1. **Task Completion Fails**: When any task completes, the event handler crashes
2. **No Dependency Resolution**: Dependent tasks are never identified or marked as ready
3. **Workflows Stuck**: All workflows remain in pending state indefinitely
4. **Events Not Acknowledged**: Due to handler error, completion events aren't acknowledged in Redis

### Cascade Effects
- Signal workflows cannot progress past initial task
- Timer workflows cannot advance through stages
- All multi-task workflows fail silently
- System appears to "hang" with no visible errors to users

## Root Cause Analysis

### The Missing Method
The `UnifiedDependencyManager` class (in `src/gleitzeit/core/dependency_manager.py`) does NOT implement:
- `get_dependent_tasks()` - Required to find tasks that depend on a completed task
- Any method with "dependent" in its name
- Any equivalent functionality to identify downstream tasks

### Why This Happened
The `UnifiedDependencyManager` was likely refactored to consolidate dependency functionality, but the required interface for finding dependent tasks was not implemented or was removed during refactoring.

## Evidence from Logs

### Server Log Analysis
```
2025-09-16 13:17:38,826 - gleitzeit.events.multiplexed_stream_consumer - ERROR - Handler error for task:completed: 'UnifiedDependencyManager' object has no attribute 'get_dependent_tasks'
2025-09-16 13:17:38,827 - gleitzeit.events.multiplexed_stream_consumer - WARNING - Not acknowledging message 1758021458826-0 due to handler errors
```

### Event Processing Trace
1. ✅ `workflow:submitted` events are processed
2. ✅ `task:ready` events are emitted and handled
3. ✅ Tasks are picked up by `StatelessTaskOrchestrator`
4. ✅ Tasks execute successfully
5. ✅ `task:completed` event is emitted
6. ❌ `_handle_task_completed()` crashes on missing method
7. ❌ Dependent tasks never become ready
8. ❌ Workflow stuck forever

## Required Fix

### Option 1: Implement Missing Method
Add `get_dependent_tasks()` method to `UnifiedDependencyManager`:
```python
async def get_dependent_tasks(self, completed_task_id: str) -> List[str]:
    """
    Get tasks that depend on the completed task and are now ready to run.

    Args:
        completed_task_id: ID of the task that just completed

    Returns:
        List of task IDs that are now ready to execute
    """
    # Implementation needed:
    # 1. Get workflow containing this task
    # 2. Find all tasks that have completed_task_id in their dependencies
    # 3. Check if all their dependencies are now satisfied
    # 4. Return list of newly ready task IDs
```

### Option 2: Use Alternative Method
If the functionality exists under a different name, update `StatelessTaskOrchestrator` to use the correct method.

### Option 3: Bypass Dependency Manager
Implement dependency resolution directly in `StatelessTaskOrchestrator` if the dependency manager is not intended for this purpose.

## Testing Requirements

After fixing, verify:
1. Simple linear workflow (A → B → C) completes
2. Parallel workflow (A → [B, C] → D) processes correctly
3. Signal workflows can receive signals and continue
4. Timer workflows advance through time-based stages
5. Task completion events are properly acknowledged

## Workaround (Temporary)

Until fixed, workflows are completely non-functional for any multi-task scenario. No workaround exists without code changes.

## Related Issues

### Previously Fixed
- ✅ Duplicate event emissions (fixed)
- ✅ Signal/timer stream initialization (fixed)
- ✅ Provider pool protocol mismatch (fixed)

### Current Blockers
- ❌ **This bug** - No workflows can complete
- ❌ Consumer group errors (may be related)
- ❌ Signal workflows stuck even with provider available

## Priority

**CRITICAL** - This bug makes the entire workflow system non-functional. No workflows with dependencies can execute successfully.

## Discovery Context

Found while investigating why signal workflows were stuck in pending state despite:
- Signal provider being correctly registered
- Events being properly emitted
- Task handlers being called

The investigation revealed that the first task (signal send) completes but the completion handler crashes, preventing any subsequent tasks from executing.

## Verification Steps

To confirm this bug:
1. Check server logs for "Handler error for task:completed"
2. Submit any multi-task workflow
3. Observe first task completes but workflow remains pending
4. Check Redis for unacknowledged task:completed events

## Files Affected

- `/src/gleitzeit/core/stateless_task_orchestrator.py` - Calls missing method
- `/src/gleitzeit/core/dependency_manager.py` - Missing implementation
- Any workflow with task dependencies - Cannot execute

## Next Steps

1. **Immediate**: Implement `get_dependent_tasks()` in `UnifiedDependencyManager`
2. **Testing**: Verify all workflow types can complete
3. **Documentation**: Update interface documentation for dependency manager
4. **Monitoring**: Add error tracking for critical method calls