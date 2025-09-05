# Scaling Existing Gleitzeit Components

## Overview
This document outlines how to enhance the EXISTING Gleitzeit components for horizontal scaling without replacing them. Based on analysis of the current architecture, we can achieve scaling through minimal, targeted improvements.

## Current Architecture Strengths
- **EventDrivenWorkflowManager**: Already tracks workflow state via events
- **QueueManager**: Already manages task queues with persistence
- **RetryManager**: Already handles retry logic with backoff strategies  
- **ExecutionEngine**: Already coordinates task execution with providers

## Key Insight: The Components Are Good, Just Need Distribution

### Problem 1: Single ExecutionEngine Instance
**Current State:**
```python
# Only one instance with hardcoded limit
self.max_concurrent_tasks = max_concurrent_tasks or 10
```

**Solution: Make ExecutionEngine Distributable**
```python
class ExecutionEngine:
    def __init__(self, ..., node_id: str = None, partition_key: str = None):
        self.node_id = node_id or f"engine-{uuid.uuid4()}"
        self.partition_key = partition_key  # For task assignment
        
    def _should_handle_task(self, task_id: str) -> bool:
        """Check if this engine instance should handle this task"""
        if not self.partition_key:
            return True  # No partitioning, handle all
        # Use consistent hashing for distribution
        return hash(task_id) % num_engines == self.partition_id
```

### Problem 2: QueueManager Polls All Tasks
**Current State:**
```python
# Scans all pending tasks repeatedly
async def _check_and_enqueue_ready_tasks(self):
    pending_tasks = await self.persistence.get_pending_tasks()
```

**Solution: Event-Driven Task Readiness**
```python
class QueueManager:
    async def _on_task_completed(self, event: GleitzeitEvent):
        """When task completes, check its dependents"""
        completed_task_id = event.data['task_id']
        workflow_id = event.data['workflow_id']
        
        # Only check tasks that depend on the completed one
        dependent_tasks = await self.persistence.get_dependent_tasks(completed_task_id)
        for task in dependent_tasks:
            if await self._are_dependencies_satisfied(task):
                await self._enqueue_task(task)
```

### Problem 3: EventDrivenWorkflowManager Duplicate Processing
**Current State:**
```python
# In-memory set doesn't work across instances
self._processing_workflows: Set[str] = set()
```

**Solution: Use Redis for Distributed Locking**
```python
class EventDrivenWorkflowManager:
    async def _on_task_completed(self, event: GleitzeitEvent):
        workflow_id = event.data.get('workflow_id')
        
        # Use Redis distributed lock
        lock_key = f"workflow:lock:{workflow_id}:complete"
        if not await self.redis.set(lock_key, "1", nx=True, ex=5):
            return  # Another instance is handling it
        
        try:
            await self._check_workflow_completion(workflow_id)
        finally:
            await self.redis.delete(lock_key)
```

## Minimal Changes for Maximum Impact

### 1. Add Node ID to Components
```python
# Small change to each component's __init__
def __init__(self, ..., node_id: str = None):
    self.node_id = node_id or f"{component_name}-{uuid.uuid4()}"
```

### 2. Add Task Partitioning to ExecutionEngine
```python
# In ExecutionEngine._on_task_ready
async def _on_task_ready(self, event: GleitzeitEvent):
    task_id = event.data['task_id']
    
    # Only process if assigned to this engine
    if not self._should_handle_task(task_id):
        return
    
    # Rest of existing logic...
```

### 3. Add Dependency Index to Persistence
```python
# New method in PersistenceBackend
async def get_dependent_tasks(self, task_id: str) -> List[Task]:
    """Get tasks that depend on the given task"""
    # Redis: Use sorted sets for dependency tracking
    # SQL: Add index on dependencies column
```

### 4. Use Redis Pub/Sub for Event Distribution
```python
# In EventBus
class EventBus:
    async def emit(self, event: GleitzeitEvent):
        # Existing: notify local handlers
        await self._notify_local_handlers(event)
        
        # New: publish to Redis for other instances
        if self.redis:
            channel = f"events:{event.event_type}"
            await self.redis.publish(channel, event.to_json())
```

## Implementation Phases

### Phase 1: Enable Multiple Engines (1 week)
1. Add node_id to ExecutionEngine
2. Add partition-based task assignment
3. Test with 2-3 engine instances

### Phase 2: Optimize Queue Manager (1 week)
1. Add dependency indexing to persistence
2. Implement event-driven dependency checking
3. Remove polling for ready tasks

### Phase 3: Distributed Event Bus (2 weeks)
1. Add Redis pub/sub to EventBus
2. Add distributed locking to WorkflowManager
3. Test cross-instance event handling

### Phase 4: Production Hardening (1 week)
1. Add health checks and monitoring
2. Implement graceful shutdown
3. Add automatic rebalancing

## Configuration Example

```python
# Launch multiple engine instances
engine1 = ExecutionEngine(
    persistence=redis_backend,
    event_bus=event_bus,
    node_id="engine-1",
    partition_key=0,
    total_partitions=3
)

engine2 = ExecutionEngine(
    persistence=redis_backend,
    event_bus=event_bus,
    node_id="engine-2", 
    partition_key=1,
    total_partitions=3
)

engine3 = ExecutionEngine(
    persistence=redis_backend,
    event_bus=event_bus,
    node_id="engine-3",
    partition_key=2,
    total_partitions=3
)
```

## Benefits of This Approach

1. **Minimal Code Changes**: Most components stay exactly the same
2. **Backward Compatible**: Can run single-instance or multi-instance
3. **Gradual Migration**: Can enable scaling one component at a time
4. **Preserves Architecture**: Keeps event-driven design intact
5. **Low Risk**: Each change is small and testable

## Comparison with MVP Approach

| Aspect | MVP (New Components) | This Approach (Enhance Existing) |
|--------|---------------------|----------------------------------|
| Code Changes | ~2000 lines new code | ~200 lines modifications |
| Risk | High (new architecture) | Low (incremental changes) |
| Testing | Need full test suite | Can use existing tests |
| Migration | Big bang replacement | Gradual rollout |
| Time to Production | 2-3 months | 3-4 weeks |

## Next Steps

1. **Validate Approach**: Test partition-based task assignment
2. **Prototype**: Add node_id to ExecutionEngine and test with 2 instances
3. **Measure**: Benchmark throughput improvement
4. **Iterate**: Apply same pattern to other components

## Conclusion

The existing Gleitzeit components are well-designed and don't need replacement. By adding:
- Node IDs for instance identification
- Partition-based work distribution
- Redis-based distributed coordination
- Event-driven dependency resolution

We can achieve horizontal scaling with minimal changes while preserving the existing architecture's strengths.