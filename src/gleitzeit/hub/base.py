"""
Base classes for resource hub management
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Any, Optional, Set, Callable, TypeVar, Generic
import asyncio
import logging
from collections import defaultdict
import json

logger = logging.getLogger(__name__)

T = TypeVar('T')


class ResourceStatus(Enum):
    """Status of a resource instance"""
    UNKNOWN = "unknown"
    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class ResourceType(Enum):
    """Types of managed resources"""
    OLLAMA = "ollama"
    DOCKER = "docker"
    COMPUTE = "compute"
    STORAGE = "storage"
    CUSTOM = "custom"


@dataclass
class ResourceMetrics:
    """Metrics for a resource instance"""
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_mb: float = 0.0
    disk_io_mb: float = 0.0
    network_io_mb: float = 0.0
    request_count: int = 0
    error_count: int = 0
    avg_response_time_ms: float = 0.0
    p95_response_time_ms: float = 0.0
    p99_response_time_ms: float = 0.0
    active_connections: int = 0
    queued_requests: int = 0
    custom_metrics: Dict[str, Any] = field(default_factory=dict)
    last_updated: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary"""
        return {
            'cpu_percent': self.cpu_percent,
            'memory_percent': self.memory_percent,
            'memory_mb': self.memory_mb,
            'request_count': self.request_count,
            'error_count': self.error_count,
            'error_rate': self.error_count / max(1, self.request_count) * 100,
            'avg_response_time_ms': self.avg_response_time_ms,
            'p95_response_time_ms': self.p95_response_time_ms,
            'p99_response_time_ms': self.p99_response_time_ms,
            'active_connections': self.active_connections,
            'queued_requests': self.queued_requests,
            'custom': self.custom_metrics,
            'last_updated': self.last_updated.isoformat()
        }


@dataclass
class ResourceInstance(Generic[T]):
    """Represents a managed resource instance"""
    id: str
    name: str
    type: ResourceType
    endpoint: str  # URL or connection string
    status: ResourceStatus = ResourceStatus.UNKNOWN
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: Set[str] = field(default_factory=set)
    capabilities: Set[str] = field(default_factory=set)
    metrics: ResourceMetrics = field(default_factory=ResourceMetrics)
    health_checks_failed: int = 0
    last_health_check: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    config: Optional[T] = None  # Type-specific configuration
    
    def is_available(self) -> bool:
        """Check if instance is available for use"""
        return self.status in [ResourceStatus.HEALTHY, ResourceStatus.DEGRADED]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert instance to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'type': self.type.value,
            'endpoint': self.endpoint,
            'status': self.status.value,
            'metadata': self.metadata,
            'tags': list(self.tags),
            'capabilities': list(self.capabilities),
            'metrics': self.metrics.to_dict(),
            'health_checks_failed': self.health_checks_failed,
            'last_health_check': self.last_health_check.isoformat() if self.last_health_check else None,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }


class ResourceHub(ABC, Generic[T]):
    """
    Abstract base class for resource hub management
    
    Provides unified interface for managing different types of compute resources
    (Ollama instances, Docker containers, cloud instances, etc.)
    """
    
    def __init__(
        self,
        hub_id: str,
        resource_type: ResourceType,
        health_check_interval: int = 30,
        max_health_failures: int = 3,
        enable_auto_recovery: bool = True,
        enable_metrics: bool = True,
        persistence: Optional[Any] = None  # UnifiedPersistenceAdapter
    ):
        self.hub_id = hub_id
        self.resource_type = resource_type
        self.health_check_interval = health_check_interval
        self.max_health_failures = max_health_failures
        self.enable_auto_recovery = enable_auto_recovery
        self.enable_metrics = enable_metrics
        self.persistence = persistence
        
        # Resource registry
        self.instances: Dict[str, ResourceInstance[T]] = {}
        self.instance_lock = asyncio.Lock()
        
        # Event callbacks
        self.event_handlers: Dict[str, List[Callable]] = defaultdict(list)
        
        # Background tasks
        self.health_monitor_task: Optional[asyncio.Task] = None
        self.metrics_collector_task: Optional[asyncio.Task] = None
        self.running = False
        
        # Statistics
        self.stats = {
            'total_registered': 0,
            'total_health_checks': 0,
            'total_recoveries': 0,
            'total_failures': 0,
            'uptime_seconds': 0
        }
        self.started_at: Optional[datetime] = None
        
        logger.info(f"Initialized {resource_type.value} hub: {hub_id}")
    
    # Abstract methods to be implemented by subclasses
    
    @abstractmethod
    async def check_health(self, instance: ResourceInstance[T]) -> bool:
        """
        Check health of a specific instance
        Returns True if healthy, False otherwise
        """
        pass
    
    @abstractmethod
    async def collect_metrics(self, instance: ResourceInstance[T]) -> ResourceMetrics:
        """
        Collect metrics from a specific instance
        """
        pass
    
    @abstractmethod
    async def start_instance(self, config: T) -> ResourceInstance[T]:
        """
        Start a new resource instance with given configuration
        """
        pass
    
    @abstractmethod
    async def stop_instance(self, instance_id: str) -> bool:
        """
        Stop a specific resource instance
        """
        pass
    
    @abstractmethod
    async def restart_instance(self, instance_id: str) -> bool:
        """
        Restart a specific resource instance
        """
        pass
    
    # Common hub functionality
    
    async def register_instance(
        self,
        instance_id: str,
        name: str,
        endpoint: str,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[Set[str]] = None,
        capabilities: Optional[Set[str]] = None,
        config: Optional[T] = None
    ) -> ResourceInstance[T]:
        """Register a new resource instance"""
        async with self.instance_lock:
            if instance_id in self.instances:
                logger.warning(f"Instance {instance_id} already registered")
                return self.instances[instance_id]
            
            instance = ResourceInstance(
                id=instance_id,
                name=name,
                type=self.resource_type,
                endpoint=endpoint,
                metadata=metadata or {},
                tags=tags or set(),
                capabilities=capabilities or set(),
                config=config
            )
            
            self.instances[instance_id] = instance
            self.stats['total_registered'] += 1
            
            # Save to persistence if available
            if self.persistence:
                await self.persistence.save_instance(self.hub_id, instance)
            
            # Trigger initial health check
            asyncio.create_task(self._check_instance_health(instance))
            
            await self._emit_event('instance_registered', instance.to_dict())
            logger.info(f"Registered {self.resource_type.value} instance: {instance_id} ({name})")
            
            return instance
    
    async def register_instance_object(self, instance: ResourceInstance[T]) -> ResourceInstance[T]:
        """Register an already created ResourceInstance object"""
        async with self.instance_lock:
            if instance.id in self.instances:
                logger.warning(f"Instance {instance.id} already registered")
                return self.instances[instance.id]
            
            self.instances[instance.id] = instance
            self.stats['total_registered'] += 1
            
            # Save to persistence if available
            if self.persistence:
                await self.persistence.save_instance(self.hub_id, instance)
            
            # Trigger initial health check
            asyncio.create_task(self._check_instance_health(instance))
            
            await self._emit_event('instance_registered', instance.to_dict())
            logger.info(f"Registered {self.resource_type.value} instance: {instance.id} ({instance.name})")
            
            return instance
    
    async def unregister_instance(self, instance_id: str) -> bool:
        """Unregister a resource instance"""
        async with self.instance_lock:
            if instance_id not in self.instances:
                return False
            
            instance = self.instances.pop(instance_id)
            
            # Delete from persistence if available
            if self.persistence:
                await self.persistence.delete_instance(instance_id)
            
            await self._emit_event('instance_unregistered', instance.to_dict())
            logger.info(f"Unregistered instance: {instance_id}")
            
            return True
    
    async def get_instance(self, instance_id: str) -> Optional[ResourceInstance[T]]:
        """Get a specific instance by ID"""
        return self.instances.get(instance_id)
    
    async def health_check(self, instance_id: str) -> bool:
        """Check health of an instance by ID (wrapper for check_health)"""
        instance = self.instances.get(instance_id)
        if not instance:
            return False
        return await self.check_health(instance)
    
    async def list_instances(
        self,
        status: Optional[ResourceStatus] = None,
        tags: Optional[Set[str]] = None,
        capabilities: Optional[Set[str]] = None
    ) -> List[ResourceInstance[T]]:
        """List instances with optional filtering"""
        instances = list(self.instances.values())
        
        if status:
            instances = [i for i in instances if i.status == status]
        
        if tags:
            instances = [i for i in instances if tags.issubset(i.tags)]
        
        if capabilities:
            instances = [i for i in instances if capabilities.issubset(i.capabilities)]
        
        return instances
    
    async def get_available_instance(
        self,
        tags: Optional[Set[str]] = None,
        capabilities: Optional[Set[str]] = None,
        strategy: str = "least_loaded"
    ) -> Optional[ResourceInstance[T]]:
        """
        Get an available instance using specified strategy
        Strategies: least_loaded, round_robin, random, first_available
        """
        available = await self.list_instances(status=ResourceStatus.HEALTHY)
        
        if tags:
            available = [i for i in available if tags.issubset(i.tags)]
        
        if capabilities:
            available = [i for i in available if capabilities.issubset(i.capabilities)]
        
        if not available:
            return None
        
        if strategy == "least_loaded":
            return min(available, key=lambda i: i.metrics.active_connections)
        elif strategy == "round_robin":
            # Simple round-robin using instance order
            return available[0]  # Caller should rotate list
        elif strategy == "random":
            import random
            return random.choice(available)
        else:  # first_available
            return available[0]
    
    async def update_instance_status(
        self,
        instance_id: str,
        status: ResourceStatus,
        reason: Optional[str] = None
    ):
        """Update instance status"""
        if instance_id not in self.instances:
            return
        
        instance = self.instances[instance_id]
        old_status = instance.status
        instance.status = status
        instance.updated_at = datetime.utcnow()
        
        if old_status != status:
            await self._emit_event('status_changed', {
                'instance_id': instance_id,
                'old_status': old_status.value,
                'new_status': status.value,
                'reason': reason
            })
            
            logger.info(f"Instance {instance_id} status changed: {old_status.value} -> {status.value}")
    
    # Background tasks
    
    async def _health_monitor_loop(self):
        """Background task for health monitoring"""
        while self.running:
            try:
                tasks = []
                for instance in list(self.instances.values()):
                    tasks.append(self._check_instance_health(instance))
                
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                
                self.stats['total_health_checks'] += len(tasks)
                
            except Exception as e:
                logger.error(f"Health monitor error: {e}")
            
            await asyncio.sleep(self.health_check_interval)
    
    async def _check_instance_health(self, instance: ResourceInstance[T]):
        """Check health of a single instance"""
        try:
            is_healthy = await self.check_health(instance)
            instance.last_health_check = datetime.utcnow()
            
            if is_healthy:
                if instance.status != ResourceStatus.HEALTHY:
                    await self.update_instance_status(instance.id, ResourceStatus.HEALTHY)
                instance.health_checks_failed = 0
            else:
                instance.health_checks_failed += 1
                
                if instance.health_checks_failed >= self.max_health_failures:
                    await self.update_instance_status(
                        instance.id,
                        ResourceStatus.UNHEALTHY,
                        f"Failed {instance.health_checks_failed} health checks"
                    )
                    
                    if self.enable_auto_recovery:
                        await self._attempt_recovery(instance)
                elif instance.health_checks_failed > 1:
                    await self.update_instance_status(
                        instance.id,
                        ResourceStatus.DEGRADED,
                        f"Failed {instance.health_checks_failed} health checks"
                    )
        
        except Exception as e:
            logger.error(f"Health check failed for {instance.id}: {e}")
            instance.health_checks_failed += 1
    
    async def _attempt_recovery(self, instance: ResourceInstance[T]):
        """Attempt to recover an unhealthy instance"""
        logger.info(f"Attempting recovery for instance {instance.id}")
        
        try:
            success = await self.restart_instance(instance.id)
            
            if success:
                self.stats['total_recoveries'] += 1
                await self._emit_event('instance_recovered', {
                    'instance_id': instance.id,
                    'recovery_method': 'restart'
                })
            else:
                self.stats['total_failures'] += 1
                await self._emit_event('recovery_failed', {
                    'instance_id': instance.id
                })
        
        except Exception as e:
            logger.error(f"Recovery failed for {instance.id}: {e}")
            self.stats['total_failures'] += 1
    
    async def _metrics_collector_loop(self):
        """Background task for metrics collection"""
        while self.running:
            try:
                tasks = []
                for instance in list(self.instances.values()):
                    if instance.is_available():
                        tasks.append(self._collect_instance_metrics(instance))
                
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                
            except Exception as e:
                logger.error(f"Metrics collector error: {e}")
            
            await asyncio.sleep(30)  # Collect metrics every 30 seconds
    
    async def _collect_instance_metrics(self, instance: ResourceInstance[T]):
        """Collect metrics for a single instance"""
        try:
            metrics = await self.collect_metrics(instance)
            instance.metrics = metrics
            instance.updated_at = datetime.utcnow()
            
        except Exception as e:
            logger.error(f"Metrics collection failed for {instance.id}: {e}")
    
    # Event handling
    
    def on_event(self, event_name: str, handler: Callable):
        """Register an event handler"""
        self.event_handlers[event_name].append(handler)
    
    async def _emit_event(self, event_name: str, data: Any):
        """Emit an event to all registered handlers"""
        handlers = self.event_handlers.get(event_name, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
            except Exception as e:
                logger.error(f"Event handler error for {event_name}: {e}")
    
    # Lifecycle management
    
    async def start(self):
        """Start the resource hub"""
        if self.running:
            return
        
        self.running = True
        self.started_at = datetime.utcnow()
        
        # Start background tasks
        self.health_monitor_task = asyncio.create_task(self._health_monitor_loop())
        
        if self.enable_metrics:
            self.metrics_collector_task = asyncio.create_task(self._metrics_collector_loop())
        
        await self._emit_event('hub_started', {
            'hub_id': self.hub_id,
            'resource_type': self.resource_type.value
        })
        
        logger.info(f"Started {self.resource_type.value} hub: {self.hub_id}")
    
    async def stop(self):
        """Stop the resource hub"""
        if not self.running:
            return
        
        self.running = False
        
        # Cancel background tasks
        if self.health_monitor_task:
            self.health_monitor_task.cancel()
            try:
                await self.health_monitor_task
            except asyncio.CancelledError:
                pass
        
        if self.metrics_collector_task:
            self.metrics_collector_task.cancel()
            try:
                await self.metrics_collector_task
            except asyncio.CancelledError:
                pass
        
        # Update uptime
        if self.started_at:
            self.stats['uptime_seconds'] = (datetime.utcnow() - self.started_at).total_seconds()
        
        await self._emit_event('hub_stopped', {
            'hub_id': self.hub_id,
            'stats': self.stats
        })
        
        logger.info(f"Stopped {self.resource_type.value} hub: {self.hub_id}")
    
    # Hub status and statistics
    
    async def get_status(self) -> Dict[str, Any]:
        """Get hub status and statistics"""
        total = len(self.instances)
        by_status = defaultdict(int)
        
        for instance in self.instances.values():
            by_status[instance.status.value] += 1
        
        return {
            'hub_id': self.hub_id,
            'resource_type': self.resource_type.value,
            'running': self.running,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'uptime_seconds': (datetime.utcnow() - self.started_at).total_seconds() if self.started_at else 0,
            'instances': {
                'total': total,
                'by_status': dict(by_status),
                'healthy': by_status[ResourceStatus.HEALTHY.value],
                'degraded': by_status[ResourceStatus.DEGRADED.value],
                'unhealthy': by_status[ResourceStatus.UNHEALTHY.value]
            },
            'stats': self.stats,
            'config': {
                'health_check_interval': self.health_check_interval,
                'max_health_failures': self.max_health_failures,
                'enable_auto_recovery': self.enable_auto_recovery,
                'enable_metrics': self.enable_metrics
            }
        }
    
    async def get_metrics_summary(self) -> Dict[str, Any]:
        """Get aggregated metrics summary"""
        if not self.instances:
            return {}
        
        total_cpu = sum(i.metrics.cpu_percent for i in self.instances.values())
        total_memory = sum(i.metrics.memory_mb for i in self.instances.values())
        total_requests = sum(i.metrics.request_count for i in self.instances.values())
        total_errors = sum(i.metrics.error_count for i in self.instances.values())
        
        response_times = [i.metrics.avg_response_time_ms for i in self.instances.values() if i.metrics.avg_response_time_ms > 0]
        
        return {
            'aggregate': {
                'total_cpu_percent': total_cpu,
                'total_memory_mb': total_memory,
                'total_requests': total_requests,
                'total_errors': total_errors,
                'error_rate': (total_errors / max(1, total_requests)) * 100,
                'avg_response_time_ms': sum(response_times) / len(response_times) if response_times else 0
            },
            'by_instance': {
                instance_id: instance.metrics.to_dict()
                for instance_id, instance in self.instances.items()
            }
        }
    
    async def cleanup(self) -> None:
        """Clean up resources - to be overridden by subclasses"""
        await self.stop()