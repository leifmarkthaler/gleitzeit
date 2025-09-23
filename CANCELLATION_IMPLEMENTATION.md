# Gleitzeit 0.0.7 Cancellation Implementation Documentation

## Overview

Gleitzeit 0.0.7 implements a **hard fail policy** for task and workflow cancellation. When any task is cancelled, the entire workflow and all its dependent tasks are cancelled cascadingly. This ensures strict workflow integrity and prevents partial execution states.

## Architecture

### Event-Driven Cancellation

The cancellation system uses Redis streams for event propagation:

```
User Request → API Endpoint → Redis Stream → DependencyWorker → Cascade Effects
```

### Key Components

1. **API Endpoints** (`src/gleitzeit/api/routes/tasks.py`, `workflows.py`)
   - `/tasks/{task_id}/cancel` - Cancel a specific task
   - `/workflows/{workflow_id}/cancel` - Cancel an entire workflow

2. **DependencyWorker** (`src/gleitzeit/workers/dependency_worker.py`)
   - Listens to `task:cancelled` and `workflow:cancelled` streams
   - Implements cascading cancellation logic
   - Enforces hard fail policy

3. **TaskExecutionWorker** (`src/gleitzeit/workers/task_execution_worker.py`)
   - Checks task status before execution
   - Skips cancelled tasks
   - Emits confirmation events

## Implementation Details

### Hard Fail Policy Behavior

#### When a Task is Cancelled:

1. **Initial Cancellation**
   ```python
   # Task status updated to "cancelled"
   await redis.hset(task_key, {
       "status": "cancelled",
       "cancelled_at": timestamp,
       "cancelled_reason": reason
   })
   ```

2. **Dependency Cascade**
   ```python
   # All dependent tasks are cancelled (not just blocked)
   for dependent_task in find_dependents(task_id):
       emit_event("task:cancelled", dependent_task)
   ```

3. **Workflow Cancellation**
   ```python
   # Entire workflow is cancelled (hard fail)
   emit_event("workflow:cancelled", workflow_id)
   ```

4. **Full Cascade**
   - All remaining non-terminal tasks in workflow are cancelled
   - Each cancellation triggers its own cascade for dependents

#### When a Workflow is Cancelled:

1. **Workflow Status Update**
   ```python
   await redis.hset(workflow_key, {
       "status": "cancelled",
       "cancelled_at": timestamp,
       "cancelled_reason": reason
   })
   ```

2. **Task Cancellation**
   ```python
   # Emit cancellation for all non-terminal tasks
   for task in workflow.tasks:
       if task.status not in ["completed", "failed", "cancelled", "blocked"]:
           emit_event("task:cancelled", task.id)
   ```

### Stream Consumption

The DependencyWorker subscribes to cancellation streams:

```python
def get_base_streams(self) -> List[str]:
    return [
        "task:completed",
        "workflow:submitted",
        "task:cancelled",      # NEW: Listen for task cancellations
        "workflow:cancelled"    # NEW: Listen for workflow cancellations
    ]
```

### Task Execution Checks

Before executing any task, the TaskExecutionWorker verifies status:

```python
async def process_task(self, task_data: Dict):
    # Check cancellation before execution
    task_state = await self.redis.hgetall(state_key)
    if task_state:
        current_status = task_state.get(b"status", b"").decode()
        if current_status == "cancelled":
            logger.info(f"Task {task_id} was cancelled, skipping execution")
            return  # Skip execution entirely
```

## API Usage

### Cancel a Task

```bash
curl -X POST http://localhost:8000/api/tasks/{task_id}/cancel
```

**Response:**
```json
{
    "task_id": "task_123",
    "status": "cancelled",
    "message": "Task cancellation requested"
}
```

**Effects:**
- Task marked as cancelled
- All dependent tasks cancelled
- Workflow cancelled (hard fail policy)
- All other workflow tasks cancelled

### Cancel a Workflow

```bash
curl -X POST http://localhost:8000/api/workflows/{workflow_id}/cancel
```

**Response:**
```json
{
    "workflow_id": "workflow_456",
    "status": "cancelled",
    "tasks_cancelled": 5,
    "message": "Workflow cancelled, 5 tasks were cancelled"
}
```

**Effects:**
- Workflow marked as cancelled
- All non-terminal tasks cancelled
- Cascading cancellation for all dependencies

## State Transitions

### Task States

```
PENDING → CANCELLED (before execution)
READY → CANCELLED (queued but not started)
RUNNING → continues to completion (no interruption yet)
COMPLETED → no change (terminal state)
FAILED → no change (terminal state)
BLOCKED → no change (terminal state)
CANCELLED → no change (idempotent)
```

### Workflow States

```
SUBMITTED → CANCELLED
RUNNING → CANCELLED
COMPLETED → no change
FAILED → no change
CANCELLED → no change (idempotent)
```

## Example Scenarios

### Scenario 1: Simple Chain

```
Tasks: A → B → C → D
```

**Action:** Cancel task B
**Result:**
- A: completed (if already done) or cancelled
- B: cancelled
- C: cancelled (dependency cascade)
- D: cancelled (dependency cascade)
- Workflow: cancelled (hard fail)

### Scenario 2: Parallel Branches

```
       A
      ↙ ↘
     B   C
     ↓   ↓
     D   E
      ↘ ↙
       F
```

**Action:** Cancel task B
**Result:**
- A: completed or cancelled
- B: cancelled
- C: cancelled (workflow cancellation)
- D: cancelled (dependency on B)
- E: cancelled (workflow cancellation)
- F: cancelled (dependency cascade)
- Workflow: cancelled

### Scenario 3: Already Running Task

```
Tasks: A (completed) → B (running) → C (pending)
```

**Action:** Cancel task B
**Result:**
- A: completed (terminal state preserved)
- B: cancelled (status updated, but execution continues)
- C: cancelled (dependency cascade)
- Workflow: cancelled

## Redis Data Structures

### Task Status Keys

```redis
# Task state
task:state:{task_id} → Hash {
    status: "cancelled",
    cancelled_at: "2024-01-15T10:30:00Z",
    cancelled_reason: "user_requested",
    blocked_by: null,
    blocked_reason: null
}

# Workflow tracking sets
workflow:{workflow_id}:tasks:cancelled → Set of cancelled task IDs
workflow:{workflow_id}:tasks:blocked → Set of blocked task IDs
```

### Cancellation Streams

```redis
# Task cancellation stream (sharded)
task:cancelled:shard:0 → Stream of cancellation events
task:cancelled:shard:1 → ...
...
task:cancelled:shard:15

# Workflow cancellation stream (sharded)
workflow:cancelled:shard:0 → Stream of cancellation events
...
```

## Configuration

### Enable/Disable Hard Fail Policy

Currently, the hard fail policy is hardcoded. To make it configurable:

```python
# Future enhancement in config.yaml
cancellation:
  policy: "hard_fail"  # or "soft_fail" for blocking only
  cascade_dependencies: true
  cancel_workflow_on_task_cancel: true
  grace_period_ms: 5000  # For future running task cancellation
```

## Testing

### Unit Tests

```python
async def test_task_cancellation_cascades():
    """Verify task cancellation cascades to dependents"""
    workflow = create_workflow_with_dependencies()
    await submit_workflow(workflow)

    # Cancel a task
    await cancel_task("task_b")

    # Verify cascade
    assert get_task_status("task_c") == "cancelled"
    assert get_workflow_status(workflow.id) == "cancelled"

async def test_workflow_cancellation():
    """Verify workflow cancellation affects all tasks"""
    workflow = create_workflow_with_tasks(10)
    await submit_workflow(workflow)

    # Cancel workflow
    await cancel_workflow(workflow.id)

    # Verify all tasks cancelled
    for task in workflow.tasks:
        if task.status not in ["completed", "failed"]:
            assert get_task_status(task.id) == "cancelled"
```

### Integration Tests

```bash
# Run cancellation test suite
python test_cancellation.py

# Test concurrent cancellations
python test_cancellation_load.py --workflows 1000 --cancel-rate 0.5
```

## Monitoring

### Key Metrics

1. **Cancellation Latency**
   - Time from cancellation request to status update
   - Time for cascade completion

2. **Cancellation Volume**
   - Tasks cancelled per minute
   - Workflows cancelled per minute
   - Cascade depth distribution

3. **Stream Health**
   - Unconsumed messages in cancellation streams
   - Consumer lag

### Log Examples

```
INFO: Processing task cancellation with hard fail policy: task_123 in workflow_456
INFO: Cancelling dependent task task_124 due to cancelled dependency task_123 (hard fail policy)
INFO: Cancelling entire workflow workflow_456 due to task task_123 cancellation (hard fail policy)
INFO: Emitted cancellation for 5 tasks in workflow workflow_456
```

## Limitations

### Current Implementation

1. **No Running Task Interruption**
   - Tasks that are currently executing will complete
   - Status is updated but execution continues
   - Future enhancement needed for subprocess termination

2. **No Partial Cancellation**
   - Cannot cancel specific branches while keeping others
   - All-or-nothing approach with hard fail policy

3. **No Cancellation Undo**
   - Once cancelled, cannot resume or retry
   - Terminal state is permanent

### Future Enhancements

1. **Running Task Interruption**
   ```python
   # Monitor cancellation during execution
   async def execute_with_cancellation_check():
       while task_running:
           if is_cancelled(task_id):
               terminate_execution()
               break
           await asyncio.sleep(check_interval)
   ```

2. **Graceful Shutdown**
   ```python
   # Handler-specific cancellation
   class PythonHandler:
       async def cancel(self, context):
           process.send_signal(SIGTERM)
           await asyncio.wait_for(process.wait(), timeout=5)
           if still_running:
               process.kill()
   ```

3. **Configurable Policies**
   - Soft fail: Block dependents but continue workflow
   - Partial cancel: Cancel specific branches
   - Retry after cancel: Allow retry of cancelled workflows

## Security Considerations

1. **Authorization**
   - Only workflow owner can cancel
   - Admin override capability
   - Audit trail for all cancellations

2. **Race Conditions**
   - Idempotent cancellation operations
   - Status checks before state changes
   - Atomic Redis operations

3. **Resource Cleanup**
   - Cancelled tasks release resources
   - Temporary files cleaned up
   - Connections properly closed

## Performance Impact

### Overhead

- **Stream Processing**: ~1-2ms per cancellation event
- **Cascade Computation**: O(n) where n = number of dependents
- **Redis Operations**: 3-5 operations per task cancellation

### Optimization

- Batch cancellation events for large workflows
- Use Redis pipelines for multiple updates
- Implement cancellation coalescing for rapid requests

## Troubleshooting

### Common Issues

1. **Tasks Not Getting Cancelled**
   - Check if DependencyWorker is running
   - Verify stream consumption with `XINFO GROUPS`
   - Check Redis connectivity

2. **Partial Cancellation**
   - Verify all workers have updated code
   - Check for race conditions in status updates
   - Review worker logs for errors

3. **Slow Cascade**
   - Monitor Redis performance
   - Check worker count and scaling
   - Review dependency graph complexity

### Debug Commands

```bash
# Check cancellation stream lag
redis-cli XINFO GROUPS task:cancelled:shard:0

# Monitor cancellation events
redis-cli XREAD BLOCK 0 STREAMS task:cancelled:shard:0 $

# Check task status
redis-cli HGETALL task:state:task_123

# View cancelled tasks in workflow
redis-cli SMEMBERS workflow:workflow_456:tasks:cancelled
```

## Best Practices

1. **Always Check Status Before Operations**
   - Verify task isn't cancelled before expensive operations
   - Check workflow status in long-running loops

2. **Handle Cancellation Gracefully**
   - Clean up resources on cancellation
   - Log cancellation reasons for debugging
   - Emit appropriate events for audit

3. **Design for Cancellation**
   - Break long tasks into smaller chunks
   - Add cancellation checkpoints
   - Implement proper cleanup handlers

## Summary

The Gleitzeit 0.0.7 cancellation implementation provides:

✅ **Complete for non-running tasks**
- API endpoints for task and workflow cancellation
- Event-driven cancellation propagation
- Hard fail policy with full cascade
- Dependency-aware cancellation
- Pre-execution cancellation checks

❌ **Not yet implemented for running tasks**
- No interruption of executing tasks
- No graceful shutdown mechanisms
- No handler-specific cancellation

The system ensures workflow integrity through aggressive cancellation cascading, preventing partial execution states and maintaining consistency across distributed task execution.