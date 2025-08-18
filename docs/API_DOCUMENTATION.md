# Gleitzeit API Documentation

## Overview

Gleitzeit provides a REST API for workflow orchestration with support for multiple execution providers, task dependencies, retry mechanisms, and batch processing. The API runs on FastAPI and provides comprehensive endpoints for workflow management.

**Base URL**: `http://localhost:8000`  
**Version**: 0.0.5  
**Status**: Operational

## Table of Contents

- [Core Concepts](#core-concepts)
- [Authentication](#authentication)
- [API Endpoints](#api-endpoints)
  - [System Endpoints](#system-endpoints)
  - [Workflow Endpoints](#workflow-endpoints)
  - [Task Endpoints](#task-endpoints)
  - [Provider Endpoints](#provider-endpoints)
  - [Utility Endpoints](#utility-endpoints)
- [Data Models](#data-models)
- [Providers](#providers)
- [Retry Mechanism](#retry-mechanism)
- [Error Handling](#error-handling)
- [Examples](#examples)

## Core Concepts

### Protocols
Protocols define the interface for task execution. Currently supported protocols:
- `python/v1` - Python script execution
- `llm/v1` - Language model operations (Ollama)
- `mcp/v1` - Model Context Protocol tools
- `template/v1` - Workflow templates

### Providers
Providers implement protocols and execute tasks:
- **PythonProvider** - Executes Python scripts with sandboxing
- **OllamaProvider** - Interfaces with Ollama for LLM operations
- **SimpleMCPProvider** - Provides computational tools
- **TemplateProvider** - Generates workflow templates

### Workflows
Workflows are collections of tasks with dependencies that execute in order based on their dependency graph.

### Tasks
Individual units of work that are executed by providers. Tasks can have dependencies, retry configurations, and priorities.

## Authentication

Currently, the API does not require authentication. This will be added in future versions.

## API Endpoints

### System Endpoints

#### GET /
Returns basic API information.

**Response:**
```json
{
  "name": "Gleitzeit API",
  "version": "0.0.5",
  "status": "running",
  "documentation": "/docs"
}
```

#### GET /status
Returns detailed system status including provider health and statistics.

**Response:**
```json
{
  "status": "running",
  "version": "0.0.5",
  "providers": {
    "api-python-provider": {
      "protocol": "python/v1",
      "status": "healthy",
      "methods": ["python/execute", "python/validate", "python/info"]
    },
    "api-ollama-provider": {
      "protocol": "llm/v1",
      "status": "healthy",
      "methods": ["llm/generate", "llm/chat", "llm/vision", "llm/embeddings"]
    },
    "api-mcp-provider": {
      "protocol": "mcp/v1",
      "status": "healthy",
      "methods": ["mcp/tool.echo", "mcp/tool.add", "mcp/tool.multiply", "mcp/tool.concat"]
    },
    "api-template-provider": {
      "protocol": "template/v1",
      "status": "healthy",
      "methods": ["template/research", "template/code", "template/analyze", "template/chat"]
    }
  },
  "persistence_backend": "UnifiedRedisAdapter",
  "task_statistics": {
    "pending": 0,
    "executing": 0,
    "completed": 150,
    "failed": 23,
    "retry_pending": 2
  },
  "uptime_seconds": 3600.5
}
```

#### GET /health
Simple health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

### Workflow Endpoints

#### POST /workflows
Submit a workflow for execution.

**Request Body:**
```json
{
  "name": "My Workflow",
  "description": "Optional workflow description",
  "tasks": [
    {
      "id": "task1",
      "name": "First Task",
      "protocol": "python/v1",
      "method": "python/execute",
      "params": {
        "file": "/path/to/script.py",
        "args": ["arg1", "arg2"]
      },
      "dependencies": [],
      "priority": "normal",
      "retry": {
        "max_attempts": 3,
        "base_delay": 1.0,
        "backoff_strategy": "exponential",
        "max_delay": 60.0,
        "jitter": true
      }
    },
    {
      "id": "task2",
      "name": "Second Task",
      "protocol": "llm/v1",
      "method": "llm/chat",
      "params": {
        "model": "llama3.2:latest",
        "messages": [
          {"role": "user", "content": "Process this: ${task1.result}"}
        ],
        "temperature": 0.7
      },
      "dependencies": ["task1"],
      "priority": "high"
    }
  ],
  "metadata": {
    "user": "john_doe",
    "project": "analysis"
  }
}
```

**Response:**
```json
{
  "workflow_id": "api_workflow_8a2ffbc3",
  "status": "submitted",
  "tasks_total": 2,
  "tasks_completed": 0,
  "tasks_failed": 0,
  "results": {},
  "created_at": "2024-01-15T10:30:00.000Z",
  "completed_at": null
}
```

#### GET /workflows/{workflow_id}
Get workflow execution status and results.

**Response:**
```json
{
  "workflow_id": "api_workflow_8a2ffbc3",
  "status": "completed",
  "tasks_total": 2,
  "tasks_completed": 2,
  "tasks_failed": 0,
  "results": {
    "task1": {
      "status": "completed",
      "result": {"output": "Script output", "exit_code": 0},
      "error": null
    },
    "task2": {
      "status": "completed",
      "result": {"response": "Processed successfully"},
      "error": null
    }
  },
  "created_at": "2024-01-15T10:30:00.000Z",
  "completed_at": "2024-01-15T10:31:45.000Z"
}
```

#### POST /workflows/upload
Upload and execute a workflow from a YAML file.

**Request:** Multipart form with file upload
- `file`: YAML workflow file
- `execute`: boolean (default: true) - Whether to execute immediately

**Response:** Same as POST /workflows

#### DELETE /workflows/{workflow_id}
Cancel a running workflow.

**Response:**
```json
{
  "status": "cancelled",
  "workflow_id": "api_workflow_8a2ffbc3"
}
```

### Task Endpoints

#### POST /tasks
Execute a single task without a workflow.

**Request Body:**
```json
{
  "id": "optional_task_id",
  "name": "My Task",
  "protocol": "mcp/v1",
  "method": "mcp/tool.add",
  "params": {
    "a": 10,
    "b": 25
  },
  "priority": "normal",
  "retry": {
    "max_attempts": 3,
    "base_delay": 1.0,
    "backoff_strategy": "exponential"
  }
}
```

**Response:**
```json
{
  "task_id": "api_task_7e3610e4",
  "status": "submitted",
  "result": null,
  "error": null,
  "execution_time": null,
  "created_at": "2024-01-15T10:30:00.000Z",
  "completed_at": null
}
```

#### GET /tasks/{task_id}
Get task execution status and result.

**Response:**
```json
{
  "task_id": "api_task_7e3610e4",
  "status": "completed",
  "result": {
    "response": "35",
    "result": 35,
    "calculation": "10 + 25 = 35"
  },
  "error": null,
  "execution_time": 0.015,
  "created_at": "2024-01-15T10:30:00.000Z",
  "completed_at": "2024-01-15T10:30:00.015Z"
}
```

### Provider Endpoints

#### GET /providers
List all registered providers and their capabilities.

**Response:**
```json
{
  "providers": [
    {
      "id": "api-python-provider",
      "protocol": "python/v1",
      "name": "Python Execution Provider",
      "description": "Executes Python scripts and code",
      "methods": ["python/execute", "python/validate", "python/info"],
      "status": "healthy"
    },
    {
      "id": "api-mcp-provider",
      "protocol": "mcp/v1",
      "name": "Simple MCP Provider",
      "description": "Direct MCP tool implementation for testing",
      "methods": ["tool.echo", "tool.add", "tool.multiply", "tool.concat"],
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

### Utility Endpoints

#### POST /batch
Process multiple files in batch.

**Request Body:**
```json
{
  "directory": "/path/to/documents",
  "pattern": "*.txt",
  "method": "llm/chat",
  "prompt": "Summarize this document in 3 bullet points",
  "model": "llama3.2:latest"
}
```

**Response:**
```json
{
  "batch_id": "batch-8a2ffbc3",
  "total_files": 10,
  "successful": 9,
  "failed": 1,
  "processing_time": 45.2,
  "results": {
    "file1.txt": {
      "status": "completed",
      "result": "• Point 1\n• Point 2\n• Point 3"
    },
    "file2.txt": {
      "status": "failed",
      "error": "File too large"
    }
  }
}
```

#### POST /chat
Simple chat interface for LLM interaction.

**Request Body:**
```json
{
  "message": "Explain quantum computing",
  "model": "llama3.2:latest",
  "temperature": 0.7,
  "session_id": "optional_session_123"
}
```

**Response:**
```json
{
  "status": "success",
  "response": "Quantum computing is a type of computation that...",
  "model": "llama3.2:latest",
  "session_id": "optional_session_123"
}
```

#### POST /templates/{template_type}
Execute a pre-built workflow template.

**Template Types:**
- `research` - Multi-step research workflow
- `code` - Code generation workflow
- `analyze` - Content analysis workflow
- `chat` - Conversational workflow

**Request Body:**
```json
{
  "topic": "Machine Learning",
  "depth": "medium",
  "max_steps": 5
}
```

**Response:**
```json
{
  "template_type": "research",
  "workflow_id": "template_research_abc123",
  "topic": "Machine Learning",
  "status": "completed",
  "steps_planned": 5,
  "execution_time": 23.5,
  "report": "Comprehensive research report...",
  "workflow_tasks": ["research_plan", "background_research", "current_trends", "analysis", "final_report"],
  "success": true
}
```

## Data Models

### Task Priority Levels
- `low` - Executed after all higher priority tasks
- `normal` - Default priority
- `high` - Executed before normal priority tasks
- `urgent` - Executed immediately

### Task Status Values
- `pending` - Task created but not queued
- `queued` - Task in queue waiting for execution
- `validated` - Task parameters validated
- `routed` - Task routed to provider
- `executing` - Task currently being executed
- `completed` - Task completed successfully
- `failed` - Task failed permanently
- `cancelled` - Task was cancelled
- `retry_pending` - Task failed and waiting for retry

### Workflow Status Values
- `pending` - Workflow created but not started
- `running` - Workflow currently executing
- `completed` - All tasks completed
- `failed` - Workflow failed
- `cancelled` - Workflow was cancelled

### Retry Configuration
```json
{
  "max_attempts": 3,           // Maximum retry attempts (1-10)
  "base_delay": 1.0,           // Base delay in seconds (0.1-60)
  "backoff_strategy": "exponential", // "linear", "exponential", or "fixed"
  "max_delay": 300.0,          // Maximum delay in seconds (1-3600)
  "jitter": true               // Add random jitter to delays
}
```

## Providers

### Python Provider (python/v1)

**Methods:**
- `python/execute` - Execute a Python script file
- `python/validate` - Validate Python syntax
- `python/info` - Get provider information

**Parameters for execute:**
```json
{
  "file": "/path/to/script.py",
  "args": ["arg1", "arg2"],
  "env": {"KEY": "value"},
  "timeout": 30
}
```

**Security:** Only executes scripts in trusted directories (configured in provider)

### Ollama Provider (llm/v1)

**Methods:**
- `llm/generate` - Text generation
- `llm/chat` - Chat completion
- `llm/vision` - Image analysis
- `llm/embeddings` - Generate embeddings

**Parameters for chat:**
```json
{
  "model": "llama3.2:latest",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant"},
    {"role": "user", "content": "Hello"}
  ],
  "temperature": 0.7,
  "max_tokens": 1000,
  "stream": false
}
```

### MCP Provider (mcp/v1)

**Methods:**
- `mcp/tool.echo` - Echo message
- `mcp/tool.add` - Add two numbers
- `mcp/tool.multiply` - Multiply two numbers
- `mcp/tool.concat` - Concatenate strings

**Parameters for add:**
```json
{
  "a": 10,
  "b": 25
}
```

### Template Provider (template/v1)

**Methods:**
- `template/research` - Generate research workflow
- `template/code` - Generate code development workflow
- `template/analyze` - Generate analysis workflow
- `template/chat` - Generate chat workflow

**Parameters for research:**
```json
{
  "topic": "Quantum Computing",
  "depth": "shallow|medium|deep",
  "max_steps": 5
}
```

## Retry Mechanism

The API implements automatic retry for failed tasks with the following features:

### Retryable Errors
The following error types trigger automatic retries:
- `PROVIDER_TIMEOUT` - Provider request timed out
- `PROVIDER_OVERLOADED` - Provider is overloaded
- `TASK_TIMEOUT` - Task execution timed out
- `TASK_EXECUTION_FAILED` - Task execution failed (recoverable)
- `CONNECTION_TIMEOUT` - Network connection timeout
- `CONNECTION_LOST` - Network connection lost
- `NETWORK_UNREACHABLE` - Network unreachable
- `RESOURCE_EXHAUSTED` - Resources temporarily exhausted
- `RATE_LIMIT_EXCEEDED` - Rate limit exceeded
- `PERSISTENCE_CONNECTION_FAILED` - Database connection failed

### Backoff Strategies
- **linear** - Delay increases linearly (delay * attempt)
- **exponential** - Delay doubles each attempt (delay * 2^attempt)
- **fixed** - Same delay for each retry

### Example with Retry
```json
{
  "name": "Retry Example Task",
  "protocol": "python/v1",
  "method": "python/execute",
  "params": {
    "file": "unstable_script.py"
  },
  "retry": {
    "max_attempts": 5,
    "base_delay": 2.0,
    "backoff_strategy": "exponential",
    "max_delay": 60.0,
    "jitter": true
  }
}
```

## Error Handling

### Error Response Format
```json
{
  "detail": "Error message",
  "status_code": 400,
  "error_code": "TASK_VALIDATION_FAILED",
  "task_id": "task_123",
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

### HTTP Status Codes
- `200` - Success
- `201` - Created (resource created successfully)
- `400` - Bad Request (validation error, malformed request)
- `404` - Resource not found (workflow, task, or file not found)
- `422` - Unprocessable Entity (semantic errors)
- `500` - Internal server error (unexpected error)
- `503` - Service unavailable (system not initialized, provider unavailable)

### Error Codes

#### Validation Errors
- `VALIDATION_ERROR` - General validation failure
- `TASK_VALIDATION_FAILED` - Task parameters validation failed
- `WORKFLOW_VALIDATION_FAILED` - Workflow structure validation failed
- `INVALID_PROTOCOL` - Protocol not registered or invalid
- `INVALID_METHOD` - Method not supported by protocol
- `INVALID_PARAMS` - Parameters don't match method schema
- `MISSING_REQUIRED_FIELD` - Required field missing in request

#### Provider Errors
- `PROVIDER_NOT_FOUND` - No provider available for protocol
- `PROVIDER_TIMEOUT` - Provider request timed out
- `PROVIDER_OVERLOADED` - Provider is overloaded (rate limit)
- `PROVIDER_ERROR` - General provider error
- `PROVIDER_UNAVAILABLE` - Provider is not healthy or disconnected

#### Task Execution Errors
- `TASK_NOT_FOUND` - Task ID not found
- `TASK_EXECUTION_FAILED` - Task execution failed (retryable)
- `TASK_TIMEOUT` - Task execution timed out
- `TASK_CANCELLED` - Task was cancelled
- `TASK_DEPENDENCY_FAILED` - Task dependency failed

#### Workflow Errors
- `WORKFLOW_NOT_FOUND` - Workflow ID not found
- `WORKFLOW_EXECUTION_FAILED` - Workflow execution failed
- `WORKFLOW_CANCELLED` - Workflow was cancelled
- `CYCLIC_DEPENDENCY` - Circular dependency detected in workflow

#### System Errors
- `SYSTEM_NOT_INITIALIZED` - API system not initialized
- `PERSISTENCE_ERROR` - Database/cache operation failed
- `PERSISTENCE_CONNECTION_FAILED` - Cannot connect to persistence backend
- `RESOURCE_EXHAUSTED` - System resources exhausted
- `RATE_LIMIT_EXCEEDED` - API rate limit exceeded

#### Network Errors
- `CONNECTION_TIMEOUT` - Network connection timeout
- `CONNECTION_LOST` - Network connection lost
- `NETWORK_UNREACHABLE` - Network unreachable

### Error Response Examples

#### Validation Error
```json
{
  "detail": "Method 'invalid_method' not found in protocol 'python/v1'",
  "status_code": 400,
  "error_code": "INVALID_METHOD",
  "request_id": "req_abc123"
}
```

#### Provider Timeout
```json
{
  "detail": "Provider 'api-ollama-provider' timed out after 30 seconds",
  "status_code": 503,
  "error_code": "PROVIDER_TIMEOUT",
  "provider_id": "api-ollama-provider",
  "task_id": "task_xyz789"
}
```

#### Task Not Found
```json
{
  "detail": "Task not found",
  "status_code": 404,
  "error_code": "TASK_NOT_FOUND",
  "task_id": "task_nonexistent"
}
```

#### System Not Initialized
```json
{
  "detail": "System not initialized",
  "status_code": 503,
  "error_code": "SYSTEM_NOT_INITIALIZED"
}

## Examples

### Example 1: Simple Python Script Execution
```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Run Analysis",
    "protocol": "python/v1",
    "method": "python/execute",
    "params": {
      "file": "examples/scripts/analyze_data.py"
    }
  }'
```

### Example 2: LLM Chat with Retry
```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Chat Query",
    "protocol": "llm/v1",
    "method": "llm/chat",
    "params": {
      "model": "llama3.2:latest",
      "messages": [
        {"role": "user", "content": "Explain Docker in 100 words"}
      ]
    },
    "retry": {
      "max_attempts": 3,
      "base_delay": 2.0,
      "backoff_strategy": "exponential"
    }
  }'
```

### Example 3: Multi-Step Workflow with Dependencies
```bash
curl -X POST http://localhost:8000/workflows \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Data Processing Pipeline",
    "tasks": [
      {
        "id": "fetch_data",
        "name": "Fetch Data",
        "protocol": "python/v1",
        "method": "python/execute",
        "params": {"file": "fetch_data.py"}
      },
      {
        "id": "process_data",
        "name": "Process Data",
        "protocol": "python/v1",
        "method": "python/execute",
        "params": {"file": "process_data.py"},
        "dependencies": ["fetch_data"]
      },
      {
        "id": "analyze_results",
        "name": "Analyze Results",
        "protocol": "llm/v1",
        "method": "llm/chat",
        "params": {
          "model": "llama3.2:latest",
          "messages": [
            {"role": "user", "content": "Analyze: ${process_data.result}"}
          ]
        },
        "dependencies": ["process_data"]
      }
    ]
  }'
```

### Example 4: Batch Processing
```bash
curl -X POST http://localhost:8000/batch \
  -H "Content-Type: application/json" \
  -d '{
    "directory": "documents",
    "pattern": "*.pdf",
    "method": "llm/chat",
    "prompt": "Extract key points from this document",
    "model": "llama3.2:latest"
  }'
```

### Example 5: Using MCP Tools
```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Calculate Sum",
    "protocol": "mcp/v1",
    "method": "mcp/tool.add",
    "params": {
      "a": 42,
      "b": 58
    }
  }'
```

## Parameter Substitution

Tasks can reference results from previous tasks using the `${task_id.field}` syntax:

```json
{
  "tasks": [
    {
      "id": "task1",
      "method": "python/execute",
      "params": {"file": "generate_data.py"}
    },
    {
      "id": "task2",
      "method": "llm/chat",
      "params": {
        "messages": [
          {"role": "user", "content": "Process this data: ${task1.result}"}
        ]
      },
      "dependencies": ["task1"]
    }
  ]
}
```

## Persistence

The API uses Redis for persistence by default, with automatic fallback to SQL or in-memory storage:

1. **Redis** (Primary) - Fast, distributed caching
2. **SQL** (Fallback) - SQLite or PostgreSQL
3. **Memory** (Development) - Non-persistent, for testing

Configure via environment variables:
```bash
GLEITZEIT_REDIS_URL=redis://localhost:6379/0
GLEITZEIT_PERSISTENCE_TYPE=auto  # auto|redis|sql|memory
```

## Rate Limiting

Currently not implemented. Tasks are queued and executed based on priority and available resources.

## WebSocket Support

Not currently implemented. Use polling on workflow/task status endpoints for real-time updates.

## Monitoring

The `/status` endpoint provides basic monitoring information:
- Provider health status
- Task statistics by status
- System uptime
- Active workflow count

For production deployments, consider adding:
- Prometheus metrics endpoint
- OpenTelemetry tracing
- Custom health checks

## Development

### Running the API
```bash
# Development
uvicorn gleitzeit.api.main:app --reload --port 8000

# Production
uvicorn gleitzeit.api.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### API Documentation
Interactive API documentation is available at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### Testing
```bash
# Test API endpoints
pytest tests/api/

# Test with coverage
pytest tests/api/ --cov=gleitzeit.api
```

## Limitations

- No built-in authentication/authorization
- No WebSocket support for real-time updates
- Limited to single-instance deployment (no distributed coordination)
- No built-in rate limiting
- File operations limited to trusted directories

## Version History

### v0.0.5 (Current)
- Fixed retry mechanism for all providers
- Added TaskExecutionError to retryable errors
- Improved error handling in Python and MCP providers
- Fixed batch processor protocol auto-detection
- Fixed API configuration format for retry settings

### v0.0.4
- Initial REST API implementation
- Basic provider support
- Workflow execution with dependencies
- Batch processing capabilities