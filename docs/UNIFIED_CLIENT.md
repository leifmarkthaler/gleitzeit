# Gleitzeit Unified Client Documentation

## Overview

The Gleitzeit Unified Client provides a single, consistent interface for interacting with the Gleitzeit workflow orchestration system. It supports both local (native) execution and remote (API) execution, making it ideal for development, testing, and production use cases.

**Simple Import**: Just use `from gleitzeit import Client` - no need to import modes separately!

## Key Features

- **Multiple Execution Modes**: Native, API, and Auto modes
- **Automatic Server Management**: Can auto-start and manage API servers
- **Consistent Interface**: Same code works in all modes
- **Smart Mode Selection**: Automatically chooses the best execution mode
- **Resource Management**: Proper cleanup and lifecycle management
- **Type Safety**: Full type hints for better IDE support

## Installation

The unified client is included with the Gleitzeit installation:

```bash
# Using pip
pip install -e .

# Using uv (recommended)
uv pip install -e .
```

## Quick Start

```python
import asyncio
from gleitzeit import Client

async def main():
    # Auto mode (default) - automatically selects best option
    async with Client() as client:
        # Execute a task
        result = await client.execute_task(
            protocol="mcp/v1",
            method="mcp/tool.add",
            params={"a": 5, "b": 3},
            name="Addition Task"
        )
        print(f"Result: {result.result}")
        
        # Run a workflow
        workflow_result = await client.run_workflow("workflow.yaml")
        print(f"Workflow status: {workflow_result['status']}")

asyncio.run(main())
```

## Execution Modes

### 1. AUTO Mode (Default)

Automatically selects the best execution mode:
- Checks if an API server is available
- If not available and `auto_start_server=True`, starts one
- Falls back to native mode if API is not available

```python
async with Client(mode=ClientMode.AUTO) as client:
    print(f"Selected mode: {client.get_mode()}")
    # Use client normally - it handles mode selection
```

### 2. NATIVE Mode

Direct execution using the local ExecutionEngine. Best for:
- Development and testing
- Single-user scenarios
- When you need direct access to the execution engine
- Debugging

```python
async with Client(mode=ClientMode.NATIVE) as client:
    # Executes directly without any server
    result = await client.execute_task(...)
```

**Advantages:**
- No server process needed
- Direct access to execution engine
- Faster for single-user development
- Easier debugging

### 3. API Mode

Executes through the REST API server. Best for:
- Production environments
- Distributed execution
- Multiple concurrent clients
- Service-oriented architectures

```python
async with Client(
    mode=ClientMode.API,
    api_host="localhost",
    api_port=8000
) as client:
    # All operations go through the API
    result = await client.execute_task(...)
```

**Advantages:**
- Centralized execution
- Multiple clients can connect
- Persistence across client restarts
- Production-ready architecture

## Client Configuration

### Constructor Parameters

```python
Client(
    mode: ClientMode = ClientMode.AUTO,
    api_host: str = "localhost",
    api_port: int = 8000,
    auto_start_server: bool = True,
    keep_server_running: bool = True,
    native_config: Optional[Dict[str, Any]] = None
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `mode` | `ClientMode` | `AUTO` | Execution mode (AUTO, NATIVE, or API) |
| `api_host` | `str` | `"localhost"` | API server hostname |
| `api_port` | `int` | `8000` | API server port |
| `auto_start_server` | `bool` | `True` | Auto-start API server if not running (API/AUTO modes) |
| `keep_server_running` | `bool` | `True` | Keep server running after client shutdown (if started by client) |
| `native_config` | `Dict[str, Any]` | `None` | Configuration for native mode execution |

### Native Configuration Options

```python
native_config = {
    "max_concurrent_tasks": 10,  # Maximum parallel tasks
    "persistence_type": "redis",  # Persistence backend
    "redis_url": "redis://localhost:6379/0"
}

async with Client(
    mode=ClientMode.NATIVE,
    native_config=native_config
) as client:
    # Use configured native client
```

## Core Methods

### Task Execution

#### `execute_task()`

Execute a single task:

```python
result = await client.execute_task(
    protocol="python/v1",
    method="python/execute",
    params={"file": "calculate_stats.py"},
    name="Statistics Calculation"
)

if result.status == "completed":
    print(f"Output: {result.result}")
else:
    print(f"Error: {result.error}")
```

**Parameters:**
- `protocol` (str): Protocol identifier (e.g., "python/v1", "llm/v1", "mcp/v1")
- `method` (str): Method to execute
- `params` (Dict[str, Any]): Task parameters
- `name` (Optional[str]): Task name for identification

**Returns:** `TaskResult` object with status, result, and error information

### Workflow Execution

#### `run_workflow()`

Execute a workflow from a YAML/JSON file:

```python
result = await client.run_workflow(
    workflow_file="examples/data_pipeline.yaml",
    watch=True  # Monitor execution progress
)

print(f"Workflow ID: {result['workflow_id']}")
print(f"Status: {result['status']}")
print(f"Results: {result['results']}")
```

**Parameters:**
- `workflow_file` (str): Path to workflow definition file
- `watch` (bool): Watch execution progress in real-time

**Returns:** Dictionary with workflow execution results

### Batch Processing

#### `batch_process()`

Process multiple files in parallel:

```python
batch_result = await client.batch_process(
    directory="documents",
    pattern="*.txt",
    method="llm/chat",
    prompt="Summarize this document in 3 bullet points",
    model="llama3.2:latest",
    max_concurrent=5,
    name="Document Batch Processing"
)

print(f"Processed: {batch_result['total_files']} files")
print(f"Successful: {batch_result['successful']}")
print(f"Failed: {batch_result['failed']}")
```

**Parameters:**
- `directory` (str): Directory containing files
- `pattern` (str): File pattern to match (e.g., "*.txt")
- `method` (str): Processing method
- `prompt` (str): Prompt for each file
- `model` (str): Model to use (for LLM tasks)
- `max_concurrent` (int): Maximum parallel tasks
- `name` (Optional[str]): Batch operation name

### Chat Interface

#### `chat()`

Simple chat interface for LLM interaction:

```python
response = await client.chat(
    message="Explain workflow orchestration",
    model="llama3.2:latest",
    temperature=0.7,
    session_id="session-123"  # Optional for context
)

print(f"Response: {response}")
```

**Parameters:**
- `message` (str): User message
- `model` (str): LLM model to use
- `temperature` (float): Generation temperature (0.0-1.0)
- `session_id` (Optional[str]): Session ID for conversation context

## Utility Methods

### Mode Detection

```python
# Check current mode
current_mode = client.get_mode()  # Returns: "api", "native", or "not initialized"

# Check specific modes
if client.is_api_mode:
    print("Using API mode")
elif client.is_native_mode:
    print("Using native mode")
```

## Complete Examples

### Example 1: Development Workflow

```python
import asyncio
from gleitzeit import Client, ClientMode

async def development_workflow():
    """Development workflow using native mode for speed"""
    
    # Use native mode for development
    async with Client(mode=ClientMode.NATIVE) as client:
        print(f"Developing in {client.get_mode()} mode")
        
        # Test Python script
        result = await client.execute_task(
            protocol="python/v1",
            method="python/execute",
            params={"file": "process_data.py"},
            name="Data Processing"
        )
        
        if result.status == "completed":
            print(f"✓ Script executed: {result.result}")
        else:
            print(f"✗ Script failed: {result.error}")
            
        # Test with MCP tools
        calc_result = await client.execute_task(
            protocol="mcp/v1",
            method="mcp/tool.multiply",
            params={"a": 10, "b": 5},
            name="Calculation Test"
        )
        
        print(f"Calculation: {calc_result.result}")

asyncio.run(development_workflow())
```

### Example 2: Production Deployment

```python
import asyncio
from gleitzeit import Client, ClientMode

async def production_workflow():
    """Production workflow using API mode"""
    
    # Force API mode for production
    async with Client(
        mode=ClientMode.API,
        api_host="api.production.com",
        api_port=8000,
        auto_start_server=False  # Don't auto-start in production
    ) as client:
        
        # Run production workflow
        result = await client.run_workflow(
            "workflows/production_pipeline.yaml",
            watch=True
        )
        
        if result['status'] == 'completed':
            print(f"✓ Pipeline completed successfully")
            # Process results
            for task_id, task_result in result['results'].items():
                print(f"  Task {task_id}: {task_result['status']}")
        else:
            print(f"✗ Pipeline failed: {result}")
            # Handle failure

asyncio.run(production_workflow())
```

### Example 3: Batch Document Processing

```python
import asyncio
from pathlib import Path
from gleitzeit import Client

async def process_documents():
    """Process a batch of documents"""
    
    async with Client() as client:  # AUTO mode
        print(f"Processing in {client.get_mode()} mode")
        
        # Process all markdown files
        result = await client.batch_process(
            directory="docs",
            pattern="*.md",
            method="llm/chat",
            prompt="Extract the main topics from this document",
            model="llama3.2:latest",
            max_concurrent=10
        )
        
        print(f"\nBatch Processing Results:")
        print(f"Total files: {result['total_files']}")
        print(f"Successful: {result['successful']}")
        print(f"Failed: {result['failed']}")
        print(f"Time taken: {result['processing_time']:.2f}s")
        
        # Save results
        import json
        with open("batch_results.json", "w") as f:
            json.dump(result['results'], f, indent=2)

asyncio.run(process_documents())
```

### Example 4: Mode Migration

```python
import asyncio
from gleitzeit import Client, ClientMode

async def migrate_from_dev_to_prod():
    """Show how to migrate from development to production"""
    
    workflow_file = "examples/data_pipeline.yaml"
    
    # Phase 1: Development with native mode
    print("Phase 1: Development")
    async with Client(mode=ClientMode.NATIVE) as client:
        result = await client.run_workflow(workflow_file)
        assert result['status'] == 'completed', "Development test failed"
        print("✓ Development test passed")
    
    # Phase 2: Integration testing with API mode
    print("\nPhase 2: Integration Testing")
    async with Client(
        mode=ClientMode.API,
        auto_start_server=True
    ) as client:
        result = await client.run_workflow(workflow_file)
        assert result['status'] == 'completed', "Integration test failed"
        print("✓ Integration test passed")
    
    # Phase 3: Production with AUTO mode
    print("\nPhase 3: Production")
    async with Client(mode=ClientMode.AUTO) as client:
        print(f"Auto-selected: {client.get_mode()} mode")
        result = await client.run_workflow(workflow_file)
        print(f"✓ Production execution: {result['status']}")

asyncio.run(migrate_from_dev_to_prod())
```

## Error Handling

```python
import asyncio
from gleitzeit import Client, ClientMode

async def robust_execution():
    """Example with proper error handling"""
    
    try:
        async with Client(mode=ClientMode.API) as client:
            result = await client.execute_task(
                protocol="python/v1",
                method="python/execute",
                params={"file": "risky_script.py"},
                name="Risky Operation"
            )
            
            if result.status == "completed":
                print(f"Success: {result.result}")
            elif result.status == "failed":
                print(f"Task failed: {result.error}")
                # Handle task failure
            elif result.status == "retry_pending":
                print("Task is being retried...")
                # Wait or handle retry
                
    except RuntimeError as e:
        if "API server not available" in str(e):
            print("Could not connect to API server")
            # Fall back to native mode or handle error
        else:
            raise
    except Exception as e:
        print(f"Unexpected error: {e}")
        # Handle unexpected errors

asyncio.run(robust_execution())
```

## Best Practices

### 1. Use Context Managers

Always use the async context manager to ensure proper cleanup:

```python
# Good
async with Client() as client:
    await client.execute_task(...)

# Avoid manual management
client = GleitzeitClient()
await client.initialize()  # Don't do this
```

### 2. Choose the Right Mode

- **Development**: Use `NATIVE` mode for faster iteration
- **Testing**: Use `NATIVE` or `API` mode depending on what you're testing
- **Production**: Use `API` mode or `AUTO` mode for flexibility
- **CI/CD**: Use `API` mode with explicit configuration

### 3. Handle Mode-Specific Behavior

```python
async with Client() as client:
    if client.is_native_mode:
        # Native mode specific configuration
        print("Running locally")
    elif client.is_api_mode:
        # API mode specific handling
        print(f"Connected to API at {client.api_url}")
```

### 4. Configure Server Management

For production environments, disable auto-start:

```python
# Production configuration
client = Client(
    mode=ClientMode.API,
    auto_start_server=False,  # Don't auto-start in production
    keep_server_running=True   # But keep it running if we start it
)
```

### 5. Use Type Hints

The client is fully typed for better IDE support:

```python
from gleitzeit import Client, ClientMode
from gleitzeit.core.models import TaskResult

async def process() -> TaskResult:
    async with Client() as client:
        result: TaskResult = await client.execute_task(...)
        return result
```

## Migration from Existing Clients

### From Direct ExecutionEngine Usage

```python
# Old approach
engine = ExecutionEngine(...)
await engine.submit_task(task)
await engine.start(ExecutionMode.SINGLE_SHOT)

# New approach
async with Client(mode=ClientMode.NATIVE) as client:
    result = await client.execute_task(
        protocol=task.protocol,
        method=task.method,
        params=task.params,
        name=task.name
    )
```

### From API Client

```python
# Old approach
async with GleitzeitAPIClient() as api_client:
    result = await api_client.execute_task(task_dict)

# New approach
async with Client(mode=ClientMode.API) as client:
    result = await client.execute_task(
        protocol=task_dict["protocol"],
        method=task_dict["method"],
        params=task_dict["params"],
        name=task_dict["name"]
    )
```

## Troubleshooting

### Issue: API Mode Fails to Connect

```python
# Check if server is running
async with Client(
    mode=ClientMode.API,
    auto_start_server=True  # Try auto-starting
) as client:
    if not client.is_api_mode:
        print("Failed to use API mode, fell back to:", client.get_mode())
```

### Issue: Native Mode Missing Providers

Ensure providers are properly registered in native mode:

```python
native_config = {
    "max_concurrent_tasks": 5,
    "provider_config": {
        "python": {"allow_local": True},
        "ollama": {"auto_discover": False}
    }
}

async with Client(
    mode=ClientMode.NATIVE,
    native_config=native_config
) as client:
    # Providers will be configured with these settings
```

### Issue: Server Keeps Running After Tests

Control server lifecycle explicitly:

```python
async with Client(
    keep_server_running=False  # Stop server on shutdown
) as client:
    # Server will be stopped when client exits
```

## Performance Considerations

### Native Mode Performance

- **Pros**: No network overhead, direct execution
- **Cons**: Single process, no distribution
- **Best for**: Development, small workloads

### API Mode Performance

- **Pros**: Distributed execution, scalable
- **Cons**: Network overhead, serialization cost
- **Best for**: Production, large workloads

### Optimization Tips

1. **Batch Operations**: Use `batch_process()` for multiple files
2. **Connection Pooling**: API mode reuses connections automatically
3. **Parallel Execution**: Set `max_concurrent` appropriately
4. **Mode Selection**: Use AUTO mode to let the client optimize

## Security Considerations

### Python Execution

The client only supports file-based Python execution for security:

```python
# Supported - executes a file
await client.execute_task(
    protocol="python/v1",
    method="python/execute",
    params={"file": "script.py"}  # Must be in examples/scripts/
)

# NOT supported - no arbitrary code execution
# params={"code": "malicious_code()"}  # This won't work
```

### API Security

When using API mode in production:

1. Use proper authentication (when implemented)
2. Configure firewall rules for API ports
3. Use HTTPS in production (configure reverse proxy)
4. Validate all inputs

## Future Enhancements

Planned features for the unified client:

- [ ] Authentication and authorization
- [ ] Streaming results for long-running tasks
- [ ] WebSocket support for real-time updates
- [ ] Client-side caching
- [ ] Retry policies configuration
- [ ] Custom provider registration
- [ ] Metrics and monitoring hooks

## Support

For issues, questions, or contributions:

- GitHub: https://github.com/leifmarkthaler/gleitzeit
- Documentation: /docs/
- Examples: /examples/

---

*Last Updated: 2025-08-18*
*Version: 0.0.5*