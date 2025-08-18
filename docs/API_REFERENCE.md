# Gleitzeit REST API Reference

## Overview

The Gleitzeit REST API provides HTTP endpoints for workflow orchestration, task execution, and system management. Built with FastAPI, it offers automatic OpenAPI documentation, async support, and type validation.

## Base URL

```
http://localhost:8000
```

## Authentication

Currently, the API does not require authentication. This will be added in future versions.

## API Endpoints

### System Management

#### GET /status
Get system status including providers, persistence backend, and statistics.

**Response:**
```json
{
  "status": "running",
  "version": "0.0.5",
  "providers": {
    "api-python-provider": {
      "protocol": "python/v1",
      "status": "healthy",
      "methods": ["python/execute", "python/validate"]
    }
  },
  "persistence_backend": "UnifiedRedisAdapter",
  "task_statistics": {
    "completed": 150,
    "failed": 5,
    "queued": 2
  },
  "uptime_seconds": 3600.5
}
```

#### GET /health
Health check endpoint for monitoring.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

#### GET /providers
List all registered protocol providers.

**Response:**
```json
{
  "providers": [
    {
      "id": "api-python-provider",
      "protocol": "python/v1",
      "name": "PythonProvider",
      "description": "Execute Python code",
      "methods": ["python/execute", "python/validate"],
      "status": "healthy"
    }
  ]
}
```

#### GET /protocols
List all registered protocols.

**Response:**
```json
{
  "protocols": ["python/v1", "llm/v1", "mcp/v1", "template/v1"]
}
```

### Workflow Management

#### POST /workflows
Submit a workflow for execution.

**Request Body:**
```json
{
  "name": "Data Processing Workflow",
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
      "name": "Analyze",
      "protocol": "llm/v1",
      "method": "llm/chat",
      "params": {
        "model": "llama3.2",
        "messages": [{"role": "user", "content": "Analyze this data: ${task1.result}"}]
      },
      "dependencies": ["task1"],
      "priority": "normal"
    }
  ],
  "metadata": {
    "author": "user",
    "tags": ["data", "analysis"]
  }
}
```

**Response:**
```json
{
  "workflow_id": "api_workflow_a1b2c3d4",
  "status": "submitted",
  "tasks_total": 2,
  "tasks_completed": 0,
  "tasks_failed": 0,
  "results": {},
  "created_at": "2024-01-15T10:30:00Z",
  "completed_at": null
}
```

#### GET /workflows/{workflow_id}
Get workflow status and results.

**Response:**
```json
{
  "workflow_id": "api_workflow_a1b2c3d4",
  "status": "completed",
  "tasks_total": 2,
  "tasks_completed": 2,
  "tasks_failed": 0,
  "results": {
    "task1": {
      "status": "completed",
      "result": {"output": "Data loaded successfully"},
      "error": null
    },
    "task2": {
      "status": "completed",
      "result": {"response": "The data shows interesting patterns..."},
      "error": null
    }
  },
  "created_at": "2024-01-15T10:30:00Z",
  "completed_at": "2024-01-15T10:31:30Z"
}
```

#### POST /workflows/upload
Upload and execute a workflow YAML/JSON file.

**Request:** Multipart form with file upload

**Query Parameters:**
- `execute` (boolean, default: true) - Whether to execute the workflow

**Response:**
```json
{
  "workflow_id": "workflow_from_file",
  "status": "submitted",
  "name": "Uploaded Workflow",
  "tasks": 5
}
```

#### DELETE /workflows/{workflow_id}
Cancel a running workflow.

**Response:**
```json
{
  "status": "cancelled",
  "workflow_id": "api_workflow_a1b2c3d4"
}
```

### Task Execution

#### POST /tasks
Execute a single task.

**Request Body:**
```json
{
  "name": "Calculate Sum",
  "protocol": "python/v1",
  "method": "python/execute",
  "params": {
    "code": "result = sum([1, 2, 3, 4, 5])"
  },
  "priority": "high",
  "retry": {
    "max_attempts": 3,
    "base_delay": 5.0
  }
}
```

**Response:**
```json
{
  "task_id": "api_task_e5f6g7h8",
  "status": "submitted",
  "result": null,
  "error": null,
  "execution_time": null,
  "created_at": "2024-01-15T10:30:00Z",
  "completed_at": null
}
```

#### GET /tasks/{task_id}
Get task status and result.

**Response:**
```json
{
  "task_id": "api_task_e5f6g7h8",
  "status": "completed",
  "result": {
    "output": "",
    "result": 15
  },
  "error": null,
  "execution_time": 0.125,
  "created_at": "2024-01-15T10:30:00Z",
  "completed_at": "2024-01-15T10:30:01Z"
}
```

### Convenience Endpoints

#### POST /execute/python
Execute Python code directly.

**Request Body:**
```json
{
  "code": "import math\nresult = math.factorial(10)",
  "timeout": 30
}
```

**Response:**
```json
{
  "status": "success",
  "output": "",
  "result": 3628800,
  "execution_time": 0.05
}
```

#### POST /chat
Chat with LLM.

**Request Body:**
```json
{
  "message": "Explain microservices architecture",
  "model": "llama3.2:latest",
  "temperature": 0.7,
  "session_id": "user_session_123"
}
```

**Response:**
```json
{
  "status": "success",
  "response": "Microservices architecture is a design approach...",
  "model": "llama3.2:latest",
  "session_id": "user_session_123"
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
  "model": "llama3.2:latest",
  "max_concurrent": 5
}
```

**Response:**
```json
{
  "batch_id": "batch_i9j0k1l2",
  "total_files": 10,
  "successful": 9,
  "failed": 1,
  "processing_time": 45.67,
  "results": {
    "file1.txt": {
      "status": "success",
      "content": "Summary of file1..."
    }
  }
}
```

### Template Endpoints

#### POST /templates/{template_type}
Execute a workflow template.

**Template Types:**
- `research` - Multi-step research workflow
- `code` - Code development workflow
- `analyze` - Content analysis workflow
- `chat` - Conversational workflow

**Request Body (for research):**
```json
{
  "topic": "quantum computing applications",
  "depth": "deep",
  "max_steps": 5
}
```

**Response:**
```json
{
  "template_type": "research",
  "workflow_id": "template_research_m3n4o5p6",
  "topic": "quantum computing applications",
  "status": "completed",
  "steps_planned": 5,
  "execution_time": 234.56,
  "report": "# Research Report: Quantum Computing Applications\n\n## Executive Summary...",
  "workflow_tasks": ["research_plan", "background_research", "current_trends", "analysis", "final_report"],
  "success": true
}
```

## Error Responses

All endpoints return standard HTTP status codes and error messages:

```json
{
  "detail": "Workflow not found"
}
```

**Common Status Codes:**
- `200` - Success
- `400` - Bad Request (invalid parameters)
- `404` - Resource not found
- `500` - Internal server error
- `503` - Service unavailable (system not initialized)

## WebSocket Support (Coming Soon)

Future versions will include WebSocket endpoints for:
- Real-time workflow progress updates
- Streaming task results
- Live system monitoring

## Rate Limiting

Currently no rate limiting is implemented. This will be added in future versions.

## Python Client Usage

### Async Client

```python
import asyncio
from gleitzeit.api.client import GleitzeitAPIClient

async def main():
    async with GleitzeitAPIClient() as client:
        # Get system status
        status = await client.get_status()
        print(f"Status: {status['status']}")
        
        # Execute Python code
        result = await client.execute_python("result = 2 ** 10")
        print(f"Result: {result['result']}")
        
        # Chat with LLM
        response = await client.chat("Hello!")
        print(f"Response: {response['response']}")
        
        # Run research template
        research = await client.research("AI ethics", depth="deep")
        print(f"Research complete: {research['success']}")

asyncio.run(main())
```

### Sync Client

```python
from gleitzeit.api.client import GleitzeitAPIClientSync

client = GleitzeitAPIClientSync()

# Get status
status = client.get_status()
print(f"System: {status['status']}")

# Execute code
result = client.execute_python("print('Hello API!')")
print(f"Output: {result['output']}")

# Chat
response = client.chat("What is Gleitzeit?")
print(f"Answer: {response['response']}")
```

## cURL Examples

### Submit Workflow
```bash
curl -X POST http://localhost:8000/workflows \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Workflow",
    "tasks": [{
      "name": "Test Task",
      "protocol": "python/v1",
      "method": "python/execute",
      "params": {"code": "result = 42"}
    }]
  }'
```

### Execute Python Code
```bash
curl -X POST http://localhost:8000/execute/python \
  -H "Content-Type: application/json" \
  -d '{"code": "import sys; print(sys.version)"}'
```

### Chat with LLM
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello, how are you?"}'
```

## Running the API Server

### Using uvicorn directly:
```bash
uvicorn gleitzeit.api.main:app --host 0.0.0.0 --port 8000 --reload
```

### Using the run script:
```bash
python src/gleitzeit/api/run_server.py
```

### Using Docker (coming soon):
```bash
docker run -p 8000:8000 gleitzeit/api:latest
```

## OpenAPI Documentation

When the server is running, interactive API documentation is available at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- OpenAPI Schema: http://localhost:8000/openapi.json

## Environment Variables

- `GLEITZEIT_API_HOST` - API host (default: 0.0.0.0)
- `GLEITZEIT_API_PORT` - API port (default: 8000)
- `GLEITZEIT_REDIS_URL` - Redis connection URL
- `GLEITZEIT_SQL_DB_PATH` - SQLite database path
- `GLEITZEIT_LOG_LEVEL` - Logging level (DEBUG, INFO, WARNING, ERROR)