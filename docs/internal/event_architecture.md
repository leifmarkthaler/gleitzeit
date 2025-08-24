# Gleitzeit Event-Driven Architecture - Internal Documentation

## Overview

This document describes the internal event-driven architecture of Gleitzeit, which enables real-time coordination between components without timing dependencies or polling. This architecture is currently implemented with SQLAlchemy/SQLite and needs to be replicated for the Redis adapter.

## Core Components

### 1. EventBus (`src/gleitzeit/events/base.py`)

The central event distribution system that:
- Maintains a registry of event handlers for each event type
- Distributes events to all registered handlers
- Executes handlers concurrently using `asyncio.gather()`

```python
class EventBus:
    def __init__(self):
        self._handlers: Dict[str, List[EventHandler]] = {}
    
    def register(self, event_type: str, handler: EventHandler) -> None:
        # Register handler for event type
        
    async def emit(self, event: GleitzeitEvent) -> None:
        # Emit event to all registered handlers
```

### 2. Event Types (`src/gleitzeit/core/events.py`)

Core event types in the system:
- `TASK_SUBMITTED` - Task added to queue
- `TASK_STARTED` - Task execution begins
- `TASK_COMPLETED` - Task execution succeeds
- `TASK_FAILED` - Task execution fails
- `TASK_RETRY_SCHEDULED` - Task scheduled for retry
- `WORKFLOW_SUBMITTED` - Workflow submitted
- `WORKFLOW_STARTED` - Workflow execution begins
- `WORKFLOW_COMPLETED` - Workflow finishes (all tasks done)
- `WORKFLOW_FAILED` - Workflow fails

## Event Flow Architecture

### Task Execution Flow

```
1. Client submits workflow
   ↓
2. ExecutionEngine submits tasks to QueueManager
   ↓
3. ExecutionEngine._execute_task() runs
   ↓
4. Task starts → Emit TASK_STARTED event
   ↓
5. Task completes → Emit TASK_COMPLETED event
   ↓
6. Handlers process events concurrently:
   - PersistenceTaskHandler: Updates task status in DB
   - TaskCompletedHandler: Triggers dependency resolution
   ↓
7. QueueManager checks workflow completion
   ↓
8. If all tasks done → Emit WORKFLOW_COMPLETED event
```

### Critical Design Decisions

#### 1. ExecutionEngine as Source of Truth for Results

The ExecutionEngine collects task results directly from `_execute_task()` returns and includes them in the WORKFLOW_COMPLETED event. This avoids race conditions from reading persistence.

```python
# In ExecutionEngine._execute_workflow()
all_task_results = {}
for level_index, task_ids in enumerate(execution_levels):
    level_results = await asyncio.gather(*task_futures, return_exceptions=True)
    # Collect results directly from execution
    for i, result in enumerate(level_results):
        if isinstance(result, TaskResult):
            all_task_results[task_id] = {
                "status": "completed",
                "result": result.result,
                "error": result.error
            }

# Emit with complete results
workflow_completed_event = GleitzeitEvent(
    event_type=EventType.WORKFLOW_COMPLETED,
    data={
        "workflow_id": workflow.id,
        "task_results": all_task_results,  # Direct from execution
        ...
    }
)
```

#### 2. Event Handler Registration Order

Handlers are registered in specific order but execute concurrently:
1. PersistenceTaskHandler - Updates persistence
2. TaskCompletedHandler - Handles dependencies

Both run concurrently via `asyncio.gather()` which can cause race conditions.

#### 3. Workflow Completion Detection

Two approaches were considered:

**Current Implementation (ExecutionEngine-driven):**
- ExecutionEngine emits WORKFLOW_COMPLETED after all tasks complete
- Includes all task results collected during execution
- No race conditions or timing issues

**Alternative (QueueManager-driven):**
- QueueManager detects completion via task events
- Issue: Concurrent task completions cause race conditions
- Each completion check may see partial results

## Key Event Handlers

### PersistenceTaskHandler
Updates task status in persistence for all task events:
- TASK_STARTED → status = EXECUTING
- TASK_COMPLETED → status = COMPLETED, save result
- TASK_FAILED → status = FAILED, save error

### TaskCompletedHandler
Processes task completion for workflow orchestration:
- Calls QueueManager.mark_task_completed()
- Triggers dependency resolution
- Checks workflow completion

### WorkflowCompletedHandler
Collects workflow results for client:
- Stores completed workflow data
- Resolves waiting futures for async clients
- Provides results without persistence reads

## Implementation Requirements for Redis Adapter

### 1. Event Publishing

Redis adapter must publish events to Redis pub/sub:

```python
# Example Redis event publishing
async def emit_event(self, event: GleitzeitEvent):
    channel = f"gleitzeit:events:{event.event_type}"
    event_data = json.dumps({
        "event_type": event.event_type,
        "data": event.data,
        "timestamp": event.timestamp.isoformat(),
        "source": event.source
    })
    await self.redis.publish(channel, event_data)
```

### 2. Event Subscription

Components must subscribe to relevant event channels:

```python
# Example Redis event subscription
async def subscribe_to_events(self):
    pubsub = self.redis.pubsub()
    await pubsub.subscribe(
        "gleitzeit:events:TASK_COMPLETED",
        "gleitzeit:events:WORKFLOW_COMPLETED"
    )
    
    async for message in pubsub.listen():
        if message['type'] == 'message':
            event = json.loads(message['data'])
            await self.handle_event(event)
```

### 3. Atomic Operations

Critical operations must be atomic to prevent race conditions:

```python
# Example: Atomic workflow completion check
async def check_workflow_completion_atomic(self, workflow_id: str):
    # Use Redis transaction (MULTI/EXEC) or Lua script
    script = """
    local workflow_key = KEYS[1]
    local tasks_key = KEYS[2]
    
    -- Get all task statuses atomically
    local task_statuses = redis.call('HGETALL', tasks_key)
    
    -- Check if all completed
    local all_completed = true
    for i = 1, #task_statuses, 2 do
        if task_statuses[i+1] ~= 'completed' then
            all_completed = false
            break
        end
    end
    
    -- Update workflow status atomically
    if all_completed then
        redis.call('HSET', workflow_key, 'status', 'completed')
        return 1
    end
    return 0
    """
    
    result = await self.redis.eval(
        script, 
        2, 
        f"workflow:{workflow_id}",
        f"workflow:{workflow_id}:tasks"
    )
    
    if result == 1:
        # Emit WORKFLOW_COMPLETED event
        await self.emit_workflow_completed_event(workflow_id)
```

### 4. Distributed Coordination

With Redis, multiple Gleitzeit instances can coordinate:

```python
# Example: Distributed lock for workflow completion
async def mark_workflow_complete_distributed(self, workflow_id: str):
    lock_key = f"lock:workflow:{workflow_id}:completion"
    lock_value = str(uuid.uuid4())
    
    # Try to acquire lock
    if await self.redis.set(lock_key, lock_value, nx=True, ex=10):
        try:
            # Check and update workflow atomically
            await self.check_workflow_completion_atomic(workflow_id)
        finally:
            # Release lock only if we own it
            if await self.redis.get(lock_key) == lock_value:
                await self.redis.delete(lock_key)
```

## Common Pitfalls and Solutions

### 1. SQLite Session Isolation

**Problem:** Different database sessions see different data snapshots, causing stale reads.

**Solution:** ExecutionEngine collects results directly from task execution rather than reading from persistence.

### 2. Concurrent Event Handler Race Conditions

**Problem:** Multiple handlers updating same data concurrently.

**Solution:** 
- Use atomic operations (transactions, Redis MULTI/EXEC)
- Single source of truth for results (ExecutionEngine)
- Idempotent operations where possible

### 3. Missing Events

**Problem:** Component not receiving critical events.

**Solution:**
- Ensure EventBus is passed to all components
- ExecutionEngine.emit_event() must use EventBus
- Verify handler registration for all event types

### 4. Duplicate Events

**Problem:** Same event emitted multiple times (e.g., WORKFLOW_COMPLETED from both ExecutionEngine and QueueManager).

**Solution:** Single responsibility - only ExecutionEngine emits WORKFLOW_COMPLETED with results.

## Testing Event Flow

### 1. Unit Tests

```python
async def test_workflow_completion_event():
    """Test that WORKFLOW_COMPLETED includes all task results"""
    
    # Setup
    event_bus = EventBus()
    handler = WorkflowCompletedHandler()
    event_bus.register(EventType.WORKFLOW_COMPLETED, handler)
    
    # Execute workflow
    engine = ExecutionEngine(event_bus=event_bus, ...)
    workflow = create_test_workflow()
    await engine._execute_workflow(workflow)
    
    # Verify event received with results
    assert workflow.id in handler.completed_workflows
    results = handler.completed_workflows[workflow.id]
    assert len(results['task_results']) == len(workflow.tasks)
    assert all(r['status'] == 'completed' for r in results['task_results'].values())
```

### 2. Integration Tests

```python
async def test_redis_event_flow():
    """Test event flow with Redis adapter"""
    
    # Setup Redis event monitoring
    events_received = []
    
    async def monitor_events():
        pubsub = redis.pubsub()
        await pubsub.subscribe("gleitzeit:events:*")
        async for msg in pubsub.listen():
            events_received.append(json.loads(msg['data']))
    
    monitor_task = asyncio.create_task(monitor_events())
    
    # Run workflow
    client = GleitzeitClient(persistence={'type': 'redis'})
    result = await client.run_workflow("test_workflow.yaml")
    
    # Verify event sequence
    event_types = [e['event_type'] for e in events_received]
    assert 'WORKFLOW_SUBMITTED' in event_types
    assert 'TASK_COMPLETED' in event_types
    assert 'WORKFLOW_COMPLETED' in event_types
    
    # Verify final event has results
    final_event = next(e for e in events_received 
                      if e['event_type'] == 'WORKFLOW_COMPLETED')
    assert 'task_results' in final_event['data']
```

## Migration Guide for Redis Adapter

### Step 1: Implement Event Publishing

Add event publishing to all Redis persistence operations:

```python
class RedisUnifiedAdapter:
    async def save_task(self, task: Task) -> Task:
        # Save to Redis
        await self._save_task_to_redis(task)
        
        # Emit appropriate event
        if task.status == TaskStatus.COMPLETED:
            await self.emit_event(create_task_completed_event(task))
        elif task.status == TaskStatus.FAILED:
            await self.emit_event(create_task_failed_event(task))
            
        return task
```

### Step 2: Subscribe to Events

Components using Redis adapter must subscribe to events:

```python
class RedisQueueManager:
    async def start_event_listener(self):
        """Start listening for task events"""
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(
            "gleitzeit:events:TASK_COMPLETED",
            "gleitzeit:events:TASK_FAILED"
        )
        
        asyncio.create_task(self._process_events(pubsub))
    
    async def _process_events(self, pubsub):
        async for message in pubsub.listen():
            if message['type'] == 'message':
                event = json.loads(message['data'])
                
                if event['event_type'] == 'TASK_COMPLETED':
                    task_id = event['data']['task_id']
                    await self.mark_task_completed(task_id)
```

### Step 3: Atomic Workflow Completion

Implement atomic workflow completion checking:

```python
async def check_and_emit_workflow_completion(self, workflow_id: str):
    """Atomically check workflow completion and emit event"""
    
    # Lua script for atomic check and update
    script = """
    local workflow_key = KEYS[1]
    local tasks_key = KEYS[2]
    local event_key = KEYS[3]
    
    -- Check if already completed
    if redis.call('HGET', workflow_key, 'status') == 'completed' then
        return 0
    end
    
    -- Get all tasks and check completion
    local tasks = redis.call('SMEMBERS', tasks_key)
    local all_completed = true
    local task_results = {}
    
    for i, task_id in ipairs(tasks) do
        local status = redis.call('HGET', 'task:' .. task_id, 'status')
        if status ~= 'completed' and status ~= 'failed' then
            all_completed = false
            break
        end
    end
    
    if all_completed then
        -- Update workflow status
        redis.call('HSET', workflow_key, 'status', 'completed')
        redis.call('HSET', workflow_key, 'completed_at', ARGV[1])
        
        -- Publish event
        redis.call('PUBLISH', event_key, ARGV[2])
        return 1
    end
    
    return 0
    """
    
    event_data = json.dumps({
        "event_type": "WORKFLOW_COMPLETED",
        "data": {
            "workflow_id": workflow_id,
            "status": "completed",
            "timestamp": datetime.utcnow().isoformat()
        }
    })
    
    result = await self.redis.eval(
        script,
        3,
        f"workflow:{workflow_id}",
        f"workflow:{workflow_id}:tasks",
        "gleitzeit:events:WORKFLOW_COMPLETED",
        datetime.utcnow().isoformat(),
        event_data
    )
    
    return result == 1
```

## Performance Considerations

### 1. Event Batching

For high-throughput scenarios, batch events:

```python
class BatchedEventBus:
    def __init__(self, batch_size=100, batch_timeout=0.1):
        self._batch = []
        self._batch_size = batch_size
        self._batch_timeout = batch_timeout
        
    async def emit(self, event: GleitzeitEvent):
        self._batch.append(event)
        
        if len(self._batch) >= self._batch_size:
            await self._flush_batch()
    
    async def _flush_batch(self):
        if not self._batch:
            return
            
        # Redis pipeline for batch publishing
        pipe = self.redis.pipeline()
        for event in self._batch:
            channel = f"gleitzeit:events:{event.event_type}"
            pipe.publish(channel, json.dumps(event.to_dict()))
        
        await pipe.execute()
        self._batch = []
```

### 2. Event Filtering

Reduce unnecessary event processing:

```python
class FilteredEventHandler(EventHandler):
    def __init__(self, workflow_id: str):
        self.workflow_id = workflow_id
    
    async def handle(self, event: GleitzeitEvent):
        # Only process events for our workflow
        if event.data.get('workflow_id') != self.workflow_id:
            return
        
        await self._process_event(event)
```

## Monitoring and Debugging

### 1. Event Metrics

Track event flow for monitoring:

```python
class MetricsEventBus(EventBus):
    def __init__(self):
        super().__init__()
        self.metrics = {
            'events_emitted': Counter(),
            'events_processed': Counter(),
            'event_processing_time': Histogram()
        }
    
    async def emit(self, event: GleitzeitEvent):
        self.metrics['events_emitted'].inc()
        
        with self.metrics['event_processing_time'].time():
            await super().emit(event)
        
        self.metrics['events_processed'].inc()
```

### 2. Event Tracing

Add tracing for debugging:

```python
class TracedEvent(GleitzeitEvent):
    def __init__(self, *args, trace_id: str = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.trace_id = trace_id or str(uuid.uuid4())
        self.trace_path = []
    
    def add_trace(self, component: str):
        self.trace_path.append({
            'component': component,
            'timestamp': datetime.utcnow().isoformat()
        })
```

## Summary

The event-driven architecture enables:
1. **Real-time coordination** without polling or delays
2. **Distributed processing** with Redis pub/sub
3. **Atomic operations** preventing race conditions
4. **Scalability** through event batching and filtering
5. **Observability** via metrics and tracing

Key principles:
- Single source of truth for results (ExecutionEngine)
- Atomic operations for state changes
- Idempotent event handlers
- Clear event flow with no circular dependencies
- Comprehensive error handling and retry logic