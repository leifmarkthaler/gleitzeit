"""
Worker Manager for Gleitzeit

Handles worker-specific process management with shard assignment,
auto-scaling, and health monitoring.
"""

import sys
import asyncio
import logging
import json
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, field
from datetime import datetime

from .process_manager import SmartProcessManager
from .instance import get_current_instance

logger = logging.getLogger(__name__)


@dataclass
class WorkerConfig:
    """Configuration for a worker type"""
    enabled: bool = False
    worker_class: str = ""
    count: int = 1
    max_concurrent: int = 10
    batch_size: int = 10
    block_timeout: int = 5000
    auto_scale: bool = False
    min_replicas: int = 1
    max_replicas: int = 10
    scale_threshold_high: int = 100
    scale_threshold_low: int = 10


class WorkerManager:
    """Manages Gleitzeit workers with proper shard assignment and lifecycle handling"""

    def __init__(self, process_manager: SmartProcessManager, config: Optional[Dict] = None):
        """
        Initialize Worker Manager

        Args:
            process_manager: Core process manager for lifecycle handling
            config: Configuration dictionary
        """
        self.process_manager = process_manager
        self.config = config or {}

        # Instance info for namespacing
        self.instance = get_current_instance()
        if not self.instance:
            raise RuntimeError("Instance identity not initialized")

        # Worker configuration
        self.worker_configs = self._load_worker_configs()
        self.num_shards = self.config.get('sharding', {}).get('num_shards', 16)
        self.shard_assignments: Dict[int, List[str]] = {i: [] for i in range(self.num_shards)}

        # Active workers tracking
        self.active_workers: Dict[str, Dict[str, Any]] = {}

    def _load_worker_configs(self) -> Dict[str, WorkerConfig]:
        """Load worker configurations from config"""
        default_configs = {
            "task_execution": WorkerConfig(
                enabled=False,  # Disabled by default for safety
                worker_class="gleitzeit.workers.task_execution_worker.TaskExecutionWorker",
                count=2,
                auto_scale=True,
                max_replicas=10
            ),
            "dependency": WorkerConfig(
                enabled=False,
                worker_class="gleitzeit.workers.dependency_worker.DependencyWorker",
                count=2,
                auto_scale=True,
                max_replicas=5
            ),
            "retry": WorkerConfig(
                enabled=False,
                worker_class="gleitzeit.workers.retry_worker.RetryWorker",
                count=1,
                auto_scale=False
            ),
            "workflow_loader": WorkerConfig(
                enabled=False,
                worker_class="gleitzeit.workers.workflow_loader_worker.WorkflowLoaderWorker",
                count=1,
                auto_scale=False
            )
        }

        # Load from config and merge
        worker_configs = {}
        config_workers = self.config.get('workers', {})

        # Handle case where workers config is a list (convert to empty dict)
        if isinstance(config_workers, list):
            config_workers = {}

        for worker_type, default_config in default_configs.items():
            config_dict = config_workers.get(worker_type, {})

            # Create WorkerConfig from merged dict
            merged_dict = {
                'enabled': config_dict.get('enabled', default_config.enabled),
                'worker_class': config_dict.get('worker_class', default_config.worker_class),
                'count': config_dict.get('count', default_config.count),
                'max_concurrent': config_dict.get('max_concurrent', default_config.max_concurrent),
                'batch_size': config_dict.get('batch_size', default_config.batch_size),
                'block_timeout': config_dict.get('block_timeout', default_config.block_timeout),
                'auto_scale': config_dict.get('auto_scale', default_config.auto_scale),
                'min_replicas': config_dict.get('min_replicas', default_config.min_replicas),
                'max_replicas': config_dict.get('max_replicas', default_config.max_replicas),
                'scale_threshold_high': config_dict.get('scale_threshold_high', default_config.scale_threshold_high),
                'scale_threshold_low': config_dict.get('scale_threshold_low', default_config.scale_threshold_low)
            }

            worker_configs[worker_type] = WorkerConfig(**merged_dict)

        return worker_configs

    async def start_all_workers(self, kill_existing: bool = False) -> bool:
        """Start all configured workers"""
        results = []

        for worker_type, config in self.worker_configs.items():
            if not config.enabled:
                logger.info(f"Skipping {worker_type} workers (disabled)")
                continue

            if config.count <= 0:
                logger.info(f"Skipping {worker_type} workers (count={config.count})")
                continue

            logger.info(f"Starting {config.count} {worker_type} workers")

            # Start workers for this type
            for i in range(config.count):
                worker_name = f"{worker_type}-{i}"
                assigned_shards = self._assign_shards_to_worker(worker_name, worker_type, i, config.count)

                result = await self.start_worker(
                    worker_name=worker_name,
                    worker_type=worker_type,
                    config=config,
                    assigned_shards=assigned_shards,
                    kill_existing=kill_existing
                )
                results.append(result)

        success = all(results) if results else True
        if success and results:
            logger.info(f"✓ Started {len([r for r in results if r])} workers")

        return success

    async def start_worker(
        self,
        worker_name: str,
        worker_type: str,
        config: WorkerConfig,
        assigned_shards: List[int],
        kill_existing: bool = False
    ) -> bool:
        """Start a single worker process"""
        logger.info(f"Starting worker {worker_name} with shards {assigned_shards}")

        # Use the project's venv python directly (created by uv)
        from pathlib import Path
        project_root = Path(__file__).parent.parent.parent.parent
        venv_python = project_root / ".venv" / "bin" / "python"

        if not venv_python.exists():
            raise RuntimeError(
                f"Virtual environment not found at {venv_python}\n"
                "Please set up the project with uv:\n"
                "  cd <project_root>\n"
                "  uv venv .venv\n"
                "  uv sync"
            )

        # Build command
        cmd = [
            str(venv_python), "-m", "gleitzeit.workers.runner",
            "--worker-class", config.worker_class,
            "--worker-id", worker_name,
            "--redis-url", self.process_manager.redis_url,
            "--shards", ",".join(map(str, assigned_shards)),
            "--max-concurrent", str(config.max_concurrent),
            "--batch-size", str(config.batch_size),
            "--block-timeout", str(config.block_timeout)
        ]

        # Workers don't need ports, use a tracking port
        tracking_port = None

        try:
            # Set up worker environment
            env = {
                'GLEITZEIT_WORKER_TYPE': worker_type,
                'GLEITZEIT_WORKER_SHARDS': ','.join(map(str, assigned_shards)),
                'GLEITZEIT_INSTANCE_ID': self.instance.instance_id,
                'GLEITZEIT_INSTANCE_NAME': self.instance.instance_name,
            }

            process_info = await self.process_manager.start_service(
                service_name=worker_name,
                command=cmd,
                port=tracking_port,
                env=env,
                kill_existing=kill_existing
            )

            if process_info:
                # Track the worker
                self.active_workers[worker_name] = {
                    'worker_type': worker_type,
                    'assigned_shards': assigned_shards,
                    'config': config,
                    'started_at': datetime.utcnow(),
                    'process_info': process_info
                }

                # Persist shard assignment to Redis
                redis = self.process_manager.redis
                if redis:
                    # Add to worker registry
                    await redis.sadd(f"worker:registry:{worker_type}", worker_name)

                    # Store shard assignment
                    await redis.set(
                        f"worker:shards:{worker_name}",
                        json.dumps(assigned_shards),
                        ex=3600  # 1 hour TTL
                    )

                    # Store shard ownership
                    for shard in assigned_shards:
                        await redis.set(
                            f"shard:owner:{shard}",
                            json.dumps({
                                "worker_name": worker_name,
                                "instance_id": self.instance.instance_id
                            }),
                            ex=3600
                        )

                logger.info(f"✓ Worker {worker_name} started (PID: {process_info.pid})")
                return True
            else:
                logger.error(f"Failed to start worker {worker_name}")
                return False

        except Exception as e:
            logger.error(f"Error starting worker {worker_name}: {e}")
            return False

    def _assign_shards_to_worker(self, worker_name: str, worker_type: str, index: int, total: int) -> List[int]:
        """Assign shards to a worker using round-robin distribution"""
        if total <= 0:
            return []

        assigned = []
        for shard in range(self.num_shards):
            if shard % total == index:
                assigned.append(shard)
                # Track shard assignment
                if shard not in self.shard_assignments:
                    self.shard_assignments[shard] = []
                self.shard_assignments[shard].append(worker_name)

        logger.debug(f"Assigned shards {assigned} to {worker_name}")
        return assigned

    async def stop_worker(self, worker_name: str) -> None:
        """Stop a specific worker"""
        if worker_name in self.active_workers:
            await self.process_manager.stop_service(worker_name)

            # Clean up shard assignments
            worker_info = self.active_workers[worker_name]
            for shard in worker_info.get('assigned_shards', []):
                if shard in self.shard_assignments:
                    if worker_name in self.shard_assignments[shard]:
                        self.shard_assignments[shard].remove(worker_name)

            # Remove from active workers
            del self.active_workers[worker_name]
            logger.info(f"Worker {worker_name} stopped")

    async def stop_all_workers(self) -> None:
        """Stop all workers"""
        worker_names = list(self.active_workers.keys())
        for worker_name in worker_names:
            try:
                await self.stop_worker(worker_name)
            except Exception as e:
                logger.error(f"Error stopping worker {worker_name}: {e}")

    async def scale_workers(self, worker_type: str, target_count: int) -> bool:
        """Scale workers of a specific type to target count"""
        if worker_type not in self.worker_configs:
            logger.error(f"Unknown worker type: {worker_type}")
            return False

        config = self.worker_configs[worker_type]
        current_workers = [
            name for name, info in self.active_workers.items()
            if info['worker_type'] == worker_type
        ]
        current_count = len(current_workers)

        if target_count == current_count:
            logger.info(f"Worker count for {worker_type} already at target: {target_count}")
            return True

        elif target_count > current_count:
            # Scale up
            logger.info(f"Scaling up {worker_type} from {current_count} to {target_count}")
            for i in range(current_count, target_count):
                worker_name = f"{worker_type}-{i}"
                assigned_shards = self._assign_shards_to_worker(worker_name, worker_type, i, target_count)

                result = await self.start_worker(
                    worker_name=worker_name,
                    worker_type=worker_type,
                    config=config,
                    assigned_shards=assigned_shards,
                    kill_existing=False
                )
                if not result:
                    logger.error(f"Failed to scale up worker {worker_name}")
                    return False

        else:
            # Scale down
            logger.info(f"Scaling down {worker_type} from {current_count} to {target_count}")
            workers_to_stop = current_workers[target_count:]
            for worker_name in workers_to_stop:
                await self.stop_worker(worker_name)

        return True

    def get_worker_status(self) -> Dict[str, Any]:
        """Get status of all workers"""
        status = {
            'instance_id': self.instance.instance_id,
            'total_workers': len(self.active_workers),
            'workers_by_type': {},
            'shard_assignments': self.shard_assignments,
            'workers': {}
        }

        # Group by type
        for worker_name, worker_info in self.active_workers.items():
            worker_type = worker_info['worker_type']
            if worker_type not in status['workers_by_type']:
                status['workers_by_type'][worker_type] = []
            status['workers_by_type'][worker_type].append(worker_name)

            # Individual worker status
            status['workers'][worker_name] = {
                'worker_type': worker_type,
                'assigned_shards': worker_info['assigned_shards'],
                'started_at': worker_info['started_at'].isoformat(),
                'pid': worker_info['process_info'].pid,
                'status': worker_info['process_info'].status
            }

        return status

    async def health_check_workers(self) -> Dict[str, bool]:
        """Perform health checks on all workers"""
        health_status = {}

        for worker_name, worker_info in self.active_workers.items():
            # For now, just check if process is running
            # Future: check worker heartbeats in Redis
            process_info = worker_info['process_info']
            health_status[worker_name] = process_info.status == 'running'

        return health_status

    def get_worker_configs(self) -> Dict[str, WorkerConfig]:
        """Get worker configurations"""
        return self.worker_configs