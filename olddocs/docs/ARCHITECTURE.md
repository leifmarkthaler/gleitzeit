# Gleitzeit Architecture Overview

## Table of Contents
1. [System Architecture](#system-architecture)
2. [Core Components](#core-components)
3. [Data Flow](#data-flow)
4. [Design Principles](#design-principles)
5. [Component Interactions](#component-interactions)

## System Architecture

Gleitzeit v0.0.5 is built on a layered architecture with clear separation of concerns:

```
┌─────────────────────────────────────────────────────────┐
│                   User Interface Layer                   │
│                  (CLI, Python API, YAML)                 │
└─────────────────────────┬───────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────┐
│                  Orchestration Layer                     │
│                    ExecutionEngine                       │
│         ┌──────────────┬──────────────┬──────────┐     │
│         │ QueueManager │ Dependency   │ Workflow │     │
│         │              │ Resolver     │ Loader   │     │
│         └──────────────┴──────────────┴──────────┘     │
└─────────────────────────┬───────────────────────────────┘
                          │
        ┌─────────────────┴─────────────────┐
        │                                   │
┌───────▼────────┐               ┌──────────▼──────────┐
│ Protocol Layer │               │  Resource Layer     │
│                │               │                     │
│  ┌──────────┐  │               │  ┌──────────────┐  │
│  │ Registry │  │               │  │ResourceManager│  │
│  └────┬─────┘  │               │  └──────┬───────┘  │
│       │        │               │         │          │
│  ┌────▼─────┐  │               │  ┌──────▼──────┐   │
│  │Providers │  │               │  │    Hubs     │   │
│  │          │  │               │  │             │   │
│  │ • Ollama │  │               │  │ • OllamaHub │   │
│  │ • Python │  │               │  │ • DockerHub │   │
│  │ • MCP    │  │               │  └─────────────┘   │
│  └──────────┘  │               └─────────────────────┘
└────────────────┘
         │                                   │
         └─────────────┬─────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                   Persistence Layer                      │
│                UnifiedPersistenceAdapter                 │
│         ┌──────────┬──────────┬──────────┐             │
│         │  Redis   │  SQLite  │  Memory  │             │
│         │ Adapter  │ Adapter  │ Adapter  │             │
│         └──────────┴──────────┴──────────┘             │
└──────────────────────────────────────────────────────────┘
```

## Core Components

### 1. ExecutionEngine
**Location**: `src/gleitzeit/core/execution_engine.py`

The central orchestrator that coordinates all workflow execution:
- Manages workflow lifecycle
- Handles task dependencies
- Coordinates with providers and resources
- Maintains execution state

**Key Responsibilities**:
- Submit and execute workflows
- Resolve task dependencies
- Route tasks to appropriate providers
- Collect and store results
- Handle errors and retries

### 2. ProtocolProviderRegistry
**Location**: `src/gleitzeit/core/registry.py`

Manages protocol definitions and provider instances:
- Registers protocols and their specifications
- Maps methods to providers
- Validates method calls against protocol specs
- Manages provider lifecycle

**Key Features**:
- Protocol inheritance support
- Method validation
- Provider instance management
- Dynamic provider loading

### 3. ResourceManager
**Location**: `src/gleitzeit/hub/resource_manager.py`

Orchestrates multiple resource hubs:
- Global resource allocation
- Cross-hub metrics aggregation
- Resource optimization
- Allocation tracking

**Key Features**:
- Multi-hub orchestration
- Resource allocation strategies
- Global metrics collection
- Event coordination

### 4. Resource Hubs
**Location**: `src/gleitzeit/hub/`

Manage specific types of compute resources:

#### OllamaHub
- Manages Ollama server instances
- Health monitoring and metrics
- Auto-discovery of running instances
- Load balancing support

#### DockerHub
- Container lifecycle management
- Resource limit enforcement
- Container pooling for reuse
- Secure execution environment

### 5. Providers
**Location**: `src/gleitzeit/providers/`

Execute protocol methods using hub resources:

#### OllamaProvider
- LLM operations (chat, vision)
- Uses OllamaHub for server access
- Streaming support
- File content injection

#### PythonProvider
- Python code execution
- Uses DockerHub for security
- Restricted to container execution
- No arbitrary script support

#### SimpleMCPProvider
- MCP tool execution
- JSON-RPC communication
- Tool validation

### 6. UnifiedPersistenceAdapter
**Location**: `src/gleitzeit/persistence/`

Single interface for all persistence needs:
- Automatic fallback chain (Redis → SQLite → Memory)
- Cross-domain operations
- Transaction support
- Zero configuration

## Data Flow

### Workflow Execution Flow

```
1. User submits workflow (CLI/API)
        ↓
2. WorkflowLoader parses YAML
        ↓
3. ExecutionEngine receives workflow
        ↓
4. QueueManager queues tasks
        ↓
5. DependencyResolver orders tasks
        ↓
6. For each task:
   a. Registry finds appropriate provider
   b. Provider requests resources from hub
   c. Provider executes method
   d. Results stored in persistence
   e. Parameter substitution for next tasks
        ↓
7. Workflow complete, results returned
```

### Resource Allocation Flow

```
1. Provider needs resource (e.g., Ollama server)
        ↓
2. Provider requests from its hub
        ↓
3. Hub checks available instances
        ↓
4. Hub performs health check
        ↓
5. Hub returns healthy instance
        ↓
6. Provider uses instance
        ↓
7. Hub tracks metrics
```

## Design Principles

### 1. Separation of Concerns
- **Providers** handle protocol execution only
- **Hubs** manage resource lifecycle only
- **Persistence** handles storage uniformly
- **Engine** orchestrates without implementation details

### 2. Clean Interfaces
- Each component has a well-defined interface
- Dependencies are explicit and minimal
- Components are replaceable/testable

### 3. Fault Tolerance
- Automatic persistence fallback
- Health monitoring and recovery
- Graceful degradation
- Comprehensive error handling

### 4. Scalability
- Parallel task execution
- Resource pooling
- Efficient queue management
- Metrics-based optimization

### 5. Security
- Container isolation for code execution
- Restricted Python environment
- No arbitrary script execution
- Resource limits enforcement

## Component Interactions

### Provider-Hub Interaction
```python
# Provider requests resource from hub
provider = OllamaProvider(
    provider_id="ollama",
    ollama_hub=hub  # Dependency injection
)

# During execution
async def handle_request(self, method, params):
    # Provider uses hub to get healthy instance
    instance = await self.hub.get_available_instance()
    # Execute using instance
    result = await self._execute_on_instance(instance, method, params)
    return result
```

### Engine-Registry Interaction
```python
# Engine routes task to provider
provider = await registry.get_provider_for_method(task.method)
result = await provider.execute(task.method, task.params)
```

### Persistence Interaction
```python
# Unified interface for all components
await persistence.save_task(task)
await persistence.save_workflow(workflow)
await persistence.save_instance(hub_id, instance)
```

## Key Architectural Decisions

### 1. Hub-Provider Separation
**Decision**: Separate resource management from protocol execution
**Rationale**: 
- Cleaner testing (mock hubs for provider tests)
- Better resource management (centralized monitoring)
- Flexibility (providers can use multiple hubs)

### 2. Unified Persistence
**Decision**: Single adapter interface with fallback chain
**Rationale**:
- Simplifies implementation
- Automatic reliability
- Zero configuration for users

### 3. Container-Only Python Execution
**Decision**: Remove arbitrary script execution, require containers
**Rationale**:
- Security (complete isolation)
- Resource control (memory/CPU limits)
- Reproducibility (consistent environment)

### 4. Event-Driven Architecture
**Decision**: Use events for hub-provider communication
**Rationale**:
- Loose coupling
- Extensibility
- Real-time monitoring

## Performance Considerations

### Optimization Points
1. **Connection Pooling**: Reuse HTTP connections in providers
2. **Container Pooling**: Reuse Docker containers in DockerHub
3. **Parallel Execution**: Execute independent tasks concurrently
4. **Lazy Loading**: Load providers only when needed
5. **Efficient Persistence**: Batch operations where possible

### Bottlenecks and Solutions
1. **LLM Inference**: Use multiple Ollama instances
2. **Container Startup**: Pool and reuse containers
3. **Network Latency**: Local caching and connection pooling
4. **Persistence**: Redis for high-throughput scenarios

## Testing Architecture

### Test Layers
1. **Unit Tests**: Individual component testing
2. **Integration Tests**: Component interaction testing
3. **End-to-End Tests**: Full workflow execution
4. **Performance Tests**: Load and stress testing

### Test Coverage
- 193+ unit tests
- 100% pass rate
- Mock implementations for all major components
- Comprehensive error case coverage

## Future Architecture Considerations

### Potential Enhancements
1. **Distributed Execution**: Multi-node support
2. **Plugin System**: Dynamic provider/hub loading
3. **Event Streaming**: Real-time workflow monitoring
4. **Advanced Scheduling**: Priority queues, deadlines
5. **Resource Prediction**: ML-based resource allocation

### Scalability Path
1. **Horizontal Scaling**: Multiple engine instances
2. **Resource Federation**: Cross-cluster resource sharing
3. **Distributed Persistence**: Shared state across nodes
4. **Load Balancing**: Smart task distribution

## Summary

Gleitzeit v0.0.5's architecture provides:
- **Clean separation** of concerns
- **Robust persistence** with automatic fallback
- **Comprehensive resource management**
- **Security-first** design
- **Extensible** and testable components

The architecture is designed to be both powerful for complex workflows and simple for basic use cases, with sensible defaults and zero-configuration operation.