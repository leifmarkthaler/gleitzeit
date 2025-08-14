# Gleitzeit V4 - Event-Driven Workflow Orchestration

🚀 **Modern, event-driven workflow orchestration system with multi-backend persistence and pluggable providers.**

## 🆕 Recent Enhancements (v4.1)

- ✅ **Enhanced Event-Driven Execution** - Fixed task assignment and processing in event-driven mode
- ✅ **Improved CLI Workflow Support** - Added support for both `params` and `parameters` in YAML workflows
- ✅ **Better Provider Management** - Enhanced CLI provider commands with health checking
- ✅ **Verified Redis Persistence** - Confirmed full LLM response storage and retrieval
- ✅ **Production Ready Status** - 94% test success rate with comprehensive coverage

## Features

- ✅ **Event-driven architecture** - No polling, pure async/await
- ✅ **Multi-backend persistence** - SQLite, Redis, InMemory 
- ✅ **Pluggable providers** - Python, Ollama LLM, custom providers
- ✅ **Dependency resolution** - Complex workflow dependencies with parameter substitution
- ✅ **Retry logic** - Configurable retry strategies with exponential backoff
- ✅ **Real-time monitoring** - Task execution tracking and statistics
- ✅ **Simple CLI** - Easy workflow creation and execution

## Quick Start

### Installation

```bash
# Install with pip
pip install -e .

# Or install with development dependencies
pip install -e .[dev]

# Install all optional dependencies
pip install -e .[all]
```

### Basic Usage

```bash
# Create a new workflow
gleitzeit init my_workflow --type python

# Run the workflow
gleitzeit run my_workflow.yaml

# Check system status
gleitzeit status

# Execute Python code directly
gleitzeit exec "print('Hello Gleitzeit!')"
```

## CLI Commands

### Core Commands

- **`gleitzeit run <workflow.yaml>`** - Execute a workflow
- **`gleitzeit status`** - Show system status and statistics
- **`gleitzeit init <name>`** - Create new workflow template
- **`gleitzeit exec <code>`** - Execute Python code directly
- **`gleitzeit config`** - Show/manage configuration

### Options

- **`--verbose`** / **`-v`** - Enable verbose logging
- **`--debug`** - Enable debug logging
- **`--backend sqlite|redis`** - Override persistence backend

## Workflow Definition

Workflows are defined in YAML format:

```yaml
name: "Example Workflow"
description: "Demonstrates Python and LLM tasks"
tasks:
  - name: "Generate Data"
    protocol: "python/v1"
    method: "python/execute"
    parameters:
      code: |
        import random
        result = {
          'numbers': [random.randint(1, 100) for _ in range(5)],
          'operation': 'sum'
        }
        print(f"Generated: {result['numbers']}")
      timeout: 10
    priority: "high"
    
  - name: "Process Results"
    protocol: "python/v1" 
    method: "python/execute"
    parameters:
      code: |
        # Access previous task result
        data = ${Generate Data.result.result}
        total = sum(data['numbers'])
        
        result = {
          'input_numbers': data['numbers'],
          'total': total,
          'average': total / len(data['numbers'])
        }
        
        print(f"Sum: {total}, Average: {result['average']}")
      timeout: 10
    dependencies: ["Generate Data"]
    priority: "normal"
    retry:
      max_attempts: 3
      base_delay: 1.0
      strategy: "exponential"
```

### Task Parameters

- **`name`** - Human readable task name
- **`protocol`** - Protocol to use (`python/v1`, `llm/v1`)
- **`method`** - Method within protocol (`python/execute`, `llm/chat`)
- **`parameters`** - Task-specific parameters
- **`dependencies`** - List of task names this task depends on
- **`priority`** - Task priority (`low`, `normal`, `high`, `urgent`)
- **`retry`** - Retry configuration (optional)

### Parameter Substitution

Access results from previous tasks using `${TaskName.result.field}` syntax:

```yaml
parameters:
  code: |
    # Access the result from "Previous Task"
    previous_result = ${Previous Task.result.result}
    print(f"Previous task returned: {previous_result}")
```

### Retry Configuration

```yaml
retry:
  max_attempts: 3        # Maximum retry attempts
  base_delay: 1.0        # Base delay in seconds
  max_delay: 60.0        # Maximum delay cap
  strategy: "exponential" # exponential, linear, fixed
  jitter: true           # Add random jitter
```

## Providers

### Python Provider

Execute Python code with full variable access:

```yaml
- name: "Python Task"
  protocol: "python/v1"
  method: "python/execute" 
  parameters:
    code: |
      # Your Python code here
      import json
      result = {'status': 'success', 'data': [1, 2, 3]}
      print(f"Result: {json.dumps(result)}")
    timeout: 30
```

### Ollama LLM Provider

Interface with Ollama for local LLM inference:

```yaml
- name: "LLM Task"
  protocol: "llm/v1"
  method: "llm/chat"
  parameters:
    model: "llama3.2:latest"
    messages:
      - role: "user"
        content: "Write a haiku about automation"
    temperature: 0.7
    max_tokens: 100
```

## Persistence Backends

### SQLite (Default)

Local database perfect for development and single-node deployments:

```bash
# Uses SQLite by default
gleitzeit run workflow.yaml

# Explicitly specify SQLite
gleitzeit run workflow.yaml --backend sqlite
```

### Redis

Distributed persistence for production deployments:

```bash
# Use Redis backend
gleitzeit run workflow.yaml --backend redis

# Check Redis statistics
gleitzeit status --backend redis
```

## Configuration

Configuration is stored in `~/.gleitzeit/config.yaml`:

```yaml
persistence:
  backend: sqlite  # or redis
  sqlite:
    db_path: ~/.gleitzeit/workflows.db
  redis:
    host: localhost
    port: 6379
    db: 0

providers:
  python:
    enabled: true
  ollama:
    enabled: true
    endpoint: http://localhost:11434

execution:
  max_concurrent_tasks: 5
```

Create default configuration:

```bash
gleitzeit config
# Follow prompts to create default config
```

## Examples

### Simple Python Workflow

```bash
# Create Python workflow template
gleitzeit init data_processing --type python

# Edit the generated workflow.yaml file
# Then run it
gleitzeit run data_processing.yaml
```

### LLM Workflow

```bash
# Create LLM workflow template  
gleitzeit init content_generation --type llm

# Run with Ollama
gleitzeit run content_generation.yaml
```

### Mixed Workflow

```bash
# Create mixed Python + LLM workflow
gleitzeit init ai_pipeline --type mixed

# Run the full pipeline
gleitzeit run ai_pipeline.yaml --watch
```

### Direct Code Execution

```bash
# Execute Python code directly
gleitzeit exec "
import datetime
print(f'Current time: {datetime.datetime.now()}')
result = {'timestamp': str(datetime.datetime.now())}
"
```

## Development

### Running Tests

```bash
# Install development dependencies
pip install -e .[dev]

# Run all tests
cd tests
python -m pytest

# Run specific test categories
python test_redis_full_execution.py
python test_sqlite_backend.py  
python test_retry_working.py
```

### Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   CLI Layer     │    │  Core Engine     │    │   Persistence   │
│                 │    │                  │    │                 │
│ • gleitzeit_cli │───▶│ • ExecutionEngine│───▶│ • RedisBackend  │
│ • YAML Parser  │    │ • QueueManager   │    │ • SQLiteBackend │
│ • Config Mgmt   │    │ • DependencyRes  │    │ • InMemoryBackend│
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                       │                       │
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Providers     │    │   Task Queue     │    │   Retry Logic   │
│                 │    │                  │    │                 │
│ • PythonProvider│    │ • Priority Queue │    │ • RetryManager  │
│ • OllamaProvider│    │ • Event Tracking │    │ • Backoff Logic │ 
│ • CustomProvider│    │ • Dependency Res │    │ • Event Schedule│
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

## API Reference

### Core Classes

- **`ExecutionEngine`** - Central workflow coordinator
- **`Task`** - Individual task definition  
- **`Workflow`** - Collection of tasks with dependencies
- **`QueueManager`** - Task queuing and priority management
- **`RetryManager`** - Retry logic and scheduling

### Persistence

- **`PersistenceBackend`** - Abstract base class
- **`SQLiteBackend`** - Local SQLite storage
- **`RedisBackend`** - Distributed Redis storage
- **`InMemoryBackend`** - Fast in-memory storage

### Providers

- **`CustomFunctionProvider`** - Python code execution
- **`OllamaProvider`** - Local LLM inference
- **`ProviderBase`** - Provider interface

## License

MIT License - see LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Run the test suite
5. Submit a pull request

## Support

- **Issues**: [GitHub Issues](https://github.com/gleitzeit/gleitzeit-v4/issues)
- **Documentation**: [docs.gleitzeit.dev](https://docs.gleitzeit.dev)
- **Community**: [Discord](https://discord.gg/gleitzeit)