# Task Queue and Workflow Execution Audit

## Issues Found

### 1. Task Status Inconsistency
**Problem**: Task `task-72188dba` shows as "queued" in Redis hash but has a completed result in `gleitzeit:task_result:task-72188dba`
- Task hash status: `queued`
- Task result status: `completed`
- Has both `started_at` and `completed_at` timestamps
- Result shows successful execution with empty output

**Root Cause**: Status update race condition - task result is saved but task status in main hash not updated

### 2. Workflow Failure Cascade Issues
**Workflow**: `workflow-d93550ce` (example_calculation)
- Status: Failed
- Tasks:
  - `task-2a5eeef4` (generate_numbers): completed ✓
  - `task-72188dba` (calculate_sum): queued (but actually completed)
  - `task-68543f59` (calculate_average): failed (timeout after 300s)
  - `task-b946d04a` (final_report): failed (dependency failed)

**Problem**: When `calculate_average` failed with timeout, the workflow was marked as failed correctly, but `calculate_sum` remained in inconsistent state

### 3. Task Execution Flow Issues
- Tasks are executed and results are stored
- Task results have correct status
- But main task hash not always updated
- Status index (`gleitzeit:idx:task_status:queued`) contains tasks that are actually completed

## Architecture Observations

### Multiple Status Update Paths
Found status updates in multiple components:
1. **TaskExecutor** (`task_executor.py`): Updates via `_update_task_status()`
2. **TaskOrchestrator** (`task_orchestrator.py`): Cascade failure updates
3. **StatelessDependencyManager** (`stateless_dependency_manager.py`): Workflow completion
4. **ReconciliationService** (`reconciliation_service.py`): Resets to QUEUED for retry
5. **TaskQueue** (`task_queue.py`): Sets QUEUED when enqueueing
6. **RetryManager** (`retry_manager.py`): Resets for retry attempts

### Event System Integration
- Events are emitted but may not be properly consumed
- Redis streaming is used for logs but status updates use direct hash operations
- Multiple components trying to manage state independently

## Suspected Root Causes

1. **Missing Atomic Operations**: Task status update and result save not atomic
2. **Event-Driven vs Direct Updates**: Mix of event-driven and direct persistence updates
3. **Reconciliation Interference**: Reconciliation service may be resetting completed tasks to queued
4. **Cascade Failure Timing**: Race between task completion and workflow failure cascade

## Critical Finding: Missing Event Handler Registration

### PersistenceTaskHandler Not Registered
**Location**: `src/gleitzeit/events/persistence_handlers.py`
**Issue**: The `PersistenceTaskHandler` class exists but is NEVER instantiated or registered with the event bus
- This handler is responsible for updating task status when TASK_COMPLETED events are received
- Without it, tasks complete but their status in Redis is never updated from QUEUED to COMPLETED
- This explains why task-72188dba has a completed result but still shows as "queued"

### Event Flow Breakdown
1. TaskExecutor completes a task and emits TASK_COMPLETED event
2. Event is published to the event bus
3. **MISSING**: PersistenceTaskHandler should receive event and update task status
4. Result: Task result is saved but task status remains unchanged

### Other Registered Handlers
Found these components registering for TASK_COMPLETED:
- ExecutionEngineV2: Updates statistics only
- WorkflowManager: Handles workflow-level updates
- TaskOrchestrator: Checks workflow progression
- Client components: For client-side tracking

But none of these update the individual task status in persistence!

## RECHECK: Event System Architecture

### Current Implementation  
1. **Redis Pub/Sub Used** - NOT Redis Streams
   - `PubSubEventBus` uses Redis PUBLISH/SUBSCRIBE
   - `StreamTransport` exists but is NOT being used
   - SystemManager creates `PubSubEventBus` when Redis is available
   - Events use Pub/Sub which is fire-and-forget, not durable

2. **Task Status Update BUG CONFIRMED**
   - TaskExecutor calls `_update_task_status()` which sets `task.status = TaskStatus.COMPLETED`
   - Then calls `persistence.save_task(task)` 
   - In `unified_redis.py` line 229: `'status': task.status` saves the enum directly
   - **BUG CONFIRMED**: `str(TaskStatus.COMPLETED)` returns `"TaskStatus.COMPLETED"` not `"completed"`
   - Must use `task.status.value` to get the string value
   - This causes Redis to store the wrong value, leaving tasks as "queued"

3. **Evidence of the Bug**
   - Task `task-72188dba` has:
     - `started_at`: 2025-09-09T07:38:45.620017
     - `completed_at`: 2025-09-09T07:38:45.739597  
     - `status`: queued (WRONG - should be completed)
   - Task executed successfully but status wasn't updated properly

## Complete Audit Findings

### 1. Missing Event Handler Registration (CRITICAL)
The `PersistenceTaskHandler` that updates task status on TASK_COMPLETED events is never instantiated or registered. This causes tasks to complete but their status remains "queued" in Redis.

### 2. Multiple Workflow Completion Checks
Found multiple components checking workflow completion independently:
- `StatelessDependencyManager._check_workflow_completion()`
- `RedisTaskQueue._check_workflow_completion()`
- `EventDrivenRetryManager._check_workflow_completion()`
- `TaskOrchestrator._check_workflow_progress()`

Each uses slightly different logic, creating potential race conditions.

### 3. Non-Atomic Status Updates
Task completion involves multiple operations that aren't atomic:
1. Task status update in hash
2. Status index update (remove from queued, add to completed)
3. Task result save
4. Workflow completed_tasks list update

If any step fails, the system enters an inconsistent state.

### 4. Event System vs Direct Updates
The system mixes event-driven and direct persistence updates:
- TaskExecutor directly updates status AND emits events
- Some components listen to events, others poll persistence
- No clear separation of concerns

### 5. Cascade Failure Logic
When a task fails, dependent tasks should be marked as failed. This happens in multiple places:
- `TaskOrchestrator._mark_blocked_tasks_as_failed()`
- Various workflow failure handlers

But the cascade can miss tasks if they're in certain states.

## Root Cause Summary

The primary issue is **missing event handler registration**. The `PersistenceTaskHandler` exists but is never wired up to handle TASK_COMPLETED events, causing task statuses to remain stale even after successful execution.

Secondary issues include non-atomic operations and multiple competing workflow completion checks that can cause race conditions.

## Fix Required

1. Register `PersistenceTaskHandler` with the event bus during SystemManager initialization
2. Ensure atomic task status updates using Redis transactions
3. Consolidate workflow completion logic to a single authoritative component
4. Clarify event-driven vs direct update patterns