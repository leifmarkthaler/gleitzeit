# Repurposing SystemManager as Component Orchestrator

## Brilliant Idea! Transform SystemManager from Task Processor to Component Manager

Instead of processing workflows/tasks, SystemManager becomes the **orchestrator of workers and infrastructure**.

## New Role: Component Lifecycle Manager

### From Task Processing to Component Orchestration

**Old SystemManager (Task Processing)**:
```python
class ModularStreamSystemManager:
    async def process_all_once():  # Process tasks
    async def submit_workflow():   # Handle workflows
    async def execute_task():      # Execute tasks
```

**New SystemManager (Component Orchestration)**:
```python
class ComponentOrchestrator:
    async def start_workers():     # Manage worker lifecycle
    async def health_check():       # Monitor component health
    async def scale_workers():      # Auto-scale based on load
    async def coordinate():         # Coordinate distributed components
```

## The New Architecture

```
ComponentOrchestrator (formerly SystemManager)
        ├── Worker Management
        │   ├── Start/Stop Workers
        │   ├── Health Monitoring
        │   └── Auto-scaling
        ├── Resource Management
        │   ├── Redis Connections
        │   ├── Provider Pools
        │   └── Memory Management
        ├── Service Discovery
        │   ├── Worker Registration
        │   ├── Shard Assignment
        │   └── Load Balancing
        └── Observability
            ├── Metrics Aggregation
            ├── Log Collection
            └── Distributed Tracing
```

## Implementation: Component Orchestrator

```python
# src/gleitzeit/orchestrator/component_orchestrator.py
import asyncio
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class WorkerConfig:
    worker_type: str
    count: int
    shards: List[int]
    resources: Dict[str, any]

class ComponentOrchestrator:
    """
    Manages the lifecycle of all Gleitzeit components.
    This is what SystemManager SHOULD have been!
    """

    def __init__(self, redis_url: str, config: Dict):
        self.redis_url = redis_url
        self.config = config
        self.workers: Dict[str, List[Worker]] = {}
        self.health_status: Dict[str, bool] = {}
        self.metrics: Dict[str, any] = {}

    async def initialize(self):
        """Initialize orchestrator and core infrastructure"""

        # Setup Redis connection pool
        self.redis_pool = await self._create_redis_pool()

        # Initialize service registry
        self.registry = ServiceRegistry(self.redis_pool)

        # Setup monitoring
        self.monitor = ComponentMonitor(self.registry)

        # Initialize shard manager
        self.shard_manager = ShardManager(num_shards=16)

    async def start_workers(self, worker_configs: List[WorkerConfig]):
        """Start and manage workers"""

        for config in worker_configs:
            workers = []
            for i in range(config.count):
                # Assign shards
                assigned_shards = self.shard_manager.assign_shards(
                    worker_id=f"{config.worker_type}-{i}",
                    worker_type=config.worker_type
                )

                # Create worker
                worker = await self._create_worker(
                    worker_type=config.worker_type,
                    worker_id=f"{config.worker_type}-{i}",
                    shards=assigned_shards,
                    redis_url=self.redis_url
                )

                # Start worker
                await worker.start()
                workers.append(worker)

                # Register in service discovery
                await self.registry.register_worker(worker)

            self.workers[config.worker_type] = workers

        logger.info(f"Started {sum(len(w) for w in self.workers.values())} workers")

    async def auto_scale(self):
        """Auto-scale workers based on queue depth"""

        while True:
            metrics = await self._collect_metrics()

            for worker_type, stats in metrics.items():
                queue_depth = stats['queue_depth']
                worker_count = len(self.workers.get(worker_type, []))

                # Scale up if queues are deep
                if queue_depth > worker_count * 100:
                    await self.scale_up(worker_type, count=5)

                # Scale down if queues are empty
                elif queue_depth < worker_count * 10 and worker_count > 1:
                    await self.scale_down(worker_type, count=1)

            await asyncio.sleep(30)  # Check every 30 seconds

    async def health_check(self):
        """Monitor component health"""

        while True:
            # Check worker health
            for worker_type, workers in self.workers.items():
                for worker in workers:
                    is_healthy = await worker.health_check()

                    if not is_healthy:
                        logger.warning(f"Worker {worker.id} unhealthy, restarting")
                        await self.restart_worker(worker)

            # Check Redis health
            redis_healthy = await self._check_redis_health()
            self.health_status['redis'] = redis_healthy

            # Emit health metrics
            await self._emit_health_metrics()

            await asyncio.sleep(10)  # Check every 10 seconds

    async def coordinate_deployment(self, deployment_spec: Dict):
        """Coordinate zero-downtime deployment"""

        # Phase 1: Start new workers
        new_workers = await self.start_workers(
            deployment_spec['workers'],
            version=deployment_spec['version']
        )

        # Phase 2: Wait for new workers to be ready
        await self._wait_for_workers_ready(new_workers)

        # Phase 3: Gradually shift traffic
        for percentage in [10, 25, 50, 75, 100]:
            await self._shift_traffic(new_workers, percentage)
            await asyncio.sleep(60)  # Monitor for 1 minute

            if not await self._check_error_rate():
                await self._rollback(new_workers)
                return False

        # Phase 4: Drain old workers
        await self._drain_workers(self.workers)

        # Phase 5: Stop old workers
        await self._stop_workers(self.workers)

        self.workers = new_workers
        return True

    async def manage_sharding(self):
        """Dynamically manage shard assignments"""

        class ShardManager:
            async def rebalance_shards(self):
                """Rebalance shards across workers"""

                # Get current load per shard
                shard_loads = await self._get_shard_loads()

                # Find imbalanced shards
                avg_load = sum(shard_loads.values()) / len(shard_loads)
                hot_shards = [s for s, load in shard_loads.items()
                             if load > avg_load * 1.5]

                # Reassign hot shards to less loaded workers
                for shard in hot_shards:
                    await self._reassign_shard(shard)

    async def collect_metrics(self) -> Dict:
        """Aggregate metrics from all components"""

        metrics = {
            'workers': {},
            'queues': {},
            'shards': {},
            'system': {}
        }

        # Collect worker metrics
        for worker_type, workers in self.workers.items():
            metrics['workers'][worker_type] = {
                'count': len(workers),
                'tasks_processed': sum(w.tasks_processed for w in workers),
                'error_rate': self._calculate_error_rate(workers)
            }

        # Collect queue metrics
        for shard in range(16):
            for stream_type in ['task:ready', 'task:completed']:
                key = f"{stream_type}:{shard}"
                metrics['queues'][key] = await self.redis.xlen(key)

        # System metrics
        metrics['system'] = {
            'memory_usage': self._get_memory_usage(),
            'cpu_usage': self._get_cpu_usage(),
            'network_io': self._get_network_io()
        }

        return metrics
```

## Repurposed SystemManager Features

### 1. Worker Lifecycle Management
```python
class WorkerLifecycleManager:
    async def start_worker(self, worker_type: str, config: Dict):
        """Start a new worker process"""

    async def stop_worker(self, worker_id: str, graceful: bool = True):
        """Stop a worker with optional grace period"""

    async def restart_worker(self, worker_id: str):
        """Restart a failed worker"""

    async def upgrade_worker(self, worker_id: str, new_version: str):
        """Rolling upgrade of worker"""
```

### 2. Service Discovery & Registration
```python
class ServiceRegistry:
    async def register_worker(self, worker: Worker):
        """Register worker in Redis for discovery"""
        await self.redis.hset(f"workers:{worker.type}", worker.id, {
            "host": worker.host,
            "port": worker.port,
            "shards": worker.shards,
            "started": datetime.now()
        })

    async def discover_workers(self, worker_type: str) -> List[Worker]:
        """Discover available workers of type"""
        return await self.redis.hgetall(f"workers:{worker_type}")
```

### 3. Load Balancing & Sharding
```python
class LoadBalancer:
    async def assign_work(self, task: Task) -> str:
        """Intelligently assign task to worker"""

        # Get shard for workflow
        shard = hash(task.workflow_id) % 16

        # Find least loaded worker for shard
        workers = await self.registry.get_workers_for_shard(shard)

        # Pick worker with smallest queue
        best_worker = min(workers, key=lambda w: w.queue_depth)

        return best_worker.id
```

### 4. Health Monitoring & Recovery
```python
class HealthMonitor:
    async def monitor_workers(self):
        """Continuously monitor worker health"""

        for worker in self.workers:
            if not await worker.is_healthy():
                await self.handle_unhealthy_worker(worker)

    async def handle_unhealthy_worker(self, worker: Worker):
        """Handle unhealthy worker"""

        # Remove from rotation
        await self.registry.mark_unhealthy(worker)

        # Reassign shards
        await self.shard_manager.reassign_shards(worker.shards)

        # Restart worker
        await self.restart_worker(worker)
```

## Benefits of Repurposing

### 1. **Leverages Existing Code**
- Reuse monitoring mixins
- Keep health check logic
- Maintain Redis connectivity

### 2. **Clear Separation of Concerns**
- Orchestrator manages infrastructure
- Workers process tasks
- API handles requests

### 3. **Enterprise Features**
- Service discovery
- Health monitoring
- Auto-scaling
- Zero-downtime deployments

### 4. **Operational Excellence**
```bash
# Single command to manage everything
gleitzeit orchestrator start

# Auto-scales workers based on load
gleitzeit orchestrator auto-scale --min=10 --max=100

# Rolling deployment
gleitzeit orchestrator deploy --version=2.0
```

## Migration Path

### Phase 1: Add Orchestration Features
```python
# Add to existing SystemManager
class ModularStreamSystemManager:
    # Keep existing code

    # Add new orchestration methods
    async def manage_workers(self):
        """New: Manage worker lifecycle"""

    async def monitor_health(self):
        """New: Monitor component health"""
```

### Phase 2: Shift Responsibilities
```python
# Move task processing to workers
# Keep component management in SystemManager
if USE_ORCHESTRATOR_MODE:
    await self.manage_workers()  # New role
else:
    await self.process_tasks()   # Old role
```

### Phase 3: Complete Transformation
```python
# Rename and refocus
class ComponentOrchestrator:  # Was: SystemManager
    # Remove all task processing
    # Keep only component management
```

## Real-World Equivalents

### Kubernetes Controller
- Manages pods (workers)
- Handles scaling
- Health checks
- Service discovery

### Netflix Conductor
- Orchestrates microservices
- Doesn't process tasks itself
- Manages component lifecycle

### Apache Mesos
- Resource manager
- Schedules work to agents
- Monitors health

## Conclusion

Repurposing SystemManager as a **Component Orchestrator** is brilliant because:

1. **Preserves investment** in existing code
2. **Provides essential** infrastructure management
3. **Enables enterprise** features (auto-scaling, health checks)
4. **Clear responsibility**: Infrastructure, not business logic

The SystemManager transforms from a bottleneck into an **enabler** - managing the workers that do the actual work!

This is the **perfect evolution** of the SystemManager concept!