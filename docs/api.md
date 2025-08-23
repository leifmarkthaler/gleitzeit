# Gleitzeit REST API Reference

## Overview

The Gleitzeit REST API provides HTTP endpoints for workflow orchestration, task execution, and system management. The API server can be started using the CLI:

```bash
gleitzeit serve --host localhost --port 8000
```

## Base URL

```
http://localhost:8000
```

## Authentication

Currently, the API does not require authentication. This may change in future versions.

## Content Types

- **Request**: `application/json`
- **Response**: `application/json`

## Error Responses

All error responses follow this format:

```json
{
  "detail": "Error message describing what went wrong"
}
```

Common HTTP status codes:
- `200 OK` - Request succeeded
- `400 Bad Request` - Invalid request parameters
- `404 Not Found` - Resource not found
- `422 Unprocessable Entity` - Validation error
- `500 Internal Server Error` - Server error
- `503 Service Unavailable` - System not initialized

## Endpoints

### System Status

#### GET /
Get API information.

**Response:**
```json
{
  "name": "Gleitzeit API",
  "version": "0.0.6",
  "status": "running",
  "documentation": "/docs"
}
```

#### GET /status
Get system status and statistics.

**Response:**
```json
{
  "status": "running",
  "providers": {
    "client": {
      "status": "healthy",
      "type": "GleitzeitClient"
    }
  },
  "persistence_backend": "GleitzeitClient",
  "task_statistics": {
    "completed": 150,
    "failed": 5,
    "queued": 10
  },
  "uptime_seconds": 3600.5
}
```

### Workflow Management

#### POST /workflows
Submit a workflow for execution.

**Request Body:**
```json
{
  "name": "Data Processing Pipeline",
  "description": "Process and analyze data",
  "tasks": [
    {
      "id": "task1",
      "name": "Load Data",
      "protocol": "python/v1",
      "method": "python/execute",
      "params": {
        "code": "import pandas as pd\ndata = pd.read_csv('data.csv')"
      },
      "priority": "normal"
    },
    {
      "id": "task2",
      "name": "Process Data",
      "protocol": "python/v1",
      "method": "python/execute",
      "params": {
        "code": "result = data.mean()"
      },
      "dependencies": ["task1"],
      "priority": "normal"
    }
  ],
  "metadata": {
    "project": "analytics",
    "version": "1.0"
  }
}
```

**Response:**
```json
{
  "workflow_id": "wf_12345678",
  "status": "submitted",
  "tasks_total": 2,
  "tasks_completed": 0,
  "tasks_failed": 0,
  "created_at": "2024-01-15T10:30:00Z",
  "completed_at": null,
  "results": {}
}
```

#### GET /workflows
List all workflows with optional filtering.

**Query Parameters:**
- `status` (string, optional): Filter by status (e.g., "completed", "running", "failed")
- `limit` (integer, default: 50, max: 100): Maximum results to return
- `offset` (integer, default: 0): Number of results to skip

**Response:**
```json
{
  "workflows": [
    {
      "id": "wf_12345678",
      "name": "Data Pipeline",
      "status": "completed",
      "created_at": "2024-01-15T10:30:00Z",
      "completed_at": "2024-01-15T10:35:00Z",
      "tasks_total": 5,
      "tasks_completed": 5,
      "tasks_failed": 0
    }
  ],
  "total": 25,
  "limit": 50,
  "offset": 0
}
```

#### GET /workflows/{workflow_id}
Get workflow status and results.

**Response:**
```json
{
  "workflow_id": "wf_12345678",
  "status": "completed",
  "tasks_total": 2,
  "tasks_completed": 2,
  "tasks_failed": 0,
  "created_at": "2024-01-15T10:30:00Z",
  "completed_at": "2024-01-15T10:32:00Z",
  "results": {
    "task1": {
      "status": "completed",
      "result": {"output": "Data loaded successfully"},
      "error": null
    },
    "task2": {
      "status": "completed",
      "result": {"output": "Processing complete", "mean": 42.5},
      "error": null
    }
  }
}
```

#### GET /workflows/{workflow_id}/tasks
Get all tasks for a specific workflow.

**Query Parameters:**
- `limit` (integer, default: 1000): Maximum results to return
- `offset` (integer, default: 0): Number of results to skip

**Response:**
```json
{
  "workflow_id": "wf_12345678",
  "tasks": [
    {
      "task_id": "task_abc123",
      "name": "Load Data",
      "status": "completed",
      "protocol": "python/v1",
      "method": "python/execute",
      "created_at": "2024-01-15T10:30:00Z",
      "completed_at": "2024-01-15T10:30:05Z"
    }
  ],
  "total": 2
}
```

#### GET /workflows/{workflow_id}/timeline
Get execution timeline for a workflow.

**Response:**
```json
{
  "workflow_id": "wf_12345678",
  "timeline": [
    {
      "task_id": "task_abc123",
      "name": "Load Data",
      "status": "completed",
      "started_at": "2024-01-15T10:30:00Z",
      "completed_at": "2024-01-15T10:30:05Z",
      "duration": 5.0
    },
    {
      "task_id": "task_def456",
      "name": "Process Data",
      "status": "completed",
      "started_at": "2024-01-15T10:30:05Z",
      "completed_at": "2024-01-15T10:30:15Z",
      "duration": 10.0
    }
  ],
  "total_tasks": 2
}
```

#### GET /workflows/{workflow_id}/results
Get aggregated results for a workflow.

**Response:**
```json
{
  "workflow_id": "wf_12345678",
  "status": "completed",
  "results": {
    "task_abc123": {
      "status": "completed",
      "result": {"output": "Data loaded"},
      "error": null
    },
    "task_def456": {
      "status": "completed",
      "result": {"output": "Processing complete", "mean": 42.5},
      "error": null
    }
  },
  "created_at": "2024-01-15T10:30:00Z",
  "completed_at": "2024-01-15T10:31:00Z"
}
```

#### DELETE /workflows/{workflow_id}
Delete a workflow and all its associated tasks.

**Response:**
```json
{
  "success": true,
  "message": "Workflow deleted successfully"
}
```

#### POST /workflows/upload
Upload and execute a workflow YAML file.

**Request:** Multipart form data
- `file`: YAML workflow file
- `execute` (query param, boolean, default: true): Whether to execute immediately

**Response:**
```json
{
  "workflow_id": "wf_12345678",
  "status": "submitted",
  "filename": "pipeline.yaml",
  "message": "Workflow uploaded and execution started"
}
```

### Task Execution

#### POST /tasks
Execute a single task.

**Request Body:**
```json
{
  "name": "Calculate Result",
  "protocol": "python/v1",
  "method": "python/execute",
  "params": {
    "code": "result = 2 + 2\nprint(result)"
  },
  "priority": "normal",
  "retry": {
    "max_attempts": 3,
    "base_delay": 2.0,
    "max_delay": 30.0
  }
}
```

**Priority values:** `"low"`, `"normal"`, `"high"`, `"urgent"`

**Response:**
```json
{
  "task_id": "task_12345678",
  "status": "submitted",
  "result": null,
  "error": null,
  "created_at": "2024-01-15T10:30:00Z",
  "completed_at": null
}
```

#### GET /tasks
List all tasks with optional filtering.

**Query Parameters:**
- `workflow_id` (string, optional): Filter by workflow ID
- `status` (string, optional): Filter by status
- `limit` (integer, default: 100, max: 500): Maximum results
- `offset` (integer, default: 0): Number of results to skip

**Response:**
```json
{
  "tasks": [
    {
      "task_id": "task_12345678",
      "name": "Calculate Result",
      "workflow_id": "wf_87654321",
      "status": "completed",
      "protocol": "python/v1",
      "method": "python/execute",
      "priority": "normal",
      "created_at": "2024-01-15T10:30:00Z",
      "completed_at": "2024-01-15T10:30:05Z",
      "execution_time": 5.0
    }
  ],
  "total": 150,
  "limit": 100,
  "offset": 0
}
```

#### GET /tasks/{task_id}
Get task status and result.

**Response:**
```json
{
  "task_id": "task_12345678",
  "status": "completed",
  "result": {
    "output": "4",
    "return_value": 4
  },
  "error": null,
  "created_at": "2024-01-15T10:30:00Z",
  "completed_at": "2024-01-15T10:30:05Z"
}
```

#### GET /tasks/{task_id}/result
Get the result of a specific task.

**Response:**
```json
{
  "task_id": "task_12345678",
  "status": "completed",
  "result": {
    "output": "4",
    "return_value": 4
  },
  "error": null,
  "completed_at": "2024-01-15T10:30:05Z"
}
```

#### GET /tasks/{task_id}/logs
Get execution logs for a task.

**Query Parameters:**
- `tail` (integer, default: 50): Number of recent log lines to return

**Response:**
```json
{
  "task_id": "task_12345678",
  "logs": [
    "[OUTPUT] Processing started",
    "[STDOUT] Data loaded successfully",
    "Task task_12345678 - Status: completed"
  ],
  "total_lines": 3,
  "tail": 50
}
```

#### DELETE /tasks/{task_id}
Delete a task from persistence.

**Response:**
```json
{
  "success": true,
  "message": "Task deleted successfully"
}
```

### System Information

#### GET /resources
Get resource manager and hub status.

**Response:**
```json
{
  "resource_manager": {
    "id": "client-resources",
    "running": true,
    "stats": {
      "total_resources": 3,
      "active_resources": 2
    }
  },
  "hubs": {
    "ollama": {
      "hub_id": "ollama-hub",
      "resource_type": "ollama",
      "total_instances": 3,
      "healthy_instances": 3,
      "instances": [
        {
          "id": "ollama-127.0.0.1-11434",
          "name": "Ollama@11434",
          "status": "healthy",
          "endpoint": "http://127.0.0.1:11434"
        }
      ]
    }
  }
}
```

#### GET /providers
List all registered providers.

**Response:**
```json
{
  "providers": [
    {
      "name": "ollama-provider",
      "protocol": "llm/v1",
      "status": "healthy",
      "capabilities": ["chat", "vision"]
    },
    {
      "name": "python-provider",
      "protocol": "python/v1",
      "status": "healthy",
      "capabilities": ["execute"]
    }
  ]
}
```

#### GET /protocols
List all registered protocols.

**Response:**
```json
{
  "protocols": [
    {
      "name": "llm/v1",
      "description": "Language Model Protocol"
    },
    {
      "name": "python/v1",
      "description": "Python Execution Protocol"
    },
    {
      "name": "mcp/v1",
      "description": "Model Context Protocol"
    }
  ]
}
```

#### GET /health
Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### Convenience Endpoints

#### POST /chat
Chat with an LLM model.

**Request Body:**
```json
{
  "message": "What is machine learning?",
  "model": "llama3.2",
  "temperature": 0.7,
  "session_id": "session_123"
}
```

**Response:**
```json
{
  "status": "success",
  "response": "Machine learning is a subset of artificial intelligence...",
  "model": "llama3.2",
  "session_id": "session_123"
}
```

#### POST /batch
Process files in batch.

**Request Body:**
```json
{
  "directory": "/path/to/files",
  "pattern": "*.txt",
  "method": "llm/chat",
  "prompt": "Summarize this document",
  "model": "llama3.2",
  "max_concurrent": 5,
  "name": "Batch Summary Job"
}
```

**Response:**
```json
{
  "batch_id": "batch_12345678",
  "status": "processing",
  "total_files": 10,
  "processed": 0,
  "failed": 0,
  "results": {}
}
```

## Workflow Definition Format

Workflows can be defined in YAML or JSON format:

### YAML Example
```yaml
name: Data Analysis Pipeline
description: Analyze customer data
tasks:
  - id: load_data
    name: Load Customer Data
    protocol: python/v1
    method: python/execute
    params:
      code: |
        import pandas as pd
        data = pd.read_csv('customers.csv')
        result = len(data)
    priority: normal

  - id: analyze
    name: Analyze Data
    protocol: llm/v1
    method: llm/chat
    params:
      model: llama3.2
      messages:
        - role: user
          content: "Analyze the following data: {{ load_data.result }}"
    dependencies: [load_data]
    priority: high

metadata:
  author: data_team
  version: "1.0"
```

### Task Protocol Types

#### python/v1
Execute Python code.

**Methods:**
- `python/execute` - Execute Python code

**Parameters:**
```json
{
  "code": "Python code to execute",
  "timeout": 30  // Optional timeout in seconds
}
```

#### llm/v1
Interact with language models.

**Methods:**
- `llm/chat` - Chat completion
- `llm/vision` - Vision analysis

**Parameters for chat:**
```json
{
  "model": "llama3.2",
  "messages": [
    {"role": "system", "content": "You are helpful"},
    {"role": "user", "content": "Hello"}
  ],
  "temperature": 0.7,
  "max_tokens": 1000
}
```

#### mcp/v1
Model Context Protocol for tool use.

**Methods:**
- `mcp/call_tool` - Call an MCP tool

**Parameters:**
```json
{
  "server": "filesystem",
  "tool": "read_file",
  "arguments": {
    "path": "/path/to/file.txt"
  }
}
```

#### template/v1
Use predefined workflow templates.

**Methods:**
- `template/research` - Research template
- `template/code_review` - Code review template

**Parameters:**
```json
{
  "template": "research",
  "topic": "quantum computing",
  "depth": "comprehensive"
}
```

## Task Dependencies

Tasks can depend on other tasks using the `dependencies` field:

```json
{
  "id": "task2",
  "dependencies": ["task1"],
  "params": {
    "input": "{{ task1.result }}"
  }
}
```

## Parameter Substitution

Use template syntax to reference results from previous tasks:

- `{{ task_id.result }}` - Get the result of a task
- `{{ task_id.output }}` - Get the output field
- `{{ task_id.result.field_name }}` - Access nested fields

## Priority Levels

Tasks support four priority levels:
1. `low` - Background tasks
2. `normal` - Default priority
3. `high` - Important tasks
4. `urgent` - Critical tasks

## Retry Configuration

Configure automatic retries for tasks:

```json
{
  "retry": {
    "max_attempts": 5,      // Maximum retry attempts
    "base_delay": 2.0,      // Initial delay in seconds
    "max_delay": 60.0,      // Maximum delay between retries
    "exponential_base": 2   // Exponential backoff multiplier
  }
}
```

## Status Values

### Workflow Status
- `pending` - Workflow created but not started
- `running` - Workflow is executing
- `completed` - All tasks completed successfully
- `failed` - One or more tasks failed
- `cancelled` - Workflow was cancelled

### Task Status
- `pending` - Task waiting to execute
- `queued` - Task in queue
- `executing` - Task currently running
- `completed` - Task finished successfully
- `failed` - Task failed
- `cancelled` - Task was cancelled
- `skipped` - Task skipped due to dependency failure

## Rate Limiting

The API implements rate limiting to prevent abuse:
- Default: 100 requests per minute per IP
- Batch operations: 10 requests per minute

## WebSocket Support (Coming Soon)

Future versions will support WebSocket connections for:
- Real-time task status updates
- Streaming LLM responses
- Live workflow monitoring

## Examples

### Execute a Simple Task
```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Quick Calculation",
    "protocol": "python/v1",
    "method": "python/execute",
    "params": {
      "code": "print(sum(range(100)))"
    }
  }'
```

### Submit a Workflow
```bash
curl -X POST http://localhost:8000/workflows \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Workflow",
    "tasks": [
      {
        "id": "t1",
        "name": "First Task",
        "protocol": "python/v1",
        "method": "python/execute",
        "params": {"code": "result = 42"}
      }
    ]
  }'
```

### Chat with LLM
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Explain quantum computing",
    "model": "llama3.2",
    "temperature": 0.7
  }'
```

### List Completed Workflows
```bash
curl "http://localhost:8000/workflows?status=completed&limit=10"
```

### Delete a Task
```bash
curl -X DELETE http://localhost:8000/tasks/task_12345678
```

## Versioning

The API uses semantic versioning. The current version is `0.0.6`.

Breaking changes will increment the major version number and will be documented in the changelog.

## Support

For issues, feature requests, or questions:
- GitHub Issues: https://github.com/yourusername/gleitzeit/issues
- Documentation: https://gleitzeit.readthedocs.io