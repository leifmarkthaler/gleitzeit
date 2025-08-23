# Python API Reference

## GleitzeitClient

The main client for interacting with Gleitzeit from Python.

### Initialization

```python
from gleitzeit import GleitzeitClient

# Auto mode (default)
client = GleitzeitClient()

# Specific mode
client = GleitzeitClient(mode="api")  # or "native" or "auto"

# With configuration
client = GleitzeitClient(
    mode="api",
    api_host="localhost",
    api_port=8000,
    auto_start_server=True,
    keep_server_running=True
)
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `mode` | str | "auto" | Client mode: "auto", "api", or "native" |
| `api_host` | str | "localhost" | API server hostname |
| `api_port` | int | 8000 | API server port |
| `auto_start_server` | bool | True | Auto-start API server if not running |
| `keep_server_running` | bool | True | Keep server running after client closes |
| `native_config` | dict | None | Configuration for native mode |

### Context Manager

Always use as a context manager for proper resource cleanup:

```python
async with GleitzeitClient() as client:
    # Use client
    pass
# Automatic cleanup
```

## Core Methods

### run_workflow

Execute a workflow from file or dictionary.

```python
async def run_workflow(
    workflow: Union[str, Dict[str, Any]],
    inputs: Optional[Dict[str, Any]] = None,
    watch: bool = False
) -> Dict[str, Any]
```

**Parameters:**
- `workflow`: Path to YAML file or workflow dictionary
- `inputs`: Input parameters for the workflow
- `watch`: Watch for file changes and re-run

**Returns:** Dictionary with task results

**Example:**

```python
# From file
result = await client.run_workflow("pipeline.yaml")

# From dictionary
workflow = {
    "name": "Test",
    "tasks": [
        {
            "id": "task1",
            "method": "llm/chat",
            "parameters": {
                "model": "llama3.2",
                "messages": [{"role": "user", "content": "Hello"}]
            }
        }
    ]
}
result = await client.run_workflow(workflow)

# With inputs
result = await client.run_workflow(
    "template.yaml",
    inputs={"topic": "AI", "length": 500}
)
```

### chat

Chat with an LLM model via Ollama.

```python
async def chat(
    prompt: str,
    model: str = "llama3.2",
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    system: Optional[str] = None,
    **kwargs
) -> str
```

**Parameters:**
- `prompt`: User message
- `model`: Ollama model name
- `temperature`: Response randomness (0-1)
- `max_tokens`: Maximum response length
- `system`: System prompt
- `**kwargs`: Additional model parameters

**Returns:** Model response as string

**Example:**

```python
# Simple chat
response = await client.chat("What is Python?")

# With configuration
response = await client.chat(
    "Write a poem",
    model="mistral",
    temperature=0.9,
    system="You are a creative poet"
)
```

### chat_messages

Chat with message history.

```python
async def chat_messages(
    messages: List[Dict[str, str]],
    model: str = "llama3.2",
    **kwargs
) -> str
```

**Parameters:**
- `messages`: List of message dictionaries with "role" and "content"
- `model`: Ollama model name
- `**kwargs`: Additional parameters

**Example:**

```python
messages = [
    {"role": "system", "content": "You are helpful"},
    {"role": "user", "content": "What is AI?"},
    {"role": "assistant", "content": "AI is..."},
    {"role": "user", "content": "Tell me more"}
]

response = await client.chat_messages(messages)
```

### batch_process

Process multiple files in batch.

```python
async def batch_process(
    directory: str,
    pattern: str = "*",
    prompt: str = None,
    model: str = "llama3.2",
    max_concurrent: int = 5,
    output_dir: Optional[str] = None,
    template: Optional[Dict] = None,
    **kwargs
) -> Dict[str, str]
```

**Parameters:**
- `directory`: Directory to process
- `pattern`: File pattern (glob syntax)
- `prompt`: Prompt template
- `model`: Ollama model
- `max_concurrent`: Parallel processing limit
- `output_dir`: Save results to directory
- `template`: Custom task template

**Returns:** Dictionary mapping filenames to results

**Example:**

```python
# Process text files
results = await client.batch_process(
    directory="documents",
    pattern="*.txt",
    prompt="Summarize this document",
    model="llama3.2"
)

# Recursive with output
results = await client.batch_process(
    directory="data",
    pattern="**/*.json",
    prompt="Extract key metrics",
    output_dir="summaries",
    max_concurrent=10
)
```

### execute_task

Execute a single task.

```python
async def execute_task(
    task: Union[Task, Dict[str, Any]]
) -> TaskResult
```

**Parameters:**
- `task`: Task object or dictionary

**Returns:** TaskResult object

**Example:**

```python
task = {
    "id": "analyze",
    "method": "llm/chat",
    "parameters": {
        "model": "llama3.2",
        "messages": [{"role": "user", "content": "Analyze this"}]
    }
}

result = await client.execute_task(task)
print(result.response)
```

### execute_python_script

Execute a Python script file.

```python
async def execute_python_script(
    script: str,
    args: Optional[Dict[str, Any]] = None,
    timeout: int = 30
) -> Any
```

**Parameters:**
- `script`: Path to Python script
- `args`: Arguments passed as JSON to script
- `timeout`: Execution timeout in seconds

**Returns:** Script output (parsed from JSON)

**Example:**

```python
result = await client.execute_python_script(
    "process_data.py",
    args={"input": "data.csv", "output": "results.json"},
    timeout=60
)
```

## Utility Methods

### list_models

List available Ollama models.

```python
async def list_models() -> List[str]
```

**Example:**

```python
models = await client.list_models()
print(models)  # ["llama3.2", "mistral", "codellama", ...]
```

### get_status

Get system status.

```python
async def get_status() -> Dict[str, Any]
```

**Example:**

```python
status = await client.get_status()
print(status["ollama"]["available"])  # True/False
```

## Advanced Usage

### Parallel Execution

```python
import asyncio

async def parallel_processing():
    async with GleitzeitClient() as client:
        tasks = [
            client.chat("Question 1", model="llama3.2"),
            client.chat("Question 2", model="llama3.2"),
            client.chat("Question 3", model="llama3.2")
        ]
        results = await asyncio.gather(*tasks)
        return results
```

### Error Handling

```python
from gleitzeit.core.errors import (
    GleitzeitError,
    TaskExecutionError,
    ValidationError,
    TimeoutError
)

async def safe_execution():
    async with GleitzeitClient() as client:
        try:
            result = await client.run_workflow("workflow.yaml")
        except ValidationError as e:
            print(f"Invalid workflow: {e}")
        except TaskExecutionError as e:
            print(f"Task failed: {e}")
        except TimeoutError as e:
            print(f"Operation timed out: {e}")
        except GleitzeitError as e:
            print(f"General error: {e}")
```

### Custom Configuration

```python
# Native mode with resource management
client = GleitzeitClient(
    mode="native",
    native_config={
        "enable_resource_management": True,
        "max_parallel_tasks": 10,
        "default_timeout": 60
    }
)

# API mode with custom endpoint
client = GleitzeitClient(
    mode="api",
    api_host="gleitzeit.example.com",
    api_port=443,
    auto_start_server=False  # Don't try to start remote server
)
```

## Data Management Methods

### list_workflows

List all workflows with optional filtering.

```python
async def list_workflows(
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> Dict[str, Any]
```

**Parameters:**
- `status`: Filter by status (e.g., "completed", "running", "failed")
- `limit`: Maximum number of results
- `offset`: Pagination offset

**Returns:** Dictionary with workflow list and metadata

**Example:**

```python
# List all workflows
workflows = await client.list_workflows()
print(f"Total workflows: {workflows['total']}")

# List only completed workflows
completed = await client.list_workflows(status="completed")

# Paginated results
page2 = await client.list_workflows(limit=20, offset=20)
```

### list_tasks

List all tasks with optional filtering.

```python
async def list_tasks(
    workflow_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> Dict[str, Any]
```

**Parameters:**
- `workflow_id`: Filter by workflow ID
- `status`: Filter by status
- `limit`: Maximum number of results
- `offset`: Pagination offset

**Returns:** Dictionary with task list and metadata

**Example:**

```python
# List all tasks
tasks = await client.list_tasks()

# List tasks for specific workflow
workflow_tasks = await client.list_tasks(workflow_id="workflow-123")

# List failed tasks
failed_tasks = await client.list_tasks(status="failed")
```

### delete_task

Delete a task from persistence.

```python
async def delete_task(task_id: str) -> bool
```

**Parameters:**
- `task_id`: ID of the task to delete

**Returns:** True if deleted, False if not found

**Example:**

```python
# Delete a task
deleted = await client.delete_task("task-123")
if deleted:
    print("Task deleted successfully")
else:
    print("Task not found")
```

### delete_workflow

Delete a workflow and all its associated tasks.

```python
async def delete_workflow(workflow_id: str) -> bool
```

**Parameters:**
- `workflow_id`: ID of the workflow to delete

**Returns:** True if deleted, False if not found

**Note:** This will cascade delete:
- All tasks belonging to the workflow
- All task results
- Queue state references
- Workflow execution records

**Example:**

```python
# Delete a workflow and all its tasks
deleted = await client.delete_workflow("workflow-123")
if deleted:
    print("Workflow and all tasks deleted")
else:
    print("Workflow not found")
```

### get_task

Get a task by ID.

```python
async def get_task(task_id: str) -> Optional[Task]
```

**Parameters:**
- `task_id`: Task ID

**Returns:** Task object or None if not found

**Example:**

```python
task = await client.get_task("task-123")
if task:
    print(f"Task status: {task.status}")
    print(f"Task name: {task.name}")
```

### get_workflow

Get a workflow by ID.

```python
async def get_workflow(workflow_id: str) -> Optional[Workflow]
```

**Parameters:**
- `workflow_id`: Workflow ID

**Returns:** Workflow object or None if not found

**Example:**

```python
workflow = await client.get_workflow("workflow-123")
if workflow:
    print(f"Workflow name: {workflow.name}")
    print(f"Total tasks: {len(workflow.tasks)}")
```

### submit_task

Submit a task for execution.

```python
async def submit_task(
    name: str,
    protocol: str,
    method: str,
    params: Dict[str, Any],
    priority: Priority = Priority.NORMAL,
    queue: str = "default",
    resource_requirements: Optional[Dict[str, Any]] = None
) -> Task
```

**Parameters:**
- `name`: Task name
- `protocol`: Protocol identifier (e.g., "python/v1", "llm/v1")
- `method`: Method to execute
- `params`: Method parameters
- `priority`: Task priority (LOW, NORMAL, HIGH, CRITICAL)
- `queue`: Queue name
- `resource_requirements`: Optional resource requirements

**Returns:** Task object with generated ID

**Example:**

```python
# Submit a Python task
task = await client.submit_task(
    name="data_processing",
    protocol="python/v1",
    method="python/execute",
    params={
        "code": "import pandas as pd; print('Processing data')"
    },
    priority=Priority.HIGH
)
print(f"Task submitted: {task.id}")

# Submit an LLM task
task = await client.submit_task(
    name="text_analysis",
    protocol="llm/v1",
    method="llm/chat",
    params={
        "model": "llama3.2",
        "messages": [{"role": "user", "content": "Analyze this text"}]
    }
)
```

### Streaming Responses

```python
# Note: Streaming support varies by mode
async def stream_chat():
    async with GleitzeitClient() as client:
        # Check if streaming is supported
        if hasattr(client, 'chat_stream'):
            async for chunk in client.chat_stream("Tell a story"):
                print(chunk, end="", flush=True)
```

## Type Hints

All methods include full type hints for better IDE support:

```python
from typing import Dict, List, Optional, Any, Union
from gleitzeit import GleitzeitClient
from gleitzeit.core.models import Task, TaskResult, WorkflowExecution

async def typed_example() -> Dict[str, TaskResult]:
    client: GleitzeitClient
    async with GleitzeitClient() as client:
        result: Dict[str, Any] = await client.run_workflow("workflow.yaml")
        response: str = await client.chat("Hello", model="llama3.2")
        return result
```

## Resource Management

### With Resource Management Enabled

```python
client = GleitzeitClient(
    mode="native",
    native_config={"enable_resource_management": True}
)

# Resources are automatically managed
# Multiple Ollama instances are load-balanced
# Docker containers are managed for Python execution
```

## Best Practices

1. **Always use context managers** - Ensures cleanup
2. **Handle errors appropriately** - Use try/except blocks
3. **Set timeouts** - Prevent hanging operations
4. **Use type hints** - Better IDE support and error catching
5. **Batch similar operations** - Use batch_process for multiple files
6. **Configure retries** - Handle transient failures
7. **Log operations** - For debugging and monitoring

## Complete Example

```python
import asyncio
import logging
from gleitzeit import GleitzeitClient

logging.basicConfig(level=logging.INFO)

async def document_pipeline():
    """Process documents through analysis pipeline"""
    
    async with GleitzeitClient() as client:
        # Check system status
        status = await client.get_status()
        if not status["ollama"]["available"]:
            raise RuntimeError("Ollama not available")
        
        # Batch process documents
        summaries = await client.batch_process(
            directory="documents",
            pattern="*.txt",
            prompt="Summarize in 3 sentences",
            model="llama3.2",
            max_concurrent=5
        )
        
        # Analyze summaries
        analysis = await client.chat(
            f"Identify common themes in: {list(summaries.values())}",
            model="llama3.2"
        )
        
        # Save results
        result = await client.execute_python_script(
            "save_results.py",
            args={
                "summaries": summaries,
                "analysis": analysis,
                "output": "report.json"
            }
        )
        
        return result

if __name__ == "__main__":
    result = asyncio.run(document_pipeline())
    print(f"Pipeline complete: {result}")
```