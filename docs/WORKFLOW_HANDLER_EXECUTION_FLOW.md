# Workflow Handler Execution Flow

## Complete Execution Path: How Workflows Get Called and Executed

### Step 1: Task Encounters Workflow Task
```yaml
# Parent workflow has this task:
- id: call_child
  type: workflow
  method: workflow/execute
  params:
    workflow_ref: "child.yaml"
    inputs: {data: "test"}
```

### Step 2: TaskExecutionWorker Processes Task
```python
# In TaskExecutionWorker
async def execute_task(self, task: Task):
    # Routes to WorkflowHandler based on type/method
    handler = self.handlers.get('workflow/v1')
    result = await handler.execute(task)
    # Result has status=WAITING, metadata with submit_workflow=True
```

### Step 3: WorkflowHandler Returns Metadata (STATELESS)
```python
# WorkflowHandler ONLY returns metadata, does NO work
async def _handle_execute(self, task: Task) -> TaskResult:
    child_workflow_id = f"{task.workflow_id}:child:{task.id}:abc123"
    
    return TaskResult(
        status=TaskStatus.WAITING,
        metadata={
            'waiting_for': 'workflow',
            'submit_workflow': True,  # <-- Flag for worker
            'child_workflow_id': child_workflow_id,
            'workflow_ref': 'child.yaml',
            'workflow_inputs': {data: 'test'},
            # ... other metadata
        }
    )
```

### Step 4: TaskExecutionWorker Acts on Metadata
```python
# Back in TaskExecutionWorker after handler returns
async def process_task_result(self, task: Task, result: TaskResult):
    # Check for workflow submission flag
    if result.metadata.get('submit_workflow'):
        # Worker does the ACTUAL submission
        await self._submit_child_workflow(task, result.metadata)
    
    # Task goes to waiting state
    if result.status == TaskStatus.WAITING:
        await self._mark_task_waiting(task, result.metadata)
```

### Step 5: Worker Submits to Redis Stream
```python
async def _submit_child_workflow(self, task: Task, metadata: Dict):
    # Worker writes to submission stream
    submission_stream = f"{{shard:{metadata['child_shard']}}}:workflow:submit"
    
    await self.redis.xadd(submission_stream, {
        b'child_workflow_id': metadata['child_workflow_id'],
        b'workflow_ref': metadata['workflow_ref'],
        b'inputs': json.dumps(metadata['workflow_inputs']),
        b'parent_workflow_id': task.workflow_id,
        b'parent_task_id': task.id,
        # ...
    })
```

### Step 6: WorkflowSubmissionWorker Picks Up
```python
# Separate worker monitors submission stream
class WorkflowSubmissionWorker(BaseWorker):
    def get_base_streams(self):
        return ["workflow:submit"]
    
    async def process_message(self, stream, msg_id, data):
        # 1. Register parent-child relationship
        await self._register_child(data)
        
        # 2. Submit to workflow loader stream
        loader_stream = f"{{shard:{data['child_shard']}}}:workflow:loader"
        await self.redis.xadd(loader_stream, {
            b'workflow_id': data['child_workflow_id'],
            b'workflow_ref': data['workflow_ref'],
            # ...
        })
```

### Step 7: WorkflowLoaderWorker Creates Child
```python
# Existing WorkflowLoaderWorker on target shard
class WorkflowLoaderWorkerV2(BaseWorker):
    async def process_message(self, stream, msg_id, data):
        # Load workflow definition
        workflow = await self._load_workflow(data['workflow_ref'])
        
        # Create tasks for child workflow
        for task_def in workflow['tasks']:
            task = Task(
                workflow_id=data['child_workflow_id'],
                # ... task details
            )
            await self._submit_task(task)
```

### Step 8: Child Workflow Executes
- Child workflow tasks execute normally on target shard
- Just like any other workflow
- No awareness it's a child

### Step 9: Child Workflow Completes
```python
# When last task completes, workflow is marked complete
# This triggers completion event
await self.redis.xadd(
    f"{{shard:{child_shard}}}:workflow:completed",
    {b'workflow_id': child_workflow_id, b'result': result}
)
```

### Step 10: WorkflowMonitorWorker Detects Completion
```python
class WorkflowMonitorWorker(BaseWorker):
    def get_base_streams(self):
        return ["workflow:completed"]
    
    async def process_message(self, stream, msg_id, data):
        # Check if this is a child workflow
        registry = await self.redis.hgetall(
            f"{{shard:0}}:workflow:children:{data['workflow_id']}"
        )
        
        if registry:  # It's a child
            parent_task_id = registry['parent_task_id']
            parent_workflow_id = registry['parent_workflow_id']
            
            # Wake parent task with result
            await self._wake_parent_task(
                parent_workflow_id,
                parent_task_id,
                data['result']
            )
```

### Step 11: Parent Task Wakes Up
```python
async def _wake_parent_task(self, workflow_id, task_id, result):
    # Update task status to READY with result
    task_key = f"{{shard:{get_shard(workflow_id)}}}:task:{task_id}"
    await self.redis.hset(task_key, {
        b'status': b'READY',
        b'result': json.dumps(result)
    })
    
    # Add to ready queue
    ready_stream = f"{{shard:{get_shard(workflow_id)}}}:task:ready"
    await self.redis.xadd(ready_stream, {
        b'task_id': task_id,
        b'workflow_id': workflow_id
    })
```

### Step 12: Parent Task Continues
```python
# TaskExecutionWorker picks up the ready task
# Task now has the child workflow's result
# Parent workflow continues with next tasks
```

## Key Points About This Design

### 1. Handler is Completely Stateless
- WorkflowHandler NEVER touches Redis
- Only computes metadata and returns it
- Similar to SignalHandler pattern

### 2. Workers Do All the Work
- TaskExecutionWorker submits based on metadata
- WorkflowSubmissionWorker handles cross-shard submission
- WorkflowMonitorWorker handles completion
- WorkflowLoaderWorker creates actual workflow

### 3. Stream-Based Communication
- All communication via Redis Streams
- No polling, everything is event-driven
- Workers monitor specific streams

### 4. Cross-Shard Capable
- Child can run on different shard
- Registry tracks relationships
- Notifications cross shard boundaries

## Comparison with Direct Execution

### What We DON'T Do (Would Break Statelessness):
```python
# BAD - Handler accessing Redis directly
class WorkflowHandler(BaseHandler):
    async def execute(self, task):
        # DON'T DO THIS - breaks statelessness!
        await self.redis.xadd(...)  # NO!
        result = await self.redis.get(...)  # NO!
```

### What We DO (Maintains Statelessness):
```python
# GOOD - Handler returns metadata only
class WorkflowHandler(BaseHandler):
    async def execute(self, task):
        # Only compute and return metadata
        return TaskResult(
            status=TaskStatus.WAITING,
            metadata={'submit_workflow': True, ...}
        )
```

## Benefits of This Approach

1. **Testability**: Handlers can be tested without Redis
2. **Scalability**: Workers can be scaled independently
3. **Maintainability**: Clear separation of concerns
4. **Reliability**: Workers handle retries and failures
5. **Flexibility**: Easy to add new workflow features

## Example Sequence Diagram

```
ParentTask -> WorkflowHandler: execute(workflow_task)
WorkflowHandler -> ParentTask: WAITING + metadata
ParentTask -> TaskExecutionWorker: process result
TaskExecutionWorker -> Redis: xadd(workflow:submit)
WorkflowSubmissionWorker -> Redis: xread(workflow:submit)
WorkflowSubmissionWorker -> Redis: xadd(workflow:loader)
WorkflowLoaderWorker -> Redis: xread(workflow:loader)
WorkflowLoaderWorker -> ChildWorkflow: create tasks
ChildWorkflow -> ChildWorkflow: execute
ChildWorkflow -> Redis: xadd(workflow:completed)
WorkflowMonitorWorker -> Redis: xread(workflow:completed)
WorkflowMonitorWorker -> ParentTask: wake with result
ParentTask -> TaskExecutionWorker: continue execution
```