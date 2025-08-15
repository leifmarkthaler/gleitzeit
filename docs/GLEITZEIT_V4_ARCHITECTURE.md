# Gleitzeit V4 System Architecture Guide

## Overview

Gleitzeit V4 is a distributed task orchestration system built on protocol-based architecture with JSON-RPC 2.0 compliance and Socket.IO communication. It represents a significant evolution from previous versions, moving from provider-type-based systems to universal protocol-based integration.

**Key Design Principles:**
- **Protocol-based Architecture**: Tasks use protocols (e.g., "llm/v1", "echo/v1") instead of provider types
- **JSON-RPC 2.0 Compliance**: Full compliance for universal service integration
- **Distributed by Design**: Socket.IO-based communication between components
- **Advanced Dependency Resolution**: Topological sorting, circular dependency detection
- **Priority-based Task Queuing**: Urgent → High → Normal → Low ordering
- **Native MCP Support**: Model Context Protocol as extension of JSON-RPC 2.0

## 🔧 Recent Architecture Enhancements (v4.1)

### Event-Driven Task Processing Improvements
- **Enhanced `_process_ready_tasks()` Method**: Fixed event-driven mode to properly dequeue and execute ready tasks when capacity allows
- **Execution Mode Optimization**: CLI now uses appropriate execution modes (SINGLE_SHOT for direct execution, EVENT_DRIVEN for Socket.IO-based workflows)
- **Provider Management**: Added missing registry methods for provider health checking and listing

### CLI Architecture Refinements  
- **YAML Parameter Flexibility**: Support for both `params` and `parameters` fields in workflow definitions
- **Execution Engine Integration**: Improved CLI workflow submission with proper execution engine initialization
- **Response Persistence**: Enhanced JSON response file generation with complete task and workflow results

### Persistence Layer Verification
- **Redis Integration Confirmed**: Full verification of task and result persistence including LLM responses
- **Task Result Storage**: Complete execution metadata, timing, and provider responses stored in Redis
- **Workflow State Management**: Enhanced tracking of workflow execution states and task dependencies

## Architecture Components

### 1. Core Models (`gleitzeit_v4/core/models.py`)

**Task Model**
```python
class Task(BaseModel):
    id: str
    name: str
    protocol: str          # e.g., "llm/v1", "echo/v1"
    method: str            # e.g., "generate", "ping"
    params: Dict[str, Any]
    dependencies: List[str] = []
    priority: Priority = Priority.NORMAL
    retry_config: Optional[RetryConfig] = None
    status: TaskStatus = TaskStatus.CREATED
```

**Workflow Model**
```python
class Workflow(BaseModel):
    id: str
    name: str
    tasks: List[Task]
    priority: Priority = Priority.NORMAL
    status: WorkflowStatus = WorkflowStatus.CREATED
```

**Protocol Specifications**
```python
class ProtocolSpec(BaseModel):
    name: str              # e.g., "llm"
    version: str           # e.g., "v1"
    description: str
    methods: Dict[str, MethodSpec]
```

### 2. Central Server (`gleitzeit_v4/server/central_server.py`)

**Core Responsibilities:**
- Protocol registration and management
- Task queue coordination
- Provider and engine client coordination
- Socket.IO event handling
- Method routing and execution

**Key Components:**
- `ProtocolRegistry`: Manages available protocols
- `QueueManager`: Handles task queuing with priority and dependencies
- `ExecutionEngine`: Routes tasks to appropriate providers
- `WorkflowManager`: Orchestrates multi-task workflows

**Socket.IO API:**
```python
# Provider registration
await sio.emit('register_provider', {
    'provider_id': 'my-provider',
    'protocol_id': 'llm/v1',
    'methods': ['generate', 'chat', 'embed']
})

# Task execution
response = await sio.call('execute_method', {
    'task_id': 'task-123',
    'method': 'generate',
    'params': {'prompt': 'Hello'}
}, sid=provider_sid)
```

### 3. Protocol Registry (`gleitzeit_v4/server/protocol_registry.py`)

**Protocol Management:**
- Register and validate protocol specifications
- Method discovery and routing
- Provider capability matching
- MCP protocol integration

**Usage:**
```python
# Register a protocol
llm_protocol = ProtocolSpec(
    name="llm", version="v1", description="LLM protocol",
    methods={
        "generate": MethodSpec(name="generate", description="Generate text"),
        "chat": MethodSpec(name="chat", description="Chat completion")
    }
)
registry.register_protocol(llm_protocol)

# Find providers for protocol
providers = registry.get_providers_for_protocol("llm/v1")
```

### 4. Task Queue System (`gleitzeit_v4/queue/`)

**QueueManager (`queue_manager.py`):**
- Priority-based task queuing (Urgent → High → Normal → Low)
- Task lifecycle management
- Retry logic with configurable backoff strategies
- Task persistence and recovery

**DependencyResolver (`dependency_resolver.py`):**
- Circular dependency detection using DFS
- Topological sorting for execution order
- Parameter substitution analysis (`${task-id.result.field}`)
- Advanced workflow validation

**Key Features:**
```python
# Priority ordering
priorities = [Priority.URGENT, Priority.HIGH, Priority.NORMAL, Priority.LOW]

# Dependency resolution
execution_order = resolver.get_execution_order(workflow_id)
# Returns: [["A1", "A2"], ["B1", "B2"], ["C1"], ["D1"]]

# Parameter substitution
"Write about: ${generate-topic.result.content}"
# Resolves to actual generated content
```

### 5. Provider System

**ProtocolProvider Base Class (`gleitzeit_v4/providers/base.py`):**
```python
class ProtocolProvider:
    def __init__(self, provider_id: str, protocol_id: str, name: str, description: str):
        self.provider_id = provider_id
        self.protocol_id = protocol_id  # e.g., "llm/v1"
    
    async def execute_method(self, method: str, params: Dict[str, Any]) -> Any:
        # Implement method execution
        pass
```

**Example: Ollama Provider (`gleitzeit_v4/providers/ollama_provider.py`):**
```python
class OllamaProvider(ProtocolProvider):
    def __init__(self, provider_id: str, ollama_url: str = "http://localhost:11434"):
        super().__init__(
            provider_id=provider_id,
            protocol_id="llm/v1",
            name="Ollama LLM Provider",
            description="Ollama local LLM provider"
        )
    
    async def execute_method(self, method: str, params: Dict[str, Any]) -> Any:
        if method == "generate":
            return await self._generate(params)
        elif method == "chat":
            return await self._chat(params)
        # ... other methods
```

**Socket.IO Provider Client (`gleitzeit_v4/client/socketio_provider.py`):**
- Connects providers to central server
- Handles method execution requests
- Manages provider lifecycle and health

### 6. Engine Client System (`gleitzeit_v4/client/socketio_engine.py`)

**SocketIOEngineClient:**
- Connects to central server as workflow orchestrator
- Submits tasks and workflows
- Monitors task execution and results
- Handles dependency resolution

**Usage:**
```python
engine = SocketIOEngineClient(
    engine_id="workflow-engine",
    server_url="http://localhost:8000"
)

# Submit task
await engine.submit_task(task)

# Monitor results
result = engine.task_results.get(task_id)
```

## Workflow Execution Flow

### 1. Task Submission
```
Client → Engine Client → Central Server → Queue Manager
```

### 2. Dependency Resolution
```
Queue Manager → DependencyResolver → Topological Sort → Ready Tasks
```

### 3. Provider Assignment
```
Ready Tasks → Protocol Registry → Find Providers → Best Match Selection
```

### 4. Parameter Substitution
```
Task Parameters → Dependency Results → ${task-id.result.field} → Resolved Parameters
```

### 5. Task Execution
```
Central Server → Socket.IO → Provider Client → Method Execution → Result
```

### 6. Workflow Completion
```
Task Results → Dependency Update → Next Ready Tasks → Workflow Status
```

## Key Architectural Differences from V2/V3

### V2: Basic Sequential Execution
- Simple task chaining
- Provider-type-based routing
- Limited dependency support

### V3: Event-Driven Architecture
- Pure event-driven workflow orchestration
- Event bus communication
- Reactive task scheduling
- Parameter substitution: `${task_TASKID_result}`

### V4: Protocol-Based Distributed System
- **Protocol-based architecture**: Universal service integration
- **JSON-RPC 2.0 compliance**: Standard protocol support
- **Advanced dependency resolution**: Topological sorting, circular detection
- **Socket.IO distributed communication**: Real-time bidirectional communication
- **Enhanced parameter substitution**: `${task-id.result.field}` with nested access
- **Priority-based queuing**: Four-level priority system
- **Native MCP support**: Model Context Protocol integration

## Directory Structure

```
gleitzeit_v4/
├── core/
│   ├── models.py          # Core data models (Task, Workflow, Protocol)
│   ├── protocol.py        # Protocol specifications
│   └── __init__.py        # Public API exports
├── server/
│   ├── central_server.py  # Main server with Socket.IO
│   ├── protocol_registry.py  # Protocol management
│   └── __init__.py
├── queue/
│   ├── queue_manager.py   # Task queuing and lifecycle
│   ├── dependency_resolver.py  # Dependency analysis
│   └── __init__.py
├── providers/
│   ├── base.py           # ProtocolProvider base class
│   ├── ollama_provider.py # Ollama LLM provider
│   ├── echo_provider.py  # Test/debug provider
│   └── __init__.py
├── client/
│   ├── socketio_provider.py  # Provider client
│   ├── socketio_engine.py    # Engine client
│   └── __init__.py
└── cli/
    ├── main.py           # CLI interface
    └── __init__.py
```

## Workflow Definition Formats

### YAML Workflows
V4 supports both JSON and YAML workflow definitions. YAML provides a more human-readable format:

```yaml
# Example V4 YAML Workflow
name: "Research Workflow"
description: "Generate topic and write article"
version: "1.0"

tasks:
  - id: "generate-topic"
    name: "Generate Topic"
    protocol: "llm/v1"
    method: "generate" 
    priority: "high"
    params:
      prompt: "Generate an AI research topic"
      model: "llama3"
      temperature: 0.8
      max_tokens: 50

  - id: "write-article"
    name: "Write Article"
    protocol: "llm/v1"
    method: "generate"
    dependencies: ["generate-topic"]
    priority: "normal"
    params:
      prompt: "Write about: ${generate-topic.result.content}"
      model: "llama3"
      temperature: 0.7
      max_tokens: 300

metadata:
  author: "Gleitzeit V4"
  tags: ["research", "ai"]
  estimated_duration: "5 minutes"
```

### JSON Workflows
Traditional JSON format is also supported:

```json
{
  "name": "Research Workflow",
  "description": "Generate topic and write article",
  "tasks": [
    {
      "id": "generate-topic",
      "protocol": "llm/v1",
      "method": "generate",
      "priority": "high",
      "params": {
        "prompt": "Generate an AI research topic",
        "model": "llama3"
      }
    }
  ]
}
```

### CLI Usage
```bash
# Submit YAML workflow
gleitzeit workflow submit my_workflow.yaml --wait

# Submit JSON workflow  
gleitzeit workflow submit my_workflow.json --wait
```

## Configuration and Deployment

### Server Configuration
```python
server = CentralServer(
    host="localhost",
    port=8000,
    max_concurrent_tasks=100,
    enable_persistence=True,
    cors_allowed_origins="*"
)
```

### Provider Registration
```python
# Start provider
provider = SocketIOOllamaProvider(
    provider_id="ollama-provider-1",
    server_url="http://localhost:8000",
    ollama_url="http://localhost:11434"
)
await provider.start()

# Auto-registration happens on connection
```

### Engine Client Setup
```python
engine = SocketIOEngineClient(
    engine_id="main-engine",
    server_url="http://localhost:8000"
)
await engine.start()

# Submit workflows
await engine.submit_workflow(workflow)
```

## Testing and Validation

### Test Files Location
- `test_ollama_v4.py`: Ollama integration test
- `test_simple_vision.py`: Vision model testing
- `test_queue_retry_v4.py`: Queue and retry mechanism testing
- `test_workflow_dependencies.py`: Dependent task workflow testing
- `test_advanced_dependencies.py`: Advanced dependency resolution testing

### Key Test Scenarios
1. **Protocol Registration**: Verify protocols are properly registered
2. **Priority Queuing**: Test urgent → high → normal → low ordering
3. **Dependency Resolution**: Verify topological sorting works
4. **Parameter Substitution**: Test `${task-id.result.field}` resolution
5. **Circular Dependency Detection**: Ensure cycles are caught
6. **Retry Mechanisms**: Test configurable retry with backoff
7. **Provider Integration**: Verify Socket.IO communication
8. **Workflow Orchestration**: End-to-end workflow execution

## Error Handling and Resilience

### Task-Level Errors
- **Retry Configuration**: Max attempts, backoff strategies
- **Failure Isolation**: Individual task failures don't cascade
- **Status Tracking**: Detailed task lifecycle status

### Provider-Level Errors
- **Connection Monitoring**: Socket.IO disconnect handling
- **Health Checks**: Provider availability monitoring
- **Load Balancing**: Route to healthy providers

### System-Level Errors
- **Graceful Degradation**: Continue with available providers
- **Error Logging**: Comprehensive error tracking
- **Recovery Mechanisms**: Automatic retry and reassignment

## Performance Considerations

### Scalability
- **Horizontal Scaling**: Add more provider instances
- **Connection Pooling**: Efficient Socket.IO connection management
- **Load Distribution**: Smart provider selection

### Memory Management
- **Task Lifecycle**: Automatic cleanup of completed tasks
- **Result Storage**: Configurable result retention
- **Queue Optimization**: Priority-based memory usage

### Network Efficiency
- **Binary Protocol**: Efficient Socket.IO communication
- **Connection Reuse**: Persistent connections
- **Batch Operations**: Group similar operations

## Future Enhancements

### Planned Features
1. **Web Dashboard**: Real-time monitoring and management
2. **REST API**: HTTP interface alongside Socket.IO
3. **Provider Discovery**: Automatic provider registration
4. **Advanced Scheduling**: Time-based and resource-aware scheduling
5. **Metrics and Monitoring**: Detailed performance analytics
6. **Security Layer**: Authentication and authorization
7. **Configuration Management**: Dynamic configuration updates

### Integration Opportunities
1. **Kubernetes**: Container orchestration integration
2. **Message Queues**: RabbitMQ, Apache Kafka support
3. **Databases**: Persistent workflow state
4. **Cloud Services**: AWS, GCP, Azure provider support
5. **ML Platforms**: Direct integration with ML services

## Getting Started for New Contributors

### 1. Understanding the Codebase
1. Start with `gleitzeit_v4/core/models.py` for data structures
2. Review `gleitzeit_v4/server/central_server.py` for main logic
3. Examine test files for usage patterns

### 2. Running Tests
```bash
# Basic functionality
python test_queue_retry_v4.py

# Ollama integration
python test_ollama_v4.py

# Workflow dependencies
python test_workflow_dependencies.py
```

### 3. Adding New Providers
1. Inherit from `ProtocolProvider`
2. Implement `execute_method()`
3. Register with protocol registry
4. Test with Socket.IO client

### 4. Development Workflow
1. **Protocol Design**: Define protocol specification
2. **Provider Implementation**: Create provider class
3. **Testing**: Write comprehensive tests
4. **Documentation**: Update architecture guide
5. **Integration**: Test with full system

---

This architecture guide provides a comprehensive overview of Gleitzeit V4's design, implementation, and usage patterns. The system is production-ready with robust error handling, advanced dependency resolution, and scalable distributed architecture.