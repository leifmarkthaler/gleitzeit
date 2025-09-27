# Gleitzeit 0.0.7 State Progression Comprehensive Audit

## Executive Summary

The workflow status display issue stems from a data synchronization mismatch between where the DependencyWorker stores status information and where the API expects to find it. The DependencyWorker creates and updates `workflow:status:{id}` hash with task counts but **never includes a status field**, while the API looks for status in this hash. The actual workflow status remains in `workflow:data:{id}`.

## 1. Redis Key Structure Analysis

### Workflow Keys (3 Distinct Patterns)

#### 1.1 `workflow:state:{workflow_id}`
- **Created by**: API during submission
- **Contains**: Initial submission metadata
- **Fields**:
  - `submitted_at`: Timestamp
  - `status`: "submitted"
- **Lifecycle**: Created at submission, rarely updated afterward

#### 1.2 `workflow:data:{workflow_id}`
- **Created by**: WorkflowLoader worker
- **Updated by**: DependencyWorker
- **Contains**: Core workflow definition and runtime status
- **Fields**:
  - `workflow`: JSON workflow definition
  - `submitted_at`: Timestamp
  - `status`: **ACTUAL STATUS** ("running", "completed", "failed")
- **Lifecycle**: Created during load, status updated during execution

#### 1.3 `workflow:status:{workflow_id}`
- **Created by**: DependencyWorker
- **Contains**: Task tracking metrics ONLY
- **Fields**:
  - `total_tasks`: Count
  - `completed_tasks`: Count
  - `failed_tasks`: Count
  - `skipped_tasks`: Count
  - `blocked_tasks`: Count
  - `completed_at`: Timestamp (on completion)
  - **MISSING**: `status` field
- **Problem**: No actual status field, only counts

### Task Keys

#### `task:status:{task_id}:{workflow_id}`
- **Managed by**: TaskExecutionWorker
- **Contains**: Complete task state
- **Fields**: status, result, error, timestamps
- **Works correctly**: Task status tracking functions properly

## 2. State Transition Flow

### Workflow Progression

```
1. API Submission (submit endpoint)
   └─> Creates: workflow:state:{id} with status="submitted"
   └─> Emits to: workflow:load stream

2. WorkflowLoader Processing
   └─> Creates: workflow:data:{id} with status="loaded"
   └─> Emits to: workflow:submitted stream

3. DependencyWorker Initialization
   └─> Updates: workflow:data:{id} status="running"
   └─> Creates: workflow:status:{id} (task counts, NO status field)
   └─> Emits: initial tasks to task:ready

4. Task Execution (TaskExecutionWorker)
   └─> Updates: task:status:{task_id}:{workflow_id}
   └─> Emits: task:completed events

5. DependencyWorker Completion Check
   └─> Updates: workflow:status:{id} (adds completed_at, still NO status)
   └─> Status remains in: workflow:data:{id}
   └─> Emits: workflow:completed event
```

### Task Progression

```
Ready -> Running -> Completed/Failed/Waiting
└─> All states properly tracked in task:status:{id}:{workflow_id}
```

## 3. Code Analysis: Where Status Updates Occur

### DependencyWorker (`dependency_worker.py`)

**Line 105-112**: Creates workflow:data with initial status
```python
await self.redis.hset(
    default_sharding.get_workflow_key("data", workflow_id).encode(),
    mapping={
        b"workflow": json.dumps(workflow_data).encode(),
        b"submitted_at": datetime.utcnow().isoformat().encode(),
        b"status": b"running"  # <-- Status in workflow:data
    }
)
```

**Line 396-406**: Updates workflow:status on completion
```python
await self.redis.hset(
    default_sharding.get_workflow_key("status", workflow_id).encode(),
    mapping={
        b"status": workflow_status,  # <-- This line exists but may not execute
        b"completed_at": datetime.utcnow().isoformat().encode(),
        b"completed_tasks": str(completed).encode(),
        # ... other counts
    }
)
```

**Issue**: Initial workflow:status creation (line 167-171) doesn't include status field:
```python
await self.redis.hset(
    status_key.encode(),
    mapping={
        b"total_tasks": str(total_tasks).encode(),
        b"completed_tasks": b"0",
        b"failed_tasks": b"0"
        # NO status field here!
    }
)
```

### API (`routes/workflows.py`)

**Line 63-87**: Fetches from workflow:status expecting status field
```python
status_key = default_sharding.get_workflow_key("status", workflow_id)
pipe.hgetall(status_key.encode())
# ...
status_value = decoded_state.get("status", "unknown")  # Falls back to "unknown"
```

## 4. Root Cause Analysis

### The Problem
1. **DependencyWorker** creates `workflow:status` hash WITHOUT status field initially
2. **DependencyWorker** updates status in `workflow:data` hash
3. **API** looks for status in `workflow:status` hash
4. Result: API always gets "unknown" for status

### Why It Happens
- Line 167-171 in dependency_worker.py creates workflow:status without status field
- Line 110 updates status in workflow:data, not workflow:status
- Line 399 should add status to workflow:status but only on completion
- During "running" state, workflow:status never has a status field

## 5. Verification Commands

```bash
# Check what's actually in Redis for a workflow
redis-cli hgetall "{shard:X}:workflow:WORKFLOW_ID:status"   # Has counts, no status
redis-cli hgetall "{shard:X}:workflow:WORKFLOW_ID:data"     # Has actual status
redis-cli hgetall "{shard:X}:workflow:WORKFLOW_ID:state"    # Has initial "submitted"
```

## 6. Recommended Fix

### Option 1: Fix DependencyWorker (Recommended)
Add status field when creating and updating workflow:status:

```python
# Line 167-171: Add status when creating
await self.redis.hset(
    status_key.encode(),
    mapping={
        b"status": b"running",  # ADD THIS LINE
        b"total_tasks": str(total_tasks).encode(),
        b"completed_tasks": b"0",
        b"failed_tasks": b"0"
    }
)

# Line 396-406: Ensure status is included on completion (already there)
```

### Option 2: Fix API to Read from workflow:data
Change API to read status from workflow:data instead of workflow:status.

### Option 3: Hybrid Approach
API reads from workflow:status first, falls back to workflow:data if not found.

## 7. Impact Assessment

### Current Impact
- All workflows show "unknown" status in UI
- Progress tracking works (task counts are correct)
- Workflows execute properly (core functionality intact)

### Fix Impact
- Option 1: Minimal - 2 line change, backward compatible
- Option 2: Medium - API change, requires testing
- Option 3: Low - API fallback logic, most resilient

## 8. Additional Findings

### Working Correctly
- Task state progression
- Workflow execution flow
- Worker coordination
- Event propagation

### Potential Improvements
1. Consolidate workflow state into single hash
2. Add state transition validation
3. Implement state history tracking
4. Add retry mechanism for state updates

## Conclusion

The state progression system is well-architected with clear separation of concerns. The issue is a simple data synchronization gap where the DependencyWorker doesn't populate the status field in the workflow:status hash that the API expects. A 2-line fix in the DependencyWorker will resolve the workflow status display issue while maintaining backward compatibility.