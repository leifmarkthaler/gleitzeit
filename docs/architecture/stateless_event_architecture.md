# Stateless Event Architecture

## Overview

This document explains how Gleitzeit maintains its stateless, scalable architecture while providing comprehensive event tracking and replay capabilities. The key insight: we store **facts** (what happened) in Redis, not **state** (worker memory).

## Core Principle: Stateless Workers with Event Emission

### What Makes a Worker Stateless?

A stateless worker:
1. **Processes one message at a time**
2. **Reads all needed data from external storage (Redis)**
3. **Computes results (pure functions)**
4. **Writes results back to storage**
5. **Holds NO state between messages**

### How Events Maintain Statelessness

```python
class DependencyWorker(BaseWorker):
    async def process_message(self, stream: str, message_id: bytes, data: Dict):
        # 1. Read from Redis (source of truth)
        workflow = await self.redis.get("workflow:data:...")

        # 2. Compute (pure function - no stored state)
        ready_tasks = self.find_ready_tasks(workflow)

        # 3. Write results back to Redis
        await self.redis.xadd("task:ready", ready_tasks)

        # 4. Emit event (fire-and-forget, no state)
        await self.event_store.store_event(
            event_type=EventType.TASK_READY,
            workflow_id=workflow_id,
            task_id=task_id
        )

        # Worker holds NOTHING after message completes!
```

## Architecture Decisions That Preserve Statelessness

### 1. Event Store is Just a Redis Wrapper

```python
class EventStore:
    """Not a state container - just a Redis writer"""

    async def store_event(self, event_type, workflow_id, task_id, data):
        # Simply appends to Redis stream
        await self.redis.xadd(
            f"events:{workflow_id}",
            {"type": event_type, "task": task_id, "data": json.dumps(data)}
        )
        # No state maintained in EventStore!
```

The EventStore:
- ✅ Writes to Redis streams (stateless operation)
- ✅ Fire-and-forget pattern (no waiting for confirmation)
- ❌ Does NOT maintain any in-memory state
- ❌ Does NOT coordinate between workers

### 2. Parameter Resolution Remains Pure

We explicitly chose NOT to store resolved parameters:

```python
# Parameters are computed on-demand (pure function)
def resolve_parameters(workflow_definition, task_results):
    # Pure computation - same inputs always produce same outputs
    resolved = {}
    for param in workflow_definition.params:
        if param.startswith("${"):
            resolved[param] = lookup_from_results(param, task_results)
        else:
            resolved[param] = param
    return resolved

# NOT stored - recomputed each time needed
```

This maintains the key property:
- **Stateless**: `f(workflow_def, task_results) → resolved_params`
- **Deterministic**: Same inputs always produce same outputs
- **No duplication**: Single source of truth

### 3. Events Don't Create Dependencies

Events are **observational**, not **operational**:

```python
# WRONG - Event required for operation
async def process_task(task):
    event = await wait_for_event()  # ❌ Creates state dependency
    if event:
        execute(task)

# RIGHT - Event is just observation
async def process_task(task):
    result = execute(task)          # ✅ Operation happens regardless
    await emit_event(result)         # ✅ Event is just notification
    return result
```

## Scalability Analysis

### Horizontal Scaling Unchanged

Workers scale exactly as before:

```yaml
# Scaling is identical with or without events
task_execution_worker:
  replicas: 10  # Each processes tasks independently

dependency_worker:
  replicas: 5   # Each processes completions independently

# Adding events doesn't change scaling model
```

### Why Events Don't Affect Scaling

1. **No Inter-Worker Communication**
   ```python
   # Workers still don't talk to each other
   Worker1 → Redis ← Worker2
   ```

2. **Append-Only Operations** (O(1) complexity)
   ```python
   # Appending events is constant time
   await redis.xadd("events:wf123", event)  # ~0.5ms always
   ```

3. **Sharded by Workflow**
   ```
   Workflow A events → {shard:1}:events:workflowA
   Workflow B events → {shard:2}:events:workflowB
   # No cross-shard operations needed
   ```

### Performance Impact

```python
# Before (without events):
async def complete_task(task_id, result):
    await redis.hset(f"task:{task_id}", {
        "status": "completed",
        "result": result
    })  # ~0.5ms

# After (with events):
async def complete_task(task_id, result):
    # Original operation unchanged
    await redis.hset(f"task:{task_id}", {
        "status": "completed",
        "result": result
    })  # ~0.5ms

    # Event emission is async/fire-and-forget
    asyncio.create_task(
        event_store.store_event(EventType.TASK_COMPLETED, ...)
    )  # ~0.5ms but doesn't block

    # Total blocking time: still ~0.5ms
```

## Proof of Statelessness

### Kill Test
```bash
# Kill any worker at any time
kill -9 <worker_pid>

# Another worker immediately picks up
# No state lost because there was no state to lose
```

### Scale Test
```bash
# Scale from 1 to 100 workers
kubectl scale deployment task-worker --replicas=100

# All 100 can process simultaneously
# No coordination needed between them
```

### Restart Test
```bash
# Restart entire system
docker-compose down
docker-compose up

# Workflows continue from exact point
# All state in Redis, none in workers
```

### Location Independence
```python
# Run workers anywhere - they're stateless
Worker(region="us-east")  # Process task A
Worker(region="eu-west")  # Process task B
Worker(region="ap-south") # Process task C
# All work on same Redis, no affinity needed
```

## Event Storage Strategy

### Bounded Growth

Events are automatically trimmed to prevent unbounded growth:

```python
await redis.xadd(
    stream_key,
    event_data,
    maxlen=10000,      # Keep only last 10k events
    approximate=True   # Allow Redis to optimize trimming
)
```

### Sharding Maintains Locality

```
Events follow workflow sharding:
├── {shard:0}
│   ├── events:workflow_001  (max 10k events)
│   ├── events:workflow_002  (max 10k events)
│   └── events:workflow_003  (max 10k events)
├── {shard:1}
│   ├── events:workflow_004  (max 10k events)
│   └── events:workflow_005  (max 10k events)
```

Each workflow's events stay on the same shard as its tasks - maintaining data locality.

## Replay Maintains Statelessness

### Replay Worker is Also Stateless

```python
class ReplayWorker(BaseWorker):
    async def replay_workflow(self, workflow_id: str):
        # 1. Read current state from Redis
        workflow = await self.redis.get(f"workflow:data:{workflow_id}")
        timeline = await self.redis.xrange(f"events:{workflow_id}")

        # 2. Compute what needs replay (pure function)
        tasks_to_clear = self.compute_replay_tasks(workflow, timeline)

        # 3. Write changes back to Redis
        for task in tasks_to_clear:
            await self.redis.delete(f"task:result:{task}")

        # 4. Re-submit to existing workers
        await self.redis.xadd("workflow:submitted", workflow)

        # No state held - existing workers handle normally!
```

### Replay Doesn't Break Statelessness

- **No special replay mode** - Workers process normally
- **No replay state** - Just cleared results and re-submission
- **No coordination** - Workers don't know it's a replay

## Comparison: Stateful vs Stateless Events

### ❌ WRONG: Stateful Event System
```python
class StatefulWorker:
    def __init__(self):
        self.events = []  # ❌ In-memory state
        self.processed_tasks = {}  # ❌ Worker state

    async def process(self, task):
        self.events.append(task)  # ❌ Accumulating state
        if task.id in self.processed_tasks:  # ❌ Checking memory
            return self.processed_tasks[task.id]
        result = await execute(task)
        self.processed_tasks[task.id] = result  # ❌ Storing state
```

### ✅ RIGHT: Stateless Event System (Gleitzeit)
```python
class StatelessWorker:
    # No __init__ with state!

    async def process(self, task):
        # Everything from Redis
        existing = await redis.get(f"task:result:{task.id}")
        if existing:
            return existing

        result = await execute(task)

        # Everything to Redis
        await redis.set(f"task:result:{task.id}", result)
        await redis.xadd(f"events:{task.workflow_id}", {
            "type": "completed",
            "task": task.id,
            "result": result
        })

        # Nothing held in worker!
```

## Design Principles

### 1. Facts, Not State
- ✅ Store "Task X completed at time T" (fact in Redis)
- ❌ Don't store "Worker Y is processing X" (state in memory)

### 2. Append-Only Events
- ✅ Events are immutable and append-only
- ❌ Never update or delete events
- ❌ Never query events during execution

### 3. Fire-and-Forget Emission
- ✅ Emit events asynchronously
- ❌ Don't wait for event confirmation
- ❌ Don't depend on event ordering

### 4. Computation Over Storage
- ✅ Recompute parameters from source data
- ❌ Don't store computed values
- ❌ Don't cache in workers

## Performance Characteristics

| Operation | Without Events | With Events | Impact |
|-----------|---------------|-------------|---------|
| Task Start | ~1ms | ~1.5ms | +0.5ms async |
| Task Complete | ~1ms | ~1.5ms | +0.5ms async |
| Parameter Resolution | ~2ms | ~2ms | No change |
| Workflow Submit | ~5ms | ~5.5ms | +0.5ms |
| Scaling to 100 workers | Instant | Instant | No change |
| Worker Restart | Instant | Instant | No change |

## Monitoring Statelessness

### Metrics to Watch

```python
# Good - Stateless operation
redis_operations_per_second: 10000  # ✅ High throughput
worker_memory_usage: 50MB  # ✅ Constant memory
event_emission_latency: 0.5ms  # ✅ Consistent

# Bad - Stateful behavior
worker_memory_usage: 500MB+  # ❌ Growing = state accumulation
inter_worker_messages: > 0  # ❌ Workers talking = coordination
event_query_during_execution: > 0  # ❌ Reading events = dependency
```

## Conclusion

Gleitzeit's event system maintains complete statelessness by:

1. **Treating events as facts, not state** - Events record what happened, not what's happening
2. **Using Redis as the single source of truth** - All data lives in Redis, none in workers
3. **Keeping workers independent** - No coordination, communication, or shared state
4. **Computing over storing** - Parameters resolved on-demand, not cached
5. **Appending asynchronously** - Events don't block or create dependencies

This architecture ensures that adding comprehensive event tracking and replay capabilities doesn't compromise the core benefits of a stateless, scalable workflow system. Workers remain disposable, scalable, and location-independent while providing complete visibility into workflow execution.