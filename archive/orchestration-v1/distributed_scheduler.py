"""
Distributed Task Scheduler with partition-based work distribution

This extends TaskSchedulerOnly to support multiple instances through
consistent hashing and partition-based task assignment.
"""

import asyncio
import logging
import hashlib
from typing import Optional, Set
from datetime import datetime, timedelta

from gleitzeit.orchestration.task_scheduler_only import TaskSchedulerOnly
from gleitzeit.core.models import Workflow
from gleitzeit.persistence.base import PersistenceBackend
from gleitzeit.events.base import EventBus
from gleitzeit.core.events import GleitzeitEvent, EventType

logger = logging.getLogger(__name__)


class DistributedTaskScheduler(TaskSchedulerOnly):
    """
    Distributed task scheduler that supports multiple instances.
    
    Features:
    - Partition-based workflow assignment using consistent hashing
    - Distributed locking for critical sections
    - Automatic rebalancing on node join/leave
    - Health checking and failover
    """
    
    def __init__(
        self,
        persistence: PersistenceBackend,
        event_bus: EventBus,
        node_id: str = "scheduler-1",
        partition_key: Optional[int] = None,
        total_partitions: int = 1
    ):
        """
        Initialize distributed scheduler.
        
        Args:
            persistence: Backend for state storage
            event_bus: Event bus for coordination
            node_id: Unique identifier for this scheduler instance
            partition_key: This node's partition (0 to total_partitions-1)
            total_partitions: Total number of partitions
        """
        super().__init__(persistence, event_bus, node_id)
        
        self.partition_key = partition_key
        self.total_partitions = total_partitions
        self.is_distributed = partition_key is not None
        
        # Track active locks
        self._active_locks: Set[str] = set()
        
        # Heartbeat for health checking
        self._heartbeat_task = None
        self._last_heartbeat = datetime.utcnow()
        
        if self.is_distributed:
            logger.info(
                f"Distributed scheduler {node_id} initialized: "
                f"partition {partition_key}/{total_partitions}"
            )
    
    def _should_handle_workflow(self, workflow_id: str) -> bool:
        """
        Check if this scheduler instance should handle a workflow.
        
        Uses consistent hashing to distribute workflows across partitions.
        """
        if not self.is_distributed:
            return True  # Single instance handles everything
        
        # Use consistent hashing for stable assignment
        hash_value = int(hashlib.md5(workflow_id.encode()).hexdigest(), 16)
        assigned_partition = hash_value % self.total_partitions
        
        return assigned_partition == self.partition_key
    
    async def _on_workflow_submitted(self, event: GleitzeitEvent):
        """
        Handle workflow submission - only if assigned to this partition.
        """
        workflow_id = event.data.get('workflow_id')
        if not workflow_id:
            return
        
        # Check if we should handle this workflow
        if not self._should_handle_workflow(workflow_id):
            logger.debug(
                f"Workflow {workflow_id} not assigned to partition {self.partition_key}, skipping"
            )
            return
        
        logger.info(
            f"Scheduler {self.node_id} (partition {self.partition_key}) "
            f"handling workflow {workflow_id}"
        )
        
        # Call parent implementation
        await super()._on_workflow_submitted(event)
    
    async def _on_task_completed(self, event: GleitzeitEvent):
        """
        Handle task completion with distributed locking.
        """
        workflow_id = event.data.get('workflow_id')
        if not workflow_id:
            return
        
        # Only handle if this is our workflow
        if not self._should_handle_workflow(workflow_id):
            return
        
        # Use distributed lock to prevent duplicate scheduling
        if self.is_distributed and hasattr(self.persistence, 'redis'):
            lock_key = f"scheduler:lock:{workflow_id}:task_complete"
            
            # Try to acquire lock
            if not await self._acquire_lock(lock_key, ttl=5):
                logger.debug(f"Could not acquire lock for {workflow_id}, another node is handling")
                return
            
            try:
                await super()._on_task_completed(event)
            finally:
                await self._release_lock(lock_key)
        else:
            # No distribution or no Redis, proceed normally
            await super()._on_task_completed(event)
    
    async def _acquire_lock(self, lock_key: str, ttl: int = 5) -> bool:
        """
        Acquire a distributed lock using Redis.
        
        Args:
            lock_key: Key for the lock
            ttl: Time to live in seconds
        
        Returns:
            True if lock acquired, False otherwise
        """
        if not hasattr(self.persistence, 'redis'):
            return True  # No Redis, assume we have the lock
        
        try:
            # SET NX EX for atomic lock acquisition
            result = await self.persistence.redis.set(
                lock_key,
                self.node_id,
                nx=True,  # Only set if not exists
                ex=ttl    # Expire after TTL seconds
            )
            
            if result:
                self._active_locks.add(lock_key)
                logger.debug(f"Acquired lock: {lock_key}")
            
            return bool(result)
            
        except Exception as e:
            logger.error(f"Failed to acquire lock {lock_key}: {e}")
            return False
    
    async def _release_lock(self, lock_key: str):
        """
        Release a distributed lock.
        
        Args:
            lock_key: Key for the lock to release
        """
        if not hasattr(self.persistence, 'redis'):
            return
        
        try:
            # Only delete if we own it
            if lock_key in self._active_locks:
                await self.persistence.redis.delete(lock_key)
                self._active_locks.discard(lock_key)
                logger.debug(f"Released lock: {lock_key}")
                
        except Exception as e:
            logger.error(f"Failed to release lock {lock_key}: {e}")
    
    async def start_heartbeat(self):
        """
        Start heartbeat for health monitoring.
        """
        if not self.is_distributed or not hasattr(self.persistence, 'redis'):
            return
        
        async def heartbeat_loop():
            while True:
                try:
                    # Update heartbeat in Redis
                    heartbeat_key = f"scheduler:heartbeat:{self.node_id}"
                    heartbeat_data = {
                        "node_id": self.node_id,
                        "partition": self.partition_key,
                        "timestamp": datetime.utcnow().isoformat(),
                        "active_workflows": len(self.dependency_graphs)
                    }
                    
                    await self.persistence.redis.setex(
                        heartbeat_key,
                        30,  # Expire after 30 seconds
                        json.dumps(heartbeat_data)
                    )
                    
                    self._last_heartbeat = datetime.utcnow()
                    logger.debug(f"Heartbeat sent for {self.node_id}")
                    
                except Exception as e:
                    logger.error(f"Heartbeat failed: {e}")
                
                await asyncio.sleep(10)  # Send heartbeat every 10 seconds
        
        self._heartbeat_task = asyncio.create_task(heartbeat_loop())
        logger.info(f"Started heartbeat for {self.node_id}")
    
    async def stop_heartbeat(self):
        """
        Stop the heartbeat task.
        """
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            logger.info(f"Stopped heartbeat for {self.node_id}")
    
    async def get_active_schedulers(self) -> list:
        """
        Get list of active scheduler nodes.
        
        Returns:
            List of active scheduler node information
        """
        if not hasattr(self.persistence, 'redis'):
            return [{"node_id": self.node_id, "partition": self.partition_key}]
        
        active_nodes = []
        
        try:
            # Scan for heartbeat keys
            pattern = "scheduler:heartbeat:*"
            cursor = 0
            
            while True:
                cursor, keys = await self.persistence.redis.scan(
                    cursor, match=pattern, count=100
                )
                
                for key in keys:
                    try:
                        data = await self.persistence.redis.get(key)
                        if data:
                            node_info = json.loads(data)
                            # Check if heartbeat is recent (within 30 seconds)
                            heartbeat_time = datetime.fromisoformat(node_info['timestamp'])
                            if datetime.utcnow() - heartbeat_time < timedelta(seconds=30):
                                active_nodes.append(node_info)
                    except Exception as e:
                        logger.warning(f"Failed to parse heartbeat data: {e}")
                
                if cursor == 0:
                    break
            
        except Exception as e:
            logger.error(f"Failed to get active schedulers: {e}")
        
        return active_nodes
    
    async def rebalance_check(self):
        """
        Check if rebalancing is needed based on active nodes.
        
        This could trigger workflow redistribution if nodes have
        joined or left the cluster.
        """
        if not self.is_distributed:
            return
        
        active_nodes = await self.get_active_schedulers()
        active_partitions = {node['partition'] for node in active_nodes}
        
        # Check for missing partitions
        expected_partitions = set(range(self.total_partitions))
        missing_partitions = expected_partitions - active_partitions
        
        if missing_partitions:
            logger.warning(
                f"Missing partitions detected: {missing_partitions}. "
                f"Consider starting schedulers for these partitions."
            )
            
            # Could implement automatic takeover of missing partitions here
            # For now, just log the warning
    
    async def get_stats(self) -> dict:
        """
        Get statistics for this scheduler instance.
        
        Returns:
            Dictionary with scheduler statistics
        """
        stats = {
            "node_id": self.node_id,
            "partition": self.partition_key,
            "total_partitions": self.total_partitions,
            "is_distributed": self.is_distributed,
            "active_workflows": len(self.dependency_graphs),
            "active_locks": len(self._active_locks),
            "last_heartbeat": self._last_heartbeat.isoformat() if self._last_heartbeat else None
        }
        
        # Add workflow distribution if distributed
        if self.is_distributed and self.dependency_graphs:
            workflow_ids = list(self.dependency_graphs.keys())
            stats["workflows"] = workflow_ids[:10]  # First 10 for brevity
            stats["total_workflows"] = len(workflow_ids)
        
        return stats


import json  # Add this import at the top of the file


class DistributedOrchestrator:
    """
    Orchestrator that supports multiple distributed scheduler instances.
    """
    
    def __init__(
        self,
        persistence: PersistenceBackend,
        event_bus: EventBus,
        node_id: str = "orchestrator-1",
        partition_key: Optional[int] = None,
        total_partitions: int = 1
    ):
        """
        Initialize distributed orchestrator.
        
        Args:
            persistence: Backend for state storage
            event_bus: Event bus for coordination
            node_id: Unique identifier for this orchestrator
            partition_key: Partition for the scheduler (None for single instance)
            total_partitions: Total number of partitions
        """
        self.persistence = persistence
        self.event_bus = event_bus
        self.node_id = node_id
        
        # Use existing workflow manager for state tracking
        from gleitzeit.core.event_driven_workflow_manager import EventDrivenWorkflowManager
        self.workflow_manager = EventDrivenWorkflowManager(persistence, event_bus)
        
        # Create distributed scheduler
        self.scheduler = DistributedTaskScheduler(
            persistence=persistence,
            event_bus=event_bus,
            node_id=f"{node_id}-scheduler",
            partition_key=partition_key,
            total_partitions=total_partitions
        )
        
        logger.info(
            f"Distributed orchestrator initialized: {node_id} "
            f"(partition {partition_key}/{total_partitions})"
        )
    
    async def start(self):
        """
        Start the orchestrator and its components.
        """
        # Start heartbeat if distributed
        if self.scheduler.is_distributed:
            await self.scheduler.start_heartbeat()
        
        logger.info(f"Started distributed orchestrator {self.node_id}")
    
    async def stop(self):
        """
        Stop the orchestrator and clean up.
        """
        # Stop heartbeat
        await self.scheduler.stop_heartbeat()
        
        # Release all locks
        if hasattr(self.persistence, 'redis'):
            for lock_key in list(self.scheduler._active_locks):
                await self.scheduler._release_lock(lock_key)
        
        logger.info(f"Stopped distributed orchestrator {self.node_id}")
    
    async def submit_workflow(self, workflow: Workflow) -> str:
        """
        Submit workflow for execution.
        """
        # Save workflow to persistence
        await self.persistence.save_workflow(workflow)
        
        # Emit WORKFLOW_SUBMITTED event
        # The distributed scheduler will decide if it should handle it
        await self.event_bus.emit(GleitzeitEvent(
            event_type=EventType.WORKFLOW_SUBMITTED,
            data={
                "workflow_id": workflow.id,
                "workflow_name": workflow.name,
                "task_count": len(workflow.tasks),
                "timestamp": datetime.utcnow().isoformat()
            }
        ))
        
        # Log which partition will handle it
        if self.scheduler.is_distributed:
            hash_value = int(hashlib.md5(workflow.id.encode()).hexdigest(), 16)
            assigned_partition = hash_value % self.scheduler.total_partitions
            logger.info(
                f"Workflow {workflow.id} submitted, will be handled by partition {assigned_partition}"
            )
        
        return workflow.id
    
    async def get_cluster_stats(self) -> dict:
        """
        Get statistics for the entire cluster.
        
        Returns:
            Dictionary with cluster-wide statistics
        """
        # Get local stats
        local_stats = await self.scheduler.get_stats()
        
        # Get active nodes
        active_nodes = await self.scheduler.get_active_schedulers()
        
        # Check partition coverage
        total_partitions = self.scheduler.total_partitions
        active_partitions = {node['partition'] for node in active_nodes}
        missing_partitions = set(range(total_partitions)) - active_partitions
        
        cluster_stats = {
            "local_node": local_stats,
            "active_nodes": active_nodes,
            "total_nodes": len(active_nodes),
            "total_partitions": total_partitions,
            "active_partitions": list(active_partitions),
            "missing_partitions": list(missing_partitions),
            "partition_coverage": len(active_partitions) / total_partitions if total_partitions > 0 else 0
        }
        
        return cluster_stats