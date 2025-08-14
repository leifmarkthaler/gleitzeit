# Gleitzeit V4 - Task Orchestration System

A protocol-based task execution system for orchestrating workflows with async/await patterns.

**Version:** 0.0.4

## Core Features

- **Task Orchestration** - Execute tasks with dependency management
- **Protocol-Based** - JSON-RPC 2.0 foundation for provider integration
- **Multiple Backends** - SQLite, Redis, or in-memory persistence
- **Provider Support** - Python execution, Ollama LLM, extensible architecture
- **Workflow Management** - YAML-based workflow definitions
- **CLI Interface** - Command-line tools for task and workflow management

## Quick Start

### Installation

```bash
pip install -e .
```

### Basic Usage

```bash
# Execute Python code
python cli.py task submit python/execute --code "print('Hello World')"

# Submit a workflow
python cli.py workflow submit examples/simple_workflow.yaml

# Check system status  
python cli.py system status

# View help
python cli.py --help
```

## Workflow Example

Create a simple workflow (`my_workflow.yaml`):

```yaml
name: "Example Workflow"
description: "Simple calculation workflow"
tasks:
  - name: "calculate"
    protocol: "python/v1"
    method: "python/execute"
    params:
      code: |
        import math
        result = math.sqrt(16) * 2
        print(f"Result: {result}")
```

Run it:
```bash
python cli.py workflow submit my_workflow.yaml
```

## Provider Support

### Python Provider
Execute Python code with restricted environment:
```bash
python cli.py task submit python/execute --code "result = sum([1,2,3,4,5])"
```

### Ollama Provider  
LLM inference via Ollama:
```bash
python cli.py task submit llm/chat --model "llama3" --messages '[{"role":"user","content":"Hello"}]'
```

## Architecture

- **Tasks** specify protocols and methods using JSON-RPC 2.0
- **Providers** implement protocol interfaces for different services
- **Registry** manages provider lifecycle and routing
- **Queue System** handles task scheduling and dependencies
- **Persistence** stores tasks, results, and workflow state

## CLI Commands

### Task Management
```bash
# Submit single task
python cli.py task submit PROTOCOL/METHOD [options]

# List submitted tasks
python cli.py task list

# Get task result
python cli.py task result TASK_ID
```

### Workflow Management
```bash
# Submit workflow from YAML
python cli.py workflow submit workflow.yaml

# List workflows
python cli.py workflow list

# Get workflow status
python cli.py workflow status WORKFLOW_ID
```

### Provider Management
```bash
# List available providers
python cli.py provider list

# Check provider health
python cli.py provider health PROVIDER_ID
```

### Backend Operations
```bash
# View system statistics
python cli.py backend get-stats

# List all tasks
python cli.py backend list-tasks

# Get results by workflow
python cli.py backend get-results-by-workflow WORKFLOW_NAME
```

## Configuration

Set environment variables for customization:

```bash
# Persistence backend
export GLEITZEIT_PERSISTENCE_BACKEND=sqlite  # redis, sqlite, none

# Database connections
export GLEITZEIT_REDIS_URL=redis://localhost:6379/0
export GLEITZEIT_SQLITE_PATH=~/.gleitzeit/gleitzeit.db

# Provider settings
export GLEITZEIT_OLLAMA_URL=http://localhost:11434
```

## Development

### Running Tests
```bash
# Core system tests
PYTHONPATH=. python run_core_tests.py

# CLI tests
PYTHONPATH=. python tests/test_comprehensive_cli.py
```

### Project Structure
```
├── core/                 # Core execution engine, models, protocols
├── providers/           # Provider implementations
├── persistence/        # Backend storage implementations  
├── task_queue/         # Queue management and scheduling
├── tests/              # Test suite
├── cli.py              # Main CLI interface
└── registry.py         # Provider registry and management
```

## Examples

See the `examples/` directory for workflow templates:
- `simple_workflow.yaml` - Basic Python execution
- `dependent_workflow.yaml` - Tasks with dependencies
- `llm_workflow.yaml` - LLM-based workflows

## Documentation

- `CLI_COMMANDS.md` - Complete CLI reference
- `PROVIDER_LIFECYCLE_MANAGEMENT.md` - Provider development guide
- `GLEITZEIT_V4_DESIGN.md` - Architecture overview

## License

See LICENSE file for details.