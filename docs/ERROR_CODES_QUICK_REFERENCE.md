# Error Codes Quick Reference

## Most Common Errors

| Code | Name | Common Cause | Quick Fix |
|------|------|--------------|-----------|
| -32602 | INVALID_PARAMS | Wrong or missing parameters | Check required params in docs |
| -30002 | PROVIDER_NOT_FOUND | Provider not registered | Check provider ID spelling |
| -30003 | PROVIDER_NOT_AVAILABLE | Service down or unreachable | Start provider service |
| -30008 | METHOD_NOT_SUPPORTED | Method doesn't exist | Check supported methods list |
| -29001 | TASK_VALIDATION_FAILED | Invalid task definition | Fix task YAML/JSON |
| -29003 | TASK_TIMEOUT | Task exceeded time limit | Increase timeout value |
| -28001 | WORKFLOW_VALIDATION_FAILED | Invalid workflow | Check workflow structure |
| -31003 | CONFIGURATION_ERROR | Bad config or file format | Fix configuration |

## Complete Error Code List

### JSON-RPC Standard (-32768 to -32000)
```
-32700  PARSE_ERROR              Invalid JSON
-32600  INVALID_REQUEST          Invalid request format  
-32601  METHOD_NOT_FOUND         Method doesn't exist
-32602  INVALID_PARAMS           Invalid parameters
-32603  INTERNAL_ERROR           Internal error
```

### System Errors (-31999 to -31000)
```
-31001  SYSTEM_NOT_INITIALIZED   System not ready
-31002  SYSTEM_SHUTDOWN          System shutting down
-31003  CONFIGURATION_ERROR      Configuration problem
-31004  RESOURCE_EXHAUSTED       Out of resources
-31005  RATE_LIMIT_EXCEEDED      Too many requests
```

### Provider/Protocol Errors (-30999 to -30000)
```
-30001  PROTOCOL_NOT_FOUND           Protocol not registered
-30002  PROVIDER_NOT_FOUND           Provider not found
-30003  PROVIDER_NOT_AVAILABLE       Provider unavailable
-30004  PROVIDER_INITIALIZATION_FAILED  Provider init failed
-30005  PROVIDER_UNHEALTHY           Provider unhealthy
-30006  PROVIDER_TIMEOUT             Provider timed out
-30007  PROVIDER_OVERLOADED          Provider overloaded
-30008  METHOD_NOT_SUPPORTED         Method not supported
-30009  PROTOCOL_VERSION_MISMATCH    Version mismatch
```

### Task Errors (-29999 to -29000)
```
-29001  TASK_VALIDATION_FAILED   Task validation failed
-29002  TASK_EXECUTION_FAILED    Task execution failed
-29003  TASK_TIMEOUT             Task timed out
-29004  TASK_CANCELLED           Task was cancelled
-29005  TASK_DEPENDENCY_FAILED   Dependencies failed
-29006  TASK_PARAMETER_ERROR     Parameter error
-29007  TASK_RESULT_INVALID      Invalid result
-29008  TASK_RETRY_EXHAUSTED     Max retries reached
-29009  TASK_NOT_FOUND           Task not found
```

### Workflow Errors (-28999 to -28000)
```
-28001  WORKFLOW_VALIDATION_FAILED   Workflow validation failed
-28002  WORKFLOW_NOT_FOUND           Workflow not found
-28003  WORKFLOW_EXECUTION_FAILED    Workflow execution failed
-28004  WORKFLOW_TIMEOUT             Workflow timed out
-28005  WORKFLOW_CANCELLED           Workflow cancelled
-28006  WORKFLOW_CIRCULAR_DEPENDENCY Circular dependency
-28007  WORKFLOW_INVALID_STATE       Invalid state
```

### Queue/Scheduling Errors (-27999 to -27000)
```
-27001  QUEUE_NOT_FOUND          Queue doesn't exist
-27002  QUEUE_FULL               Queue at capacity
-27003  QUEUE_EMPTY              Queue is empty
-27004  SCHEDULING_FAILED        Scheduling failed
-27005  SCHEDULER_NOT_RUNNING    Scheduler not running
```

### Persistence Errors (-26999 to -26000)
```
-26001  PERSISTENCE_CONNECTION_FAILED  Can't connect to DB
-26002  PERSISTENCE_WRITE_FAILED       Write failed
-26003  PERSISTENCE_READ_FAILED        Read failed
-26004  PERSISTENCE_TRANSACTION_FAILED Transaction failed
-26005  PERSISTENCE_INTEGRITY_ERROR    Data integrity error
```

### Network Errors (-25999 to -25000)
```
-25001  NETWORK_UNREACHABLE      Network unreachable
-25002  CONNECTION_REFUSED       Connection refused
-25003  CONNECTION_TIMEOUT       Connection timed out
-25004  CONNECTION_LOST          Connection lost
-25005  AUTHENTICATION_FAILED    Auth failed
-25006  AUTHORIZATION_FAILED     Not authorized
```

## Error Patterns

### Retryable Errors
These errors can be retried with backoff:
- PROVIDER_TIMEOUT (-30006)
- PROVIDER_OVERLOADED (-30007)
- TASK_TIMEOUT (-29003)
- CONNECTION_TIMEOUT (-25003)
- CONNECTION_LOST (-25004)
- NETWORK_UNREACHABLE (-25001)
- RESOURCE_EXHAUSTED (-31004)
- RATE_LIMIT_EXCEEDED (-31005)
- PERSISTENCE_CONNECTION_FAILED (-26001)

### Non-Retryable Errors
Don't retry these:
- INVALID_PARAMS (-32602)
- METHOD_NOT_FOUND (-32601)
- METHOD_NOT_SUPPORTED (-30008)
- TASK_VALIDATION_FAILED (-29001)
- WORKFLOW_VALIDATION_FAILED (-28001)
- CONFIGURATION_ERROR (-31003)
- AUTHENTICATION_FAILED (-25005)
- AUTHORIZATION_FAILED (-25006)

## Example Error Handling

### Python
```python
from gleitzeit.core.errors import ErrorCode, GleitzeitError

try:
    result = await client.execute(task)
except GleitzeitError as e:
    match e.code:
        case ErrorCode.PROVIDER_TIMEOUT:
            # Retry with longer timeout
            pass
        case ErrorCode.INVALID_PARAMS:
            # Fix parameters
            pass
        case ErrorCode.PROVIDER_NOT_AVAILABLE:
            # Use fallback provider
            pass
        case _:
            # Log and re-raise
            logger.error(f"Error {e.code}: {e.message}")
            raise
```

### CLI
```bash
# Enable debug mode for more details
gleitzeit --debug run workflow.yaml

# Common fixes
gleitzeit status                    # Check system status
gleitzeit config                    # Verify configuration
gleitzeit init python my_workflow    # Create template
```

## Debug Tips

1. **Enable debug mode**: Shows full error details
2. **Check error code**: Identifies exact problem
3. **Review error data**: Contains context info
4. **Check logs**: May have additional details
5. **Test in isolation**: Simplify to find issue

## Need Help?

- Full documentation: [ERROR_REFERENCE.md](./ERROR_REFERENCE.md)
- GitHub Issues: https://github.com/gleitzeit/gleitzeit/issues
- Include error code + message when reporting