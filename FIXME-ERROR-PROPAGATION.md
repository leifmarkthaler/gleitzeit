# FIXME: Error Propagation Issues

## Issue
Multiple error propagation and debugging issues throughout the codebase make it difficult to diagnose problems.

## Specific Problems

### 1. ProviderFactory Validation Errors
**Location**: `src/gleitzeit/providers/factory.py` line 367
```python
raise ProviderValidationError(
    f"Provider class {class_name} failed validation",
    provider_class=class_name,
    validation_errors=class_errors
)
```
**Problem**: The actual validation errors are not shown in the error message. The `class_errors` list contains the specific issues but they're only passed as metadata, not in the visible error message.

**Fix Required**: Include the actual validation errors in the exception message:
```python
error_details = '\n'.join(f"  - {error}" for error in class_errors)
raise ProviderValidationError(
    f"Provider class {class_name} failed validation:\n{error_details}",
    ...
)
```

### 2. Registry Provider Lookup Errors
**Location**: `src/gleitzeit/registry.py` line 306
```python
error_message=f"No providers available for {protocol_id}::{request.method}"
```
**Problem**: Doesn't indicate WHY no providers are available (not registered, unhealthy, method mismatch, etc.)

**Fix Required**: Add diagnostic information:
- List registered providers for the protocol
- Show which providers were filtered out and why
- Include provider health status

### 3. Task Execution Errors
**Location**: `src/gleitzeit/core/task_executor.py` line 223
```python
error_msg = response.error.message if hasattr(response.error, 'message') else str(response.error)
raise TaskExecutionError(task_id=task.id, message=error_msg)
```
**Problem**: Loses context about which provider was used, what parameters were sent, etc.

### 4. Event Handler Registration Errors
**Location**: Multiple event handler registrations
**Problem**: Silent failures when handlers are registered asynchronously - no indication if registration succeeded or failed.

### 5. Client Error Messages
**Location**: `src/gleitzeit/client/adapters/event_driven.py`
```python
ERROR:src.gleitzeit.client.adapters.event_driven:Task hello-task failed permanently: Unknown error
```
**Problem**: "Unknown error" provides no debugging information.

## General Issues

1. **Lost Stack Traces**: Many places catch exceptions and re-raise with new messages, losing the original stack trace
2. **Silent Failures**: Async operations that fail silently (especially event registrations)
3. **Generic Error Messages**: "Unknown error", "Failed", etc. without context
4. **Missing Debug Logging**: Critical decision points don't log why certain paths were taken
5. **Validation Error Details**: Validation failures don't show what was expected vs. what was provided

## Recommended Fixes

1. **Always include context in errors**:
   - What was being attempted
   - What data was involved
   - Why it failed
   - What the user can do to fix it

2. **Use exception chaining**:
   ```python
   try:
       # operation
   except SomeError as e:
       raise NewError(f"Context: {details}") from e  # Preserves stack trace
   ```

3. **Add debug logging at decision points**:
   ```python
   if not providers:
       logger.debug(f"No providers found for {protocol_id}: registered_providers={list(self.providers.keys())}")
       return None
   ```

4. **Make async registration failures visible**:
   ```python
   try:
       await self.register_handler(...)
       logger.info(f"Successfully registered handler for {event_type}")
   except Exception as e:
       logger.error(f"Failed to register handler for {event_type}: {e}")
       raise  # Don't silently swallow
   ```

## Priority
**HIGH** - These issues make debugging extremely difficult and hide root causes of failures.