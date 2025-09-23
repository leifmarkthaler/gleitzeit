# Gleitzeit 0.0.7 - New Provider System

## Overview

The provider system has been completely redesigned with a clean, scalable architecture focused on simplicity and performance.

## Key Changes

### 1. Archive
- All old provider files moved to `src/gleitzeit/providers/archive/`
- Clean slate implementation with no backward compatibility constraints

### 2. Core Architecture

#### Provider Interface (`src/gleitzeit/providers/core.py`)
- Minimal interface with just 3 methods: `execute`, `execute_stream`, `validate`
- Standardized `ExecutionRequest` and `ExecutionResponse` data classes
- No complex dependencies or optional parameters

#### Provider Implementations (`src/gleitzeit/providers/impl/`)
- **PythonProvider**: Executes Python code in isolated subprocesses
- **TimerProvider**: Handles sleep and scheduling with SLEEPING status
- **SignalProvider**: Manages workflow signals with WAITING status

### 3. Pooling System (`src/gleitzeit/providers/pool.py`)

**How it works:**
- Each protocol gets a pool of provider instances (min 2, max 10 by default)
- Concurrent requests are distributed across pool instances
- Auto-scaling based on utilization (scales up at 80%, down at 20%)
- Health tracking per instance with automatic failover

**Benefits:**
- Parallel execution (5 Python providers = 5 concurrent executions)
- Fault isolation (one crashed provider doesn't affect others)
- Efficient resource usage with bounded pools

### 4. Registry & Discovery (`src/gleitzeit/providers/registry.py`)
- Auto-discovers providers in `impl/` directory
- Protocol to provider class mapping
- Task type to protocol mapping (e.g., "python" → "python/v2")

### 5. Orchestrator (`src/gleitzeit/providers/orchestrator.py`)
- Coordinates all providers across the cluster
- Event-driven architecture with Redis support
- Async execution with request tracking
- Comprehensive metrics and monitoring

## Usage Example

```python
from gleitzeit.providers import ProviderOrchestrator

# Create orchestrator
orchestrator = ProviderOrchestrator(
    redis_client=redis,  # Optional
    config={
        'pool_defaults': {
            'min_instances': 2,
            'max_instances': 10,
            'auto_scale': True
        }
    }
)

# Initialize (auto-discovers and creates pools)
await orchestrator.initialize()

# Execute Python code
response = await orchestrator.execute(
    task_type="python",
    method="exec",
    params={"code": "result = sum(range(100))"}
)
print(response.result)  # 4950

# Execute timer (returns immediately with SLEEPING status)
response = await orchestrator.execute(
    task_type="timer",
    method="sleep",
    params={"duration": 60}
)
print(response.status)  # "sleeping"

# Wait for signal (returns immediately with WAITING status)
response = await orchestrator.execute(
    task_type="signal",
    method="wait",
    params={"signal": "my_signal"}
)
print(response.status)  # "waiting"
```

## Adding New Providers

Simply create a new file in `src/gleitzeit/providers/impl/`:

```python
from ..core import Provider, ExecutionRequest, ExecutionResponse

class MyProvider(Provider):
    protocol = "my_protocol/v1"

    async def execute(self, request: ExecutionRequest) -> ExecutionResponse:
        # Implementation
        return ExecutionResponse(
            request_id=request.request_id,
            status="success",
            result={"data": "processed"}
        )

    async def validate(self, request: ExecutionRequest) -> bool:
        return True  # Validation logic
```

The provider will be auto-discovered and pooled automatically!

## Architecture Benefits

1. **Simplicity**: Each provider ~100 lines of focused code
2. **Scalability**: Horizontal scaling through pooling
3. **Reliability**: Process isolation and health tracking
4. **Performance**: Concurrent execution across pool instances
5. **Maintainability**: Clear contracts and separation of concerns

## Metrics & Monitoring

The system provides comprehensive metrics:

```python
metrics = await orchestrator.get_metrics()
# {
#     'requests_processed': 150,
#     'success_rate': 0.98,
#     'pools': {
#         'python/v2': {
#             'utilization': 0.4,
#             'instances': 3,
#             'health_scores': [1.0, 0.98, 1.0]
#         }
#     }
# }
```

## Testing

Run the test suite:
```bash
python test_new_providers.py
```

## Migration from Old System

1. Old providers are archived in `src/gleitzeit/providers/archive/`
2. Update workflows to use new task types if needed
3. The new system uses protocol versions (e.g., "python/v2" instead of "python/v1")

## Next Steps

1. Add more providers (HTTP, LLM, Shell, etc.)
2. Implement provider middleware for cross-cutting concerns
3. Add distributed tracing support
4. Create Kubernetes operators for cloud-native deployment