# Error Management Audit - Gleitzeit

## Files Needing Error Management Updates

### Priority 1: Provider Files (Critical) 🔴

#### 1. **ollama_provider.py** - 5 generic exceptions
- Lines 116, 167, 246, 274, 304
- Issues: Using `ValueError` and `RuntimeError` instead of specific errors
- **Fix**: Replace with `ProviderError`, `TaskValidationError`

#### 2. **python_function_provider.py** - 12 generic exceptions
- Lines 116, 153, 202, 209, 212, 223, 334, 337, 390, 399, 402
- Issues: Many `ValueError` exceptions for validation
- **Fix**: Replace with `TaskValidationError`, `ConfigurationError`

#### 3. **simple_mcp_provider.py** - 2 generic exceptions
- Lines 87, 92
- Issues: Using `ValueError` for unsupported methods
- **Fix**: Replace with `MethodNotSupportedError`

### Priority 2: Core Files (Important) 🟡

#### 4. **workflow_loader.py** - 5 generic exceptions
- Lines 39, 193, 196, 201, 204
- Issues: Using `ValueError` for validation
- **Fix**: Replace with `WorkflowValidationError`

#### 5. **batch_processor.py** - 3 generic exceptions
- Lines 116, 119, 155, 253
- Issues: Using `ValueError` for validation
- **Fix**: Replace with `TaskValidationError`

#### 6. **models.py** - 7 generic exceptions
- Lines 118, 122, 127, 131, 134, 152
- Issues: Using `ValueError` for method name validation
- **Fix**: Replace with `TaskValidationError`

#### 7. **execution_engine.py** - 2 generic exceptions
- Lines 230, 1122
- Issues: Using `ValueError` for validation
- **Fix**: Replace with `WorkflowValidationError`

#### 8. **jsonrpc.py** - 9 generic exceptions
- Lines 44, 64, 122, 125, 249, 254, 267, 290, 295, 308
- Issues: Using `ValueError` for protocol validation
- **Fix**: Replace with `ProtocolError`

### Priority 3: Support Files (Nice to Have) 🟢

#### 9. **registry.py** - 2 generic exceptions
- Lines 159, 444
- Issues: Using `ValueError` for not found errors
- **Fix**: Replace with `ProviderNotFoundError`

#### 10. **protocol.py** - 7 generic exceptions
- Lines 114, 118, 123, 127, 130, 222, 359
- Issues: Using `ValueError` for validation
- **Fix**: Replace with `ProtocolError`

#### 11. **task_queue.py** - 2 generic exceptions
- Lines 394, 422
- Issues: Using `ValueError` for queue errors
- **Fix**: Replace with `QueueError`

#### 12. **workflow_manager.py** - 2 generic exceptions
- Lines 256, 395
- Issues: Using `ValueError` for validation
- **Fix**: Replace with `WorkflowValidationError`

### Priority 4: CLI Files (Low Priority) 🔵

#### 13. **cli/workflow.py** - 2 generic exceptions
- Lines 34, 36
- Issues: Using `ValueError` for YAML errors
- **Fix**: Replace with `ConfigurationError`

#### 14. **cli/commands/dev.py** - 3 generic exceptions + poor handling
- Lines 142, 171, 206, 229
- Issues: Using generic `Exception`, has bare except blocks
- **Fix**: Replace with specific errors and proper handling

#### 15. **client/api.py** - 1 generic exception
- Line 353
- Issues: Using `ValueError` for type validation
- **Fix**: Replace with `TaskValidationError`

## Summary Statistics

- **Total Files with Issues**: 15
- **Total Generic Exceptions**: 62
- **Critical Priority**: 3 files (providers)
- **High Priority**: 5 files (core)
- **Medium Priority**: 4 files (support)
- **Low Priority**: 3 files (CLI)

## Recommended Fix Pattern

Replace generic exceptions with specific Gleitzeit errors:

```python
# Before:
raise ValueError(f"Unsupported method: {method}")

# After:
from gleitzeit.core.errors import MethodNotSupportedError
raise MethodNotSupportedError(method, protocol_id=self.protocol_id)
```

```python
# Before:
raise RuntimeError(f"API error {response.status}: {error_text}")

# After:
from gleitzeit.core.errors import ProviderError, ErrorCode
raise ProviderError(
    f"API error {response.status}: {error_text}",
    code=ErrorCode.PROVIDER_NOT_AVAILABLE,
    provider_id=self.provider_id
)
```

## New Error Classes Needed

Add these to `errors.py`:

```python
class MethodNotSupportedError(ProviderError):
    """Method not supported by provider"""
    def __init__(self, method: str, provider_id: str, **kwargs):
        super().__init__(
            f"Method '{method}' not supported by provider '{provider_id}'",
            ErrorCode.METHOD_NOT_SUPPORTED,
            provider_id=provider_id,
            **kwargs
        )

class QueueNotFoundError(QueueError):
    """Queue not found error"""
    def __init__(self, queue_name: str, **kwargs):
        super().__init__(
            f"Queue '{queue_name}' not found",
            ErrorCode.QUEUE_NOT_FOUND,
            queue_name=queue_name,
            **kwargs
        )

class InvalidParameterError(TaskError):
    """Invalid parameter error"""
    def __init__(self, param_name: str, reason: str, task_id: Optional[str] = None, **kwargs):
        super().__init__(
            f"Invalid parameter '{param_name}': {reason}",
            ErrorCode.INVALID_PARAMS,
            task_id=task_id,
            data={"parameter": param_name, "reason": reason},
            **kwargs
        )
```

## Implementation Plan

1. **Phase 1**: Update providers (ollama, python, mcp)
2. **Phase 2**: Update core files (workflow_loader, batch_processor, models)
3. **Phase 3**: Update support files (registry, protocol, task_queue)
4. **Phase 4**: Update CLI files

## Testing Strategy

After each phase:
1. Run existing tests
2. Test error scenarios manually
3. Verify error messages are clear and helpful