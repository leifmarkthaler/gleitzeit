# Gleitzeit 0.0.7 Complete State Progression Audit

## Executive Summary

This comprehensive audit traces the complete event flow and state progression through the Gleitzeit system. The workflow status display issue previously identified has been confirmed: **the DependencyWorker creates `workflow:status:{id}` without a status field initially (line 159-167), while the API expects to find status there (line 87 in workflows.py).**

## 1. System Architecture Overview

### Key Components
1. **API** (`workflows.py`) - Workflow submission and status retrieval
2. **WorkflowLoaderWorkerV2** - Validates and transforms workflows
3. **DependencyWorker** - Manages task dependencies and workflow state
4. **TaskExecutionWorker** - Executes tasks via handlers
5. **Redis** - State storage and event streaming

### Event Streams (Sharded)
- `workflow:load` - Initial submission
- `workflow:submitted` - After validation
- `task:ready` - Tasks ready for execution
- `task:completed` - Task completion events
- `workflow:completed` - Workflow completion

## 2. Complete State Flow

### Phase 1: Workflow Submission
**Location**: `workflows.py:192-261` (submit_workflow endpoint)

```
User submits workflow
    ↓
API creates workflow_id
    ↓
API writes to workflow:load stream
    ↓
API creates workflow:state:{id} with status="submitted"
```

**Redis Keys Created**:
- `{shard:X}:workflow:state:{workflow_id}` - Initial state with "submitted" status
- `{shard:X}:workflow:load` - Stream entry for loader

**State at this point**:
```redis
workflow:state:{id} = {
    workflow_id: "...",
    status: "submitted",
    submitted_at: "...",
    stream_message_id: "...",
    user_id: "..."
}
```

### Phase 2: Workflow Loading and Validation
**Location**: `workflow_loader_worker_v2.py:126-284`

```
WorkflowLoaderWorkerV2 reads from workflow:load
    ↓
Validates workflow structure
    ↓
Transforms tasks to protocol format
    ↓
On Success:
    - Creates workflow:data:{id} with status="loaded"
    - Emits to workflow:submitted stream
    - Updates indexes
On Failure:
    - Creates workflow:status:{id} with status="validation_failed"
    - Emits to workflow:load:failed stream
```

**Redis Keys Created/Updated**:
- `{shard:X}:workflow:data:{workflow_id}` - Full workflow definition
- `{shard:X}:workflow:submitted` - Stream for dependency worker
- `{shard:0}:index:workflow_shards` - Shard mapping
- `{shard:X}:index:workflows` - Per-shard workflow list
- `{shard:0}:index:task_workflow` - Task to workflow mapping

**State at this point**:
```redis
workflow:data:{id} = {
    workflow: {...},
    loaded_at: "...",
    status: "loaded"
}
```

### Phase 3: Dependency Resolution and Task Scheduling
**Location**: `dependency_worker.py:85-168`

```
DependencyWorker reads from workflow:submitted
    ↓
Updates workflow:data:{id} status to "running"
    ↓
Builds dependency graph
    ↓
Creates workflow:status:{id} WITHOUT status field! ← BUG HERE
    ↓
Finds initial tasks (no dependencies)
    ↓
Emits initial tasks to task:ready stream
```

**Redis Keys Created/Updated**:
- `{shard:X}:workflow:data:{workflow_id}` - Updated with status="running"
- `{shard:X}:workflow:dependency:graph:{workflow_id}` - Task dependency mappings
- `{shard:X}:workflow:status:{workflow_id}` - Task counts (NO STATUS FIELD!)
- `{shard:X}:task:ready` - Stream for task execution

**State at this point**:
```redis
workflow:data:{id} = {
    workflow: {...},
    submitted_at: "...",
    status: "running"  ← Actual status here
}

workflow:status:{id} = {
    status: "pending",  ← Added at line 161 but NOT what API reads!
    total_tasks: "3",
    completed_tasks: "0",
    pending_tasks: "2",
    running_tasks: "1"
    # NO "status" field that API expects at line 87!
}
```

### Phase 4: Task Execution
**Location**: `task_execution_worker.py:149-299`

```
TaskExecutionWorker reads from task:ready
    ↓
Checks for cancellation
    ↓
Finds appropriate handler
    ↓
Executes task via handler
    ↓
Updates task:status:{task_id}:{workflow_id}
    ↓
Emits to task:completed or task:failed
```

**Redis Keys Created/Updated**:
- `{shard:X}:task:status:{task_id}:{workflow_id}` - Task execution state
- `{shard:X}:task:completed` or `{shard:X}:task:failed` - Completion streams

**State at this point**:
```redis
task:status:{task_id}:{workflow_id} = {
    status: "completed",
    result: {...},
    executed_at: "...",
    handler_id: "...",
    worker_id: "..."
}
```

### Phase 5: Dependency Resolution After Task Completion
**Location**: `dependency_worker.py:169-255`

```
DependencyWorker reads from task:completed
    ↓
Updates workflow:status completed_tasks count
    ↓
Checks dependency graph for newly ready tasks
    ↓
Resolves parameters with ${} substitution
    ↓
Emits ready tasks to task:ready
    ↓
Checks for workflow completion
```

**Redis Keys Updated**:
- `{shard:X}:workflow:status:{workflow_id}` - Incremented completed_tasks
- `{shard:X}:workflow:tasks:completed:{workflow_id}` - Set of completed tasks
- `{shard:X}:workflow:tasks:running:{workflow_id}` - Set of running tasks

### Phase 6: Workflow Completion
**Location**: `dependency_worker.py:337-417`

```
All tasks accounted for (completed/failed/skipped/blocked)
    ↓
Determines final workflow status
    ↓
Updates workflow:status:{id} with status field (FINALLY!)
    ↓
Emits to workflow:completed stream
    ↓
Stores completion event
```

**Redis Keys Updated**:
- `{shard:X}:workflow:status:{workflow_id}` - NOW has status field!

**Final State**:
```redis
workflow:status:{id} = {
    status: "completed",  ← Finally added here!
    completed_at: "...",
    completed_tasks: "3",
    skipped_tasks: "0",
    blocked_tasks: "0",
    failed_tasks: "0"
}
```

## 3. State Storage Patterns

### Three Distinct Workflow Keys

1. **`workflow:state:{id}`** - Initial submission metadata
   - Created by: API at submission
   - Contains: submitted_at, status="submitted"
   - Rarely updated after creation

2. **`workflow:data:{id}`** - Core workflow definition and runtime status
   - Created by: WorkflowLoader
   - Updated by: DependencyWorker
   - Contains: workflow JSON, status (actual runtime status)

3. **`workflow:status:{id}`** - Task tracking metrics
   - Created by: DependencyWorker
   - Problem: Missing status field during execution
   - Contains: task counts only until completion

## 4. Critical Issues Identified

### Issue 1: Missing Status Field in workflow:status
**Location**: `dependency_worker.py:159-167`

The DependencyWorker creates `workflow:status` without a status field:
```python
await self.redis.hset(
    default_sharding.get_workflow_key("status", workflow_id).encode(),
    mapping={
        b"status": b"pending",  # This line sets "pending" but API doesn't read it correctly
        b"total_tasks": str(len(workflow_data.get('tasks', []))).encode(),
        b"completed_tasks": b"0",
        b"pending_tasks": str(pending_count).encode(),
        b"running_tasks": str(len(initial_tasks)).encode()
    }
)
```

The API expects status in `workflow:status` at line 87:
```python
status_value = decoded_state.get("status", "unknown")
```

### Issue 2: Inconsistent Status Storage
- Runtime status is in `workflow:data:{id}`
- API reads from `workflow:status:{id}`
- Status only added to `workflow:status` on completion

### Issue 3: State Duplication
Three different locations store overlapping state:
- `workflow:state` - Initial submission state
- `workflow:data` - Runtime state
- `workflow:status` - Metrics and (eventually) final status

## 5. Event Stream Flow

```
workflow:load (sharded)
    ↓ WorkflowLoaderWorkerV2
workflow:submitted (sharded)
    ↓ DependencyWorker
task:ready (sharded)
    ↓ TaskExecutionWorker
task:completed (sharded)
    ↓ DependencyWorker
workflow:completed (sharded)
```

All streams are sharded by workflow_id for locality.

## 6. State Transition Diagram

```
SUBMITTED (workflow:state)
    ↓
LOADED (workflow:data)
    ↓
RUNNING (workflow:data)
    ↓
[Tasks Execute]
    ↓
COMPLETED/FAILED (workflow:status - only at end!)
```

## 7. Recommended Fixes

### Fix 1: Add Status to workflow:status on Creation
```python
# dependency_worker.py line 159-167
await self.redis.hset(
    default_sharding.get_workflow_key("status", workflow_id).encode(),
    mapping={
        b"status": b"running",  # Add actual status field
        b"total_tasks": str(len(workflow_data.get('tasks', []))).encode(),
        b"completed_tasks": b"0",
        b"pending_tasks": str(pending_count).encode(),
        b"running_tasks": str(len(initial_tasks)).encode()
    }
)
```

### Fix 2: Update Status Field During Execution
Update workflow:status status field when workflow:data status changes.

### Fix 3: API Fallback Logic
```python
# workflows.py - Add fallback to workflow:data if status not in workflow:status
status_value = decoded_state.get("status")
if not status_value or status_value == "unknown":
    # Fallback to workflow:data
    data_status = await conn.redis.hget(
        default_sharding.get_workflow_key("data", workflow_id).encode(),
        b"status"
    )
    if data_status:
        status_value = data_status.decode()
```

## 8. Performance Considerations

### Current Bottlenecks
1. API performs multiple Redis calls per workflow in list endpoint
2. No batch operations for workflow status retrieval
3. Task dependencies resolved one at a time

### Optimization Opportunities
1. Pipeline Redis operations in API
2. Cache workflow status in memory with TTL
3. Batch dependency resolution

## 9. Validation Gaps

### Missing Validations
1. No validation that task IDs are unique across workflow
2. No circular dependency detection
3. No validation of parameter references (${} syntax)
4. No limits on workflow depth or breadth

### Security Concerns
1. No sanitization of workflow names/descriptions
2. No rate limiting on workflow submissions
3. No validation of handler protocol availability

## 10. Conclusion

The Gleitzeit state progression system is well-designed with clear separation of concerns and proper sharding for scalability. The primary issue is a simple oversight where the DependencyWorker doesn't set the status field in `workflow:status` that the API expects to read. This causes all workflows to show "unknown" status until completion.

The fix is straightforward: ensure the status field is set when creating and updating the `workflow:status` hash. Additionally, consolidating the three workflow state locations into a more unified structure would reduce complexity and potential for inconsistencies.

### Immediate Actions Required
1. **Fix the missing status field** in DependencyWorker (2-line change)
2. **Add fallback logic** in API for robustness
3. **Add validation** for circular dependencies and parameter references

### Long-term Improvements
1. **Consolidate state storage** into fewer Redis keys
2. **Implement state history tracking** for debugging
3. **Add comprehensive state validation** at each transition
4. **Optimize Redis operations** with pipelining and batching