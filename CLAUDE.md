# Gleitzeit - Task and Workflow Orchestration System (v0.0.4)

## Project Overview

Gleitzeit is a protocol-based orchestration system designed for coordinating LLM workflows with multi-task, multi-method execution patterns. It features an event-driven architecture with support for multiple persistence backends and provider types.

**Version:** 0.0.4  
**Location:** `/old/gleitzeit_v4/` (current active codebase)

## Core Features

- **LLM Workflow Coordination** - Orchestrate complex LLM interactions and chains
- **Multi-Task Workflows** - Combine different task types (LLM, Python, MCP) in workflows  
- **Protocol-Based** - JSON-RPC 2.0 foundation with native MCP support
- **Multiple Backends** - SQLite, Redis, or in-memory persistence
- **Dependency Management** - Tasks can depend on outputs from previous tasks
- **YAML Workflows** - Define complex workflows declaratively
- **Event-Driven Architecture** - Asynchronous task execution with retry support

## Architecture Overview

```
Central Server (Event Coordinator)
├── Task Queue - Priority-based task scheduling with persistence
├── Dependency Resolver - Parameter substitution and circular detection
├── Workflow Manager - Workflow lifecycle and state management
├── Execution Engine - Task execution and retry management
└── Provider System - Pluggable execution backends
    ├── Ollama Provider - LLM interactions
    ├── Python Function Provider - Local Python execution
    ├── MCP Provider - Model Context Protocol support
    └── Mock Providers - Testing and development
```

## Core Components

### `/old/gleitzeit_v4/core/` - Core Infrastructure
- **`models.py`**: Core data models (Task, Workflow, Provider)
- **`events.py`**: Event system and correlation tracking
- **`errors.py`**: Centralized error handling
- **`jsonrpc.py`**: JSON-RPC 2.0 implementation
- **`protocol.py`**: Protocol specification and validation
- **`workflow_manager.py`**: Workflow lifecycle management
- **`execution_engine.py`**: Task execution coordination
- **`dependency_tracker.py`**: Dependency resolution and parameter substitution
- **`scheduler.py`**: Task scheduling and priority management
- **`retry_manager.py`**: Retry logic and backoff strategies

### `/old/gleitzeit_v4/server/` - Server Components
- **`central_server.py`**: Main server implementation with event routing

### `/old/gleitzeit_v4/task_queue/` - Task Management
- **`task_queue.py`**: Priority queue with persistence support
- **`dependency_resolver.py`**: Dependency graph resolution

### `/old/gleitzeit_v4/persistence/` - Storage Backends
- **`base.py`**: Abstract persistence interface
- **`sqlite_backend.py`**: SQLite persistence implementation
- **`redis_backend.py`**: Redis persistence implementation

### `/old/gleitzeit_v4/providers/` - Provider Implementations
- **`base.py`**: Base provider interface
- **`ollama_provider.py`**: Ollama LLM provider
- **`python_function_provider.py`**: Python code execution
- **`mcp_provider.py`**: MCP protocol provider
- **`echo_provider.py`**: Simple echo provider for testing
- **`mock_*_provider.py`**: Mock providers for testing

### `/old/gleitzeit_v4/protocols/` - Protocol Definitions
- **`llm_protocol.py`**: LLM protocol specification
- **`python_protocol.py`**: Python execution protocol
- **`mcp_protocol.py`**: MCP protocol specification

### `/old/gleitzeit_v4/pooling/` - Connection Pooling
- **`manager.py`**: Connection pool management
- **`pool.py`**: Pool implementation
- **`worker.py`**: Worker thread management
- **`backpressure.py`**: Backpressure handling
- **`circuit_breaker.py`**: Circuit breaker pattern

### `/old/gleitzeit_v4/cli/` - Command Line Interface
- **`gleitzeit_cli.py`**: Main CLI entry point
- **`commands/`**: Individual command implementations
  - **`submit.py`**: Workflow submission
  - **`status.py`**: Status checking
  - **`dev.py`**: Development commands
- **`workflow.py`**: Workflow management CLI
- **`config.py`**: CLI configuration

### `/old/gleitzeit_v4/client/` - Client Libraries
- **`socketio_engine.py`**: SocketIO client implementation
- **`socketio_provider.py`**: SocketIO-based provider client

## CLI Commands & Usage

### Installation
```bash
# From the /old/gleitzeit_v4/ directory
pip install -e .

# With development dependencies
pip install -e .[dev]

# With all optional dependencies
pip install -e .[all]
```

### Basic Commands
```bash
# Submit a workflow
gleitzeit workflow submit examples/llm_workflow.yaml

# Check workflow status
gleitzeit workflow status WORKFLOW_ID

# View system status
gleitzeit system status

# Start development server
gleitzeit dev start

# View help
gleitzeit --help
```

### Workflow Management
```bash
# List all workflows
gleitzeit workflow list

# Get workflow details
gleitzeit workflow get WORKFLOW_ID

# Cancel a workflow
gleitzeit workflow cancel WORKFLOW_ID
```

## Example Workflows

### Simple LLM Workflow
Location: `/old/gleitzeit_v4/examples/llm_workflow.yaml`
```yaml
name: "Simple LLM Workflow"
tasks:
  - name: "generate_text"
    protocol: "llm/v1"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Write a haiku about coding"
```

### Dependent Workflow
Location: `/old/gleitzeit_v4/examples/dependent_workflow.yaml`
```yaml
name: "Dependent Tasks"
tasks:
  - name: "first_task"
    protocol: "llm/v1"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Generate a topic"
  
  - name: "second_task"
    protocol: "llm/v1"
    method: "llm/chat"
    dependencies: ["first_task"]
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Write about: ${first_task.result}"
```

### Mixed Provider Workflow
Location: `/old/gleitzeit_v4/examples/mixed_workflow.yaml`
```yaml
name: "Mixed Provider Workflow"
tasks:
  - name: "llm_task"
    protocol: "llm/v1"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Generate Python code to calculate fibonacci"
  
  - name: "python_task"
    protocol: "python/v1"
    method: "python/execute"
    dependencies: ["llm_task"]
    parameters:
      code: "${llm_task.result}"
```

## Testing

### Test Structure
Location: `/old/gleitzeit_v4/tests/`

- **Core Tests**: `test_core_*.py` - Core component testing
- **Integration Tests**: `test_*_integration.py` - Full system tests
- **Provider Tests**: `test_*_provider.py` - Provider implementations
- **Workflow Tests**: `test_*_workflow.py` - Workflow execution
- **CLI Tests**: `test_cli*.py` - Command line interface

### Running Tests
```bash
# Run all tests
cd /old/gleitzeit_v4
pytest

# Run specific test categories
pytest tests/test_core_components.py
pytest tests/test_integration.py

# Run with coverage
pytest --cov=. tests/

# Run test suite scripts
python tests/run_all_tests.py
python tests/run_core_tests.py
```

## Configuration

### Environment Variables
```bash
# Server configuration
GLEITZEIT_HOST=127.0.0.1
GLEITZEIT_PORT=8765
GLEITZEIT_LOG_LEVEL=INFO

# Persistence backend
GLEITZEIT_BACKEND=sqlite  # or 'redis', 'memory'
GLEITZEIT_SQLITE_PATH=./gleitzeit.db
GLEITZEIT_REDIS_URL=redis://localhost:6379

# Provider configuration
OLLAMA_HOST=http://localhost:11434
```

### Provider Configuration
Providers are configured via the central server initialization:

```python
# In server startup
providers = {
    "ollama": OllamaProvider(base_url="http://localhost:11434"),
    "python": PythonFunctionProvider(),
    "mcp": MCPProvider(),
}
```

## Development

### Project Structure
```
/old/gleitzeit_v4/
├── cli/                 # CLI implementation
├── client/              # Client libraries
├── core/                # Core infrastructure
├── examples/            # Example workflows
├── integrations/        # External integrations
├── persistence/         # Storage backends
├── pooling/            # Connection pooling
├── protocols/          # Protocol definitions
├── providers/          # Provider implementations
├── server/             # Server implementation
├── task_queue/         # Task queue management
├── tests/              # Test suite
├── docs/               # Documentation
├── setup.py            # Package configuration
└── README.md           # Project readme
```

### Adding New Providers
1. Create provider class inheriting from `ProviderBase` in `/old/gleitzeit_v4/providers/`
2. Implement required methods: `execute()`, `validate_parameters()`
3. Register provider in server initialization
4. Add protocol specification if needed

### Adding New Protocols
1. Define protocol in `/old/gleitzeit_v4/protocols/`
2. Create JSON Schema for validation
3. Implement provider supporting the protocol
4. Add examples and tests

### Key Development Files
- **Main entry**: `/old/gleitzeit_v4/main.py`
- **CLI entry**: `/old/gleitzeit_v4/cli/gleitzeit_cli.py`
- **Server**: `/old/gleitzeit_v4/server/central_server.py`
- **Setup**: `/old/gleitzeit_v4/setup.py`

## Dependencies

### Core Requirements
- `click>=8.0.0` - CLI framework
- `pydantic>=2.0.0` - Data validation
- `pyyaml>=6.0.0` - YAML parsing
- `aiohttp>=3.8.0` - Async HTTP
- `aiosqlite>=0.19.0` - SQLite backend
- `redis>=4.5.0` - Redis backend
- `httpx>=0.24.0` - HTTP client

### Development Requirements
- `pytest>=7.0.0` - Testing framework
- `pytest-asyncio>=0.21.0` - Async test support
- `black>=23.0.0` - Code formatting
- `mypy>=1.0.0` - Type checking
- `ruff>=0.1.0` - Linting

## Documentation

### Available Documentation
- `/old/gleitzeit_v4/README.md` - Main project documentation
- `/old/gleitzeit_v4/docs/GLEITZEIT_V4_ARCHITECTURE.md` - Architecture overview
- `/old/gleitzeit_v4/docs/GLEITZEIT_V4_DESIGN.md` - Design principles
- `/old/gleitzeit_v4/docs/PROTOCOLS_PROVIDERS_EXECUTION.md` - Protocol details
- `/old/gleitzeit_v4/docs/EVENT_ROUTING.md` - Event system documentation
- `/old/gleitzeit_v4/docs/TASK_QUEUE_PERSISTENCE.md` - Persistence details
- `/old/gleitzeit_v4/docs/CLI_COMMANDS.md` - CLI reference

## Key Features

### Protocol-Based Design
- Clean separation between protocol definition and implementation
- Support for multiple protocols (LLM, Python, MCP)
- JSON-RPC 2.0 foundation for standardized communication

### Persistence Options
- **SQLite**: Default, good for single-node deployments
- **Redis**: Distributed, good for multi-node deployments
- **Memory**: Fast, for testing and development

### Task Dependencies
- Automatic dependency resolution
- Parameter substitution from previous task outputs
- Circular dependency detection

### Retry Management
- Configurable retry policies per task
- Exponential backoff support
- Circuit breaker pattern for provider protection

### Connection Pooling
- Efficient resource management
- Backpressure handling
- Worker thread pooling

## Common Workflows

### Development Workflow
```bash
# Start development server
cd /old/gleitzeit_v4
gleitzeit dev start

# In another terminal, submit a workflow
gleitzeit workflow submit examples/llm_workflow.yaml

# Monitor status
gleitzeit workflow status <workflow_id>
```

### Testing Workflow
```bash
# Run unit tests
pytest tests/test_core_components.py

# Run integration tests
pytest tests/test_integration.py

# Run all tests with coverage
pytest --cov=. tests/
```

This system provides a robust foundation for orchestrating complex workflows involving LLMs, Python execution, and other providers, with a focus on reliability, extensibility, and ease of use.