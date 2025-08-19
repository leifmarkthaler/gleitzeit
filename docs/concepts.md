# Core Concepts

## Overview

Gleitzeit orchestrates workflows by executing tasks in sequence or parallel. Each task uses a provider to perform specific operations like LLM chat, Python execution, or workflow template generation.

## Key Components

### Workflows

A workflow is a collection of tasks that execute in a defined order. Workflows are defined in YAML files.

```yaml
name: "My Workflow"
tasks:
  - id: "task1"
    method: "llm/chat"
    parameters:
      # task configuration
```

### Tasks

Tasks are individual units of work. Each task has:
- **id**: Unique identifier
- **method**: Protocol method to execute (e.g., "llm/chat")
- **dependencies**: Other tasks that must complete first
- **parameters**: Configuration for the task

### Providers

Providers implement protocols and execute tasks. Built-in providers:
- **OllamaProvider**: LLM operations via Ollama
- **PythonProvider**: Python script execution
- **SimpleMCPProvider**: Model Context Protocol tools
- **TemplateProvider**: Pre-built workflow template generation

### Protocols

Protocols define the interface between tasks and providers. Each protocol specifies available methods:
- **llm/v1**: Language model operations
- **python/v1**: Python execution
- **mcp/v1**: MCP tool usage
- **template/v1**: Workflow template generation

## Execution Model

### Sequential Execution

Tasks with dependencies execute in order:

```yaml
tasks:
  - id: "first"
    method: "llm/chat"
  
  - id: "second"
    dependencies: ["first"]  # Waits for first
    method: "python/execute"
```

### Parallel Execution

Tasks without dependencies run concurrently:

```yaml
tasks:
  - id: "task1"
    method: "llm/chat"  # Starts immediately
  
  - id: "task2"
    method: "llm/chat"  # Runs in parallel with task1
  
  - id: "combine"
    dependencies: ["task1", "task2"]  # Waits for both
```

### Parameter Substitution

Tasks can use results from previous tasks:

```yaml
tasks:
  - id: "generate"
    method: "llm/chat"
    parameters:
      messages:
        - content: "Generate a topic"
  
  - id: "expand"
    dependencies: ["generate"]
    parameters:
      messages:
        - content: "Write about: ${generate.response}"
```

Substitution syntax:
- `${task_id.field}` - Access task result field
- `${task_id.nested.field}` - Access nested fields

## Client Modes

The GleitzeitClient operates in three modes:

### Native Mode

Direct execution using the embedded engine:

```python
client = GleitzeitClient(mode="native")
```

Best for:
- Development and testing
- Single-user applications
- Simple deployments

### API Mode

Connects to a Gleitzeit server:

```python
client = GleitzeitClient(mode="api", api_host="localhost", api_port=8000)
```

Best for:
- Production deployments
- Multi-user systems
- Distributed workflows

### Auto Mode

Automatically detects and uses the best available mode:

```python
client = GleitzeitClient()  # Default mode
```

Logic:
1. Check if API server is running
2. Use API if available
3. Fall back to native mode

## Persistence

Gleitzeit supports multiple persistence backends with automatic fallback:

### Redis (Primary)

High-performance distributed storage:

```bash
export GLEITZEIT_REDIS_URL=redis://localhost:6379
```

### SQLite (Fallback)

Local file-based storage:

```bash
export GLEITZEIT_SQL_DB_PATH=~/.gleitzeit/db.sqlite
```

### Memory (Last Resort)

In-process storage (data lost on restart).

The system automatically tries backends in order: Redis → SQLite → Memory

## Batch Processing

Process multiple files with a single workflow template:

```yaml
name: "Batch Analysis"
type: "batch"
batch:
  directory: "documents"
  pattern: "*.txt"
  max_concurrent: 5
template:
  method: "llm/chat"
  model: "llama3.2"
  messages:
    - role: "user"
      content: "Analyze: ${file_content}"
```

## Resource Management

### Hubs

Hubs manage external resources:
- **OllamaHub**: Manages Ollama LLM instances
- **DockerHub**: Manages Docker containers

### Auto-Discovery

Ollama instances are automatically discovered on ports 11434-11439.

### Load Balancing

Multiple instances are load-balanced based on:
- Current load
- Model availability
- Response time

## Error Handling

### Retry Logic

Tasks can retry on failure:

```yaml
tasks:
  - id: "task"
    retry:
      max_attempts: 3
      delay: 2
      exponential_backoff: true
```

### Timeouts

Prevent hanging tasks:

```yaml
parameters:
  timeout: 30  # seconds
```

### Fallback Chains

Providers and persistence backends automatically fall back to alternatives on failure.

## Context Management

The client uses async context managers for proper resource cleanup:

```python
async with GleitzeitClient() as client:
    # Resources automatically managed
    result = await client.run_workflow("workflow.yaml")
# Cleanup happens automatically
```

## Next Steps

- Learn to create [Workflows](workflows.md)
- Explore the [Python API](api.md)
- Master the [CLI](cli.md)