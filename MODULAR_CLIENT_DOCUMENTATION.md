# Gleitzeit 0.0.7 Client Documentation

## Overview

Gleitzeit 0.0.7 provides two powerful client interfaces for workflow orchestration:

1. **Modular Client** - Full-featured client with mixin-based architecture
2. **Easy Client** - Fluent interface for simplified workflow creation

Both clients include comprehensive security features, authentication, retry logic, and error handling.

---

## Modular Client

The modular client provides a professional-grade interface with separated concerns through mixins.

### Architecture

```
GleitzeitClient
├── AuthMixin          # Authentication & session management
├── RetryMixin         # Retry logic & error handling
├── WorkflowMixin      # Workflow operations
├── TaskMixin          # Task operations
├── MonitoringMixin    # Health checks & metrics
└── BaseClient         # Core HTTP functionality
```

### Installation

```python
from gleitzeit.client import GleitzeitClient
```

### Basic Usage

```python
import asyncio
from gleitzeit.client import GleitzeitClient

async def main():
    # Client with auto-login enabled (default)
    async with GleitzeitClient('http://localhost:8000') as client:
        # Submit a workflow
        workflow = {
            'name': 'My Workflow',
            'tasks': [
                {
                    'name': 'task1',
                    'protocol': 'python',
                    'method': 'python/execute',
                    'params': {
                        'code': 'result = {"value": 42}'
                    }
                }
            ]
        }

        response = await client.submit_workflow(workflow)
        print(f"Submitted: {response.workflow_id}")

        # Wait for completion
        final_status = await client.wait_for_workflow(
            response.workflow_id,
            timeout=60
        )
        print(f"Final status: {final_status.status}")

asyncio.run(main())
```

### Authentication

The client supports multiple authentication methods:

#### 1. Auto-Login (Default)
```python
# Automatically creates a basic user session
client = GleitzeitClient(auto_login=True)
```

#### 2. Session-Based Authentication
```python
client = GleitzeitClient(auto_login=False)
await client.create_session("username", "password")
```

#### 3. JWT Token Authentication
```python
client = GleitzeitClient(jwt_token="your-jwt-token")
```

#### 4. API Key Authentication
```python
client = GleitzeitClient(api_key="your-api-key")
```

### Workflow Operations

#### Submit Workflow
```python
response = await client.submit_workflow(
    workflow={'name': 'test', 'tasks': [...]},
    workflow_id='custom-id',  # Optional
    priority=10,              # Optional
    metadata={'env': 'prod'}  # Optional
)
```

#### Batch Submission
```python
workflows = [workflow1, workflow2, workflow3]
responses = await client.submit_workflows_batch(
    workflows,
    max_concurrent=5
)
```

#### Get Workflow Status
```python
status = await client.get_workflow_status('workflow-id')
print(f"Status: {status.status}")
print(f"Created: {status.created_at}")
```

#### Cancel Workflow
```python
result = await client.cancel_workflow('workflow-id')
```

#### Wait for Completion
```python
final_status = await client.wait_for_workflow(
    'workflow-id',
    timeout=300,      # Max wait time in seconds
    poll_interval=2   # Check every 2 seconds
)
```

### Task Operations

#### Get Task Status
```python
task_status = await client.get_task_status(
    'task-id',
    workflow_id='workflow-id'  # Optional, faster lookup
)
```

#### Retry Failed Task
```python
result = await client.retry_task('task-id')
```

#### Get Task Logs
```python
logs = await client.get_task_logs('task-id', 'workflow-id')
for log in logs:
    print(log)
```

#### Get Failed Tasks
```python
failed_tasks = await client.get_failed_tasks('workflow-id')
for task in failed_tasks:
    print(f"Failed: {task.task_id} - {task.error}")
```

### Monitoring & Health

#### Health Check
```python
health = await client.health_check()
```

#### System Health
```python
system_health = await client.get_system_health()
print(f"Status: {system_health.status}")
print(f"Workers: {system_health.worker_count}")
print(f"Active workflows: {system_health.active_workflows}")
```

#### Worker Status
```python
workers = await client.get_workers_status()
for worker in workers:
    print(f"{worker.worker_id}: {worker.status}")
```

#### Queue Depths
```python
queues = await client.get_queue_depths()
for queue_name, depth in queues.items():
    print(f"{queue_name}: {depth} items")
```

#### Audit Logs
```python
logs = await client.get_audit_logs(
    limit=100,
    user='alice',
    action='workflow_submit'
)
```

### Error Handling

The client includes comprehensive error handling:

```python
from gleitzeit.client import (
    AuthenticationError,
    AuthorizationError
)

try:
    response = await client.submit_workflow(workflow)
except AuthenticationError:
    print("Authentication failed")
except AuthorizationError:
    print("Not authorized for this operation")
except Exception as e:
    print(f"Error: {e}")
```

### Retry Configuration

Customize retry behavior:

```python
client = GleitzeitClient(
    retry_config={
        "max_retries": 5,
        "initial_delay": 0.5,
        "max_delay": 60.0,
        "exponential_base": 2,
        "jitter": True
    }
)
```

### Connection Pooling

Configure connection pool size:

```python
client = GleitzeitClient(
    pool_size=10,  # Connection pool size
    timeout=60     # Request timeout in seconds
)
```

---

## Easy Client

The Easy Client provides a fluent, chainable interface for building workflows with minimal code.

### Basic Usage

```python
from gleitzeit.easy import t, w

# Create and submit a workflow
workflow = w(
    t('fetch_data')
        .with_(code='result = fetch_from_api()')
        .retry(3)
        .timeout(30),

    t('process_data')
        .needs('fetch_data')
        .with_(code='result = process(dependencies["fetch_data"])')

).name('Data Pipeline').submit()
```

### Task Builder (`t`)

Create tasks with chainable configuration:

#### Basic Task
```python
task = t('my_task')
    .with_(code='result = 42')
```

#### With Dependencies
```python
task = t('task2')
    .needs('task1')
    .with_(code='result = dependencies["task1"] * 2')
```

#### With Configuration
```python
task = t('complex_task')
    .with_(code='result = complex_operation()')
    .retry(3)
    .timeout(60)
    .priority(10)
    .cache(300)  # Cache for 5 minutes
```

#### Environment Variables
```python
task = t('env_task')
    .with_(code='import os; result = os.environ["API_KEY"]')
    .env(API_KEY='secret-key', DEBUG='true')
```

#### Convenience Methods
```python
# Python code directly
task = t('python_task').with_code('result = 42')

# Python file
task = t('file_task').with_file('scripts/process.py')

# Capture output
task = t('output_task')
    .with_code('print("Hello"); result = "Done"')
    .capture_output(True)
```

### Workflow Builder (`w`)

Compose tasks into workflows:

#### Simple Workflow
```python
workflow = w(
    t('task1').with_code('result = 1'),
    t('task2').with_code('result = 2')
)
```

#### With Metadata
```python
workflow = w(
    t('task1').with_code('result = "hello"')
).name('My Workflow') \
 .id('custom-workflow-id') \
 .version('2.0.0') \
 .description('Process customer orders') \
 .metadata(env='production', owner='team-a')
```

#### Parallel Tasks
```python
workflow = w().parallel(
    t('fetch_user').with_code('result = get_user()'),
    t('fetch_product').with_code('result = get_product()'),
    t('fetch_inventory').with_code('result = get_inventory()')
)
```

#### Sequential Tasks
```python
workflow = w().sequential(
    t('step1').with_code('result = 1'),
    t('step2').with_code('result = dependencies["step1"] + 1'),
    t('step3').with_code('result = dependencies["step2"] + 1')
)
```

### Workflow Submission

#### Direct Submission
```python
result = workflow.submit()
print(f"Submitted: {result['workflow_id']}")
```

#### Submit and Wait
```python
result = workflow.submit_and_wait(
    timeout=300,
    poll_interval=2
)
print(f"Final status: {result['status']}")
```

#### Async Submission
```python
async def submit_async():
    result = await workflow.submit_async()
    return result
```

### Validation

Validate before submission:

```python
errors = workflow.validate()
if errors:
    for error in errors:
        print(f"Error: {error}")
else:
    workflow.submit()
```

### Export Formats

#### JSON Export
```python
json_str = workflow.to_json(indent=2)
print(json_str)
```

#### YAML Export
```python
yaml_str = workflow.to_yaml()
print(yaml_str)
```

#### Dictionary Export
```python
workflow_dict = workflow.to_dict()
```

### Complex Example

```python
from gleitzeit.easy import t, w

# E-commerce order processing workflow
order_workflow = w(
    # Parallel data fetching
    t('fetch_customer')
        .with_code('result = get_customer(customer_id)')
        .timeout(10),

    t('fetch_product')
        .with_code('result = get_product(product_id)')
        .timeout(10),

    t('check_inventory')
        .with_code('result = check_stock(product_id)')
        .timeout(5),

    # Validation after all data is fetched
    t('validate_order')
        .needs('fetch_customer', 'fetch_product', 'check_inventory')
        .with_code('''
customer = dependencies["fetch_customer"]
product = dependencies["fetch_product"]
inventory = dependencies["check_inventory"]

if inventory["available"] > 0:
    result = {"valid": True, "customer": customer, "product": product}
else:
    result = {"valid": False, "reason": "Out of stock"}
''')
        .retry(2),

    # Process payment if valid
    t('process_payment')
        .needs('validate_order')
        .with_code('''
order = dependencies["validate_order"]
if order["valid"]:
    result = charge_customer(order["customer"], order["product"])
else:
    result = {"status": "skipped", "reason": order["reason"]}
''')
        .timeout(30)
        .priority(100),

    # Send confirmation
    t('send_confirmation')
        .needs('process_payment')
        .with_code('result = send_email(customer_email, order_details)')

).name('Order Processing') \
 .description('Complete order processing pipeline') \
 .metadata(department='sales', priority='high')

# Submit and monitor
result = order_workflow.submit_and_wait(timeout=120)
print(f"Order processing: {result['status']}")
```

---

## Migration from 0.0.6

### Client Changes

| 0.0.6 | 0.0.7 |
|-------|-------|
| Multiple client classes | Unified modular client |
| Event-driven with WebSockets | REST API with polling |
| Native and API adapters | API-only client |
| Complex mixin hierarchy | Clean mixin separation |

### Easy Client Changes

The Easy Client syntax remains largely the same:

```python
# 0.0.6
from gleitzeit.easy import t, w
workflow = w(
    t("task1", "python/v1:execute").with_(file="script.py")
)

# 0.0.7 (identical syntax!)
from gleitzeit.easy import t, w
workflow = w(
    t("task1", "python/v1:execute").with_(file="script.py")
)
```

### New Features in 0.0.7

1. **Direct submission** - `workflow.submit()` directly submits to API
2. **Submit and wait** - `workflow.submit_and_wait()` waits for completion
3. **Better validation** - Automatic dependency and circular reference checking
4. **Async support** - Full async/await support throughout

---

## Best Practices

### 1. Use Context Managers
Always use context managers for automatic cleanup:
```python
async with GleitzeitClient() as client:
    # Your code here
    pass  # Connection automatically closed
```

### 2. Handle Errors Gracefully
```python
try:
    response = await client.submit_workflow(workflow)
except AuthenticationError:
    # Re-authenticate
    await client.create_session(username, password)
    response = await client.submit_workflow(workflow)
```

### 3. Use Easy Client for Simple Workflows
For straightforward workflows, the Easy Client is more concise:
```python
# Instead of building complex dictionaries
workflow_dict = {
    "workflow": {
        "name": "Test",
        "tasks": [...]
    }
}

# Use Easy Client
w(t('task').with_code('result = 42')).name('Test').submit()
```

### 4. Batch Operations
For multiple workflows, use batch operations:
```python
responses = await client.submit_workflows_batch(
    workflows,
    max_concurrent=5  # Limit concurrent submissions
)
```

### 5. Monitor Long-Running Workflows
```python
# Don't poll too frequently
status = await client.wait_for_workflow(
    workflow_id,
    timeout=600,
    poll_interval=5  # Poll every 5 seconds
)
```

---

## Troubleshooting

### Authentication Issues
```python
# If auto-login fails, create session manually
client = GleitzeitClient(auto_login=False)
await client.create_session("your_username", "your_password")
```

### Rate Limiting
The client automatically handles rate limits with exponential backoff.

### Connection Issues
```python
# Increase timeout for slow networks
client = GleitzeitClient(timeout=120)
```

### Validation Errors
```python
# Always validate before submission
errors = workflow.validate()
if not errors:
    workflow.submit()
```

---

## API Reference

### GleitzeitClient

```python
class GleitzeitClient(
    api_url: str = "http://localhost:8000",
    session_id: Optional[str] = None,
    api_key: Optional[str] = None,
    jwt_token: Optional[str] = None,
    pool_size: int = 5,
    timeout: int = 30,
    auto_login: bool = True,
    username: Optional[str] = None,
    password: Optional[str] = None,
    retry_config: Optional[Dict[str, Any]] = None
)
```

### TaskBuilder

```python
t(task_id: str, protocol_method: str = "python/v1:execute") -> TaskBuilder
```

### WorkflowBuilder

```python
w(*tasks: TaskBuilder) -> WorkflowBuilder
```

---

## Support

For issues or questions:
- Check the [GitHub repository](https://github.com/your-org/gleitzeit)
- Review the examples in `/examples` directory
- Consult the API documentation at `/docs`