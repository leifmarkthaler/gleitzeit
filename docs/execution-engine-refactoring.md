# Execution Engine Refactoring: Persistence-Only Architecture

## Overview

This document describes the refactoring of the Gleitzeit Execution Engine from a hybrid memory/persistence architecture to a pure persistence-based architecture, along with the resolution of a critical task re-execution bug that emerged during the refactoring.

## Background

### Original Architecture (Hybrid Approach)
The original ExecutionEngine used both local memory structures and persistence backend:

```python
# Local memory structures (OLD)
self.active_tasks: Dict[str, Task] = {}      # Currently executing tasks
self.task_results: Dict[str, TaskResult] = {}  # Completed task results
self.workflow_states: Dict[str, Workflow] = {} # Workflow state tracking
```

This dual-storage approach led to:
- **Data consistency issues** between memory and persistence
- **Memory overhead** from duplicated data
- **Complexity** in synchronizing state between two storage layers
- **Scalability limitations** for distributed deployments

### Refactored Architecture (Persistence-Only)
The refactored engine uses only the persistence backend for all state management:

```python
# No local memory structures - everything through persistence
# Active tasks tracked via TaskStatus.EXECUTING queries
# Task results stored/retrieved from persistence backend
# Workflow states stored/retrieved from persistence backend
```

## The Refactoring Process

### Step 1: Remove Local Memory Dictionaries

**Changes Made:**
1. Removed the three dictionary declarations from `__init__`
2. Replaced dictionary operations with persistence calls
3. Added helper method `_get_active_task_count()` to query active tasks from persistence

**Key Changes:**
```python
# OLD: Dictionary lookup
if task.id in self.active_tasks:
    return self.active_tasks[task.id]

# NEW: Persistence query
task = await self.persistence.get_task(task.id)
if task and task.status == TaskStatus.EXECUTING:
    return task
```

### Step 2: Update State Management

**Task Status Tracking:**
- Active tasks: Query persistence for `TaskStatus.EXECUTING`
- Completed tasks: Query persistence for `TaskStatus.COMPLETED`
- Failed tasks: Query persistence for `TaskStatus.FAILED`

**Workflow State:**
- Store workflow updates immediately to persistence
- Retrieve fresh workflow state before any operation
- Update workflow's `completed_tasks` and `failed_tasks` lists in persistence

### Step 3: Fix Method Signatures

Several methods needed to become async to support persistence operations:
- `_get_stats_dict()` → `async def _get_stats_dict()`
- `get_task_result()` → `async def get_task_result()`
- `get_workflow_results()` → `async def get_workflow_results()`

## The Task Re-execution Bug

### Problem Discovery

After refactoring, a critical bug emerged where tasks would execute repeatedly in an infinite loop:

```
INFO: Executing task task_a8a9c537
INFO: Task task_a8a9c537 completed successfully in 0.028s
INFO: Executing task task_a8a9c537  # Same task executing again!
INFO: Task task_a8a9c537 completed successfully in 0.023s
INFO: Executing task task_a8a9c537  # And again...
[... continues indefinitely ...]
```

### Additional Issues Found

During testing with complex workflows with dependencies, additional issues were discovered:

1. **Queue Monitoring Re-enqueueing**: The queue monitoring loop was checking for PENDING tasks and re-enqueueing them without verifying if they already had results
2. **Dequeue Race Conditions**: Tasks that were already completed could be returned by dequeue if the persistence layer had stale data
3. **Inconsistent Task Status**: Some tasks would have COMPLETED results in task_results table but still show as PENDING in tasks table

### Root Cause Analysis

#### Issue 1: Workflow Completion Check
In `_check_workflow_completion()`, tasks without dependencies were being re-submitted without checking if they were already completed:

```python
# BUGGY CODE
if task.dependencies:
    # Check dependencies...
else:
    # Task has no dependencies, but wasn't submitted yet
    ready_tasks.append(task)  # BUG: Not checking if already completed!
```

#### Issue 2: Race Condition in Event-Driven Mode
The primary cause was a race condition in the persistence layer:

1. Task completes and status updated to `COMPLETED`
2. Task saved to persistence with `await self.persistence.save_task(task)`
3. **Immediately** after, engine tries to dequeue next task
4. Persistence backend hasn't fully committed the transaction
5. Query for `QUEUED` tasks returns the just-completed task
6. Task executes again, creating an infinite loop

### The Fix

#### Fix 1: Proper Status Checking
Added status verification before submitting tasks in `_check_workflow_completion()`:

```python
# Get fresh task status from persistence
fresh_task = await self.persistence.get_task(task.id)
if fresh_task and fresh_task.status in [TaskStatus.COMPLETED, TaskStatus.EXECUTING, TaskStatus.FAILED]:
    continue  # Skip already processed tasks

# Only submit tasks that are truly pending
if not fresh_task or fresh_task.status in [TaskStatus.PENDING, TaskStatus.QUEUED]:
    ready_tasks.append(task)
```

#### Fix 2: Persistence Commit Delay
Added a small delay and ID check to prevent race conditions:

```python
# In event-driven mode, after task completion
if active_count < self.max_concurrent_tasks:
    # Small delay to ensure persistence has committed the status change
    await asyncio.sleep(0.1)
    
    # Try to execute any newly available dependent tasks
    ready_task = await self.queue_manager.dequeue_next_task()
    
    # Ensure we don't re-execute the task we just completed
    if ready_task and ready_task.id != task.id:
        asyncio.create_task(self._execute_task(ready_task))
```

#### Fix 3: Queue Monitoring Safety Checks
Enhanced `_check_and_enqueue_ready_tasks` in TaskQueue to verify task state before enqueueing:

```python
# Get fresh task status to avoid race conditions
fresh_task = await self.persistence.get_task(task.id)
if not fresh_task:
    continue

# Skip if task is not actually pending anymore
if fresh_task.status != TaskStatus.PENDING:
    logger.debug(f"Task {task.id} no longer pending (status: {fresh_task.status}), skipping")
    continue

# Check if task has already been processed (has a result)
existing_result = await self.persistence.get_task_result(task.id)
if existing_result:
    logger.debug(f"Task {task.id} already has result (status: {existing_result.status}), skipping")
    continue
```

#### Fix 4: Dequeue Double-Checking
Added verification in the dequeue method to prevent returning completed tasks:

```python
# Double-check the task is actually QUEUED (avoid race conditions)
fresh_task = await self.persistence.get_task(task.id)
if not fresh_task or fresh_task.status != TaskStatus.QUEUED:
    logger.debug(f"Task {task.id} no longer QUEUED, skipping")
    continue

# Check if task already has a result (avoid re-executing completed tasks)
existing_result = await self.persistence.get_task_result(fresh_task.id)
if existing_result:
    logger.warning(f"Task {fresh_task.id} already has result but was QUEUED, skipping")
    # Fix the inconsistent state
    fresh_task.status = TaskStatus.COMPLETED
    await self.persistence.save_task(fresh_task)
    continue
```

## Architecture Components

### Queue Manager
- Manages task queues with priority-based ordering
- Updates task status to `EXECUTING` when dequeuing
- Properly marks tasks as `COMPLETED` or `FAILED`
- All operations use persistence backend directly

### Retry Manager
- Handles failed task retries with exponential backoff
- Monitors for stuck tasks in the queue
- Uses persistence for tracking retry counts and scheduling
- Prevents retry loops by checking max attempts

### Execution Engine
- Routes tasks to appropriate protocol providers
- Manages task lifecycle through status transitions
- Handles workflow dependency resolution
- Now uses **only** persistence backend (no local memory)

## Benefits of Refactoring

### Consistency
- Single source of truth (persistence backend)
- No synchronization issues between memory and storage
- Consistent state across restarts

### Scalability
- Ready for distributed deployment
- Multiple engine instances can share same persistence
- No memory limitations from local dictionaries

### Reliability
- State survives process crashes
- Automatic recovery on restart
- No data loss from memory-only storage

## Testing the Fix

### Before Fix
```bash
# Task executes repeatedly
INFO: Executing task task_xyz (python/v1/python/execute)
INFO: Task task_xyz completed successfully in 0.022s
INFO: Executing task task_xyz (python/v1/python/execute)  # Repeat!
INFO: Task task_xyz completed successfully in 0.022s
[... continues 100+ times ...]
```

### After Fix
```bash
# Task executes only once
INFO: Executing task task_xyz (python/v1/python/execute)
INFO: Task task_xyz completed successfully in 0.028s
# No repetition - working correctly!
```

### Verification
```sql
-- Check database for duplicate executions
SELECT COUNT(*) FROM tasks WHERE id='task_xyz';
-- Result: 1 (correct - only one entry)
```

## Lessons Learned

### 1. Persistence Consistency
When moving from memory to persistence-only architecture, consider:
- Transaction commit timing
- Query consistency guarantees
- Race conditions between write and read operations

### 2. Event-Driven Challenges
Event-driven execution with persistence requires:
- Careful ordering of status updates
- Consideration of eventual consistency
- Guards against re-processing completed work

### 3. Testing Requirements
Persistence-only architectures need:
- Tests for concurrent operations
- Verification of idempotency
- Load testing to expose race conditions

## Configuration

### Using SQL Backend (Recommended for Testing)
```bash
export GLEITZEIT_PERSISTENCE_TYPE=sql
python -m gleitzeit.cli.gleitzeit_cli serve --port 8041
```

### Using Redis Backend
```bash
export GLEITZEIT_PERSISTENCE_TYPE=redis
python -m gleitzeit.cli.gleitzeit_cli serve --port 8041
```

**Note:** The Redis adapter may need updates to support all refactored operations.

## Migration Guide

If upgrading from the old hybrid architecture:

1. **Backup your data** before upgrading
2. **Test thoroughly** with your workloads
3. **Monitor for performance** changes
4. **Verify idempotency** of your tasks

## Additional Fixes Implemented

### API Task Status Aggregation Issue

**Problem:** The workflow status API endpoint (`/workflows/{workflow_id}`) was showing incorrect task completion counts (`tasks_completed: 0`) even when tasks were actually completed.

**Root Cause:** The API endpoint attempted to read `tasks_completed` and `tasks_failed` fields directly from the `Workflow` model object, but these fields don't exist in the model - they need to be calculated dynamically from current task statuses.

**Solution:** Refactored the workflow status endpoint in `/src/gleitzeit/api/main.py`:

1. **Always calculate dynamically**: Removed the faulty primary path that assumed workflow objects have task count fields
2. **Use live task data**: Always fetch current task statuses via `list_tasks()` and calculate counts from actual task states
3. **Preserve workflow metadata**: Still get workflow metadata (creation time, etc.) from the workflow object when available

```python
# Before (BUGGY)
tasks_completed = workflow.tasks_completed if hasattr(workflow, 'tasks_completed') else 0

# After (FIXED)
tasks_completed = sum(1 for t in tasks if hasattr(t, 'status') and str(t.status) == "completed")
```

**Results:**
- ✅ Correct task completion counts in workflow status
- ✅ Proper workflow status calculation (`completed`, `running`, `failed`)
- ✅ Accurate completion timestamps
- ✅ Task results properly included in response

### Ollama Model Name Matching Issue

**Problem:** Ollama tasks were failing with "Failed to allocate Ollama resource" errors due to model name mismatches between request and available models.

**Root Cause:** The OllamaHub resource allocation was performing exact capability matching, but:
- Workflows specify models like `llama3.2` 
- Ollama stores them as `llama3.2:latest`
- The subset check `{'llama3.2'}.issubset({'llama3.2:latest'})` returned `False`

**Solution:** Enhanced the `get_available_instance()` method in `/src/gleitzeit/hub/ollama_hub.py` to handle Ollama model name variations:

```python
def model_matches(requested_models, available_models):
    for requested in requested_models:
        # Exact match first
        if requested in available_models:
            continue
        
        # Try with :latest suffix
        if f"{requested}:latest" in available_models:
            continue
        
        # Try without :latest suffix
        if requested.endswith(":latest"):
            base_name = requested[:-7]  # Remove ":latest"
            if base_name in available_models:
                continue
        
        # No match found for this requested model
        return False
    return True
```

**Results:**
- ✅ Ollama tasks execute successfully with model name variations
- ✅ `llama3.2` requests match `llama3.2:latest` instances
- ✅ Both `llama3.2` and `llama3.2:latest` work in workflows

### UnboundLocalError Fix

**Problem:** Tasks were failing with `UnboundLocalError: cannot access local variable 'failure_reason' before assignment` in the execution engine.

**Root Cause:** The `failure_reason` variable was only defined in certain code paths of the exception handling block.

**Solution:** Initialize the `failure_reason` variable early in the exception handling logic in `/src/gleitzeit/core/execution_engine.py`.

**Results:**
- ✅ No more UnboundLocalError exceptions
- ✅ Proper error reporting for failed tasks

## Future Improvements

### Short Term
- Implement transaction support for atomic updates
- Add persistence backend connection pooling
- Optimize query performance with indexes
- Improve task result retrieval in workflow endpoints

### Long Term
- Support for distributed locking
- Event sourcing for state changes
- Caching layer for read-heavy operations

## Troubleshooting

### Task Executing Multiple Times
**Symptom:** Same task ID appears multiple times in logs

**Possible Causes:**
1. Persistence backend slow to commit
2. Multiple engine instances without coordination
3. Queue monitoring re-enqueueing completed tasks

**Solutions:**
1. Increase commit delay in event-driven mode
2. Use distributed locking for multi-instance deployments
3. Verify queue manager properly updates task status

### Tasks Not Executing
**Symptom:** Tasks remain in QUEUED status

**Possible Causes:**
1. Persistence queries not returning correct results
2. Task dependencies not properly resolved
3. Engine not in event-driven mode

**Solutions:**
1. Check persistence backend connectivity
2. Verify dependency resolution logic
3. Ensure engine started with correct execution mode

## References

- [Gleitzeit Architecture Documentation](./architecture.md)
- [Persistence Backend Guide](./persistence-backend.md)
- [Task Queue Implementation](../src/gleitzeit/task_queue/task_queue.py)
- [Retry Manager Implementation](../src/gleitzeit/core/retry_manager.py)