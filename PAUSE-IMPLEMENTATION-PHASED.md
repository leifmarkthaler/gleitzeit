# Two-Phase Pause Implementation Strategy

## YES! That's a Perfect Approach! ✅

Your suggestion is excellent - start simple with cancel+requeue, then add provider-specific pause later.

## Phase 1: Cancel & Requeue (Simple, Quick to Implement)

### How It Works
```
PAUSE:
1. Mark workflow as PAUSED
2. Cancel all EXECUTING tasks → Status: CANCELLED
3. Store task IDs that were cancelled
4. Stop processing new tasks

RESUME:
1. Mark workflow as RUNNING
2. Reset cancelled tasks → Status: PENDING/QUEUED
3. Requeue tasks for execution
4. Tasks run from the beginning (idempotent required)
```

### Implementation

```python
# src/gleitzeit/persistence/scalable_redis.py

class ScalableRedisAdapter:
    
    async def pause_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Phase 1: Simple pause by cancelling running tasks."""
        workflow = await self.get_workflow(workflow_id)
        if not workflow:
            raise WorkflowNotFoundError(workflow_id)
        
        if workflow.status != WorkflowStatus.RUNNING:
            raise InvalidStateError(f"Cannot pause workflow in {workflow.status} state")
        
        # Track cancelled tasks for resume
        pause_metadata = {
            "paused_at": datetime.utcnow().isoformat(),
            "cancelled_tasks": [],
            "queued_tasks": []
        }
        
        # Get all tasks
        tasks = await self.get_workflow_tasks(workflow_id)
        
        for task in tasks:
            if task.status == TaskStatus.EXECUTING:
                # Cancel executing tasks
                task.status = TaskStatus.CANCELLED
                task.metadata = task.metadata or {}
                task.metadata["paused_cancel"] = True
                await self.save_task(task)
                pause_metadata["cancelled_tasks"].append(task.id)
                
                # Send cancellation signal to executor
                cancel_key = f"task:cancel:{task.id}"
                await self._execute("set", cancel_key, "1", ex=60)
                
            elif task.status == TaskStatus.QUEUED:
                # Remove from queue
                task.metadata = task.metadata or {}
                task.metadata["paused_queued"] = True
                await self.save_task(task)
                pause_metadata["queued_tasks"].append(task.id)
        
        # Save pause metadata
        pause_key = self._key(f"workflow:pause:{workflow_id}")
        await self._execute("hset", pause_key, mapping=pause_metadata)
        
        # Update workflow status
        workflow.status = WorkflowStatus.PAUSED
        await self.save_workflow(workflow)
        
        return {
            "workflow_id": workflow_id,
            "status": "paused",
            "cancelled_tasks": len(pause_metadata["cancelled_tasks"]),
            "queued_tasks": len(pause_metadata["queued_tasks"]),
            "message": "Tasks cancelled and will restart on resume"
        }
    
    async def resume_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Phase 1: Resume by requeuing cancelled tasks."""
        workflow = await self.get_workflow(workflow_id)
        if not workflow:
            raise WorkflowNotFoundError(workflow_id)
        
        if workflow.status != WorkflowStatus.PAUSED:
            raise InvalidStateError(f"Cannot resume workflow in {workflow.status} state")
        
        # Get pause metadata
        pause_key = self._key(f"workflow:pause:{workflow_id}")
        pause_data = await self._execute("hgetall", pause_key)
        
        requeued_tasks = []
        
        if pause_data:
            # Requeue cancelled tasks
            cancelled_tasks = json.loads(pause_data.get("cancelled_tasks", "[]"))
            for task_id in cancelled_tasks:
                task = await self.get_task(task_id, workflow_id)
                if task:
                    # Reset to PENDING so it gets picked up again
                    task.status = TaskStatus.PENDING
                    task.started_at = None
                    task.completed_at = None
                    task.result = None
                    task.error = None
                    
                    # Clear pause metadata
                    if task.metadata and "paused_cancel" in task.metadata:
                        del task.metadata["paused_cancel"]
                    
                    await self.save_task(task)
                    requeued_tasks.append(task_id)
            
            # Restore queued tasks
            queued_tasks = json.loads(pause_data.get("queued_tasks", "[]"))
            for task_id in queued_tasks:
                task = await self.get_task(task_id, workflow_id)
                if task:
                    task.status = TaskStatus.QUEUED
                    if task.metadata and "paused_queued" in task.metadata:
                        del task.metadata["paused_queued"]
                    await self.save_task(task)
                    requeued_tasks.append(task_id)
        
        # Clean up pause metadata
        await self._execute("del", pause_key)
        
        # Update workflow status
        workflow.status = WorkflowStatus.RUNNING
        await self.save_workflow(workflow)
        
        # Emit event to trigger task processing
        if self.enable_events:
            await self._emit_workflow_event("workflow.resumed", workflow)
        
        return {
            "workflow_id": workflow_id,
            "status": "resumed",
            "requeued_tasks": len(requeued_tasks),
            "message": "Tasks requeued for execution from beginning"
        }
```

### Task Executor Cancellation Handler

```python
# src/gleitzeit/core/task_executor.py

class TaskExecutor:
    
    async def execute_task_with_cancellation(self, task: Task) -> TaskResult:
        """Execute task with cancellation support."""
        
        # Start execution
        execution_task = asyncio.create_task(self._run_task(task))
        cancel_key = f"task:cancel:{task.id}"
        
        # Monitor for cancellation
        while not execution_task.done():
            # Check for cancel signal
            cancel_signal = await self.redis.get(cancel_key)
            if cancel_signal == "1":
                # Cancel the task
                execution_task.cancel()
                
                # Clean up
                await self.redis.delete(cancel_key)
                
                return TaskResult(
                    task_id=task.id,
                    status=TaskStatus.CANCELLED,
                    error="Task cancelled due to workflow pause"
                )
            
            await asyncio.sleep(0.5)  # Check every 500ms
        
        return await execution_task
```

## Phase 2: Provider-Specific Pause (Advanced, Later)

### Provider Capabilities

```python
class ProviderCapabilities:
    """What pause features each provider supports."""
    
    PROVIDER_FEATURES = {
        "docker": {
            "supports_pause": True,
            "supports_checkpoint": False,  # Unless CRIU enabled
            "pause_command": "docker pause {container_id}",
            "resume_command": "docker unpause {container_id}"
        },
        "python": {
            "supports_pause": False,  # Can't pause Python process
            "supports_checkpoint": True,  # Can save state
            "requires_cooperation": True  # Code must check pause flag
        },
        "shell": {
            "supports_pause": True,  # Via SIGTSTP/SIGCONT
            "supports_checkpoint": False,
            "pause_signal": "SIGTSTP",
            "resume_signal": "SIGCONT"
        },
        "http": {
            "supports_pause": False,  # Can't pause HTTP request
            "supports_checkpoint": False,
            "requires_idempotency": True
        }
    }
```

### Enhanced Pause Implementation

```python
class ScalableRedisAdapter:
    
    async def pause_workflow_advanced(self, workflow_id: str) -> Dict[str, Any]:
        """Phase 2: Provider-aware pause."""
        workflow = await self.get_workflow(workflow_id)
        
        pause_results = {
            "paused": [],
            "cancelled": [],
            "checkpointed": []
        }
        
        tasks = await self.get_workflow_tasks(workflow_id)
        
        for task in tasks:
            if task.status == TaskStatus.EXECUTING:
                provider = task.protocol
                
                if provider == "docker":
                    # Pause Docker container
                    container_id = task.metadata.get("container_id")
                    if container_id:
                        await self._pause_docker_container(container_id)
                        task.status = TaskStatus.PAUSED
                        pause_results["paused"].append(task.id)
                    else:
                        # No container yet, just cancel
                        task.status = TaskStatus.CANCELLED
                        pause_results["cancelled"].append(task.id)
                
                elif provider == "python":
                    # Try to checkpoint if supported
                    if task.metadata.get("supports_checkpoint"):
                        checkpoint = await self._get_task_checkpoint(task.id)
                        if checkpoint:
                            await self._save_checkpoint(task.id, checkpoint)
                            pause_results["checkpointed"].append(task.id)
                    
                    # Cancel the task
                    task.status = TaskStatus.CANCELLED
                    pause_results["cancelled"].append(task.id)
                
                elif provider == "shell":
                    # Send SIGTSTP to process
                    pid = task.metadata.get("process_id")
                    if pid:
                        await self._suspend_process(pid)
                        task.status = TaskStatus.PAUSED
                        pause_results["paused"].append(task.id)
                    else:
                        task.status = TaskStatus.CANCELLED
                        pause_results["cancelled"].append(task.id)
                
                else:
                    # Default: cancel
                    task.status = TaskStatus.CANCELLED
                    pause_results["cancelled"].append(task.id)
                
                await self.save_task(task)
        
        workflow.status = WorkflowStatus.PAUSED
        await self.save_workflow(workflow)
        
        return pause_results
```

## Comparison: Phase 1 vs Phase 2

| Aspect | Phase 1 (Cancel & Requeue) | Phase 2 (Provider-Specific) |
|--------|---------------------------|-----------------------------|
| **Implementation** | Simple, 1-2 days | Complex, 1-2 weeks |
| **Task Restart** | From beginning | From pause point (if supported) |
| **Resource Usage** | Frees all resources | Keeps some resources (containers) |
| **Data Loss** | Loses progress | Preserves progress |
| **Requirements** | Tasks must be idempotent | Provider-specific features |
| **Reliability** | Very reliable | Depends on provider |
| **Use Cases** | Most workflows | Long-running, expensive tasks |

## Migration Path

### 1. Start with Phase 1
```python
# Simple implementation that works for all providers
await client.pause_workflow(workflow_id)  # Cancels tasks
await client.resume_workflow(workflow_id)  # Requeues tasks
```

### 2. Add Provider Detection
```python
# Check if task supports advanced pause
if task.protocol == "docker" and container_exists:
    use_advanced_pause()
else:
    use_simple_cancel()
```

### 3. Gradual Provider Support
- Docker: First to support (easiest)
- Shell: Second (process suspension)
- Python: Last (requires cooperation)

## Benefits of This Approach

### Phase 1 Benefits ✅
1. **Quick to implement** - Can ship in days
2. **Works for all providers** - Universal solution
3. **Simple and reliable** - Less edge cases
4. **Frees resources** - Good for cost optimization
5. **Clear semantics** - Users understand "restart from beginning"

### Phase 2 Benefits (Future) 🚀
1. **Preserves progress** - No repeated work
2. **Faster resume** - Continue from pause point
3. **Resource optimization** - Keep warm containers
4. **Advanced use cases** - Checkpointing, migration

## Testing Strategy

### Phase 1 Tests
```python
async def test_pause_cancel_requeue():
    # Submit workflow with long task
    workflow = await client.submit_workflow({
        "tasks": [{"duration": 60, "name": "long_task"}]
    })
    
    # Wait for task to start
    await wait_for_task_status("long_task", TaskStatus.EXECUTING)
    
    # Pause (cancels task)
    result = await client.pause_workflow(workflow.id)
    assert result["cancelled_tasks"] == 1
    
    # Verify task is cancelled
    task = await client.get_task("long_task")
    assert task.status == TaskStatus.CANCELLED
    
    # Resume (requeues task)
    result = await client.resume_workflow(workflow.id)
    assert result["requeued_tasks"] == 1
    
    # Task should complete normally
    await wait_for_workflow_completion(workflow.id)
```

## Conclusion

**YES! Your approach is perfect:**

**Phase 1 (Now)**: Cancel & Requeue
- Simple, reliable, works everywhere
- Ships quickly, solves 80% of use cases
- Good enough for most workflows

**Phase 2 (Later)**: Provider-Specific Pause
- Advanced feature for specific needs
- Gradual rollout per provider
- Backwards compatible

This phased approach gives immediate value while leaving room for future enhancements. Start simple, iterate based on real usage!