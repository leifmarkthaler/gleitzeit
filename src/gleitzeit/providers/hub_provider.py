"""
Hub-Integrated Provider Base Class
Streamlines resource management by integrating hub functionality directly into providers
"""

import logging
from typing import Dict, Any, Optional, List, TypeVar, Generic, Type
from abc import ABC, abstractmethod
import asyncio

from gleitzeit.providers.base import ProtocolProvider
from gleitzeit.hub.base import ResourceHub, ResourceInstance, ResourceStatus
from gleitzeit.common.load_balancer import LoadBalancer, LoadBalancingStrategy, ResourceInfo
from gleitzeit.common.metrics import MetricsCollector
from gleitzeit.common.health_monitor import HealthMonitor, HealthCheck
from gleitzeit.common.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

T = TypeVar('T')  # Generic config type


class HubProvider(ProtocolProvider, Generic[T], ABC):
    """
    Base provider class with integrated hub functionality
    
    This streamlined approach:
    - Eliminates the need for separate hub instances
    - Provides built-in resource management
    - Simplifies provider implementation
    - Maintains clean separation of concerns
    """
    
    def __init__(
        self,
        provider_id: str,
        protocol_id: str,
        name: str,
        description: str,
        resource_config_class: Type[T],
        enable_sharing: bool = False,
        max_instances: int = 10,
        enable_auto_discovery: bool = False,
        enable_health_monitoring: bool = True,
        enable_circuit_breaker: bool = True,
        enable_metrics: bool = True,
        default_load_balancing: LoadBalancingStrategy = LoadBalancingStrategy.LEAST_LOADED
    ):
        """
        Initialize hub-integrated provider
        
        Args:
            provider_id: Unique provider identifier
            protocol_id: Protocol this provider implements
            name: Human-readable name
            description: Provider description
            resource_config_class: Configuration class for resources
            enable_sharing: Allow this provider to be shared across instances
            max_instances: Maximum resource instances to manage
            enable_auto_discovery: Auto-discover available resources
            enable_health_monitoring: Enable health checks
            enable_circuit_breaker: Enable circuit breaker protection
            enable_metrics: Enable metrics collection
            default_load_balancing: Default load balancing strategy
        """
        super().__init__(provider_id, protocol_id, name, description)
        
        # Resource management
        self.resource_config_class = resource_config_class
        self.instances: Dict[str, ResourceInstance[T]] = {}
        self.max_instances = max_instances
        self.enable_sharing = enable_sharing
        self.enable_auto_discovery = enable_auto_discovery
        
        # Components
        self.load_balancer = LoadBalancer(default_strategy=default_load_balancing)
        self.metrics_collector = MetricsCollector() if enable_metrics else None
        self.health_monitor = HealthMonitor() if enable_health_monitoring else None
        self.circuit_breaker = CircuitBreaker() if enable_circuit_breaker else None
        
        # State
        self.is_initialized = False
        self.shutdown_event = asyncio.Event()
        
        # Background tasks
        self.monitor_task: Optional[asyncio.Task] = None
        
        logger.info(f"Initialized HubProvider: {provider_id} with integrated resource management")
    
    # Abstract methods for subclasses to implement
    
    @abstractmethod
    async def create_resource(self, config: T) -> ResourceInstance[T]:
        """
        Create a new resource instance
        
        Args:
            config: Resource configuration
            
        Returns:
            Created resource instance
        """
        pass
    
    @abstractmethod
    async def destroy_resource(self, instance: ResourceInstance[T]):
        """
        Destroy a resource instance
        
        Args:
            instance: Instance to destroy
        """
        pass
    
    @abstractmethod
    async def execute_on_resource(
        self,
        instance: ResourceInstance[T],
        method: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a method on a specific resource
        
        Args:
            instance: Resource instance
            method: Method to execute
            params: Method parameters
            
        Returns:
            Execution result
        """
        pass
    
    @abstractmethod
    async def check_resource_health(self, instance: ResourceInstance[T]) -> bool:
        """
        Check if a resource is healthy
        
        Args:
            instance: Resource instance
            
        Returns:
            True if healthy
        """
        pass
    
    @abstractmethod
    async def discover_resources(self) -> List[T]:
        """
        Discover available resources (optional)
        
        Returns:
            List of discovered resource configurations
        """
        return []
    
    # Hub functionality integrated into provider
    
    async def initialize(self):
        """Initialize the provider with integrated hub"""
        if self.is_initialized:
            return
        
        try:
            # Auto-discover resources if enabled
            if self.enable_auto_discovery:
                discovered = await self.discover_resources()
                for config in discovered:
                    try:
                        instance = await self.create_resource(config)
                        await self.register_instance(instance)
                        logger.info(f"Auto-discovered and registered: {instance.id}")
                    except Exception as e:
                        logger.error(f"Failed to register discovered resource: {e}")
            
            # Start health monitoring
            if self.health_monitor:
                self.monitor_task = asyncio.create_task(self._health_monitor_loop())
            
            self.is_initialized = True
            logger.info(f"✅ Provider {self.provider_id} initialized with {len(self.instances)} resources")
            
        except Exception as e:
            logger.error(f"Failed to initialize provider: {e}")
            raise
    
    async def shutdown(self):
        """Shutdown the provider and cleanup resources"""
        logger.info(f"Shutting down provider {self.provider_id}")
        
        # Signal shutdown
        self.shutdown_event.set()
        
        # Stop monitoring
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        
        # Cleanup resources
        for instance in list(self.instances.values()):
            try:
                await self.destroy_resource(instance)
                logger.debug(f"Destroyed resource: {instance.id}")
            except Exception as e:
                logger.error(f"Failed to destroy resource {instance.id}: {e}")
        
        self.instances.clear()
        self.is_initialized = False
        logger.info(f"Provider {self.provider_id} shutdown complete")
    
    async def register_instance(self, instance: ResourceInstance[T]):
        """Register a resource instance"""
        if len(self.instances) >= self.max_instances:
            raise ValueError(f"Maximum instances ({self.max_instances}) reached")
        
        self.instances[instance.id] = instance
        
        # Register with health monitor
        if self.health_monitor:
            self.health_monitor.register_resource(
                resource_id=instance.id,
                health_check=ResourceHealthCheck(self, instance),
                metadata={'instance': instance}
            )
        
        logger.info(f"Registered resource: {instance.id}")
    
    async def unregister_instance(self, instance_id: str):
        """Unregister a resource instance"""
        if instance_id in self.instances:
            instance = self.instances.pop(instance_id)
            
            # Unregister from health monitor
            if self.health_monitor:
                self.health_monitor.unregister_resource(instance_id)
            
            logger.info(f"Unregistered resource: {instance_id}")
            return instance
        return None
    
    async def get_instance(
        self,
        requirements: Optional[Dict[str, Any]] = None,
        strategy: Optional[LoadBalancingStrategy] = None
    ) -> Optional[ResourceInstance[T]]:
        """
        Get a resource instance based on requirements
        
        Args:
            requirements: Resource requirements
            strategy: Load balancing strategy
            
        Returns:
            Selected resource instance or None
        """
        # Filter healthy instances
        healthy_instances = [
            inst for inst in self.instances.values()
            if inst.status == ResourceStatus.HEALTHY
        ]
        
        if not healthy_instances:
            return None
        
        # Apply requirements filter
        if requirements:
            filtered = []
            for inst in healthy_instances:
                # Check capabilities
                if 'capabilities' in requirements:
                    required = set(requirements['capabilities'])
                    if not required.issubset(inst.capabilities):
                        continue
                
                # Check tags
                if 'tags' in requirements:
                    required = set(requirements['tags'])
                    if not required.issubset(inst.tags):
                        continue
                
                filtered.append(inst)
            
            healthy_instances = filtered
        
        if not healthy_instances:
            return None
        
        # Convert to ResourceInfo for load balancer
        resources = [
            ResourceInfo(
                id=inst.id,
                active_requests=inst.metrics.active_connections,
                avg_response_time=inst.metrics.avg_response_time_ms,
                error_rate=inst.metrics.error_count / max(inst.metrics.request_count, 1),
                capabilities=inst.capabilities,
                metadata={'instance': inst}
            )
            for inst in healthy_instances
        ]
        
        # Select using load balancer
        selected = self.load_balancer.select_resource(
            resources=resources,
            strategy=strategy,
            required_capabilities=requirements.get('capabilities') if requirements else None
        )
        
        if selected and selected.metadata:
            return selected.metadata['instance']
        
        return None
    
    async def execute(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a protocol method
        
        This is the main entry point that:
        1. Gets an appropriate resource instance
        2. Executes the method on that instance
        3. Handles metrics and error tracking
        """
        # Get instance based on method requirements
        requirements = self.get_method_requirements(method, params)
        instance = await self.get_instance(requirements)
        
        if not instance:
            # Try to create a new instance if possible
            if len(self.instances) < self.max_instances:
                config = self.create_default_config(method, params)
                instance = await self.create_resource(config)
                await self.register_instance(instance)
            else:
                raise Exception(f"No available resources for method {method}")
        
        # Track metrics
        if self.metrics_collector:
            self.metrics_collector.record_request_start(instance.id)
        
        # Execute with circuit breaker if enabled
        try:
            if self.circuit_breaker and not self.circuit_breaker.can_execute(instance.id):
                raise Exception(f"Circuit breaker open for {instance.id}")
            
            # Execute on resource
            import time
            start_time = time.time()
            
            result = await self.execute_on_resource(instance, method, params)
            
            response_time = (time.time() - start_time) * 1000  # ms
            
            # Record success
            if self.metrics_collector:
                self.metrics_collector.record_request_end(
                    instance.id, 
                    success=True, 
                    response_time_ms=response_time
                )
            
            if self.circuit_breaker:
                self.circuit_breaker.record_success(instance.id)
            
            # Update instance metrics
            instance.metrics.request_count += 1
            instance.metrics.avg_response_time_ms = (
                (instance.metrics.avg_response_time_ms * (instance.metrics.request_count - 1) + response_time) 
                / instance.metrics.request_count
            )
            
            return result
            
        except Exception as e:
            # Record failure
            if self.metrics_collector:
                self.metrics_collector.record_request_end(
                    instance.id,
                    success=False,
                    error=str(e)
                )
            
            if self.circuit_breaker:
                self.circuit_breaker.record_failure(instance.id, e)
            
            # Update instance metrics
            instance.metrics.error_count += 1
            
            raise
    
    async def health_check(self) -> Dict[str, Any]:
        """Check provider health"""
        healthy_count = sum(
            1 for inst in self.instances.values()
            if inst.status == ResourceStatus.HEALTHY
        )
        
        return {
            "status": "healthy" if healthy_count > 0 else "unhealthy",
            "details": {
                "provider_id": self.provider_id,
                "protocol": self.protocol_id,
                "total_instances": len(self.instances),
                "healthy_instances": healthy_count,
                "max_instances": self.max_instances,
                "sharing_enabled": self.enable_sharing,
                "auto_discovery": self.enable_auto_discovery
            }
        }
    
    async def get_status(self) -> Dict[str, Any]:
        """Get detailed provider status"""
        status = await self.health_check()
        
        # Add metrics if available
        if self.metrics_collector:
            status['metrics'] = self.metrics_collector.get_summary()
        
        # Add instance details
        status['instances'] = {
            inst.id: {
                'status': inst.status.value,
                'endpoint': inst.endpoint,
                'capabilities': list(inst.capabilities),
                'tags': list(inst.tags),
                'metrics': inst.metrics.to_dict()
            }
            for inst in self.instances.values()
        }
        
        return status
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """
        Handle a JSON-RPC method call (required by ProtocolProvider)
        Routes to execute() for actual execution
        """
        return await self.execute(method, params)
    
    # Helper methods for subclasses
    
    def get_method_requirements(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get resource requirements for a method
        Subclasses can override to provide specific requirements
        """
        return {}
    
    def create_default_config(self, method: str, params: Dict[str, Any]) -> T:
        """
        Create default resource configuration
        Subclasses should override to provide sensible defaults
        """
        return self.resource_config_class()
    
    # Internal methods
    
    async def _health_monitor_loop(self):
        """Background health monitoring"""
        while not self.shutdown_event.is_set():
            try:
                for instance in list(self.instances.values()):
                    try:
                        is_healthy = await self.check_resource_health(instance)
                        
                        # Update status
                        old_status = instance.status
                        instance.status = ResourceStatus.HEALTHY if is_healthy else ResourceStatus.UNHEALTHY
                        
                        if old_status != instance.status:
                            logger.info(f"Instance {instance.id} status changed: {old_status.value} -> {instance.status.value}")
                    
                    except Exception as e:
                        logger.error(f"Health check failed for {instance.id}: {e}")
                        instance.status = ResourceStatus.UNHEALTHY
                
                # Wait before next check
                await asyncio.sleep(30)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health monitor loop: {e}")
                await asyncio.sleep(5)


class ResourceHealthCheck(HealthCheck):
    """Health check adapter for resources"""
    
    def __init__(self, provider: HubProvider, instance: ResourceInstance):
        self.provider = provider
        self.instance = instance
    
    async def check(self, resource_id: str, **kwargs) -> Any:
        """Perform health check"""
        return await self.provider.check_resource_health(self.instance)