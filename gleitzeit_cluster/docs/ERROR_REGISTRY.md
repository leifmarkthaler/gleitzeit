# Gleitzeit Error Registry

A comprehensive, centralized error management system for the entire Gleitzeit project, providing structured error definitions, user-friendly messages, resolution hints, and automated error handling.

## Overview

The error registry system provides:

- **📋 Centralized Error Catalog**: All errors defined in one place with consistent structure
- **🏷️ Structured Error Codes**: Unique codes (GZ####) for each error type
- **🎯 Domain Organization**: Errors grouped by system component
- **📖 User-Friendly Messages**: Clear, actionable error messages for users
- **🔧 Resolution Hints**: Built-in troubleshooting guidance
- **🔄 Retry Logic**: Intelligent retry behavior based on error category
- **🔍 Search & Discovery**: CLI tools for exploring and understanding errors

## Architecture

### Error Structure

```python
@dataclass
class ErrorDefinition:
    code: ErrorCode           # Unique error code (e.g., GZ1001)
    domain: ErrorDomain       # System component (infrastructure, execution, etc.)
    message: str             # Technical error message
    category: ErrorCategory  # Retry behavior (transient, permanent, etc.)
    severity: ErrorSeverity  # Impact level (low, medium, high, critical)
    user_message: str        # User-friendly message
    resolution_hint: str     # Troubleshooting guidance
    documentation_url: str   # Link to detailed documentation
    retry_after: int        # Recommended retry delay (seconds)
    tags: List[str]         # Search and filtering tags
    related_errors: List[ErrorCode]  # Related error codes
```

### Error Domains

| Domain | Description | Error Range | Examples |
|--------|-------------|-------------|----------|
| **Infrastructure** | Core services (Redis, Socket.IO, cluster) | GZ1000-1999 | Connection failures, service startup |
| **Execution** | Task execution (Ollama, Python, HTTP) | GZ2000-2999 | Model not found, function errors |
| **Workflow** | Workflow orchestration and validation | GZ3000-3999 | Circular dependencies, batch processing |
| **Authentication** | Users, API keys, permissions | GZ4000-4999 | Token expired, insufficient permissions |
| **Storage** | Files, data persistence, caching | GZ5000-5999 | File not found, disk space |
| **Network** | Network connectivity, HTTP requests | GZ6000-6999 | Connection timeouts, DNS failures |
| **Validation** | Input validation, schema validation | GZ7000-7999 | Invalid parameters, format errors |
| **System** | OS-level, resources, dependencies | GZ8000-8999 | Memory exhaustion, missing deps |
| **CLI** | Command-line interface errors | GZ9000-9499 | Invalid commands, auth required |
| **Monitoring** | Observability, metrics, health checks | GZ9500-9999 | Health check failures, telemetry |

## Usage Examples

### Creating Structured Errors

```python
from gleitzeit_cluster.core.errors import GleitzeitError, ErrorCode

# Generic error with context
raise GleitzeitError(
    ErrorCode.OLLAMA_MODEL_NOT_FOUND,
    context={"model_name": "llama3", "available_models": ["mistral", "codellama"]}
)

# Convenience exceptions
from gleitzeit_cluster.core.errors import OllamaModelNotFoundError
raise OllamaModelNotFoundError("llama3", context={"endpoint": "gpu-server"})
```

### Error Handling with Retry Logic

```python
try:
    result = await some_operation()
except GleitzeitError as e:
    if e.should_retry:
        await asyncio.sleep(e.retry_after_seconds or 1)
        # Retry the operation
    else:
        # Log and handle permanent error
        logger.error(f"Permanent error: {e.user_friendly_message}")
        if e.resolution_hint:
            logger.info(f"Resolution: {e.resolution_hint}")
```

### Integration with Existing Error Handling

```python
# Convert to ErrorInfo for compatibility
error_info = gleitzeit_error.to_error_info()
retry_manager.handle_error(error_info)

# Serialize for APIs/logging
error_dict = gleitzeit_error.to_dict()
```

## CLI Tools

### List All Errors
```bash
# List all errors
gleitzeit errors list

# Filter by domain
gleitzeit errors list --domain infrastructure

# Filter by severity
gleitzeit errors list --severity high

# Show detailed information
gleitzeit errors list --details --format table
```

### Search Errors
```bash
# Search by keyword
gleitzeit errors search "redis"
gleitzeit errors search "connection"

# Different output formats
gleitzeit errors search "ollama" --format json
```

### Show Specific Error
```bash
# Show error details
gleitzeit errors show GZ1001

# JSON format
gleitzeit errors show GZ2011 --format json
```

### Error Statistics
```bash
# Show catalog statistics
gleitzeit errors stats

# JSON format for analysis
gleitzeit errors stats --format json
```

### Validation
```bash
# Validate error catalog consistency
gleitzeit errors validate
```

## Current Error Catalog

### Infrastructure Errors (GZ1000-1999)

| Code | Message | Severity | Category |
|------|---------|----------|----------|
| GZ1001 | Failed to establish connection to Redis server | Medium | Transient |
| GZ1002 | Redis operation timed out | Medium | Transient |
| GZ1010 | Failed to establish Socket.IO connection | Medium | Transient |
| GZ1011 | Failed to start Socket.IO server | High | Permanent |
| GZ1020 | Failed to start required service | High | Permanent |
| GZ1030 | Cluster initialization failed | Critical | Permanent |

### Execution Errors (GZ2000-2999)

| Code | Message | Severity | Category |
|------|---------|----------|----------|
| GZ2001 | Task execution encountered an error | Medium | Transient |
| GZ2010 | Cannot connect to Ollama server | High | Transient |
| GZ2011 | Requested Ollama model is not available | High | Permanent |
| GZ2020 | Python function not found in registry | Medium | Permanent |
| GZ2031 | Image file not found for vision task | Medium | Permanent |

### Workflow Errors (GZ3000-3999)

| Code | Message | Severity | Category |
|------|---------|----------|----------|
| GZ3002 | Workflow not found | Medium | Permanent |
| GZ3003 | Workflow contains circular task dependencies | High | Validation |
| GZ3020 | Batch processing operation failed | Medium | Transient |

### Authentication Errors (GZ4000-4999)

| Code | Message | Severity | Category |
|------|---------|----------|----------|
| GZ4002 | Authentication token has expired | Medium | Authentication |
| GZ4010 | API key is invalid or malformed | Medium | Authentication |
| GZ4021 | Insufficient permissions for requested operation | Medium | Authentication |

### Storage Errors (GZ5000-5999)

| Code | Message | Severity | Category |
|------|---------|----------|----------|
| GZ5001 | Requested file does not exist | Medium | Permanent |
| GZ5004 | Insufficient disk space for operation | High | Resource |

### Other Domains

- **Network Errors (GZ6000-6999)**: 1 error defined
- **Validation Errors (GZ7000-7999)**: 1 error defined
- **System Errors (GZ8000-8999)**: 1 error defined
- **CLI Errors (GZ9000-9499)**: 2 errors defined
- **Monitoring Errors (GZ9500-9999)**: 1 error defined

## Benefits

### For Developers
- **Consistent Error Handling**: All errors follow the same structure
- **Type Safety**: Enum-based error codes prevent typos
- **IDE Support**: Full autocomplete and refactoring support
- **Comprehensive Context**: Rich error information for debugging

### For Users
- **Clear Error Messages**: User-friendly explanations of what went wrong
- **Actionable Guidance**: Built-in resolution hints for common issues
- **Consistent Experience**: All errors formatted the same way

### For Operations
- **Structured Logging**: All errors contain structured metadata
- **Error Analytics**: Track error patterns and frequency
- **Documentation Integration**: Links to detailed troubleshooting guides
- **Intelligent Retry**: Automatic retry behavior based on error classification

### For Maintenance
- **Centralized Management**: All errors defined in one place
- **Easy Updates**: Change error messages/hints without code changes
- **Validation**: Built-in consistency checking
- **Search & Discovery**: Easy to find and understand all possible errors

## Extension Guidelines

### Adding New Errors

1. **Choose appropriate domain and code range**
2. **Provide comprehensive metadata**:
   - Clear technical and user messages
   - Appropriate severity and category
   - Helpful resolution hints
   - Relevant tags for search

3. **Add to error catalog**:
```python
ErrorCode.NEW_ERROR_CODE: ErrorDefinition(
    code=ErrorCode.NEW_ERROR_CODE,
    domain=ErrorDomain.APPROPRIATE_DOMAIN,
    message="Technical error description",
    category=ErrorCategory.APPROPRIATE_CATEGORY,
    severity=ErrorSeverity.APPROPRIATE_LEVEL,
    user_message="User-friendly explanation",
    resolution_hint="Steps to resolve the issue",
    documentation_url="https://docs.gleitzeit.dev/errors/...",
    tags=["relevant", "search", "tags"]
)
```

4. **Create convenience exception if commonly used**:
```python
class SpecificError(GleitzeitError):
    def __init__(self, context: Optional[Dict] = None, cause: Optional[Exception] = None):
        super().__init__(ErrorCode.NEW_ERROR_CODE, context, cause)
```

### Best Practices

- **Be Specific**: Avoid generic error messages
- **User-First**: Write error messages users can understand and act on
- **Provide Context**: Include relevant information in error context
- **Link Documentation**: Add documentation URLs for complex errors
- **Test Thoroughly**: Validate error behavior in different scenarios
- **Keep Updated**: Review and update error messages based on user feedback

## Integration Points

The error registry integrates with:

- **Core Cluster**: Structured error handling throughout cluster operations
- **Task Execution**: Standardized errors for all task types
- **Authentication**: Consistent auth error handling
- **CLI Tools**: User-friendly error display and management
- **Logging System**: Structured error information for analysis
- **Retry Logic**: Intelligent retry behavior based on error classification
- **Documentation**: Automatic error reference generation

## Statistics

- **Total Errors**: 25 defined across all domains
- **Coverage**: All major system components covered
- **User Experience**: 100% of errors have user-friendly messages
- **Resolution Guidance**: 100% of errors have resolution hints
- **Documentation**: Core errors have detailed documentation links
- **Validation**: Automatic consistency checking prevents catalog issues

The comprehensive error registry makes Gleitzeit more robust, user-friendly, and maintainable by providing a structured approach to error handling across the entire system.