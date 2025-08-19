"""
Resource Manager - High-level interface for resource management
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Type, Set
from datetime import datetime

from .models import (
    ResourceInstance,
    ResourceRequirements,
    ResourceType,
    ResourceStatus,
    ResourceMetrics
)
from .pool import ResourcePool
from .allocator import ResourceAllocator, AllocationStrategy

logger = logging.getLogger(__name__)


class ResourceManager:
    """
    High-level resource management interface
    
    Provides simplified API for:
    - Creating and managing resource pools
    - Allocating resources to tasks
    - Monitoring resource health and metrics
    - Auto-scaling based on demand
    """
    
    def __init__(self, manager_id: str = "default") -> None:
        self.manager_id = manager_id
        self.allocator = ResourceAllocator(f"{manager_id}-allocator")
        
        # Pool factory methods
        self.pool_factories: Dict[ResourceType, Any] = {}
        
        # Auto-scaling configuration
        self.auto_scaling_enabled = False
        self.scaling_task: Optional[asyncio.Task] = None
        
        # Monitoring
        self.monitor_task: Optional[asyncio.Task] = None
        self.monitor_interval = 60  # seconds
        
        self.running = False
        
        logger.info(f"Created ResourceManager {manager_id}")
    
    async def create_pool(
        self,
        pool_id: str,
        resource_type: ResourceType,
        min_instances: int = 0,
        max_instances: int = 10,
        initial_instances: Optional[List[ResourceInstance]] = None
    ) -> ResourcePool:
        """Create a new resource pool"""
        pool = ResourcePool(
            pool_id=pool_id,
            resource_type=resource_type,
            min_instances=min_instances,
            max_instances=max_instances
        )
        
        # Add initial instances
        if initial_instances:
            for instance in initial_instances:
                await pool.add_instance(instance)
        
        # Register with allocator
        await self.allocator.add_pool(pool)
        
        logger.info(f"Created pool {pool_id} with {len(initial_instances or [])} initial instances")
        return pool
    
    async def create_ollama_pool(
        self,
        pool_id: str = "ollama-pool",
        endpoints: Optional[List[str]] = None,
        models: Optional[List[str]] = None,
        min_instances: int = 1,
        max_instances: int = 5
    ) -> ResourcePool:
        """Create a pool for Ollama instances"""
        pool = await self.create_pool(
            pool_id=pool_id,
            resource_type=ResourceType.OLLAMA,
            min_instances=min_instances,
            max_instances=max_instances
        )
        
        # Create instances for provided endpoints
        if endpoints:
            for i, endpoint in enumerate(endpoints):
                instance = ResourceInstance(
                    id=f"ollama-{i}",
                    name=f"Ollama Instance {i}",
                    resource_type=ResourceType.OLLAMA,
                    endpoint=endpoint,
                    status=ResourceStatus.AVAILABLE,
                    capabilities=set(models) if models else set(),
                    max_concurrent_tasks=3,
                    available_memory_mb=8192,
                    available_cpu_cores=4
                )
                await pool.add_instance(instance)
        
        return pool
    
    async def create_docker_pool(
        self,
        pool_id: str = "docker-pool",
        min_instances: int = 0,
        max_instances: int = 10
    ) -> ResourcePool:
        """Create a pool for Docker containers"""
        return await self.create_pool(
            pool_id=pool_id,
            resource_type=ResourceType.DOCKER,
            min_instances=min_instances,
            max_instances=max_instances
        )
    
    async def allocate_resource(
        self,
        task_id: str,
        resource_type: ResourceType,
        capabilities: Optional[Set[str]] = None,
        min_memory_mb: Optional[int] = None,
        min_cpu_cores: Optional[int] = None,
        strategy: str = "least_loaded",
        timeout: float = 30.0
    ) -> Optional[ResourceInstance]:
        """
        Allocate a resource for a task
        
        Simplified interface that creates requirements and delegates to allocator
        """
        requirements = ResourceRequirements(
            resource_type=resource_type,
            capabilities=capabilities or set(),
            min_memory_mb=min_memory_mb,
            min_cpu_cores=min_cpu_cores
        )
        
        # Convert string strategy to enum
        try:
            alloc_strategy = AllocationStrategy(strategy)
        except ValueError:
            alloc_strategy = AllocationStrategy.LEAST_LOADED
        
        return await self.allocator.allocate(
            task_id=task_id,
            requirements=requirements,
            strategy=alloc_strategy,
            timeout=timeout
        )
    
    async def release_resource(self, task_id: str) -> bool:
        """Release resources allocated to a task"""
        return await self.allocator.release(task_id)
    
    async def get_allocation(self, task_id: str) -> Optional[ResourceInstance]:
        """Get the resource allocated to a task"""
        return await self.allocator.get_allocation(task_id)
    
    async def register_instance(
        self,
        pool_id: str,
        instance: ResourceInstance
    ) -> bool:
        """Register a resource instance with a pool"""
        for pool in self.allocator.pools.values():
            if pool.pool_id == pool_id:
                return await pool.add_instance(instance)
        
        logger.error(f"Pool {pool_id} not found")
        return False
    
    async def unregister_instance(
        self,
        pool_id: str,
        instance_id: str
    ) -> bool:
        """Unregister a resource instance from a pool"""
        for pool in self.allocator.pools.values():
            if pool.pool_id == pool_id:
                return await pool.remove_instance(instance_id)
        
        return False
    
    async def list_pools(self) -> List[Dict[str, Any]]:
        """List all resource pools"""
        pools = []
        
        for pool in self.allocator.pools.values():
            metrics = await pool.get_metrics()
            pools.append({
                'pool_id': pool.pool_id,
                'resource_type': pool.resource_type.value,
                'instances': metrics['instances'],
                'requests': metrics['requests']
            })
        
        return pools
    
    async def list_instances(
        self,
        pool_id: Optional[str] = None,
        resource_type: Optional[ResourceType] = None,
        status: Optional[ResourceStatus] = None
    ) -> List[ResourceInstance]:
        """List resource instances"""
        instances = []
        
        for pool in self.allocator.pools.values():
            # Filter by pool_id
            if pool_id and pool.pool_id != pool_id:
                continue
            
            # Filter by resource_type
            if resource_type and pool.resource_type != resource_type:
                continue
            
            pool_instances = await pool.list_instances(status=status)
            instances.extend(pool_instances)
        
        return instances
    
    async def get_metrics(self) -> Dict[str, Any]:
        """Get resource management metrics"""
        allocator_metrics = await self.allocator.get_metrics()
        
        # Add manager-level metrics
        metrics = {
            'manager_id': self.manager_id,
            'running': self.running,
            'auto_scaling': self.auto_scaling_enabled,
            'allocator': allocator_metrics,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        return metrics
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on all resources"""
        health_results = {
            'manager_id': self.manager_id,
            'healthy': True,
            'pools': {}
        }
        
        for pool in self.allocator.pools.values():
            pool_health = await pool.health_check()
            health_results['pools'][pool.pool_id] = pool_health
            
            # Mark as unhealthy if any pool is unhealthy
            if pool_health['unhealthy'] > 0:
                health_results['healthy'] = False
        
        return health_results
    
    async def enable_auto_scaling(
        self,
        check_interval: int = 30,
        scale_up_threshold: float = 0.8,  # 80% utilization
        scale_down_threshold: float = 0.2  # 20% utilization
    ) -> None:
        """Enable auto-scaling for resource pools"""
        self.auto_scaling_enabled = True
        
        async def auto_scale_loop():
            while self.auto_scaling_enabled and self.running:
                try:
                    for pool in self.allocator.pools.values():
                        metrics = await pool.get_metrics()
                        
                        total = metrics['instances']['total']
                        available = metrics['instances']['available']
                        
                        if total == 0:
                            continue
                        
                        utilization = 1.0 - (available / total)
                        
                        # Scale up if utilization too high
                        if utilization > scale_up_threshold:
                            new_target = min(total + 1, pool.max_instances)
                            if new_target > total:
                                logger.info(f"Scaling up pool {pool.pool_id} from {total} to {new_target}")
                                await pool.scale(new_target)
                        
                        # Scale down if utilization too low
                        elif utilization < scale_down_threshold:
                            new_target = max(total - 1, pool.min_instances)
                            if new_target < total:
                                logger.info(f"Scaling down pool {pool.pool_id} from {total} to {new_target}")
                                await pool.scale(new_target)
                    
                    await asyncio.sleep(check_interval)
                    
                except Exception as e:
                    logger.error(f"Auto-scaling error: {e}")
                    await asyncio.sleep(check_interval)
        
        if not self.scaling_task or self.scaling_task.done():
            self.scaling_task = asyncio.create_task(auto_scale_loop())
            logger.info("Enabled auto-scaling")
    
    async def disable_auto_scaling(self) -> None:
        """Disable auto-scaling"""
        self.auto_scaling_enabled = False
        
        if self.scaling_task:
            self.scaling_task.cancel()
            try:
                await self.scaling_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Disabled auto-scaling")
    
    async def _monitor_loop(self) -> None:
        """Background monitoring loop"""
        while self.running:
            try:
                # Perform health checks
                health = await self.health_check()
                
                if not health['healthy']:
                    logger.warning(f"Resource health check failed: {health}")
                
                # Log metrics periodically
                metrics = await self.get_metrics()
                total_instances = sum(
                    p['instances']['total'] 
                    for p in metrics['allocator']['pool_metrics'].values()
                )
                active_allocations = metrics['allocator']['active_allocations']
                
                logger.info(
                    f"ResourceManager: {total_instances} instances, "
                    f"{active_allocations} active allocations"
                )
                
                await asyncio.sleep(self.monitor_interval)
                
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
                await asyncio.sleep(self.monitor_interval)
    
    async def start(self) -> None:
        """Start the resource manager"""
        if self.running:
            return
        
        self.running = True
        
        # Start allocator
        await self.allocator.start()
        
        # Start monitoring
        self.monitor_task = asyncio.create_task(self._monitor_loop())
        
        logger.info(f"Started ResourceManager {self.manager_id}")
    
    async def stop(self) -> None:
        """Stop the resource manager"""
        if not self.running:
            return
        
        self.running = False
        
        # Disable auto-scaling
        await self.disable_auto_scaling()
        
        # Stop monitoring
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        
        # Stop allocator
        await self.allocator.stop()
        
        logger.info(f"Stopped ResourceManager {self.manager_id}")