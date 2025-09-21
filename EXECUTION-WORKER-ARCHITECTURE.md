# Core Execution Worker Architecture

## Current Execution Architecture

The execution core consists of:
1. **ExecutionEngineV2** - Thin coordination layer
2. **StatelessTaskOrchestrator** - Event-driven task coordination (no loops)
3. **TaskExecutor** - Actual task execution against providers
4. **QueueManager** - Task distribution
5. **DependencyManager** - Dependency resolution

## The Scalability Problem

### Current Bottlenecks:
1. **Single Orchestrator Instance** - Even with leader election, only one processes tasks
2. **Provider Execution** - All task execution goes through single pooling adapter
3. **Dependency Resolution** - Complex workflows create cascading dependencies
4. **Queue Processing** - Single consumer per queue

### What Happens Now:
```
API receives task → Emits task:ready → Single Orchestrator picks up → Executes serially
```

## Proposed: Execution Workers

### 1. **TaskExecutionWorker** (CRITICAL)
Break task execution into dedicated workers that:
- Consume from `task:ready` streams
- Execute tasks against providers
- Emit completion events
- Scale horizontally per task load

```python
class TaskExecutionWorker:
    """
    Dedicated worker for task execution.
    Multiple instances can run in parallel.
    """
    def __init__(self, worker_id: str, shard_id: int = None):
        self.worker_id = worker_id
        self.shard_id = shard_id  # For sharded execution

    async def run(self):
        # Consumer group ensures each task processed once
        while True:
            messages = await redis.xreadgroup(
                "execution-workers",
                self.worker_id,
                {"task:ready:*": ">"},
                block=5000
            )
            for stream, task_data in messages:
                await self.execute_task(task_data)

    async def execute_task(self, task_data):
        # Get provider from pool
        provider = await self.get_provider(task_data.protocol)
        # Execute task
        result = await provider.execute(task_data)
        # Emit result
        await self.emit_task_result(result)
```

### 2. **WorkflowCoordinatorWorker** (HIGH)
Coordinate workflow progression without centralized orchestrator:
- Monitor task completions
- Check workflow dependencies
- Emit next tasks
- Update workflow status

```python
class WorkflowCoordinatorWorker:
    """
    Coordinates workflow progression.
    Stateless, event-driven.
    """
    async def run(self):
        # Listen for task completions
        while True:
            messages = await redis.xreadgroup(
                "workflow-coordinators",
                self.worker_id,
                {"task:completed:*": ">", "task:failed:*": ">"},
                block=5000
            )
            for stream, event in messages:
                await self.handle_task_event(event)

    async def handle_task_event(self, event):
        # Check if workflow can progress
        workflow = await self.get_workflow(event.workflow_id)
        ready_tasks = await self.check_dependencies(workflow)
        for task in ready_tasks:
            await self.emit_task_ready(task)
```

### 3. **QueueDistributorWorker** (MEDIUM)
Distribute tasks across execution workers:
- Smart routing based on load
- Shard assignment
- Priority handling
- Backpressure management

```python
class QueueDistributorWorker:
    """
    Distributes tasks to execution workers.
    Handles sharding and load balancing.
    """
    async def run(self):
        while True:
            # Get pending tasks
            tasks = await redis.xreadgroup(
                "queue-distributors",
                self.worker_id,
                {"task:pending:*": ">"},
                block=5000
            )
            for stream, task in tasks:
                shard = self.calculate_shard(task)
                await redis.xadd(f"task:ready:{shard}", task)
```

## Sharding Strategy

### Task Sharding
Distribute tasks across workers using consistent hashing:

```python
def calculate_shard(task) -> int:
    # Shard by workflow to maintain locality
    workflow_hash = hash(task.workflow_id)
    return workflow_hash % NUM_SHARDS
```

### Benefits:
- **Workflow Locality** - Tasks from same workflow on same shard
- **Load Distribution** - Even distribution across shards
- **Scalability** - Add shards as load increases

## Provider Pooling at Scale

### Current Problem:
Single PoolingAdapter becomes bottleneck

### Solution: Distributed Provider Pools
```python
class DistributedProviderPool:
    """
    Each execution worker has local pool.
    Pools coordinate via Redis for limits.
    """
    def __init__(self, worker_id: str):
        self.local_pool = {}  # Local provider instances
        self.global_limits = {}  # Redis-tracked limits

    async def get_provider(self, protocol: str):
        # Check local pool first
        if protocol in self.local_pool:
            return self.local_pool[protocol]

        # Check global availability
        if await self.can_create_provider(protocol):
            provider = await self.create_provider(protocol)
            self.local_pool[protocol] = provider
            return provider

        # Wait for available slot
        return await self.wait_for_provider(protocol)
```

## Execution Flow with Workers

### Before (Centralized):
```
Task Submitted
    ↓
Single Orchestrator
    ↓
Single TaskExecutor
    ↓
Single PoolingAdapter
    ↓
Provider Execution
```

### After (Distributed):
```
Task Submitted
    ↓
Queue Distributor (multiple)
    ↓ (sharding)
Execution Workers (many)
    ↓ (parallel)
Local Provider Pools
    ↓
Parallel Execution
```

## Implementation Phases

### Phase 1: TaskExecutionWorker
- Core execution parallelization
- Immediate scalability improvement
- Works with existing orchestrator

### Phase 2: WorkflowCoordinatorWorker
- Distributed workflow coordination
- Remove orchestrator bottleneck
- Event-driven progression

### Phase 3: Distributed Provider Pools
- Local pools per worker
- Global coordination via Redis
- Dynamic provider scaling

### Phase 4: Advanced Features
- Auto-scaling based on queue depth
- Intelligent task routing
- Circuit breakers
- Backpressure handling

## Configuration

```yaml
execution:
  workers:
    execution:
      count: 10  # Number of execution workers
      shards: 8  # Number of shards
      max_concurrent: 5  # Tasks per worker

    coordination:
      count: 3  # Workflow coordinators

    distribution:
      count: 2  # Queue distributors

  providers:
    python:
      max_global: 100  # Global limit
      per_worker: 10   # Per-worker limit
```

## Benefits

### Scalability
- **Horizontal scaling** - Add workers as needed
- **No single bottleneck** - Distributed at every layer
- **Linear scaling** - Performance scales with workers

### Reliability
- **Fault isolation** - Worker failure doesn't affect others
- **No single point of failure** - Multiple coordinators
- **Automatic recovery** - Consumer groups handle failures

### Performance
- **Parallel execution** - Multiple tasks simultaneously
- **Local provider pools** - Reduced contention
- **Sharded distribution** - Even load spreading

## Comparison with Current Architecture

| Component | Current | Proposed |
|-----------|---------|----------|
| Task Execution | Single Orchestrator | Multiple Execution Workers |
| Provider Access | Single PoolingAdapter | Distributed Local Pools |
| Workflow Coordination | Single Orchestrator | Multiple Coordinator Workers |
| Queue Processing | Single Consumer | Sharded Consumers |
| Scalability | Vertical (bigger machine) | Horizontal (more workers) |
| Fault Tolerance | Leader Election | Consumer Groups |
| Max Throughput | ~100 tasks/sec | ~10,000+ tasks/sec |

## Migration Path

### Step 1: Add TaskExecutionWorkers
- Keep existing orchestrator for coordination
- Workers handle execution only
- Immediate parallelization benefit

### Step 2: Add WorkflowCoordinatorWorkers
- Gradually move coordination logic
- Orchestrator becomes optional
- Full distributed coordination

### Step 3: Distributed Pools
- Each worker gets local pool
- Redis coordinates global limits
- Maximum scalability achieved

## Conclusion

The core execution MUST be converted to workers for true scalability:
- **TaskExecutionWorker** - Parallel task execution
- **WorkflowCoordinatorWorker** - Distributed coordination
- **QueueDistributorWorker** - Smart task distribution
- **Distributed Provider Pools** - Local pools with global coordination

This architecture can scale to 10,000+ tasks/second across hundreds of workers, compared to current ~100 tasks/second limit.