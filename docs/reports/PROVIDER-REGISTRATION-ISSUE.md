# Provider Registration Issue Analysis

## Problem Summary

Task execution fails because the Python provider is not accessible to the TaskExecutor. The root cause is a disconnect between the provider pooling system and the protocol registry that TaskExecutor uses.

## Current Architecture

### Two Parallel Systems

1. **ProviderPoolManager** (src/gleitzeit/providers/provider_pool_manager.py)
   - Manages pooled provider instances
   - Registered in SystemManager._start_providers() at line 862-889
   - Stores providers in its own internal registry

2. **ProtocolProviderRegistry** (src/gleitzeit/registry.py) 
   - Used by TaskExecutor for provider lookup
   - Created in SystemManager._start_core_components() at line 742-743
   - NOT connected to ProviderPoolManager

### The Disconnect

```
SystemManager creates:
  ├── ProtocolProviderRegistry (self.registry)
  │   └── Used by TaskExecutor
  │       └── execute_request() calls registry.execute_request()
  │
  └── ProviderPoolManager (self.provider_pool_manager)
      └── Has providers but NOT registered with registry!
```

## Execution Flow Analysis

### Task Execution Path (src/gleitzeit/core/task_executor.py)

1. **Line 168-232**: `_route_and_execute()` method
   - First checks pooling_adapter (lines 184-202)
   - Falls back to registry.execute_request() (lines 204-231)

2. **The Problem**: 
   - PoolingAdapter exists but is NOT passed to TaskExecutor
   - Registry exists but has NO providers registered
   - Result: "No providers available for python/v1::execute"

### SystemManager Initialization

In `src/gleitzeit/system/system_manager.py`:

1. **Line 765-772**: Creates ExecutionEngineV2
   - Does NOT pass pooling_adapter parameter
   - Engine creates TaskExecutor without pooling_adapter

2. **Line 852-899**: Creates ProviderPoolManager
   - Registers Python provider in pool
   - But NEVER connects to registry or execution engine

## The Missing Connection

### Option 1: Pass PoolingAdapter to ExecutionEngine

```python
# In SystemManager._start_core_components() after line 862
pooling_adapter = PoolingAdapter(persistence=self.persistence)
await pooling_adapter.initialize()

# Register providers with adapter
await pooling_adapter.register_provider(
    "python_provider",
    "python/v1", 
    PythonProvider
)

# Pass to execution engine (modify line 765)
self.execution_engine = ExecutionEngineV2(
    registry=self.registry,
    queue_manager=queue_manager,
    dependency_resolver=dependency_manager,
    persistence=self.persistence,
    event_bus=self.event_bus,
    pooling_adapter=pooling_adapter  # ADD THIS
)
```

### Option 2: Register Providers with Registry

```python
# In SystemManager._start_providers() after creating provider pool
# Around line 889, add:

# Also register with the main registry
python_provider = PythonProvider(
    provider_id="python_provider",
    protocol_id="python/v1"
)
await python_provider.initialize()

self.registry.register_provider(
    provider_id="python_provider",
    protocol_id="python/v1",
    provider_instance=python_provider
)
```

## Recommended Solution

**Use Option 1** - Pass PoolingAdapter to ExecutionEngine:

1. **Benefits**:
   - Leverages existing pooling infrastructure
   - Maintains stateless architecture
   - Better resource management

2. **Implementation**:
   - Move provider initialization BEFORE engine creation
   - Create PoolingAdapter
   - Pass adapter to ExecutionEngineV2
   - TaskExecutor will automatically use it

## Verification

After implementing the fix, task execution should work:

```python
# TaskExecutor._route_and_execute() will:
1. Check pooling_adapter.is_protocol_available("python/v1")  # Returns True
2. Call pooling_adapter.execute_task(task)  # Executes successfully
3. Return result
```

## Impact

This fix will resolve:
- "No providers available for python/v1::execute" errors
- Task execution failures
- Workflow completion issues

The workflow lifecycle is otherwise complete - only this provider registration issue prevents execution.