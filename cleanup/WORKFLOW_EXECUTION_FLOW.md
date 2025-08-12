# Gleitzeit V2 Workflow Execution Flow

This document describes the complete flow from workflow submission to task completion in the Gleitzeit V2 distributed task execution system.

## Architecture Overview

```
Client → Workflow Server → Central Server → Providers
   ↓         ↓                ↓              ↓
Workflow  Task Queue     Socket.IO Hub   Task Execution
Submit   & Dependencies  & Coordination   & Results
```

## Components

- **Client**: Submits workflows and receives completion notifications
- **Workflow Server**: Orchestrates workflows, manages task dependencies, handles parameter substitution
- **Central Server**: Socket.IO hub for provider registration and message routing
- **Task Queue**: Redis-based queue with dependency management
- **Providers**: Execute tasks (MCP, Ollama, etc.)

## Complete Execution Flow

### 1. Workflow Submission

**Client → Workflow Server**
```
Socket.IO Event: 'workflow:submit'
Data: {
  workflow: { id, name, tasks, dependencies, ... },
  client_socket_id: "client123"
}
```

**Workflow Server Processing:**
1. Receives workflow via `workflow:submit` event
2. Creates `Workflow` object from JSON using `Workflow.from_dict()`
   - **Critical**: Uses `add_task()` method to ensure `workflow_id` is set on each task
3. Calls `workflow_engine.submit_workflow(workflow)`

### 2. Workflow Engine Processing

**WorkflowEngine.submit_workflow():**
```python
# Store workflow in memory
self.workflows[workflow.id] = workflow
workflow.status = WorkflowStatus.QUEUED

# Register task-to-workflow mapping
for task in workflow.tasks:
    self.task_to_workflow[task.id] = workflow.id

# Enqueue tasks with dependency handling
await self.task_queue.enqueue_batch(workflow.tasks)

# Update status
workflow.status = WorkflowStatus.RUNNING
```

### 3. Task Queue and Dependency Management

**TaskQueue.enqueue_batch():**
```python
ready_tasks = []
pending_tasks = []

for task in tasks:
    if not task.dependencies or all_deps_completed:
        ready_tasks.append(task)
        # Add to Redis: "gleitzeit_v2:ready_tasks"
    else:
        pending_tasks.append(task)
        # Add to Redis: "gleitzeit_v2:pending_tasks"
```

### 4. Task Scheduling Loop

**WorkflowEngine._scheduler_loop()** (runs every 2 seconds):
```python
# Get available providers
available_providers = self.provider_manager.get_available_providers()

# For each provider, try to assign a compatible task
for provider in available_providers:
    task = await self.task_queue.dequeue_task(
        provider_capabilities=provider.capabilities
    )
    if task:
        await self._assign_task_to_provider(task, provider)
```

### 5. Task Assignment

**WorkflowEngine._assign_task_to_provider():**
```python
# Update task status
task.status = TaskStatus.RUNNING
task.started_at = datetime.utcnow()

# CRITICAL: Parameter substitution happens here
await self._substitute_task_parameters(task)

# Delegate to server for actual assignment
await self._server.assign_task_to_provider(task, provider)
```

**WorkflowServer.assign_task_to_provider():**
```python
# Additional parameter substitution (backup/redundancy)
await self._substitute_task_parameters(task)

# Send task to provider via central server
await self.sio.emit('task:assign', {
    'task_id': task.id,
    'workflow_id': task.workflow_id,
    'task_type': task.task_type.value,
    'parameters': task.parameters.to_dict(),  # ← Substituted parameters
    'provider_id': provider.id,
    'provider_socket_id': provider.socket_id,
    ...
})
```

### 6. Parameter Substitution Process

**_substitute_task_parameters():**
```python
# Get workflow and its completed task results
workflow = self.workflows[task.workflow_id]
params_dict = task.parameters.to_dict()

# Find patterns like ${task_TASKID_result}
pattern = r'\$\{task_([a-f0-9\-]+)_result\}'

def replace_match(match):
    task_id = match.group(1)
    if task_id in workflow.task_results:
        return str(workflow.task_results[task_id])
    return match.group(0)  # Keep original if not found

# Recursively substitute in all string values
substituted_params = substitute_recursive(params_dict)
task.parameters = TaskParameters(**substituted_params)
```

### 7. Central Server Message Routing

**Central Server receives 'task:assign':**
```python
# Route to specific provider
await sio.emit('task:execute', task_data, room=provider_socket_id)
```

### 8. Provider Task Execution

**Provider receives 'task:execute':**
```python
# Execute task based on type
if task_type == 'mcp_function':
    result = await execute_mcp_function(parameters)
elif task_type == 'llm_generate':
    result = await execute_llm_generation(parameters)

# Send result back
await sio.emit('task:completed', {
    'task_id': task_id,
    'workflow_id': workflow_id,
    'result': result
})
```

### 9. Task Completion Flow

**Central Server routes 'task:completed' → Workflow Server**

**Workflow Server receives 'task:completed':**
```python
@self.sio.on('task:completed')
async def task_completed(data):
    task_id = data.get('task_id')
    workflow_id = data.get('workflow_id') 
    result = data.get('result')
    
    await self.workflow_engine.on_task_completed(task_id, workflow_id, result)
```

**WorkflowEngine.on_task_completed():**
```python
# Mark task completed in queue (may unblock dependent tasks)
newly_available = await self.task_queue.mark_task_completed(task_id, result)

# Update workflow state
workflow.completed_tasks.append(task_id)
workflow.task_results[task_id] = result  # ← Store for parameter substitution

# Update task object
for task in workflow.tasks:
    if task.id == task_id:
        task.result = result
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.utcnow()

# Check if workflow is complete
if workflow.is_complete():
    await self._complete_workflow(workflow_id)
```

### 10. Workflow Completion

**WorkflowEngine._complete_workflow():**
```python
workflow.status = WorkflowStatus.COMPLETED
workflow.completed_at = datetime.utcnow()

# Broadcast completion to client
await self._server.broadcast_workflow_completed(
    workflow_id=workflow_id,
    status='completed',
    results=workflow.task_results
)
```

**Client receives 'workflow:completed':**
```python
@sio.on('workflow:completed')
def on_workflow_completed(data):
    print(f"🎯 Workflow completed: {data['workflow_id']}")
    print(f"Results: {data['results']}")
```

## Key Message Types

### Client ↔ Workflow Server
- `workflow:submit` - Submit new workflow
- `workflow:submitted` - Confirmation of submission
- `workflow:completed` - Workflow finished notification
- `workflow:status` - Status inquiry
- `workflow:cancel` - Cancel workflow

### Workflow Server ↔ Central Server
- `component:register` - Register as server component
- `task:assign` - Assign task to provider
- `task:completed` - Task completion notification
- `task:failed` - Task failure notification
- `provider:register` - New provider registration
- `provider:disconnected` - Provider disconnection

### Central Server ↔ Providers
- `task:execute` - Execute assigned task
- `task:completed` - Report task completion
- `task:failed` - Report task failure
- `provider:register` - Register provider capabilities

## Critical Success Factors

1. **Workflow ID Assignment**: `Workflow.from_dict()` must use `add_task()` to set `workflow_id`
2. **Parameter Substitution**: Happens at task assignment time, before sending to provider
3. **Task Results Storage**: `workflow.task_results[task_id] = result` enables parameter substitution
4. **Dependency Management**: Task queue respects dependencies and unblocks waiting tasks
5. **Provider Capabilities**: Task scheduling matches task types to provider capabilities

## Error Handling

- **Task Failure**: Provider sends `task:failed`, workflow can continue or stop based on `error_strategy`
- **Provider Disconnection**: Tasks reassigned to other available providers
- **Timeout**: Tasks timeout and can be retried up to `max_retries`
- **Parameter Substitution Failure**: Missing dependencies keep original placeholder patterns

## Performance Considerations

- **Scheduler Interval**: 2-second polling loop balances responsiveness vs. CPU usage
- **Batch Operations**: Task enqueueing happens in batches for efficiency
- **Redis Pipeline**: Task queue operations use Redis pipelines where possible
- **Concurrent Providers**: Multiple providers can execute tasks simultaneously
- **Memory Management**: Completed workflows should be cleaned up periodically

## Example: Combined MCP + LLM Workflow

1. **Submit**: Client submits workflow with 2 tasks (MCP → LLM dependency)
2. **Schedule**: Only MCP task is ready, LLM task waits in pending queue
3. **Execute MCP**: Provider executes `list_files` function, returns directory JSON
4. **Store Result**: `workflow.task_results[mcp_task_id] = directory_json`
5. **Unblock LLM**: MCP completion makes LLM task available
6. **Parameter Substitution**: LLM prompt gets `${task_MCP_ID_result}` replaced with actual directory JSON
7. **Execute LLM**: Ollama processes prompt with real directory data
8. **Complete**: Both tasks done, workflow completes, client notified

This flow enables powerful combinations of external tools (MCP) with AI reasoning (LLM) in a distributed, scalable architecture.