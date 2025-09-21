# Pause/Resume Implementation Design

## Current State Analysis

The system has pause/resume endpoints but lacks core implementation:
- ✅ API endpoints exist (`/workflows/{id}/pause`, `/workflows/{id}/resume`)
- ✅ Client methods exist (`pause_workflow()`, `resume_workflow()`)
- ❌ No PAUSED status in WorkflowStatus enum
- ❌ No pause logic in persistence layer
- ❌ No pause logic in task orchestrator
- ❌ No mechanism to pause running tasks

## Implementation Strategy

### 1. Add PAUSED Status to Models

```python
# src/gleitzeit/core/models.py

class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"      # Add this
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TaskStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    VALIDATED = "validated"
    ROUTED = "routed"
    EXECUTING = "executing"
    PAUSED = "paused"      # Add this
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRY_PENDING = "retry_pending"
```

### 2. Implement Pause in ScalableRedisAdapter

```python
# src/gleitzeit/persistence/scalable_redis.py

class ScalableRedisAdapter:
    
    async def pause_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Pause a running workflow and all its tasks."""
        workflow = await self.get_workflow(workflow_id)
        if not workflow:
            raise WorkflowNotFoundError(workflow_id)
        
        if workflow.status != WorkflowStatus.RUNNING:
            raise InvalidStateError(f"Cannot pause workflow in {workflow.status} state")
        
        # Store pause metadata
        pause_key = self._key(f"workflow:pause:{workflow_id}")
        pause_data = {
            "paused_at": datetime.utcnow().isoformat(),
            "previous_status": str(workflow.status),
            "paused_tasks": []
        }
        
        # Pause all executing tasks
        tasks = await self.get_workflow_tasks(workflow_id)
        for task in tasks:
            if task.status in [TaskStatus.EXECUTING, TaskStatus.QUEUED]:
                # Save task state before pausing
                task_pause_key = self._key(f"task:pause:{task.id}")
                await self._execute("hset", task_pause_key, mapping={
                    "previous_status": str(task.status),
                    "paused_at": datetime.utcnow().isoformat()
                })
                
                # Update task status
                task.status = TaskStatus.PAUSED
                await self.save_task(task)
                pause_data["paused_tasks"].append(task.id)
        
        # Save pause metadata
        await self._execute("hset", pause_key, mapping=pause_data)
        
        # Update workflow status
        workflow.status = WorkflowStatus.PAUSED
        await self.save_workflow(workflow)
        
        # Emit pause event
        if self.enable_events:
            await self._emit_workflow_event("workflow.paused", workflow)
        
        return {
            "workflow_id": workflow_id,
            "status": "paused",
            "paused_tasks": pause_data["paused_tasks"],
            "paused_at": pause_data["paused_at"]
        }
    
    async def resume_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Resume a paused workflow and its tasks."""
        workflow = await self.get_workflow(workflow_id)
        if not workflow:
            raise WorkflowNotFoundError(workflow_id)
        
        if workflow.status != WorkflowStatus.PAUSED:
            raise InvalidStateError(f"Cannot resume workflow in {workflow.status} state")
        
        # Get pause metadata
        pause_key = self._key(f"workflow:pause:{workflow_id}")
        pause_data = await self._execute("hgetall", pause_key)
        
        resumed_tasks = []
        
        # Resume paused tasks
        if pause_data and "paused_tasks" in pause_data:
            task_ids = json.loads(pause_data["paused_tasks"])
            for task_id in task_ids:
                # Get task pause state
                task_pause_key = self._key(f"task:pause:{task_id}")
                task_pause_data = await self._execute("hgetall", task_pause_key)
                
                # Restore task status
                task = await self.get_task(task_id)
                if task and task.status == TaskStatus.PAUSED:
                    previous_status = task_pause_data.get("previous_status", "QUEUED")
                    task.status = TaskStatus[previous_status]
                    await self.save_task(task)
                    resumed_tasks.append(task_id)
                    
                    # Clean up pause data
                    await self._execute("del", task_pause_key)
                    
                    # Re-queue if it was executing
                    if task.status == TaskStatus.EXECUTING:
                        # Reset to QUEUED so it gets picked up again
                        task.status = TaskStatus.QUEUED
                        await self.save_task(task)
        
        # Clean up workflow pause data
        await self._execute("del", pause_key)
        
        # Update workflow status
        workflow.status = WorkflowStatus.RUNNING
        await self.save_workflow(workflow)
        
        # Emit resume event
        if self.enable_events:
            await self._emit_workflow_event("workflow.resumed", workflow)
        
        return {
            "workflow_id": workflow_id,
            "status": "resumed",
            "resumed_tasks": resumed_tasks,
            "resumed_at": datetime.utcnow().isoformat()
        }
```

### 3. Handle Pause in Task Orchestrator

```python
# src/gleitzeit/core/task_orchestrator.py

class TaskOrchestrator:
    
    async def _should_skip_task(self, task: Task) -> bool:
        """Check if task should be skipped (paused or cancelled)."""
        if task.status == TaskStatus.PAUSED:
            logger.info(f"Skipping paused task {task.id}")
            return True
        
        # Check if workflow is paused
        workflow = await self.persistence.get_workflow(task.workflow_id)
        if workflow and workflow.status == WorkflowStatus.PAUSED:
            logger.info(f"Skipping task {task.id} - workflow is paused")
            return True
        
        return False
    
    async def _handle_task_ready(self, event: GleitzeitEvent):
        """Handle task ready for execution."""
        task_id = event.data.get("task_id")
        task = await self.persistence.get_task(task_id)
        
        # Skip if paused
        if await self._should_skip_task(task):
            return
        
        # Continue with normal execution...
```

### 4. Handle Running Task Interruption

```python
# src/gleitzeit/core/task_executor.py

class TaskExecutor:
    
    async def _check_pause_signal(self, task_id: str) -> bool:
        """Check if task should be paused."""
        pause_signal_key = f"task:pause:signal:{task_id}"
        signal = await self.persistence.redis.get(pause_signal_key)
        return signal == "1"
    
    async def execute_task(self, task: Task) -> TaskResult:
        """Execute task with pause checking."""
        
        # Start execution in background
        execution_task = asyncio.create_task(self._run_task(task))
        
        # Monitor for pause signal
        while not execution_task.done():
            if await self._check_pause_signal(task.id):
                # Cancel execution
                execution_task.cancel()
                
                # Save partial state
                await self._save_task_checkpoint(task)
                
                # Mark as paused
                task.status = TaskStatus.PAUSED
                await self.persistence.save_task(task)
                
                return TaskResult(
                    task_id=task.id,
                    status="paused",
                    paused=True
                )
            
            await asyncio.sleep(1)  # Check every second
        
        # Normal completion
        return await execution_task
```

### 5. Graceful Provider Interruption

```python
# src/gleitzeit/providers/python_provider.py

class PythonProvider:
    
    async def execute_with_interruption(self, task: Task) -> Any:
        """Execute Python task with interruption support."""
        
        # For long-running Python tasks
        if task.supports_checkpointing:
            return await self._execute_with_checkpoints(task)
        else:
            # Best effort - may not interrupt immediately
            return await self._execute_with_timeout(task)
    
    async def _execute_with_checkpoints(self, task: Task) -> Any:
        """Execute with periodic checkpointing."""
        
        # Load checkpoint if resuming
        checkpoint = await self._load_checkpoint(task.id)
        start_from = checkpoint.get("step", 0) if checkpoint else 0
        
        # Execute in steps
        for step in range(start_from, task.total_steps):
            # Check for pause
            if await self._should_pause(task.id):
                await self._save_checkpoint(task.id, {"step": step})
                raise TaskPausedException()
            
            # Execute step
            result = await self._execute_step(task, step)
            
            # Save progress
            if step % 10 == 0:  # Checkpoint every 10 steps
                await self._save_checkpoint(task.id, {
                    "step": step,
                    "partial_result": result
                })
        
        return result
```

## Pause Strategies by Provider Type

### 1. Python Tasks
- **Cooperative**: Tasks check pause flag periodically
- **Checkpointing**: Save state at intervals
- **Timeout-based**: Cancel after timeout

### 2. Docker Tasks
- **Container pause**: `docker pause <container_id>`
- **Container stop**: `docker stop --time=10 <container_id>`
- **Checkpoint/Restore**: Using CRIU if available

### 3. Shell Tasks
- **Process suspension**: Send SIGTSTP signal
- **Process termination**: Send SIGTERM with state save

### 4. HTTP/API Tasks
- **Request cancellation**: Cancel ongoing requests
- **Idempotency**: Ensure safe retry on resume

## State Persistence During Pause

```python
# Structure for pause state
pause_state = {
    "workflow": {
        "id": "wf_123",
        "paused_at": "2024-01-01T10:00:00",
        "previous_status": "RUNNING",
        "pause_reason": "user_requested",
        "paused_by": "user_123"
    },
    "tasks": [
        {
            "id": "task_1",
            "status_before": "EXECUTING",
            "progress": 0.75,
            "checkpoint": {
                "step": 750,
                "partial_data": {...}
            }
        }
    ],
    "resources": {
        "containers": ["container_abc"],
        "processes": [12345],
        "connections": ["conn_1"]
    }
}
```

## Resume Strategies

### 1. Full Restart
- Simple but loses progress
- Good for idempotent tasks

### 2. Checkpoint Resume
- Resume from saved state
- Requires checkpoint support

### 3. Partial Re-execution
- Skip completed portions
- Re-run from failure point

## Event Flow

### Pause Flow
```
1. User calls pause_workflow()
2. ScalableRedisAdapter updates workflow status
3. Emit workflow.pausing event
4. Task Orchestrator receives event
5. Sets pause signals for running tasks
6. Task Executors check signals
7. Tasks save state and pause
8. Emit task.paused events
9. Workflow marked as PAUSED
10. Emit workflow.paused event
```

### Resume Flow
```
1. User calls resume_workflow()
2. ScalableRedisAdapter updates workflow status
3. Emit workflow.resuming event
4. Restore task states from pause data
5. Re-queue paused tasks
6. Task Orchestrator picks up tasks
7. Tasks resume from checkpoints
8. Emit task.resumed events
9. Workflow marked as RUNNING
10. Emit workflow.resumed event
```

## Implementation Priority

### Phase 1: Basic Pause (1-2 days)
1. Add PAUSED status to enums
2. Implement pause/resume in ScalableRedisAdapter
3. Update task orchestrator to skip paused tasks
4. Test with simple workflows

### Phase 2: Graceful Interruption (2-3 days)
1. Add pause signal checking to executors
2. Implement checkpoint system
3. Provider-specific pause handlers
4. Test with long-running tasks

### Phase 3: Advanced Features (3-5 days)
1. Partial state preservation
2. Resource cleanup on pause
3. Resume strategies
4. UI integration

## Testing Strategy

```python
async def test_workflow_pause_resume():
    # Submit workflow
    workflow = await client.submit_workflow(test_workflow)
    
    # Wait for it to start
    await wait_for_status(workflow.id, WorkflowStatus.RUNNING)
    
    # Pause workflow
    result = await client.pause_workflow(workflow.id)
    assert result["status"] == "paused"
    
    # Verify tasks are paused
    tasks = await client.get_workflow_tasks(workflow.id)
    for task in tasks:
        if task.status == TaskStatus.EXECUTING:
            assert task.status == TaskStatus.PAUSED
    
    # Resume workflow
    result = await client.resume_workflow(workflow.id)
    assert result["status"] == "resumed"
    
    # Verify completion
    await wait_for_status(workflow.id, WorkflowStatus.COMPLETED)
```

## Benefits

1. **Resource Management**: Free up resources during pause
2. **Cost Optimization**: Stop billing for paused work
3. **Debugging**: Pause to inspect state
4. **Priority Management**: Pause low-priority work
5. **Maintenance Windows**: Pause during updates
6. **Error Recovery**: Pause to fix issues

## Conclusion

Implementing pause/resume requires:
1. Status additions to models
2. Persistence layer support
3. Orchestrator awareness
4. Executor interruption
5. Provider-specific handlers
6. State preservation

The implementation can be done incrementally, starting with basic workflow pause and advancing to graceful task interruption with checkpointing.