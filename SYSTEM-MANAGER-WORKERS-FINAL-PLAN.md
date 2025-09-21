# System Manager to Workers: Final Implementation Plan

## Executive Summary

Transform ModularStreamSystemManager into a lightweight coordinator that emits events to sharded streams, where specialized workers process them with workflow locality.

## Current vs Target Architecture

### Current (Monolithic)
```
SystemManager → process_all_once() → Everything Sequential
                ↓
    Single stream: "gleitzeit:events:stream:task:ready"
```

### Target (Distributed Workers)
```
SystemManager → emit_to_shard() → Sharded Streams → Specialized Workers
                ↓                        ↓                    ↓
         workflow_id hash         task:ready:0-15      ExecutionWorkers
                                  dep:check:0-15       DependencyWorkers
                                  workflow:coord:0-15  CoordinatorWorkers
```

## Phase 1: Add Sharding Infrastructure (Week 1)

### 1.1 Create Sharding Utilities

```python
# src/gleitzeit/core/sharding.py
from typing import Optional

class ShardingStrategy:
    """Workflow-based sharding for stream locality"""

    def __init__(self, num_shards: int = 16):
        self.num_shards = num_shards
        self.shard_assignments = {}  # Cache workflow->shard mappings

    def get_shard(self, workflow_id: str) -> int:
        """Get shard for workflow (consistent for all its tasks)"""
        if workflow_id not in self.shard_assignments:
            self.shard_assignments[workflow_id] = hash(workflow_id) % self.num_shards
        return self.shard_assignments[workflow_id]

    def get_stream_key(self, base: str, workflow_id: str) -> str:
        """Get sharded stream key maintaining workflow locality"""
        shard = self.get_shard(workflow_id)
        return f"{base}:{shard}"

# Global instance
sharding = ShardingStrategy(num_shards=16)
```

### 1.2 Update StreamlinedEventBus

```python
# src/gleitzeit/events/streamlined_event_bus.py
class StreamlinedEventBus:
    def __init__(self, redis_client, sharding_enabled: bool = False):
        self.redis = redis_client
        self.sharding_enabled = sharding_enabled
        self.sharding = ShardingStrategy() if sharding_enabled else None

    async def emit(self, event, workflow_id: Optional[str] = None):
        """Emit event with optional sharding"""

        # Extract workflow_id from event if not provided
        if not workflow_id and hasattr(event, 'data'):
            workflow_id = event.data.get('workflow_id')

        # Determine stream key
        if self.sharding_enabled and workflow_id:
            # Sharded stream for workflow locality
            stream_key = self.sharding.get_stream_key(
                event.event_type.lower().replace('_', ':'),
                workflow_id
            )
        else:
            # Old unsharded pattern (for backward compatibility)
            stream_key = f"gleitzeit:events:stream:{event.event_type.lower()}"

        # Emit to appropriate stream
        await self.redis.xadd(stream_key, event.to_dict())
```

## Phase 2: Create Core Workers (Week 1-2)

### 2.1 Base Worker with Sharding Support

```python
# src/gleitzeit/workers/base_sharded.py
class ShardedWorker(BaseWorker):
    """Base worker that handles sharded streams"""

    def __init__(self, config: WorkerConfig, assigned_shards: List[int] = None):
        super().__init__(config)
        self.assigned_shards = assigned_shards or list(range(16))  # Default: all shards

    def get_stream_patterns(self) -> Dict[str, str]:
        """Get sharded stream patterns"""
        patterns = {}
        for shard in self.assigned_shards:
            for base_stream in self.get_base_streams():
                patterns[f"{base_stream}:{shard}"] = ">"
        return patterns

    @abstractmethod
    def get_base_streams(self) -> List[str]:
        """Return base stream names (without shard suffix)"""
        pass
```

### 2.2 TaskExecutionWorker with Workflow Locality

```python
# src/gleitzeit/workers/task_execution_worker.py
class TaskExecutionWorker(ShardedWorker):
    """Execute tasks with workflow locality"""

    def get_base_streams(self) -> List[str]:
        return ["task:ready", "task:retry"]

    async def process_message(self, stream: str, msg_id: str, data: Dict):
        """Process task with cached workflow context"""

        workflow_id = data['workflow_id']
        task_id = data['task_id']

        # All tasks from this workflow come to same shard
        # So we can cache workflow data efficiently
        workflow = await self.get_cached_workflow(workflow_id)

        # Execute task
        result = await self.execute_task(data['task'])

        # Emit completion TO SAME SHARD for dependency locality
        shard = self.sharding.get_shard(workflow_id)
        await self.redis.xadd(f"task:completed:{shard}", {
            'workflow_id': workflow_id,
            'task_id': task_id,
            'result': json.dumps(result)
        })
```

### 2.3 DependencyWorker with Local Resolution

```python
# src/gleitzeit/workers/dependency_worker.py
class DependencyWorker(ShardedWorker):
    """Resolve dependencies with workflow locality"""

    def get_base_streams(self) -> List[str]:
        return ["task:completed", "workflow:submitted"]

    async def process_message(self, stream: str, msg_id: str, data: Dict):
        """Process with ALL workflow data on same shard"""

        workflow_id = data['workflow_id']
        shard = self.sharding.get_shard(workflow_id)

        if "task:completed" in stream:
            # Check dependencies - ALL ARE LOCAL TO THIS SHARD!
            graph_key = f"dep:graph:{workflow_id}"
            graph = await self.redis.hgetall(graph_key)

            # Find ready tasks (no cross-shard communication!)
            ready_tasks = self.find_ready_tasks(graph, data['task_id'])

            # Emit ready tasks TO SAME SHARD
            for task_id in ready_tasks:
                await self.redis.xadd(f"task:ready:{shard}", {
                    'workflow_id': workflow_id,
                    'task_id': task_id
                })
```

## Phase 3: Update System Manager (Week 2)

### 3.1 Lightweight System Manager

```python
# src/gleitzeit/system/lightweight_manager.py
class LightweightSystemManager:
    """Minimal manager that emits to sharded streams"""

    def __init__(self, redis_client, enable_sharding: bool = True):
        self.redis = redis_client
        self.sharding = ShardingStrategy() if enable_sharding else None

    async def submit_workflow(self, workflow: Workflow):
        """Submit workflow to sharded streams"""

        if self.sharding:
            # Get shard for this workflow
            shard = self.sharding.get_shard(workflow.id)

            # ALL workflow events go to same shard
            await self.redis.xadd(f"workflow:submitted:{shard}", {
                'workflow_id': workflow.id,
                'workflow': workflow.to_json()
            })

            # Initial tasks also go to same shard
            for task in workflow.get_initial_tasks():
                await self.redis.xadd(f"task:ready:{shard}", {
                    'workflow_id': workflow.id,
                    'task_id': task.id,
                    'task': task.to_json()
                })
        else:
            # Fallback to old pattern
            await self.emit_old_style(workflow)
```

### 3.2 Gradual Migration in ModularStreamSystemManager

```python
# src/gleitzeit/system/modular_stream_system_manager.py
class ModularStreamSystemManager:
    def __init__(self, enable_workers: bool = False):
        self.enable_workers = enable_workers
        self.sharding = ShardingStrategy() if enable_workers else None

    async def process_task(self, task: Task):
        """Dual-mode processing"""

        if self.enable_workers and random.random() < WORKER_PERCENTAGE:
            # New: Emit to sharded stream
            shard = self.sharding.get_shard(task.workflow_id)
            await self.redis.xadd(f"task:ready:{shard}", {
                'workflow_id': task.workflow_id,
                'task_id': task.id,
                'task': task.to_json()
            })
            # Let workers handle it
        else:
            # Old: Process directly
            await self.task_executor.execute(task)
```

## Phase 4: Deployment Strategy (Week 3)

### 4.1 Worker Distribution

```yaml
# k8s/workers-deployment.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: execution-workers
spec:
  serviceName: execution-workers
  replicas: 16  # One per shard minimum
  template:
    spec:
      containers:
      - name: worker
        env:
        - name: WORKER_TYPE
          value: "execution"
        - name: ASSIGNED_SHARDS
          value: "$(SHARD_ASSIGNMENT)"  # Calculated based on pod ordinal
```

### 4.2 Shard Assignment Strategy

```python
# Assign shards to workers for redundancy
def assign_shards_to_workers(num_workers: int, num_shards: int = 16):
    """
    Distribute shards across workers with redundancy

    Example with 5 workers, 16 shards:
    - Worker 0: shards [0, 5, 10, 15]
    - Worker 1: shards [1, 6, 11]
    - Worker 2: shards [2, 7, 12]
    - Worker 3: shards [3, 8, 13]
    - Worker 4: shards [4, 9, 14]
    """
    assignments = defaultdict(list)
    for shard in range(num_shards):
        worker = shard % num_workers
        assignments[worker].append(shard)
    return assignments
```

## Phase 5: Migration Timeline (Week 3-4)

### Day 1-2: Deploy Infrastructure
```bash
# Deploy Redis with higher memory for sharded streams
kubectl apply -f redis-sharded.yaml

# Create consumer groups for all shards
for shard in {0..15}; do
  redis-cli XGROUP CREATE task:ready:$shard execution-workers-$shard 0
done
```

### Day 3-5: Deploy Workers
```bash
# Start with read-only workers (monitoring)
kubectl apply -f workers-readonly.yaml

# Verify they're consuming correctly
kubectl logs -l app=execution-worker --tail=100
```

### Day 6-7: Enable Dual Write
```python
# Enable sharding in SystemManager
ENABLE_SHARDING = True
DUAL_WRITE = True  # Write to both old and new streams
```

### Day 8-9: Gradual Traffic Shift
```python
# Increase worker traffic percentage
WORKER_PERCENTAGE = 0.1  # 10%
# Monitor metrics
WORKER_PERCENTAGE = 0.5  # 50%
# If stable
WORKER_PERCENTAGE = 1.0  # 100%
```

### Day 10: Cleanup
```python
# Disable old path
DUAL_WRITE = False
ENABLE_OLD_PATH = False
```

## Monitoring & Metrics

### Per-Shard Metrics
```python
class ShardMetrics:
    async def get_shard_health(self):
        metrics = {}
        for shard in range(16):
            metrics[f"shard_{shard}"] = {
                "pending_tasks": await redis.xlen(f"task:ready:{shard}"),
                "completed_today": await redis.get(f"metrics:completed:{shard}:{today}"),
                "avg_latency_ms": await redis.get(f"metrics:latency:{shard}"),
                "active_workflows": await redis.scard(f"workflows:active:{shard}")
            }
        return metrics
```

### Load Balancing Alert
```python
def check_shard_balance(metrics):
    """Alert if shard imbalance > 30%"""
    loads = [m["pending_tasks"] for m in metrics.values()]
    avg_load = sum(loads) / len(loads)
    max_deviation = max(abs(load - avg_load) / avg_load for load in loads)

    if max_deviation > 0.3:
        alert("Shard imbalance detected", max_deviation)
```

## Benefits of This Approach

### 1. **Workflow Locality**
- All tasks from workflow stay on same shard
- Dependencies resolved locally
- Cache efficiency maximized

### 2. **Gradual Migration**
- No downtime required
- Can rollback instantly
- A/B testing possible

### 3. **Linear Scalability**
- Add workers to scale
- Add shards if needed
- Geographic distribution ready

### 4. **Simple Operations**
```bash
# Scale up
kubectl scale statefulset execution-workers --replicas=32

# Scale down
kubectl scale statefulset execution-workers --replicas=8
```

## Success Metrics

| Metric | Current | Target | Achieved |
|--------|---------|--------|----------|
| Throughput | 100 tasks/sec | 10,000 tasks/sec | |
| Latency P99 | 500ms | 50ms | |
| Workflow Completion | 60s avg | 6s avg | |
| Horizontal Scale | No | Yes | |
| Geographic Distribution | No | Yes | |

## Conclusion

This plan transforms the monolithic SystemManager into a distributed, sharded, worker-based architecture while:
- **Maintaining workflow locality** through consistent sharding
- **Enabling gradual migration** with dual-mode operation
- **Providing linear scalability** through worker addition
- **Ensuring zero downtime** during transition

The key innovation is **workflow-based sharding** which keeps all related tasks together, making the system both efficient and debuggable!