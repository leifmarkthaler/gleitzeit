# Multi-Instance Handler Design for Gleitzeit

## Overview

This document outlines the design for supporting multiple backend instances (e.g., multiple Ollama servers, multiple database connections) in Gleitzeit handlers while maintaining the system's distributed architecture.

## Core Principles

1. **Worker-Level Configuration**: Each TaskExecutionWorker can have its own handler configuration
2. **Handler Abstraction**: Handlers remain stateless and protocol-compliant
3. **Transparent Scaling**: Multiple instances appear as increased capacity, not complexity
4. **Graceful Degradation**: System continues working even if some instances fail

## Architecture Approaches

### Approach 1: Worker-Specific Handler Configuration (Recommended)

```yaml
# Worker configuration specifies handler instances
worker_config:
  worker_id: "exec-worker-1"
  handler_configs:
    ollama/v1:
      base_url: "http://ollama-1:11434"
    postgres/v1:
      connection_string: "postgres://db-1:5432"
```

**Advantages:**
- Fits Gleitzeit's distributed worker model
- Each worker is independent
- Natural load balancing via Redis streams
- No single point of failure

**Implementation:**
- TaskExecutionWorker accepts handler configs at initialization
- Workers compete for tasks via consumer groups
- Redis naturally distributes work

### Approach 2: Handler-Level Instance Pooling

```python
class PooledHandler(BaseHandler):
    def __init__(self, config):
        self.instances = config.get('instances', [])
        self.selection_strategy = config.get('strategy', 'round_robin')
```

**Advantages:**
- Single handler manages multiple backends
- Can implement sophisticated selection strategies
- Centralized health monitoring

**Disadvantages:**
- More complex handler implementation
- Potential bottleneck in instance selection
- Harder to debug

### Approach 3: Service Discovery Integration

```yaml
handler_config:
  ollama/v1:
    discovery:
      method: "consul"  # or "etcd", "kubernetes"
      service: "ollama-service"
      health_check: true
```

**Advantages:**
- Dynamic instance discovery
- Automatic failover
- Cloud-native approach

**Disadvantages:**
- Additional infrastructure dependency
- More complex deployment

## Recommended Implementation Pattern

### 1. Configuration Hierarchy

```yaml
# Global defaults (gleitzeit.yaml)
handlers:
  ollama/v1:
    default_timeout: 300
    default_model: llama2

# Worker-specific overrides (worker-config.yaml or CLI args)
workers:
  - id: worker-1
    shards: [0, 1, 2, 3]
    handlers:
      ollama/v1:
        base_url: http://ollama-1:11434

  - id: worker-2
    shards: [4, 5, 6, 7]
    handlers:
      ollama/v1:
        base_url: http://ollama-2:11435
```

### 2. Worker Initialization

```python
class TaskExecutionWorker(BaseWorker):
    def __init__(self, config: WorkerConfig):
        # Base initialization
        super().__init__(config)

        # Handler-specific configs
        handler_configs = config.get('handler_configs', {})

        # Initialize handlers with worker-specific configs
        for protocol, handler_class in registry.get_handlers():
            handler_config = handler_configs.get(protocol, {})
            self.handlers[protocol] = handler_class(handler_config)
```

### 3. Deployment Patterns

#### Pattern A: Shard-Based Distribution
```
Worker 1 (shards 0-7)  → Ollama Instance 1
Worker 2 (shards 8-15) → Ollama Instance 2
```

#### Pattern B: Redundant Workers
```
Worker 1A (all shards) → Ollama Instance 1
Worker 1B (all shards) → Ollama Instance 1
Worker 2A (all shards) → Ollama Instance 2
Worker 2B (all shards) → Ollama Instance 2
```

#### Pattern C: Mixed Handlers
```
Worker 1 → Ollama Instance 1, PostgreSQL Primary
Worker 2 → Ollama Instance 2, PostgreSQL Replica
```

## Load Balancing Strategies

### 1. Redis Consumer Group (Natural)
- Multiple workers in same consumer group
- Redis distributes messages automatically
- No additional load balancing needed

### 2. Shard Assignment
- Workers assigned different shards
- Each shard routes to specific handler instance
- Predictable routing

### 3. Health-Aware Routing
- Workers monitor their handler health
- Pause consumption if handler unhealthy
- Other workers take over

## Configuration Management

### Option 1: Environment Variables
```bash
GLEITZEIT_HANDLER_OLLAMA_URL=http://ollama-1:11434 \
GLEITZEIT_WORKER_ID=exec-1 \
python -m gleitzeit.workers.runner
```

### Option 2: Configuration Files
```yaml
# /etc/gleitzeit/workers/exec-1.yaml
worker:
  id: exec-1
  type: task_execution
  handlers:
    ollama/v1:
      base_url: ${OLLAMA_URL:-http://localhost:11434}
```

### Option 3: Command Line Arguments
```bash
python -m gleitzeit.workers.runner \
  --worker-class TaskExecutionWorker \
  --handler-config ollama/v1:base_url=http://ollama-1:11434
```

## Health Monitoring

### Handler Health Checks
```python
class BaseHandler:
    async def health_check(self) -> HealthStatus:
        """Check if handler backend is healthy"""
        return HealthStatus(
            healthy=True,
            latency_ms=10,
            last_check=datetime.now()
        )
```

### Worker Health Reporting
```python
class TaskExecutionWorker:
    async def report_health(self):
        """Report worker and handler health to Redis"""
        health = {
            'worker_id': self.worker_id,
            'timestamp': datetime.now(),
            'handlers': {}
        }

        for protocol, handler in self.handlers.items():
            health['handlers'][protocol] = await handler.health_check()

        await self.redis.hset(f"worker:health:{self.worker_id}", health)
```

## Scaling Considerations

### Horizontal Scaling
- Add more workers with same configuration
- Redis consumer groups handle distribution
- No code changes needed

### Vertical Scaling
- Add more handler instances
- Deploy new workers pointing to new instances
- Gradual rollout possible

### Auto-Scaling
```yaml
scaling:
  metrics:
    - queue_depth > 100
    - avg_task_duration > 5s

  actions:
    scale_up:
      add_workers: 2
      handler_instance: "next_available"

    scale_down:
      remove_workers: 1
      grace_period: 60s
```

## Best Practices

1. **Keep Handlers Stateless**: Don't store instance selection state in handlers
2. **Use Worker Groups**: Let Redis handle load balancing via consumer groups
3. **Monitor Everything**: Track which worker/instance handles each task
4. **Graceful Shutdown**: Workers should complete current tasks before stopping
5. **Instance Affinity**: Consider keeping related tasks on same instance (optional)

## Migration Path

### Phase 1: Single Instance (Current)
- One handler configuration
- Multiple workers share same backend

### Phase 2: Worker-Specific Config
- Each worker can override handler config
- Backwards compatible

### Phase 3: Dynamic Discovery (Future)
- Service discovery integration
- Automatic instance registration
- Health-based routing

## Example: Ollama Multi-Instance Setup

### Deployment
```bash
# Start Ollama instances
ollama serve --port 11434
ollama serve --port 11435

# Start workers
python run_worker.py --id worker-1 --ollama-url http://localhost:11434
python run_worker.py --id worker-2 --ollama-url http://localhost:11435
```

### Monitoring
```python
# Check which instance handled each task
for task_id in completed_tasks:
    result = redis.hget(f"task:result:{task_id}")
    print(f"Task {task_id} handled by {result['worker_id']}")
```

## Conclusion

The recommended approach is **Worker-Specific Handler Configuration** because:

1. It aligns with Gleitzeit's distributed architecture
2. Requires minimal changes to existing code
3. Provides natural load balancing via Redis
4. Maintains handler simplicity
5. Enables gradual migration

This design allows Gleitzeit to scale horizontally by adding workers with different backend instances while maintaining the simplicity and reliability of the current system.