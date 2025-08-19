# Resource Management Guide

## Overview

Gleitzeit v0.0.5 introduces a comprehensive resource management system built on two key components:
- **Resource Hubs**: Manage specific types of compute resources (Ollama servers, Docker containers)
- **ResourceManager**: Orchestrates multiple hubs for global resource coordination

## Architecture

```
┌────────────────────────────────────────────────┐
│            ResourceManager                      │
│         (Global Orchestration)                  │
│                                                 │
│  • Manages multiple hubs                       │
│  • Global resource allocation                  │
│  • Cross-hub metrics aggregation              │
│  • Event coordination                          │
└───────────────┬────────────────────────────────┘
                │
     ┌──────────┼──────────┐
     ▼          ▼          ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│OllamaHub │ │DockerHub │ │CustomHub │
│          │ │          │ │          │
│ Manages  │ │ Manages  │ │ Manages  │
│  Ollama  │ │ Docker   │ │  Custom  │
│ Servers  │ │Containers│ │Resources │
└──────────┘ └──────────┘ └──────────┘
```

## Core Concepts

### ResourceInstance
The fundamental unit of resource management:

```python
@dataclass
class ResourceInstance:
    """Represents a managed resource instance"""
    id: str                          # Unique identifier
    name: str                        # Human-readable name
    type: ResourceType               # OLLAMA, DOCKER, etc.
    endpoint: str                    # Access endpoint (URL)
    status: ResourceStatus           # STARTING, HEALTHY, UNHEALTHY, STOPPED
    config: Any                      # Type-specific configuration
    metadata: Dict[str, Any] = None  # Additional metadata
    created_at: datetime = None      # Creation timestamp
    last_health_check: datetime = None
    metrics: ResourceMetrics = None
```

### ResourceHub Base Class

```python
from gleitzeit.hub.base import ResourceHub, ResourceInstance
from typing import TypeVar, Generic, Optional, List

T = TypeVar('T')  # Configuration type

class ResourceHub(Generic[T], ABC):
    """Base class for all resource hubs"""
    
    def __init__(
        self,
        hub_id: str,
        resource_type: ResourceType,
        max_instances: Optional[int] = None,
        health_check_interval: int = 30,
        enable_auto_recovery: bool = True,
        persistence: Optional[UnifiedPersistenceAdapter] = None
    ):
        self.hub_id = hub_id
        self.resource_type = resource_type
        self.max_instances = max_instances
        self.health_check_interval = health_check_interval
        self.enable_auto_recovery = enable_auto_recovery
        self.persistence = persistence
        self.instances: Dict[str, ResourceInstance] = {}
        self._health_monitor_task = None
    
    @abstractmethod
    async def start_instance(self, config: T) -> ResourceInstance:
        """Start a new resource instance"""
        pass
    
    @abstractmethod
    async def stop_instance(self, instance_id: str) -> None:
        """Stop a resource instance"""
        pass
    
    @abstractmethod
    async def check_health(self, instance: ResourceInstance) -> bool:
        """Check if instance is healthy"""
        pass
```

## Hub Implementations

### OllamaHub

Manages Ollama LLM server instances:

```python
from gleitzeit.hub.ollama_hub import OllamaHub
from gleitzeit.hub.configs import OllamaConfig

# Create hub
hub = OllamaHub(
    hub_id="ollama-main",
    max_instances=5,
    health_check_interval=30,
    enable_auto_recovery=True
)

# Initialize
await hub.initialize()

# Start instances
configs = [
    OllamaConfig(host="127.0.0.1", port=11434),
    OllamaConfig(host="127.0.0.1", port=11435),
    OllamaConfig(host="192.168.1.100", port=11434)
]

for config in configs:
    instance = await hub.start_instance(config)
    print(f"Started: {instance.name} at {instance.endpoint}")

# Get available instance for use
instance = await hub.get_available_instance()
if instance:
    # Use instance.endpoint for API calls
    response = await make_ollama_request(instance.endpoint, params)
```

### DockerHub

Manages Docker containers for secure code execution:

```python
from gleitzeit.hub.docker_hub import DockerHub
from gleitzeit.hub.configs import DockerConfig

# Create hub
hub = DockerHub(
    hub_id="docker-main",
    max_instances=10,
    enable_container_reuse=True,
    default_image="python:3.11-slim"
)

# Initialize
await hub.initialize()

# Start container
config = DockerConfig(
    image="python:3.11-slim",
    memory_limit="512m",
    cpu_limit=1.0,
    network_mode="none",  # Security: no network
    auto_remove=False     # Reuse containers
)

instance = await hub.start_instance(config)

# Execute code in container
result = await hub.execute_in_container(
    instance.id,
    code="print('Hello from container')"
)
```

## ResourceManager

Global orchestrator for all hubs:

```python
from gleitzeit.hub.resource_manager import ResourceManager

class ResourceManager:
    """Orchestrates multiple resource hubs"""
    
    def __init__(self):
        self.hubs: Dict[str, ResourceHub] = {}
        self.allocation_strategy = "round-robin"
    
    async def add_hub(self, name: str, hub: ResourceHub) -> None:
        """Register a hub with the manager"""
        self.hubs[name] = hub
        await hub.initialize()
    
    async def get_resource(
        self,
        resource_type: ResourceType,
        requirements: Optional[Dict] = None
    ) -> Optional[ResourceInstance]:
        """Get available resource matching requirements"""
        # Find appropriate hub
        for hub in self.hubs.values():
            if hub.resource_type == resource_type:
                instance = await hub.get_available_instance(requirements)
                if instance:
                    return instance
        return None
    
    async def get_global_metrics(self) -> Dict[str, Any]:
        """Aggregate metrics across all hubs"""
        metrics = {
            "total_resources": 0,
            "healthy_resources": 0,
            "by_type": {},
            "by_hub": {}
        }
        
        for name, hub in self.hubs.items():
            hub_metrics = await hub.get_metrics()
            metrics["by_hub"][name] = hub_metrics
            metrics["total_resources"] += hub_metrics["total"]
            metrics["healthy_resources"] += hub_metrics["healthy"]
            
            # Aggregate by type
            resource_type = hub.resource_type.value
            if resource_type not in metrics["by_type"]:
                metrics["by_type"][resource_type] = 0
            metrics["by_type"][resource_type] += hub_metrics["total"]
        
        return metrics
```

## Complete Setup Example

```python
import asyncio
from gleitzeit.hub.ollama_hub import OllamaHub
from gleitzeit.hub.docker_hub import DockerHub
from gleitzeit.hub.resource_manager import ResourceManager
from gleitzeit.persistence import UnifiedPersistenceAdapter

async def setup_resource_management():
    # 1. Create persistence adapter
    persistence = UnifiedPersistenceAdapter()
    await persistence.initialize()
    
    # 2. Create OllamaHub for LLM resources
    ollama_hub = OllamaHub(
        hub_id="ollama-main",
        max_instances=5,
        health_check_interval=30,
        enable_auto_recovery=True,
        persistence=persistence
    )
    
    # 3. Create DockerHub for Python execution
    docker_hub = DockerHub(
        hub_id="docker-main",
        max_instances=10,
        enable_container_reuse=True,
        cleanup_interval=300,  # Clean idle containers every 5 min
        persistence=persistence
    )
    
    # 4. Create ResourceManager
    manager = ResourceManager()
    
    # 5. Register hubs with manager
    await manager.add_hub("ollama", ollama_hub)
    await manager.add_hub("docker", docker_hub)
    
    # 6. Start initial resources
    # Start Ollama instances
    ollama_configs = [
        OllamaConfig(host="127.0.0.1", port=11434),
        OllamaConfig(host="127.0.0.1", port=11435)
    ]
    for config in ollama_configs:
        await ollama_hub.start_instance(config)
    
    # Pre-warm Docker containers
    docker_config = DockerConfig(
        image="python:3.11-slim",
        memory_limit="512m"
    )
    for _ in range(3):  # Start 3 containers
        await docker_hub.start_instance(docker_config)
    
    return manager

# Usage
async def main():
    manager = await setup_resource_management()
    
    # Get metrics
    metrics = await manager.get_global_metrics()
    print(f"Total resources: {metrics['total_resources']}")
    print(f"Healthy: {metrics['healthy_resources']}")
    
    # Get specific resource
    ollama_instance = await manager.get_resource(
        ResourceType.OLLAMA,
        requirements={"min_memory": 4096}
    )
    
    if ollama_instance:
        print(f"Got Ollama at: {ollama_instance.endpoint}")
```

## Health Monitoring

### Automatic Health Checks

Hubs automatically monitor instance health:

```python
class OllamaHub(ResourceHub):
    async def _health_monitor_loop(self):
        """Background health monitoring"""
        while self._running:
            for instance in list(self.instances.values()):
                try:
                    is_healthy = await self.check_health(instance)
                    
                    if is_healthy and instance.status != ResourceStatus.HEALTHY:
                        instance.status = ResourceStatus.HEALTHY
                        await self._emit_event("instance_recovered", instance)
                    
                    elif not is_healthy and instance.status == ResourceStatus.HEALTHY:
                        instance.status = ResourceStatus.UNHEALTHY
                        await self._emit_event("instance_unhealthy", instance)
                        
                        if self.enable_auto_recovery:
                            await self._attempt_recovery(instance)
                    
                    instance.last_health_check = datetime.now()
                    
                except Exception as e:
                    logger.error(f"Health check failed for {instance.id}: {e}")
            
            await asyncio.sleep(self.health_check_interval)
```

### Custom Health Checks

```python
class CustomHub(ResourceHub):
    async def check_health(self, instance: ResourceInstance) -> bool:
        """Custom health check implementation"""
        try:
            # Check process is running
            if not self._is_process_running(instance):
                return False
            
            # Check responds to requests
            response = await self._test_endpoint(instance.endpoint)
            if not response:
                return False
            
            # Check resource usage
            metrics = await self._get_instance_metrics(instance)
            if metrics['cpu_percent'] > 90 or metrics['memory_percent'] > 95:
                logger.warning(f"Instance {instance.id} under high load")
                return False
            
            return True
        except Exception:
            return False
```

## Resource Allocation Strategies

### Round-Robin Allocation
```python
class RoundRobinStrategy:
    def __init__(self):
        self.last_index = {}
    
    def select_instance(self, instances: List[ResourceInstance]) -> ResourceInstance:
        hub_id = instances[0].hub_id if instances else None
        if not hub_id or hub_id not in self.last_index:
            self.last_index[hub_id] = 0
        
        healthy = [i for i in instances if i.status == ResourceStatus.HEALTHY]
        if not healthy:
            return None
        
        index = self.last_index[hub_id] % len(healthy)
        self.last_index[hub_id] = index + 1
        return healthy[index]
```

### Load-Based Allocation
```python
class LoadBasedStrategy:
    async def select_instance(self, instances: List[ResourceInstance]) -> ResourceInstance:
        healthy = [i for i in instances if i.status == ResourceStatus.HEALTHY]
        if not healthy:
            return None
        
        # Select instance with lowest load
        loads = []
        for instance in healthy:
            metrics = instance.metrics or {}
            load = metrics.get('cpu_percent', 0) * 0.5 + metrics.get('memory_percent', 0) * 0.5
            loads.append((load, instance))
        
        loads.sort(key=lambda x: x[0])
        return loads[0][1] if loads else None
```

## Event System

Hubs emit events for monitoring and integration:

```python
# Subscribe to hub events
def on_instance_started(data):
    print(f"Instance started: {data['instance'].id}")

def on_instance_unhealthy(data):
    alert_admin(f"Instance unhealthy: {data['instance'].id}")

hub.on_event('instance_started', on_instance_started)
hub.on_event('instance_unhealthy', on_instance_unhealthy)

# Available events
EVENTS = [
    'instance_started',
    'instance_stopped',
    'instance_healthy',
    'instance_unhealthy',
    'instance_recovered',
    'health_check_failed',
    'resource_limit_reached',
    'cleanup_performed'
]
```

## Metrics Collection

### Hub Metrics
```python
metrics = await hub.get_metrics()
# {
#     "hub_id": "ollama-main",
#     "total": 5,
#     "healthy": 4,
#     "unhealthy": 1,
#     "starting": 0,
#     "stopped": 0,
#     "cpu_usage_percent": 45.2,
#     "memory_usage_mb": 8192,
#     "health_check_success_rate": 0.95,
#     "average_response_time_ms": 125
# }
```

### Instance Metrics
```python
instance_metrics = await hub.get_instance_metrics(instance_id)
# {
#     "instance_id": "ollama-127-0-0-1-11434",
#     "uptime_seconds": 3600,
#     "requests_processed": 1500,
#     "errors": 5,
#     "cpu_percent": 35.5,
#     "memory_mb": 2048,
#     "disk_io_mb": 150,
#     "network_io_mb": 75
# }
```

### Global Metrics
```python
global_metrics = await manager.get_global_metrics()
# {
#     "total_resources": 15,
#     "healthy_resources": 13,
#     "by_type": {
#         "OLLAMA": 5,
#         "DOCKER": 10
#     },
#     "by_hub": {
#         "ollama-main": {...},
#         "docker-main": {...}
#     },
#     "total_cpu_percent": 55.3,
#     "total_memory_gb": 12.5
# }
```

## Auto-Recovery

Hubs can automatically recover unhealthy instances:

```python
class OllamaHub(ResourceHub):
    async def _attempt_recovery(self, instance: ResourceInstance):
        """Attempt to recover unhealthy instance"""
        logger.info(f"Attempting recovery for {instance.id}")
        
        try:
            # Step 1: Try gentle restart
            await self._restart_instance(instance)
            await asyncio.sleep(5)
            
            if await self.check_health(instance):
                logger.info(f"Recovery successful for {instance.id}")
                instance.status = ResourceStatus.HEALTHY
                return
            
            # Step 2: Stop and restart
            await self.stop_instance(instance.id)
            new_instance = await self.start_instance(instance.config)
            
            if await self.check_health(new_instance):
                logger.info(f"Full restart successful for {instance.id}")
                return
            
            # Step 3: Mark as failed
            instance.status = ResourceStatus.FAILED
            await self._emit_event("recovery_failed", instance)
            
        except Exception as e:
            logger.error(f"Recovery failed for {instance.id}: {e}")
```

## Resource Cleanup

### Automatic Cleanup
```python
class DockerHub(ResourceHub):
    async def _cleanup_loop(self):
        """Periodic cleanup of idle resources"""
        while self._running:
            await asyncio.sleep(self.cleanup_interval)
            
            for instance in list(self.instances.values()):
                if instance.status == ResourceStatus.STOPPED:
                    idle_time = (datetime.now() - instance.last_used).seconds
                    
                    if idle_time > self.max_idle_time:
                        logger.info(f"Cleaning up idle container {instance.id}")
                        await self._remove_container(instance)
                        del self.instances[instance.id]
```

### Manual Cleanup
```python
# Clean up specific instance
await hub.cleanup_instance(instance_id)

# Clean up all stopped instances
await hub.cleanup_stopped()

# Force cleanup all
await hub.cleanup_all()
```

## Best Practices

### 1. Resource Pooling
```python
# Pre-warm resources for better performance
async def prewarm_resources(hub, count=3):
    """Start resources in advance"""
    configs = [hub.default_config for _ in range(count)]
    tasks = [hub.start_instance(config) for config in configs]
    await asyncio.gather(*tasks)
```

### 2. Graceful Shutdown
```python
async def shutdown_resources(manager):
    """Gracefully shutdown all resources"""
    # Stop accepting new requests
    manager.accepting_requests = False
    
    # Wait for active requests
    await manager.wait_for_active_requests(timeout=30)
    
    # Stop all hubs
    for hub in manager.hubs.values():
        await hub.stop()
```

### 3. Resource Limits
```python
# Enforce resource limits
hub = DockerHub(
    max_instances=10,
    max_cpu_per_instance=2.0,
    max_memory_per_instance="1GB",
    total_memory_limit="8GB"
)
```

### 4. Monitoring Integration
```python
# Export metrics to monitoring system
async def export_metrics(manager, prometheus_gateway):
    while True:
        metrics = await manager.get_global_metrics()
        await prometheus_gateway.push(metrics)
        await asyncio.sleep(60)
```

## Troubleshooting

### Instance Not Starting
```python
# Check hub status
status = await hub.get_status()
if status['instances'] >= status['max_instances']:
    print("Resource limit reached")

# Check specific instance logs
logs = await hub.get_instance_logs(instance_id)
print(logs)
```

### Health Check Failures
```python
# Manually check health
is_healthy = await hub.check_health(instance)
if not is_healthy:
    # Get detailed diagnostics
    diagnostics = await hub.diagnose_instance(instance_id)
    print(diagnostics)
```

### Resource Leaks
```python
# Find orphaned resources
orphaned = await hub.find_orphaned_resources()
for resource in orphaned:
    await hub.cleanup_orphaned(resource)
```

## Summary

The Resource Management system in Gleitzeit v0.0.5 provides:
- **Unified management** of diverse compute resources
- **Automatic health monitoring** and recovery
- **Flexible allocation strategies**
- **Comprehensive metrics** and monitoring
- **Resource pooling** and reuse
- **Clean separation** from business logic

This architecture ensures efficient resource utilization while maintaining reliability and performance.