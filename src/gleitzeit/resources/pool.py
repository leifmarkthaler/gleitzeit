"""
Resource Pool - Manages collections of resource instances
"""

import asyncio
import logging
from typing import Dict, List, Optional, Set, Any
from datetime import datetime, timedelta
from collections import defaultdict

from .models import (
    ResourceInstance, 
    ResourceStatus, 
    ResourceType,
    ResourceRequirements,
    ResourceMetrics
)

logger = logging.getLogger(__name__)


class ResourcePool:
    """
    Manages a pool of resource instances of the same type
    
    Provides:
    - Instance lifecycle management
    - Health monitoring
    - Load balancing
    - Auto-scaling capabilities
    """
    
    def __init__(
        self,
        pool_id: str,
        resource_type: ResourceType,
        min_instances: int = 0,
        max_instances: int = 10,
        health_check_interval: int = 30
    ) -> None:
        self.pool_id = pool_id
        self.resource_type = resource_type
        self.min_instances = min_instances
        self.max_instances = max_instances
        self.health_check_interval = health_check_interval
        
        # Instance management
        self.instances: Dict[str, ResourceInstance] = {}
        self.instance_lock = asyncio.Lock()
        
        # Health monitoring
        self.health_task: Optional[asyncio.Task] = None
        self.running = False
        
        # Statistics
        self.stats = {
            'instances_created': 0,
            'instances_removed': 0,
            'health_checks': 0,
            'allocation_attempts': 0,
            'allocation_failures': 0
        }
        
        logger.info(f"Created ResourcePool {pool_id} for {resource_type.value}")
    
    async def add_instance(self, instance: ResourceInstance) -> bool:
        """Add an instance to the pool"""
        if instance.resource_type != self.resource_type:
            logger.error(f"Instance type {instance.resource_type} doesn't match pool type {self.resource_type}")
            return False
        
        async with self.instance_lock:
            if instance.id in self.instances:
                logger.warning(f"Instance {instance.id} already in pool")
                return False
            
            if len(self.instances) >= self.max_instances:
                logger.warning(f"Pool {self.pool_id} at max capacity ({self.max_instances})")
                return False
            
            self.instances[instance.id] = instance
            self.stats['instances_created'] += 1
            logger.info(f"Added instance {instance.id} to pool {self.pool_id}")
            return True
    
    async def remove_instance(self, instance_id: str) -> bool:
        """Remove an instance from the pool"""
        async with self.instance_lock:
            if instance_id not in self.instances:
                return False
            
            instance = self.instances.pop(instance_id)
            
            # Release any tasks using this instance
            for task_id in list(instance.current_tasks):
                instance.release(task_id)
            
            self.stats['instances_removed'] += 1
            logger.info(f"Removed instance {instance_id} from pool {self.pool_id}")
            return True
    
    async def get_instance(self, instance_id: str) -> Optional[ResourceInstance]:
        """Get a specific instance by ID"""
        return self.instances.get(instance_id)
    
    async def get_available_instance(
        self,
        requirements: Optional[ResourceRequirements] = None,
        strategy: str = "least_loaded"
    ) -> Optional[ResourceInstance]:
        """
        Get an available instance that meets requirements
        
        Strategies:
        - least_loaded: Choose instance with fewest active tasks
        - round_robin: Cycle through available instances
        - random: Random selection
        - best_fit: Choose instance that best matches requirements
        """
        self.stats['allocation_attempts'] += 1
        
        available_instances = []
        
        async with self.instance_lock:
            for instance in self.instances.values():
                # Check if instance is available
                if not instance.is_available():
                    continue
                
                # Check if it meets requirements
                if requirements and not requirements.matches(instance):
                    continue
                
                available_instances.append(instance)
            
            if not available_instances:
                self.stats['allocation_failures'] += 1
                return None
            
            # Apply selection strategy
            if strategy == "least_loaded":
                # Sort by number of current tasks
                available_instances.sort(key=lambda i: len(i.current_tasks))
                selected = available_instances[0]
            
            elif strategy == "best_fit":
                # Score instances based on how well they match requirements
                if requirements:
                    def score_instance(inst: ResourceInstance) -> float:
                        score = 1.0
                        
                        # Prefer instances with exact capability match
                        if requirements.capabilities:
                            overlap = requirements.capabilities.intersection(inst.capabilities)
                            score *= len(overlap) / len(requirements.capabilities)
                        
                        # Prefer instances with lower current load
                        score *= (1.0 - len(inst.current_tasks) / inst.max_concurrent_tasks)
                        
                        # Consider memory if specified
                        if requirements.min_memory_mb and inst.available_memory_mb:
                            score *= min(1.0, inst.available_memory_mb / requirements.min_memory_mb)
                        
                        return score
                    
                    available_instances.sort(key=score_instance, reverse=True)
                
                selected = available_instances[0]
            
            elif strategy == "round_robin":
                # Simple round-robin (would need state tracking for true RR)
                import random
                selected = random.choice(available_instances)
            
            else:  # random or fallback
                import random
                selected = random.choice(available_instances)
            
            return selected
    
    async def allocate_to_task(
        self,
        task_id: str,
        requirements: Optional[ResourceRequirements] = None
    ) -> Optional[ResourceInstance]:
        """Allocate an instance to a specific task"""
        instance = await self.get_available_instance(requirements)
        
        if instance and instance.allocate(task_id):
            logger.debug(f"Allocated instance {instance.id} to task {task_id}")
            return instance
        
        return None
    
    async def release_from_task(self, task_id: str) -> None:
        """Release any instance allocated to a task"""
        async with self.instance_lock:
            for instance in self.instances.values():
                if task_id in instance.current_tasks:
                    instance.release(task_id)
                    logger.debug(f"Released instance {instance.id} from task {task_id}")
    
    async def list_instances(
        self,
        status: Optional[ResourceStatus] = None
    ) -> List[ResourceInstance]:
        """List all instances, optionally filtered by status"""
        instances = list(self.instances.values())
        
        if status:
            instances = [i for i in instances if i.status == status]
        
        return instances
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on all instances"""
        self.stats['health_checks'] += 1
        
        healthy = 0
        unhealthy = 0
        results = {}
        
        async with self.instance_lock:
            for instance in self.instances.values():
                # Simple health check based on status and failures
                is_healthy = (
                    instance.status in [ResourceStatus.AVAILABLE, ResourceStatus.BUSY] and
                    instance.health_check_failures < 3
                )
                
                if is_healthy:
                    healthy += 1
                    instance.last_health_check = datetime.utcnow()
                    instance.health_check_failures = 0
                else:
                    unhealthy += 1
                    instance.health_check_failures += 1
                    
                    # Mark as failed after too many failures
                    if instance.health_check_failures >= 3:
                        instance.status = ResourceStatus.FAILED
                
                results[instance.id] = {
                    'healthy': is_healthy,
                    'status': instance.status.value,
                    'failures': instance.health_check_failures
                }
        
        return {
            'pool_id': self.pool_id,
            'total': len(self.instances),
            'healthy': healthy,
            'unhealthy': unhealthy,
            'instances': results
        }
    
    async def get_metrics(self) -> Dict[str, Any]:
        """Get pool metrics"""
        total_instances = len(self.instances)
        available = sum(1 for i in self.instances.values() if i.is_available())
        busy = sum(1 for i in self.instances.values() if i.status == ResourceStatus.BUSY)
        failed = sum(1 for i in self.instances.values() if i.status == ResourceStatus.FAILED)
        
        # Aggregate metrics from instances
        total_requests = sum(i.metrics.total_requests for i in self.instances.values())
        active_requests = sum(i.metrics.active_requests for i in self.instances.values())
        failed_requests = sum(i.metrics.failed_requests for i in self.instances.values())
        
        avg_cpu = 0.0
        avg_memory = 0.0
        if total_instances > 0:
            avg_cpu = sum(i.metrics.cpu_usage_percent for i in self.instances.values()) / total_instances
            avg_memory = sum(i.metrics.memory_usage_mb for i in self.instances.values()) / total_instances
        
        return {
            'pool_id': self.pool_id,
            'resource_type': self.resource_type.value,
            'instances': {
                'total': total_instances,
                'available': available,
                'busy': busy,
                'failed': failed,
                'min': self.min_instances,
                'max': self.max_instances
            },
            'requests': {
                'total': total_requests,
                'active': active_requests,
                'failed': failed_requests,
                'error_rate': (failed_requests / total_requests * 100) if total_requests > 0 else 0
            },
            'resources': {
                'avg_cpu_percent': avg_cpu,
                'avg_memory_mb': avg_memory
            },
            'stats': self.stats
        }
    
    async def scale(self, target_instances: int) -> bool:
        """Scale pool to target number of instances"""
        if target_instances < self.min_instances or target_instances > self.max_instances:
            logger.error(f"Target {target_instances} outside bounds [{self.min_instances}, {self.max_instances}]")
            return False
        
        current = len(self.instances)
        
        if current == target_instances:
            return True
        
        if current < target_instances:
            # Scale up - would need factory method to create instances
            logger.info(f"Scaling up pool {self.pool_id} from {current} to {target_instances}")
            # This would be implemented by the ResourceManager
            
        else:
            # Scale down - remove least loaded instances
            to_remove = current - target_instances
            
            # Sort by load and remove least loaded
            sorted_instances = sorted(
                self.instances.values(),
                key=lambda i: len(i.current_tasks)
            )
            
            for instance in sorted_instances[:to_remove]:
                if len(instance.current_tasks) == 0:
                    await self.remove_instance(instance.id)
        
        return True
    
    async def optimize(self) -> None:
        """Optimize pool by removing unhealthy instances and rebalancing"""
        async with self.instance_lock:
            # Remove failed instances
            failed_instances = [
                i.id for i in self.instances.values()
                if i.status == ResourceStatus.FAILED
            ]
            
            for instance_id in failed_instances:
                logger.info(f"Removing failed instance {instance_id}")
                await self.remove_instance(instance_id)
            
            # Could add more optimization logic here:
            # - Rebalance tasks across instances
            # - Consolidate underutilized instances
            # - Pre-warm instances based on patterns
    
    async def start(self) -> None:
        """Start pool management tasks"""
        if self.running:
            return
        
        self.running = True
        
        # Start health check loop
        async def health_loop():
            while self.running:
                await asyncio.sleep(self.health_check_interval)
                try:
                    await self.health_check()
                except Exception as e:
                    logger.error(f"Health check error in pool {self.pool_id}: {e}")
        
        self.health_task = asyncio.create_task(health_loop())
        logger.info(f"Started ResourcePool {self.pool_id}")
    
    async def stop(self) -> None:
        """Stop pool management tasks"""
        if not self.running:
            return
        
        self.running = False
        
        # Cancel health check task
        if self.health_task:
            self.health_task.cancel()
            try:
                await self.health_task
            except asyncio.CancelledError:
                pass
        
        logger.info(f"Stopped ResourcePool {self.pool_id}")