# Easy Client Error Handling Documentation

## Overview

The Gleitzeit Easy Client provides a fluent interface for defining workflows with integrated error handling that leverages the actual implemented error system. This document describes how to use the error handling features with the easy client.

## Key Principle

The easy client uses **only the errors and features that are actually implemented** in the Gleitzeit system and providers. It does not rely on hypothetical or unimplemented event handlers. Instead, it configures task metadata that the backend's retry and timeout systems understand.

## Error Handling Features

### 1. Retry Configuration

Configure automatic retries for tasks that may fail with transient errors:

```python
from gleitzeit.easy import t, w

task = (
    t("risky_operation", "python/v1:python/execute")
    .with_(file="process_data.py")
    .with_retry(max_attempts=3, delay=2.0)  # Retry up to 3 times with 2 second delay
)
```

**How it works:**
- Sets `metadata.max_attempts` and `metadata.retry_delay` in the task
- The backend's retry manager uses these values when the task fails
- Only retries on retryable errors (network issues, timeouts, etc.)

### 2. Timeout Configuration

Set execution timeouts to prevent tasks from running indefinitely:

```python
task = (
    t("long_running_task", "python/v1:python/execute")
    .with_(file="complex_calculation.py")
    .with_timeout(30)  # 30 second timeout
)
```

**How it works:**
- Sets the `timeout` field in the task definition
- The TaskExecutor enforces this timeout during execution
- If exceeded, the task fails with a timeout error

### 3. Combining Retry and Timeout

Use both features together for robust error handling:

```python
task = (
    t("api_call", "python/v1:python/execute")
    .with_(file="call_external_api.py")
    .with_retry(max_attempts=3, delay=5.0)
    .with_timeout(60)
)
```

## Error Classes

The easy client includes comprehensive validation error classes:

### Base Error Classes

```python
from gleitzeit.easy import (
    EasyClientError,           # Base error for all easy client errors
    TaskBuilderError,          # Errors in task building
    WorkflowBuilderError,      # Errors in workflow building
)
```

### Validation Errors

```python
from gleitzeit.easy import (
    InvalidProtocolFormatError,  # Protocol format is invalid
    InvalidDependencyError,      # Task dependency doesn't exist
    DuplicateTaskError,         # Duplicate task IDs
    CircularDependencyError,    # Circular dependencies detected
    EmptyWorkflowError,         # No tasks in workflow
    InvalidParameterError,      # Invalid parameter values
    InvalidConfigurationError,  # Invalid configuration
)
```

## Error Discovery

The easy client can discover what errors providers actually support:

```python
import asyncio
from gleitzeit.client import GleitzeitClient

async def discover_errors():
    client = GleitzeitClient(base_url="http://localhost:8000")
    await client.initialize()

    # Get errors for a specific protocol
    errors = await client.get_provider_errors("python/v1")

    for error in errors:
        print(f"Error: {error['name']}")
        print(f"  Retryable: {error.get('is_retryable', False)}")
        print(f"  Code: {error.get('error_code_name', 'N/A')}")

asyncio.run(discover_errors())
```

## Complete Example

Here's a complete example showing error handling in action:

```python
#!/usr/bin/env python3
import asyncio
from gleitzeit.easy import t, w
from gleitzeit.client import GleitzeitClient

async def main():
    # Create tasks with error handling
    fetch_data = (
        t("fetch_data", "python/v1:python/execute")
        .with_(file="fetch_from_api.py")
        .with_retry(max_attempts=3, delay=2.0)
        .with_timeout(30)
    )

    process_data = (
        t("process_data", "python/v1:python/execute")
        .needs("fetch_data")
        .with_(file="transform_data.py")
        .with_retry(max_attempts=2, delay=1.0)
        .with_timeout(60)
    )

    save_results = (
        t("save_results", "python/v1:python/execute")
        .needs("process_data")
        .with_(file="save_to_database.py")
        .with_retry(max_attempts=5, delay=3.0)  # More retries for DB operations
        .with_timeout(45)
    )

    # Create workflow
    workflow = (
        w(fetch_data, process_data, save_results)
        .name("data_pipeline")
        .version("1.0.0")
        .description("Data pipeline with comprehensive error handling")
    )

    # Validate workflow
    errors = workflow.validate()
    if errors:
        print(f"Validation errors: {errors}")
        return

    # Submit workflow
    client = GleitzeitClient(base_url="http://localhost:8000")
    await client.initialize()

    workflow_dict = workflow.to_dict()
    result = await client.submit_workflow(workflow_dict)
    workflow_id = result.get("workflow_id")
    print(f"Submitted workflow: {workflow_id}")

    # Monitor workflow
    while True:
        workflow_obj = await client.get_workflow(workflow_id)
        print(f"Status: {workflow_obj.status}")

        if workflow_obj.status in ["completed", "failed"]:
            break

        await asyncio.sleep(2)

    print(f"Final status: {workflow_obj.status}")

if __name__ == "__main__":
    asyncio.run(main())
```

## Validation

The easy client performs comprehensive validation:

### Task Validation

- **Task ID**: Must be alphanumeric with underscores, hyphens, or dots
- **Protocol Format**: Must be in format `protocol/version:method`
- **Dependencies**: All referenced tasks must exist in the workflow
- **Parameters**: Parameter values are validated

### Workflow Validation

- **Empty Workflow**: Must contain at least one task
- **Duplicate Tasks**: No duplicate task IDs allowed
- **Circular Dependencies**: Detects and prevents circular dependencies
- **Dependency Resolution**: Ensures all dependencies can be resolved

Example validation:

```python
workflow = w(
    t("task1", "python/v1:python/execute").needs("task2"),
    t("task2", "python/v1:python/execute").needs("task1")
)

errors = workflow.validate()
# Returns: ["Circular dependency detected: task1 -> task2 -> task1"]
```

## Retryable Errors

The system automatically retries on these error types:

- `PROVIDER_TIMEOUT` - Provider operation timed out
- `PROVIDER_OVERLOADED` - Provider is overloaded
- `CONNECTION_TIMEOUT` - Network connection timeout
- `NETWORK_UNREACHABLE` - Network is unreachable
- `RESOURCE_EXHAUSTED` - Resources exhausted
- `RATE_LIMIT_EXCEEDED` - Rate limit exceeded

Non-retryable errors (immediate failure):

- `VALIDATION_ERROR` - Input validation failed
- `METHOD_NOT_SUPPORTED` - Method not supported
- `AUTHENTICATION_FAILED` - Authentication failed
- `PERMISSION_DENIED` - Permission denied
- `TASK_NOT_FOUND` - Task not found
- `INVALID_REQUEST` - Invalid request format

## Implementation Details

### Task Metadata Structure

When you use `with_retry()` and `with_timeout()`, the easy client creates this structure:

```json
{
  "id": "task_id",
  "protocol": "python/v1",
  "method": "python/execute",
  "params": {...},
  "metadata": {
    "max_attempts": 3,
    "retry_delay": 2.0
  },
  "timeout": 30
}
```

### How Retry Works

1. Task fails with an error
2. System checks if error is retryable using `is_retryable_error()`
3. If retryable and attempts < max_attempts:
   - Waits for retry_delay seconds
   - Re-queues the task
   - Increments attempt counter
4. If not retryable or max attempts reached:
   - Task marked as failed
   - Workflow continues or fails based on dependencies

### How Timeout Works

1. TaskExecutor starts task execution
2. Sets a timeout using the task's `timeout` field
3. If execution exceeds timeout:
   - Task is terminated
   - Returns timeout error
   - Error may trigger retry if configured

## Best Practices

1. **Use appropriate retry counts**:
   - Network operations: 3-5 retries
   - Database operations: 2-3 retries
   - Critical operations: 5+ retries

2. **Set reasonable timeouts**:
   - API calls: 30-60 seconds
   - Data processing: 60-300 seconds
   - LLM operations: 120-600 seconds

3. **Configure retry delays**:
   - Start with 1-2 seconds for fast operations
   - Use 5-10 seconds for rate-limited APIs
   - Consider exponential backoff for production

4. **Validate early**:
   - Always call `workflow.validate()` before submission
   - Check validation errors and fix before submitting

5. **Monitor workflows**:
   - Use client events to monitor progress
   - Check task statuses for debugging
   - Log errors for analysis

## Migration from Event Handlers

If you were using hypothetical event handlers (like `on_error()`), migrate to real error handling:

**Before (doesn't work):**
```python
task.on_error().run("error_handler", "python/v1:python/execute")
```

**After (works):**
```python
task.with_retry(max_attempts=3, delay=2.0).with_timeout(30)
```

The system's built-in retry mechanism provides better error handling than custom event handlers.

## Troubleshooting

### Task Not Retrying

1. Check if error is retryable (see list above)
2. Verify `metadata.max_attempts` is set
3. Check server logs for retry attempts

### Timeout Not Working

1. Verify `timeout` field is set in task
2. Check if provider supports timeouts
3. Ensure timeout value is reasonable

### Validation Errors

1. Check task ID format (alphanumeric + `_-.`)
2. Verify protocol format (`protocol/version:method`)
3. Ensure all dependencies exist
4. Look for circular dependencies

## Summary

The easy client's error handling:
- Uses the actual implemented retry and timeout systems
- Configures task metadata that the backend understands
- Provides comprehensive validation
- Supports error discovery to understand provider capabilities
- Works with the system's retryable error detection

This approach ensures reliability while using only features that are actually implemented in the Gleitzeit system.