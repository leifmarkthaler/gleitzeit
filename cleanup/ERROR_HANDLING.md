# Gleitzeit V4 Error Handling Guide

## Overview

Gleitzeit V4 uses a centralized error system that provides:
- **Consistent error codes** across all components
- **JSON-RPC 2.0 compliant** error format
- **Automatic retry detection** for transient failures
- **Error severity classification** for monitoring
- **Rich error context** with cause tracking
- **Type-safe error handling** with specific exception classes

## Error Code Ranges

The error system uses structured error code ranges following JSON-RPC 2.0:

| Range | Category | Description |
|-------|----------|-------------|
| -32768 to -32000 | JSON-RPC Protocol | Standard JSON-RPC 2.0 errors |
| -31999 to -31000 | System Errors | Core system failures |
| -30999 to -30000 | Provider/Protocol | Provider and protocol errors |
| -29999 to -29000 | Task Execution | Task-specific errors |
| -28999 to -28000 | Workflow | Workflow orchestration errors |
| -27999 to -27000 | Queue/Scheduling | Queue and scheduler errors |
| -26999 to -26000 | Persistence | Database and storage errors |
| -25999 to -25000 | Network/Communication | Network and connection errors |

## Using the Error System

### Basic Error Creation

```python
from gleitzeit_v4.core.errors import GleitzeitError, ErrorCode

# Create a basic error
error = GleitzeitError(
    message="Something went wrong",
    code=ErrorCode.INTERNAL_ERROR,
    data={"detail": "Additional context"}
)

# Convert to JSON-RPC format
jsonrpc_error = error.to_error_detail().to_jsonrpc_error()
```

### Specific Error Types

```python
from gleitzeit_v4.core.errors import (
    ProviderNotFoundError,
    TaskTimeoutError,
    WorkflowValidationError,
    PersistenceConnectionError
)

# Provider errors
error = ProviderNotFoundError("my-provider-id")

# Task errors
error = TaskTimeoutError("task-123", timeout=30.0)

# Workflow errors
validation_errors = ["No tasks defined", "Invalid name"]
error = WorkflowValidationError("workflow-456", validation_errors)

# Persistence errors
error = PersistenceConnectionError(
    backend="Redis",
    connection_string="redis://localhost:6379",
    cause=original_exception
)
```

### Error Chaining

Track error causes through the system:

```python
try:
    # Low-level operation
    database_connection()
except ConnectionError as e:
    # Wrap with context
    persistence_error = PersistenceConnectionError(
        backend="PostgreSQL",
        connection_string=conn_str,
        cause=e
    )
    
    # Wrap again with task context
    task_error = TaskError(
        message="Failed to save task result",
        code=ErrorCode.TASK_EXECUTION_FAILED,
        task_id="task-999",
        cause=persistence_error
    )
    
    raise task_error
```

## Error Utilities

### Retry Detection

Automatically determine if an error is retryable:

```python
from gleitzeit_v4.core.errors import is_retryable_error

if is_retryable_error(error):
    # Schedule retry
    await schedule_retry(task)
else:
    # Mark as permanently failed
    await mark_failed(task)
```

Retryable error codes:
- `PROVIDER_TIMEOUT`
- `PROVIDER_OVERLOADED`
- `TASK_TIMEOUT`
- `CONNECTION_TIMEOUT`
- `CONNECTION_LOST`
- `NETWORK_UNREACHABLE`
- `RESOURCE_EXHAUSTED`
- `RATE_LIMIT_EXCEEDED`
- `PERSISTENCE_CONNECTION_FAILED`

### Severity Classification

Classify errors for monitoring and alerting:

```python
from gleitzeit_v4.core.errors import get_error_severity

severity = get_error_severity(error)
# Returns: 'critical', 'error', 'warning', or 'info'

if severity == "critical":
    # Send immediate alert
    await alert_on_call_engineer(error)
elif severity == "warning":
    # Log for review
    logger.warning(f"Warning: {error}")
```

Severity levels:
- **Critical**: System shutdown, auth failures, data integrity issues
- **Error**: Execution failures, validation errors, timeouts
- **Warning**: Queue full, rate limits, task cancellations
- **Info**: Normal operational messages

### Standard Exception Mapping

Convert Python exceptions to error codes:

```python
from gleitzeit_v4.core.errors import error_to_jsonrpc

try:
    # Some operation
    result = process_data(invalid_input)
except Exception as e:
    # Automatically maps to appropriate error code
    jsonrpc_error = error_to_jsonrpc(e)
    # ValueError -> INVALID_PARAMS
    # TimeoutError -> TASK_TIMEOUT
    # ConnectionError -> CONNECTION_REFUSED
    # etc.
```

## Integration Examples

### In Providers

```python
class MyProvider(ProtocolProvider):
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        try:
            if method not in self.supported_methods:
                raise GleitzeitError(
                    message=f"Method {method} not supported",
                    code=ErrorCode.METHOD_NOT_SUPPORTED,
                    data={"supported_methods": self.supported_methods}
                )
            
            result = await self.execute_method(method, params)
            return result
            
        except TimeoutError as e:
            raise ProviderTimeoutError(
                provider_id=self.provider_id,
                timeout=self.timeout,
                cause=e
            )
```

### In Execution Engine

```python
async def execute_task(self, task: Task) -> TaskResult:
    try:
        # Validate task
        validation_errors = self.validate_task(task)
        if validation_errors:
            raise TaskValidationError(task.id, validation_errors)
        
        # Execute with timeout
        result = await asyncio.wait_for(
            self.route_to_provider(task),
            timeout=task.timeout
        )
        
        return TaskResult(
            task_id=task.id,
            status=TaskStatus.COMPLETED,
            result=result
        )
        
    except asyncio.TimeoutError as e:
        raise TaskTimeoutError(task.id, task.timeout, cause=e)
    
    except ProviderError as e:
        # Provider errors are already structured
        raise
    
    except Exception as e:
        # Wrap unexpected errors
        raise TaskError(
            message=f"Task execution failed: {e}",
            code=ErrorCode.TASK_EXECUTION_FAILED,
            task_id=task.id,
            cause=e
        )
```

### In API Responses

```python
@app.exception_handler(GleitzeitError)
async def handle_gleitzeit_error(request: Request, exc: GleitzeitError):
    return JSONResponse(
        status_code=determine_http_status(exc.code),
        content={
            "jsonrpc": "2.0",
            "error": exc.to_error_detail().to_jsonrpc_error(),
            "id": request.headers.get("X-Request-ID")
        }
    )
```

## Monitoring Integration

```python
# Prometheus metrics
error_counter = Counter(
    'gleitzeit_errors_total',
    'Total number of errors',
    ['error_code', 'severity', 'component']
)

# Track errors
def track_error(error: GleitzeitError, component: str):
    severity = get_error_severity(error)
    error_counter.labels(
        error_code=error.code.name,
        severity=severity,
        component=component
    ).inc()
    
    # Log with appropriate level
    if severity == "critical":
        logger.critical(f"{component}: {error}")
    elif severity == "error":
        logger.error(f"{component}: {error}")
    elif severity == "warning":
        logger.warning(f"{component}: {error}")
    else:
        logger.info(f"{component}: {error}")
```

## Best Practices

1. **Always use specific error types** when available instead of generic `GleitzeitError`
2. **Include relevant context** in the error data field
3. **Chain errors** to preserve the full error context
4. **Check retryability** before scheduling retries
5. **Use appropriate severity** for monitoring and alerting
6. **Map standard exceptions** to error codes for consistency
7. **Include error codes in logs** for easier debugging
8. **Return JSON-RPC format** for API responses

## Error Recovery Strategies

### Automatic Retry

```python
async def execute_with_retry(task: Task, max_attempts: int = 3):
    for attempt in range(max_attempts):
        try:
            return await execute_task(task)
        except GleitzeitError as e:
            if not is_retryable_error(e) or attempt == max_attempts - 1:
                raise
            
            # Exponential backoff
            delay = 2 ** attempt
            await asyncio.sleep(delay)
```

### Circuit Breaker

```python
class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.is_open = False
        
    async def call(self, func, *args, **kwargs):
        if self.is_open:
            raise ProviderError(
                "Circuit breaker is open",
                code=ErrorCode.PROVIDER_NOT_AVAILABLE
            )
        
        try:
            result = await func(*args, **kwargs)
            self.failure_count = 0  # Reset on success
            return result
            
        except GleitzeitError as e:
            if get_error_severity(e) == "critical":
                self.failure_count += 1
                
                if self.failure_count >= self.failure_threshold:
                    self.is_open = True
                    logger.error(f"Circuit breaker opened after {self.failure_count} failures")
            
            raise
```

## Testing Errors

```python
import pytest
from gleitzeit_v4.core.errors import TaskTimeoutError, is_retryable_error

def test_task_timeout_is_retryable():
    error = TaskTimeoutError("task-123", timeout=30.0)
    assert is_retryable_error(error)
    assert error.code == ErrorCode.TASK_TIMEOUT
    assert error.data["timeout_seconds"] == 30.0

def test_error_chaining():
    cause = ConnectionError("Database connection failed")
    error = PersistenceConnectionError(
        backend="PostgreSQL",
        connection_string="postgres://localhost/db",
        cause=cause
    )
    
    assert error.data["cause"] == str(cause)
    assert error.data["cause_type"] == "ConnectionError"
```

## Summary

The centralized error system provides a robust foundation for error handling across Gleitzeit V4:

- **Consistency**: All errors follow the same structure and coding scheme
- **Interoperability**: JSON-RPC 2.0 compliance ensures compatibility
- **Observability**: Built-in severity and retry detection aids monitoring
- **Debuggability**: Error chaining preserves full context
- **Type Safety**: Specific error classes prevent mistakes
- **Automation**: Utilities enable automatic retry and recovery logic

By using this system consistently, Gleitzeit V4 maintains high reliability and provides excellent debugging capabilities for both development and production environments.