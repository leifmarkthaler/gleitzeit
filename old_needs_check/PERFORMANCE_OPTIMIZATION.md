# Gleitzeit Performance Optimization Opportunities

## Current Performance Baseline
- **20 workflows processed in ~13 seconds**
- **Average: 0.65 seconds per workflow**
- **System load: 9.8% CPU, 67.8% memory**

## Identified Bottlenecks & Optimization Opportunities

### 1. Worker Count and Concurrency (Quick Win)
**Current State:**
- 2 task execution workers with max_concurrent=5 each (10 total concurrent)
- 1 dependency worker with max_concurrent=10
- 1 workflow loader with max_concurrent=5

**Optimization:**
```yaml
workers:
  - worker_type: task_execution
    count: 4  # Increase from 2
    max_concurrent: 10  # Increase from 5
    batch_size: 20  # Increase from default 10

  - worker_type: dependency
    count: 2  # Increase from 1
    max_concurrent: 20  # Increase from 10
    batch_size: 20

  - worker_type: workflow_loader_v2
    count: 2  # Increase from 1
    max_concurrent: 10  # Increase from 5
```
**Expected Speedup: 2-3x**

### 2. Batch Processing (Medium Impact)
**Current State:**
- Workers process messages with batch_size=10
- Block timeout of 5000ms causes unnecessary waiting

**Optimization:**
```python
# In WorkerConfig
batch_size: int = 50  # Increase from 10
block_timeout: int = 1000  # Reduce from 5000ms
```
**Expected Speedup: 20-30% reduction in latency**

### 3. Redis Pipeline Operations (High Impact)
**Current State:**
- Multiple individual Redis calls for each task
- No pipelining in dependency resolution

**Optimization:**
```python
# In DependencyWorker.resolve_task_parameters()
async def resolve_task_parameters_optimized(self, task: Dict, workflow_id: str) -> Dict:
    dependencies = task.get('dependencies', [])
    if not dependencies:
        return task

    # Pipeline all Redis reads
    pipe = self.redis.pipeline(transaction=False)
    for dep_id in dependencies:
        pipe.hgetall(default_sharding.get_task_key(dep_id, workflow_id).encode())

    results = await pipe.execute()
    # Process results...
```
**Expected Speedup: 30-50% for workflows with dependencies**

### 4. Workflow Loader Caching (Medium Impact)
**Current State:**
- Workflows are parsed every time
- No deduplication of identical workflows

**Optimization:**
```python
# Cache parsed workflows
@lru_cache(maxsize=100)
async def get_cached_workflow(self, workflow_hash: str):
    # Return cached parsed workflow
    pass
```
**Expected Speedup: 10-20% for repeated workflow patterns**

### 5. Task Execution Subprocess Pool (High Impact)
**Current State:**
- New Python subprocess spawned for each task
- Subprocess creation overhead ~50-100ms

**Optimization:**
```python
# Create subprocess pool in PythonHandler
class PythonHandler(BaseHandler):
    def __init__(self):
        self.process_pool = ProcessPoolExecutor(max_workers=10)

    async def _execute_code(self, task: Task):
        # Reuse process from pool
        result = await self.process_pool.run(execute_python, code, inputs)
```
**Expected Speedup: 50-100ms per Python task**

### 6. Sharding and Locality Optimization (Medium Impact)
**Current State:**
- Workers process all 16 shards
- No affinity between workers and shards

**Optimization:**
```yaml
workers:
  - worker_type: task_execution
    count: 4
    shard_affinity: [0,1,2,3]  # Each worker handles 4 shards
```
**Expected Speedup: 10-15% reduction in Redis cluster routing**

### 7. Stream Processing Optimization (Low Impact)
**Current State:**
- Using consumer groups with ">" cursor (fixed)
- No stream trimming

**Optimization:**
```python
# Trim old stream entries
await self.redis.xtrim(stream_key, maxlen=1000, approximate=True)
```
**Expected Speedup: Prevents memory bloat**

### 8. Event Store Optimization (Medium Impact)
**Current State:**
- Event store writes for every task state change
- No batching

**Optimization:**
```python
# Batch event writes
class BatchedEventStore:
    async def store_events_batch(self, events: List[Event]):
        pipe = self.redis.pipeline()
        for event in events:
            pipe.xadd(...)
        await pipe.execute()
```
**Expected Speedup: 20-30% for event-heavy workflows**

## Implementation Priority

### Phase 1: Configuration Changes (Immediate)
1. Increase worker counts and concurrency
2. Adjust batch sizes and timeouts
3. **Expected Overall Speedup: 2-3x**

### Phase 2: Code Optimizations (1-2 days)
1. Implement Redis pipelining
2. Add subprocess pooling for Python handler
3. **Expected Overall Speedup: Additional 30-50%**

### Phase 3: Architecture Improvements (1 week)
1. Implement workflow caching
2. Add shard affinity
3. Batch event processing
4. **Expected Overall Speedup: Additional 20-30%**

## Expected Final Performance
- **Target: 20 workflows in 3-5 seconds**
- **Average: 0.15-0.25 seconds per workflow**
- **4-5x overall improvement**

## Monitoring Metrics to Track
1. **Workflow completion time** (P50, P95, P99)
2. **Task execution latency**
3. **Redis operations per second**
4. **Worker CPU utilization**
5. **Queue depths over time**
6. **Subprocess spawn time**
7. **Redis memory usage**

## Quick Test Commands
```bash
# Test with optimized config
gleitzeit start --config optimized_config.yaml

# Submit batch test
for i in {1..100}; do
    gleitzeit submit test_simple.yaml &
done
wait

# Check performance
gleitzeit status --detailed
```