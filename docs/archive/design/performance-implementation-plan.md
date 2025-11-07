# Gleitzeit Performance Optimization Implementation Plan (REVISED)

**Status**: System Functional - Optimizations Recommended
**Priority**: Medium - System works but needs optimization for scale
**Timeline**: 2-4 weeks for full optimization

## Current System State

The Gleitzeit 0.0.7 system is **operational and functional**. Testing confirms:
- ✅ Workflows are processed correctly
- ✅ Dependencies are resolved properly
- ✅ Sharding architecture works as designed
- ⚠️ API performance degrades with data volume
- ⚠️ List operations use inefficient scanning

## Optimization Phases

## Phase 1: High-Impact Optimizations (Days 1-3)
**Goal**: Eliminate major performance bottlenecks

### Task 1.1: Add Workflow and Task Indexes
**Priority**: HIGH - Biggest performance impact
**Effort**: 4 hours
**Impact**: 10-100x improvement for list operations

#### Implementation:
```python
# In workflow_loader_worker_v2.py after workflow submission:
async def handle_workflow_submission(self, workflow_id: str, workflow: dict):
    # ... existing code ...

    # Add to workflow index
    shard = default_sharding.get_shard(workflow_id)
    await self.redis.sadd(
        f"{{shard:{shard}}}:index:workflows".encode(),
        workflow_id.encode()
    )

    # Add task IDs to workflow-specific index
    for task in workflow.get('tasks', []):
        await self.redis.sadd(
            f"{{shard:{shard}}}:index:tasks:{workflow_id}".encode(),
            task['id'].encode()
        )
```

#### Update API Endpoints:
```python
# In routes/workflows.py - Replace scanning with index lookup
@router.get("/list")
async def list_workflows(...):
    workflows = []

    # Check each shard's index (no scanning!)
    for shard in range(16):
        index_key = f"{{shard:{shard}}}:index:workflows"
        workflow_ids = await conn.redis.smembers(index_key.encode())

        # Use pipeline for efficiency
        pipe = conn.redis.pipeline()
        for wf_id in workflow_ids:
            wf_id = wf_id.decode()
            status_key = default_sharding.get_workflow_key("status", wf_id)
            pipe.hgetall(status_key.encode())

        results = await pipe.execute()
        # Process results...
```

### Task 1.2: Implement Task Count Caching
**Priority**: HIGH - Eliminates N×M operations
**Effort**: 3 hours
**Impact**: 100x improvement for workflow listings

```python
# In dependency_worker.py - Update counts incrementally
async def process_task_completed(self, workflow_id: str, task_id: str):
    # ... existing code ...

    # Update cached count
    status_key = default_sharding.get_workflow_key("status", workflow_id)
    await self.redis.hincrby(status_key.encode(), b"completed_count", 1)

    # Check if workflow complete
    total = await self.redis.hget(status_key.encode(), b"total_tasks")
    completed = await self.redis.hget(status_key.encode(), b"completed_count")

    if total and completed and int(total) == int(completed):
        await self.redis.hset(status_key.encode(), b"status", b"completed")
```

### Task 1.3: Add Request Timeouts
**Priority**: HIGH - Prevents hanging requests
**Effort**: 1 hour
**Impact**: Better user experience

```python
# In api/main.py
from fastapi import Request, HTTPException
import asyncio

@app.middleware("http")
async def timeout_middleware(request: Request, call_next):
    try:
        response = await asyncio.wait_for(
            call_next(request),
            timeout=30.0
        )
        return response
    except asyncio.TimeoutError:
        raise HTTPException(504, detail="Request timeout")
```

## Phase 2: API Performance (Days 4-6)
**Goal**: Optimize response times to <100ms

### Task 2.1: Batch Redis Operations with Pipelines
**Priority**: MEDIUM
**Effort**: 4 hours
**Impact**: 2-5x improvement

```python
# Example: Batch task status lookups
async def get_multiple_tasks(task_ids: List[str]):
    pipe = redis.pipeline()

    for task_id in task_ids:
        # Try each shard (or use index to find correct shard)
        for shard in range(16):
            key = f"{{shard:{shard}}}:task:status:{task_id}"
            pipe.exists(key.encode())
            pipe.hgetall(key.encode())

    results = await pipe.execute()
    # Process paired results (exists, data)...
```

### Task 2.2: Implement Result Caching
**Priority**: MEDIUM
**Effort**: 4 hours
**Impact**: Reduces repeated computations

```python
# Simple TTL cache for expensive operations
from functools import lru_cache
from datetime import datetime, timedelta

class CachedWorkflowList:
    def __init__(self, ttl_seconds=30):
        self.cache = {}
        self.ttl = timedelta(seconds=ttl_seconds)

    async def get_workflows(self, status=None):
        cache_key = f"workflows:{status or 'all'}"

        if cache_key in self.cache:
            cached_time, data = self.cache[cache_key]
            if datetime.now() - cached_time < self.ttl:
                return data

        # Fetch fresh data
        data = await self._fetch_workflows(status)
        self.cache[cache_key] = (datetime.now(), data)
        return data
```

## Phase 3: Scalability Enhancements (Week 2)
**Goal**: Prepare for 10,000+ workflows

### Task 3.1: Stream Trimming
**Priority**: MEDIUM
**Effort**: 2 hours
**Impact**: Prevents memory growth

```python
# In base worker after XADD
async def emit_event(self, stream: str, data: dict):
    stream_key = default_sharding.get_stream_key(stream, workflow_id)

    # Add message
    await self.redis.xadd(stream_key.encode(), data)

    # Trim to reasonable size
    await self.redis.xtrim(
        stream_key.encode(),
        maxlen=10000,
        approximate=True
    )
```

### Task 3.2: Implement Proper Pagination
**Priority**: MEDIUM
**Effort**: 4 hours
**Impact**: Handles large result sets

```python
# Use sorted sets for efficient pagination
async def store_workflow_with_timestamp(workflow_id: str):
    shard = default_sharding.get_shard(workflow_id)
    timestamp = datetime.utcnow().timestamp()

    await redis.zadd(
        f"{{shard:{shard}}}:index:workflows:sorted".encode(),
        {workflow_id.encode(): timestamp}
    )

async def get_workflows_paginated(offset: int, limit: int):
    workflows = []

    for shard in range(16):
        key = f"{{shard:{shard}}}:index:workflows:sorted"

        # Get page of workflow IDs sorted by timestamp
        ids = await redis.zrevrange(
            key.encode(),
            offset,
            offset + limit - 1
        )
        workflows.extend(ids)

    return workflows[:limit]
```

### Task 3.3: Add Performance Monitoring
**Priority**: LOW
**Effort**: 4 hours
**Impact**: Identifies bottlenecks

```python
# Add metrics collection
from prometheus_client import Counter, Histogram, generate_latest

request_duration = Histogram(
    'api_request_duration_seconds',
    'API request duration',
    ['method', 'endpoint']
)

@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start

    request_duration.labels(
        method=request.method,
        endpoint=request.url.path
    ).observe(duration)

    return response

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type="text/plain")
```

## Testing Strategy

### Performance Benchmarks
```python
# tests/test_performance.py
import pytest
import time
import asyncio

@pytest.mark.asyncio
async def test_workflow_list_performance():
    # Create test data
    for i in range(100):
        await submit_workflow(f"test_workflow_{i}")

    # Measure list performance
    start = time.time()
    response = await client.get("/workflows/list")
    duration = time.time() - start

    assert response.status_code == 200
    assert duration < 1.0  # Must complete within 1 second
    assert len(response.json()["workflows"]) == 100

@pytest.mark.asyncio
async def test_concurrent_operations():
    # Test system under concurrent load
    tasks = []
    for i in range(50):
        tasks.append(submit_workflow(f"concurrent_{i}"))

    start = time.time()
    await asyncio.gather(*tasks)
    duration = time.time() - start

    assert duration < 10.0  # 50 workflows in under 10 seconds
```

### Load Testing
```bash
# Using locust for load testing
# locustfile.py
from locust import HttpUser, task, between

class WorkflowUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def list_workflows(self):
        self.client.get("/workflows/list")

    @task
    def submit_workflow(self):
        self.client.post("/workflows/submit", json={
            "workflow": {...}
        })

# Run: locust -f locustfile.py --host http://localhost:8080
```

## Rollout Plan

### Week 1: Core Optimizations
- **Day 1-2**: Implement indexes and caching
- **Day 3**: Deploy to staging, test thoroughly
- **Day 4-5**: Monitor in production (feature flag controlled)

### Week 2: Enhanced Performance
- **Day 1-2**: Pipeline optimizations
- **Day 3-4**: Pagination and result caching
- **Day 5**: Performance testing and tuning

### Week 3: Monitoring and Tuning
- **Day 1-2**: Add metrics and monitoring
- **Day 3-4**: Load testing and optimization
- **Day 5**: Documentation and knowledge transfer

## Success Metrics

### Performance Targets
- **P50 Latency**: < 50ms for all endpoints
- **P99 Latency**: < 200ms for list operations
- **Throughput**: 1000+ requests/second
- **Concurrent Workflows**: 10,000+ active

### Quality Metrics
- **Error Rate**: < 0.1%
- **Timeout Rate**: < 0.01%
- **Redis Memory**: < 70% utilization
- **CPU Usage**: < 60% average

## Risk Mitigation

### Deployment Risks
- **Feature Flags**: Deploy all optimizations behind flags
- **Gradual Rollout**: 10% → 50% → 100% traffic
- **Rollback Plan**: One-click rollback to previous version
- **Monitoring**: Alert on performance regression

### Data Risks
- **Backup Before Changes**: Snapshot Redis before index creation
- **Index Rebuild Script**: Script to rebuild indexes if corrupted
- **Dual Write Period**: Write to both old and new patterns during transition

## Resource Requirements

### Development
- **Backend Engineers**: 2 developers for 2 weeks
- **QA Engineer**: 1 tester for load testing
- **DevOps**: Support for deployment and monitoring

### Infrastructure
- **Redis Memory**: May need 20% more for indexes
- **Monitoring**: Prometheus + Grafana setup
- **Load Testing**: Dedicated environment

## Migration Notes

### For Existing Data
```python
# One-time script to build indexes for existing workflows
async def migrate_existing_workflows():
    print("Building indexes for existing workflows...")

    # Find all workflows
    pattern = b"*:workflow:status:*"
    count = 0

    async for key in redis.scan_iter(match=pattern, count=100):
        # Extract workflow_id
        parts = key.decode().split(":")
        workflow_id = parts[-1]
        shard = int(parts[0].strip("{}shard:"))

        # Add to index
        await redis.sadd(
            f"{{shard:{shard}}}:index:workflows".encode(),
            workflow_id.encode()
        )
        count += 1

        if count % 100 == 0:
            print(f"Indexed {count} workflows...")

    print(f"Migration complete: {count} workflows indexed")
```

## Conclusion

The system is **functional but not optimized**. These improvements will:
1. Reduce response times by 10-100x
2. Enable scaling to 10,000+ workflows
3. Improve reliability and user experience
4. Provide monitoring and observability

The optimizations are **non-breaking** and can be deployed **incrementally** with minimal risk.