"""
Resource Allocator - Intelligent resource allocation and routing
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
from enum import Enum

from .models import (
    ResourceInstance,
    ResourceRequirements,
    ResourceType,
    ResourceStatus
)
from .pool import ResourcePool

logger = logging.getLogger(__name__)


class AllocationStrategy(str, Enum):
    """Resource allocation strategies"""
    LEAST_LOADED = "least_loaded"      # Choose least loaded instance
    ROUND_ROBIN = "round_robin"        # Cycle through instances
    BEST_FIT = "best_fit"              # Best match for requirements
    FASTEST = "fastest"                # Lowest response time
    RANDOM = "random"                  # Random selection
    STICKY = "sticky"                  # Try to reuse same instance


class AllocationRequest:
    """Request for resource allocation"""
    def __init__(
        self,
        task_id: str,
        requirements: ResourceRequirements,
        strategy: AllocationStrategy = AllocationStrategy.LEAST_LOADED,
        timeout: float = 30.0,
        priority: int = 0
    ) -> None:
        self.task_id = task_id
        self.requirements = requirements
        self.strategy = strategy
        self.timeout = timeout
        self.priority = priority
        self.requested_at = datetime.utcnow()
        self.allocated_instance: Optional[ResourceInstance] = None
        self.allocation_time: Optional[float] = None


class ResourceAllocator:
    """
    Intelligent resource allocation across multiple pools
    
    Features:
    - Multi-pool management
    - Intelligent routing based on requirements
    - Queuing for unavailable resources
    - Allocation tracking and metrics
    """
    
    def __init__(self, allocator_id: str = "default") -> None:
        self.allocator_id = allocator_id
        
        # Pool management
        self.pools: Dict[str, ResourcePool] = {}
        self.pool_lock = asyncio.Lock()
        
        # Allocation tracking
        self.allocations: Dict[str, Tuple[str, str]] = {}  # task_id -> (pool_id, instance_id)
        self.allocation_lock = asyncio.Lock()
        
        # Request queue for when no resources available
        self.pending_requests: List[AllocationRequest] = []
        self.request_event = asyncio.Event()
        
        # Statistics
        self.stats = {
            'total_allocations': 0,
            'successful_allocations': 0,
            'failed_allocations': 0,
            'queued_requests': 0,
            'avg_wait_time_ms': 0.0,
            'allocations_by_pool': defaultdict(int),
            'allocations_by_strategy': defaultdict(int)
        }
        
        # Background tasks
        self.queue_processor: Optional[asyncio.Task] = None
        self.running = False
        
        logger.info(f"Created ResourceAllocator {allocator_id}")
    
    async def add_pool(self, pool: ResourcePool) -> bool:
        """Add a resource pool"""
        async with self.pool_lock:
            if pool.pool_id in self.pools:
                logger.warning(f"Pool {pool.pool_id} already exists")
                return False
            
            self.pools[pool.pool_id] = pool
            logger.info(f"Added pool {pool.pool_id} to allocator")
            return True
    
    async def remove_pool(self, pool_id: str) -> bool:
        """Remove a resource pool"""
        async with self.pool_lock:
            if pool_id not in self.pools:
                return False
            
            pool = self.pools.pop(pool_id)
            
            # Release all allocations from this pool
            async with self.allocation_lock:
                tasks_to_release = [
                    task_id for task_id, (pid, _) in self.allocations.items()
                    if pid == pool_id
                ]
                
                for task_id in tasks_to_release:
                    await self.release(task_id)
            
            await pool.stop()
            logger.info(f"Removed pool {pool_id} from allocator")
            return True
    
    async def allocate(
        self,
        task_id: str,
        requirements: ResourceRequirements,
        strategy: AllocationStrategy = AllocationStrategy.LEAST_LOADED,
        timeout: float = 30.0,
        priority: int = 0
    ) -> Optional[ResourceInstance]:
        """
        Allocate a resource for a task
        
        Returns allocated instance or None if allocation fails
        """
        self.stats['total_allocations'] += 1
        self.stats['allocations_by_strategy'][strategy.value] += 1
        
        request = AllocationRequest(
            task_id=task_id,
            requirements=requirements,
            strategy=strategy,
            timeout=timeout,
            priority=priority
        )
        
        # Check if task already has allocation
        async with self.allocation_lock:
            if task_id in self.allocations:
                pool_id, instance_id = self.allocations[task_id]
                pool = self.pools.get(pool_id)
                if pool:
                    instance = await pool.get_instance(instance_id)
                    if instance:
                        logger.debug(f"Task {task_id} already allocated to {instance_id}")
                        return instance
        
        # Try immediate allocation
        instance = await self._try_allocate(request)
        
        if instance:
            self.stats['successful_allocations'] += 1
            request.allocated_instance = instance
            request.allocation_time = (datetime.utcnow() - request.requested_at).total_seconds()
            
            # Update average wait time
            current_avg = self.stats['avg_wait_time_ms']
            total_allocs = self.stats['successful_allocations']
            new_wait_ms = request.allocation_time * 1000
            self.stats['avg_wait_time_ms'] = (
                (current_avg * (total_allocs - 1) + new_wait_ms) / total_allocs
            )
            
            return instance
        
        # Queue request if immediate allocation failed
        if timeout > 0:
            logger.info(f"Queuing allocation request for task {task_id}")
            self.stats['queued_requests'] += 1
            
            # Insert in priority order
            inserted = False
            for i, req in enumerate(self.pending_requests):
                if priority > req.priority:
                    self.pending_requests.insert(i, request)
                    inserted = True
                    break
            
            if not inserted:
                self.pending_requests.append(request)
            
            self.request_event.set()
            
            # Wait for allocation with timeout
            start_time = asyncio.get_event_loop().time()
            
            while (asyncio.get_event_loop().time() - start_time) < timeout:
                if request.allocated_instance:
                    self.stats['successful_allocations'] += 1
                    return request.allocated_instance
                
                await asyncio.sleep(0.1)
            
            # Timeout - remove from queue
            if request in self.pending_requests:
                self.pending_requests.remove(request)
        
        self.stats['failed_allocations'] += 1
        logger.warning(f"Failed to allocate resource for task {task_id}")
        return None
    
    async def _try_allocate(self, request: AllocationRequest) -> Optional[ResourceInstance]:
        """Try to allocate from available pools"""
        # Get pools that match resource type
        matching_pools = [
            pool for pool in self.pools.values()
            if pool.resource_type == request.requirements.resource_type
        ]
        
        if not matching_pools:
            logger.warning(f"No pools available for type {request.requirements.resource_type}")
            return None
        
        # Try allocation based on strategy
        if request.strategy == AllocationStrategy.STICKY:
            # Try to use same pool/instance as before (would need history tracking)
            pass
        
        elif request.strategy == AllocationStrategy.FASTEST:
            # Sort pools by average response time
            matching_pools.sort(
                key=lambda p: self._get_pool_avg_response_time(p)
            )
        
        # Try each pool
        for pool in matching_pools:
            instance = await pool.allocate_to_task(
                request.task_id,
                request.requirements
            )
            
            if instance:
                # Record allocation
                async with self.allocation_lock:
                    self.allocations[request.task_id] = (pool.pool_id, instance.id)
                    self.stats['allocations_by_pool'][pool.pool_id] += 1
                
                logger.info(f"Allocated {instance.id} from pool {pool.pool_id} to task {request.task_id}")
                return instance
        
        return None
    
    def _get_pool_avg_response_time(self, pool: ResourcePool) -> float:
        """Get average response time for a pool"""
        total_time = 0.0
        total_instances = 0
        
        for instance in pool.instances.values():
            if instance.metrics.avg_response_time_ms > 0:
                total_time += instance.metrics.avg_response_time_ms
                total_instances += 1
        
        if total_instances == 0:
            return float('inf')
        
        return total_time / total_instances
    
    async def release(self, task_id: str) -> bool:
        """Release resources allocated to a task"""
        async with self.allocation_lock:
            if task_id not in self.allocations:
                return False
            
            pool_id, instance_id = self.allocations.pop(task_id)
            
            # Release from pool
            pool = self.pools.get(pool_id)
            if pool:
                await pool.release_from_task(task_id)
                logger.info(f"Released allocation for task {task_id}")
                
                # Trigger queue processing for pending requests
                self.request_event.set()
                return True
        
        return False
    
    async def get_allocation(self, task_id: str) -> Optional[ResourceInstance]:
        """Get the instance allocated to a task"""
        async with self.allocation_lock:
            if task_id not in self.allocations:
                return None
            
            pool_id, instance_id = self.allocations[task_id]
            pool = self.pools.get(pool_id)
            
            if pool:
                return await pool.get_instance(instance_id)
        
        return None
    
    async def list_allocations(self) -> Dict[str, Dict[str, Any]]:
        """List all current allocations"""
        allocations = {}
        
        async with self.allocation_lock:
            for task_id, (pool_id, instance_id) in self.allocations.items():
                pool = self.pools.get(pool_id)
                if pool:
                    instance = await pool.get_instance(instance_id)
                    if instance:
                        allocations[task_id] = {
                            'pool_id': pool_id,
                            'instance_id': instance_id,
                            'resource_type': instance.resource_type.value,
                            'status': instance.status.value,
                            'metrics': {
                                'cpu': instance.metrics.cpu_usage_percent,
                                'memory': instance.metrics.memory_usage_mb,
                                'active_requests': instance.metrics.active_requests
                            }
                        }
        
        return allocations
    
    async def get_metrics(self) -> Dict[str, Any]:
        """Get allocator metrics"""
        # Aggregate pool metrics
        pool_metrics = {}
        total_instances = 0
        available_instances = 0
        
        for pool_id, pool in self.pools.items():
            metrics = await pool.get_metrics()
            pool_metrics[pool_id] = metrics
            total_instances += metrics['instances']['total']
            available_instances += metrics['instances']['available']
        
        return {
            'allocator_id': self.allocator_id,
            'pools': len(self.pools),
            'total_instances': total_instances,
            'available_instances': available_instances,
            'active_allocations': len(self.allocations),
            'pending_requests': len(self.pending_requests),
            'stats': dict(self.stats),
            'pool_metrics': pool_metrics
        }
    
    async def optimize(self) -> None:
        """Optimize resource allocation"""
        # Rebalance allocations across pools
        # This could include:
        # - Moving tasks from overloaded to underloaded pools
        # - Consolidating tasks to fewer instances
        # - Pre-allocating based on patterns
        
        for pool in self.pools.values():
            await pool.optimize()
    
    async def _process_queue(self) -> None:
        """Process pending allocation requests"""
        while self.running:
            try:
                # Wait for signal or timeout
                await asyncio.wait_for(self.request_event.wait(), timeout=1.0)
                self.request_event.clear()
                
                # Process pending requests
                processed = []
                
                for request in self.pending_requests[:]:  # Copy to avoid modification issues
                    # Check timeout
                    elapsed = (datetime.utcnow() - request.requested_at).total_seconds()
                    if elapsed > request.timeout:
                        processed.append(request)
                        continue
                    
                    # Try allocation
                    instance = await self._try_allocate(request)
                    if instance:
                        request.allocated_instance = instance
                        request.allocation_time = elapsed
                        processed.append(request)
                        logger.info(f"Allocated queued request for task {request.task_id}")
                
                # Remove processed requests
                for request in processed:
                    if request in self.pending_requests:
                        self.pending_requests.remove(request)
                
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                logger.error(f"Queue processing error: {e}")
    
    async def start(self) -> None:
        """Start the allocator"""
        if self.running:
            return
        
        self.running = True
        
        # Start all pools
        for pool in self.pools.values():
            await pool.start()
        
        # Start queue processor
        self.queue_processor = asyncio.create_task(self._process_queue())
        
        logger.info(f"Started ResourceAllocator {self.allocator_id}")
    
    async def stop(self) -> None:
        """Stop the allocator"""
        if not self.running:
            return
        
        self.running = False
        
        # Cancel queue processor
        if self.queue_processor:
            self.queue_processor.cancel()
            try:
                await self.queue_processor
            except asyncio.CancelledError:
                pass
        
        # Stop all pools
        for pool in self.pools.values():
            await pool.stop()
        
        # Clear pending requests
        self.pending_requests.clear()
        
        logger.info(f"Stopped ResourceAllocator {self.allocator_id}")