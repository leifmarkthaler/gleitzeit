# System Manager to Workers Transition Plan

## Current Architecture Analysis

### ModularStreamSystemManager
The system manager currently handles EVERYTHING:
- Event bus management
- Workflow execution
- Task orchestration
- Provider management
- Dependency resolution
- Monitoring
- Authentication

**Key Issue**: `process_all_once()` method tries to process everything in one go - not scalable!

### Stream Naming Convention
Current pattern: `gleitzeit:events:stream:{event_type}`

Examples:
```
gleitzeit:events:stream:task:ready
gleitzeit:events:stream:task:completed
gleitzeit:events:stream:workflow:submitted
```

**Problem**: No sharding! All tasks go to one stream.

## Required Changes for Worker Architecture

### 1. Stream Sharding Strategy

#### Current (No Sharding)
```
gleitzeit:events:stream:task:ready  # ALL tasks
```

#### New (With Sharding)
```
task:ready:0     # Shard 0
task:ready:1     # Shard 1
...
task:ready:15    # Shard 15
```

Sharding function:
```python
def get_shard(workflow_id: str, num_shards: int = 16) -> int:
    return hash(workflow_id) % num_shards
```

### 2. Decouple Components from SystemManager

#### Current (Tightly Coupled)
```python
class StreamWorker:
    def __init__(self, system_manager):
        self.redis = system_manager.persistence.redis
        self.event_bus = system_manager.event_bus
```

#### New (Standalone)
```python
class StreamWorker:
    def __init__(self, redis_url: str, config: WorkerConfig):
        self.redis = await aioredis.from_url(redis_url)
        self.config = config
```

### 3. Split SystemManager Responsibilities

Transform monolithic manager into coordinator that emits events:

```python
class LightweightSystemManager:
    """Minimal manager that just emits events for workers"""

    async def submit_workflow(self, workflow):
        # Don't process - just emit
        shard = get_shard(workflow.id)
        await redis.xadd(f"workflow:submit:{shard}", {
            "workflow": workflow.to_json()
        })

    async def submit_task(self, task):
        # Don't execute - just emit
        shard = get_shard(task.workflow_id)
        await redis.xadd(f"task:ready:{shard}", {
            "task": task.to_json()
        })
```

### 4. Update StreamlinedEventBus for Sharding

```python
class ShardedEventBus:
    """Event bus with sharding support"""

    async def emit(self, event, shard_key=None):
        if shard_key:
            shard = get_shard(shard_key)
            stream_key = f"{event.event_type}:{shard}"
        else:
            stream_key = event.event_type

        await redis.xadd(stream_key, event.to_dict())
```

### 5. Migration Path

#### Phase 1: Dual Mode (Week 1)
Keep SystemManager but add worker emission:

```python
class ModularStreamSystemManager:
    async def process_task(self, task):
        if ENABLE_WORKERS:
            # Emit for workers
            shard = get_shard(task.workflow_id)
            await redis.xadd(f"task:ready:{shard}", {"task": task.to_json()})
        else:
            # Old path
            await self.task_executor.execute(task)
```

#### Phase 2: Add Workers (Week 2)
Deploy workers alongside existing system:

```python
# Start workers
gleitzeit worker --type execution --count 10
gleitzeit worker --type dependency --count 5
gleitzeit worker --type loader --count 3
```

#### Phase 3: Redirect Traffic (Week 3)
Route percentage of traffic to workers:

```python
if random.random() < WORKER_PERCENTAGE:
    # Use workers
    await emit_to_workers(task)
else:
    # Use old system
    await process_directly(task)
```

#### Phase 4: Full Migration (Week 4)
Disable old processing, use only workers:

```python
ENABLE_WORKERS = True
WORKER_PERCENTAGE = 1.0
```

## Component-to-Worker Mapping

| SystemManager Component | New Worker | Stream Pattern |
|------------------------|------------|----------------|
| ExecutionEngineV2 | TaskExecutionWorker | `task:ready:{shard}` |
| WorkflowManager | WorkflowCoordinatorWorker | `workflow:submitted:{shard}` |
| DependencyManager | DependencyGraphWorker | `dependency:check:{shard}` |
| WorkflowLoaderV2 | WorkflowLoaderWorker | `workflow:load:request` |
| TaskOrchestrator | Multiple workers | Various streams |
| ProviderHub | Provider workers | `provider:{type}:request` |

## Key Code Changes

### 1. Update Event Emission
```python
# Old
await event_bus.emit(GleitzeitEvent(
    event_type=EventType.TASK_READY,
    data={"task_id": task.id}
))

# New (with sharding)
shard = get_shard(task.workflow_id)
await redis.xadd(f"task:ready:{shard}", {
    "task_id": task.id,
    "workflow_id": task.workflow_id,
    "task": json.dumps(task.to_dict())
})
```

### 2. Update Worker Consumption
```python
# Old (single stream)
streams = {"gleitzeit:events:stream:task:ready": ">"}

# New (sharded streams)
streams = {f"task:ready:{i}": ">" for i in range(NUM_SHARDS)}
```

### 3. Remove process_all_once()
Replace with individual worker triggers:

```python
# Old
async def process_all_once():
    # Process everything
    pass

# New
# Each worker processes its own stream independently
```

## Benefits of Transition

### Performance
- **Current**: Single process bottleneck
- **With Workers**: Linear scaling with worker count
- **Expected**: 10-100x throughput improvement

### Reliability
- **Current**: Single point of failure
- **With Workers**: Fault isolation, automatic recovery

### Scalability
- **Current**: Vertical scaling only
- **With Workers**: Horizontal scaling, geographic distribution

### Operations
- **Current**: Complex monolith
- **With Workers**: Simple, focused components

## Risk Mitigation

1. **Feature Flags**: Control rollout percentage
2. **Dual Mode**: Keep old system as fallback
3. **Monitoring**: Track both systems in parallel
4. **Rollback**: Can disable workers instantly
5. **Testing**: Full integration tests before cutover

## Timeline

### Week 1: Preparation
- Add sharding to event emission
- Create worker base classes
- Update CLI for worker management

### Week 2: Implementation
- Implement core workers
- Deploy to staging
- Run parallel tests

### Week 3: Migration
- Enable workers for 10% traffic
- Monitor metrics
- Fix issues

### Week 4: Completion
- Increase to 100% traffic
- Remove old code paths
- Documentation update

## Success Criteria

1. **No Performance Regression**: Same or better latency
2. **10x Throughput**: Handle 10x more workflows
3. **Zero Downtime**: Seamless migration
4. **Simple Operations**: Easy to scale workers

## Conclusion

The transition from ModularStreamSystemManager to workers requires:
1. **Sharded streams** for parallel processing
2. **Decoupled components** that don't need system_manager
3. **Event-driven architecture** where components communicate via streams
4. **Gradual migration** with feature flags and dual-mode operation

This is a **proven pattern** used by companies like Uber and Netflix to scale from monoliths to microservices!