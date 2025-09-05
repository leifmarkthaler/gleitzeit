"""
Scalable Provider Implementation with Pull-Based Task Execution

This module provides horizontally scalable provider implementations that
pull tasks from queues and execute them in parallel.
"""

import asyncio
import logging
import json
from typing import Optional, Dict, Any, List
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from gleitzeit.core.models import TaskStatus, TaskResult
from gleitzeit.persistence.base import PersistenceBackend
from gleitzeit.events.base import EventBus
from gleitzeit.core.events import GleitzeitEvent, EventType
from gleitzeit.providers.base import ProtocolProvider

logger = logging.getLogger(__name__)


class ScalableProviderAdapter:
    """
    Scalable adapter for protocol providers that supports multiple workers.
    
    Features:
    - Multiple concurrent workers per instance
    - Pull-based task acquisition from Redis queues
    - Automatic retry on transient failures
    - Health monitoring and metrics
    - Graceful shutdown
    """
    
    def __init__(
        self,
        provider: ProtocolProvider,
        persistence: PersistenceBackend,
        event_bus: EventBus,
        protocol: str,
        node_id: str = "provider-1",
        num_workers: int = 5,
        max_retries: int = 3
    ):
        """
        Initialize scalable provider adapter.
        
        Args:
            provider: The protocol provider to execute tasks
            persistence: Backend for state storage
            event_bus: Event bus for coordination
            protocol: Protocol name this adapter handles
            node_id: Unique identifier for this adapter instance
            num_workers: Number of concurrent workers
            max_retries: Maximum retries for transient failures
        """
        self.provider = provider
        self.persistence = persistence
        self.event_bus = event_bus
        self.protocol = protocol
        self.node_id = node_id
        self.num_workers = num_workers
        self.max_retries = max_retries
        
        # Worker management
        self.workers: List[asyncio.Task] = []
        self.running = False
        
        # Metrics
        self.metrics = {
            "tasks_processed": 0,
            "tasks_succeeded": 0,
            "tasks_failed": 0,
            "total_execution_time": 0.0,
            "started_at": None,
            "worker_status": {}
        }
        
        # Thread pool for CPU-bound tasks
        self.executor = ThreadPoolExecutor(max_workers=num_workers)
        
        logger.info(
            f"ScalableProviderAdapter initialized: {node_id} "
            f"with {num_workers} workers for protocol {protocol}"
        )
    
    async def start(self):
        """Start all workers."""
        if self.running:
            logger.warning(f"Adapter {self.node_id} already running")
            return
        
        self.running = True
        self.metrics["started_at"] = datetime.utcnow()
        
        # Start workers
        for worker_id in range(self.num_workers):
            worker = asyncio.create_task(
                self._worker_loop(worker_id),
                name=f"{self.node_id}-worker-{worker_id}"
            )
            self.workers.append(worker)
            self.metrics["worker_status"][worker_id] = "running"
        
        # Start health monitor
        asyncio.create_task(self._health_monitor())
        
        logger.info(f"Started {self.num_workers} workers for {self.node_id}")
    
    async def stop(self):
        """Stop all workers gracefully."""
        logger.info(f"Stopping adapter {self.node_id}")
        self.running = False
        
        # Wait for workers to finish current tasks
        if self.workers:
            await asyncio.gather(*self.workers, return_exceptions=True)
            self.workers.clear()
        
        # Shutdown executor
        self.executor.shutdown(wait=True)
        
        logger.info(f"Adapter {self.node_id} stopped")
    
    async def _worker_loop(self, worker_id: int):
        """
        Main worker loop that pulls and executes tasks.
        
        Args:
            worker_id: Unique identifier for this worker
        """
        queue_key = f"provider:queue:{self.protocol}"
        worker_name = f"{self.node_id}-worker-{worker_id}"
        
        logger.info(f"Worker {worker_name} started")
        
        while self.running:
            try:
                # Try to get a task from queue
                result = await self._pull_task(queue_key)
                
                if result:
                    _, task_json = result
                    await self._execute_task(task_json, worker_id)
                else:
                    # No task available, short sleep
                    await asyncio.sleep(0.1)
                    
            except Exception as e:
                logger.error(f"Worker {worker_name} error: {e}")
                await asyncio.sleep(1)  # Back off on error
        
        self.metrics["worker_status"][worker_id] = "stopped"
        logger.info(f"Worker {worker_name} stopped")
    
    async def _pull_task(self, queue_key: str) -> Optional[tuple]:
        """
        Pull a task from the queue.
        
        Args:
            queue_key: Redis queue key
            
        Returns:
            Tuple of (key, task_json) or None if no task available
        """
        if hasattr(self.persistence, 'redis'):
            return await self.persistence.redis.brpop(queue_key, timeout=1)
        else:
            # Fallback for testing without Redis
            return await self.persistence.brpop(queue_key, timeout=1)
    
    async def _execute_task(self, task_json: str, worker_id: int):
        """
        Execute a single task.
        
        Args:
            task_json: JSON-encoded task data
            worker_id: ID of the worker executing this task
        """
        start_time = datetime.utcnow()
        task_data = json.loads(task_json)
        task_id = task_data["task_id"]
        workflow_id = task_data["workflow_id"]
        
        logger.debug(f"Worker {worker_id} executing task {task_id}")
        
        # Update task status to EXECUTING
        await self._update_task_status(task_id, TaskStatus.EXECUTING)
        
        # Emit TASK_STARTED event
        await self.event_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_STARTED,
            data={
                "task_id": task_id,
                "workflow_id": workflow_id,
                "worker": f"{self.node_id}-{worker_id}",
                "timestamp": datetime.utcnow().isoformat()
            }
        ))
        
        # Execute with retries
        result = None
        error = None
        attempts = 0
        
        while attempts < self.max_retries:
            attempts += 1
            
            try:
                # Execute the task
                if asyncio.iscoroutinefunction(self.provider.execute):
                    result = await self.provider.execute(
                        task_data["method"],
                        task_data["params"]
                    )
                else:
                    # Run sync provider in thread pool
                    result = await asyncio.get_event_loop().run_in_executor(
                        self.executor,
                        self.provider.execute,
                        task_data["method"],
                        task_data["params"]
                    )
                
                # Success
                break
                
            except Exception as e:
                error = str(e)
                logger.warning(
                    f"Task {task_id} attempt {attempts} failed: {error}"
                )
                
                if attempts < self.max_retries:
                    await asyncio.sleep(2 ** attempts)  # Exponential backoff
        
        # Calculate execution time
        execution_time = (datetime.utcnow() - start_time).total_seconds()
        
        # Save result
        if result is not None:
            # Success
            task_result = TaskResult(
                task_id=task_id,
                status=TaskStatus.COMPLETED,
                result=result,
                completed_at=datetime.utcnow()
            )
            
            await self.persistence.save_task_result(task_result)
            
            # Update metrics
            self.metrics["tasks_processed"] += 1
            self.metrics["tasks_succeeded"] += 1
            self.metrics["total_execution_time"] += execution_time
            
            # Emit TASK_COMPLETED event
            await self.event_bus.emit(GleitzeitEvent(
                event_type=EventType.TASK_COMPLETED,
                data={
                    "task_id": task_id,
                    "workflow_id": workflow_id,
                    "result": result,
                    "worker": f"{self.node_id}-{worker_id}",
                    "execution_time": execution_time,
                    "timestamp": datetime.utcnow().isoformat()
                }
            ))
            
            logger.info(
                f"Task {task_id} completed by worker {worker_id} "
                f"in {execution_time:.2f}s"
            )
            
        else:
            # Failure after all retries
            task_result = TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error=error,
                completed_at=datetime.utcnow()
            )
            
            await self.persistence.save_task_result(task_result)
            
            # Update metrics
            self.metrics["tasks_processed"] += 1
            self.metrics["tasks_failed"] += 1
            
            # Emit TASK_FAILED event
            await self.event_bus.emit(GleitzeitEvent(
                event_type=EventType.TASK_FAILED,
                data={
                    "task_id": task_id,
                    "workflow_id": workflow_id,
                    "error": error,
                    "is_permanent": True,
                    "worker": f"{self.node_id}-{worker_id}",
                    "attempts": attempts,
                    "timestamp": datetime.utcnow().isoformat()
                }
            ))
            
            logger.error(
                f"Task {task_id} failed permanently after {attempts} attempts"
            )
    
    async def _update_task_status(self, task_id: str, status: TaskStatus):
        """Update task status in persistence."""
        task = await self.persistence.get_task(task_id)
        if task:
            task.status = status
            await self.persistence.save_task(task)
    
    async def _health_monitor(self):
        """Monitor health and publish metrics."""
        while self.running:
            try:
                # Publish health status
                if hasattr(self.persistence, 'redis'):
                    health_key = f"provider:health:{self.node_id}"
                    health_data = {
                        "node_id": self.node_id,
                        "protocol": self.protocol,
                        "num_workers": self.num_workers,
                        "active_workers": sum(
                            1 for status in self.metrics["worker_status"].values()
                            if status == "running"
                        ),
                        "metrics": {
                            "tasks_processed": self.metrics["tasks_processed"],
                            "tasks_succeeded": self.metrics["tasks_succeeded"],
                            "tasks_failed": self.metrics["tasks_failed"],
                            "avg_execution_time": (
                                self.metrics["total_execution_time"] / 
                                self.metrics["tasks_processed"]
                            ) if self.metrics["tasks_processed"] > 0 else 0
                        },
                        "timestamp": datetime.utcnow().isoformat()
                    }
                    
                    await self.persistence.redis.setex(
                        health_key,
                        30,  # Expire after 30 seconds
                        json.dumps(health_data)
                    )
                
                # Check worker health
                dead_workers = []
                for worker in self.workers:
                    if worker.done():
                        exception = worker.exception()
                        if exception:
                            logger.error(f"Worker died with exception: {exception}")
                        dead_workers.append(worker)
                
                # Restart dead workers
                for dead_worker in dead_workers:
                    self.workers.remove(dead_worker)
                    worker_id = len(self.workers)  # Simple ID assignment
                    new_worker = asyncio.create_task(
                        self._worker_loop(worker_id),
                        name=f"{self.node_id}-worker-{worker_id}"
                    )
                    self.workers.append(new_worker)
                    logger.info(f"Restarted worker {worker_id}")
                
            except Exception as e:
                logger.error(f"Health monitor error: {e}")
            
            await asyncio.sleep(10)  # Check every 10 seconds
    
    async def get_metrics(self) -> Dict[str, Any]:
        """
        Get current metrics for this adapter.
        
        Returns:
            Dictionary with adapter metrics
        """
        uptime = 0
        if self.metrics["started_at"]:
            uptime = (datetime.utcnow() - self.metrics["started_at"]).total_seconds()
        
        return {
            "node_id": self.node_id,
            "protocol": self.protocol,
            "num_workers": self.num_workers,
            "active_workers": sum(
                1 for status in self.metrics["worker_status"].values()
                if status == "running"
            ),
            "tasks_processed": self.metrics["tasks_processed"],
            "tasks_succeeded": self.metrics["tasks_succeeded"],
            "tasks_failed": self.metrics["tasks_failed"],
            "success_rate": (
                self.metrics["tasks_succeeded"] / self.metrics["tasks_processed"]
            ) if self.metrics["tasks_processed"] > 0 else 0,
            "avg_execution_time": (
                self.metrics["total_execution_time"] / self.metrics["tasks_processed"]
            ) if self.metrics["tasks_processed"] > 0 else 0,
            "uptime_seconds": uptime,
            "throughput": (
                self.metrics["tasks_processed"] / uptime
            ) if uptime > 0 else 0
        }


class ProviderCluster:
    """
    Manages a cluster of scalable provider adapters.
    
    This class coordinates multiple provider adapter instances
    for horizontal scaling of task execution.
    """
    
    def __init__(
        self,
        protocol: str,
        persistence: PersistenceBackend,
        event_bus: EventBus
    ):
        """
        Initialize provider cluster.
        
        Args:
            protocol: Protocol name this cluster handles
            persistence: Backend for state storage
            event_bus: Event bus for coordination
        """
        self.protocol = protocol
        self.persistence = persistence
        self.event_bus = event_bus
        self.adapters: List[ScalableProviderAdapter] = []
        
        logger.info(f"ProviderCluster initialized for protocol {protocol}")
    
    async def add_adapter(
        self,
        provider: ProtocolProvider,
        node_id: Optional[str] = None,
        num_workers: int = 5
    ) -> ScalableProviderAdapter:
        """
        Add a new adapter to the cluster.
        
        Args:
            provider: Protocol provider instance
            node_id: Unique node ID (auto-generated if None)
            num_workers: Number of workers for this adapter
            
        Returns:
            The created adapter
        """
        if node_id is None:
            node_id = f"{self.protocol}-adapter-{len(self.adapters)}"
        
        adapter = ScalableProviderAdapter(
            provider=provider,
            persistence=self.persistence,
            event_bus=self.event_bus,
            protocol=self.protocol,
            node_id=node_id,
            num_workers=num_workers
        )
        
        self.adapters.append(adapter)
        await adapter.start()
        
        logger.info(f"Added adapter {node_id} to cluster")
        return adapter
    
    async def scale_up(self, count: int = 1, num_workers: int = 5):
        """
        Scale up by adding more adapters.
        
        Args:
            count: Number of adapters to add
            num_workers: Workers per adapter
        """
        for i in range(count):
            # Create new provider instance
            # In real implementation, this would be protocol-specific
            from gleitzeit.providers.base import ProtocolProvider
            provider = ProtocolProvider()  # Placeholder
            
            await self.add_adapter(provider, num_workers=num_workers)
        
        logger.info(f"Scaled up cluster by {count} adapters")
    
    async def scale_down(self, count: int = 1):
        """
        Scale down by removing adapters.
        
        Args:
            count: Number of adapters to remove
        """
        removed = []
        for _ in range(min(count, len(self.adapters))):
            if self.adapters:
                adapter = self.adapters.pop()
                await adapter.stop()
                removed.append(adapter.node_id)
        
        logger.info(f"Scaled down cluster by removing: {removed}")
    
    async def get_cluster_metrics(self) -> Dict[str, Any]:
        """
        Get aggregated metrics for the entire cluster.
        
        Returns:
            Dictionary with cluster-wide metrics
        """
        cluster_metrics = {
            "protocol": self.protocol,
            "num_adapters": len(self.adapters),
            "total_workers": sum(a.num_workers for a in self.adapters),
            "total_tasks_processed": 0,
            "total_tasks_succeeded": 0,
            "total_tasks_failed": 0,
            "adapters": []
        }
        
        for adapter in self.adapters:
            metrics = await adapter.get_metrics()
            cluster_metrics["adapters"].append(metrics)
            cluster_metrics["total_tasks_processed"] += metrics["tasks_processed"]
            cluster_metrics["total_tasks_succeeded"] += metrics["tasks_succeeded"]
            cluster_metrics["total_tasks_failed"] += metrics["tasks_failed"]
        
        if cluster_metrics["total_tasks_processed"] > 0:
            cluster_metrics["overall_success_rate"] = (
                cluster_metrics["total_tasks_succeeded"] /
                cluster_metrics["total_tasks_processed"]
            )
        else:
            cluster_metrics["overall_success_rate"] = 0
        
        return cluster_metrics
    
    async def stop_all(self):
        """Stop all adapters in the cluster."""
        logger.info(f"Stopping all adapters in cluster for protocol {self.protocol}")
        
        await asyncio.gather(
            *[adapter.stop() for adapter in self.adapters],
            return_exceptions=True
        )
        
        self.adapters.clear()
        logger.info("All adapters stopped")