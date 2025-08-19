# Shutdown Methods in Gleitzeit

## Overview
Yes, there are shutdown methods across all components to properly clean up resources.

## 1. Client (GleitzeitClient)

### Automatic Shutdown (Recommended)
```python
# Using context manager - automatically calls shutdown on exit
async with Client() as client:
    # ... use client ...
    pass  # shutdown() called automatically here
```

### Manual Shutdown
```python
client = Client()
await client.initialize()
# ... use client ...
await client.shutdown()  # Manual shutdown
```

### What `client.shutdown()` does:
- **API Mode**:
  - Closes API client connection
  - Stops API server if started by client (unless `keep_server_running=True`)
  - Cleans up HTTP sessions

- **Native Mode**:
  - Stops resource manager (`await self._resource_manager.stop()`)
  - Shuts down all providers
  - Closes persistence backend
  - Cleans up all resources

## 2. CLI

### Automatic Shutdown
The CLI automatically calls `_shutdown_system()` after every command:

```python
async def _shutdown_system(self):
    """Clean shutdown of the system including hubs and resource manager"""
    
    # Shutdown all providers
    if self.execution_engine and self.execution_engine.registry:
        for provider_id, provider_instance in self.execution_engine.registry.provider_instances.items():
            if hasattr(provider_instance, 'shutdown'):
                await provider_instance.shutdown()
            elif hasattr(provider_instance, 'cleanup'):
                await provider_instance.cleanup()
    
    # Shutdown resource manager and hubs
    if self.resource_manager:
        await self.resource_manager.stop()
    
    # Shutdown persistence backend
    if self.persistence_backend:
        await self.persistence_backend.shutdown()
```

### When it's called:
- After `run` command completes
- After `status` command
- After `batch` command
- In all error scenarios (finally blocks)

## 3. API Server

### Lifespan Management
The API uses FastAPI's lifespan context manager:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Gleitzeit API...")
    await setup_system()
    yield
    # Shutdown automatically called here
    logger.info("Shutting down Gleitzeit API...")
    await cleanup_system()
```

### What `cleanup_system()` does:
```python
async def cleanup_system():
    """Clean up system resources including hubs and resource manager"""
    # Clean up providers
    if app_state.execution_engine and app_state.registry:
        for provider_id, provider in app_state.registry.provider_instances.items():
            if hasattr(provider, 'shutdown'):
                await provider.shutdown()
    
    # Shutdown resource manager and hubs
    if app_state.resource_manager:
        await app_state.resource_manager.stop()
    
    # Shutdown persistence
    if app_state.persistence_backend:
        await app_state.persistence_backend.shutdown()
```

### When it's called:
- When API server receives shutdown signal (CTRL+C)
- When server process is terminated
- On any unhandled exception during lifespan

## 4. Component-Level Shutdown Methods

### ExecutionEngine
```python
await engine.stop()
# - Stops scheduler
# - Waits for active tasks
# - Sets shutdown event
```

### ResourceManager
```python
await resource_manager.stop()
# - Stops all hubs
# - Cancels monitor tasks
# - Cleans up allocations
```

### Hubs (OllamaHub, DockerHub)
```python
await hub.stop()
# - Stops health monitoring
# - Optionally stops instances
# - Closes connections
```

### Providers
```python
await provider.shutdown()
# - Provider-specific cleanup
# - Closes connections
# - Releases resources
```

### Persistence Backends
```python
await persistence.shutdown()
# - Closes database connections
# - Flushes pending writes
# - Releases locks
```

## Best Practices

### 1. Always Use Context Managers
```python
# Good - automatic cleanup
async with Client() as client:
    await client.run_workflow("workflow.yaml")

# Avoid - manual management
client = Client()
await client.initialize()
await client.run_workflow("workflow.yaml")
await client.shutdown()  # Easy to forget!
```

### 2. Handle Shutdown Errors
```python
try:
    async with Client() as client:
        # ... work ...
except Exception as e:
    logger.error(f"Error: {e}")
    # shutdown still called automatically
```

### 3. Server Lifecycle Management
```python
# Auto-start and keep running
client = Client(
    auto_start_server=True,
    keep_server_running=True  # Server stays alive after client exits
)

# Manual server management
client = Client(
    auto_start_server=False,  # Don't auto-start
    keep_server_running=False  # Stop when client exits
)
```

## Common Issues and Solutions

### Issue: Unclosed client session warnings
```
ERROR:asyncio:Unclosed client session
```
**Solution**: Hub's aiohttp session not being closed. This is being tracked and will be fixed.

### Issue: Server keeps running after client exits
**Solution**: Set `keep_server_running=False` when creating client:
```python
client = Client(keep_server_running=False)
```

### Issue: Resources not cleaned up in tests
**Solution**: Use pytest fixtures with proper cleanup:
```python
@pytest.fixture
async def client():
    async with Client() as c:
        yield c
    # Cleanup happens automatically
```

## Summary

All three main components (CLI, API, Client) have proper shutdown methods:

- **Client**: `await client.shutdown()` or use context manager (recommended)
- **CLI**: Automatic `_shutdown_system()` after each command
- **API**: Automatic `cleanup_system()` on server shutdown

The shutdown process follows this hierarchy:
1. Stop high-level components (ExecutionEngine, ResourceManager)
2. Stop providers and hubs
3. Close persistence backends
4. Release system resources (connections, processes)

**Recommendation**: Always use context managers (`async with`) for automatic, guaranteed cleanup.