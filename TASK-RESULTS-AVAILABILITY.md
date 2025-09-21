# Task Results Availability

## YES - Task results are fully available! ✅

Gleitzeit stores and provides access to all task results after completion.

## How Results Are Stored

### 1. In ScalableRedisAdapter
```python
# When saving a task (line 609)
"result": json.dumps(getattr(task, 'result', None)) if getattr(task, 'result', None) else ""

# When retrieving a task (line 683)
result=json.loads(task_data['result']) if task_data.get('result') else None
```

Results are:
- Stored as JSON in Redis
- Persisted with the task data
- Available immediately after task completion
- Preserved even after workflow completion

### 2. In Task Model
```python
class Task(BaseModel):
    result: Optional[Any] = None  # Task result stored here
    
class TaskResult(BaseModel):
    task_id: str
    workflow_id: Optional[str]
    status: TaskStatus
    result: Optional[Any]  # Actual result data
    error: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    duration_seconds: Optional[float]
```

### 3. In Workflow Model
```python
class Workflow(BaseModel):
    task_results: Dict[str, Any]  # Task ID -> Result mapping
    
    def mark_task_completed(self, task_id: str, result: Any):
        """Mark task completed and store result"""
        self.task_results[task_id] = result
```

## How to Retrieve Results

### 1. Get Individual Task Result
```python
# Using client
task = await client.get_task(task_id)
if task.status == TaskStatus.COMPLETED:
    result = task.result  # Direct access

# Or get TaskResult object
task_result = await client.get_task_result(task_id)
if task_result:
    actual_result = task_result.result
    duration = task_result.duration_seconds
```

### 2. Get All Workflow Results
```python
# Get all results for a workflow
results = await client.get_workflow_results(workflow_id)

# Results is a list of task results
for result in results:
    print(f"Task {result['task_id']}: {result['result']}")
```

### 3. Wait for Task Completion
```python
# Submit and wait for result
task = await client.submit_task(task_data)
result = await client.wait_for_task(task.id, timeout=60)

if result:
    print(f"Task completed with: {result.result}")
else:
    print("Task timed out or failed")
```

### 4. Get Results from Workflow
```python
# Submit workflow and wait
workflow = await client.submit_workflow(workflow_data)
await client.wait_for_workflow(workflow.id)

# Get the workflow with results
workflow = await client.get_workflow(workflow.id)

# Access results directly
for task_id, result in workflow.task_results.items():
    print(f"Task {task_id}: {result}")
```

## API Endpoints for Results

### 1. Get Task Result
```http
GET /api/v1/tasks/{task_id}/result

Response:
{
    "task_id": "task_123",
    "status": "completed",
    "result": {"data": "processed", "count": 42},
    "duration_seconds": 2.5
}
```

### 2. Get Workflow Results
```http
GET /api/v1/workflows/{workflow_id}/results

Response:
{
    "items": [
        {
            "task_id": "task_1",
            "result": {"output": "data1"},
            "status": "completed"
        },
        {
            "task_id": "task_2",
            "result": {"output": "data2"},
            "status": "completed"
        }
    ]
}
```

## Result Types Supported

### 1. Simple Values
```python
task.result = 42
task.result = "processed text"
task.result = True
```

### 2. Complex Objects
```python
task.result = {
    "processed_items": 100,
    "errors": [],
    "metrics": {"duration": 2.5, "memory": "120MB"}
}
```

### 3. Lists and Arrays
```python
task.result = [1, 2, 3, 4, 5]
task.result = [{"id": 1}, {"id": 2}]
```

### 4. Large Results
Results are JSON serialized, so they should be kept reasonable in size.
For large data, consider:
- Storing reference/URL to data
- Using external storage (S3, etc.)
- Streaming results separately

## Result Persistence

### Duration
- Results persist as long as the task exists in Redis
- No automatic expiration by default
- Can be configured with TTL if needed

### Reliability
- Results are persisted to Redis immediately
- Survive system restarts (Redis persistence)
- Available across all nodes in cluster

## Example: Complete Flow

```python
import asyncio
from gleitzeit import GleitzeitClient

async def process_with_results():
    client = GleitzeitClient()
    await client.initialize()
    
    # Submit task
    task = await client.submit_task({
        "name": "Process Data",
        "protocol": "python",
        "method": "process",
        "params": {"input": "data"}
    })
    
    print(f"Task {task.id} submitted")
    
    # Wait for completion
    result = await client.wait_for_task(task.id)
    
    if result and result.status == "completed":
        print(f"Result: {result.result}")
        print(f"Duration: {result.duration_seconds}s")
    else:
        print(f"Task failed: {result.error if result else 'timeout'}")
    
    # Alternative: Get result later
    task = await client.get_task(task.id)
    if task.result:
        print(f"Stored result: {task.result}")

asyncio.run(process_with_results())
```

## Result Features

### ✅ Available Features
1. **Immediate Access**: Results available as soon as task completes
2. **Persistence**: Results stored in Redis with task data
3. **Full Objects**: Complex JSON-serializable objects supported
4. **Metadata**: Duration, timestamps, error info included
5. **Bulk Retrieval**: Get all workflow results at once
6. **API Access**: REST endpoints for result retrieval
7. **Event Notifications**: Events emitted when results ready

### ⚠️ Limitations
1. **Size**: Large results impact Redis memory
2. **Binary Data**: Must be base64 encoded
3. **Streaming**: No built-in streaming for large results
4. **Expiration**: No automatic cleanup (manual TTL needed)

## Conclusion

**YES - Task results are fully available and easily accessible!**

Gleitzeit provides comprehensive result storage and retrieval:
- Results stored persistently in Redis
- Multiple ways to access (direct, wait, bulk)
- Support for complex data structures
- Available via API and client libraries
- Preserved across system restarts

The result system is production-ready and handles the complete lifecycle from task execution to result retrieval.