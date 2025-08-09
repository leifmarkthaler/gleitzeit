# Gleitzeit Simplified Architecture

## Core Focus: LLM Workflow Orchestration

Gleitzeit's primary purpose is orchestrating LLM tasks across multiple endpoints and machines. Python functions are secondary and should be handled via Socket.IO for clean separation.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                   Gleitzeit Orchestrator                 │
│                                                          │
│  • Workflow Management                                   │
│  • Task Scheduling & Dependencies                        │
│  • Redis State Management                                │
│  • Socket.IO Communication Hub                           │
└────────────┬────────────────────┬───────────────────────┘
             │                    │
             │ Socket.IO          │ Direct
             │                    │
    ┌────────▼────────┐   ┌──────▼──────────┐
    │ Python Tasks    │   │ LLM Endpoints   │
    │                 │   │                 │
    │ @gleitzeit_task │   │ • Ollama        │
    │ decorators      │   │ • OpenAI        │
    │                 │   │ • Claude        │
    └─────────────────┘   │ • Local Models  │
                          └─────────────────┘
```

## Key Components

### 1. LLM Task Orchestration (Primary)
- **Multi-endpoint management**: Round-robin, least-loaded, priority-based routing
- **Model management**: Automatic model loading/unloading
- **Resource optimization**: GPU/CPU allocation across machines
- **Failure handling**: Automatic failover between endpoints

### 2. Python Tasks via Socket.IO (Secondary)
- **Simple decorator**: `@gleitzeit_task` makes any function a task
- **Clean separation**: Python tasks run in separate services
- **No backwards compatibility**: Fresh, clean implementation

## Usage Patterns

### Pattern 1: Pure LLM Workflows
```python
workflow = cluster.create_workflow("Analysis")

# Chain multiple LLM tasks
extract = workflow.add_text_task(
    "Extract Data",
    prompt="Extract key points from: {input}",
    model="llama3"
)

analyze = workflow.add_text_task(
    "Analyze",
    prompt="Analyze: {{Extract Data.result}}",
    model="mixtral",
    dependencies=["Extract Data"]
)
```

### Pattern 2: Mixed LLM + Python Workflows
```python
# Define Python task with decorator
@gleitzeit_task()
def process_data(raw_data):
    return transform(raw_data)

# Mix Python and LLM tasks
workflow = cluster.create_workflow("Pipeline")

python_task = workflow.add_external_task(
    "Process",
    service_name="Python Tasks",
    external_parameters={"function_name": "process_data"}
)

llm_task = workflow.add_text_task(
    "Generate",
    prompt="Based on {{Process.result}}, generate...",
    dependencies=["Process"]
)
```

## Benefits of Simplified Architecture

1. **Clear Focus**: LLM orchestration is the primary concern
2. **Clean Separation**: Python tasks via Socket.IO, LLM tasks direct
3. **Scalability**: Each component scales independently
4. **Simplicity**: No complex backwards compatibility
5. **Flexibility**: Easy to add new task types via Socket.IO

## Migration from Native Python Tasks

### Old Way (Native Execution)
```python
# Python functions executed inside cluster
workflow.add_python_task(
    "Process",
    function_name="my_function",
    args=[data]
)
```

### New Way (Socket.IO Service)
```python
# Python functions as external services
@gleitzeit_task()
def my_function(data):
    return process(data)

# Start service (once)
await start_task_service()

# Use in workflows
workflow.add_external_task(
    "Process",
    service_name="Python Tasks",
    external_parameters={"function_name": "my_function"}
)
```

## LLM Endpoint Management (Unchanged)

The core LLM orchestration remains the powerful feature:

```python
# Configure multiple Ollama endpoints
cluster = GleitzeitCluster(
    ollama_endpoints=[
        EndpointConfig("http://gpu-server-1:11434", priority=1, gpu=True),
        EndpointConfig("http://gpu-server-2:11434", priority=2, gpu=True),
        EndpointConfig("http://cpu-server:11434", priority=3, gpu=False),
    ],
    ollama_strategy=LoadBalancingStrategy.LEAST_LOADED
)

# Tasks automatically distributed across endpoints
workflow.add_text_task(
    "Heavy Task",
    prompt="Complex prompt...",
    model="llama3:70b",  # Automatically routed to GPU server
)
```

## Summary

Gleitzeit is now clearly focused on its core strength: **orchestrating LLM workflows across distributed endpoints**. Python tasks are handled cleanly via Socket.IO with a simple decorator pattern, maintaining separation of concerns and enabling independent scaling.