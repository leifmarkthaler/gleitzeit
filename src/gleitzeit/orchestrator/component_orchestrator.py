"""
Component Orchestrator for Gleitzeit 0.0.7

Manages the lifecycle of all Gleitzeit workers and infrastructure components.
This is the repurposed SystemManager - instead of processing tasks, it manages workers.
"""

import asyncio
import logging
import json
import signal
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import redis.asyncio as aioredis
import psutil
from enum import Enum
from ..core.sharding import default_sharding

logger = logging.getLogger(__name__)


class WorkerState(Enum):
    """Worker states"""
    STARTING = "starting"
    RUNNING = "running"
    UNHEALTHY = "unhealthy"
    STOPPING = "stopping"
    STOPPED = "stopped"


@dataclass
class WorkerSpec:
    """Worker specification"""
    worker_type: str
    worker_class: str
    count: int = 1
    shards: Optional[List[int]] = None
    max_concurrent: int = 10
    batch_size: int = 10  # Added batch_size
    block_timeout: int = 5000  # Added block_timeout (milliseconds)
    auto_scale: bool = False
    min_replicas: int = 1
    max_replicas: int = 10
    scale_threshold_high: int = 100  # Queue depth per worker to scale up
    scale_threshold_low: int = 10   # Queue depth per worker to scale down


@dataclass
class ManagedWorker:
    """Managed worker instance"""
    worker_id: str
    worker_type: str
    process: Optional[asyncio.subprocess.Process] = None
    task: Optional[asyncio.Task] = None
    state: WorkerState = WorkerState.STOPPED
    assigned_shards: List[int] = field(default_factory=list)
    started_at: Optional[datetime] = None
    health_check_failures: int = 0
    metrics: Dict[str, Any] = field(default_factory=dict)


class ComponentOrchestrator:
    """
    Manages the lifecycle of all Gleitzeit components.

    This is what SystemManager evolved into - instead of processing
    workflows/tasks, it manages the workers that do the processing.
    """

    def __init__(self, redis_url: Optional[str] = None, config: Optional[Dict] = None, machine_id: Optional[str] = None):
        self.config = config or {}

        # Generate unique machine ID if not provided
        import socket
        import os
        self.machine_id = machine_id or f"{socket.gethostname()}-{os.getpid()}"

        # Use Redis URL from config if not provided directly
        if redis_url:
            self.redis_url = redis_url
        elif self.config.get('redis'):
            redis_config = self.config['redis']
            if redis_config.get('mode') == 'single':
                single = redis_config.get('single_node', {})
                host = single.get('host', 'localhost')
                port = single.get('port', 6379)
                db = single.get('db', 0)
                self.redis_url = f"redis://{host}:{port}/{db}"
            else:
                # For cluster mode, use first node
                cluster_nodes = redis_config.get('cluster_nodes', [])
                if cluster_nodes:
                    node = cluster_nodes[0]
                    self.redis_url = f"redis://{node['host']}:{node['port']}"
                else:
                    self.redis_url = "redis://localhost:6379"
        else:
            self.redis_url = "redis://localhost:6379"

        self.redis: Optional[aioredis.Redis] = None

        # Worker management
        self.worker_specs: Dict[str, WorkerSpec] = {}
        self.managed_workers: Dict[str, ManagedWorker] = {}
        self.worker_processes: Dict[str, asyncio.subprocess.Process] = {}

        # Component health
        self.health_status: Dict[str, bool] = {}

        # Orchestrator state
        self._running = False
        self._tasks: Set[asyncio.Task] = set()

        # Sharding configuration
        sharding_config = self.config.get('sharding', {})
        self.num_shards = sharding_config.get('num_shards', 16)
        self.shard_assignments: Dict[int, List[str]] = {
            i: [] for i in range(self.num_shards)
        }

    async def initialize(self):
        """Initialize orchestrator and core infrastructure"""
        logger.info("Initializing ComponentOrchestrator")

        # Setup Redis connection
        self.redis = await aioredis.from_url(
            self.redis_url,
            decode_responses=False
        )

        # Load worker configurations
        self.load_worker_specs()

        # Setup signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_shutdown)

        logger.info("ComponentOrchestrator initialized")

    def load_worker_specs(self):
        """Load worker specifications from config"""
        default_specs = [
            WorkerSpec(
                worker_type="task_execution",
                worker_class="gleitzeit.workers.task_execution_worker.TaskExecutionWorker",
                count=5,
                auto_scale=True,
                max_replicas=50
            ),
            WorkerSpec(
                worker_type="retry",
                worker_class="gleitzeit.workers.retry_worker.RetryWorker",
                count=2,
                auto_scale=True,
                max_replicas=10
            ),
            WorkerSpec(
                worker_type="dependency",
                worker_class="gleitzeit.workers.dependency_worker.DependencyWorker",
                count=3,
                auto_scale=True,
                max_replicas=20
            ),
            WorkerSpec(
                worker_type="workflow_loader",
                worker_class="gleitzeit.workers.workflow_loader_worker.WorkflowLoaderWorker",
                count=2,
                auto_scale=False
            ),
        ]

        # Use config specs or defaults
        specs = self.config.get('workers', default_specs)
        for spec in specs:
            if isinstance(spec, dict):
                spec = WorkerSpec(**spec)
            self.worker_specs[spec.worker_type] = spec

    async def start(self):
        """Start the orchestrator and all managed components"""
        logger.info("Starting ComponentOrchestrator")
        self._running = True

        # Register this orchestrator instance
        import os
        pid = os.getpid()
        orchestrator_key = f"orchestrator:{self.machine_id}"
        orchestrator_info = {
            "pid": str(pid),
            "machine_id": self.machine_id,
            "started_at": datetime.utcnow().isoformat(),
            "status": "running"
        }
        await self.redis.hset(orchestrator_key.encode(), mapping={k.encode(): v.encode() for k, v in orchestrator_info.items()})
        await self.redis.expire(orchestrator_key.encode(), 120)  # 2 minute TTL

        # Start heartbeat task to keep registration alive
        self._tasks.add(asyncio.create_task(self.orchestrator_heartbeat()))

        logger.info(f"Orchestrator registered: {self.machine_id} (PID: {pid})")

        # Start initial workers
        await self.start_all_workers()

        # Start monitoring tasks
        self._tasks.add(asyncio.create_task(self.health_monitor()))
        self._tasks.add(asyncio.create_task(self.auto_scaler()))
        self._tasks.add(asyncio.create_task(self.metrics_collector()))

        # Wait for shutdown
        try:
            while self._running:
                await asyncio.sleep(1)
        finally:
            await self.shutdown()

    async def start_all_workers(self):
        """Start all configured workers"""
        for worker_type, spec in self.worker_specs.items():
            logger.info(f"Starting {spec.count} {worker_type} workers")

            for i in range(spec.count):
                # Include machine ID in worker ID to ensure uniqueness across machines
                worker_id = f"{self.machine_id}-{worker_type}-{i}"

                # Assign shards
                assigned_shards = self.assign_shards_to_worker(
                    worker_id,
                    worker_type
                )

                # Start worker
                await self.start_worker(
                    worker_id=worker_id,
                    worker_type=worker_type,
                    worker_class=spec.worker_class,
                    assigned_shards=assigned_shards,
                    max_concurrent=spec.max_concurrent,
                    batch_size=spec.batch_size,
                    block_timeout=spec.block_timeout
                )

    async def start_worker(
        self,
        worker_id: str,
        worker_type: str,
        worker_class: str,
        assigned_shards: List[int],
        max_concurrent: int = 10,
        batch_size: int = 10,
        block_timeout: int = 5000
    ):
        """Start a single worker process"""
        logger.info(f"Starting worker {worker_id} with shards {assigned_shards}")

        # Create managed worker entry
        managed_worker = ManagedWorker(
            worker_id=worker_id,
            worker_type=worker_type,
            assigned_shards=assigned_shards,
            state=WorkerState.STARTING,
            started_at=datetime.utcnow()
        )

        # Start worker as subprocess
        cmd = [
            "python", "-m", "gleitzeit.workers.runner",
            "--worker-class", worker_class,
            "--worker-id", worker_id,
            "--redis-url", self.redis_url,
            "--shards", ",".join(map(str, assigned_shards)),
            "--max-concurrent", str(max_concurrent),
            "--batch-size", str(batch_size),
            "--block-timeout", str(block_timeout)
        ]

        try:
            # Pass environment variables to subprocess
            import os
            env = os.environ.copy()
            # Ensure correct PYTHONPATH
            import pathlib
            src_path = str(pathlib.Path(__file__).parent.parent.parent.absolute())
            env['PYTHONPATH'] = f"{src_path}:{env.get('PYTHONPATH', '')}"

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )

            managed_worker.process = process
            managed_worker.state = WorkerState.RUNNING

            # Monitor process output
            managed_worker.task = asyncio.create_task(
                self.monitor_worker_output(worker_id, process)
            )

        except Exception as e:
            logger.error(f"Failed to start worker {worker_id}: {e}")
            managed_worker.state = WorkerState.STOPPED

        self.managed_workers[worker_id] = managed_worker

        # Register in service discovery
        await self.register_worker(managed_worker)

    async def monitor_worker_output(
        self,
        worker_id: str,
        process: asyncio.subprocess.Process
    ):
        """Monitor worker process output"""
        async def read_stream(stream, prefix):
            while process.returncode is None:
                try:
                    line = await asyncio.wait_for(
                        stream.readline(),
                        timeout=1.0
                    )
                    if line:
                        msg = line.decode().strip()
                        if "ERROR" in msg or "CRITICAL" in msg or "unhealthy" in msg.lower():
                            logger.error(f"[{worker_id}:{prefix}] {msg}")
                        elif "WARNING" in msg:
                            logger.warning(f"[{worker_id}:{prefix}] {msg}")
                        else:
                            logger.info(f"[{worker_id}:{prefix}] {msg}")
                except asyncio.TimeoutError:
                    pass
                except Exception as e:
                    logger.error(f"Error monitoring {worker_id} {prefix}: {e}")
                    break

        # Monitor both stdout and stderr
        await asyncio.gather(
            read_stream(process.stdout, "stdout"),
            read_stream(process.stderr, "stderr"),
            return_exceptions=True
        )

    def assign_shards_to_worker(
        self,
        worker_id: str,
        worker_type: str
    ) -> List[int]:
        """Assign shards to a worker based on round-robin distribution"""
        # Get worker index
        worker_index = int(worker_id.split('-')[-1])

        # Get total workers of this type
        total_workers = self.worker_specs[worker_type].count

        # Assign shards round-robin
        assigned = []
        for shard in range(self.num_shards):
            if shard % total_workers == worker_index:
                assigned.append(shard)
                self.shard_assignments[shard].append(worker_id)

        return assigned

    async def health_monitor(self):
        """Monitor health of all components"""
        while self._running:
            try:
                # Check worker health
                for worker_id, worker in self.managed_workers.items():
                    if worker.state == WorkerState.RUNNING:
                        is_healthy = await self.check_worker_health(worker_id)

                        if not is_healthy:
                            worker.health_check_failures += 1

                            if worker.health_check_failures > 3:
                                logger.warning(f"Worker {worker_id} unhealthy, restarting")
                                await self.restart_worker(worker_id)
                        else:
                            worker.health_check_failures = 0

                # Check Redis health
                try:
                    await self.redis.ping()
                    self.health_status['redis'] = True
                except:
                    self.health_status['redis'] = False
                    logger.error("Redis connection unhealthy")

                await asyncio.sleep(10)  # Check every 10 seconds

            except Exception as e:
                logger.error(f"Health monitor error: {e}")
                await asyncio.sleep(5)

    async def check_worker_health(self, worker_id: str) -> bool:
        """Check if a worker is healthy"""
        try:
            # Check process is running
            worker = self.managed_workers.get(worker_id)
            if not worker or not worker.process:
                return False

            if worker.process.returncode is not None:
                return False

            # Check worker heartbeat in Redis (on shard 0)
            heartbeat = await self.redis.hget(
                f"{{shard:0}}:worker:metrics:{worker_id}".encode(),
                b"last_heartbeat"
            )

            if heartbeat:
                last_heartbeat = datetime.fromisoformat(heartbeat.decode())
                age = datetime.utcnow() - last_heartbeat

                if age > timedelta(seconds=60):
                    return False
            else:
                return False

            return True

        except Exception as e:
            logger.error(f"Health check failed for {worker_id}: {e}")
            return False

    async def auto_scaler(self):
        """Auto-scale workers based on queue depth"""
        while self._running:
            try:
                for worker_type, spec in self.worker_specs.items():
                    if not spec.auto_scale:
                        continue

                    # Get queue metrics
                    metrics = await self.get_queue_metrics(worker_type)
                    current_count = sum(
                        1 for w in self.managed_workers.values()
                        if w.worker_type == worker_type and w.state == WorkerState.RUNNING
                    )

                    if not current_count:
                        continue

                    avg_queue_depth = metrics['total_pending'] / current_count

                    # Scale up
                    if avg_queue_depth > spec.scale_threshold_high:
                        if current_count < spec.max_replicas:
                            scale_to = min(current_count + 5, spec.max_replicas)
                            await self.scale_workers(worker_type, scale_to)
                            logger.info(f"Scaled up {worker_type} to {scale_to} workers")

                    # Scale down
                    elif avg_queue_depth < spec.scale_threshold_low:
                        if current_count > spec.min_replicas:
                            scale_to = max(current_count - 1, spec.min_replicas)
                            await self.scale_workers(worker_type, scale_to)
                            logger.info(f"Scaled down {worker_type} to {scale_to} workers")

                await asyncio.sleep(30)  # Check every 30 seconds

            except Exception as e:
                logger.error(f"Auto-scaler error: {e}")
                await asyncio.sleep(30)

    async def orchestrator_heartbeat(self):
        """Maintain orchestrator registration in Redis"""
        while self._running:
            try:
                orchestrator_key = f"orchestrator:{self.machine_id}"
                await self.redis.hset(
                    orchestrator_key.encode(),
                    b"last_heartbeat",
                    datetime.utcnow().isoformat().encode()
                )
                await self.redis.expire(orchestrator_key.encode(), 120)  # Refresh TTL

                # Also publish metrics about this orchestrator's workers
                local_workers = len([w for w in self.managed_workers.values() if w.state == WorkerState.RUNNING])
                await self.redis.hset(
                    orchestrator_key.encode(),
                    b"worker_count",
                    str(local_workers).encode()
                )

                await asyncio.sleep(30)  # Heartbeat every 30 seconds
            except Exception as e:
                logger.error(f"Orchestrator heartbeat error: {e}")
                await asyncio.sleep(10)

    async def get_queue_metrics(self, worker_type: str) -> Dict[str, int]:
        """Get queue depth metrics for a worker type"""
        metrics = {
            'total_pending': 0,
            'by_shard': {}
        }

        # Map worker types to stream patterns
        stream_patterns = {
            'task_execution': ['task:ready', 'task:retry'],
            'dependency': ['task:completed', 'workflow:submitted'],
            'workflow_loader': ['workflow:load', 'workflow:reload']
        }

        patterns = stream_patterns.get(worker_type, [])

        for pattern in patterns:
            for shard in range(self.num_shards):
                # Use proper shard key format
                stream_key = f"{{shard:{shard}}}:{pattern}".encode()
                length = await self.redis.xlen(stream_key)
                metrics['total_pending'] += length
                metrics['by_shard'][shard] = metrics['by_shard'].get(shard, 0) + length

        return metrics

    async def scale_workers(self, worker_type: str, target_count: int):
        """Scale workers to target count"""
        current_workers = [
            (wid, w) for wid, w in self.managed_workers.items()
            if w.worker_type == worker_type and w.state == WorkerState.RUNNING
        ]
        current_count = len(current_workers)

        if target_count > current_count:
            # Scale up
            spec = self.worker_specs[worker_type]
            for i in range(current_count, target_count):
                # Include machine ID in worker ID for uniqueness
                worker_id = f"{self.machine_id}-{worker_type}-{i}"

                # For autoscaling, distribute shards evenly across workers
                # When workers > shards, some workers will get fewer or no shards
                assigned_shards = []

                # Use min to ensure we don't try to distribute more than exists
                workers_with_shards = min(target_count, self.num_shards)

                # Only assign shards if this worker should have them
                if i < workers_with_shards:
                    for shard in range(self.num_shards):
                        # Distribute shards evenly across workers that should have shards
                        if shard % workers_with_shards == i:
                            assigned_shards.append(shard)

                await self.start_worker(
                    worker_id=worker_id,
                    worker_type=worker_type,
                    worker_class=spec.worker_class,
                    assigned_shards=assigned_shards,
                    max_concurrent=spec.max_concurrent,
                    batch_size=spec.batch_size,
                    block_timeout=spec.block_timeout
                )

        elif target_count < current_count:
            # Scale down - stop oldest workers first
            workers_to_stop = sorted(
                current_workers,
                key=lambda x: x[1].started_at or datetime.min
            )[:current_count - target_count]

            for worker_id, _ in workers_to_stop:
                await self.stop_worker(worker_id)

    async def restart_worker(self, worker_id: str):
        """Restart a worker"""
        worker = self.managed_workers.get(worker_id)
        if not worker:
            return

        logger.info(f"Restarting worker {worker_id}")

        # Stop old process
        await self.stop_worker(worker_id, remove=False)

        # Start new process
        spec = self.worker_specs[worker.worker_type]
        await self.start_worker(
            worker_id=worker_id,
            worker_type=worker.worker_type,
            worker_class=spec.worker_class,
            assigned_shards=worker.assigned_shards,
            max_concurrent=spec.max_concurrent,
            batch_size=spec.batch_size,
            block_timeout=spec.block_timeout
        )

    async def stop_worker(self, worker_id: str, remove: bool = True):
        """Stop a worker process"""
        worker = self.managed_workers.get(worker_id)
        if not worker:
            return

        logger.info(f"Stopping worker {worker_id}")
        worker.state = WorkerState.STOPPING

        # Terminate process
        if worker.process:
            try:
                # Check if process is still running
                if worker.process.returncode is None:
                    worker.process.terminate()
                    try:
                        await asyncio.wait_for(worker.process.wait(), timeout=10)
                    except asyncio.TimeoutError:
                        worker.process.kill()
                        await worker.process.wait()
            except ProcessLookupError:
                # Process already dead
                pass

        # Cancel monitoring task
        if worker.task:
            worker.task.cancel()

        worker.state = WorkerState.STOPPED

        # Deregister from service discovery
        await self.deregister_worker(worker)

        # Remove from managed workers
        if remove:
            del self.managed_workers[worker_id]

    async def register_worker(self, worker: ManagedWorker):
        """Register worker in service discovery"""
        worker_info = {
            b"worker_type": worker.worker_type.encode(),
            b"worker_id": worker.worker_id.encode(),
            b"shards": json.dumps(worker.assigned_shards).encode(),
            b"started_at": worker.started_at.isoformat().encode() if worker.started_at else b"",
            b"state": worker.state.value.encode()
        }

        key = default_sharding.get_worker_key(worker.worker_type, worker.worker_id)
        await self.redis.hset(key.encode(), mapping=worker_info)
        await self.redis.expire(key.encode(), 120)  # 2 minute TTL

    async def deregister_worker(self, worker: ManagedWorker):
        """Remove worker from service discovery"""
        key = default_sharding.get_worker_key(worker.worker_type, worker.worker_id)
        await self.redis.delete(key.encode())

    async def metrics_collector(self):
        """Collect and aggregate metrics from all components"""
        while self._running:
            try:
                metrics = {
                    'timestamp': datetime.utcnow().isoformat(),
                    'workers': {},
                    'queues': {},
                    'system': {}
                }

                # Collect worker metrics
                for worker_id, worker in self.managed_workers.items():
                    if worker.state != WorkerState.RUNNING:
                        continue

                    worker_metrics = await self.redis.hgetall(
                        f"{{shard:0}}:worker:metrics:{worker_id}".encode()
                    )

                    if worker_metrics:
                        metrics['workers'][worker_id] = {
                            k.decode(): v.decode() for k, v in worker_metrics.items()
                        }

                # Collect queue metrics
                for worker_type in self.worker_specs.keys():
                    metrics['queues'][worker_type] = await self.get_queue_metrics(worker_type)

                # System metrics
                metrics['system'] = {
                    'cpu_percent': psutil.cpu_percent(),
                    'memory_percent': psutil.virtual_memory().percent,
                    'redis_healthy': self.health_status.get('redis', False)
                }

                # Store aggregated metrics
                await self.redis.hset(
                    b"orchestrator:metrics",
                    b"latest",
                    json.dumps(metrics).encode()
                )

                await asyncio.sleep(60)  # Collect every minute

            except Exception as e:
                logger.error(f"Metrics collector error: {e}")
                await asyncio.sleep(60)

    def _handle_shutdown(self):
        """Handle graceful shutdown signal"""
        logger.info("Shutdown signal received")
        self._running = False

    async def shutdown(self):
        """Gracefully shutdown all components"""
        logger.info(f"Shutting down ComponentOrchestrator {self.machine_id}")

        # Deregister this orchestrator
        orchestrator_key = f"orchestrator:{self.machine_id}"
        await self.redis.delete(orchestrator_key.encode())

        # Stop all workers
        worker_ids = list(self.managed_workers.keys())
        for worker_id in worker_ids:
            await self.stop_worker(worker_id)

        # Cancel monitoring tasks
        for task in self._tasks:
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        # Close Redis connection
        if self.redis:
            await self.redis.close()

        logger.info("ComponentOrchestrator shutdown complete")

    async def get_status(self) -> Dict[str, Any]:
        """Get orchestrator status"""
        return {
            'running': self._running,
            'workers': {
                worker_id: {
                    'type': w.worker_type,
                    'state': w.state.value,
                    'shards': w.assigned_shards,
                    'health_failures': w.health_check_failures
                }
                for worker_id, w in self.managed_workers.items()
            },
            'health': self.health_status,
            'shards': self.shard_assignments
        }


if __name__ == "__main__":
    import sys
    import yaml
    import aiofiles

    if len(sys.argv) < 2:
        print("Usage: python -m gleitzeit.orchestrator.component_orchestrator <config_file>")
        sys.exit(1)

    config_file = sys.argv[1]

    async def main():
        # Load configuration from file asynchronously
        async with aiofiles.open(config_file, 'r') as f:
            content = await f.read()
            config = yaml.safe_load(content)

        # Pass None as redis_url to use config
        # Machine ID will be auto-generated from hostname
        import socket
        machine_id = config.get('machine_id') or socket.gethostname()
        orchestrator = ComponentOrchestrator(redis_url=None, config=config, machine_id=machine_id)
        await orchestrator.initialize()
        try:
            await orchestrator.start()
        except KeyboardInterrupt:
            logger.info("Received interrupt, shutting down...")
        finally:
            await orchestrator.shutdown()

    asyncio.run(main())