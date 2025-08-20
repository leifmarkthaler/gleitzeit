# Gleitzeit System Architecture

## Overview

Gleitzeit is a workflow orchestration system designed with a clean, layered architecture that separates concerns between protocol definition, task execution, resource management, and persistence. The system follows a hub-and-spoke model for resource management and uses an event-driven execution engine for workflow processing.

## Core Design Principles

1. **Protocol-Based Abstraction**: All execution capabilities are defined through protocols, allowing for extensible and pluggable providers
2. **Separation of Concerns**: Resource management (hubs) is separated from protocol execution (providers)
3. **Event-Driven Execution**: Asynchronous, non-blocking workflow execution with dependency resolution
4. **Unified Persistence**: Single adapter interface with automatic fallback (Redis → SQL → Memory)
5. **Type Safety**: Comprehensive type hints and Pydantic models for validation
6. **Resilience**: Built-in retry logic, health monitoring, and graceful degradation

## System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                           User Interface                             │
│                    (CLI / Python Client / REST API)                 │
└────────────────────────────┬────────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────────┐
│                        GleitzeitClient                               │
│                 (Unified API / Mode Selection)                       │
└────────────────────────────┬────────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────────┐
│                      Execution Engine                                │
│         (Workflow Orchestration / Task Scheduling)                   │
├──────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐    │
│  │ Task Queue   │  │ Dependency   │  │ Parameter              │    │
│  │ Manager      │  │ Resolver     │  │ Substitution Engine    │    │
│  └──────────────┘  └──────────────┘  └────────────────────────┘    │
└────────────────┬───────────────────────────┬────────────────────────┘
                 │                           │
        Protocol Layer                Resource Layer
                 │                           │
┌────────────────▼──────────────┐  ┌────────▼────────────────────────┐
│     Protocol Registry          │  │    Resource Manager             │
├────────────────────────────────┤  ├─────────────────────────────────┤
│  ┌──────────────────────────┐ │  │  ┌───────────┐ ┌────────────┐  │
│  │ Protocol Specifications  │ │  │  │OllamaHub  │ │DockerHub   │  │
│  ├──────────────────────────┤ │  │  └───────────┘ └────────────┘  │
│  │ • LLM Protocol (llm/v1)  │ │  │  ┌───────────┐                  │
│  │ • Python (python/v1)     │ │  │  │MCPHub     │                  │
│  │ • MCP (mcp/v1)          │ │  │  └───────────┘                  │
│  └──────────────────────────┘ │  └─────────────────────────────────┘
├────────────────────────────────┤
│        Providers               │
│  ┌──────────────────────────┐ │
│  │ OllamaProvider           │ │
│  │ PythonProvider           │ │
│  │ MCPHubProvider           │ │
│  └──────────────────────────┘ │
└────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────────────┐
│                      Persistence Layer                               │
│                  (Unified Adapter Interface)                         │
├──────────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐    │
│  │Redis Adapter│  │SQL Adapter  │  │Memory Adapter           │    │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
```

## Component Architecture

### 1. Client Layer

#### GleitzeitClient (`client.py`)
The unified client interface that provides:
- **Mode Selection**: Auto, API, or Native mode
- **High-Level Methods**: `run_workflow()`, `chat()`, `batch_process()`
- **Resource Management**: Optional resource management capabilities
- **Context Management**: Async context manager for proper lifecycle

```python
# Client automatically handles mode selection and setup
async with GleitzeitClient(mode="auto") as client:
    result = await client.run_workflow("workflow.yaml")
```

### 2. Execution Layer

#### ExecutionEngine (`core/execution_engine.py`)
The central orchestrator that:
- **Manages workflow lifecycle**: Submission, execution, completion
- **Runs in event-driven mode**: Continuously processes task queue
- **Handles task state transitions**: PENDING → RUNNING → COMPLETED/FAILED
- **Manages retries**: Exponential backoff with configurable attempts

#### TaskQueue (`task_queue/queue_manager.py`)
Priority-based task queue with:
- **Priority scheduling**: Higher priority tasks execute first
- **Dependency tracking**: Ensures prerequisites complete before dependent tasks
- **Concurrency control**: Manages parallel execution limits

#### DependencyResolver (`task_queue/dependency_resolver.py`)
- **Topological sorting**: Determines execution order
- **Cycle detection**: Prevents circular dependencies
- **Dynamic resolution**: Updates as tasks complete

#### ParameterSubstitution (`core/parameter_substitution.py`)
- **Template resolution**: Replaces `${task_id.field}` with actual values
- **Nested access**: Supports `${task.result.data.value}`
- **Type preservation**: Maintains JSON types during substitution

### 3. Protocol Layer

#### Protocol Registry (`registry.py`)
Central registry managing:
- **Protocol registration**: Maps protocol IDs to specifications
- **Provider registration**: Associates providers with protocols
- **Method routing**: Routes method calls to appropriate providers
- **Validation**: Ensures protocol compliance

#### Protocol Specifications
Defined in `protocols/` directory:

**LLM Protocol (`llm/v1`)**
```yaml
Methods:
- llm/chat: Conversational text generation
- llm/vision: Image analysis
- llm/generate: Direct text generation
- llm/embeddings: Vector embeddings
```

**Python Protocol (`python/v1`)**
```yaml
Methods:
- python/execute: Script execution
- python/validate: Syntax validation
- python/info: Provider information
```

**MCP Protocol (`mcp/v1`)**
```yaml
Methods:
- mcp/tool.*: Execute MCP tools
- mcp/tools/list: List available tools
- mcp/servers: List MCP servers
- mcp/ping: Health check
```

### 4. Provider Layer

Providers implement protocol methods and handle actual execution:

#### Base Provider (`providers/base.py`)
Abstract base class defining:
- **Interface contract**: Required methods all providers must implement
- **Lifecycle methods**: `initialize()`, `shutdown()`, `health_check()`
- **Request handling**: `handle_request(method, params)`

#### Provider Implementations

**OllamaProvider**
- Manages communication with Ollama LLM servers
- Handles streaming responses
- Implements retry logic for transient failures

**PythonProvider**
- Executes Python scripts in isolated subprocesses
- Manages script timeout and resource limits
- Handles script output capture and JSON parsing

**MCPHubProvider**
- Routes MCP tool calls to external servers
- Manages stdio/WebSocket/HTTP connections
- Handles tool discovery and registration

### 5. Resource Management Layer

#### ResourceManager (`hub/resource_manager.py`)
Coordinates multiple resource hubs:
- **Hub registration**: Manages different resource types
- **Allocation strategies**: Round-robin, least-loaded, best-fit
- **Cross-hub coordination**: Manages dependencies between resources

#### Resource Hubs (`hub/*.py`)

**Base ResourceHub**
Abstract base providing:
- **Instance lifecycle**: Start, stop, restart
- **Health monitoring**: Periodic health checks
- **Metrics collection**: Usage statistics
- **Auto-scaling**: Dynamic instance management

**OllamaHub**
- Auto-discovers Ollama instances on configurable ports
- Model-aware routing
- Connection pooling for performance

**DockerHub** (Optional)
- Container lifecycle management
- Resource limit enforcement
- Volume mounting for data access

**MCPHub**
- Manages external MCP server processes
- Tool discovery and registration
- Automatic restart on failure

### 6. Persistence Layer

#### Unified Persistence Adapter (`persistence/unified_persistence.py`)
Single interface with multiple backends:

```python
class UnifiedPersistenceAdapter:
    async def save_workflow(workflow: Workflow) -> bool
    async def save_task(task: Task) -> bool
    async def get_workflow(id: str) -> Optional[Workflow]
    async def get_task(id: str) -> Optional[Task]
    async def update_task_status(id: str, status: TaskStatus) -> bool
```

#### Backend Implementations

**Redis Adapter**
- High-performance distributed storage
- Pub/sub for event notifications
- TTL-based expiration

**SQL Adapter**
- SQLite for local storage
- PostgreSQL for production
- Transaction support

**Memory Adapter**
- In-process storage for testing
- Fast but non-persistent
- Automatic cleanup

### 7. Data Models

#### Core Models (`core/models.py`)
Pydantic models for type safety and validation:

```python
@dataclass
class Task:
    id: str
    name: str
    protocol: str
    method: str
    parameters: Dict[str, Any]
    dependencies: List[str]
    status: TaskStatus
    result: Optional[TaskResult]
    retry_config: Optional[RetryConfig]
    
@dataclass
class Workflow:
    id: str
    name: str
    tasks: List[Task]
    status: WorkflowStatus
    created_at: datetime
    completed_at: Optional[datetime]
```

## Data Flow

### Workflow Execution Flow

```
1. User submits workflow (YAML/Dict)
   ↓
2. WorkflowLoader validates and parses
   ↓
3. ExecutionEngine creates workflow instance
   ↓
4. Tasks added to TaskQueue with dependencies
   ↓
5. DependencyResolver determines execution order
   ↓
6. For each ready task:
   a. ParameterSubstitution resolves templates
   b. ProtocolRegistry routes to provider
   c. Provider executes task
   d. Result stored in persistence
   e. Dependencies updated
   ↓
7. Workflow marked complete when all tasks finish
```

### Task Execution Flow

```
1. Task dequeued from TaskQueue
   ↓
2. Protocol and method extracted
   ↓
3. Registry finds appropriate provider
   ↓
4. Provider validates parameters
   ↓
5. Provider executes:
   - OllamaProvider → HTTP request to Ollama
   - PythonProvider → Subprocess execution
   - MCPHubProvider → Route to MCP server
   ↓
6. Result wrapped in TaskResult
   ↓
7. Persistence updated with result
   ↓
8. Dependent tasks notified
```

## Design Patterns

### 1. **Registry Pattern**
Central registries manage protocols, providers, and resources, enabling dynamic discovery and loose coupling.

### 2. **Strategy Pattern**
Resource allocation strategies (round-robin, least-loaded) can be swapped without changing client code.

### 3. **Adapter Pattern**
Unified persistence adapter provides consistent interface across different storage backends.

### 4. **Observer Pattern**
Event-driven execution engine observes task state changes and triggers dependent task execution.

### 5. **Factory Pattern**
PersistenceFactory creates appropriate adapter based on configuration.

### 6. **Template Method Pattern**
Base provider class defines execution template, concrete providers implement specific steps.

### 7. **Command Pattern**
Tasks encapsulate execution requests as objects, allowing queuing and retry.

## Concurrency Model

### Async/Await Throughout
- All I/O operations are async
- Non-blocking execution allows high concurrency
- asyncio event loop manages coroutines

### Task Parallelism
- Independent tasks execute concurrently
- Configurable concurrency limits prevent resource exhaustion
- Dependency resolution ensures correct ordering

### Connection Pooling
- HTTP connections pooled for Ollama
- Database connections pooled for SQL
- Process pools for Python execution

## Error Handling Strategy

### Retry Logic
```python
retry_config = RetryConfig(
    max_attempts=3,
    initial_delay=1.0,
    exponential_backoff=True,
    max_delay=30.0
)
```

### Graceful Degradation
- Persistence fallback: Redis → SQL → Memory
- Provider fallback: Primary → Secondary instances
- Partial batch completion: Continue on individual failures

### Error Propagation
- Provider errors wrapped in ProviderError
- Validation errors caught early with ValidationError
- Task failures stored but don't stop workflow

## Security Considerations

### Python Execution Isolation
- Scripts run in separate processes
- Optional Docker containerization
- Resource limits enforced
- No direct filesystem access by default

### MCP Server Sandboxing
- External processes with limited permissions
- Environment variable filtering
- Command validation before execution


## Performance Optimizations

### Caching
- Python bytecode caching
- LLM response caching (optional)
- Tool discovery caching

### Connection Reuse
- HTTP keep-alive for Ollama
- Persistent WebSocket connections for MCP
- Database connection pooling

### Batch Processing
- Parallel file processing
- Chunked uploads/downloads
- Streaming for large responses

## Monitoring and Observability

### Metrics Collection
```python
ResourceMetrics:
- CPU usage
- Memory consumption
- Request latency
- Success/failure rates
- Queue depth
```

### Health Checks
- Provider health endpoints
- Resource instance monitoring
- Persistence backend checks

### Logging
- Structured logging with levels
- Correlation IDs for request tracking
- Error aggregation and reporting

## Extension Points

### Custom Protocols
1. Define protocol specification
2. Implement provider class
3. Register with protocol registry
4. Use in workflows

### Custom Persistence Backends
1. Implement UnifiedPersistenceAdapter interface
2. Add to PersistenceFactory
3. Configure in settings

### Custom Resource Hubs
1. Extend ResourceHub base class
2. Implement required methods
3. Register with ResourceManager

## Configuration Architecture

### Hierarchical Configuration
1. **Default values** in code
2. **Configuration file** (`~/.gleitzeit/config.yaml`)
3. **Environment variables** (GLEITZEIT_*)
4. **Runtime parameters** (method arguments)

### Configuration Scopes
- **Global**: Affects entire system
- **Provider-specific**: Provider behavior
- **Task-specific**: Individual task execution

## Deployment Architecture

### Development Mode
- Native mode with in-process execution
- Memory persistence
- Local Ollama instance

### Production Mode
- API server deployment
- Redis persistence
- Multiple Ollama instances
- Docker-based Python execution
- Load balancer for API servers

### Scaling Considerations
- Horizontal scaling of API servers
- Distributed task queue with Redis
- Multiple resource instances per hub
- Database connection pooling

## Future Architecture Considerations

### Planned Enhancements
1. **Distributed Execution**: Multi-node task execution
2. **Workflow Versioning**: Track workflow changes
3. **Event Streaming**: Real-time progress updates
4. **Plugin System**: Dynamic provider loading
5. **Workflow Templates**: Reusable workflow patterns
6. **API Security**: Authentication tokens, CORS configuration, rate limiting

### Extensibility Points
- Protocol versioning support
- Provider plugin architecture
- Custom task schedulers
- Workflow hooks and callbacks
- External metric collectors

## Summary

Gleitzeit's architecture prioritizes:
- **Modularity**: Clear separation between components
- **Extensibility**: Easy to add new protocols and providers
- **Reliability**: Built-in retry and fallback mechanisms
- **Performance**: Async execution and connection pooling
- **Maintainability**: Clean interfaces and type safety

The system's layered architecture ensures that changes in one layer don't affect others, making it easy to evolve and maintain over time.