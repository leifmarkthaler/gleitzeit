# Modular Client Documentation

## Overview

The Gleitzeit client has been restructured from a monolithic 3,712-line class into a clean, modular architecture using mixins and adapters. This provides better maintainability, testability, and extensibility while maintaining full backward compatibility.

## Architecture

### Directory Structure

```
src/gleitzeit/client/
├── __init__.py              # Backward-compatible interface
├── base.py                  # ModularGleitzeitClient core
├── mixins/                  # Functional domain mixins
│   ├── __init__.py
│   ├── workflow.py          # Workflow operations
│   ├── task.py             # Task operations
│   ├── queue.py            # Queue management
│   ├── batch.py            # Batch processing
│   ├── auth.py             # Authentication
│   └── system.py           # System operations
└── adapters/               # Execution mode adapters
    ├── __init__.py
    ├── base.py            # Abstract adapter interface
    ├── api.py             # API mode implementation
    └── native.py          # Native mode implementation
```

## Core Components

### 1. ModularGleitzeitClient

The main client class that combines all mixins and manages adapters:

```python
from gleitzeit.client import GleitzeitClient

# Auto-detect mode (API if available, Native otherwise)
async with GleitzeitClient() as client:
    result = await client.submit_workflow(workflow)

# Explicit API mode
async with GleitzeitClient(mode="api", api_port=8000) as client:
    result = await client.submit_workflow(workflow)

# Native mode with configuration
async with GleitzeitClient(
    mode="native",
    persistence_type="redis",
    redis_url="redis://localhost:6379"
) as client:
    result = await client.submit_workflow(workflow)
```

### 2. Mixins

Each mixin handles a specific functional domain:

#### WorkflowMixin
Provides workflow-related operations:
- `submit_workflow(workflow)` - Submit a workflow for execution
- `run_workflow(workflow_file, watch=False)` - Run from YAML/JSON file
- `get_workflow(workflow_id)` - Get workflow by ID
- `list_workflows(status, limit, offset)` - List workflows
- `cancel_workflow(workflow_id)` - Cancel a workflow
- `pause_workflow(workflow_id)` - Pause a workflow
- `resume_workflow(workflow_id)` - Resume a workflow
- `delete_workflow(workflow_id)` - Delete a workflow
- `get_workflow_tasks(workflow_id)` - Get workflow's tasks
- `wait_for_workflow(workflow_id, timeout)` - Wait for completion
- `clone_workflow(workflow_id, new_name)` - Clone a workflow
- `get_workflow_statistics()` - Get execution statistics

#### TaskMixin
Provides task-related operations:
- `submit_task(task)` - Submit a task
- `execute_task(task)` - Execute and wait for result
- `get_task(task_id)` - Get task by ID
- `get_task_result(task_id)` - Get task result
- `get_task_status(task_id)` - Get task status
- `list_tasks(status, workflow_id, limit, offset)` - List tasks
- `cancel_task(task_id)` - Cancel a task
- `delete_task(task_id)` - Delete a task
- `wait_for_task(task_id, timeout)` - Wait for completion
- `retry_task(task_id)` - Retry a failed task
- `get_task_statistics()` - Get task statistics
- `batch_execute_tasks(tasks, max_concurrent)` - Execute multiple tasks
- `wait_for_tasks(task_ids, timeout)` - Wait for multiple tasks

#### QueueMixin
Provides queue management:
- `get_queues()` - Get all queues
- `get_queue_details(queue_name)` - Get queue details
- `pause_queue(queue_name)` - Pause a queue
- `resume_queue(queue_name)` - Resume a queue
- `clear_queue(queue_name)` - Clear queue items
- `configure_queue(queue_name, config)` - Configure queue
- `get_queue_statistics()` - Get queue statistics
- `rebalance_queues()` - Rebalance work across queues
- `get_queue_health()` - Get health status

#### BatchProcessingMixin
Provides batch and directory operations:
- `batch_process(directory, pattern, method, prompt, model, max_concurrent)` - Process files in batch
- `process_directory(directory, file_extensions, workflow_yaml, max_concurrent, recursive)` - Process directory with workflow template
- `batch_process_with_progress(...)` - Process with progress updates (async generator)
- `batch_analyze_files(files, analysis_prompt, model, output_format)` - Analyze multiple files
- `batch_transform_files(input_dir, output_dir, pattern, transformation, model)` - Transform files

#### AuthMixin
Provides authentication operations:
- `login(username, password)` - Login user
- `logout()` - Logout current user
- `get_current_user()` - Get authenticated user

#### SystemMixin
Provides system operations:
- `get_system_status()` - Get system status
- `health_check()` - Perform health check
- `get_providers()` - Get available providers
- `get_protocols()` - Get available protocols
- `chat(message, model, temperature, session_id)` - Chat with LLM

### 3. Adapters

Adapters implement the actual execution logic for different modes:

#### BaseAdapter
Abstract interface that all adapters must implement. Defines the contract for operations.

#### APIAdapter
Implements operations via HTTP API calls:
- Manages HTTP session with connection pooling
- Handles authentication tokens
- Converts between client models and API requests
- Implements retry logic for failed requests

#### NativeAdapter
Implements operations using direct engine access:
- Creates and manages ExecutionEngine
- Direct persistence backend access
- In-process provider registry
- No network overhead

## Usage Examples

### Basic Workflow Execution

```python
from gleitzeit.client import GleitzeitClient
from gleitzeit.core.models import Workflow, Task

async def run_workflow():
    async with GleitzeitClient() as client:
        # Create workflow
        workflow = Workflow(
            name="Data Processing",
            tasks=[
                Task(
                    id="load",
                    name="Load Data",
                    method="file/read",
                    parameters={"path": "data.csv"}
                ),
                Task(
                    id="process",
                    name="Process Data",
                    method="python/execute",
                    parameters={"code": "result = process_data()"},
                    dependencies=["load"]
                )
            ]
        )
        
        # Submit and wait
        result = await client.submit_workflow(workflow)
        final_state = await client.wait_for_workflow(result['workflow_id'])
        print(f"Workflow completed: {final_state}")
```

### Batch Processing with Progress

```python
async def batch_process_with_updates():
    async with GleitzeitClient() as client:
        # Process files with progress updates
        async for progress in client.batch_process_with_progress(
            directory="/data",
            pattern="*.txt",
            prompt="Summarize this document",
            model="llama3.2",
            max_concurrent=5
        ):
            print(f"Progress: {progress['progress']['completed']}/{progress['progress']['total']}")
            print(f"File: {progress['file']} - Result: {progress['result']}")
```

### Directory Processing with Workflow Template

```python
async def process_directory():
    async with GleitzeitClient() as client:
        workflow_template = """
        name: Process ${file_name}
        tasks:
          - name: Read file
            id: read
            method: file/read
            input:
              path: ${file_path}
          
          - name: Analyze
            id: analyze
            method: llm/chat
            input:
              prompt: Analyze ${file_name}
              model: llama3.2
            depends_on: [read]
          
          - name: Save results
            id: save
            method: file/write
            input:
              path: ${file_dir}/results/${file_name}.analysis.txt
              content: "{{analyze.output}}"
            depends_on: [analyze]
        """
        
        results = await client.process_directory(
            directory="/documents",
            file_extensions=[".txt", ".md", ".pdf"],
            workflow_yaml=workflow_template,
            max_concurrent=10,
            recursive=True
        )
        
        print(f"Processed {len(results)} files")
```

### Queue Management

```python
async def manage_queues():
    async with GleitzeitClient() as client:
        # Get queue status
        queues = await client.get_queues()
        for queue_name, info in queues.items():
            print(f"Queue {queue_name}: {info['size']} items")
        
        # Get health status
        health = await client.get_queue_health()
        for queue, status in health.items():
            print(f"{queue}: {status['status']} - {status['message']}")
        
        # Rebalance if needed
        recommendations = await client.rebalance_queues()
        for rec in recommendations['recommendations']:
            print(f"Recommend: {rec['action']} for {rec['queue']}")
```

### Mode Switching

```python
async def switch_modes():
    async with GleitzeitClient(mode="auto") as client:
        print(f"Initial mode: {client.get_mode()}")
        
        # Switch to native mode
        await client.switch_mode("native")
        print(f"Switched to: {client.get_mode()}")
        
        # Execute in native mode
        result = await client.execute_task(task)
        
        # Switch back to API
        await client.switch_mode("api")
        result = await client.execute_task(task)
```

## Migration Guide

### From Legacy Client

The new modular client maintains backward compatibility:

```python
# Old code continues to work
from gleitzeit import GleitzeitClient

client = GleitzeitClient()  # Works with new modular client

# To use legacy client explicitly (deprecated)
client = GleitzeitClient(use_legacy=True)
```

### Extending the Client

Add new functionality via mixins:

```python
# custom_mixin.py
class CustomMixin:
    """Custom functionality mixin."""
    
    async def custom_operation(self, param: str) -> Dict[str, Any]:
        """Perform custom operation."""
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        
        # Delegate to adapter
        return await self._adapter.custom_operation(param)

# Extend the client
from gleitzeit.client.base import ModularGleitzeitClient
from custom_mixin import CustomMixin

class ExtendedClient(ModularGleitzeitClient, CustomMixin):
    """Client with custom functionality."""
    pass
```

## Configuration

### Environment Variables

```bash
# API Mode Configuration
GLEITZEIT_API_HOST=localhost
GLEITZEIT_API_PORT=8000
GLEITZEIT_AUTO_START_SERVER=true
GLEITZEIT_KEEP_SERVER_RUNNING=true

# Native Mode Configuration  
GLEITZEIT_PERSISTENCE_TYPE=redis
GLEITZEIT_REDIS_URL=redis://localhost:6379
GLEITZEIT_MAX_WORKERS=10
```

### Programmatic Configuration

```python
# API mode with custom settings
client = GleitzeitClient(
    mode="api",
    api_host="remote-server.com",
    api_port=9000,
    auto_start_server=False
)

# Native mode with Redis
client = GleitzeitClient(
    mode="native",
    persistence_type="redis",
    redis_url="redis://localhost:6379",
    max_workers=20
)
```

## Performance Considerations

### Connection Pooling
The API adapter uses connection pooling for better performance:
```python
# Reuses connections across requests
async with GleitzeitClient(mode="api") as client:
    # All operations share the same session pool
    await client.submit_task(task1)
    await client.submit_task(task2)
```

### Concurrent Operations
Use batch methods for better performance:
```python
# Good - concurrent execution
results = await client.batch_execute_tasks(tasks, max_concurrent=10)

# Less efficient - sequential
results = []
for task in tasks:
    result = await client.execute_task(task)
    results.append(result)
```

### Resource Management
Always use context managers:
```python
# Good - automatic cleanup
async with GleitzeitClient() as client:
    await client.submit_workflow(workflow)

# Avoid - manual cleanup required
client = GleitzeitClient()
await client.initialize()
await client.submit_workflow(workflow)
await client.shutdown()  # Easy to forget
```

## Troubleshooting

### Common Issues

1. **Import Error**: `ModuleNotFoundError: No module named 'gleitzeit.client'`
   - Solution: Ensure you're using the latest version with modular client

2. **Runtime Error**: `Client not initialized`
   - Solution: Call `await client.initialize()` or use context manager

3. **API Connection Failed**
   - Check if API server is running: `gleitzeit serve`
   - Verify host/port configuration
   - Check firewall settings

4. **Native Mode Missing Dependencies**
   - Install required packages: `pip install gleitzeit[native]`

### Debug Mode

Enable debug logging:
```python
import logging
logging.basicConfig(level=logging.DEBUG)

async with GleitzeitClient() as client:
    # Debug logs will show adapter operations
    await client.submit_workflow(workflow)
```

## API Reference

### Client Initialization

```python
GleitzeitClient(
    mode: Union[str, ClientMode] = ClientMode.AUTO,
    api_host: str = "localhost",
    api_port: int = 8000,
    auto_start_server: bool = True,
    keep_server_running: bool = True,
    **native_config
)
```

### Client Methods

All mixin methods are available on the client instance. See individual mixin documentation above for complete method signatures.

## Best Practices

1. **Always use context managers** for automatic resource cleanup
2. **Use batch operations** for processing multiple items
3. **Configure appropriate timeouts** for long-running operations
4. **Handle exceptions gracefully** with try/except blocks
5. **Use type hints** for better IDE support and type checking
6. **Monitor queue health** in production environments
7. **Enable authentication** in production deployments

## Comparison with Legacy Client

| Aspect | Legacy Client | Modular Client |
|--------|--------------|----------------|
| File Size | 3,712 lines | ~300 lines per module |
| Organization | Monolithic | Mixin-based |
| Mode Handling | Duplicate methods | Adapter pattern |
| Testing | Difficult | Easy per-component |
| Extension | Modify core | Add mixins |
| Maintenance | Hard | Easy |
| Performance | Same | Better (pooling) |

## Future Enhancements

- Plugin system for dynamic mixin loading
- WebSocket support for real-time updates
- Async context managers for resource allocation
- Distributed execution support
- Advanced caching strategies