# Gleitzeit 0.0.7 Consolidated State Architecture

## Overview

This document describes the consolidated state storage architecture implemented to resolve state fragmentation issues in Gleitzeit. The consolidation reduces complexity, improves consistency, and ensures workflow status is always available.

## Previous Architecture (Fragmented)

Previously, workflow state was fragmented across three Redis keys:

1. **`workflow:state:{id}`** - Initial submission metadata
2. **`workflow:data:{id}`** - Workflow definition AND runtime status
3. **`workflow:status:{id}`** - Task counts but NO status field until completion

This caused the "unknown" status issue where the API couldn't find the status field.

## New Consolidated Architecture

The consolidated architecture uses only two Redis keys:

### 1. `workflow:state:{id}` - All Runtime State

Contains all workflow runtime state and metrics in a single hash:

```redis
{
  # Identification
  "workflow_id": "uuid",
  "name": "Workflow Name",
  "description": "Workflow description",
  "version": "1.0.0",

  # Status Fields
  "status": "running|completed|failed|cancelled|validation_failed",
  "submitted_at": "ISO timestamp",
  "started_at": "ISO timestamp",
  "loaded_at": "ISO timestamp",
  "completed_at": "ISO timestamp",

  # Task Metrics (live updated)
  "total_tasks": "10",
  "completed_tasks": "5",
  "failed_tasks": "0",
  "skipped_tasks": "0",
  "blocked_tasks": "0",
  "pending_tasks": "3",
  "running_tasks": "2",

  # Tracking
  "worker_id": "worker-uuid",
  "user_id": "user-uuid",

  # Error Info (if failed)
  "error": "Error message if validation failed"
}
```

### 2. `workflow:data:{id}` - Workflow Definition Only

Contains only the workflow definition (kept separate due to size):

```redis
{
  "workflow": "{JSON workflow definition}"
}
```

## State Transitions

### Phase 1: Submission (API)
```python
workflow:state:{id} = {
  "workflow_id": id,
  "status": "submitted",
  "submitted_at": timestamp,
  "user_id": user
}
```

### Phase 2: Loading (WorkflowLoader)
```python
# Updates state
workflow:state:{id} += {
  "status": "loaded",
  "loaded_at": timestamp,
  "name": name,
  "description": desc,
  "version": version
}

# Stores definition
workflow:data:{id} = {
  "workflow": workflow_json
}
```

### Phase 3: Running (DependencyWorker)
```python
workflow:state:{id} += {
  "status": "running",
  "started_at": timestamp,
  "total_tasks": N,
  "completed_tasks": 0,
  "running_tasks": M,
  "pending_tasks": N-M,
  # ... other counts
}
```

### Phase 4: Task Execution Updates
```python
# On task completion
HINCRBY workflow:state:{id} completed_tasks 1
HINCRBY workflow:state:{id} running_tasks -1

# On task failure
HINCRBY workflow:state:{id} failed_tasks 1
HINCRBY workflow:state:{id} running_tasks -1
```

### Phase 5: Completion
```python
workflow:state:{id} += {
  "status": "completed|failed",
  "completed_at": timestamp,
  "running_tasks": 0,
  "pending_tasks": 0
}
```

## Benefits of Consolidation

### 1. Single Source of Truth
- All runtime state in one location
- No synchronization issues between keys
- Status always available

### 2. Atomic Updates
- Single key updates are atomic
- No race conditions between state updates
- Consistent view of workflow state

### 3. Simplified API Queries
- Single Redis call for all state
- No need to check multiple keys
- Reduced latency

### 4. Better Monitoring
- All metrics in one place
- Easy to track workflow progress
- Simple health checks

## Implementation Changes

### DependencyWorker Changes

**Before:**
```python
# Created workflow:status without status field
await redis.hset("workflow:status:{id}", {
    "total_tasks": N,
    "completed_tasks": 0
    # NO status field!
})
```

**After:**
```python
# Creates consolidated state with status
await redis.hset("workflow:state:{id}", {
    "status": "running",  # Always included
    "total_tasks": N,
    "completed_tasks": 0,
    "running_tasks": M,
    # ... all fields
})
```

### API Changes

**Before:**
```python
# Had to check workflow:status (often missing status)
state = await redis.hgetall("workflow:status:{id}")
status = state.get("status", "unknown")  # Often "unknown"
```

**After:**
```python
# Single source with guaranteed status
state = await redis.hgetall("workflow:state:{id}")
status = state.get("status", "unknown")  # Always has value
```

## Migration Notes

### Backward Compatibility
- Old workflows with `workflow:status` keys still work
- API can fall back to old keys if needed
- No data migration required

### Performance Impact
- Reduced Redis calls (1 instead of 2-3)
- Smaller memory footprint (fewer keys)
- Faster API responses

## Redis Key Reference

### Per-Workflow Keys
```
{shard:X}:workflow:state:{workflow_id}    # All runtime state
{shard:X}:workflow:data:{workflow_id}     # Workflow definition
{shard:X}:workflow:dependency:graph:{id}  # Task dependencies
{shard:X}:workflow:tasks:completed:{id}   # Completed task set
{shard:X}:workflow:tasks:failed:{id}      # Failed task set
{shard:X}:workflow:tasks:running:{id}     # Running task set
{shard:X}:workflow:tasks:blocked:{id}     # Blocked task set
{shard:X}:workflow:tasks:skipped:{id}     # Skipped task set
```

### Per-Task Keys
```
{shard:X}:task:status:{task_id}:{workflow_id}  # Task execution state
```

### Streams (Event-Driven)
```
{shard:X}:workflow:load        # Workflow submissions
{shard:X}:workflow:submitted   # Validated workflows
{shard:X}:task:ready           # Tasks ready for execution
{shard:X}:task:completed       # Completed tasks
{shard:X}:task:failed          # Failed tasks
{shard:X}:workflow:completed   # Completed workflows
```

## Testing

The consolidation has been tested with:
1. Unit test verifying state transitions
2. API read/write operations
3. Task execution flow
4. Workflow completion scenarios

Test file: `test_state_consolidation.py`

## Monitoring Queries

### Check Workflow Status
```redis
HGET {shard:X}:workflow:state:{workflow_id} status
```

### Get Full Workflow State
```redis
HGETALL {shard:X}:workflow:state:{workflow_id}
```

### Monitor Progress
```redis
HMGET {shard:X}:workflow:state:{workflow_id} \
      completed_tasks running_tasks pending_tasks failed_tasks
```

## Conclusion

The consolidated state architecture eliminates the fragmentation that caused the workflow status display issue. By maintaining all runtime state in a single `workflow:state` key, the system ensures consistency, improves performance, and simplifies the codebase. The status field is now always present and correctly updated throughout the workflow lifecycle.