# Workflow ID Sharding Strategy for Streams

## The Problem

When we shard streams, we need to ensure:
1. All tasks from the same workflow go to the same shard (locality)
2. Load is evenly distributed across shards
3. Workers can efficiently process related tasks
4. Dependencies are resolved quickly

## Sharding Strategies

### Strategy 1: Workflow-Based Sharding (RECOMMENDED)

All events for a workflow go to the same shard:

```python
def get_shard(workflow_id: str, num_shards: int = 16) -> int:
    """Shard by workflow ID for locality"""
    return hash(workflow_id) % num_shards
```

**Stream Structure:**
```
task:ready:0         # All tasks from workflows that hash to shard 0
task:ready:1         # All tasks from workflows that hash to shard 1
...
task:ready:15        # All tasks from workflows that hash to shard 15

task:completed:0     # Completions for workflows in shard 0
task:completed:1     # Completions for workflows in shard 1
...
```

**Advantages:**
- ✅ Workflow locality - all tasks from same workflow on same shard
- ✅ Efficient dependency resolution - dependencies are local
- ✅ Cache efficiency - worker caches workflow data
- ✅ Simpler debugging - one workflow = one shard

**Disadvantages:**
- ❌ Potential hotspots if one workflow has many tasks
- ❌ Uneven distribution if workflow sizes vary greatly

### Strategy 2: Task-Based Sharding (NOT RECOMMENDED)

Each task sharded independently:

```python
def get_shard(task_id: str, num_shards: int = 16) -> int:
    """Shard by task ID - DON'T DO THIS!"""
    return hash(task_id) % num_shards
```

**Problems:**
- ❌ Tasks from same workflow scattered across shards
- ❌ Dependency resolution requires cross-shard communication
- ❌ No cache locality
- ❌ Complex coordination

### Strategy 3: Hybrid Sharding (ADVANCED)

Different sharding for different event types:

```python
def get_shard(event_type: str, workflow_id: str, task_id: str = None) -> int:
    if event_type in ['workflow:submitted', 'workflow:completed']:
        # Workflow events by workflow
        return hash(workflow_id) % NUM_WORKFLOW_SHARDS

    elif event_type in ['task:ready', 'task:executing']:
        # Task execution by workflow for locality
        return hash(workflow_id) % NUM_TASK_SHARDS

    elif event_type in ['task:completed', 'task:failed']:
        # Completions by workflow for dependency resolution
        return hash(workflow_id) % NUM_TASK_SHARDS

    elif event_type == 'logs':
        # Logs can be randomly distributed
        return random.randint(0, NUM_LOG_SHARDS - 1)
```

## Implementation with Workflow Sharding

### 1. Stream Key Generation

```python
class StreamKeyGenerator:
    """Generate sharded stream keys based on workflow"""

    def __init__(self, num_shards: int = 16):
        self.num_shards = num_shards

    def get_task_stream(self, event_type: str, workflow_id: str) -> str:
        """Get sharded stream key for task events"""
        shard = hash(workflow_id) % self.num_shards
        return f"{event_type}:{shard}"

    def get_workflow_stream(self, event_type: str, workflow_id: str) -> str:
        """Get sharded stream key for workflow events"""
        shard = hash(workflow_id) % self.num_shards
        return f"{event_type}:{shard}"
```

### 2. Worker Assignment

Workers consume from specific shards:

```python
class ShardedWorker:
    def __init__(self, worker_id: str, assigned_shards: List[int]):
        """Worker handles specific shards"""
        self.worker_id = worker_id
        self.assigned_shards = assigned_shards

    def get_streams(self) -> Dict[str, str]:
        """Get streams for assigned shards"""
        streams = {}
        for shard in self.assigned_shards:
            streams[f"task:ready:{shard}"] = ">"
            streams[f"task:completed:{shard}"] = ">"
        return streams
```

### 3. Workflow Submission with Sharding

```python
async def submit_workflow(workflow: Workflow):
    """Submit workflow with proper sharding"""

    # Calculate shard for this workflow
    shard = hash(workflow.id) % NUM_SHARDS

    # Emit workflow submission to sharded stream
    await redis.xadd(f"workflow:submitted:{shard}", {
        "workflow_id": workflow.id,
        "workflow": workflow.to_json()
    })

    # Emit initial tasks to same shard
    for task in workflow.get_initial_tasks():
        await redis.xadd(f"task:ready:{shard}", {
            "task_id": task.id,
            "workflow_id": workflow.id,
            "task": task.to_json()
        })
```

### 4. Dependency Resolution with Locality

```python
class LocalDependencyResolver:
    """Resolve dependencies within same shard"""

    async def on_task_completed(self, task_id: str, workflow_id: str):
        """Handle task completion in same shard"""

        # Get shard for this workflow
        shard = hash(workflow_id) % NUM_SHARDS

        # Check dependencies (all in same shard!)
        ready_tasks = await self.check_dependencies(workflow_id, task_id)

        # Emit ready tasks to same shard
        for task in ready_tasks:
            await redis.xadd(f"task:ready:{shard}", {
                "task_id": task.id,
                "workflow_id": workflow_id,
                "task": task.to_json()
            })
```

## Shard Configuration

### Development (Few Shards)
```yaml
sharding:
  num_shards: 4
  workers_per_shard: 1
```

### Production (Many Shards)
```yaml
sharding:
  num_shards: 16
  workers_per_shard: 3  # Redundancy
```

### High Scale (Dynamic Sharding)
```yaml
sharding:
  num_shards: 64
  workers_per_shard: 5
  rebalance_threshold: 0.3  # Rebalance if load imbalance > 30%
```

## Load Balancing Considerations

### Problem: Workflow Size Imbalance
Some workflows have 10 tasks, others have 10,000.

### Solution: Dynamic Weight-Based Sharding
```python
class WeightedShardSelector:
    def __init__(self):
        self.shard_loads = [0] * NUM_SHARDS

    async def get_shard_for_workflow(self, workflow: Workflow) -> int:
        """Assign to least loaded shard"""

        # Estimate workflow weight
        weight = len(workflow.tasks)

        # Find least loaded shard
        min_load_shard = self.shard_loads.index(min(self.shard_loads))

        # Update load tracking
        self.shard_loads[min_load_shard] += weight

        # Store mapping
        await redis.set(f"workflow:shard:{workflow.id}", min_load_shard)

        return min_load_shard
```

## Consumer Group Strategy

Each shard has its own consumer group:

```python
# Create consumer groups per shard
for shard in range(NUM_SHARDS):
    await redis.xgroup_create(
        f"task:ready:{shard}",
        f"execution-workers-shard-{shard}",
        id='0'
    )
```

## Monitoring Shards

Track metrics per shard:

```python
class ShardMetrics:
    async def get_shard_stats(self) -> Dict:
        stats = {}
        for shard in range(NUM_SHARDS):
            stats[shard] = {
                "pending_tasks": await redis.xlen(f"task:ready:{shard}"),
                "completed_tasks": await redis.xlen(f"task:completed:{shard}"),
                "active_workers": len(self.get_workers_for_shard(shard))
            }
        return stats
```

## Migration from Unsharded

### Step 1: Dual Write
```python
async def emit_task(task):
    # Write to both old and new streams
    await redis.xadd("gleitzeit:events:stream:task:ready", task)  # Old

    shard = hash(task.workflow_id) % NUM_SHARDS
    await redis.xadd(f"task:ready:{shard}", task)  # New
```

### Step 2: Dual Read
Workers consume from both old and sharded streams.

### Step 3: Switch Writers
Stop writing to old streams.

### Step 4: Drain Old Streams
Process remaining messages in old streams.

### Step 5: Remove Old Code
Delete old stream patterns.

## Benefits of Workflow-Based Sharding

1. **Locality**: All tasks from a workflow stay together
2. **Efficiency**: Dependencies resolved locally
3. **Caching**: Worker can cache workflow data
4. **Debugging**: Easy to trace workflow through single shard
5. **Scaling**: Add more shards as load increases

## Example: 1000-Task Workflow

Without sharding:
- All 1000 tasks go to ONE stream
- ONE worker processes sequentially
- Time: 1000 tasks × 100ms = 100 seconds

With 16 shards (workflow-based):
- All 1000 tasks go to ONE shard (locality preserved)
- 3 workers on that shard process in parallel
- Time: 1000 tasks ÷ 3 workers × 100ms = 33 seconds

With task-based sharding (BAD):
- Tasks scattered across 16 shards
- Dependency checks require cross-shard communication
- Time: Unpredictable due to coordination overhead

## Conclusion

**Workflow-based sharding** is the optimal strategy because it:
- Maintains locality for efficient processing
- Enables parallel processing across different workflows
- Simplifies dependency resolution
- Provides predictable performance

The key insight: **Workflows are the natural unit of sharding** because tasks within a workflow are related, while different workflows are independent!