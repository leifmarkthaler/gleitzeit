# Existing Workers Analysis

## What We Already Have

### 1. StreamWorker ✅
- **Pattern**: Kafka-style blocking XREADGROUP
- **Good**: Uses consumer groups, handles multiple streams
- **Issue**: Tightly coupled to system_manager
- **Missing**: No base class, no concurrency control

### 2. TimerWorker ✅
- **Pattern**: Leader election with Redis lock
- **Good**: Heartbeat, fencing tokens, automatic failover
- **Issue**: Also coupled to system_manager
- **Missing**: No consumer group pattern

### 3. SignalWorker ✅
- **Pattern**: Leader election + stream consumption
- **Good**: Per-workflow signal isolation
- **Issue**: Coupled to system_manager
- **Missing**: Could use consumer groups better

## Comparison with Implementation Plan

### What's Good ✅
1. **Leader Election Pattern** - Already implemented correctly
2. **Redis Streams** - Using XREADGROUP properly
3. **Graceful Shutdown** - Signal handlers in place
4. **Worker Registration** - Workers register themselves
5. **Metrics** - Basic counters already exist

### What's Missing ❌

#### 1. **No Base Worker Class**
Current workers duplicate code. Need:
```python
class BaseWorker:
    - Common Redis connection
    - Consumer group management
    - Concurrency control (semaphore)
    - Metrics collection
    - Health checks
```

#### 2. **Tight Coupling to SystemManager**
All workers require system_manager, making them hard to test and deploy independently:
```python
# Current (coupled)
def __init__(self, system_manager):
    self.redis = system_manager.persistence.redis

# Should be (decoupled)
def __init__(self, redis_url: str, config: WorkerConfig):
    self.redis = await aioredis.from_url(redis_url)
```

#### 3. **No Worker Factory**
Need factory to create workers dynamically:
```python
worker = WorkerFactory.create('execution', worker_id='exec-1')
```

#### 4. **Missing Critical Workers**
We only have 3 workers. Still need:
- TaskExecutionWorker (CRITICAL)
- DependencyGraphWorker (CRITICAL)
- WorkflowLoaderWorker
- WorkflowSchedulerWorker
- QueueDistributorWorker

#### 5. **No Sharding Strategy**
Current StreamWorker reads ALL streams. Should shard:
```python
# Current
streams = {
    "gleitzeit:events:stream:task:ready": ">"
}

# Should be
shard = hash(workflow_id) % NUM_SHARDS
streams = {
    f"task:ready:{shard}": ">"
}
```

## Refactoring Plan

### Step 1: Extract Base Class
Create base worker that existing workers can inherit from:

```python
# src/gleitzeit/workers/base.py
class BaseWorker(ABC):
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.redis = None
        self._semaphore = asyncio.Semaphore(config.max_concurrent)

    async def initialize(self):
        self.redis = await aioredis.from_url(self.config.redis_url)

    @abstractmethod
    async def process_message(self, stream, msg_id, data):
        pass

    async def run(self):
        # Common consumption loop
        pass
```

### Step 2: Refactor Existing Workers
Update to use base class:

```python
class StreamWorker(BaseWorker):
    def get_stream_patterns(self):
        return {"task:ready:*": ">", "task:completed:*": ">"}

    async def process_message(self, stream, msg_id, data):
        # Process using handlers
        pass
```

### Step 3: Add New Workers
Implement critical missing workers:

```python
class TaskExecutionWorker(BaseWorker):
    """The most critical missing worker"""

    async def process_message(self, stream, msg_id, data):
        task = Task.from_json(data['task'])
        provider = await self.get_provider(task.protocol)
        result = await provider.execute(task.method, task.params)
        await self.emit_completion(task.id, result)
```

### Step 4: Update CLI
Make workers standalone:

```python
@click.command()
@click.option('--type', type=click.Choice([
    'stream', 'timer', 'signal',  # Existing
    'execution', 'dependency', 'loader'  # New
]))
@click.option('--redis-url', default='redis://localhost:6379')
def worker(type, redis_url):
    """Start worker without system_manager"""
    config = WorkerConfig(
        worker_type=type,
        redis_url=redis_url
    )
    worker = WorkerFactory.create(config)
    asyncio.run(worker.start())
```

## Migration Strategy

### Phase 1: Backward Compatible (Week 1)
- Add base class
- Keep existing workers working with system_manager
- Add factory that supports both modes

### Phase 2: New Workers (Week 2)
- Implement TaskExecutionWorker (standalone)
- Implement DependencyGraphWorker (standalone)
- Test in parallel with existing system

### Phase 3: Refactor Existing (Week 3)
- Update StreamWorker to use base class
- Make Timer/Signal workers standalone
- Remove system_manager dependency

### Phase 4: Full Deployment (Week 4)
- Deploy all workers independently
- Remove old orchestrator code
- Monitor and optimize

## Quick Wins

### 1. Add TaskExecutionWorker NOW
This single worker would provide immediate parallelization:

```python
# src/gleitzeit/workers/execution_worker.py
class TaskExecutionWorker:
    def __init__(self, redis_url: str, worker_id: str):
        self.redis = await aioredis.from_url(redis_url)
        self.worker_id = worker_id
        self.consumer_group = "execution-workers"

    async def run(self):
        while True:
            messages = await self.redis.xreadgroup(
                self.consumer_group,
                self.worker_id,
                {"task:ready:*": ">"},
                block=5000
            )
            for stream, msgs in messages:
                for msg_id, data in msgs:
                    await self.execute_task(data)
                    await self.redis.xack(stream, self.consumer_group, msg_id)
```

### 2. Add Worker Mode to CLI
```python
# Add to existing CLI
@cli.command()
@click.option('--workers', default=1)
def start_execution_workers(workers):
    """Start execution workers"""
    for i in range(workers):
        worker = TaskExecutionWorker(
            redis_url=get_redis_url(),
            worker_id=f"exec-{i}"
        )
        asyncio.create_task(worker.run())
```

## Conclusion

We have a **good foundation** with the 3 existing workers, but they need:
1. **Decoupling** from system_manager
2. **Base class** to reduce duplication
3. **More worker types** (especially TaskExecutionWorker)
4. **Sharding** for scalability
5. **Standalone deployment** capability

The good news: The patterns are already proven (leader election, stream consumption). We just need to:
- Extract common code
- Add missing workers
- Make them deployable independently

With these changes, we can achieve the full worker architecture vision!