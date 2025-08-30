"""
Prototype of Streamlined Hub Architecture

This demonstrates the key concepts for scaling and simplifying the hub system:
1. Distributed resource registry
2. Intelligent resource selection  
3. Adaptive health monitoring
4. Global connection management
5. Unified hub interface

Note: This is a design prototype, not production-ready code
"""

import asyncio
import aiohttp
import time
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Set, Union
from enum import Enum
import statistics
import logging

logger = logging.getLogger(__name__)


# ==================== Core Data Models ====================

class ResourceType(Enum):
    DOCKER = "docker"
    OLLAMA = "ollama"  
    MCP = "mcp"
    CUSTOM = "custom"


class ResourceStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    PROVISIONING = "provisioning"
    TERMINATING = "terminating"


@dataclass
class ResourceMetrics:
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    active_connections: int = 0
    avg_response_time_ms: float = 0.0
    error_rate: float = 0.0
    requests_per_minute: int = 0
    last_updated: datetime = field(default_factory=datetime.utcnow)
    
    def is_overloaded(self) -> bool:
        return (self.cpu_percent > 80 or 
                self.memory_percent > 90 or
                self.error_rate > 0.1)


@dataclass
class Resource:
    id: str
    type: ResourceType
    endpoint: str
    status: ResourceStatus = ResourceStatus.HEALTHY
    tags: Set[str] = field(default_factory=set)
    capabilities: Set[str] = field(default_factory=set)
    metrics: ResourceMetrics = field(default_factory=ResourceMetrics)
    metadata: Dict[str, Any] = field(default_factory=dict)
    cost_per_hour: float = 0.1  # For cost-based selection
    region: str = "default"
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def is_healthy(self) -> bool:
        return self.status == ResourceStatus.HEALTHY
    
    def serialize(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'type': self.type.value,
            'endpoint': self.endpoint,
            'status': self.status.value,
            'tags': list(self.tags),
            'capabilities': list(self.capabilities),
            'metrics': {
                'cpu_percent': self.metrics.cpu_percent,
                'memory_percent': self.metrics.memory_percent,
                'active_connections': self.metrics.active_connections,
                'avg_response_time_ms': self.metrics.avg_response_time_ms,
                'error_rate': self.metrics.error_rate,
                'requests_per_minute': self.metrics.requests_per_minute,
                'last_updated': self.metrics.last_updated.isoformat()
            },
            'metadata': self.metadata,
            'cost_per_hour': self.cost_per_hour,
            'region': self.region,
            'created_at': self.created_at.isoformat()
        }


@dataclass
class ExecutionContext:
    user_id: Optional[str] = None
    workflow_id: Optional[str] = None
    priority: int = 1  # 1-10 scale
    preferred_region: Optional[str] = None
    required_capabilities: Set[str] = field(default_factory=set)
    preferred_tags: Set[str] = field(default_factory=set)
    cost_budget: Optional[float] = None
    latency_requirement: Optional[int] = None  # max ms


# ==================== Distributed Backend Interface ====================

class DistributedBackend(ABC):
    """Abstract interface for distributed state backend"""
    
    @abstractmethod
    async def set_with_ttl(self, key: str, value: str, ttl: int) -> None:
        pass
    
    @abstractmethod
    async def get(self, key: str) -> Optional[str]:
        pass
    
    @abstractmethod
    async def scan_pattern(self, pattern: str) -> List[Dict[str, Any]]:
        pass
    
    @abstractmethod
    async def delete(self, key: str) -> None:
        pass


class MockDistributedBackend(DistributedBackend):
    """Mock implementation for testing"""
    
    def __init__(self):
        self.data = {}
        self.expiry = {}
    
    async def set_with_ttl(self, key: str, value: str, ttl: int) -> None:
        self.data[key] = value
        self.expiry[key] = datetime.utcnow() + timedelta(seconds=ttl)
    
    async def get(self, key: str) -> Optional[str]:
        if key in self.expiry and datetime.utcnow() > self.expiry[key]:
            del self.data[key]
            del self.expiry[key]
            return None
        return self.data.get(key)
    
    async def scan_pattern(self, pattern: str) -> List[Dict[str, Any]]:
        # Simple pattern matching (not production quality)
        prefix = pattern.replace('*', '')
        results = []
        for key, value in self.data.items():
            if key.startswith(prefix):
                if key in self.expiry and datetime.utcnow() > self.expiry[key]:
                    continue
                try:
                    results.append(json.loads(value))
                except json.JSONDecodeError:
                    continue
        return results
    
    async def delete(self, key: str) -> None:
        self.data.pop(key, None)
        self.expiry.pop(key, None)


# ==================== Distributed Resource Registry ====================

class ResourceRegistry:
    """Distributed resource registry for multi-node deployments"""
    
    def __init__(self, backend: DistributedBackend):
        self.backend = backend
        self.ttl = 300  # 5 minute TTL for resource entries
    
    async def register_resource(self, resource: Resource) -> None:
        """Register a resource in the distributed registry"""
        key = f"resources:{resource.type.value}:{resource.id}"
        value = json.dumps(resource.serialize())
        await self.backend.set_with_ttl(key, value, self.ttl)
        
        logger.info(f"Registered resource {resource.id} of type {resource.type.value}")
    
    async def discover_resources(self, 
                               resource_type: ResourceType,
                               tags: Optional[Set[str]] = None,
                               capabilities: Optional[Set[str]] = None,
                               healthy_only: bool = True,
                               region: Optional[str] = None) -> List[Resource]:
        """Discover resources matching criteria"""
        
        pattern = f"resources:{resource_type.value}:*"
        resource_data = await self.backend.scan_pattern(pattern)
        
        resources = []
        for data in resource_data:
            resource = self._deserialize_resource(data)
            
            # Apply filters
            if healthy_only and not resource.is_healthy():
                continue
            if tags and not tags.issubset(resource.tags):
                continue  
            if capabilities and not capabilities.issubset(resource.capabilities):
                continue
            if region and resource.region != region:
                continue
                
            resources.append(resource)
        
        logger.debug(f"Discovered {len(resources)} {resource_type.value} resources")
        return resources
    
    async def update_resource_metrics(self, resource_id: str, resource_type: ResourceType, metrics: ResourceMetrics) -> None:
        """Update resource metrics in registry"""
        key = f"resources:{resource_type.value}:{resource_id}"
        resource_data = await self.backend.get(key)
        
        if resource_data:
            data = json.loads(resource_data)
            data['metrics'] = {
                'cpu_percent': metrics.cpu_percent,
                'memory_percent': metrics.memory_percent,
                'active_connections': metrics.active_connections,
                'avg_response_time_ms': metrics.avg_response_time_ms,
                'error_rate': metrics.error_rate,
                'requests_per_minute': metrics.requests_per_minute,
                'last_updated': metrics.last_updated.isoformat()
            }
            await self.backend.set_with_ttl(key, json.dumps(data), self.ttl)
    
    async def unregister_resource(self, resource_id: str, resource_type: ResourceType) -> None:
        """Remove resource from registry"""
        key = f"resources:{resource_type.value}:{resource_id}"
        await self.backend.delete(key)
        logger.info(f"Unregistered resource {resource_id}")
    
    def _deserialize_resource(self, data: Dict[str, Any]) -> Resource:
        """Convert dict back to Resource object"""
        metrics_data = data.get('metrics', {})
        metrics = ResourceMetrics(
            cpu_percent=metrics_data.get('cpu_percent', 0.0),
            memory_percent=metrics_data.get('memory_percent', 0.0),
            active_connections=metrics_data.get('active_connections', 0),
            avg_response_time_ms=metrics_data.get('avg_response_time_ms', 0.0),
            error_rate=metrics_data.get('error_rate', 0.0),
            requests_per_minute=metrics_data.get('requests_per_minute', 0)
        )
        
        return Resource(
            id=data['id'],
            type=ResourceType(data['type']),
            endpoint=data['endpoint'],
            status=ResourceStatus(data['status']),
            tags=set(data.get('tags', [])),
            capabilities=set(data.get('capabilities', [])),
            metrics=metrics,
            metadata=data.get('metadata', {}),
            cost_per_hour=data.get('cost_per_hour', 0.1),
            region=data.get('region', 'default')
        )


# ==================== Intelligent Resource Selection ====================

class SmartResourceSelector:
    """Multi-factor resource selection with configurable weights"""
    
    def __init__(self):
        # Configurable weights for different factors
        self.weights = {
            'load': 0.35,       # CPU/memory utilization
            'latency': 0.25,    # Response time history
            'affinity': 0.20,   # Data locality / workflow affinity  
            'cost': 0.10,       # Cost optimization
            'reliability': 0.10  # Error rate / uptime
        }
        
        self.selection_history = {}  # Track selections for learning
    
    async def select_best_resource(self, 
                                  resources: List[Resource], 
                                  context: ExecutionContext = None) -> Optional[Resource]:
        """Select optimal resource using multi-factor scoring"""
        
        if not resources:
            return None
        
        if len(resources) == 1:
            return resources[0]
        
        # Score all resources in parallel
        scoring_tasks = [
            self._score_resource(resource, context) 
            for resource in resources
        ]
        scores = await asyncio.gather(*scoring_tasks)
        
        # Select best scoring resource
        best_idx = max(range(len(scores)), key=lambda i: scores[i])
        selected_resource = resources[best_idx]
        
        # Track selection for learning
        self._record_selection(selected_resource, context, scores[best_idx])
        
        logger.debug(f"Selected resource {selected_resource.id} with score {scores[best_idx]:.3f}")
        return selected_resource
    
    async def _score_resource(self, resource: Resource, context: Optional[ExecutionContext]) -> float:
        """Calculate multi-factor score for a resource"""
        
        metrics = resource.metrics
        
        # Load factor (lower utilization = higher score)
        load_score = max(0, 1.0 - (metrics.cpu_percent / 100.0) - (metrics.memory_percent / 100.0))
        
        # Latency factor (faster response = higher score)
        latency_score = 1.0 / (metrics.avg_response_time_ms + 1.0)
        
        # Reliability factor (lower error rate = higher score)
        reliability_score = max(0, 1.0 - metrics.error_rate)
        
        # Cost factor (lower cost = higher score)
        cost_score = 1.0 / (resource.cost_per_hour + 0.01)
        
        # Affinity factor (context-dependent)
        affinity_score = self._calculate_affinity_score(resource, context) if context else 0.5
        
        # Weighted combination
        total_score = (
            self.weights['load'] * load_score +
            self.weights['latency'] * latency_score + 
            self.weights['reliability'] * reliability_score +
            self.weights['cost'] * cost_score +
            self.weights['affinity'] * affinity_score
        )
        
        # Penalty for overloaded resources
        if metrics.is_overloaded():
            total_score *= 0.1
        
        return max(0.0, total_score)
    
    def _calculate_affinity_score(self, resource: Resource, context: ExecutionContext) -> float:
        """Calculate affinity score based on context"""
        score = 0.5  # Base score
        
        # Region preference
        if context.preferred_region and resource.region == context.preferred_region:
            score += 0.3
        
        # Tag preferences  
        if context.preferred_tags:
            matching_tags = len(context.preferred_tags.intersection(resource.tags))
            score += 0.2 * (matching_tags / len(context.preferred_tags))
        
        # Cost constraints
        if context.cost_budget and resource.cost_per_hour <= context.cost_budget:
            score += 0.1
        
        # Previous workflow affinity (simplified)
        if context.workflow_id and context.workflow_id in resource.metadata.get('recent_workflows', []):
            score += 0.2
        
        return min(1.0, score)
    
    def _record_selection(self, resource: Resource, context: Optional[ExecutionContext], score: float):
        """Record selection for potential machine learning optimization"""
        selection_record = {
            'resource_id': resource.id,
            'resource_type': resource.type.value,
            'score': score,
            'timestamp': datetime.utcnow(),
            'context': {
                'user_id': context.user_id if context else None,
                'workflow_id': context.workflow_id if context else None,
                'priority': context.priority if context else 1
            }
        }
        
        # Store recent selections (in production, this would go to a database)
        if resource.type not in self.selection_history:
            self.selection_history[resource.type] = []
        
        self.selection_history[resource.type].append(selection_record)
        
        # Keep only last 1000 selections per type
        self.selection_history[resource.type] = self.selection_history[resource.type][-1000:]


# ==================== Adaptive Health Monitoring ====================

class AdaptiveHealthSystem:
    """Adaptive health monitoring with intelligent intervals"""
    
    def __init__(self, registry: ResourceRegistry):
        self.registry = registry
        self.base_interval = 30  # Base 30 second interval
        self.min_interval = 5    # Minimum 5 seconds for unhealthy resources
        self.max_interval = 300  # Maximum 5 minutes for healthy resources
        
        self.health_intervals = {}  # resource_id -> current_interval
        self.consecutive_health = {}  # resource_id -> consecutive healthy count
        self.monitoring_tasks = {}  # resource_id -> monitoring task
        
        self.running = False
    
    async def start_monitoring_resources(self, resources: List[Resource]):
        """Start adaptive monitoring for a list of resources"""
        self.running = True
        
        for resource in resources:
            if resource.id not in self.monitoring_tasks:
                task = asyncio.create_task(self._monitor_resource(resource))
                self.monitoring_tasks[resource.id] = task
        
        logger.info(f"Started adaptive monitoring for {len(resources)} resources")
    
    async def stop_monitoring(self):
        """Stop all monitoring tasks"""
        self.running = False
        
        for task in self.monitoring_tasks.values():
            task.cancel()
        
        await asyncio.gather(*self.monitoring_tasks.values(), return_exceptions=True)
        self.monitoring_tasks.clear()
        logger.info("Stopped all health monitoring")
    
    async def _monitor_resource(self, resource: Resource):
        """Adaptive monitoring loop for a single resource"""
        resource_id = resource.id
        
        while self.running:
            try:
                # Calculate adaptive interval
                interval = self._calculate_monitoring_interval(resource)
                
                # Perform health check (mock implementation)
                is_healthy, metrics = await self._perform_health_check(resource)
                
                # Update resource status
                new_status = ResourceStatus.HEALTHY if is_healthy else ResourceStatus.UNHEALTHY
                if resource.status != new_status:
                    resource.status = new_status
                    logger.info(f"Resource {resource_id} status changed to {new_status.value}")
                
                # Update metrics in registry  
                if metrics:
                    await self.registry.update_resource_metrics(resource_id, resource.type, metrics)
                
                # Update health tracking
                if is_healthy:
                    self.consecutive_health[resource_id] = self.consecutive_health.get(resource_id, 0) + 1
                else:
                    self.consecutive_health[resource_id] = 0
                
                # Sleep until next check
                await asyncio.sleep(interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check failed for resource {resource_id}: {e}")
                await asyncio.sleep(self.base_interval)
    
    def _calculate_monitoring_interval(self, resource: Resource) -> int:
        """Calculate adaptive monitoring interval based on resource health"""
        
        consecutive_healthy = self.consecutive_health.get(resource.id, 0)
        
        if resource.status == ResourceStatus.HEALTHY:
            # Healthy resources: exponential backoff with cap
            backoff_factor = min(consecutive_healthy // 5, 3)  # Max 3 levels of backoff
            interval = int(self.base_interval * (1.5 ** backoff_factor))
            return min(interval, self.max_interval)
        else:
            # Unhealthy resources: check more frequently
            return self.min_interval
    
    async def _perform_health_check(self, resource: Resource) -> tuple[bool, Optional[ResourceMetrics]]:
        """Perform actual health check (mock implementation)"""
        
        # Mock health check - in reality this would ping the actual resource
        await asyncio.sleep(0.1)  # Simulate network call
        
        # Mock: 95% chance healthy, 5% unhealthy
        import random
        is_healthy = random.random() > 0.05
        
        # Mock metrics
        if is_healthy:
            metrics = ResourceMetrics(
                cpu_percent=random.uniform(10, 60),
                memory_percent=random.uniform(20, 70),
                active_connections=random.randint(0, 50),
                avg_response_time_ms=random.uniform(50, 200),
                error_rate=random.uniform(0, 0.02),
                requests_per_minute=random.randint(10, 100)
            )
        else:
            metrics = ResourceMetrics(
                cpu_percent=random.uniform(80, 100),
                memory_percent=random.uniform(90, 100),
                active_connections=random.randint(50, 200),
                avg_response_time_ms=random.uniform(1000, 5000),
                error_rate=random.uniform(0.1, 0.5),
                requests_per_minute=random.randint(0, 10)
            )
        
        return is_healthy, metrics


# ==================== Global Connection Manager ====================

class GlobalConnectionManager:
    """Singleton connection manager for all HTTP communications"""
    
    _instance = None
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    async def initialize(self):
        """Initialize the connection manager"""
        if self._initialized:
            return
        
        async with GlobalConnectionManager._lock:
            if self._initialized:
                return
                
            # Create single global connector with optimized settings
            self.connector = aiohttp.TCPConnector(
                limit=2000,               # High global connection limit
                limit_per_host=200,       # High per-host limit
                ttl_dns_cache=600,        # 10 minute DNS cache
                use_dns_cache=True,
                keepalive_timeout=60,     # Keep connections alive
                enable_cleanup_closed=True,
                ssl=False  # Simplified for demo
            )
            
            # Session pool per unique endpoint
            self.sessions = {}
            self.session_lock = asyncio.Lock()
            
            self._initialized = True
            logger.info("Initialized global connection manager")
    
    async def get_session(self, endpoint: str) -> aiohttp.ClientSession:
        """Get or create session for endpoint"""
        if not self._initialized:
            await self.initialize()
        
        async with self.session_lock:
            if endpoint not in self.sessions:
                session = aiohttp.ClientSession(
                    connector=self.connector,
                    timeout=aiohttp.ClientTimeout(total=30, connect=10),
                    connector_owner=False  # Don't close connector when session closes
                )
                self.sessions[endpoint] = session
                logger.debug(f"Created new session for {endpoint}")
            
            return self.sessions[endpoint]
    
    async def cleanup(self):
        """Cleanup all sessions and connector"""
        async with self.session_lock:
            for session in self.sessions.values():
                await session.close()
            self.sessions.clear()
        
        if hasattr(self, 'connector'):
            await self.connector.close()
        
        self._initialized = False
        logger.info("Cleaned up global connection manager")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get connection manager statistics"""
        return {
            'active_sessions': len(self.sessions),
            'connector_limit': self.connector.limit if hasattr(self, 'connector') else 0,
            'connector_limit_per_host': self.connector.limit_per_host if hasattr(self, 'connector') else 0
        }


# ==================== Unified Hub Interface ====================

class ResourcePlugin(ABC):
    """Plugin interface for resource-specific operations"""
    
    @abstractmethod
    async def execute(self, resource: Resource, operation: str, **params) -> Any:
        """Execute operation on resource"""
        pass
    
    @abstractmethod
    async def health_check(self, resource: Resource) -> bool:
        """Check if resource is healthy"""
        pass


class UnifiedResourceHub:
    """Streamlined hub that handles all resource types"""
    
    def __init__(self, 
                 registry: ResourceRegistry,
                 selector: SmartResourceSelector,
                 health_system: AdaptiveHealthSystem,
                 connection_manager: GlobalConnectionManager):
        
        self.registry = registry
        self.selector = selector
        self.health_system = health_system
        self.connection_manager = connection_manager
        
        # Plugin system for resource-specific logic
        self.resource_plugins: Dict[ResourceType, ResourcePlugin] = {}
        
        # Statistics
        self.stats = {
            'requests_handled': 0,
            'resources_provisioned': 0,
            'avg_selection_time_ms': 0.0
        }
        
        self.running = False
    
    async def start(self):
        """Start the unified hub"""
        if self.running:
            return
            
        await self.connection_manager.initialize()
        self.running = True
        
        logger.info("Started unified resource hub")
    
    async def stop(self):
        """Stop the unified hub"""
        if not self.running:
            return
            
        await self.health_system.stop_monitoring()
        await self.connection_manager.cleanup()
        self.running = False
        
        logger.info("Stopped unified resource hub")
    
    async def get_resource(self, 
                          resource_type: ResourceType,
                          context: Optional[ExecutionContext] = None,
                          **filters) -> Optional[Resource]:
        """Get best available resource of specified type"""
        
        start_time = time.time()
        
        # Discover available resources from distributed registry
        resources = await self.registry.discover_resources(
            resource_type=resource_type,
            healthy_only=True,
            **filters
        )
        
        # If no resources available, try to provision new ones
        if not resources:
            new_resource = await self._try_provision_resource(resource_type, context)
            if new_resource:
                resources = [new_resource]
        
        if not resources:
            logger.warning(f"No {resource_type.value} resources available")
            return None
        
        # Select best resource using intelligent selection
        selected_resource = await self.selector.select_best_resource(resources, context)
        
        # Update statistics
        selection_time_ms = (time.time() - start_time) * 1000
        self.stats['requests_handled'] += 1
        self.stats['avg_selection_time_ms'] = (
            (self.stats['avg_selection_time_ms'] * (self.stats['requests_handled'] - 1) + selection_time_ms) /
            self.stats['requests_handled']
        )
        
        return selected_resource
    
    async def execute_on_resource(self,
                                 resource: Resource,
                                 operation: str,
                                 **params) -> Any:
        """Execute operation on specific resource using appropriate plugin"""
        
        plugin = self.resource_plugins.get(resource.type)
        if not plugin:
            raise ValueError(f"No plugin registered for resource type {resource.type.value}")
        
        try:
            # Execute operation with timing
            start_time = time.time()
            result = await plugin.execute(resource, operation, **params)
            execution_time = (time.time() - start_time) * 1000
            
            # Update resource metrics
            resource.metrics.avg_response_time_ms = (
                resource.metrics.avg_response_time_ms * 0.9 + execution_time * 0.1
            )
            resource.metrics.active_connections += 1
            
            return result
            
        except Exception as e:
            # Update error metrics
            resource.metrics.error_rate = resource.metrics.error_rate * 0.9 + 0.1
            logger.error(f"Operation {operation} failed on resource {resource.id}: {e}")
            raise
        finally:
            # Decrease active connections
            resource.metrics.active_connections = max(0, resource.metrics.active_connections - 1)
    
    def register_plugin(self, resource_type: ResourceType, plugin: ResourcePlugin):
        """Register plugin for handling specific resource type"""
        self.resource_plugins[resource_type] = plugin
        logger.info(f"Registered plugin for resource type {resource_type.value}")
    
    async def _try_provision_resource(self, 
                                    resource_type: ResourceType, 
                                    context: Optional[ExecutionContext]) -> Optional[Resource]:
        """Try to provision a new resource (mock implementation)"""
        
        # Mock provisioning - in reality this would:
        # - Call cloud APIs to start new instances
        # - Start local processes/containers  
        # - Update service registry
        
        logger.info(f"Attempting to provision new {resource_type.value} resource")
        
        # Simulate provisioning delay
        await asyncio.sleep(1.0)
        
        # Mock: 80% success rate
        import random
        if random.random() < 0.8:
            new_resource = Resource(
                id=f"{resource_type.value}_{int(time.time())}",
                type=resource_type,
                endpoint=f"http://localhost:{random.randint(8000, 9000)}",
                status=ResourceStatus.PROVISIONING,
                tags={"provisioned", "auto-scaled"},
                region=context.preferred_region if context else "default"
            )
            
            # Register in distributed registry
            await self.registry.register_resource(new_resource)
            
            # Start monitoring
            await self.health_system.start_monitoring_resources([new_resource])
            
            self.stats['resources_provisioned'] += 1
            logger.info(f"Successfully provisioned resource {new_resource.id}")
            
            return new_resource
        
        logger.warning(f"Failed to provision {resource_type.value} resource")
        return None
    
    def get_hub_stats(self) -> Dict[str, Any]:
        """Get hub statistics"""
        return {
            'requests_handled': self.stats['requests_handled'],
            'resources_provisioned': self.stats['resources_provisioned'], 
            'avg_selection_time_ms': self.stats['avg_selection_time_ms'],
            'registered_plugins': list(self.resource_plugins.keys()),
            'connection_manager': self.connection_manager.get_stats()
        }


# ==================== Example Plugin Implementation ====================

class DockerResourcePlugin(ResourcePlugin):
    """Plugin for handling Docker container resources"""
    
    async def execute(self, resource: Resource, operation: str, **params) -> Any:
        """Execute Docker operation"""
        
        if operation == "run_script":
            # Mock Docker script execution
            script_path = params.get("script_path")
            args = params.get("args", [])
            
            # Simulate execution
            await asyncio.sleep(0.5)
            
            return {
                "success": True,
                "exit_code": 0,
                "container_id": f"container_{resource.id}_{int(time.time())}",
                "output": f"Executed script {script_path} with args {args}",
                "execution_time_ms": 500
            }
        
        else:
            raise ValueError(f"Unknown Docker operation: {operation}")
    
    async def health_check(self, resource: Resource) -> bool:
        """Check Docker resource health"""
        # Mock health check
        await asyncio.sleep(0.1)
        return True  # Simplified for demo


# ==================== Demo Usage ====================

async def demo_streamlined_hub():
    """Demonstrate the streamlined hub architecture"""
    
    # Initialize components
    backend = MockDistributedBackend()
    registry = ResourceRegistry(backend)
    selector = SmartResourceSelector()
    health_system = AdaptiveHealthSystem(registry)
    connection_manager = GlobalConnectionManager()
    
    # Create unified hub
    hub = UnifiedResourceHub(registry, selector, health_system, connection_manager)
    
    # Register plugins
    hub.register_plugin(ResourceType.DOCKER, DockerResourcePlugin())
    
    # Start hub
    await hub.start()
    
    try:
        # Register some mock Docker resources
        docker_resources = [
            Resource(
                id=f"docker_{i}",
                type=ResourceType.DOCKER,
                endpoint=f"http://docker-node-{i}:2376",
                tags={"docker", "compute"},
                capabilities={"container_exec", "volume_mount"},
                region="us-east-1" if i % 2 == 0 else "us-west-2"
            )
            for i in range(5)
        ]
        
        for resource in docker_resources:
            await registry.register_resource(resource)
        
        # Start monitoring
        await health_system.start_monitoring_resources(docker_resources)
        
        print("=== Streamlined Hub Demo ===")
        
        # Example 1: Get a Docker resource
        context = ExecutionContext(
            user_id="demo_user",
            workflow_id="demo_workflow",
            preferred_region="us-east-1",
            priority=5
        )
        
        selected_resource = await hub.get_resource(ResourceType.DOCKER, context)
        if selected_resource:
            print(f"Selected Docker resource: {selected_resource.id} in {selected_resource.region}")
            
            # Execute operation on selected resource
            result = await hub.execute_on_resource(
                selected_resource,
                "run_script",
                script_path="/app/test.py",
                args=["arg1", "arg2"]
            )
            print(f"Execution result: {result}")
        
        # Example 2: Show resource discovery
        all_docker = await registry.discover_resources(ResourceType.DOCKER)
        print(f"\nDiscovered {len(all_docker)} Docker resources")
        
        # Example 3: Show hub statistics
        stats = hub.get_hub_stats()
        print(f"\nHub statistics: {stats}")
        
        # Wait a bit to let health monitoring run
        print("\nWaiting for health monitoring...")
        await asyncio.sleep(5)
        
    finally:
        await hub.stop()
        print("\nStreamlined hub demo completed")


if __name__ == "__main__":
    asyncio.run(demo_streamlined_hub())