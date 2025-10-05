# GleitzeitClient Capabilities Reference

**Complete reference guide for the Gleitzeit Python Client SDK**

The `GleitzeitClient` is a production-ready, low-level client for the Gleitzeit workflow orchestration system. It provides full control over all API operations through a modular mixin architecture.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Authentication & Sessions](#authentication--sessions)
3. [Workflow Operations](#workflow-operations)
4. [Task Operations](#task-operations)
5. [Monitoring & Health](#monitoring--health)
6. [Retry & Error Handling](#retry--error-handling)
7. [Connection Management](#connection-management)
8. [Comparison with Easy Client](#comparison-with-easy-client)

---

## Architecture Overview

The `GleitzeitClient` uses a modular mixin architecture combining five specialized components:

```python
class GleitzeitClient(
    AuthMixin,          # Authentication and session management
    RetryMixin,         # Retry logic and error handling
    WorkflowMixin,      # Workflow operations
    TaskMixin,          # Task operations
    MonitoringMixin,    # System monitoring and health checks
    BaseClient          # Core HTTP functionality
):
    ...
```

Each mixin provides focused functionality while sharing the same connection pool and configuration.

---

## Authentication & Sessions

### Supported Authentication Methods

1. **Session-based authentication** (default with auto-login)
2. **JWT token authentication**
3. **API key authentication**

### Session Management Methods

#### `create_session(username, password=None) -> str`
Create a new client session with automatic cookie management.

```python
async with GleitzeitClient(auto_login=False) as client:
    session_id = await client.create_session("my_user", "my_password")
```

#### `destroy_session() -> Dict[str, Any]`
Destroy the current session.

```python
await client.destroy_session()
```

#### `validate_session() -> bool`
Check if the current session is still valid.

```python
is_valid = await client.validate_session()
```

### JWT Token Methods

#### `create_token(username, password=None) -> str`
Create a JWT access token for authentication.

```python
async with GleitzeitClient(auto_login=False) as client:
    token = await client.create_token("my_user", "my_password")
```

#### `refresh_token(refresh_token) -> str`
Refresh an expired JWT token.

```python
new_token = await client.refresh_token(refresh_token)
```

### User Information

#### `get_current_user() -> Dict[str, Any]`
Get information about the currently authenticated user.

```python
user_info = await client.get_current_user()
```

### Auto-login

The client supports automatic authentication on connection:

```python
async with GleitzeitClient(
    auto_login=True,      # Default
    username="my_user",
    password="my_password"
) as client:
    # Session automatically created
    response = await client.submit_workflow(workflow)
```

---

## Workflow Operations

### Workflow Submission

#### `submit_workflow(workflow, workflow_id=None, priority=None, metadata=None) -> WorkflowResponse`
Submit a workflow for execution.

**Result Chaining**: When tasks have dependencies, Gleitzeit automatically injects predecessor results into the `inputs` dict. Results are keyed by task UUID (not task name).

```python
workflow = {
    "name": "example",
    "tasks": [
        {
            "name": "generate",
            "protocol": "python/v1",
            "method": "python/execute",
            "params": {
                "code": "result = {'number': 42, 'message': 'Hello'}"
            }
        },
        {
            "name": "process",
            "protocol": "python/v1",
            "method": "python/execute",
            "params": {
                "code": '''
                # Results auto-injected into 'inputs' dict by dependency worker
                # Keys are task UUIDs, values are result dicts
                for key, value in inputs.items():
                    if isinstance(value, dict) and 'number' in value:
                        number = value['number']
                        result = {'doubled': number * 2}
                        break
                '''
            },
            "dependencies": ["generate"]
        }
    ]
}

response = await client.submit_workflow(
    workflow,
    workflow_id="my-workflow-123",
    priority=10,
    metadata={"user": "john", "env": "prod"}
)
```

**Returns**: `WorkflowResponse` with fields:
- `workflow_id`: str
- `status`: str
- `message`: str
- `submitted_at`: str
- `user_id`: Optional[str]
- `session_id`: Optional[str]

#### `submit_workflows_batch(workflows, max_concurrent=5) -> List[WorkflowResponse]`
Submit multiple workflows concurrently with automatic concurrency control.

```python
workflows = [workflow1, workflow2, workflow3]
responses = await client.submit_workflows_batch(workflows, max_concurrent=3)

for resp in responses:
    if resp.status == "submitted":
        print(f"Workflow {resp.workflow_id} submitted successfully")
```

### Workflow Querying

#### `get_workflow(workflow_id) -> Dict[str, Any]`
Get complete workflow details including state, tasks, and metadata.

```python
workflow_data = await client.get_workflow("workflow-123")
```

#### `get_workflow_status(workflow_id) -> WorkflowStatus`
Get structured workflow status information.

```python
status = await client.get_workflow_status("workflow-123")
print(f"Status: {status.status}")
print(f"Created: {status.created_at}")
print(f"Error: {status.error}")
```

**Returns**: `WorkflowStatus` with fields:
- `workflow_id`: str
- `status`: str
- `created_at`: str
- `updated_at`: str
- `completed_at`: Optional[str]
- `error`: Optional[str]
- `progress`: Optional[Dict[str, Any]]

#### `get_workflow_tasks(workflow_id) -> List[Dict[str, Any]]`
Get all tasks belonging to a workflow.

```python
tasks = await client.get_workflow_tasks("workflow-123")
for task in tasks:
    print(f"Task {task['name']}: {task['status']}")
```

#### `list_workflows(limit=100, offset=0, status=None, full_data=False) -> List`
List workflows with optional filtering and pagination.

```python
# Get workflow IDs only
workflow_ids = await client.list_workflows(limit=50, status="running")

# Get full workflow data
workflows = await client.list_workflows(limit=50, full_data=True)
```

### Workflow Control

#### `cancel_workflow(workflow_id) -> Dict[str, Any]`
Cancel a running workflow.

```python
result = await client.cancel_workflow("workflow-123")
```

#### `cancel_workflows_batch(workflow_ids, max_concurrent=5) -> List[Dict[str, Any]]`
Cancel multiple workflows concurrently.

```python
workflow_ids = ["wf-1", "wf-2", "wf-3"]
results = await client.cancel_workflows_batch(workflow_ids)
```

#### `retry_workflow(workflow_id) -> WorkflowResponse`
Retry a failed workflow by creating a new instance with the original definition.

```python
new_response = await client.retry_workflow("failed-workflow-123")
print(f"Retry workflow: {new_response.workflow_id}")
```

### Workflow Waiting

#### `wait_for_workflow(workflow_id, timeout=None, poll_interval=2) -> WorkflowStatus`
Block until workflow completes or timeout is reached.

```python
try:
    final_status = await client.wait_for_workflow(
        "workflow-123",
        timeout=300,  # 5 minutes
        poll_interval=2
    )
    if final_status.status == "completed":
        print("Workflow succeeded!")
except TimeoutError:
    print("Workflow did not complete in time")
```

---

## Task Operations

### Task Querying

#### `get_task(task_id, workflow_id=None) -> Dict[str, Any]`
Get complete task details.

```python
task = await client.get_task("task-123", workflow_id="workflow-123")
```

#### `get_task_status(task_id, workflow_id=None) -> TaskStatus`
Get structured task status information.

```python
status = await client.get_task_status("task-123")
print(f"Status: {status.status}")
print(f"Result: {status.result}")
print(f"Error: {status.error}")
print(f"Retry count: {status.retry_count}")
```

**Returns**: `TaskStatus` with fields:
- `task_id`: str
- `workflow_id`: str
- `status`: str
- `provider`: str
- `created_at`: str
- `started_at`: Optional[str]
- `completed_at`: Optional[str]
- `result`: Optional[Dict[str, Any]]
- `error`: Optional[str]
- `retry_count`: int

#### `get_task_result(task_id, workflow_id=None) -> Optional[Dict[str, Any]]`
Get just the task result, if available.

```python
result = await client.get_task_result("task-123")
if result:
    print(f"Output: {result}")
```

#### `list_tasks(limit=100, offset=0, status=None, workflow_id=None, full_data=False) -> List`
List tasks with optional filtering.

```python
# Get task IDs for a specific workflow
task_ids = await client.list_tasks(workflow_id="workflow-123")

# Get full task data for failed tasks
failed_tasks = await client.list_tasks(
    status="failed",
    full_data=True,
    limit=20
)
```

### Task Control

#### `retry_task(task_id, workflow_id=None) -> Dict[str, Any]`
Retry a failed task.

```python
result = await client.retry_task("task-123", workflow_id="workflow-123")
```

#### `cancel_task(task_id, workflow_id=None) -> Dict[str, Any]`
Cancel a running task.

```python
result = await client.cancel_task("task-123")
```

### Task Waiting

#### `wait_for_task(task_id, workflow_id=None, timeout=None, poll_interval=2) -> TaskStatus`
Block until task completes or timeout is reached.

```python
final_status = await client.wait_for_task(
    "task-123",
    timeout=60,
    poll_interval=1
)
```

### Task Dependencies

#### `get_task_dependencies(task_id, workflow_id) -> List[str]`
Get the IDs of tasks this task depends on.

```python
deps = await client.get_task_dependencies("task-123", "workflow-123")
print(f"Depends on: {deps}")
```

#### `get_task_dependents(task_id, workflow_id) -> List[str]`
Get the IDs of tasks that depend on this task.

```python
dependents = await client.get_task_dependents("task-123", "workflow-123")
print(f"Blocks: {dependents}")
```

### Task Logs

#### `get_task_logs(task_id, workflow_id=None) -> List[str]`
Get execution logs for a task.

```python
logs = await client.get_task_logs("task-123")
for log_line in logs:
    print(log_line)
```

### Batch Task Operations

#### `get_failed_tasks(workflow_id) -> List[TaskStatus]`
Get all failed tasks in a workflow.

```python
failed = await client.get_failed_tasks("workflow-123")
for task in failed:
    print(f"Failed task: {task.task_id}, error: {task.error}")
```

#### `retry_failed_tasks(workflow_id) -> List[Dict[str, Any]]`
Retry all failed tasks in a workflow.

```python
results = await client.retry_failed_tasks("workflow-123")
```

---

## Monitoring & Health

### Health Checks

#### `health_check() -> Dict[str, Any]`
Perform a basic health check on the API.

```python
health = await client.health_check()
print(f"API is {health['status']}")
```

#### `get_system_health() -> SystemHealth`
Get detailed system health status.

```python
health = await client.get_system_health()
print(f"Status: {health.status}")
print(f"Version: {health.api_version}")
print(f"Uptime: {health.uptime}s")
print(f"Redis connected: {health.redis_connected}")
print(f"Workers: {health.worker_count}")
print(f"Active workflows: {health.active_workflows}")
print(f"Active tasks: {health.active_tasks}")
```

**Returns**: `SystemHealth` with fields:
- `status`: str
- `api_version`: str
- `uptime`: float
- `redis_connected`: bool
- `worker_count`: int
- `active_workflows`: int
- `active_tasks`: int

### Worker Monitoring

#### `get_workers_status() -> List[WorkerStatus]`
Get status of all workers in the system.

```python
workers = await client.get_workers_status()
for worker in workers:
    print(f"Worker {worker.worker_id} ({worker.worker_type}): {worker.status}")
    print(f"  Last heartbeat: {worker.last_heartbeat}")
    print(f"  Tasks processed: {worker.tasks_processed}")
    if worker.current_task:
        print(f"  Current task: {worker.current_task}")
```

**Returns**: List of `WorkerStatus` with fields:
- `worker_id`: str
- `worker_type`: str
- `status`: str
- `last_heartbeat`: str
- `tasks_processed`: int
- `current_task`: Optional[str]

#### `trigger_health_check_all_workers() -> Dict[str, bool]`
Trigger a health check on all workers and get results.

```python
results = await client.trigger_health_check_all_workers()
for worker_id, is_healthy in results.items():
    print(f"Worker {worker_id}: {'healthy' if is_healthy else 'unhealthy'}")
```

### Metrics

#### `get_system_metrics() -> Dict[str, Any]`
Get overall system performance metrics.

```python
metrics = await client.get_system_metrics()
```

#### `get_workflow_metrics(time_range="1h") -> Dict[str, Any]`
Get workflow execution metrics for a time period.

```python
metrics = await client.get_workflow_metrics(time_range="24h")
print(f"Workflows completed: {metrics.get('completed_count')}")
print(f"Average duration: {metrics.get('avg_duration')}s")
```

#### `get_task_metrics(time_range="1h") -> Dict[str, Any]`
Get task execution metrics for a time period.

```python
metrics = await client.get_task_metrics(time_range="7d")
```

### Queue Monitoring

#### `get_queue_depths() -> Dict[str, int]`
Get the current depth of all Redis queues.

```python
queues = await client.get_queue_depths()
for queue_name, depth in queues.items():
    print(f"{queue_name}: {depth} items")
```

### Redis Monitoring

#### `get_redis_info() -> Dict[str, Any]`
Get Redis server information and statistics.

```python
redis_info = await client.get_redis_info()
```

### Resource Monitoring

#### `get_resource_usage() -> Dict[str, Any]`
Get current resource usage (CPU, memory, etc.).

```python
resources = await client.get_resource_usage()
print(f"CPU: {resources.get('cpu_percent')}%")
print(f"Memory: {resources.get('memory_mb')} MB")
```

### Logs & Audit

#### `get_audit_logs(limit=100, offset=0, user=None, action=None) -> List[Dict[str, Any]]`
Get audit logs with optional filtering.

```python
logs = await client.get_audit_logs(
    limit=50,
    user="john",
    action="workflow_submit"
)
```

#### `get_error_logs(limit=100, offset=0, level="ERROR") -> List[Dict[str, Any]]`
Get error logs from the system.

```python
errors = await client.get_error_logs(limit=20, level="ERROR")
for error in errors:
    print(f"{error['timestamp']}: {error['message']}")
```

### Sessions & Rate Limits

#### `get_active_sessions() -> List[Dict[str, Any]]`
Get list of all active user sessions.

```python
sessions = await client.get_active_sessions()
```

#### `get_rate_limit_status() -> Dict[str, Any]`
Get current rate limit status for the authenticated user.

```python
rate_limit = await client.get_rate_limit_status()
print(f"Limit: {rate_limit['limit']}")
print(f"Remaining: {rate_limit['remaining']}")
print(f"Reset in: {rate_limit['reset_in_seconds']}s")
```

### Configuration

#### `check_api_version() -> str`
Get the API version string.

```python
version = await client.check_api_version()
```

#### `get_configuration() -> Dict[str, Any]`
Get current system configuration.

```python
config = await client.get_configuration()
```

---

## Retry & Error Handling

The `RetryMixin` provides automatic retry logic with exponential backoff for all API requests.

### Retry Configuration

```python
client = GleitzeitClient(
    retry_config={
        "max_retries": 3,           # Maximum retry attempts
        "initial_delay": 1.0,       # Initial delay in seconds
        "max_delay": 30.0,          # Maximum delay cap
        "exponential_base": 2,      # Exponential backoff base
        "jitter": True              # Add random jitter to delays
    }
)
```

### Automatic Retry Behavior

- **5xx Server Errors**: Automatically retried with exponential backoff
- **429 Rate Limit**: Automatically waits for `Retry-After` duration
- **401 Authentication**: Attempts re-authentication once if `auto_login=True`
- **4xx Client Errors**: Not retried (except 401, 429)
- **Network Errors**: Retried with exponential backoff
- **Timeout Errors**: Retried with exponential backoff

### Error Classification

```python
from gleitzeit.client.mixins.auth import AuthenticationError, AuthorizationError

try:
    await client.submit_workflow(workflow)
except AuthenticationError:
    print("Authentication failed - check credentials")
except AuthorizationError:
    print("Not authorized to perform this action")
except aiohttp.ClientResponseError as e:
    print(f"API error {e.status}: {e.message}")
except aiohttp.ClientError as e:
    print(f"Network error: {e}")
```

### Custom Timeout

```python
# Use custom timeout for specific request
result = await client._request_with_timeout(
    "POST",
    "/workflows/submit",
    timeout=60,
    json_data=workflow
)
```

---

## Connection Management

### Async Context Manager (Recommended)

```python
async with GleitzeitClient(api_url="http://localhost:8000") as client:
    # Connection automatically established
    response = await client.submit_workflow(workflow)
    # Connection automatically closed on exit
```

### Manual Connection Management

```python
client = GleitzeitClient()
await client.connect()  # Or client.initialize()
try:
    response = await client.submit_workflow(workflow)
finally:
    await client.close()  # Or client.shutdown()
```

### Connection Pooling

```python
client = GleitzeitClient(
    pool_size=10,      # Connection pool size
    timeout=30         # Default request timeout in seconds
)
```

### Auto-start Server (Development)

```python
client = GleitzeitClient(
    auto_start_server=True  # Attempt to start server if not running
)
```

---

## Comparison with Easy Client

| Feature | GleitzeitClient | Easy Client |
|---------|-----------------|-------------|
| **Level** | Low-level API | High-level DSL |
| **Control** | Full control over all operations | Simplified builder pattern |
| **Result Chaining** | Manual (iterate over `inputs` dict with UUID keys) | Automatic (variables named after tasks) |
| **Workflow Definition** | Raw dictionaries matching API schema | Fluent builder API (`t()`, `w()`, `.input()`) |
| **Use Cases** | - Production systems<br>- Advanced workflows<br>- Monitoring & ops<br>- Full API access | - Quick prototypes<br>- Simple workflows<br>- Readable code<br>- Result chaining |
| **Authentication** | Full session, JWT, API key support | Inherits from GleitzeitClient |
| **Monitoring** | 20+ monitoring & health methods | Basic workflow/task queries |
| **Batch Operations** | Built-in concurrent batch submission/cancellation | Not included |
| **Retry Logic** | Configurable exponential backoff | Inherits from GleitzeitClient |
| **Connection Pooling** | Configurable pool size | Inherits from GleitzeitClient |
| **Learning Curve** | Steeper - requires API knowledge | Gentler - DSL abstracts details |

### When to Use GleitzeitClient

- You need full control over workflow definitions
- You're building production monitoring/ops tools
- You need access to system health, metrics, and logs
- You're implementing advanced retry strategies
- You need batch operations with custom concurrency control
- You want to manage authentication explicitly
- You prefer working directly with the API schema

### When to Use Easy Client

- You're building simple workflows quickly
- You want readable, maintainable workflow code
- You need automatic result chaining between tasks
- You prefer declarative over imperative style
- You're prototyping or experimenting
- You want the framework to handle variable naming

### Combined Usage

The Easy Client extends `GleitzeitClient`, so you can use both:

```python
from gleitzeit.easy import EasyClient, t, w

async with EasyClient() as client:
    # Use Easy Client for workflow building
    workflow = w(
        t("task1", "python/v1:execute").with_(code="result = 42")
    )
    response = await client.submit(workflow)

    # Use GleitzeitClient methods for monitoring
    health = await client.get_system_health()
    workers = await client.get_workers_status()
    metrics = await client.get_workflow_metrics("1h")
```

---

## Complete Example: Production Workflow Monitoring

```python
import asyncio
from gleitzeit.client import GleitzeitClient

async def monitor_workflow_execution():
    """Complete example showing workflow submission and monitoring."""

    async with GleitzeitClient(
        api_url="http://localhost:8000",
        auto_login=True,
        username="ops_user",
        retry_config={
            "max_retries": 5,
            "initial_delay": 2.0,
            "max_delay": 60.0
        }
    ) as client:
        # Check system health before submitting
        health = await client.get_system_health()
        if health.status != "healthy":
            print(f"System unhealthy: {health}")
            return

        # Define and submit workflow
        workflow = {
            "name": "data-pipeline",
            "tasks": [
                {
                    "name": "extract",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "result = {'records': 1000}"}
                },
                {
                    "name": "transform",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "code": """
                        for key, value in inputs.items():
                            if isinstance(value, dict) and 'records' in value:
                                records = value['records']
                                result = {'processed': records * 2}
                                break
                        """
                    },
                    "dependencies": ["extract"]
                }
            ]
        }

        # Submit with metadata
        response = await client.submit_workflow(
            workflow,
            priority=10,
            metadata={"env": "prod", "pipeline": "daily"}
        )

        print(f"Submitted workflow: {response.workflow_id}")

        # Monitor execution
        try:
            final_status = await client.wait_for_workflow(
                response.workflow_id,
                timeout=300,
                poll_interval=5
            )

            if final_status.status == "completed":
                print("✓ Workflow completed successfully")

                # Get task results
                tasks = await client.get_workflow_tasks(response.workflow_id)
                for task in tasks:
                    result = await client.get_task_result(task["task_id"])
                    print(f"  {task['name']}: {result}")

            elif final_status.status == "failed":
                print(f"✗ Workflow failed: {final_status.error}")

                # Get failed tasks and logs
                failed_tasks = await client.get_failed_tasks(response.workflow_id)
                for task in failed_tasks:
                    print(f"\nFailed task: {task.task_id}")
                    print(f"  Error: {task.error}")

                    logs = await client.get_task_logs(task.task_id)
                    print(f"  Logs: {logs}")

                # Retry failed tasks
                print("\nRetrying failed tasks...")
                retry_results = await client.retry_failed_tasks(response.workflow_id)

        except TimeoutError:
            print("⏱ Workflow did not complete in time")

            # Cancel if needed
            await client.cancel_workflow(response.workflow_id)

        # Get final metrics
        metrics = await client.get_workflow_metrics("1h")
        print(f"\nMetrics: {metrics}")

if __name__ == "__main__":
    asyncio.run(monitor_workflow_execution())
```

---

## Method Count Summary

The `GleitzeitClient` provides **60+ methods** across five categories:

- **Authentication & Sessions**: 8 methods
- **Workflow Operations**: 11 methods
- **Task Operations**: 16 methods
- **Monitoring & Health**: 20 methods
- **Retry & Connection**: 5 methods
- **Core Infrastructure**: Connection pooling, async context managers, error handling

---

## Additional Resources

- **Easy Client Documentation**: See `src/gleitzeit/easy/` for high-level DSL
- **API Schema**: See `src/gleitzeit/api/` for complete API reference
- **Examples**: See `examples/` directory for additional use cases
- **Handlers**: See `src/gleitzeit/handlers/` for supported task protocols

---

**Last Updated**: 2025-09-30
**Client Version**: 0.0.7
