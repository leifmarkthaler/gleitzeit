"""
Unified Resource Manager - Orchestrates multiple resource hubs

The ResourceManager provides centralized management of different resource types
through their respective hubs. It handles resource allocation, monitoring, and
orchestration across multiple resource types (Ollama, Docker, etc.).
"""
import asyncio
import logging
from typing import Dict, List, Any, Optional, Set, Union
from datetime import datetime
from collections import defaultdict
import json

from .base import ResourceHub, ResourceInstance, ResourceStatus, ResourceType
from .configs import OllamaConfig, DockerConfig
from .ollama_hub import OllamaHub
from .docker_hub import DockerHub

logger = logging.getLogger(__name__)


class ResourceManager:
    """
    Unified manager for all resource hubs
    
    Provides:
    - Centralized resource management across different types
    - Unified API for resource allocation
    - Cross-hub orchestration and dependencies
    - Global resource monitoring and metrics
    - Resource scheduling and optimization
    """
    
    def __init__(self, manager_id: str = "resource-manager"):
        self.manager_id = manager_id
        self.hubs: Dict[str, ResourceHub] = {}
        self.hub_lock = asyncio.Lock()
        
        # Resource allocation tracking
        self.allocations: Dict[str, Dict[str, Any]] = {}  # allocation_id -> details
        self.allocation_lock = asyncio.Lock()
        
        # Global event handlers
        self.event_handlers: Dict[str, List] = defaultdict(list)
        
        # Background tasks
        self.monitor_task: Optional[asyncio.Task] = None
        self.optimizer_task: Optional[asyncio.Task] = None
        self.running = False
        
        # Statistics
        self.stats = {
            'total_hubs': 0,
            'total_resources': 0,
            'total_allocations': 0,
            'allocation_failures': 0
        }
        
        logger.info(f"Initialized ResourceManager: {manager_id}")
    
    async def add_hub(self, hub_id: str, hub: ResourceHub) -> bool:
        """Add a resource hub to the manager"""
        async with self.hub_lock:
            if hub_id in self.hubs:
                logger.warning(f"Hub {hub_id} already exists")
                return False
            
            self.hubs[hub_id] = hub
            self.stats['total_hubs'] += 1
            
            # Register for hub events
            hub.on_event('instance_registered', lambda d: self._handle_hub_event(hub_id, 'registered', d))
            hub.on_event('instance_unregistered', lambda d: self._handle_hub_event(hub_id, 'unregistered', d))
            hub.on_event('status_changed', lambda d: self._handle_hub_event(hub_id, 'status_changed', d))
            
            logger.info(f"Added hub {hub_id} ({hub.resource_type.value})")
            return True
    
    async def remove_hub(self, hub_id: str) -> bool:
        """Remove a resource hub from the manager"""
        async with self.hub_lock:
            if hub_id not in self.hubs:
                return False
            
            hub = self.hubs.pop(hub_id)
            await hub.stop()
            
            self.stats['total_hubs'] -= 1
            logger.info(f"Removed hub {hub_id}")
            return True
    
    def get_hub(self, hub_id: str) -> Optional[ResourceHub]:
        """Get a hub by ID"""
        return self.hubs.get(hub_id)
    
    async def get_hubs(self) -> Dict[str, ResourceHub]:
        """Get all registered hubs"""
        return self.hubs.copy()
    
    async def create_ollama_hub(
        self,
        hub_id: str = "ollama",
        auto_discover: bool = True,
        instances: Optional[List[Dict[str, Any]]] = None
    ) -> OllamaHub:
        """Create and add an Ollama hub"""
        hub = OllamaHub(
            hub_id=hub_id,
            auto_discover=auto_discover
        )
        
        await self.add_hub(hub_id, hub)
        await hub.initialize()  # Initialize to set up session and auto-discover
        await hub.start()
        
        # Register provided instances
        if instances:
            for inst_config in instances:
                config = OllamaConfig(
                    host=inst_config.get('host', '127.0.0.1'),
                    port=inst_config.get('port', 11434),
                    models=inst_config.get('models', []),
                    max_concurrent=inst_config.get('max_concurrent', 4)
                )
                await hub.start_instance(config)
        
        return hub
    
    async def create_docker_hub(
        self,
        hub_id: str = "docker",
        enable_container_reuse: bool = True
    ) -> DockerHub:
        """Create and add a Docker hub"""
        hub = DockerHub(
            hub_id=hub_id,
            enable_container_reuse=enable_container_reuse
        )
        
        await self.add_hub(hub_id, hub)
        await hub.start()
        
        return hub
    
    async def allocate_resource(
        self,
        resource_type: ResourceType,
        requirements: Optional[Dict[str, Any]] = None,
        allocation_id: Optional[str] = None
    ) -> Optional[ResourceInstance]:
        """
        Allocate a resource based on requirements
        
        Requirements can include:
        - tags: Set of required tags
        - capabilities: Set of required capabilities
        - min_memory: Minimum memory in MB
        - min_cpu: Minimum CPU cores
        - preferred_hub: Preferred hub ID
        """
        requirements = requirements or {}
        allocation_id = allocation_id or f"alloc-{datetime.utcnow().timestamp()}"
        
        # Find suitable hub
        suitable_hubs = [
            hub for hub_id, hub in self.hubs.items()
            if hub.resource_type == resource_type and hub.running
        ]
        
        if requirements.get('preferred_hub'):
            preferred = self.hubs.get(requirements['preferred_hub'])
            if preferred and preferred in suitable_hubs:
                suitable_hubs = [preferred] + [h for h in suitable_hubs if h != preferred]
        
        # Try to allocate from suitable hubs
        for hub in suitable_hubs:
            instance = await hub.get_available_instance(
                tags=requirements.get('tags'),
                capabilities=requirements.get('capabilities'),
                strategy=requirements.get('strategy', 'least_loaded')
            )
            
            if instance:
                # Check additional requirements
                if requirements.get('min_memory'):
                    if instance.metrics.memory_mb < requirements['min_memory']:
                        continue
                
                if requirements.get('min_cpu'):
                    # This is harder to check without more detailed metrics
                    pass
                
                # Record allocation
                async with self.allocation_lock:
                    self.allocations[allocation_id] = {
                        'instance_id': instance.id,
                        'hub_id': hub.hub_id,
                        'resource_type': resource_type.value,
                        'allocated_at': datetime.utcnow().isoformat(),
                        'requirements': requirements
                    }
                
                self.stats['total_allocations'] += 1
                logger.info(f"Allocated {instance.id} for {allocation_id}")
                return instance
        
        self.stats['allocation_failures'] += 1
        logger.warning(f"Failed to allocate {resource_type.value} for {allocation_id}")
        return None
    
    async def release_allocation(self, allocation_id: str) -> bool:
        """Release an allocated resource"""
        async with self.allocation_lock:
            if allocation_id not in self.allocations:
                return False
            
            allocation = self.allocations.pop(allocation_id)
            logger.info(f"Released allocation {allocation_id}")
            return True
    
    async def get_all_resources(
        self,
        resource_type: Optional[ResourceType] = None,
        status: Optional[ResourceStatus] = None
    ) -> List[ResourceInstance]:
        """Get all resources across all hubs"""
        all_resources = []
        
        for hub in self.hubs.values():
            if resource_type and hub.resource_type != resource_type:
                continue
            
            instances = await hub.list_instances(status=status)
            all_resources.extend(instances)
        
        return all_resources
    
    async def execute_on_ollama(
        self,
        model: str,
        method: str,
        params: Dict[str, Any],
        preferred_instance: Optional[str] = None
    ) -> Dict[str, Any]:
        """Execute a request on an Ollama instance"""
        # Find Ollama hub
        ollama_hub = None
        for hub in self.hubs.values():
            if isinstance(hub, OllamaHub):
                ollama_hub = hub
                break
        
        if not ollama_hub:
            raise RuntimeError("No Ollama hub available")
        
        # Get instance for model
        if preferred_instance:
            instance = await ollama_hub.get_instance(preferred_instance)
        else:
            instance = await ollama_hub.get_instance_for_model(model)
        
        if not instance:
            raise RuntimeError(f"No instance available for model {model}")
        
        # Execute request
        return await ollama_hub.execute_on_instance(instance.id, method, params)
    
    async def execute_in_docker(
        self,
        command: str,
        image: str = "python:3.11-slim",
        requirements: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Execute a command in a Docker container"""
        # Find Docker hub
        docker_hub = None
        for hub in self.hubs.values():
            if isinstance(hub, DockerHub):
                docker_hub = hub
                break
        
        if not docker_hub:
            raise RuntimeError("No Docker hub available")
        
        # Allocate or create container
        instance = await self.allocate_resource(
            ResourceType.DOCKER,
            requirements={'tags': {image.split(':')[0]}}
        )
        
        if not instance:
            # Create new container
            config = DockerConfig(image=image)
            instance = await docker_hub.start_instance(config)
        
        try:
            # Execute command
            result = await docker_hub.execute_in_container(instance.id, command)
            return result
        finally:
            # Release allocation
            await self.release_allocation(f"docker-exec-{instance.id}")
    
    async def scale_hub(
        self,
        hub_id: str,
        target_instances: int,
        config_template: Optional[Union[OllamaConfig, DockerConfig]] = None
    ) -> List[ResourceInstance]:
        """Scale a hub to target number of instances"""
        if hub_id not in self.hubs:
            raise ValueError(f"Hub {hub_id} not found")
        
        hub = self.hubs[hub_id]
        current_instances = await hub.list_instances()
        current_count = len(current_instances)
        
        if current_count == target_instances:
            return current_instances
        
        new_instances = []
        
        if current_count < target_instances:
            # Scale up
            for i in range(target_instances - current_count):
                if isinstance(hub, OllamaHub):
                    config = config_template or OllamaConfig(
                        port=11434 + current_count + i
                    )
                elif isinstance(hub, DockerHub):
                    config = config_template or DockerConfig()
                else:
                    continue
                
                instance = await hub.start_instance(config)
                new_instances.append(instance)
        else:
            # Scale down
            instances_to_remove = current_instances[target_instances:]
            for instance in instances_to_remove:
                await hub.stop_instance(instance.id)
        
        return await hub.list_instances()
    
    async def get_global_metrics(self) -> Dict[str, Any]:
        """Get metrics across all hubs"""
        metrics = {
            'manager_id': self.manager_id,
            'total_hubs': len(self.hubs),
            'total_resources': 0,
            'resources_by_type': {},
            'resources_by_status': defaultdict(int),
            'hub_metrics': {}
        }
        
        for hub_id, hub in self.hubs.items():
            hub_status = await hub.get_status()
            hub_metrics = await hub.get_metrics_summary()
            
            metrics['hub_metrics'][hub_id] = {
                'status': hub_status,
                'metrics': hub_metrics
            }
            
            # Aggregate counts
            instances = await hub.list_instances()
            metrics['total_resources'] += len(instances)
            
            if hub.resource_type.value not in metrics['resources_by_type']:
                metrics['resources_by_type'][hub.resource_type.value] = 0
            metrics['resources_by_type'][hub.resource_type.value] += len(instances)
            
            for instance in instances:
                metrics['resources_by_status'][instance.status.value] += 1
        
        metrics['resources_by_status'] = dict(metrics['resources_by_status'])
        metrics['allocations'] = {
            'active': len(self.allocations),
            'total': self.stats['total_allocations'],
            'failures': self.stats['allocation_failures']
        }
        
        return metrics
    
    async def optimize_resources(self):
        """Optimize resource allocation across hubs"""
        # This could include:
        # - Consolidating underutilized resources
        # - Rebalancing load across instances
        # - Scaling based on demand patterns
        # - Cost optimization for cloud resources
        
        for hub in self.hubs.values():
            instances = await hub.list_instances()
            
            # Find underutilized instances
            underutilized = [
                i for i in instances
                if i.is_available() and i.metrics.cpu_percent < 10
            ]
            
            # Could stop some underutilized instances
            # This is a simple example - real optimization would be more sophisticated
            if len(underutilized) > 2:
                logger.info(f"Found {len(underutilized)} underutilized instances in {hub.hub_id}")
    
    def _handle_hub_event(self, hub_id: str, event_type: str, data: Any):
        """Handle events from hubs"""
        self.stats['total_resources'] = sum(
            len(hub.instances) for hub in self.hubs.values()
        )
        
        # Emit global event
        for handler in self.event_handlers.get(f"hub_{event_type}", []):
            try:
                handler(hub_id, data)
            except Exception as e:
                logger.error(f"Event handler error: {e}")
    
    async def start(self):
        """Start the resource manager"""
        if self.running:
            return
        
        self.running = True
        
        # Start all hubs
        for hub in self.hubs.values():
            if not hub.running:
                await hub.start()
        
        # Start background tasks
        async def monitor_loop():
            while self.running:
                await asyncio.sleep(60)
                metrics = await self.get_global_metrics()
                logger.info(f"Resource Manager Status: {metrics['total_resources']} resources across {metrics['total_hubs']} hubs")
        
        async def optimizer_loop():
            while self.running:
                await asyncio.sleep(300)  # Every 5 minutes
                await self.optimize_resources()
        
        self.monitor_task = asyncio.create_task(monitor_loop())
        self.optimizer_task = asyncio.create_task(optimizer_loop())
        
        logger.info(f"Started ResourceManager: {self.manager_id}")
    
    async def stop(self):
        """Stop the resource manager"""
        if not self.running:
            return
        
        self.running = False
        
        # Cancel background tasks
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        
        if self.optimizer_task:
            self.optimizer_task.cancel()
            try:
                await self.optimizer_task
            except asyncio.CancelledError:
                pass
        
        # Stop all hubs
        for hub in self.hubs.values():
            await hub.stop()
        
        logger.info(f"Stopped ResourceManager: {self.manager_id}")