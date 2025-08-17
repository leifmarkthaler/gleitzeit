# Python API Reference

## GleitzeitClient

The main client for interacting with Gleitzeit programmatically.

```python
from gleitzeit.client import GleitzeitClient
```

### Constructor

```python
GleitzeitClient(
    persistence_type: Optional[str] = None,
    redis_url: Optional[str] = None,
    sql_connection: Optional[str] = None,
    sql_db_path: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None
)
```

**Parameters:**
- `persistence_type`: Force specific persistence ("redis", "sql", "memory", "auto")
- `redis_url`: Redis connection URL (e.g., "redis://localhost:6379")
- `sql_connection`: SQL connection string for databases
- `sql_db_path`: SQLite database path (default: `~/.gleitzeit/gleitzeit.db`)
- `config`: Additional configuration dictionary

### Initialization

```python
async def initialize() -> None
```
Initialize the client and persistence layer with automatic fallback.

```python
async def shutdown() -> None
```
Clean shutdown of client and all resources.

### Task Management

#### Submit Task

```python
async def submit_task(
    name: str,
    protocol: str,
    method: str,
    params: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    priority: int = 0,
    queue_name: str = "default"
) -> Task
```

Submit a single task for execution.

**Parameters:**
- `name`: Human-readable task name
- `protocol`: Protocol identifier (e.g., "llm/v1", "python/v1", "mcp/v1")
- `method`: Method to execute (e.g., "chat", "execute", "tool.add")
- `params`: Task parameters
- `metadata`: Additional metadata
- `priority`: Task priority (higher = more urgent)
- `queue_name`: Target queue name

**Returns:** Task object with ID and status

**Example:**
```python
task = await client.submit_task(
    name="Generate summary",
    protocol="llm/v1",
    method="chat",
    params={
        "model": "llama3.2",
        "messages": [
            {"role": "user", "content": "Summarize this text..."}
        ]
    }
)
```

#### Get Task Status

```python
async def get_task(task_id: str) -> Optional[Task]
async def get_task_status(task_id: str) -> Optional[str]
async def get_task_result(task_id: str) -> Optional[TaskResult]
```

Retrieve task information, status, or results.

#### Wait for Task Completion

```python
async def wait_for_task(
    task_id: str,
    timeout: Optional[float] = None,
    poll_interval: float = 1.0
) -> Optional[TaskResult]
```

Wait for a task to complete and return its result.

**Parameters:**
- `task_id`: Task ID to wait for
- `timeout`: Maximum time to wait in seconds
- `poll_interval`: Interval between status checks

#### Cancel Task

```python
async def cancel_task(task_id: str) -> bool
```

Cancel a queued task (cannot cancel running tasks).

### Workflow Management

#### Submit Workflow

```python
async def submit_workflow(
    name: str,
    tasks: List[Dict[str, Any]],
    metadata: Optional[Dict[str, Any]] = None
) -> Workflow
```

Submit a workflow with multiple tasks.

**Parameters:**
- `name`: Workflow name
- `tasks`: List of task definitions
- `metadata`: Workflow metadata

**Example:**
```python
workflow = await client.submit_workflow(
    name="Document Processing",
    tasks=[
        {
            "name": "extract_text",
            "protocol": "python/v1",
            "method": "execute",
            "params": {"code": "..."}
        },
        {
            "name": "summarize",
            "protocol": "llm/v1",
            "method": "chat",
            "params": {
                "model": "llama3.2",
                "messages": [...]
            },
            "dependencies": ["extract_text"]
        }
    ]
)
```

#### Get Workflow Information

```python
async def get_workflow(workflow_id: str) -> Optional[Workflow]
async def get_workflow_execution(execution_id: str) -> Optional[WorkflowExecution]
async def get_workflow_tasks(workflow_id: str) -> List[Task]
```

Retrieve workflow information and associated tasks.

### Resource Management

#### Register Resource

```python
async def register_resource(
    hub_id: str,
    instance_id: str,
    instance_data: Dict[str, Any]
) -> bool
```

Register a new resource instance with a hub.

#### Get Resource Information

```python
async def get_resource(instance_id: str) -> Optional[Dict[str, Any]]
async def list_resources(hub_id: str) -> List[Dict[str, Any]]
```

Retrieve resource information.

#### Resource Metrics

```python
async def save_resource_metrics(
    hub_id: str,
    instance_id: str,
    metrics: Dict[str, Any]
) -> bool

async def get_resource_metrics(
    hub_id: str,
    instance_id: Optional[str] = None
) -> Optional[ResourceMetrics]
```

Save and retrieve resource metrics.

#### Resource Utilization

```python
async def get_resource_utilization(hub_id: str) -> Dict[str, Any]
```

Get aggregated resource utilization for a hub.

**Returns:**
```python
{
    "total_instances": 5,
    "healthy_instances": 4,
    "unhealthy_instances": 1,
    "utilization_percent": 80.0
}
```

### Cross-Domain Operations

#### Link Tasks to Resources

```python
async def get_tasks_for_resource(resource_id: str) -> List[Task]
async def get_resource_for_task(task_id: str) -> Optional[Dict[str, Any]]
```

Query relationships between tasks and resources.

### Statistics and Monitoring

```python
async def get_task_statistics() -> Dict[str, int]
```

Get task execution statistics.

**Returns:**
```python
{
    "total": 100,
    "queued": 10,
    "running": 5,
    "completed": 80,
    "failed": 5
}
```

```python
async def get_queue_statistics() -> Dict[str, Any]
```

Get queue statistics for all queues.

### System Operations

#### Health Check

```python
async def health_check() -> Dict[str, Any]
```

Perform comprehensive health check.

**Returns:**
```python
{
    "status": "healthy",
    "persistence": {
        "backend": "redis",
        "status": "connected"
    },
    "queues": {
        "total": 3,
        "active": 3
    },
    "uptime_seconds": 3600
}
```

#### Cleanup

```python
async def cleanup_old_data(days: int = 30) -> int
```

Clean up data older than specified days.

**Returns:** Number of items cleaned

### Context Manager Usage

```python
async with await create_client() as client:
    # Client is initialized and ready
    task = await client.submit_task(...)
    result = await client.wait_for_task(task.id)
    # Client is automatically shut down
```

## Complete Examples

### Basic Task Execution

```python
import asyncio
from gleitzeit.client import GleitzeitClient

async def main():
    # Create and initialize client
    client = GleitzeitClient(persistence_type="redis")
    await client.initialize()
    
    try:
        # Submit an LLM task
        task = await client.submit_task(
            name="Generate story",
            protocol="llm/v1",
            method="chat",
            params={
                "model": "llama3.2",
                "messages": [
                    {"role": "user", "content": "Write a short story about AI"}
                ],
                "temperature": 0.8
            }
        )
        
        print(f"Task submitted: {task.id}")
        
        # Wait for completion
        result = await client.wait_for_task(task.id, timeout=60)
        
        if result:
            print(f"Result: {result.output}")
        else:
            print("Task timed out")
            
    finally:
        await client.shutdown()

asyncio.run(main())
```

### Workflow with Dependencies

```python
import asyncio
from gleitzeit.client import GleitzeitClient

async def main():
    client = GleitzeitClient()
    await client.initialize()
    
    try:
        # Submit workflow with dependent tasks
        workflow = await client.submit_workflow(
            name="Data Analysis Pipeline",
            tasks=[
                {
                    "name": "fetch_data",
                    "protocol": "python/v1",
                    "method": "execute",
                    "params": {
                        "code": """
import json
data = {'values': [1, 2, 3, 4, 5]}
result = json.dumps(data)
                        """
                    }
                },
                {
                    "name": "analyze_data",
                    "protocol": "python/v1",
                    "method": "execute",
                    "params": {
                        "code": """
import json
# Use result from previous task
data = json.loads('${fetch_data.result}')
average = sum(data['values']) / len(data['values'])
result = f"Average: {average}"
                        """
                    },
                    "dependencies": ["fetch_data"]
                },
                {
                    "name": "generate_report",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "params": {
                        "model": "llama3.2",
                        "messages": [
                            {
                                "role": "user",
                                "content": "Create a report based on: ${analyze_data.result}"
                            }
                        ]
                    },
                    "dependencies": ["analyze_data"]
                }
            ]
        )
        
        print(f"Workflow submitted: {workflow.id}")
        
        # Monitor workflow progress
        tasks = await client.get_workflow_tasks(workflow.id)
        for task in tasks:
            result = await client.wait_for_task(task.id, timeout=120)
            if result:
                print(f"{task.name}: {result.status}")
                
    finally:
        await client.shutdown()

asyncio.run(main())
```

### Batch Processing

```python
import asyncio
from pathlib import Path
from gleitzeit.client import GleitzeitClient

async def process_documents(directory: str, pattern: str = "*.txt"):
    client = GleitzeitClient()
    await client.initialize()
    
    try:
        # Find all matching files
        files = list(Path(directory).glob(pattern))
        tasks = []
        
        # Submit task for each file
        for file_path in files:
            with open(file_path) as f:
                content = f.read()
            
            task = await client.submit_task(
                name=f"Process {file_path.name}",
                protocol="llm/v1",
                method="chat",
                params={
                    "model": "llama3.2",
                    "messages": [
                        {
                            "role": "user",
                            "content": f"Summarize this document:\n\n{content}"
                        }
                    ]
                }
            )
            tasks.append((file_path, task))
        
        # Wait for all tasks to complete
        results = {}
        for file_path, task in tasks:
            result = await client.wait_for_task(task.id)
            if result:
                results[str(file_path)] = result.output
        
        return results
        
    finally:
        await client.shutdown()

# Usage
results = asyncio.run(process_documents("./documents", "*.md"))
for file, summary in results.items():
    print(f"{file}:\n{summary}\n")
```

### Resource Monitoring

```python
import asyncio
from gleitzeit.client import GleitzeitClient

async def monitor_resources():
    client = GleitzeitClient()
    await client.initialize()
    
    try:
        while True:
            # Get resource utilization
            ollama_util = await client.get_resource_utilization("ollama-hub")
            docker_util = await client.get_resource_utilization("docker-hub")
            
            # Get task statistics
            task_stats = await client.get_task_statistics()
            
            # Get queue statistics
            queue_stats = await client.get_queue_statistics()
            
            # Display dashboard
            print("\n" + "="*50)
            print("RESOURCE MONITOR")
            print("="*50)
            
            print("\nOllama Hub:")
            print(f"  Instances: {ollama_util['total_instances']}")
            print(f"  Healthy: {ollama_util['healthy_instances']}")
            print(f"  Utilization: {ollama_util['utilization_percent']}%")
            
            print("\nDocker Hub:")
            print(f"  Instances: {docker_util['total_instances']}")
            print(f"  Healthy: {docker_util['healthy_instances']}")
            print(f"  Utilization: {docker_util['utilization_percent']}%")
            
            print("\nTask Statistics:")
            for status, count in task_stats.items():
                print(f"  {status}: {count}")
            
            print("\nQueue Statistics:")
            for queue_name, stats in queue_stats.items():
                print(f"  {queue_name}: {stats['size']} tasks")
            
            await asyncio.sleep(5)
            
    except KeyboardInterrupt:
        print("\nMonitoring stopped")
    finally:
        await client.shutdown()

asyncio.run(monitor_resources())
```

## Error Handling

### Common Exceptions

```python
from gleitzeit.core.errors import (
    TaskExecutionError,
    WorkflowValidationError,
    ResourceUnavailableError,
    PersistenceError
)

async def safe_task_execution():
    client = GleitzeitClient()
    await client.initialize()
    
    try:
        task = await client.submit_task(...)
        result = await client.wait_for_task(task.id)
        
    except TaskExecutionError as e:
        print(f"Task failed: {e}")
        
    except ResourceUnavailableError as e:
        print(f"No resources available: {e}")
        
    except PersistenceError as e:
        print(f"Storage error: {e}")
        
    finally:
        await client.shutdown()
```

## Configuration

### Environment Variables

```bash
# Persistence
export GLEITZEIT_PERSISTENCE_TYPE=redis
export GLEITZEIT_REDIS_URL=redis://localhost:6379
export GLEITZEIT_SQL_DB_PATH=~/.gleitzeit/gleitzeit.db

# Logging
export GLEITZEIT_LOG_LEVEL=INFO
```

### Programmatic Configuration

```python
config = {
    "persistence": {
        "type": "redis",
        "redis": {
            "url": "redis://localhost:6379",
            "key_prefix": "gleitzeit"
        }
    },
    "execution": {
        "max_parallel_tasks": 20,
        "task_timeout": 300
    }
}

client = GleitzeitClient(config=config)
```

## Best Practices

1. **Always use context managers or explicitly call shutdown**
   ```python
   async with await create_client() as client:
       # Your code here
   ```

2. **Handle task timeouts gracefully**
   ```python
   result = await client.wait_for_task(task_id, timeout=60)
   if result is None:
       # Handle timeout
   ```

3. **Use appropriate persistence backend**
   - Redis: Production, distributed systems
   - SQLite: Development, single-instance
   - Memory: Testing only

4. **Monitor resource utilization**
   ```python
   util = await client.get_resource_utilization("ollama-hub")
   if util['utilization_percent'] > 90:
       # Scale up or throttle submissions
   ```

5. **Clean up old data regularly**
   ```python
   # Run daily
   deleted = await client.cleanup_old_data(days=7)
   ```

## Migration from v0.0.4

Key changes in v0.0.5:

1. **Unified Persistence**: Single adapter for all storage needs
2. **Hub-Provider Architecture**: Clean separation of resource management
3. **Cross-Domain Operations**: Link tasks to resources
4. **Automatic Fallback**: Redis → SQLite → Memory

Migration example:

```python
# Old (v0.0.4)
client = GleitzeitClient(backend="redis")

# New (v0.0.5)
client = GleitzeitClient(persistence_type="redis")
await client.initialize()  # Required initialization
```