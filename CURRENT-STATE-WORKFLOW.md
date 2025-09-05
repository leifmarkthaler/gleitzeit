# Current State: Workflow and Task System (2025-08-31)

**Last Updated:** 2025-08-31 (Added Ollama/Hub documentation)

## Overview

Gleitzeit is a protocol-based workflow orchestration system that is now fully functional with event-driven task execution and dependency resolution. The system has been debugged and tested to work end-to-end.

## Architecture Components

### Core Models

#### Task
```python
class Task(BaseModel):
    # Identity
    id: str
    workflow_id: Optional[str]
    name: str
    description: Optional[str]
    
    # Protocol specification
    protocol: str  # e.g., "python/v1", "llm/v1", "shell/v1"
    method: str    # e.g., "python/execute", "llm/generate"
    params: Dict[str, Any]  # NOT "parameters" - this is important!
    
    # Dependencies
    dependencies: Optional[List[str]] = []  # List of task IDs that must complete first
    
    # Status tracking
    status: TaskStatus = TaskStatus.PENDING
    priority: Priority = Priority.NORMAL
    retry_config: Optional[RetryConfig]
```

**Important:** Tasks use `params` field, not `parameters`!

#### Workflow
```python
class Workflow(BaseModel):
    id: str
    name: str
    description: Optional[str]
    tasks: List[Task]
    status: WorkflowStatus = WorkflowStatus.PENDING
    metadata: Dict[str, Any]
```

### Task Status Flow
```
PENDING → QUEUED → VALIDATED → ROUTED → EXECUTING → COMPLETED
                                      ↓
                                    FAILED → RETRY_PENDING
```

### Workflow Status Flow  
```
PENDING → RUNNING → COMPLETED
              ↓
            FAILED
```

## Execution Flow (Fully Event-Driven)

### 1. Workflow Submission

```python
# Client usage
from gleitzeit import Client, ClientMode, Task, Workflow

client = Client(mode=ClientMode.NATIVE)
await client.initialize()

workflow = Workflow(
    id="my_workflow",
    name="Test Workflow",
    tasks=[
        Task(
            id="task1",
            name="First Task",
            protocol="python/v1",
            method="python/execute",
            params={"file": "script1.py"}  # Must use 'params', not 'parameters'
        ),
        Task(
            id="task2", 
            name="Dependent Task",
            protocol="python/v1",
            method="python/execute",
            dependencies=["task1"],  # Will wait for task1 to complete
            params={"file": "script2.py"}
        )
    ]
)

result = await client.submit_workflow(workflow)
```

### 2. Internal Processing Flow

```
1. Client.submit_workflow()
   └── NativeAdapter.submit_workflow()
       └── ExecutionEngineV2.submit_workflow()
           └── TaskOrchestrator.submit_workflow()
               ├── Validate workflow (UnifiedDependencyManager)
               ├── Save to persistence
               └── Emit WORKFLOW_SUBMITTED event

2. QueueManager handles WORKFLOW_SUBMITTED
   └── _on_workflow_submitted()
       ├── Get workflow from persistence
       ├── Find tasks with no dependencies
       └── For each independent task:
           ├── Call _enqueue_task_with_ready_event()
           ├── Update task status to QUEUED
           ├── Save task
           └── Emit TASK_READY event

3. TaskOrchestrator handles TASK_READY
   └── _handle_task_ready()
       ├── Check capacity (max_concurrent_tasks)
       ├── Get task from persistence
       └── _schedule_task()
           └── _execute_task_with_semaphore()
               └── TaskExecutor.execute_task()
                   ├── Update status to EXECUTING
                   ├── Resolve parameters (if dependencies exist)
                   ├── Route to provider via Registry
                   ├── Provider executes (e.g., PythonProvider)
                   ├── Create TaskResult
                   ├── Save result to persistence
                   └── Emit TASK_COMPLETED event

4. TaskOrchestrator handles TASK_COMPLETED
   └── _handle_task_completed()
       └── _check_workflow_progression()
           ├── Get completed task IDs
           ├── Check if all tasks complete → Emit WORKFLOW_COMPLETED
           └── Find newly ready tasks (dependencies satisfied)
               └── For each ready task:
                   ├── enqueue_task()
                   └── Emit TASK_READY event (critical!)
```

## Critical Implementation Details

### 1. Provider Registration (Currently Hardcoded)

The system currently has hardcoded provider registration in `NativeAdapter._init_default_providers()`:

```python
# Python provider registration
python_protocol = ProtocolSpec(
    protocol_id="python/v1",
    name="python",
    version="v1",
    methods={
        "python/execute": MethodSpec(
            name="python/execute",
            description="Execute a Python file",
            parameters={
                "file": ParameterSpec(type=ParameterType.STRING, required=True)
            }
        )
    }
)
registry.register_protocol(python_protocol)

python_provider = PythonProvider(
    provider_id="python_default",
    protocol_id="python/v1"
)
registry.register_provider(
    provider_id="python_default",
    protocol_id="python/v1", 
    provider_instance=python_provider,
    supported_methods=set(python_provider.get_supported_methods())
)
```

**Note:** A ProviderHub is needed for production to handle provider lifecycle management dynamically.

### 2. PythonProvider Parameters

**Important:** PythonProvider only accepts file paths, NOT inline code:
- ✅ `params={"file": "path/to/script.py"}`
- ✅ `params={"file_path": "path/to/script.py"}`  
- ❌ `params={"code": "print('hello')"}` - This was removed as a bug fix

### 3. Event Bus Architecture

The system uses a **StatelessEventBus** that:
- Stores handlers in Redis (or in-memory with Redis interface)
- Supports distributed event processing
- No polling loops - fully event-driven
- Critical events:
  - `WORKFLOW_SUBMITTED` - Triggers initial task queueing
  - `TASK_READY` - Triggers task execution
  - `TASK_COMPLETED` - Triggers dependency checking
  - `WORKFLOW_COMPLETED` - Final workflow completion

### 4. Dependency Resolution

Tasks with dependencies:
1. Start in PENDING status (not QUEUED)
2. Wait until all dependencies are COMPLETED
3. Get enqueued and TASK_READY emitted by `_check_workflow_progression()`
4. Execute in parallel if multiple tasks become ready simultaneously

Example dependency patterns that work:
```
Linear:       task1 → task2 → task3
Parallel:     task1 → task2
                  ↘→ task3
Complex:      task1 → task2 → task3 → task5
                  ↘→ task4 ↗
```

### 5. Critical Bug Fixes Applied

1. **TaskExecutor using wrong field**: Fixed `task.parameters` → `task.params`
2. **Missing TASK_READY events**: Added emission in `_check_workflow_progression()` 
3. **TaskResult field error**: Fixed `result.output` → `result.result`
4. **Event registration race**: Added `_ensure_handlers_registered()` wait
5. **QueueManager missing event bus**: Pass event bus during initialization

## Current Limitations

### 1. No ProviderHub
- Provider registration is hardcoded in NativeAdapter
- No dynamic provider loading
- No health monitoring
- No hot-reload capability

### 2. No Parameter Passing Between Tasks
- Tasks can have dependencies but can't use outputs from previous tasks
- ParameterResolver exists but needs implementation for `${task.output}` syntax

### 3. Limited Provider Support
Currently only these providers are registered by default:
- `python/v1` - Execute Python files
- `shell/v1` - Execute shell commands
- `llm/v1` - Not registered by default but OllamaHub and OllamaProvider exist

### 4. No Workflow Templates
- WorkflowTemplate model exists but not integrated
- No workflow reuse mechanism

## Hub System and Ollama Integration

### OllamaHub
The system includes a fully functional `OllamaHub` for managing Ollama LLM instances:

```python
from gleitzeit.hub.ollama_hub import OllamaHub
from gleitzeit.providers.ollama_provider import OllamaProvider

# Create and initialize hub
ollama_hub = OllamaHub(
    hub_id="ollama-hub",
    auto_discover=True,  # Auto-discovers running Ollama instances
    discovery_ports=[11434]  # Default Ollama port
)
await ollama_hub.initialize()

# Create provider with hub
ollama_provider = OllamaProvider(
    provider_id="ollama_with_hub",
    protocol_id="llm/v1",
    default_model="llama3.2",
    hub=ollama_hub  # REQUIRED - provider needs hub for resource allocation
)
```

**Important:** OllamaProvider REQUIRES a hub for resource allocation. Without a hub, it will fail with `RESOURCE_EXHAUSTED` errors.

### Registering Ollama Provider
Since Ollama is not registered by default, you need to manually register it:

```python
# 1. Register the protocol
llm_protocol = ProtocolSpec(
    protocol_id="llm/v1",
    name="llm",
    version="v1",
    methods={
        "llm/generate": MethodSpec(...),
        "llm/chat": MethodSpec(...)
    }
)
registry.register_protocol(llm_protocol)

# 2. Create hub and provider
ollama_hub = OllamaHub(...)
await ollama_hub.initialize()

ollama_provider = OllamaProvider(
    hub=ollama_hub  # Critical!
)
await ollama_provider.initialize()

# 3. Register provider
registry.register_provider(
    provider_id="ollama_with_hub",
    protocol_id="llm/v1",
    provider_instance=ollama_provider,
    supported_methods=set(ollama_provider.get_supported_methods())
)
```

### Ollama Workflow Example
```python
workflow = Workflow(
    id="llm_workflow",
    name="LLM Processing",
    tasks=[
        Task(
            id="generate",
            protocol="llm/v1",
            method="llm/generate",
            params={
                "prompt": "Write a haiku about coding",
                "model": "llama3.2"
            }
        ),
        Task(
            id="chat",
            protocol="llm/v1", 
            method="llm/chat",
            dependencies=["generate"],
            params={
                "messages": [
                    {"role": "system", "content": "You are helpful"},
                    {"role": "user", "content": "What is 2+2?"}
                ],
                "model": "llama3.2"
            }
        )
    ]
)
```

### Hub Architecture
The hub system provides resource management:
- **Auto-discovery** of running instances (e.g., Ollama on different ports)
- **Load balancing** across multiple instances
- **Health monitoring** of resources
- **Resource allocation** for providers
- **Model-aware routing** (for Ollama, routes to instances with required models)

Other available hubs:
- `DockerHub` - Manages Docker containers for isolated execution
- `MCPHub` - Manages Model Context Protocol servers

## Testing Workflows

### Simple Test
```python
# Create test file
Path("test.py").write_text("print('Hello from task')")

# Create and submit workflow
workflow = Workflow(
    id="test",
    name="Test",
    tasks=[
        Task(
            id="t1",
            protocol="python/v1",
            method="python/execute",
            params={"file": "test.py"}
        )
    ]
)
await client.submit_workflow(workflow)
```

### Dependency Test
```python
workflow = Workflow(
    id="dep_test",
    name="Dependency Test",
    tasks=[
        Task(id="t1", protocol="python/v1", method="python/execute",
             params={"file": "task1.py"}),
        Task(id="t2", protocol="python/v1", method="python/execute",
             dependencies=["t1"], params={"file": "task2.py"}),
        Task(id="t3", protocol="python/v1", method="python/execute",
             dependencies=["t1", "t2"], params={"file": "task3.py"})
    ]
)
```

## API and Middleware

### Authentication
- Mode: `basic` (permissive for development)
- Location: `api/middleware.py` - `AuthenticationMiddleware`
- Public endpoints bypass auth
- Other endpoints get `basic_user` if no auth headers

### Error Handling
- Global `ErrorHandlingMiddleware` catches all exceptions
- Maps exceptions to HTTP status codes
- Full stack traces logged

### Logging
- `LoggingMiddleware` logs all requests/responses
- Adds `X-Process-Time` header
- Each module has its own logger

### Rate Limiting
- 60 requests per minute per client
- Configurable in middleware

## Key Files and Locations

### Core Components
- `/src/gleitzeit/core/models.py` - Task, Workflow models
- `/src/gleitzeit/core/task_orchestrator.py` - Main orchestration logic
- `/src/gleitzeit/core/task_executor.py` - Task execution
- `/src/gleitzeit/core/execution_engine_v2.py` - Engine coordinator
- `/src/gleitzeit/core/dependency_manager.py` - Dependency resolution

### Client
- `/src/gleitzeit/client/client.py` - Main client class
- `/src/gleitzeit/client/adapters/native.py` - Native mode adapter (with provider registration)

### Providers
- `/src/gleitzeit/providers/python_provider.py` - Python execution
- `/src/gleitzeit/providers/shell_provider.py` - Shell commands

### Events
- `/src/gleitzeit/events/stateless_bus.py` - Event bus implementation
- `/src/gleitzeit/core/events.py` - Event types and definitions

### Queue Management
- `/src/gleitzeit/task_queue/task_queue.py` - Queue and QueueManager

### Persistence
- `/src/gleitzeit/persistence/unified_persistence.py` - Unified persistence adapter

## Next Steps for Development

### High Priority
1. **Implement ProviderHub** - Centralized provider lifecycle management
2. **Parameter passing** - Enable `${task1.output}` in task params
3. **Add more providers** - LLM, MCP, Docker providers

### Medium Priority  
1. **Workflow templates** - Reusable workflow definitions
2. **Better monitoring** - Task metrics, execution times
3. **Workflow visualization** - DAG visualization of dependencies

### Low Priority
1. **Conditional execution** - if/else logic in workflows
2. **Loop support** - For-each over collections
3. **Sub-workflows** - Workflows calling other workflows

## Summary

The Gleitzeit workflow system is now fully functional with:
- ✅ Event-driven execution (no polling)
- ✅ Dependency resolution working correctly
- ✅ Parallel task execution
- ✅ Proper error handling and logging
- ✅ Persistence and recovery
- ✅ LLM support via OllamaHub/OllamaProvider (tested and working)
- ✅ Hub-based resource management for scalability

The system executes workflows reliably, respecting all dependency constraints and running tasks in parallel when possible. Key limitations:
1. **Provider registration is hardcoded** - needs a ProviderHub for production
2. **No parameter passing between tasks** - can't use `${task1.output}` syntax
3. **Manual hub setup required** - Ollama and other providers need manual registration

Tested capabilities:
- Python script execution workflows ✅
- Dependency chain execution (complex DAGs) ✅
- Ollama LLM workflows with hub ✅
- Parallel task execution ✅