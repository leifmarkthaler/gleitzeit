# Provider Lifecycle Management

## Overview

Gleitzeit V4 implements centralized provider lifecycle management with event-driven resource cleanup. This ensures proper cleanup of HTTP sessions, database connections, and other provider resources.

## Architecture

### Centralized Registry Management

The `ProtocolProviderRegistry` serves as the central lifecycle manager for all providers:

```python
class ProtocolProviderRegistry:
    async def stop(self):
        """Stop registry and cleanup all providers"""
        await self._cleanup_all_providers()
    
    async def _cleanup_all_providers(self):
        """Cleanup all registered provider instances"""
        for provider_id, provider_instance in self.provider_instances.items():
            await self._cleanup_provider(provider_id, provider_instance)
        self.provider_instances.clear()
    
    async def _cleanup_provider(self, provider_id: str, provider_instance: Any):
        """Cleanup a single provider instance"""
        # Try cleanup() first (pooling compatibility)
        if hasattr(provider_instance, 'cleanup'):
            await provider_instance.cleanup()
        # Fall back to shutdown()
        elif hasattr(provider_instance, 'shutdown'):
            await provider_instance.shutdown()
```

### Event-Driven Cleanup Flow

```
ExecutionEngine.stop() 
    ↓
Registry.stop() 
    ↓
Registry._cleanup_all_providers() 
    ↓
Individual provider cleanup
```

## Provider Cleanup Methods

### Standard Methods

Providers should implement one or both cleanup methods:

1. **`cleanup()`** - Preferred method, compatible with pooling systems
2. **`shutdown()`** - Standard shutdown method

### HTTP Provider Pattern

For HTTP-based providers like Ollama:

```python
class OllamaProvider(ProtocolProvider):
    def __init__(self, provider_id: str, ollama_url: str = "http://localhost:11434"):
        super().__init__(...)
        self.ollama_url = ollama_url
        self.session = None  # aiohttp ClientSession
    
    async def initialize(self):
        """Initialize HTTP session"""
        self.session = aiohttp.ClientSession()
        # ... provider initialization
    
    async def shutdown(self):
        """Cleanup HTTP session"""
        if self.session:
            await self.session.close()
            self.session = None
    
    async def cleanup(self):
        """Cleanup method for pooling compatibility"""
        await self.shutdown()
```

## Resource Management Patterns

### HTTP Sessions

**Best Practices:**
- Create sessions during `initialize()`
- Close sessions during `shutdown()`
- Set session to `None` after closing
- Handle session recreation if needed

**Example:**
```python
async def shutdown(self):
    if self.session:
        await self.session.close()
        self.session = None
```

### Database Connections

**Pattern:**
```python
async def shutdown(self):
    if self.db_pool:
        await self.db_pool.close()
        self.db_pool = None
```

### File Handles

**Pattern:**
```python
async def shutdown(self):
    if self.file_handle:
        await self.file_handle.close()
        self.file_handle = None
```

## Error Handling

### Resilient Cleanup

The registry handles cleanup errors gracefully:

```python
async def _cleanup_provider(self, provider_id: str, provider_instance: Any):
    try:
        # Attempt cleanup
        if hasattr(provider_instance, 'cleanup'):
            await provider_instance.cleanup()
        elif hasattr(provider_instance, 'shutdown'):
            await provider_instance.shutdown()
    except Exception as e:
        logger.warning(f"Failed to cleanup provider {provider_id}: {e}")
        # Continue with other providers
```

### Error Scenarios Handled

- Provider cleanup method throws exception
- Provider doesn't have cleanup methods
- Network timeouts during session closure
- Resource already closed/released

## Testing

### Test Coverage

Comprehensive tests in `tests/test_provider_cleanup.py`:

1. **Registry Cleanup Tests**
   - Single provider cleanup
   - Multiple provider cleanup
   - Error handling during cleanup
   - Registry stop behavior

2. **Provider-Specific Tests**
   - HTTP session cleanup
   - Cleanup method compatibility
   - Resource lifecycle management

3. **Integration Tests**
   - Full lifecycle testing
   - Execution engine integration
   - Concurrent cleanup scenarios

### Test Execution

```bash
# Run cleanup tests
PYTHONPATH=. python run_core_tests.py

# Specific cleanup test
PYTHONPATH=. python tests/test_provider_cleanup.py
```

## Implementation Guidelines

### For New Providers

1. **Implement Cleanup Methods**
   ```python
   async def shutdown(self):
       # Cleanup resources
   
   async def cleanup(self):
       # For pooling compatibility
       await self.shutdown()
   ```

2. **Resource Initialization**
   ```python
   async def initialize(self):
       # Create resources (sessions, connections, etc.)
   ```

3. **Error Handling**
   ```python
   async def shutdown(self):
       try:
           if self.resource:
               await self.resource.close()
       except Exception as e:
           logger.warning(f"Cleanup warning: {e}")
       finally:
           self.resource = None
   ```

### Registry Integration

Providers are automatically cleaned up when:
- Registry stops (`registry.stop()`)
- Provider is unregistered (`registry.unregister_provider()`)
- Execution engine shuts down (`engine.stop()`)

## Monitoring and Debugging

### Logging

Cleanup operations are logged:
```
INFO: Cleaning up all provider instances...
DEBUG: ✅ Cleaned up provider ollama-1
DEBUG: ✅ Shut down provider python-1
WARNING: ❌ Failed to cleanup provider broken-1: Connection error
INFO: Provider cleanup completed
```

### Health Checks

Monitor provider resource usage:
```python
async def health_check(self) -> Dict[str, Any]:
    return {
        "status": "healthy",
        "resources": {
            "http_session": self.session is not None,
            "connections": self.get_connection_count()
        }
    }
```

## Migration Guide

### Existing Providers

To add cleanup support to existing providers:

1. **Add Cleanup Method**
   ```python
   async def cleanup(self):
       await self.shutdown()
   ```

2. **Enhance Shutdown**
   ```python
   async def shutdown(self):
       # Add resource cleanup
       if self.session:
           await self.session.close()
           self.session = None
   ```

3. **Test Integration**
   - Add provider to test registry
   - Verify cleanup is called
   - Check for resource leaks

### Breaking Changes

- No breaking changes to existing provider interfaces
- All changes are additive and backward compatible
- Providers without cleanup methods still work (with warning)

## Production Deployment

### Best Practices

1. **Graceful Shutdown**
   ```python
   # In your application
   try:
       await execution_engine.stop()  # Triggers full cleanup
   except Exception as e:
       logger.error(f"Shutdown error: {e}")
   ```

2. **Resource Monitoring**
   - Monitor HTTP connection pools
   - Check for unclosed sessions
   - Track provider resource usage

3. **Error Recovery**
   - Implement retry logic for critical resources
   - Use circuit breakers for external services
   - Log cleanup failures for debugging

### Performance Considerations

- Cleanup operations run concurrently where possible
- Non-blocking cleanup for better shutdown performance
- Timeout protection prevents hanging during shutdown

## Summary

The provider lifecycle management system provides:

- ✅ **Centralized Resource Management** - All cleanup through registry
- ✅ **Event-Driven Architecture** - Cleanup triggered by system events
- ✅ **Error Resilience** - Individual provider failures don't affect others
- ✅ **Comprehensive Testing** - Full test coverage for all scenarios
- ✅ **Production Ready** - Handles real-world deployment scenarios
- ✅ **Backward Compatible** - Works with existing providers

This ensures reliable resource cleanup and prevents memory leaks, connection pool exhaustion, and other resource-related issues in production deployments.