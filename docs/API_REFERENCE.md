# Gleitzeit API Reference

## Python Client API

### GleitzeitClient

The main client for interacting with Gleitzeit programmatically.

```python
from gleitzeit import GleitzeitClient
```

#### Constructor

```python
GleitzeitClient(
    base_url: str = "http://localhost:8000",
    persistence: str = "auto",
    redis_url: str = None,
    sqlite_path: str = None,
    max_parallel_tasks: int = 10,
    task_timeout: int = 300,
    api_key: str = None
)
```

**Parameters:**
- `base_url`: API server URL (if using server mode)
- `persistence`: Persistence type ("redis", "sqlite", "memory", "auto")
- `redis_url`: Redis connection URL
- `sqlite_path`: SQLite database path
- `max_parallel_tasks`: Maximum parallel task execution
- `task_timeout`: Default task timeout in seconds
- `api_key`: API key for authentication

#### Methods

##### Workflow Management

```python
async def submit_workflow(
    self,
    workflow: Union[str, Dict[str, Any]],
    parameters: Optional[Dict[str, Any]] = None,
    wait: bool = False
) -> str
```
Submit a workflow for execution.

**Parameters:**
- `workflow`: Path to YAML file or workflow dictionary
- `parameters`: Override workflow parameters
- `wait`: Wait for completion if True

**Returns:** Workflow ID

**Example:**
```python
workflow_id = await client.submit_workflow(
    "workflow.yaml",
    parameters={"model": "llama3.2"}
)
```

---

```python
async def get_workflow_status(
    self,
    workflow_id: str
) -> Dict[str, Any]
```
Get workflow execution status.

**Returns:** Status dictionary with progress information

---

```python
async def get_workflow_results(
    self,
    workflow_id: str
) -> Dict[str, Any]
```
Get workflow execution results.

**Returns:** Dictionary mapping task IDs to results

---

```python
async def cancel_workflow(
    self,
    workflow_id: str
) -> bool
```
Cancel a running workflow.

**Returns:** True if cancelled successfully

---

```python
async def list_workflows(
    self,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> List[Dict[str, Any]]
```
List workflows with optional filtering.

**Parameters:**
- `status`: Filter by status ("pending", "running", "completed", "failed")
- `limit`: Maximum results to return
- `offset`: Pagination offset

---

##### Task Execution

```python
async def execute_task(
    self,
    task: Dict[str, Any]
) -> Any
```
Execute a single task directly.

**Parameters:**
- `task`: Task definition with protocol, method, and parameters

**Example:**
```python
result = await client.execute_task({
    "protocol": "llm/v1",
    "method": "chat",
    "parameters": {
        "model": "llama3.2",
        "messages": [{"role": "user", "content": "Hello"}]
    }
})
```

---

##### Batch Processing

```python
async def batch_process(
    self,
    directory: str,
    pattern: str = "*.txt",
    prompt: str = None,
    model: str = "llama3.2",
    max_parallel: int = 5
) -> Dict[str, Any]
```
Process multiple files in batch.

**Parameters:**
- `directory`: Directory containing files
- `pattern`: Glob pattern for file selection
- `prompt`: Processing prompt for each file
- `model`: LLM model to use
- `max_parallel`: Maximum parallel processing

**Returns:** Dictionary mapping file paths to results

---

##### Resource Management

```python
async def get_resources(
    self,
    resource_type: Optional[str] = None
) -> List[Dict[str, Any]]
```
Get available resources.

**Parameters:**
- `resource_type`: Filter by type ("OLLAMA", "DOCKER")

---

```python
async def get_resource_metrics(
) -> Dict[str, Any]
```
Get global resource metrics.

---

### Async Context Manager

```python
async with GleitzeitClient() as client:
    # Client is initialized and ready
    result = await client.execute_task(task)
    # Client is automatically cleaned up
```

### Complete Example

```python
import asyncio
from gleitzeit import GleitzeitClient

async def main():
    # Create client with configuration
    client = GleitzeitClient(
        persistence="redis",
        redis_url="redis://localhost:6379",
        max_parallel_tasks=20
    )
    
    async with client:
        # Submit workflow
        workflow_id = await client.submit_workflow(
            "workflow.yaml",
            parameters={"temperature": 0.7}
        )
        
        # Monitor progress
        while True:
            status = await client.get_workflow_status(workflow_id)
            print(f"Status: {status['status']}")
            print(f"Progress: {status['progress']}")
            
            if status['status'] in ['completed', 'failed']:
                break
            
            await asyncio.sleep(2)
        
        # Get results
        if status['status'] == 'completed':
            results = await client.get_workflow_results(workflow_id)
            for task_id, result in results.items():
                print(f"{task_id}: {result}")

asyncio.run(main())
```

## CLI API

### Workflow Commands

#### workflow submit
```bash
gleitzeit workflow submit <workflow_file> [options]
```

Submit a workflow for execution.

**Arguments:**
- `workflow_file`: Path to workflow YAML file

**Options:**
- `--param KEY=VALUE`: Set workflow parameters
- `--wait`: Wait for completion
- `--output FORMAT`: Output format (json, yaml, table)

**Example:**
```bash
gleitzeit workflow submit workflow.yaml \
  --param model=llama3.2 \
  --param temperature=0.8 \
  --wait
```

---

#### workflow status
```bash
gleitzeit workflow status <workflow_id>
```

Get workflow status.

---

#### workflow list
```bash
gleitzeit workflow list [options]
```

List workflows.

**Options:**
- `--status STATUS`: Filter by status
- `--limit N`: Limit results
- `--format FORMAT`: Output format

---

#### workflow result
```bash
gleitzeit workflow result <workflow_id> [options]
```

Get workflow results.

**Options:**
- `--task TASK_ID`: Get specific task result
- `--format FORMAT`: Output format

---

#### workflow cancel
```bash
gleitzeit workflow cancel <workflow_id>
```

Cancel a running workflow.

---

#### workflow logs
```bash
gleitzeit workflow logs <workflow_id> [options]
```

Get workflow execution logs.

**Options:**
- `--follow`: Follow log output
- `--tail N`: Show last N lines

### Batch Commands

#### batch process
```bash
gleitzeit batch <directory> [options]
```

Process files in batch.

**Arguments:**
- `directory`: Directory containing files

**Options:**
- `--pattern PATTERN`: File pattern (default: "*.txt")
- `--prompt PROMPT`: Processing prompt
- `--model MODEL`: LLM model
- `--parallel N`: Max parallel processing

**Example:**
```bash
gleitzeit batch ./documents \
  --pattern "*.md" \
  --prompt "Summarize this document" \
  --model llama3.2:7b \
  --parallel 10
```

### Provider Commands

#### provider list
```bash
gleitzeit provider list
```

List available providers.

---

#### provider info
```bash
gleitzeit provider info <provider_id>
```

Get provider information.

### Resource Commands

#### resource list
```bash
gleitzeit resource list [options]
```

List resources.

**Options:**
- `--type TYPE`: Filter by resource type
- `--status STATUS`: Filter by status

---

#### resource metrics
```bash
gleitzeit resource metrics [options]
```

Get resource metrics.

**Options:**
- `--hub HUB_ID`: Specific hub metrics
- `--format FORMAT`: Output format

### System Commands

#### system status
```bash
gleitzeit system status
```

Get system status including all components.

---

#### system cleanup
```bash
gleitzeit system cleanup [options]
```

Clean up old workflows and resources.

**Options:**
- `--older-than DURATION`: Clean items older than (e.g., "7d", "24h")
- `--dry-run`: Show what would be cleaned

### Configuration Commands

#### config show
```bash
gleitzeit config show
```

Show current configuration.

---

#### config set
```bash
gleitzeit config set <key> <value>
```

Set configuration value.

**Example:**
```bash
gleitzeit config set persistence redis
gleitzeit config set redis_url redis://localhost:6379
```

## REST API

### Endpoints

#### POST /api/workflows
Submit a workflow.

**Request Body:**
```json
{
  "workflow": {
    "name": "My Workflow",
    "tasks": [...]
  },
  "parameters": {
    "model": "llama3.2"
  }
}
```

**Response:**
```json
{
  "workflow_id": "wf-abc123",
  "status": "submitted"
}
```

---

#### GET /api/workflows/{workflow_id}
Get workflow status.

**Response:**
```json
{
  "workflow_id": "wf-abc123",
  "status": "running",
  "progress": {
    "total": 5,
    "completed": 2,
    "running": 1,
    "failed": 0
  }
}
```

---

#### GET /api/workflows/{workflow_id}/results
Get workflow results.

**Response:**
```json
{
  "workflow_id": "wf-abc123",
  "results": {
    "task1": {...},
    "task2": {...}
  }
}
```

---

#### DELETE /api/workflows/{workflow_id}
Cancel a workflow.

---

#### GET /api/workflows
List workflows.

**Query Parameters:**
- `status`: Filter by status
- `limit`: Maximum results
- `offset`: Pagination offset

---

#### POST /api/tasks
Execute a single task.

**Request Body:**
```json
{
  "protocol": "llm/v1",
  "method": "chat",
  "parameters": {
    "model": "llama3.2",
    "messages": [...]
  }
}
```

---

#### GET /api/resources
Get available resources.

**Response:**
```json
{
  "resources": [
    {
      "id": "ollama-1",
      "type": "OLLAMA",
      "status": "healthy",
      "endpoint": "http://localhost:11434"
    }
  ]
}
```

---

#### GET /api/metrics
Get system metrics.

**Response:**
```json
{
  "total_resources": 10,
  "healthy_resources": 8,
  "workflows_running": 3,
  "tasks_completed": 150
}
```

## WebSocket API

### Event Streaming

Connect to WebSocket for real-time events:

```javascript
const ws = new WebSocket('ws://localhost:8000/api/events');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Event:', data);
};

// Subscribe to workflow events
ws.send(JSON.stringify({
  type: 'subscribe',
  workflow_id: 'wf-abc123'
}));
```

### Event Types

```typescript
interface WorkflowEvent {
  type: 'workflow_started' | 'workflow_completed' | 'workflow_failed';
  workflow_id: string;
  timestamp: string;
  data: any;
}

interface TaskEvent {
  type: 'task_started' | 'task_completed' | 'task_failed';
  workflow_id: string;
  task_id: string;
  timestamp: string;
  data: any;
}

interface ResourceEvent {
  type: 'resource_registered' | 'resource_healthy' | 'resource_unhealthy';
  hub_id: string;
  instance_id: string;
  timestamp: string;
  data: any;
}
```

## Error Codes

### Client Errors (4xx)

| Code | Name | Description |
|------|------|-------------|
| 400 | BAD_REQUEST | Invalid request parameters |
| 401 | UNAUTHORIZED | Missing or invalid API key |
| 404 | NOT_FOUND | Resource not found |
| 409 | CONFLICT | Resource conflict |
| 422 | VALIDATION_ERROR | Request validation failed |
| 429 | RATE_LIMITED | Too many requests |

### Server Errors (5xx)

| Code | Name | Description |
|------|------|-------------|
| 500 | INTERNAL_ERROR | Internal server error |
| 502 | PROVIDER_ERROR | Provider execution failed |
| 503 | RESOURCE_UNAVAILABLE | No resources available |
| 504 | TIMEOUT | Operation timed out |

## SDK Examples

### JavaScript/TypeScript

```typescript
import { GleitzeitClient } from 'gleitzeit-js';

const client = new GleitzeitClient({
  baseUrl: 'http://localhost:8000',
  apiKey: 'your-api-key'
});

// Submit workflow
const workflowId = await client.submitWorkflow({
  name: 'My Workflow',
  tasks: [
    {
      id: 'task1',
      protocol: 'llm/v1',
      method: 'chat',
      parameters: {
        model: 'llama3.2',
        messages: [
          { role: 'user', content: 'Hello' }
        ]
      }
    }
  ]
});

// Get results
const results = await client.getWorkflowResults(workflowId);
console.log(results);
```

### Go

```go
package main

import (
    "github.com/yourusername/gleitzeit-go"
)

func main() {
    client := gleitzeit.NewClient(
        gleitzeit.WithBaseURL("http://localhost:8000"),
        gleitzeit.WithAPIKey("your-api-key"),
    )
    
    // Submit workflow
    workflowID, err := client.SubmitWorkflow(gleitzeit.Workflow{
        Name: "My Workflow",
        Tasks: []gleitzeit.Task{
            {
                ID:       "task1",
                Protocol: "llm/v1",
                Method:   "chat",
                Parameters: map[string]interface{}{
                    "model": "llama3.2",
                    "messages": []map[string]string{
                        {"role": "user", "content": "Hello"},
                    },
                },
            },
        },
    })
    
    if err != nil {
        panic(err)
    }
    
    // Get results
    results, err := client.GetWorkflowResults(workflowID)
    fmt.Println(results)
}
```

## Environment Variables

Configuration via environment variables:

```bash
# Persistence
GLEITZEIT_PERSISTENCE_TYPE=redis
GLEITZEIT_REDIS_URL=redis://localhost:6379
GLEITZEIT_SQLITE_PATH=./gleitzeit.db

# API Server
GLEITZEIT_API_HOST=0.0.0.0
GLEITZEIT_API_PORT=8000
GLEITZEIT_API_KEY=your-secret-key

# Execution
GLEITZEIT_MAX_PARALLEL_TASKS=20
GLEITZEIT_TASK_TIMEOUT=600

# Logging
GLEITZEIT_LOG_LEVEL=INFO
GLEITZEIT_LOG_FILE=./gleitzeit.log

# Resource Management
GLEITZEIT_OLLAMA_HOST=localhost
GLEITZEIT_OLLAMA_PORT=11434
GLEITZEIT_DOCKER_HOST=unix:///var/run/docker.sock
```

## Rate Limiting

API rate limits per endpoint:

| Endpoint | Limit | Window |
|----------|-------|--------|
| /api/workflows | 100 | 1 minute |
| /api/tasks | 1000 | 1 minute |
| /api/resources | 500 | 1 minute |
| /api/metrics | 100 | 1 minute |

Rate limit headers:
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1628694000
```

## Authentication

### API Key Authentication

Include API key in headers:
```bash
curl -H "Authorization: Bearer your-api-key" \
  http://localhost:8000/api/workflows
```

### JWT Authentication (Enterprise)

```bash
# Get token
curl -X POST http://localhost:8000/api/auth/token \
  -d '{"username": "user", "password": "pass"}'

# Use token
curl -H "Authorization: Bearer <jwt-token>" \
  http://localhost:8000/api/workflows
```

## Pagination

Standard pagination parameters:

```bash
GET /api/workflows?limit=20&offset=40
```

Response includes pagination metadata:
```json
{
  "items": [...],
  "pagination": {
    "total": 150,
    "limit": 20,
    "offset": 40,
    "has_next": true,
    "has_prev": true
  }
}
```

## Versioning

API version in URL path:
```
/api/v1/workflows  # Current version
/api/v2/workflows  # Future version
```

Or via header:
```
Accept: application/vnd.gleitzeit.v1+json
```

## Summary

The Gleitzeit API provides comprehensive programmatic access through:
- **Python Client**: Full-featured async client
- **CLI**: Command-line interface for all operations
- **REST API**: HTTP endpoints for integration
- **WebSocket**: Real-time event streaming
- **SDKs**: Language-specific libraries

All APIs follow consistent patterns for authentication, error handling, and response formats.