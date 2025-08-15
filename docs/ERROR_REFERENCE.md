# Gleitzeit Error Reference

## Overview

Gleitzeit uses a centralized error management system with specific error codes and classes to provide clear, actionable error messages. All errors follow the JSON-RPC 2.0 specification with custom extensions.

## Error Code Ranges

| Range | Category | Description |
|-------|----------|-------------|
| -32768 to -32000 | JSON-RPC Protocol | Standard JSON-RPC 2.0 errors |
| -31999 to -31000 | System | Gleitzeit system errors |
| -30999 to -30000 | Provider/Protocol | Provider and protocol errors |
| -29999 to -29000 | Task Execution | Task-related errors |
| -28999 to -28000 | Workflow | Workflow-related errors |
| -27999 to -27000 | Queue/Scheduling | Queue and scheduling errors |
| -26999 to -26000 | Persistence | Database and storage errors |
| -25999 to -25000 | Network | Network and communication errors |

## Common Error Classes

### ProviderError
Base class for all provider-related errors.

**Common Causes:**
- Provider not available
- Provider initialization failed
- Provider timeout
- Provider overloaded

**Example:**
```python
ProviderError: [PROVIDER_NOT_AVAILABLE] Ollama API error 500: Internal Server Error
```

**Resolution:**
- Check if the provider service is running
- Verify provider configuration
- Check network connectivity

### TaskError
Base class for all task execution errors.

**Common Causes:**
- Task validation failed
- Task execution failed
- Task timeout
- Task dependencies failed

**Example:**
```python
TaskError: [TASK_EXECUTION_FAILED] Task failed after 3 retry attempts
```

**Resolution:**
- Check task parameters
- Verify dependencies are satisfied
- Increase timeout if needed

### WorkflowError
Base class for workflow-related errors.

**Common Causes:**
- Workflow validation failed
- Circular dependencies
- Invalid workflow state

**Example:**
```python
WorkflowError: [WORKFLOW_VALIDATION_FAILED] Workflow validation failed: Missing required field 'tasks'
```

**Resolution:**
- Validate workflow YAML/JSON
- Check for circular dependencies
- Ensure all task references are valid

## Specific Error Classes

### MethodNotSupportedError
**Error Code:** METHOD_NOT_SUPPORTED (-30008)

**Description:** The requested method is not supported by the provider.

**Common Scenarios:**
```python
# When calling an unsupported method on a provider
provider.handle_request("unsupported_method", {})
# Raises: MethodNotSupportedError: Method 'unsupported_method' not supported by provider 'ollama-provider'
```

**Resolution:**
- Check provider's `get_supported_methods()` for available methods
- Verify method name spelling
- Ensure provider supports the protocol version

### InvalidParameterError
**Error Code:** INVALID_PARAMS (-32602)

**Description:** Invalid parameters provided to a method or task.

**Common Scenarios:**
```python
# Missing required parameter
task = Task(method="llm/vision", params={})
# Raises: InvalidParameterError: Invalid parameter 'image_data': Either image_path, image_data, or images required for vision

# Wrong parameter type
workflow.run(workflow="not_a_dict")
# Raises: InvalidParameterError: Invalid parameter 'workflow': Unsupported workflow type: <class 'str'>
```

**Resolution:**
- Check required parameters in documentation
- Verify parameter types match expected types
- Ensure all required fields are provided

### ConfigurationError
**Error Code:** CONFIGURATION_ERROR (-31003)

**Description:** Configuration-related errors.

**Common Scenarios:**
```python
# Unsupported file format
load_workflow_from_file("workflow.txt")
# Raises: ConfigurationError: Unsupported file format: .txt

# Security configuration
provider.handle_request("eval", {})
# Raises: ConfigurationError: eval method is disabled for security. Set allow_eval=true to enable.
```

**Resolution:**
- Check configuration files
- Verify file formats (YAML/JSON)
- Review security settings

### TaskValidationError
**Error Code:** TASK_VALIDATION_FAILED (-29001)

**Description:** Task validation failed.

**Common Scenarios:**
```python
# Invalid method name
task = Task(method="", params={})
# Raises: TaskValidationError: Task validation failed: Method name cannot be empty

# Invalid parameters
task = Task(method="python/execute", params={"timeout": "not_a_number"})
# Raises: TaskValidationError: Task validation failed: Parameters must be JSON serializable
```

**Resolution:**
- Validate task definition
- Check method name format
- Ensure parameters are JSON serializable

### WorkflowValidationError
**Error Code:** WORKFLOW_VALIDATION_FAILED (-28001)

**Description:** Workflow validation failed.

**Common Scenarios:**
```python
# Missing required fields
workflow = Workflow(name="test", tasks=[])
# Raises: WorkflowValidationError: Workflow validation failed: Workflow must contain at least one task

# Invalid dependencies
task = Task(name="task2", dependencies=["nonexistent_task"])
# Raises: WorkflowValidationError: Workflow validation failed: Task 'task2' depends on unknown task 'nonexistent_task'
```

**Resolution:**
- Ensure workflow has required fields
- Verify all task dependencies exist
- Check for circular dependencies

### ProviderNotFoundError
**Error Code:** PROVIDER_NOT_FOUND (-30002)

**Description:** The requested provider was not found.

**Common Scenarios:**
```python
registry.get_provider("unknown_provider")
# Raises: ProviderNotFoundError: Provider not found: unknown_provider
```

**Resolution:**
- Check registered providers with `registry.list_providers()`
- Verify provider ID spelling
- Ensure provider is initialized

### QueueNotFoundError
**Error Code:** QUEUE_NOT_FOUND (-27001)

**Description:** The specified queue was not found.

**Common Scenarios:**
```python
queue_manager.get_queue("nonexistent_queue")
# Raises: QueueNotFoundError: Queue 'nonexistent_queue' not found
```

**Resolution:**
- Check available queues
- Verify queue name
- Ensure queue is created before access

### ProtocolError
**Error Code:** Various protocol-related codes

**Description:** Protocol-level errors in JSON-RPC or provider protocols.

**Common Scenarios:**
```python
# Invalid JSON-RPC format
JSONRPCRequest(method="rpc.reserved")
# Raises: ProtocolError: Method names starting with 'rpc.' are reserved

# Invalid error code
JSONRPCError(code=12345)
# Raises: ProtocolError: Invalid JSON-RPC error code: 12345
```

**Resolution:**
- Follow JSON-RPC 2.0 specification
- Use valid error codes
- Check protocol documentation

## Error Handling Best Practices

### 1. Catching Specific Errors
```python
from gleitzeit.core.errors import (
    ProviderError, TaskError, ConfigurationError
)

try:
    result = await provider.handle_request(method, params)
except ProviderError as e:
    # Handle provider-specific errors
    logger.error(f"Provider error: {e.code} - {e.message}")
    if e.code == ErrorCode.PROVIDER_TIMEOUT:
        # Retry with longer timeout
        pass
except TaskError as e:
    # Handle task errors
    logger.error(f"Task failed: {e}")
except Exception as e:
    # Handle unexpected errors
    logger.exception("Unexpected error")
```

### 2. Checking Error Codes
```python
from gleitzeit.core.errors import ErrorCode

try:
    result = await execute_task(task)
except GleitzeitError as e:
    if e.code == ErrorCode.TASK_TIMEOUT:
        # Handle timeout
        retry_with_longer_timeout()
    elif e.code == ErrorCode.PROVIDER_NOT_AVAILABLE:
        # Handle provider unavailable
        use_fallback_provider()
    else:
        # Handle other errors
        raise
```

### 3. Retryable Errors
```python
from gleitzeit.core.errors import is_retryable_error

try:
    result = await execute_task(task)
except Exception as e:
    if is_retryable_error(e):
        # Retry with backoff
        await asyncio.sleep(backoff_time)
        result = await execute_task(task)
    else:
        # Don't retry
        raise
```

### 4. Error Context
```python
from gleitzeit.core.errors import TaskError

# Add context to errors
try:
    result = process_file(file_path)
except Exception as e:
    raise TaskError(
        f"Failed to process file: {file_path}",
        code=ErrorCode.TASK_EXECUTION_FAILED,
        task_id=task.id,
        data={
            "file_path": str(file_path),
            "original_error": str(e)
        }
    ) from e
```

## Debug Mode

Enable debug mode for detailed error information:

### CLI
```bash
gleitzeit --debug run workflow.yaml
```

### Python API
```python
client = GleitzeitClient(debug=True)
```

### Environment Variable
```bash
export GLEITZEIT_DEBUG=true
```

In debug mode:
- Full stack traces are shown
- Additional error context is displayed
- Expected warnings are shown at INFO level
- All error data fields are included

## Error Severity Levels

Errors are automatically categorized by severity:

| Severity | Error Codes | Action Required |
|----------|-------------|-----------------|
| Critical | SYSTEM_SHUTDOWN, PERSISTENCE_INTEGRITY_ERROR, AUTHENTICATION_FAILED | Immediate attention |
| Error | Most error codes | Investigation needed |
| Warning | QUEUE_FULL, RATE_LIMIT_EXCEEDED, TASK_CANCELLED | Monitor, may self-resolve |
| Info | Normal operation messages | No action needed |

## Troubleshooting Guide

### Provider Errors

**Symptom:** `ProviderError: [PROVIDER_NOT_AVAILABLE]`

**Checks:**
1. Is the provider service running?
   ```bash
   # For Ollama
   curl http://localhost:11434/api/tags
   ```
2. Check provider configuration
3. Verify network connectivity
4. Check provider logs

### Task Errors

**Symptom:** `TaskError: [TASK_TIMEOUT]`

**Checks:**
1. Increase timeout in task definition
2. Check if task is actually hanging
3. Monitor resource usage
4. Check for deadlocks

### Workflow Errors

**Symptom:** `WorkflowError: [WORKFLOW_CIRCULAR_DEPENDENCY]`

**Checks:**
1. Review task dependencies
2. Use dependency visualizer
3. Check for typos in dependency names
4. Ensure no task depends on itself

### Persistence Errors

**Symptom:** `PersistenceError: [PERSISTENCE_CONNECTION_FAILED]`

**Checks:**
1. Database service running?
2. Connection string correct?
3. Permissions valid?
4. Disk space available?

## API Error Responses

All API errors follow this format:

```json
{
  "error": {
    "code": -30008,
    "message": "Method 'unknown' not supported by provider 'ollama-provider'",
    "data": {
      "provider_id": "ollama-provider",
      "method": "unknown"
    }
  }
}
```

## Getting Help

If you encounter an error not covered here:

1. Check the full error message and code
2. Enable debug mode for more details
3. Search existing issues: https://github.com/gleitzeit/gleitzeit/issues
4. Create a new issue with:
   - Error code and message
   - Steps to reproduce
   - Workflow/task definition
   - Debug output