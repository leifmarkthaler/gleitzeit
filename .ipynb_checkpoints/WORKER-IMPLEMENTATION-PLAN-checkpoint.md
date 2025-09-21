# Worker Architecture Implementation Plan

## Phase 0: Foundation (Week 1)

### 1. Create Base Worker Framework

First, create a reusable base class that all workers inherit from:

```python
# src/gleitzeit/workers/base.py
import asyncio
import logging
import signal
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
import aioredis
from dataclasses import dataclass

@dataclass
class WorkerConfig:
    worker_type: str
    worker_id: str
    consumer_group: str
    redis_url: str
    max_concurrent: int = 10
    batch_size: int = 10
    block_timeout: int = 5000

class BaseWorker(ABC):
    """Base class for all Gleitzeit workers"""

    def __init__(self, config: WorkerConfig):
        self.config = config
        self.logger = logging.getLogger(f"{config.worker_type}.{config.worker_id}")
        self.redis: Optional[aioredis.Redis] = None
        self._running = False
        self._tasks: Dict[str, asyncio.Task] = {}
        self._semaphore = asyncio.Semaphore(config.max_concurrent)

    async def initialize(self):
        """Initialize worker resources"""
        self.redis = await aioredis.from_url(
            self.config.redis_url,
            decode_responses=True
        )
        await self.on_initialize()

    @abstractmethod
    async def on_initialize(self):
        """Override for custom initialization"""
        pass

    @abstractmethod
    def get_stream_patterns(self) -> Dict[str, str]:
        """Return stream patterns to consume"""
        # Example: {"task:ready:*": ">", "task:failed:*": ">"}
        pass

    @abstractmethod
    async def process_message(self, stream: str, message_id: str, data: Dict):
        """Process a single message"""
        pass

    async def run(self):
        """Main worker loop"""
        self._running = True

        # Setup graceful shutdown
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self.shutdown)

        while self._running:
            try:
                # Read from streams
                messages = await self.redis.xreadgroup(
                    self.config.consumer_group,
                    self.config.worker_id,
                    self.get_stream_patterns(),
                    count=self.config.batch_size,
                    block=self.config.block_timeout
                )

                # Process messages concurrently with semaphore
                tasks = []
                for stream, stream_messages in messages:
                    for msg_id, data in stream_messages:
                        task = asyncio.create_task(
                            self._process_with_semaphore(stream, msg_id, data)
                        )
                        tasks.append(task)

                # Wait for batch to complete
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

            except Exception as e:
                self.logger.error(f"Error in worker loop: {e}")
                await asyncio.sleep(1)

    async def _process_with_semaphore(self, stream: str, msg_id: str, data: Dict):
        """Process message with concurrency control"""
        async with self._semaphore:
            try:
                await self.process_message(stream, msg_id, data)
                # Acknowledge message
                await self.redis.xack(stream, self.config.consumer_group, msg_id)
            except Exception as e:
                self.logger.error(f"Failed to process {msg_id}: {e}")
                # Could implement retry logic here

    def shutdown(self):
        """Graceful shutdown"""
        self.logger.info("Shutting down worker")
        self._running = False
```

### 2. Create Worker Factory

```python
# src/gleitzeit/workers/factory.py
from typing import Type, Dict, Any
from .base import BaseWorker, WorkerConfig
from .execution_worker import TaskExecutionWorker
from .loader_worker import WorkflowLoaderWorker
from .dependency_worker import DependencyGraphWorker

WORKER_REGISTRY = {
    'execution': TaskExecutionWorker,
    'loader': WorkflowLoaderWorker,
    'dependency': DependencyGraphWorker,
    # Add more as implemented
}

class WorkerFactory:
    @staticmethod
    def create_worker(
        worker_type: str,
        worker_id: str,
        redis_url: str,
        **kwargs
    ) -> BaseWorker:
        """Create a worker instance"""

        if worker_type not in WORKER_REGISTRY:
            raise ValueError(f"Unknown worker type: {worker_type}")

        worker_class = WORKER_REGISTRY[worker_type]

        config = WorkerConfig(
            worker_type=worker_type,
            worker_id=worker_id,
            consumer_group=f"{worker_type}-workers",
            redis_url=redis_url,
            **kwargs
        )

        return worker_class(config)
```

## Phase 1: Critical Path Workers (Week 2-3)

### 1. Implement TaskExecutionWorker

```python
# src/gleitzeit/workers/execution_worker.py
from .base import BaseWorker
import json

class TaskExecutionWorker(BaseWorker):
    """Worker for executing tasks"""

    async def on_initialize(self):
        """Initialize provider pools"""
        from gleitzeit.providers.pooling_adapter import PoolingAdapter
        self.pooling_adapter = PoolingAdapter(
            persistence=self.redis,  # Simple Redis persistence
            min_pool_size=1,
            max_pool_size=5
        )
        await self.pooling_adapter.initialize()

    def get_stream_patterns(self) -> Dict[str, str]:
        return {
            "task:ready:*": ">",  # Listen to all shards
            "task:retry:*": ">"
        }

    async def process_message(self, stream: str, msg_id: str, data: Dict):
        """Execute a task"""
        task_data = json.loads(data.get('task', '{}'))
        task_id = task_data.get('id')

        try:
            # Get provider
            protocol = task_data.get('protocol', 'python/v1')
            provider = await self.pooling_adapter.get_provider(protocol)

            # Execute task
            result = await provider.execute(
                task_data.get('method'),
                task_data.get('params', {})
            )

            # Emit completion
            await self.redis.xadd(
                f"task:completed:{task_data.get('workflow_id')}",
                {
                    'task_id': task_id,
                    'result': json.dumps(result),
                    'worker_id': self.config.worker_id
                }
            )

        except Exception as e:
            # Emit failure
            await self.redis.xadd(
                f"task:failed:{task_data.get('workflow_id')}",
                {
                    'task_id': task_id,
                    'error': str(e),
                    'worker_id': self.config.worker_id
                }
            )
```

### 2. Implement DependencyGraphWorker

```python
# src/gleitzeit/workers/dependency_worker.py
class DependencyGraphWorker(BaseWorker):
    """Worker for managing dependency graphs"""

    def get_stream_patterns(self) -> Dict[str, str]:
        return {
            "workflow:submitted": ">",
            "task:completed:*": ">",
            "task:failed:*": ">"
        }

    async def process_message(self, stream: str, msg_id: str, data: Dict):
        if "workflow:submitted" in stream:
            await self.build_graph(data)
        else:
            await self.update_graph(data)

    async def build_graph(self, data: Dict):
        """Build initial dependency graph"""
        workflow = json.loads(data['workflow'])
        workflow_id = workflow['id']

        graph = {}
        for task in workflow['tasks']:
            graph[task['id']] = {
                'dependencies': task.get('depends_on', []),
                'dependents': [],
                'status': 'pending'
            }

        # Build reverse dependencies
        for task_id, node in graph.items():
            for dep_id in node['dependencies']:
                if dep_id in graph:
                    graph[dep_id]['dependents'].append(task_id)

        # Store in Redis
        await self.redis.hset(
            f"dep:graph:{workflow_id}",
            mapping={
                task_id: json.dumps(node)
                for task_id, node in graph.items()
            }
        )

        # Emit initial ready tasks
        for task_id, node in graph.items():
            if not node['dependencies']:
                await self.redis.xadd(
                    f"task:ready:{self.get_shard(workflow_id)}",
                    {'task_id': task_id, 'workflow_id': workflow_id}
                )

    def get_shard(self, workflow_id: str) -> int:
        return hash(workflow_id) % 16  # 16 shards
```

## Phase 2: CLI Integration (Week 3)

### Update CLI to Support Workers

```python
# src/gleitzeit/cli/main.py updates
@click.command()
@click.option('--type',
    type=click.Choice(['execution', 'loader', 'dependency', 'all']),
    default='all',
    help='Worker type to start')
@click.option('--count', default=1, help='Number of workers')
@click.option('--redis-url',
    default='redis://localhost:6379',
    help='Redis connection URL')
def worker(type, count, redis_url):
    """Start Gleitzeit workers"""

    async def run_worker(worker_type, worker_id):
        from gleitzeit.workers.factory import WorkerFactory

        worker = WorkerFactory.create_worker(
            worker_type=worker_type,
            worker_id=f"{worker_type}-{worker_id}",
            redis_url=redis_url
        )

        await worker.initialize()
        await worker.run()

    async def run_all():
        if type == 'all':
            # Start one of each type
            types = ['execution', 'loader', 'dependency']
            tasks = []
            for wtype in types:
                for i in range(count):
                    tasks.append(run_worker(wtype, i))
        else:
            # Start multiple of specified type
            tasks = [
                run_worker(type, i)
                for i in range(count)
            ]

        await asyncio.gather(*tasks)

    asyncio.run(run_all())
```

## Phase 3: Docker & Kubernetes (Week 4)

### 1. Dockerfile for Workers

```dockerfile
# Dockerfile.worker
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

ENV PYTHONPATH=/app

# Default to execution worker
ENV WORKER_TYPE=execution
ENV WORKER_ID=worker-1
ENV REDIS_URL=redis://redis:6379

CMD ["python", "-m", "gleitzeit", "worker",
     "--type", "${WORKER_TYPE}",
     "--redis-url", "${REDIS_URL}"]
```

### 2. Kubernetes Deployment

```yaml
# k8s/workers.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: execution-workers
spec:
  replicas: 10
  selector:
    matchLabels:
      app: gleitzeit
      component: execution-worker
  template:
    metadata:
      labels:
        app: gleitzeit
        component: execution-worker
    spec:
      containers:
      - name: worker
        image: gleitzeit-worker:latest
        env:
        - name: WORKER_TYPE
          value: "execution"
        - name: WORKER_ID
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: REDIS_URL
          value: "redis://redis-service:6379"
        resources:
          requests:
            cpu: 1
            memory: 2Gi
---
apiVersion: v1
kind: Service
metadata:
  name: redis-service
spec:
  ports:
  - port: 6379
  selector:
    app: redis
```

## Phase 4: Migration Strategy (Week 5)

### 1. Dual-Mode Operation

Keep existing system running while adding workers:

```python
# src/gleitzeit/api/main.py
@app.post("/workflows/submit")
async def submit_workflow(workflow: dict):
    if ENABLE_WORKERS:
        # New path: emit to stream for workers
        await redis.xadd(
            "workflow:submit:request",
            {"workflow": json.dumps(workflow)}
        )
    else:
        # Old path: direct processing
        await workflow_manager.submit_workflow(workflow)
```

### 2. Feature Flags

```python
# src/gleitzeit/config.py
class GleitzeitConfig:
    # Gradual rollout flags
    ENABLE_EXECUTION_WORKERS = os.getenv("ENABLE_EXECUTION_WORKERS", "false") == "true"
    ENABLE_LOADER_WORKERS = os.getenv("ENABLE_LOADER_WORKERS", "false") == "true"
    ENABLE_DEPENDENCY_WORKERS = os.getenv("ENABLE_DEPENDENCY_WORKERS", "false") == "true"

    # Worker configuration
    WORKER_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
    WORKER_COUNT = int(os.getenv("WORKER_COUNT", "1"))
    WORKER_SHARDS = int(os.getenv("WORKER_SHARDS", "16"))
```

## Phase 5: Testing Strategy (Ongoing)

### 1. Unit Tests for Workers

```python
# tests/workers/test_execution_worker.py
import pytest
from gleitzeit.workers.execution_worker import TaskExecutionWorker

@pytest.mark.asyncio
async def test_task_execution():
    worker = TaskExecutionWorker(config)
    await worker.initialize()

    # Add task to stream
    await redis.xadd("task:ready:0", {
        "task": json.dumps({
            "id": "test-1",
            "protocol": "python/v1",
            "method": "execute",
            "params": {"code": "return 42"}
        })
    })

    # Process message
    await worker.process_message("task:ready:0", "123-0", data)

    # Check completion event
    result = await redis.xread({"task:completed:*": "0"})
    assert result[0]["result"] == "42"
```

### 2. Integration Tests

```python
# tests/integration/test_worker_pipeline.py
async def test_full_workflow_with_workers():
    # Start workers in test mode
    workers = await start_test_workers()

    # Submit workflow
    await redis.xadd("workflow:submit:request", {
        "workflow": json.dumps(test_workflow)
    })

    # Wait for completion
    completed = await wait_for_event("workflow:completed", timeout=10)

    assert completed["status"] == "success"
```

## Phase 6: Monitoring (Week 6)

### 1. Prometheus Metrics

```python
# src/gleitzeit/workers/metrics.py
from prometheus_client import Counter, Histogram, Gauge

# Worker metrics
tasks_processed = Counter(
    'gleitzeit_tasks_processed_total',
    'Total tasks processed',
    ['worker_type', 'status']
)

task_duration = Histogram(
    'gleitzeit_task_duration_seconds',
    'Task processing duration',
    ['worker_type', 'protocol']
)

active_workers = Gauge(
    'gleitzeit_active_workers',
    'Number of active workers',
    ['worker_type']
)
```

### 2. Health Checks

```python
# src/gleitzeit/workers/health.py
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "workers": get_active_workers(),
        "queue_depth": get_queue_depths()
    }

@app.get("/ready")
async def ready():
    # Check Redis connection
    if not await check_redis():
        return {"status": "not_ready"}, 503
    return {"status": "ready"}
```

## Rollout Timeline

### Week 1: Foundation
- ✅ Base worker framework
- ✅ Worker factory
- ✅ Basic Redis integration

### Week 2: Core Workers
- ✅ TaskExecutionWorker
- ✅ DependencyGraphWorker
- ✅ Basic testing

### Week 3: Integration
- ✅ CLI updates
- ✅ API integration
- ✅ Feature flags

### Week 4: Deployment
- ✅ Docker images
- ✅ Kubernetes manifests
- ✅ Initial deployment to staging

### Week 5: Migration
- ✅ Dual-mode operation
- ✅ Gradual rollout
- ✅ Performance testing

### Week 6: Production
- ✅ Full production rollout
- ✅ Monitoring
- ✅ Auto-scaling

## Success Metrics

1. **Performance**: 10x throughput improvement
2. **Scalability**: Linear scaling with worker count
3. **Reliability**: No message loss, automatic recovery
4. **Operations**: Simple deployment, easy scaling

## Risk Mitigation

1. **Gradual Rollout**: Feature flags for each worker type
2. **Dual Mode**: Keep old system as fallback
3. **Monitoring**: Comprehensive metrics from day 1
4. **Testing**: Full test coverage before production
5. **Rollback Plan**: Can disable workers instantly

This implementation plan provides a **practical, low-risk path** to the full worker architecture while maintaining system stability throughout the migration!