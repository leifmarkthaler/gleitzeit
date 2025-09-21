# Pause with Rewind Capability

## YES! Pause Should Support Rewind! 🎯

Your insight is spot-on - pause with the ability to rewind (go back to earlier tasks) would be powerful.

## Current State
- ❌ No rewind functionality currently exists
- ✅ But the pause infrastructure we're building can support it!

## Enhanced Pause with Rewind

### Concept
```
Normal Pause:
  Workflow: A → B → C → [PAUSE] → Resume → C continues

Pause with Rewind:
  Workflow: A → B → C → [PAUSE + REWIND to B] → Resume → B reruns → C reruns
```

### Implementation Design

```python
class ScalableRedisAdapter:
    
    async def pause_workflow_with_rewind(
        self, 
        workflow_id: str,
        rewind_to_task: Optional[str] = None,
        rewind_to_step: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Pause workflow with optional rewind capability.
        
        Args:
            workflow_id: Workflow to pause
            rewind_to_task: Task ID to rewind to (reset this and all after)
            rewind_to_step: Step number to rewind to (1-based)
        """
        workflow = await self.get_workflow(workflow_id)
        if not workflow:
            raise WorkflowNotFoundError(workflow_id)
        
        # Determine rewind point
        if rewind_to_task:
            rewind_point = self._find_task_position(workflow, rewind_to_task)
        elif rewind_to_step:
            rewind_point = rewind_to_step - 1  # Convert to 0-based
        else:
            rewind_point = None  # No rewind, just pause
        
        pause_metadata = {
            "paused_at": datetime.utcnow().isoformat(),
            "rewind_point": rewind_point,
            "rewind_to_task": rewind_to_task,
            "cancelled_tasks": [],
            "reset_tasks": [],
            "preserved_results": {}
        }
        
        tasks = await self.get_workflow_tasks(workflow_id)
        task_order = self._get_task_execution_order(workflow, tasks)
        
        for idx, task in enumerate(task_order):
            if rewind_point is not None and idx >= rewind_point:
                # Tasks at or after rewind point - reset them
                
                # Preserve results for potential analysis
                if task.result:
                    pause_metadata["preserved_results"][task.id] = task.result
                
                # Reset task to PENDING
                task.status = TaskStatus.PENDING
                task.started_at = None
                task.completed_at = None
                task.result = None
                task.error = None
                task.metadata = task.metadata or {}
                task.metadata["rewound"] = True
                task.metadata["previous_result"] = pause_metadata["preserved_results"].get(task.id)
                
                await self.save_task(task)
                pause_metadata["reset_tasks"].append(task.id)
                
            elif task.status == TaskStatus.EXECUTING:
                # Currently running - cancel it
                task.status = TaskStatus.CANCELLED
                task.metadata = task.metadata or {}
                task.metadata["paused_cancel"] = True
                
                await self.save_task(task)
                pause_metadata["cancelled_tasks"].append(task.id)
                
                # Send cancel signal
                await self._execute("set", f"task:cancel:{task.id}", "1", ex=60)
        
        # Save pause metadata
        pause_key = self._key(f"workflow:pause:{workflow_id}")
        await self._execute("hset", pause_key, mapping=pause_metadata)
        
        # Update workflow status
        workflow.status = WorkflowStatus.PAUSED
        await self.save_workflow(workflow)
        
        return {
            "workflow_id": workflow_id,
            "status": "paused",
            "rewind_point": rewind_point,
            "rewind_to_task": rewind_to_task,
            "reset_tasks": len(pause_metadata["reset_tasks"]),
            "cancelled_tasks": len(pause_metadata["cancelled_tasks"]),
            "preserved_results": len(pause_metadata["preserved_results"])
        }
    
    def _find_task_position(self, workflow: Workflow, task_id: str) -> int:
        """Find position of task in execution order."""
        for idx, task in enumerate(workflow.tasks):
            if task.id == task_id:
                return idx
        raise TaskNotFoundError(f"Task {task_id} not found in workflow")
    
    def _get_task_execution_order(self, workflow: Workflow, tasks: List[Task]) -> List[Task]:
        """Get tasks in execution order (respecting dependencies)."""
        # Simple version - assumes tasks are in order
        # In production, would do topological sort based on dependencies
        return sorted(tasks, key=lambda t: workflow.tasks.index(t))
```

### Resume After Rewind

```python
async def resume_workflow(self, workflow_id: str) -> Dict[str, Any]:
    """Resume workflow, potentially from rewound state."""
    workflow = await self.get_workflow(workflow_id)
    
    # Get pause metadata
    pause_key = self._key(f"workflow:pause:{workflow_id}")
    pause_data = await self._execute("hgetall", pause_key)
    
    resumed_info = {
        "resumed_tasks": [],
        "from_rewind": False
    }
    
    if pause_data:
        # Check if this was a rewind
        if pause_data.get("rewind_point") is not None:
            resumed_info["from_rewind"] = True
            resumed_info["rewind_point"] = pause_data["rewind_point"]
            
            # Reset tasks will run from beginning
            reset_tasks = json.loads(pause_data.get("reset_tasks", "[]"))
            for task_id in reset_tasks:
                task = await self.get_task(task_id, workflow_id)
                if task:
                    # Clear rewind metadata
                    if task.metadata and "rewound" in task.metadata:
                        del task.metadata["rewound"]
                    
                    # Task stays in PENDING, will be picked up naturally
                    await self.save_task(task)
                    resumed_info["resumed_tasks"].append(task_id)
        
        # Handle cancelled tasks (from pause without rewind)
        cancelled_tasks = json.loads(pause_data.get("cancelled_tasks", "[]"))
        for task_id in cancelled_tasks:
            task = await self.get_task(task_id, workflow_id)
            if task:
                task.status = TaskStatus.PENDING
                await self.save_task(task)
                resumed_info["resumed_tasks"].append(task_id)
    
    # Clean up
    await self._execute("del", pause_key)
    
    # Resume workflow
    workflow.status = WorkflowStatus.RUNNING
    await self.save_workflow(workflow)
    
    return resumed_info
```

## Use Cases for Pause with Rewind

### 1. Error Recovery
```python
# Workflow fails at step 5
# Admin fixes the issue
await client.pause_workflow_with_rewind(
    workflow_id,
    rewind_to_step=4  # Rerun from step 4
)
await client.resume_workflow(workflow_id)
```

### 2. Data Correction
```python
# Discover bad input data affected tasks C and D
await client.pause_workflow_with_rewind(
    workflow_id,
    rewind_to_task="task_c"  # Rerun C and everything after
)
# Fix the data
await client.resume_workflow(workflow_id)
```

### 3. Partial Re-execution
```python
# Need to rerun last 3 steps with new parameters
await client.pause_workflow_with_rewind(
    workflow_id,
    rewind_to_step=workflow.total_steps - 2
)
# Update parameters
await client.resume_workflow(workflow_id)
```

## Rewind Strategies

### Strategy 1: Simple Reset (Phase 1)
- Reset task status to PENDING
- Clear results and timestamps
- Tasks run from beginning
- **Pros**: Simple, works universally
- **Cons**: Loses all progress

### Strategy 2: Checkpoint-based (Phase 2)
- Save task state at checkpoints
- Restore from nearest checkpoint
- **Pros**: Preserves partial progress
- **Cons**: Requires provider support

### Strategy 3: Result Preservation (Advanced)
- Keep previous results for comparison
- Allow selective result reuse
- **Pros**: Efficient, allows debugging
- **Cons**: Complex logic

## API Design

### REST Endpoints
```http
# Pause with rewind
POST /api/v1/workflows/{id}/pause
{
    "rewind_to_task": "task_c",  // Optional
    "rewind_to_step": 3,          // Optional
    "preserve_results": true      // Keep old results
}

# Get pause status
GET /api/v1/workflows/{id}/pause-status
Response:
{
    "paused": true,
    "paused_at": "2024-01-01T10:00:00Z",
    "rewind_point": 3,
    "reset_tasks": ["task_c", "task_d"],
    "preserved_results": {
        "task_c": {"old_result": "data"}
    }
}
```

### Client Interface
```python
# Simple pause
await client.pause_workflow(workflow_id)

# Pause with rewind to specific task
await client.pause_workflow(
    workflow_id,
    rewind_to_task="data_validation"
)

# Pause with rewind to step
await client.pause_workflow(
    workflow_id,
    rewind_to_step=3
)

# Resume (handles both normal and rewind)
await client.resume_workflow(workflow_id)
```

## Benefits of Pause + Rewind

1. **Error Recovery**: Fix issues and rerun affected tasks
2. **Experimentation**: Try different parameters from midpoint
3. **Debugging**: Rerun specific sections with logging
4. **Data Fixes**: Correct bad input and reprocess
5. **Partial Updates**: Rerun subset when requirements change
6. **Cost Optimization**: Only rerun necessary tasks

## Implementation Phases

### Phase 1: Basic Pause + Simple Rewind
- Pause cancels running tasks
- Rewind resets selected tasks to PENDING
- All tasks rerun from beginning
- **Timeline**: 3-4 days

### Phase 2: Smart Rewind
- Dependency-aware rewind
- Preserve non-affected task results
- Checkpoint support for long tasks
- **Timeline**: 1-2 weeks

### Phase 3: Advanced Features
- Selective result preservation
- Diff previous vs new results
- Branching (keep both paths)
- **Timeline**: 2-3 weeks

## Considerations

### Dependency Handling
```python
# If we rewind to task B, must also reset:
# - Tasks that depend on B
# - Tasks that depend on those tasks (transitive)

A → B → C → D
        ↓
        E → F

# Rewind to B means reset: B, C, D, E, F
```

### Result Comparison
```python
# After rewind and rerun, compare results
old_result = pause_metadata["preserved_results"]["task_c"]
new_result = task.result

if old_result != new_result:
    log.warning(f"Result changed after rewind: {diff}")
```

## Conclusion

**YES! Pause should absolutely work with rewind!**

The combination provides:
- **Pause**: Stop execution gracefully
- **Rewind**: Go back to earlier point
- **Resume**: Continue from chosen point

This gives users powerful workflow control for error recovery, experimentation, and debugging. Start with simple reset-based rewind, then add advanced features based on usage patterns.