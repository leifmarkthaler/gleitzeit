# Error System Documentation

## Overview

Gleitzeit implements a centralized, hierarchical error system that provides structured error handling for protocols, providers, and all system components. The error system is JSON-RPC 2.0 compliant and supports rich error context for debugging and monitoring.

## Architecture

### Error Hierarchy

```
GleitzeitError (Base)
├── SystemError
│   ├── ConfigurationError
│   ├── ResourceExhaustedError
│   └── SystemManagerError
├── ProviderError
│   ├── ProviderNotFoundError
│   ├── ProviderTimeoutError
│   ├── MethodNotSupportedError
│   └── ProviderNotAvailableError
├── ProtocolError
├── TaskError
│   ├── TaskValidationError
│   ├── TaskTimeoutError
│   ├── TaskExecutionError
│   └── TaskDependencyError
├── WorkflowError
│   ├── WorkflowValidationError
│   └── WorkflowCircularDependencyError
└── Other domain-specific errors...
```

### Error Code Ranges

The system uses standardized error codes following JSON-RPC 2.0 specification with custom extensions:

- `-32768` to `-32000`: Reserved for JSON-RPC protocol errors
- `-31999` to `-31000`: Gleitzeit system errors
- `-30999` to `-30000`: Provider and protocol errors
- `-29999` to `-29000`: Task execution errors
- `-28999` to `-28000`: Workflow errors
- `-27999` to `-27000`: Queue and scheduling errors
- `-26999` to `-26000`: Persistence errors
- `-25999` to `-25000`: Network and communication errors

## Protocol Error Implementation

### Base Protocol Error

```python
from gleitzeit.core.errors import ProtocolError, ErrorCode

class ProtocolError(GleitzeitError):
    """Protocol-related errors"""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.PROTOCOL_NOT_FOUND,
        protocol_id: Optional[str] = None,
        **kwargs
    ):
        data = kwargs.pop("data", {})
        if protocol_id:
            data["protocol_id"] = protocol_id
        super().__init__(message, code, data=data, **kwargs)
```

### Protocol Error Codes

- `PROTOCOL_NOT_FOUND (-30001)`: Protocol specification not found
- `PROTOCOL_VERSION_MISMATCH (-30009)`: Protocol version incompatibility
- `METHOD_NOT_FOUND (-32601)`: Method not defined in protocol

### Usage Example

```python
from gleitzeit.core.errors import ProtocolError, ErrorCode

# Basic protocol error
raise ProtocolError(
    f"Protocol not found: {protocol_id}",
    code=ErrorCode.PROTOCOL_NOT_FOUND,
    protocol_id=protocol_id
)

# Protocol validation error with context
raise ProtocolError(
    f"Method '{method}' not found in protocol '{protocol_id}'",
    code=ErrorCode.METHOD_NOT_FOUND,
    protocol_id=protocol_id,
    data={"method": method, "available_methods": available_methods}
)
```

## Provider Error Implementation

### Base Provider Error

```python
class ProviderError(GleitzeitError):
    """Provider-related errors"""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.PROVIDER_NOT_AVAILABLE,
        provider_id: Optional[str] = None,
        **kwargs
    ):
        data = kwargs.pop("data", {})
        if provider_id:
            data["provider_id"] = provider_id
        super().__init__(message, code, data=data, **kwargs)
```

### Provider Error Types

#### ProviderNotFoundError
```python
class ProviderNotFoundError(ProviderError):
    def __init__(self, provider_id: str, **kwargs):
        super().__init__(
            f"Provider not found: {provider_id}",
            ErrorCode.PROVIDER_NOT_FOUND,
            provider_id=provider_id,
            **kwargs
        )
```

#### ProviderTimeoutError
```python
class ProviderTimeoutError(ProviderError):
    def __init__(self, provider_id: str, timeout: float, **kwargs):
        data = kwargs.pop("data", {})
        data["timeout_seconds"] = timeout
        super().__init__(
            f"Provider {provider_id} timed out after {timeout}s",
            ErrorCode.PROVIDER_TIMEOUT,
            provider_id=provider_id,
            data=data,
            **kwargs
        )
```

#### MethodNotSupportedError
```python
class MethodNotSupportedError(ProviderError):
    def __init__(self, method: str, provider_id: str, **kwargs):
        super().__init__(
            f"Method '{method}' not supported by provider '{provider_id}'",
            ErrorCode.METHOD_NOT_SUPPORTED,
            provider_id=provider_id,
            **kwargs
        )
```

#### ProviderNotAvailableError
```python
class ProviderNotAvailableError(ProviderError):
    def __init__(self, provider_id: str, reason: Optional[str] = None, **kwargs):
        message = f"Provider '{provider_id}' is not available"
        if reason:
            message += f": {reason}"
        super().__init__(
            message,
            ErrorCode.PROVIDER_NOT_AVAILABLE,
            provider_id=provider_id,
            **kwargs
        )
```

### Provider Error Codes

- `PROVIDER_NOT_FOUND (-30002)`: Provider not registered
- `PROVIDER_NOT_AVAILABLE (-30003)`: Provider exists but unavailable
- `PROVIDER_INITIALIZATION_FAILED (-30004)`: Provider failed to initialize
- `PROVIDER_UNHEALTHY (-30005)`: Provider health check failed
- `PROVIDER_TIMEOUT (-30006)`: Provider operation timed out
- `PROVIDER_OVERLOADED (-30007)`: Provider at capacity
- `METHOD_NOT_SUPPORTED (-30008)`: Method not implemented by provider
- `PROVIDER_ERROR (-30010)`: Generic provider error

## Error Features

### 1. Structured Error Data

All errors support additional context through the `data` dictionary:

```python
raise ProviderTimeoutError(
    provider_id="llm-provider",
    timeout=30.0,
    data={
        "request_id": "abc123",
        "method": "generate",
        "queue_size": 100
    }
)
```

### 2. Cause Tracking

Errors can wrap underlying exceptions:

```python
try:
    response = await external_api.call()
except ConnectionError as e:
    raise ProviderNotAvailableError(
        provider_id="api-provider",
        reason="Connection failed",
        cause=e  # Original exception preserved
    )
```

### 3. JSON-RPC 2.0 Compliance

Errors convert to JSON-RPC format:

```python
error = ProviderTimeoutError("provider-1", 30.0)
jsonrpc_error = error.to_error_detail().to_jsonrpc_error()
# Returns:
# {
#     "code": -30006,
#     "message": "Provider provider-1 timed out after 30.0s",
#     "data": {"provider_id": "provider-1", "timeout_seconds": 30.0}
# }
```

### 4. Rich Context for Debugging

```python
error = ProviderError("Operation failed", provider_id="test-provider")
context = error.to_context_dict()
# Returns comprehensive error information:
# {
#     "code": -30003,
#     "code_name": "PROVIDER_NOT_AVAILABLE",
#     "message": "Operation failed",
#     "type": "ProviderError",
#     "data": {"provider_id": "test-provider"},
#     "traceback": "...",
#     "cause": {...}  # If cause exists
# }
```

### 5. Error Retryability

The system can determine if errors should be retried:

```python
from gleitzeit.core.errors import is_retryable_error

error = ProviderTimeoutError("provider-1", 30.0)
if is_retryable_error(error):
    # Retry the operation
    pass

# Retryable error codes include:
# - PROVIDER_TIMEOUT
# - PROVIDER_OVERLOADED
# - CONNECTION_TIMEOUT
# - NETWORK_UNREACHABLE
# - RESOURCE_EXHAUSTED
```

### 6. Error Severity Classification

```python
from gleitzeit.core.errors import get_error_severity

severity = get_error_severity(error)
# Returns: 'critical', 'error', 'warning', or 'info'

# Critical: SYSTEM_SHUTDOWN, AUTHENTICATION_FAILED
# Warning: QUEUE_FULL, RATE_LIMIT_EXCEEDED, PROVIDER_OVERLOADED
# Error: Most other errors
```

## Best Practices

### 1. Use Specific Error Types

```python
# Good - Specific error type with context
raise ProviderTimeoutError(
    provider_id="llm-provider",
    timeout=30.0
)

# Avoid - Generic error
raise Exception("Provider timed out")
```

### 2. Include Relevant Context

```python
# Good - Rich context for debugging
raise MethodNotSupportedError(
    method="custom_method",
    provider_id="my-provider",
    data={
        "supported_methods": ["method1", "method2"],
        "protocol_version": "v1.0"
    }
)
```

### 3. Preserve Original Exceptions

```python
try:
    result = await provider.execute()
except Exception as e:
    # Preserve the original exception
    raise ProviderError(
        "Execution failed",
        provider_id=provider.id,
        cause=e
    )
```

### 4. Use Error Codes Consistently

```python
# Use predefined error codes
from gleitzeit.core.errors import ErrorCode

raise ProviderError(
    "Provider overloaded",
    code=ErrorCode.PROVIDER_OVERLOADED,
    provider_id="worker-1"
)
```

## Custom Provider Error Example

Providers can define domain-specific errors while maintaining consistency:

```python
from gleitzeit.core.errors import ProviderError, ErrorCode

class TokenLimitError(ProviderError):
    """LLM token limit exceeded"""

    def __init__(self, provider_id: str, tokens: int, limit: int, **kwargs):
        data = kwargs.pop("data", {})
        data.update({
            "tokens_requested": tokens,
            "token_limit": limit,
            "exceeded_by": tokens - limit
        })
        super().__init__(
            f"Token limit exceeded: {tokens} > {limit}",
            code=ErrorCode.RESOURCE_EXHAUSTED,
            provider_id=provider_id,
            data=data,
            **kwargs
        )

# Usage
raise TokenLimitError(
    provider_id="gpt-provider",
    tokens=5000,
    limit=4096
)
```

## Error Handling in Providers

```python
class MyProvider(ProtocolProvider):
    async def execute(self, method: str, params: Dict[str, Any]) -> Any:
        try:
            # Validate method support
            if method not in self.supported_methods:
                raise MethodNotSupportedError(
                    method=method,
                    provider_id=self.provider_id
                )

            # Execute with timeout
            try:
                result = await asyncio.wait_for(
                    self._execute_internal(method, params),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                raise ProviderTimeoutError(
                    provider_id=self.provider_id,
                    timeout=self.timeout
                )

            return result

        except GleitzeitError:
            # Re-raise Gleitzeit errors
            raise
        except Exception as e:
            # Wrap unexpected errors
            raise ProviderError(
                f"Unexpected error in {self.provider_id}",
                provider_id=self.provider_id,
                cause=e
            )
```

## Error Propagation

Errors propagate through the system maintaining context:

1. **Provider** raises specific error
2. **Task Executor** catches and may retry based on `is_retryable_error()`
3. **Workflow Manager** logs error with full context
4. **API** converts to JSON-RPC error response
5. **Client** receives structured error information

## Monitoring and Logging

The error system integrates with monitoring:

```python
# Errors automatically include:
# - Timestamp (via created_at in base class)
# - Error code and name
# - Full traceback
# - Cause chain
# - Custom data fields

# Example log entry:
logger.error(
    "Provider operation failed",
    extra={
        "error_code": error.code.value,
        "error_name": error.code.name,
        "provider_id": error.data.get("provider_id"),
        "traceback": error.to_json_string()
    }
)
```

## Testing Errors

```python
import pytest
from gleitzeit.core.errors import (
    ProviderTimeoutError,
    is_retryable_error,
    ErrorCode
)

def test_provider_timeout_error():
    error = ProviderTimeoutError("test-provider", 30.0)

    assert error.code == ErrorCode.PROVIDER_TIMEOUT
    assert error.data["timeout_seconds"] == 30.0
    assert is_retryable_error(error)

    jsonrpc = error.to_error_detail().to_jsonrpc_error()
    assert jsonrpc["code"] == ErrorCode.PROVIDER_TIMEOUT.value
```

## Error Discovery

The system includes error discovery functionality to introspect and retrieve custom errors from protocols and providers at runtime.

### Error Discovery Module

```python
from gleitzeit.core.error_discovery import (
    ErrorDiscovery, ErrorInfo,
    get_provider_errors, get_protocol_errors,
    get_error_hierarchy, discover_all_errors
)
```

### Key Features

#### 1. Provider Error Discovery

Retrieve all errors a provider might raise, including custom errors:

```python
from gleitzeit.providers.python_provider import PythonProvider

provider = PythonProvider(
    provider_id="my-provider",
    protocol_id="python/v1"
)

# Get all errors for this provider
errors = get_provider_errors(provider)

for error in errors:
    print(f"Error: {error.name}")
    print(f"  Code: {error.error_code.name if error.error_code else 'N/A'}")
    print(f"  Retryable: {error.is_retryable}")
    print(f"  Module: {error.module}")
```

##### Custom Provider Errors

The error discovery system automatically finds custom errors defined in your providers:

```python
from gleitzeit.core.errors import ProviderError, ErrorCode
from gleitzeit.providers.simple import SimpleProvider

# Define custom errors for your provider
class DataValidationError(ProviderError):
    """Custom error for data validation failures"""
    def __init__(self, field: str, reason: str, **kwargs):
        super().__init__(
            f"Data validation failed for {field}: {reason}",
            code=ErrorCode.TASK_VALIDATION_FAILED,
            data={"field": field, "reason": reason},
            **kwargs
        )

class RateLimitError(ProviderError):
    """Custom error when rate limit is exceeded"""
    def __init__(self, limit: int, window: str, **kwargs):
        super().__init__(
            f"Rate limit exceeded: {limit} requests per {window}",
            code=ErrorCode.RATE_LIMIT_EXCEEDED,
            data={"limit": limit, "window": window},
            **kwargs
        )

class CustomProvider(SimpleProvider):
    """Provider with custom errors"""

    async def execute(self, method: str, params: dict):
        if self.rate_limit_exceeded():
            raise RateLimitError(100, "minute")

        if not self.validate_data(params):
            raise DataValidationError("input", "invalid format")

        return {"status": "success"}

# Discover all errors including custom ones
provider = CustomProvider(provider_id="custom", protocol_id="custom/v1")
errors = get_provider_errors(provider)

# Separate custom from base errors
for error in errors:
    if error.name in ["DataValidationError", "RateLimitError"]:
        print(f"✓ Custom Error: {error.name}")
        print(f"  Description: {error.description}")
        print(f"  Error Code: {error.error_code.name}")
    else:
        print(f"• Base Error: {error.name}")
```

The discovery system will find:
- **Custom errors** defined in the provider's module
- **Base errors** inherited from ProviderError
- **Errors raised** in the provider's methods (via AST analysis)

#### 2. Protocol Error Discovery

Retrieve errors associated with a protocol:

```python
from gleitzeit.core.protocol import ProtocolSpec

protocol = ProtocolSpec(
    name="my-protocol",
    version="v1",
    methods={...}
)

# Get protocol-related errors
errors = get_protocol_errors(protocol)
```

#### 3. Error Hierarchy Visualization

Get the complete error hierarchy:

```python
hierarchy = get_error_hierarchy()

# Returns nested dictionary structure:
# {
#     "class": "GleitzeitError",
#     "module": "gleitzeit.core.errors",
#     "description": "Base exception for all Gleitzeit errors",
#     "subclasses": {
#         "ProviderError": {...},
#         "ProtocolError": {...},
#         "TaskError": {...},
#         ...
#     }
# }
```

#### 4. System-Wide Error Discovery

Discover all errors across all providers:

```python
all_errors = discover_all_errors()

# Returns dict mapping module names to error lists
for module_name, errors in all_errors.items():
    print(f"Module {module_name}: {len(errors)} errors")
```

### ErrorInfo Structure

Each discovered error is represented as an `ErrorInfo` object:

```python
@dataclass
class ErrorInfo:
    name: str                          # Error class name
    error_class: Type[Exception]       # The error class itself
    base_class: Type[Exception]        # Parent error class
    module: str                        # Module containing the error
    error_code: Optional[ErrorCode]    # Associated error code
    description: Optional[str]         # Error description/docstring
    is_retryable: bool                 # Whether error is retryable
```

### Use Cases

#### 1. API Documentation Generation

Generate API documentation including all possible errors (both base and custom):

```python
def generate_api_docs(provider):
    errors = get_provider_errors(provider)

    # Separate custom from base errors
    custom_errors = [e for e in errors if provider.__module__ in e.module]
    base_errors = [e for e in errors if provider.__module__ not in e.module]

    doc = f"# {provider.name} API\n\n"

    if custom_errors:
        doc += "## Custom Errors\n\n"
        for error in custom_errors:
            doc += f"### {error.name}\n"
            doc += f"- Code: {error.error_code.value if error.error_code else 'N/A'}\n"
            doc += f"- Description: {error.description}\n"
            doc += f"- Retryable: {error.is_retryable}\n\n"

    doc += "## Standard Errors\n\n"
    for error in base_errors:
        doc += f"### {error.name}\n"
        doc += f"- Code: {error.error_code.value if error.error_code else 'N/A'}\n"
        doc += f"- Description: {error.description}\n"
        doc += f"- Retryable: {error.is_retryable}\n\n"

    return doc
```

#### 2. Client Error Handling Setup

Configure client-side error handling based on discovery:

```python
def setup_error_handlers(provider):
    errors = get_provider_errors(provider)

    handlers = {}
    for error in errors:
        if error.is_retryable:
            handlers[error.error_code] = RetryHandler()
        else:
            handlers[error.error_code] = LogAndFailHandler()

    return handlers
```

#### 3. Testing Error Coverage

Ensure all provider errors are tested:

```python
def test_provider_error_coverage(provider):
    errors = get_provider_errors(provider)

    for error in errors:
        # Generate test case for each error
        test_name = f"test_{error.name.lower()}"
        # Verify test exists
        assert hasattr(TestClass, test_name)
```

#### 4. Error Report Generation

Generate formatted error reports:

```python
from gleitzeit.core.error_discovery import ErrorDiscovery

errors = get_provider_errors(provider)
report = ErrorDiscovery.format_error_report(
    errors,
    title=f"Error Report for {provider.name}"
)

print(report)
# Outputs markdown-formatted error report
```

### Integration with Monitoring

The error discovery system can be integrated with monitoring tools:

```python
# Export error metrics
def export_error_metrics(provider):
    errors = get_provider_errors(provider)

    metrics = {
        "total_error_types": len(errors),
        "retryable_errors": sum(1 for e in errors if e.is_retryable),
        "error_codes": [e.error_code.value for e in errors if e.error_code]
    }

    # Send to monitoring system
    monitoring.export_metrics("provider_errors", metrics)
```

## Client and API Integration

The error discovery system is fully integrated with both the Gleitzeit client and API, providing multiple ways to access error information.

### Client Methods

The `GleitzeitClient` includes error discovery methods through the `ErrorDiscoveryMixin`:

```python
from gleitzeit.client import GleitzeitClient

client = GleitzeitClient(base_url="http://localhost:8000")

# Get provider errors
errors = await client.get_provider_errors("python-executor")
for error in errors:
    print(f"{error['name']}: {error['error_code_name']}")
    print(f"  Retryable: {error['is_retryable']}")
    print(f"  Module: {error['module']}")

# Get protocol errors
protocol_errors = await client.get_protocol_errors("python/v1")

# Get complete error hierarchy
hierarchy = await client.get_error_hierarchy()

# Check if an error is retryable
is_retryable = await client.check_error_retryability(-30006)  # PROVIDER_TIMEOUT

# Generate error report
report = await client.get_error_report(provider_id="python-executor")
print(report)  # Markdown-formatted report

# Get errors from all providers
all_errors = await client.get_all_provider_errors()
for provider_id, errors in all_errors.items():
    print(f"{provider_id}: {len(errors)} errors")
```

### API Endpoints

The error discovery system exposes RESTful API endpoints:

#### 1. Get Provider Errors
```bash
GET /errors/provider/{provider_id}

# Example
curl http://localhost:8000/errors/provider/python-executor

# Response
[
  {
    "name": "ProviderTimeoutError",
    "class": "ProviderTimeoutError",
    "base_class": "ProviderError",
    "module": "gleitzeit.core.errors",
    "error_code": -30006,
    "error_code_name": "PROVIDER_TIMEOUT",
    "description": "Provider operation timed out",
    "is_retryable": true
  },
  ...
]
```

#### 2. Get Protocol Errors
```bash
GET /errors/protocol/{protocol_id}

# Example
curl http://localhost:8000/errors/protocol/python/v1

# Response
[
  {
    "name": "ProtocolError",
    "class": "ProtocolError",
    "base_class": "GleitzeitError",
    "module": "gleitzeit.core.errors",
    "error_code": -30001,
    "error_code_name": "PROTOCOL_NOT_FOUND",
    "description": "Base protocol error",
    "is_retryable": false
  },
  ...
]
```

#### 3. Get Error Hierarchy
```bash
GET /errors/hierarchy

# Example
curl http://localhost:8000/errors/hierarchy

# Response
{
  "class": "GleitzeitError",
  "module": "gleitzeit.core.errors",
  "description": "Base exception for all Gleitzeit errors",
  "error_code": -32603,
  "error_code_name": "INTERNAL_ERROR",
  "subclasses": {
    "ProviderError": {
      "class": "ProviderError",
      "module": "gleitzeit.core.errors",
      "error_code": -30003,
      "error_code_name": "PROVIDER_NOT_AVAILABLE",
      "subclasses": {...}
    },
    ...
  }
}
```

#### 4. Get All Provider Errors
```bash
GET /errors/all-providers

# Example
curl http://localhost:8000/errors/all-providers

# Response
{
  "python-executor": [...],
  "shell-executor": [...],
  "ollama-provider": [...]
}
```

#### 5. Generate Error Report
```bash
GET /errors/report?provider_id={provider_id}

# Example - specific provider
curl http://localhost:8000/errors/report?provider_id=python-executor

# Example - all providers
curl http://localhost:8000/errors/report

# Response (Markdown format)
# Error Report for python-executor

## ProviderError Subclasses

### ProviderTimeoutError
*Provider operation timed out*
- Module: `gleitzeit.core.errors`
- Error Code: `PROVIDER_TIMEOUT` (-30006)
- Retryable: True
...
```

#### 6. Check Error Retryability
```bash
GET /errors/retryable/{error_code}

# Example
curl http://localhost:8000/errors/retryable/-30006

# Response
true
```

### Integration with OpenAPI/Swagger

The error discovery endpoints are automatically documented in the API's OpenAPI schema:

```python
# Access API documentation
# http://localhost:8000/docs

# The error discovery endpoints appear under the "error_discovery" tag
# with full request/response schemas
```

### Using Error Discovery in Applications

#### Example: Dynamic Error Handler Setup
```python
async def setup_error_handlers(client: GleitzeitClient, provider_id: str):
    """Set up error handlers based on discovered errors."""
    errors = await client.get_provider_errors(provider_id)

    handlers = {}
    for error in errors:
        if error['is_retryable']:
            handlers[error['error_code']] = RetryHandler(
                max_retries=3,
                backoff=2.0
            )
        else:
            handlers[error['error_code']] = LogAndFailHandler()

    return handlers
```

#### Example: API Client with Error Awareness
```python
class SmartAPIClient:
    def __init__(self, base_url: str):
        self.client = GleitzeitClient(base_url=base_url)
        self.error_handlers = {}

    async def initialize(self):
        """Initialize with error discovery."""
        # Discover all provider errors
        all_errors = await self.client.get_all_provider_errors()

        # Set up handlers for each provider
        for provider_id, errors in all_errors.items():
            self.error_handlers[provider_id] = await self.setup_handlers(errors)

    async def handle_error(self, error_code: int, provider_id: str):
        """Handle error based on discovered information."""
        handler = self.error_handlers.get(provider_id, {}).get(error_code)
        if handler:
            return await handler.handle()
        else:
            # Check if retryable
            is_retryable = await self.client.check_error_retryability(error_code)
            if is_retryable:
                return await self.retry()
            else:
                raise
```

#### Example: Generate API Documentation
```python
async def generate_api_docs(client: GleitzeitClient):
    """Generate complete API documentation with errors."""
    doc = "# API Documentation\n\n"

    # Get all providers
    providers = await client.get_providers()

    for provider in providers:
        provider_id = provider['provider_id']
        doc += f"## Provider: {provider_id}\n\n"

        # Get provider errors
        errors = await client.get_provider_errors(provider_id)

        doc += "### Possible Errors\n\n"
        for error in errors:
            doc += f"#### {error['name']}\n"
            doc += f"- **Code**: {error['error_code']} ({error['error_code_name']})\n"
            doc += f"- **Description**: {error['description']}\n"
            doc += f"- **Retryable**: {'Yes' if error['is_retryable'] else 'No'}\n\n"

    return doc
```

### Examples of Custom Error Discovery

Here's a complete example showing how custom provider errors are discovered:

```python
# test_custom_provider_errors.py
from gleitzeit.core.error_discovery import get_provider_errors
from gleitzeit.core.errors import ProviderError, ErrorCode
from gleitzeit.providers.simple import SimpleProvider

# Define custom errors
class APIKeyError(ProviderError):
    """Custom error for API key issues"""
    def __init__(self, message: str = "Invalid or missing API key", **kwargs):
        super().__init__(
            message,
            code=ErrorCode.AUTHENTICATION_FAILED,
            **kwargs
        )

class QuotaExceededError(ProviderError):
    """Custom error when quota is exceeded"""
    def __init__(self, used: int, limit: int, **kwargs):
        super().__init__(
            f"Quota exceeded: {used}/{limit}",
            code=ErrorCode.RESOURCE_EXHAUSTED,
            data={"used": used, "limit": limit},
            **kwargs
        )

class MyAPIProvider(SimpleProvider):
    """Provider with custom errors"""

    async def execute(self, method: str, params: dict):
        if not self.has_valid_api_key():
            raise APIKeyError()

        if self.quota_exceeded():
            raise QuotaExceededError(150, 100)

        return {"result": "success"}

# Discover errors
provider = MyAPIProvider(provider_id="myapi", protocol_id="api/v1")
errors = get_provider_errors(provider)

print(f"Found {len(errors)} total errors")

# Identify custom errors
for error in errors:
    if error.name in ["APIKeyError", "QuotaExceededError"]:
        print(f"✓ Custom Error: {error.name}")
        print(f"  - {error.description}")
        print(f"  - Code: {error.error_code.name}")
        print(f"  - Retryable: {error.is_retryable}")

# Output:
# Found 5 total errors
# ✓ Custom Error: APIKeyError
#   - Custom error for API key issues
#   - Code: AUTHENTICATION_FAILED
#   - Retryable: False
# ✓ Custom Error: QuotaExceededError
#   - Custom error when quota is exceeded
#   - Code: RESOURCE_EXHAUSTED
#   - Retryable: True
```

## Summary

The Gleitzeit error system provides:

1. **Hierarchical error types** for different domains
2. **Standardized error codes** for consistent handling
3. **Rich error context** for debugging
4. **JSON-RPC 2.0 compliance** for API responses
5. **Retryability detection** for resilient operations
6. **Cause preservation** for error chains
7. **Severity classification** for monitoring
8. **Runtime error discovery** for introspection and documentation
9. **Custom error support** with automatic discovery of provider-specific errors
10. **Client and API integration** for programmatic and REST access

This centralized approach ensures consistent error handling across all components while maintaining flexibility for domain-specific needs. The error discovery system automatically finds both standard and custom errors, making it easy to document, test, and handle all possible error conditions.

## File Reference

### Core Error System Files

#### Error Definition and Base System
- `src/gleitzeit/core/errors.py` - Central error definitions, error codes, and base error classes
- `src/gleitzeit/core/protocol.py` - Protocol specifications with error validation

#### Error Discovery
- `src/gleitzeit/core/error_discovery.py` - Error discovery engine for runtime introspection
- `docs/implementation/ERROR-SYSTEM-DOCUMENTATION.md` - This documentation file

### Client Integration Files

#### Client Mixins
- `src/gleitzeit/client/mixins/error_discovery.py` - Client mixin providing error discovery methods
- `src/gleitzeit/client/client.py` - Main client class that includes ErrorDiscoveryMixin

#### Client Adapters
- `src/gleitzeit/client/adapters/api.py` - API adapter with provider instance retrieval support

### API Integration Files

#### API Routes
- `src/gleitzeit/api/routes/error_discovery.py` - REST API endpoints for error discovery
- `src/gleitzeit/api/main.py` - Main API file with error discovery router registration

#### API Dependencies
- `src/gleitzeit/api/routes/base.py` - Base route handler for client method delegation
- `src/gleitzeit/api/dependencies.py` - Dependency injection for client pool

### Provider Error Files

#### Base Provider System
- `src/gleitzeit/providers/base.py` - Base ProtocolProvider class with error imports
- `src/gleitzeit/providers/simple.py` - SimpleProvider base class

#### Example Providers with Custom Errors
- `src/gleitzeit/providers/python_provider.py` - Python provider with TaskExecutionError usage
- `src/gleitzeit/providers/mcp_provider.py` - MCP provider implementation
- `src/gleitzeit/providers/provider_pool_manager.py` - Provider registry and pool management

### Test and Demo Files

#### Test Files
- `newtests/core/test_error_discovery.py` - Unit tests for error discovery functionality
- `test_custom_provider_errors.py` - Test for custom provider error discovery
- `test_error_discovery_api.py` - Integration test for API and client methods

#### Demo and Example Files
- `examples/error_discovery_demo.py` - Complete demo showing all error discovery features
- `test_custom_provider_errors.py` - Example of custom provider with domain-specific errors

### Documentation Files

#### Main Documentation
- `docs/implementation/ERROR-SYSTEM-DOCUMENTATION.md` - Comprehensive error system documentation
- `README.md` - Project readme with error handling overview

### Usage Quick Reference

```python
# Client usage
from gleitzeit.client import GleitzeitClient
client = GleitzeitClient()
errors = await client.get_provider_errors("python-executor")
hierarchy = await client.get_error_hierarchy()
report = await client.get_error_report()

# API usage
curl http://localhost:8000/errors/provider/python-executor
curl http://localhost:8000/errors/hierarchy
curl http://localhost:8000/errors/report

# Direct usage (without client/API)
from gleitzeit.core.error_discovery import get_provider_errors, get_error_hierarchy
from gleitzeit.providers.python_provider import PythonProvider
provider = PythonProvider(provider_id="test", protocol_id="python/v1")
errors = get_provider_errors(provider)
hierarchy = get_error_hierarchy()
```