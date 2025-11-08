# Gleitzeit API Quick Start Guide

## Installation

```bash
# Install Gleitzeit with API dependencies
cd /path/to/gleitzeit-0.0.7
pip install -e .
```

## Starting the API Server

### Option 1: Command Line

```bash
# Start with default settings (port 8000)
gleitzeit serve

# Custom port and host
gleitzeit serve --api-host 0.0.0.0 --api-port 8080

# Development mode with auto-reload
gleitzeit serve --dev-mode

# API only (no UI)
gleitzeit serve --no-ui
```

### Option 2: Direct Python

```bash
# Set Python path
export PYTHONPATH="/path/to/gleitzeit-0.0.7/src:$PYTHONPATH"

# Start server
python -m uvicorn gleitzeit.api.main:app --host 0.0.0.0 --port 8000
```

### Option 3: Docker (if available)

```bash
docker run -p 8000:8000 -e REDIS_URL=redis://redis:6379 gleitzeit:0.0.7
```

## Basic Workflow Submission

### 1. Without Authentication (Development Mode)

```bash
# Submit a simple workflow
curl -X POST http://localhost:8000/workflows/submit \
  -H "Content-Type: application/json" \
  -d '{
    "workflow": {
      "name": "hello_world",
      "tasks": [{
        "id": "task1",
        "protocol": "python/v1",
        "method": "python/execute",
        "config": {
          "code": "result = \"Hello, World!\""
        }
      }]
    }
  }'
```

### 2. With Client Session

```bash
# Create session
SESSION_ID=$(curl -X POST http://localhost:8000/auth/session/create \
  -H "Content-Type: application/json" \
  -d '{"username": "myuser"}' | jq -r .session_id)

# Submit workflow with session
curl -X POST http://localhost:8000/workflows/submit \
  -H "X-Session-ID: $SESSION_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "workflow": {
      "name": "authenticated_workflow",
      "tasks": [{
        "id": "task1",
        "protocol": "python/v1",
        "method": "python/execute",
        "config": {
          "code": "result = 42"
        }
      }]
    }
  }'
```

## Python Client SDK

### Quick Example

```python
from gleitzeit.client.client import GleitzeitClient

# Initialize client
client = GleitzeitClient(api_url="http://localhost:8000")

# Synchronous workflow submission (for scripts/notebooks)
def run_workflow():
    # Create session
    session_id = client.create_session_sync("myuser")

    # Define workflow
    workflow = {
        "name": "my_workflow",
        "tasks": [{
            "id": "calculate",
            "protocol": "python/v1",
            "method": "python/execute",
            "config": {
                "code": "result = sum(range(100))"
            }
        }]
    }

    # Submit and wait
    response = client.submit_workflow_sync(workflow)
    print(f"Submitted: {response.workflow_id}")

    # Wait for completion (timeout 60 seconds)
    result = client.wait_for_completion(response.workflow_id, timeout=60)
    print(f"Result: {result}")

run_workflow()
```

### Async Example

```python
import asyncio
from gleitzeit.client.client import GleitzeitClient

async def async_workflow():
    client = GleitzeitClient()

    async with client:
        # Authenticate
        await client.create_session("myuser")

        # Submit workflow
        workflow = {
            "name": "async_workflow",
            "tasks": [{
                "id": "task1",
                "protocol": "python/v1",
                "method": "python/execute",
                "config": {"code": "result = 'async result'"}
            }]
        }

        response = await client.submit_workflow(workflow)
        print(f"Submitted: {response.workflow_id}")

        # Check status
        status = await client.get_workflow(response.workflow_id)
        print(f"Status: {status}")

asyncio.run(async_workflow())
```

## Common Workflow Patterns

### 1. Sequential Tasks

```python
workflow = {
    "name": "sequential_processing",
    "tasks": [
        {
            "id": "step1",
            "protocol": "python/v1",
            "method": "python/execute",
            "config": {"code": "result = 'Step 1 complete'"}
        },
        {
            "id": "step2",
            "protocol": "python/v1",
            "method": "python/execute",
            "depends_on": ["step1"],
            "config": {"code": "result = 'Step 2 complete'"}
        },
        {
            "id": "step3",
            "protocol": "python/v1",
            "method": "python/execute",
            "depends_on": ["step2"],
            "config": {"code": "result = 'All steps complete'"}
        }
    ]
}
```

### 2. Parallel Tasks

```python
workflow = {
    "name": "parallel_processing",
    "tasks": [
        {
            "id": "task_a",
            "protocol": "python/v1",
            "method": "python/execute",
            "config": {"code": "result = 'Task A'"}
        },
        {
            "id": "task_b",
            "protocol": "python/v1",
            "method": "python/execute",
            "config": {"code": "result = 'Task B'"}
        },
        {
            "id": "combine",
            "protocol": "python/v1",
            "method": "python/execute",
            "depends_on": ["task_a", "task_b"],
            "config": {"code": "result = 'Combined results'"}
        }
    ]
}
```

### 3. Data Processing Pipeline

```python
workflow = {
    "name": "data_pipeline",
    "tasks": [
        {
            "id": "fetch",
            "protocol": "python/v1",
            "method": "python/execute",
            "config": {
                "code": """
import json
data = [1, 2, 3, 4, 5]
result = {"data": data}
"""
            }
        },
        {
            "id": "transform",
            "protocol": "python/v1",
            "method": "python/execute",
            "depends_on": ["fetch"],
            "config": {
                "code": """
# Access previous task result
data = inputs.get("fetch", {}).get("data", [])
transformed = [x * 2 for x in data]
result = {"transformed": transformed}
"""
            }
        },
        {
            "id": "aggregate",
            "protocol": "python/v1",
            "method": "python/execute",
            "depends_on": ["transform"],
            "config": {
                "code": """
transformed = inputs.get("transform", {}).get("transformed", [])
result = {"sum": sum(transformed), "count": len(transformed)}
"""
            }
        }
    ]
}
```

## Monitoring Workflows

### Check Workflow Status

```python
# Get workflow status
status = client.get_workflow_sync(workflow_id)
print(f"Status: {status['state']['status']}")

# Get all tasks
tasks = client.get_workflow_tasks_sync(workflow_id)
for task in tasks['tasks']:
    print(f"Task {task['task_id']}: {task.get('status')}")
```

### Get Task Results

```python
# Get specific task result
task = client.get_task_sync(task_id)
if task.result:
    print(f"Result: {task.result}")
```

## Environment Variables

```bash
# API Server
export REDIS_URL="redis://localhost:6379"
export JWT_SECRET="your-secret-key"
export GLEITZEIT_AUTO_LOGIN="true"  # Development only

# Client
export GLEITZEIT_API_URL="http://localhost:8000"
export GLEITZEIT_SESSION_ID="existing-session-id"  # Optional
```

## Health Checks

### API Health

```bash
# Basic health check
curl http://localhost:8000/health/

# Readiness check (for k8s)
curl http://localhost:8000/health/ready

# Liveness check (for k8s)
curl http://localhost:8000/health/live
```

### System Status

```bash
# Get system metrics
curl http://localhost:8000/system/metrics \
  -H "X-Session-ID: $SESSION_ID"

# Get worker status
curl http://localhost:8000/system/workers \
  -H "X-Session-ID: $SESSION_ID"
```

## Troubleshooting

### Server Won't Start

```bash
# Check if port is in use
lsof -i :8000

# Check Redis connection
redis-cli ping

# Start with debug logging
gleitzeit serve --log-level debug
```

### Authentication Issues

```python
# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Check session validity
async def check_session():
    async with client._session.post(
        f"{client.api_url}/auth/session/validate",
        json={"session_id": client.session_id}
    ) as resp:
        print(await resp.json())
```

### Workflow Not Processing

```bash
# Check if services are running
gleitzeit ps

# Check Redis streams
redis-cli xlen "{shard:0}:workflow:load"

# Start services if needed
gleitzeit serve
```

## Next Steps

1. **Read Full Documentation**: [API_AUTHENTICATION.md](./API_AUTHENTICATION.md)
2. **Explore Examples**: Check the `/examples` directory
3. **Configure Production**: Set up proper authentication and scaling
4. **Monitor Performance**: Use system metrics endpoints
5. **Implement WebSockets**: For real-time updates (coming soon)

## Support

- GitHub Issues: Report bugs and request features
- Documentation: `/docs/api/`
- Examples: `/examples/`
- Configuration: `/config/`