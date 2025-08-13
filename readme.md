# Gleitzeit - Socket.IO Workflow Orchestration System

## Project Overview

Gleitzeit is a modern, Socket.IO-based distributed workflow orchestration system designed for real-time task execution. 

**Key Characteristics:**
- Pure Socket.IO event-driven communication
- Distributed, fault-tolerant microservices
- Real-time workflow orchestration
- YAML-based configuration and workflows
- Pluggable provider system (LLM, Python, custom)

## Architecture Overview

```
Central Hub (Socket.IO Server) - Pure event router
├── Queue Manager - Task queuing and workflow coordination
├── Dependency Resolver - Parameter substitution and dependency resolution  
├── Execution Engine - Task execution and provider coordination
└── Providers (Universal) - Pluggable execution backends
    ├── Ollama LLM Provider
    ├── Python Local Provider
    └── Custom Providers (extensible)
```

## Core Components

### `/base/` - Foundation Framework
- **`component.py`**: `SocketIOComponent` base class for all distributed components
- **`config.py`**: Environment-based configuration (`ComponentConfig`)
- **`events.py`**: Event routing, correlation tracking, component registry

### `/hub/` - Central Coordination
- **`central_hub.py`**: `CentralHub` - pure Socket.IO event router and component registry
- No business logic - only routes events and maintains health monitoring

### `/components/` - Business Logic Components
- **`queue_manager.py`**: `QueueManagerClient` - task queuing, priority scheduling, workflow coordination
- **`dependency_resolver.py`**: `DependencyResolverClient` - parameter substitution, dependency resolution, circular detection
- **`execution_engine.py`**: `ExecutionEngineClient` - task execution coordination, provider routing

### `/core/` - System Infrastructure
- **`protocol.py`**: Protocol specification and validation system
- **`provider_factory.py`**: Dynamic provider creation from YAML
- **`executor_base.py`**: Base executor framework for providers
- **`yaml_loader.py`**: YAML configuration loading and validation
- **`jsonrpc.py`**: JSON-RPC 2.0 request/response handling
- **`errors.py`**: Centralized error handling

### `/protocols/` & `/providers/` - Provider System
- **Protocol definitions**: LLM and Python protocols with JSON Schema validation
- **Universal provider**: Single provider supporting multiple protocols via executor pattern
- **YAML configuration**: Dynamic provider/protocol loading from YAML files

## Key Development Patterns

### Socket.IO Component Pattern
All components inherit from `SocketIOComponent`:
```python
class MyComponent(SocketIOComponent):
    async def on_my_event(self, data):
        # Handle event with automatic correlation tracking
        result = await self.process(data)
        await self.emit_correlated('response_event', result, data)
```

### Event-Driven Communication
All inter-component communication uses Socket.IO events:
```python
# Event emission with correlation
await self.emit_correlated('execute_task', task_data, original_event)

# Event handling with correlation
@component.event_handler('execute_task')
async def handle_execution(self, data):
    # Process and respond
    await self.emit_correlated('task_completed', result, data)
```

### Provider Development
Providers use the Universal Provider + Executor pattern:
1. Create YAML configuration in `providers/yaml/`
2. Implement executor in `core/executor_base.py` 
3. Define protocol in `protocols/yaml/`
4. Register with system via YAML loading

### Workflow Definition
Workflows are YAML files with parameter substitution:
```yaml
name: "Example Workflow"
tasks:
  - id: "llm_task"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Hello world"
  
  - id: "python_task"
    method: "python/execute"
    dependencies: ["llm_task"]
    parameters:
      code: "print('LLM said:', '${llm_task.response}')"
```

## CLI Commands & Usage

### Quick Start Commands
```bash
# One-command workflow execution (recommended)
gleitzeit run examples/simple_llm_workflow.yaml

# Start everything and monitor
gleitzeit start
gleitzeit monitor
```

### Component Control
```bash
# Start individual components
gleitzeit hub --port 8001
gleitzeit components queue deps exec

# Auto-start features (hub starts automatically)
gleitzeit submit workflow.yaml
gleitzeit monitor
gleitzeit status
```

### Development Commands
```bash
# Check system status
gleitzeit status

# List available providers
gleitzeit providers

# Real-time monitoring
gleitzeit monitor
```

## Testing Framework

### Test Structure
- **Unit tests**: Individual component testing with extensive mocking
- **Integration tests**: Full component interaction testing  
- **CLI tests**: Command-line interface testing
- **Async support**: Full pytest-asyncio integration

### Test Patterns
```python
# Async component testing
@pytest.mark.asyncio
async def test_component():
    with patch('component.dependency') as mock_dep:
        result = await component.method()
        assert result == expected

# CLI testing with mocking
def test_cli_command():
    with patch('gleitzeit_v5.cli.GleitzeitCLI') as mock_cli:
        mock_cli.return_value.start = AsyncMock(return_value=True)
        # Test CLI behavior
```

### Running Tests
```bash
# Install dev dependencies
pip install -e .[dev]

# Run all tests
pytest

# Run specific test categories
pytest -m unit
pytest -m integration
pytest -m slow
```

## Configuration System

### Environment Configuration
Components use environment-based configuration:
```python
class ComponentConfig:
    hub_url: str = os.getenv('GLEITZEIT_HUB_URL', 'http://localhost:8000')
    redis_url: str = os.getenv('GLEITZEIT_REDIS_URL', 'redis://localhost:6379')
    log_level: str = os.getenv('GLEITZEIT_LOG_LEVEL', 'INFO')
```

### YAML Configuration
- **Protocols**: Define method specifications with JSON Schema validation
- **Providers**: Configure provider endpoints, authentication, capabilities
- **Workflows**: Define task sequences with dependencies and parameters

## Package Structure & Setup

### Installation
```bash
# Development installation
pip install -e .

# With development tools
pip install -e .[dev]

# With all optional dependencies
pip install -e .[all]
```

### Entry Points
- `gleitzeit` - Main CLI command
- `gz` - Short alias for quick access

### Dependencies
**Core requirements:**
- `python-socketio>=5.8.0` - Real-time communication
- `aiohttp>=3.8.0` - HTTP client/server
- `pydantic>=2.0.0` - Data validation
- `pyyaml>=6.0.0` - YAML configuration
- `rich>=13.0.0` - Beautiful CLI output
- `click>=8.0.0` - CLI framework

**Development tools:**
- `pytest>=7.0.0` + `pytest-asyncio>=0.21.0` - Testing
- `black>=23.0.0` - Code formatting  
- `mypy>=1.0.0` - Type checking
- `ruff>=0.1.0` - Linting

## Development Workflow

### Adding New Components
1. Inherit from `SocketIOComponent`
2. Implement event handlers with `@event_handler` decorator
3. Use correlation tracking for all events
4. Add component to CLI startup

### Adding New Providers
1. Create YAML configuration in `providers/yaml/`
2. Define protocol specification in `protocols/yaml/`
3. Implement executor class inheriting from `ExecutorBase`
4. Register with `ProviderFactory`

### Adding New Protocols
1. Define protocol methods and parameters
2. Create JSON Schema validation
3. Add protocol YAML configuration
4. Update provider implementations

### Code Style & Standards
- **Async/await**: All I/O operations are async
- **Type hints**: Full type annotation with Pydantic models
- **Error handling**: Centralized error codes and correlation tracking
- **Logging**: Structured logging with correlation IDs
- **Testing**: High test coverage with mocking for external dependencies

## Deployment Patterns

### Single Machine Development
```bash
# All components on localhost
gleitzeit start
```

### Distributed Deployment
```bash
# Hub on central server
GLEITZEIT_HUB_URL=http://hub-server:8000 gleitzeit hub

# Components on worker nodes  
GLEITZEIT_HUB_URL=http://hub-server:8000 gleitzeit components all
```

### Container Deployment
- Environment variable configuration
- Health check endpoints available
- Graceful shutdown handling
- Horizontal scaling support

## Key Files & Locations

### Configuration Files
- `setup.py` - Package configuration and dependencies
- `requirements.txt` - Core Python dependencies
- `pytest.ini` - Test configuration with async support

### Example Workflows
- `examples/simple_llm_workflow.yaml` - Basic LLM tasks
- `examples/dependent_workflow.yaml` - Task dependencies
- `examples/mixed_workflow.yaml` - Multi-provider workflows
- `examples/parallel_workflow.yaml` - Parallel execution
- `examples/vision_workflow.yaml` - Image processing

### Protocol & Provider Configs
- `protocols/yaml/llm.yaml` - LLM protocol specification
- `protocols/yaml/python.yaml` - Python execution protocol
- `providers/yaml/ollama.yaml` - Ollama LLM provider
- `providers/yaml/python_local.yaml` - Local Python provider

## Architecture Benefits

1. **True Horizontal Scaling**: Add instances of any component type
2. **Fault Tolerance**: Component failures don't affect system
3. **Real-time Updates**: Socket.IO enables instant progress monitoring
4. **Development Flexibility**: Independent component development
5. **Protocol Flexibility**: Easy addition of new execution backends
6. **Observability**: Full event correlation and tracing

## Common Development Tasks

### Running Quick Tests
```bash
# Test basic functionality
python test_basic_hub.py
python test_cli_quick.py

# Test specific integrations  
python test_ollama_integration.py
python test_yaml_provider_integration.py
```

### Debugging Components
```bash
# Start with verbose logging
GLEITZEIT_LOG_LEVEL=DEBUG gleitzeit start

# Monitor events in real-time
gleitzeit monitor

# Check component health
gleitzeit status
```

### Adding New Workflow Examples
1. Create YAML file in `examples/`
2. Test with `gleitzeit run examples/your_workflow.yaml`
3. Add corresponding test in test files
4. Update documentation

This system represents a modern approach to distributed workflow orchestration, emphasizing real-time communication, fault tolerance, and horizontal scalability while maintaining simplicity in component design and deployment.
