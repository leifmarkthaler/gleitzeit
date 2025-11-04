# Gleitzeit Python Client Guide

**Version:** 0.0.7
**Last Updated:** November 2025

Complete guide for using the Gleitzeit Python Client SDK.

---

## Table of Contents

1. [Installation](#installation)
2. [Quick Start](#quick-start)
3. [Client Overview](#client-overview)
4. [Authentication](#authentication)
5. [Workflow Operations](#workflow-operations)
6. [Task Operations](#task-operations)
7. [WebSocket Monitoring](#websocket-monitoring)
8. [System Monitoring](#system-monitoring)
9. [Working with Dependencies](#working-with-dependencies)
10. [Error Handling](#error-handling)
11. [Best Practices](#best-practices)
12. [Examples](#examples)

---

## Installation

```bash
# Install Gleitzeit with client dependencies
cd /path/to/gleitzeit-0.0.7
pip install -e .
```

---

## Quick Start

### Simple Workflow Submission

```python
import asyncio
from gleitzeit.client import GleitzeitClient

async def main():
    async with GleitzeitClient('http://localhost:8000') as client:
        # Define workflow
        workflow = {
            'name': 'Hello World',
            'tasks': [{
                'id': 'task1',
                'type': 'python',
                'params': {
                    'code': 'result = {"message": "Hello, World!"}'
                }
            }]
        }

        # Submit and wait
        response = await client.submit_workflow(workflow)
        print(f"Submitted: {response.workflow_id}")

        status = await client.wait_for_workflow(response.workflow_id, timeout=60)
        print(f"Status: {status.status}")

asyncio.run(main())
```

---

## Client Overview

### Architecture

The GleitzeitClient uses a modular mixin-based architecture:

```python
GleitzeitClient
├── AuthMixin          # Authentication & session management
├── RetryMixin         # Retry logic & error handling
├── WorkflowMixin      # Workflow operations
├── TaskMixin          # Task operations
├── MonitoringMixin    # Health checks & metrics
├── WebSocketMixin     # Real-time monitoring
└── BaseClient         # Core HTTP functionality
```

### Initialization

```python
from gleitzeit.client import GleitzeitClient

# Basic initialization (with auto-login)
client = GleitzeitClient('http://localhost:8000')

# With custom configuration
client = GleitzeitClient(
    api_url='http://localhost:8000',
    auto_login=True,              # Automatic session creation
    timeout=30,                   # Request timeout in seconds
    pool_size=5,                  # Connection pool size
    retry_config={                # Custom retry configuration
        'max_retries': 3,
        'backoff_factor': 2.0
    }
)
```

---

## Authentication

### Auto-Login (Default)

The client automatically creates a session on connection:

```python
async with GleitzeitClient(auto_login=True) as client:
    # Auto-login happens automatically
    response = await client.submit_workflow(workflow)
```

### Manual Session Management

```python
async with GleitzeitClient(auto_login=False) as client:
    # Create session manually
    session_id = await client.create_session("username", "password")
    print(f"Session ID: {session_id}")

    # Use the client...

    # Destroy session
    await client.destroy_session()
```

### Session Validation

```python
# Validate existing session
is_valid = await client.validate_session(session_id)

# Get current user
user = await client.get_current_user()
print(f"User: {user.username}, Role: {user.role}")
```

---

## Workflow Operations

### Submit Workflow

```python
workflow = {
    'name': 'Data Processing',
    'tasks': [{
        'id': 'process',
        'type': 'python',
        'params': {
            'code': '''
data = [1, 2, 3, 4, 5]
result = {"sum": sum(data), "count": len(data)}
'''
        }
    }]
}

response = await client.submit_workflow(workflow)
print(f"Workflow ID: {response.workflow_id}")
```

### Batch Submission

```python
workflows = [workflow1, workflow2, workflow3]

responses = await client.submit_workflows_batch(
    workflows,
    max_concurrent=5  # Submit up to 5 workflows concurrently
)

for response in responses:
    print(f"Submitted: {response.workflow_id}")
```

### Get Workflow Status

```python
status = await client.get_workflow_status(workflow_id)

print(f"Status: {status.status}")
print(f"Total tasks: {status.total_tasks}")
print(f"Completed: {status.completed_tasks}")
print(f"Failed: {status.failed_tasks}")
```

### Wait for Completion (Polling)

```python
# Poll every 2 seconds, timeout after 5 minutes
final_status = await client.wait_for_workflow(
    workflow_id,
    timeout=300,
    poll_interval=2
)

if final_status.status == 'completed':
    print("✓ Workflow completed successfully")
elif final_status.status == 'failed':
    print("✗ Workflow failed")
```

### Cancel Workflow

```python
result = await client.cancel_workflow(workflow_id)
print(f"Cancelled: {result}")
```

### List Workflows

```python
# List all workflows
workflows = await client.list_workflows(limit=100)

# Filter by status
completed = await client.list_workflows(status='completed', limit=50)
failed = await client.list_workflows(status='failed', limit=50)

for wf in workflows:
    print(f"{wf.workflow_id}: {wf.status}")
```

---

## Task Operations

### Get Task Details

```python
task = await client.get_task(task_id, workflow_id=workflow_id)

print(f"Task: {task.task_id}")
print(f"Status: {task.status}")
print(f"Result: {task.result}")
```

### Get Task Result

```python
result = await client.get_task_result(task_id, workflow_id=workflow_id)
print(f"Result: {result}")
```

### Get Task Logs

```python
logs = await client.get_task_logs(task_id, workflow_id=workflow_id)
for log in logs:
    print(log)
```

### List Tasks

```python
# List all tasks in a workflow
tasks = await client.list_tasks(workflow_id=workflow_id)

# List all failed tasks
failed_tasks = await client.get_failed_tasks(workflow_id=workflow_id, limit=100)

for task in tasks:
    print(f"{task.task_id}: {task.status}")
```

### Retry Failed Tasks

```python
# Retry a specific task
await client.retry_task(task_id, workflow_id=workflow_id)

# Retry all failed tasks in a workflow
await client.retry_failed_tasks(workflow_id)
```

---

## WebSocket Monitoring

### Real-Time Workflow Monitoring

```python
import asyncio

async def main():
    async with GleitzeitClient() as client:
        workflow_id = "..."

        # Create completion event
        done = asyncio.Event()

        # Monitor with callbacks
        await client.wait_for_workflow_async(
            workflow_id,
            on_complete=lambda e: done.set(),
            on_failure=lambda e: print(f"Failed: {e}"),
            timeout=300
        )

        # Wait for completion
        await done.wait()
        print("✓ Workflow completed!")

asyncio.run(main())
```

### Stream Workflow Events

```python
async for event in client.stream_workflow_events(workflow_id):
    print(f"Event: {event.event_type}")
    print(f"Data: {event.data}")

    if event.event_type in ['workflow:completed', 'workflow:failed']:
        break
```

### Monitor Multiple Workflows

```python
workflow_ids = ['wf1', 'wf2', 'wf3']

async for event in client.watch_multiple_workflows(workflow_ids):
    print(f"Workflow {event.workflow_id}: {event.event_type}")
```

### Task-Level Monitoring

```python
await client.wait_for_task_ws(
    task_id,
    on_complete=lambda e: print(f"Task completed: {e}"),
    on_failure=lambda e: print(f"Task failed: {e}"),
    timeout=60
)
```

---

## System Monitoring

### Health Checks

```python
# Basic health check
health = await client.health_check()
print(f"Status: {health.status}")

# Detailed system health
system_health = await client.get_system_health()
print(f"Redis: {system_health.redis}")
print(f"Workers: {system_health.workers}")
```

### Worker Status

```python
workers = await client.get_workers_status()

for worker in workers:
    print(f"Worker: {worker.worker_type}-{worker.worker_id}")
    print(f"Status: {worker.status}")
    print(f"Tasks: {worker.tasks_processed}")
```

### System Metrics

```python
# Get system-wide metrics
metrics = await client.get_system_metrics()
print(f"Total workflows: {metrics.total_workflows}")
print(f"Active workflows: {metrics.active_workflows}")

# Get workflow metrics
wf_metrics = await client.get_workflow_metrics(workflow_id)
print(f"Duration: {wf_metrics.duration}")

# Get task metrics
task_metrics = await client.get_task_metrics(task_id, workflow_id)
print(f"Execution time: {task_metrics.execution_time}")
```

### Queue Depths

```python
queues = await client.get_queue_depths()

for queue_name, depth in queues.items():
    print(f"{queue_name}: {depth} pending")
```

---

## Working with Dependencies

### Task Dependencies

Tasks can depend on the results of other tasks. Dependency results are passed via the `inputs` variable:

```python
workflow = {
    'name': 'Data Pipeline',
    'tasks': [
        {
            'id': 'fetch_data',
            'type': 'python',
            'params': {
                'code': '''
# Fetch data
data = [1, 2, 3, 4, 5]
result = {"data": data, "count": len(data)}
'''
            }
        },
        {
            'id': 'process_data',
            'type': 'python',
            'depends_on': ['fetch_data'],  # Depends on fetch_data
            'params': {
                'code': '''
# Access previous task result via inputs
fetch_result = inputs.get("fetch_data", {})
data = fetch_result.get("data", [])

# Process the data
processed = [x * 2 for x in data]
result = {"processed": processed, "sum": sum(processed)}
'''
            }
        },
        {
            'id': 'save_results',
            'type': 'python',
            'depends_on': ['process_data'],
            'params': {
                'code': '''
# Access process_data result
process_result = inputs.get("process_data", {})
print(f"Saving results: {process_result}")
result = {"status": "saved", "data": process_result}
'''
            }
        }
    ]
}
```

**Important:** Use `inputs` variable to access dependency results, not `dependencies`.

### Parallel Tasks with Aggregation

```python
workflow = {
    'name': 'Parallel Processing',
    'tasks': [
        {
            'id': 'task_a',
            'type': 'python',
            'params': {
                'code': 'result = {"value": 10}'
            }
        },
        {
            'id': 'task_b',
            'type': 'python',
            'params': {
                'code': 'result = {"value": 20}'
            }
        },
        {
            'id': 'task_c',
            'type': 'python',
            'params': {
                'code': 'result = {"value": 30}'
            }
        },
        {
            'id': 'combine',
            'type': 'python',
            'depends_on': ['task_a', 'task_b', 'task_c'],
            'params': {
                'code': '''
# Combine results from all three parallel tasks
result_a = inputs.get("task_a", {})
result_b = inputs.get("task_b", {})
result_c = inputs.get("task_c", {})

total = result_a.get("value", 0) + result_b.get("value", 0) + result_c.get("value", 0)
result = {"total": total}  # Should be 60
'''
            }
        }
    ]
}
```

---

## Error Handling

### Automatic Retries

The client automatically retries failed requests with exponential backoff:

```python
client = GleitzeitClient(
    retry_config={
        'max_retries': 3,
        'backoff_factor': 2.0,
        'max_backoff': 30.0
    }
)
```

### Exception Handling

```python
from gleitzeit.client.auth import AuthenticationError, AuthorizationError

try:
    response = await client.submit_workflow(workflow)
except AuthenticationError:
    print("Authentication failed - check your credentials")
except AuthorizationError:
    print("Not authorized to perform this action")
except asyncio.TimeoutError:
    print("Request timed out")
except Exception as e:
    print(f"Error: {e}")
```

### Workflow Failures

```python
status = await client.wait_for_workflow(workflow_id, timeout=300)

if status.status == 'failed':
    # Get failed tasks
    failed_tasks = await client.get_failed_tasks(workflow_id)

    for task in failed_tasks:
        print(f"Task {task.task_id} failed: {task.error}")

        # Get detailed logs
        logs = await client.get_task_logs(task.task_id, workflow_id)
        print(logs)
```

---

## Best Practices

### 1. Use Context Managers

Always use `async with` for automatic connection management:

```python
async with GleitzeitClient() as client:
    # Client automatically connects and closes
    response = await client.submit_workflow(workflow)
```

### 2. Handle Timeouts Appropriately

Set timeouts based on expected workflow duration:

```python
# Long-running workflow
status = await client.wait_for_workflow(
    workflow_id,
    timeout=3600,  # 1 hour
    poll_interval=10  # Check every 10 seconds
)
```

### 3. Use WebSockets for Real-Time Monitoring

WebSockets are more efficient than polling for monitoring:

```python
# Good: WebSocket monitoring
await client.wait_for_workflow_async(workflow_id, on_complete=...)

# Less efficient: Polling
await client.wait_for_workflow(workflow_id, poll_interval=2)
```

### 4. Batch Operations for Scale

Use batch operations when submitting multiple workflows:

```python
# Submit 100 workflows efficiently
responses = await client.submit_workflows_batch(
    workflows,
    max_concurrent=10
)
```

### 5. Access Dependencies via `inputs`

Always use `inputs` to access task dependency results:

```python
# ✓ Correct
prev_result = inputs.get("previous_task", {})

# ✗ Wrong (deprecated)
prev_result = dependencies.get("previous_task", {})
```

---

## Examples

### Example 1: Simple REST API Usage (No SDK)

```python
import requests

API_URL = "http://localhost:8000"

# Submit workflow
workflow = {
    "name": "Simple Task",
    "tasks": [{
        "id": "task1",
        "type": "python",
        "params": {
            "code": "result = 2 + 2"
        }
    }]
}

response = requests.post(
    f"{API_URL}/workflows/submit",
    json={"workflow": workflow}
)

workflow_id = response.json()["workflow_id"]
print(f"Submitted: {workflow_id}")

# Check status
status_response = requests.get(f"{API_URL}/workflows/{workflow_id}")
status = status_response.json()

print(f"Status: {status['state']['status']}")
```

### Example 2: Data Processing Pipeline

```python
import asyncio
from gleitzeit.client import GleitzeitClient

async def data_pipeline():
    async with GleitzeitClient() as client:
        workflow = {
            'name': 'ETL Pipeline',
            'tasks': [
                {
                    'id': 'extract',
                    'type': 'python',
                    'params': {
                        'code': '''
import json
# Simulate data extraction
data = [
    {"id": 1, "value": 100},
    {"id": 2, "value": 200},
    {"id": 3, "value": 300}
]
result = {"records": data, "count": len(data)}
'''
                    }
                },
                {
                    'id': 'transform',
                    'type': 'python',
                    'depends_on': ['extract'],
                    'params': {
                        'code': '''
# Get extracted data
extract_result = inputs.get("extract", {})
records = extract_result.get("records", [])

# Transform: double all values
transformed = [
    {**record, "value": record["value"] * 2}
    for record in records
]
result = {"transformed": transformed}
'''
                    }
                },
                {
                    'id': 'load',
                    'type': 'python',
                    'depends_on': ['transform'],
                    'params': {
                        'code': '''
# Get transformed data
transform_result = inputs.get("transform", {})
data = transform_result.get("transformed", [])

# Simulate loading to database
print(f"Loading {len(data)} records...")
for record in data:
    print(f"  Record {record['id']}: {record['value']}")

result = {"loaded_count": len(data), "status": "success"}
'''
                    }
                }
            ]
        }

        # Submit workflow
        response = await client.submit_workflow(workflow)
        print(f"✓ Submitted ETL pipeline: {response.workflow_id}")

        # Wait for completion with WebSocket
        done = asyncio.Event()

        await client.wait_for_workflow_async(
            response.workflow_id,
            on_complete=lambda e: done.set(),
            on_failure=lambda e: print(f"Pipeline failed: {e}"),
            timeout=300
        )

        await done.wait()

        # Get final status
        status = await client.get_workflow_status(response.workflow_id)
        print(f"✓ Pipeline completed: {status.status}")

        # Get load task result
        tasks = await client.get_workflow_tasks(response.workflow_id)
        load_task = next((t for t in tasks if 'load' in str(t)), None)
        if load_task:
            # Tasks may be returned as dicts
            task_id = load_task.get('task_id') if isinstance(load_task, dict) else load_task.task_id
            result = await client.get_task_result(task_id, response.workflow_id)
            print(f"✓ Loaded {result['loaded_count']} records")

asyncio.run(data_pipeline())
```

### Example 3: Stress Testing

```python
import asyncio
from gleitzeit.client import GleitzeitClient

async def stress_test(num_workflows=1000):
    async with GleitzeitClient() as client:
        # Define simple workflow
        workflow = {
            'name': 'Stress Test',
            'tasks': [{
                'id': 'calc',
                'type': 'python',
                'params': {
                    'code': 'result = sum(range(100))'
                }
            }]
        }

        # Create batch of workflows
        workflows = [workflow] * num_workflows

        # Submit batch
        print(f"Submitting {num_workflows} workflows...")
        start = time.time()

        responses = await client.submit_workflows_batch(
            workflows,
            max_concurrent=50
        )

        elapsed = time.time() - start
        print(f"✓ Submitted {len(responses)} workflows in {elapsed:.2f}s")
        print(f"  Rate: {len(responses)/elapsed:.0f} workflows/second")

asyncio.run(stress_test(1000))
```

---

## API Reference

### Client Methods

#### Workflow Operations
- `submit_workflow(workflow, workflow_id=None, priority=None, metadata=None) -> WorkflowResponse`
- `submit_workflows_batch(workflows, max_concurrent=5) -> List[WorkflowResponse]`
- `get_workflow(workflow_id) -> Workflow`
- `get_workflow_status(workflow_id) -> WorkflowStatus`
- `get_workflow_tasks(workflow_id) -> List[Task]`
- `get_workflow_metrics(workflow_id) -> WorkflowMetrics`
- `cancel_workflow(workflow_id) -> bool`
- `cancel_workflows_batch(workflow_ids) -> List[bool]`
- `retry_workflow(workflow_id) -> bool`
- `list_workflows(status=None, limit=100) -> List[Workflow]`
- `wait_for_workflow(workflow_id, timeout=300, poll_interval=2) -> WorkflowStatus`

#### Task Operations
- `get_task(task_id, workflow_id=None) -> Task`
- `get_task_status(task_id, workflow_id=None) -> TaskStatus`
- `get_task_result(task_id, workflow_id=None) -> Any`
- `get_task_logs(task_id, workflow_id=None) -> List[str]`
- `get_task_metrics(task_id, workflow_id=None) -> TaskMetrics`
- `cancel_task(task_id, workflow_id=None) -> bool`
- `retry_task(task_id, workflow_id=None) -> bool`
- `retry_failed_tasks(workflow_id) -> int`
- `list_tasks(workflow_id=None, status=None) -> List[Task]`
- `get_failed_tasks(workflow_id=None, limit=100) -> List[Task]`

#### WebSocket Operations
- `wait_for_workflow_async(workflow_id, on_complete=None, on_failure=None, timeout=300)`
- `wait_for_task_ws(task_id, on_complete=None, on_failure=None, timeout=300)`
- `stream_workflow_events(workflow_id) -> AsyncIterator[Event]`
- `watch_multiple_workflows(workflow_ids) -> AsyncIterator[Event]`
- `monitor_all_workflows() -> AsyncIterator[Event]`

#### Monitoring Operations
- `health_check() -> HealthStatus`
- `get_system_health() -> SystemHealth`
- `get_workers_status() -> List[WorkerStatus]`
- `get_system_metrics() -> SystemMetrics`
- `get_queue_depths() -> Dict[str, int]`
- `get_redis_info() -> Dict`
- `get_resource_usage() -> ResourceUsage`
- `check_api_version() -> str`

#### Authentication Operations
- `create_session(username, password='') -> str`
- `validate_session(session_id) -> bool`
- `destroy_session() -> bool`
- `get_current_user() -> User`
- `get_active_sessions() -> List[Session]`

---

## Additional Resources

- **API Documentation:** [docs/api/QUICK_START.md](api/QUICK_START.md)
- **WebSocket Guide:** [docs/python-client-websocket-examples.md](python-client-websocket-examples.md)
- **Test Examples:** [tests/client/](../tests/client/)
- **Simple REST Examples:** [/tmp/simple_client_test.py](/tmp/simple_client_test.py)

---

## Support

- **GitHub Issues:** Report bugs and request features
- **Documentation:** `/docs/`
- **Examples:** `/examples/` and `/tests/client/`

---

**Last Updated:** November 4, 2025
**Version:** 0.0.7
