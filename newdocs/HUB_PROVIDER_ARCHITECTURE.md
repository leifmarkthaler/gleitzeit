# Hub-Provider Architecture

## Overview

Gleitzeit v0.0.5 introduces a clean architectural separation between **Providers** (protocol execution) and **Hubs** (resource management). This design pattern provides better modularity, testability, and resource management.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────┐
│                  Workflow Task                      │
│              (e.g., "llm/chat")                     │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│                   Provider                          │
│         (Protocol Method Execution)                 │
│                                                     │
│  • Receives task from ExecutionEngine              │
│  • Validates parameters                            │
│  • Requests resources from Hub                     │
│  • Executes protocol method                        │
│  • Returns results                                 │
└────────────────────┬────────────────────────────────┘
                     │ Requests Resources
┌────────────────────▼────────────────────────────────┐
│                     Hub                             │
│           (Resource Management)                     │
│                                                     │
│  • Manages resource lifecycle                      │
│  • Monitors health                                 │
│  • Collects metrics                                │
│  • Handles allocation                              │
│  • Provides instances to providers                 │
└──────────────────────────────────────────────────────┘
```

## Key Concepts

### Providers
**Purpose**: Execute protocol methods
**Focus**: Business logic, protocol compliance, result formatting
**Examples**: OllamaProvider, PythonProvider, SimpleMCPProvider

### Hubs
**Purpose**: Manage compute resources
**Focus**: Lifecycle, health, metrics, allocation
**Examples**: OllamaHub, DockerHub

### ResourceManager
**Purpose**: Orchestrate multiple hubs
**Focus**: Global resource view, cross-hub operations

## Implementation Examples

### Provider Implementation

```python
from gleitzeit.providers.base import ProtocolProvider
from gleitzeit.hub.ollama_hub import OllamaHub

class OllamaProvider(ProtocolProvider):
    """Provider for LLM operations using Ollama"""
    
    def __init__(self, provider_id: str, ollama_hub: OllamaHub):
        super().__init__(
            provider_id=provider_id,
            protocol_id="llm/v1",
            name="Ollama LLM Provider"
        )
        self.hub = ollama_hub  # Hub dependency injection
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Execute LLM method using hub resources"""
        
        # Get available Ollama instance from hub
        instance = await self.hub.get_available_instance()
        if not instance:
            raise RuntimeError("No Ollama instances available")
        
        # Execute method using instance endpoint
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{instance.endpoint}/api/generate",
                json={
                    "model": params["model"],
                    "prompt": params.get("prompt", "")
                }
            ) as response:
                result = await response.json()
        
        # Return standardized result
        return {
            "response": result["response"],
            "model": params["model"],
            "provider_id": self.provider_id
        }
```

### Hub Implementation

```python
from gleitzeit.hub.base import ResourceHub, ResourceInstance, ResourceStatus
from gleitzeit.hub.configs import OllamaConfig

class OllamaHub(ResourceHub[OllamaConfig]):
    """Hub for managing Ollama server instances"""
    
    def __init__(self, hub_id: str = "ollama-hub"):
        super().__init__(
            hub_id=hub_id,
            resource_type=ResourceType.OLLAMA,
            health_check_interval=30,
            enable_auto_recovery=True
        )
        self.session = None
    
    async def check_health(self, instance: ResourceInstance) -> bool:
        """Check if Ollama instance is healthy"""
        try:
            async with self.session.get(
                f"{instance.endpoint}/api/tags",
                timeout=5
            ) as response:
                return response.status == 200
        except:
            return False
    
    async def start_instance(self, config: OllamaConfig) -> ResourceInstance:
        """Start a new Ollama instance"""
        # Start Ollama process or connect to existing
        process = await self._start_ollama_process(config)
        
        # Create resource instance
        instance = ResourceInstance(
            id=f"ollama-{config.host}-{config.port}",
            name=f"Ollama@{config.port}",
            type=ResourceType.OLLAMA,
            endpoint=f"http://{config.host}:{config.port}",
            status=ResourceStatus.STARTING,
            config=config
        )
        
        # Register and wait for health
        await self.register_instance_object(instance)
        await self._wait_for_ready(instance)
        
        return instance
```

## Separation of Concerns

### What Providers Handle
- Protocol method execution
- Parameter validation
- Request/response formatting
- Protocol-specific logic
- Error handling for protocol operations

### What Providers DON'T Handle
- ❌ Resource lifecycle (starting/stopping servers)
- ❌ Health monitoring
- ❌ Metrics collection
- ❌ Resource allocation
- ❌ Connection pooling (except their own)

### What Hubs Handle
- Resource lifecycle management
- Health monitoring and checks
- Metrics collection
- Resource allocation strategies
- Instance pooling and reuse
- Auto-recovery of unhealthy instances

### What Hubs DON'T Handle
- ❌ Protocol execution
- ❌ Business logic
- ❌ Request validation
- ❌ Result formatting

## Benefits of Separation

### 1. Testability
```python
# Easy to test provider with mock hub
mock_hub = Mock()
mock_hub.get_available_instance.return_value = mock_instance
provider = OllamaProvider("test", mock_hub)
result = await provider.handle_request("chat", params)

# Easy to test hub without provider
hub = OllamaHub()
instance = await hub.start_instance(config)
assert await hub.check_health(instance)
```

### 2. Modularity
- Swap hub implementations without changing providers
- Add new providers without modifying hubs
- Mix and match components

### 3. Resource Sharing
```python
# Multiple providers can share the same hub
ollama_hub = OllamaHub()
chat_provider = ChatProvider("chat", ollama_hub)
embedding_provider = EmbeddingProvider("embed", ollama_hub)
```

### 4. Centralized Management
```python
# ResourceManager orchestrates all hubs
manager = ResourceManager()
await manager.add_hub("ollama", ollama_hub)
await manager.add_hub("docker", docker_hub)

# Global metrics across all resources
metrics = await manager.get_global_metrics()
```

## Complete Example

### Setting Up the Architecture

```python
import asyncio
from gleitzeit.hub.ollama_hub import OllamaHub
from gleitzeit.hub.docker_hub import DockerHub
from gleitzeit.hub.resource_manager import ResourceManager
from gleitzeit.providers.ollama_provider import OllamaProvider
from gleitzeit.providers.python_provider import PythonProvider
from gleitzeit.core.registry import ProtocolProviderRegistry

async def setup_system():
    # 1. Create hubs for resource management
    ollama_hub = OllamaHub(
        hub_id="ollama-main",
        health_check_interval=30,
        enable_auto_recovery=True
    )
    
    docker_hub = DockerHub(
        hub_id="docker-main",
        max_instances=10,
        enable_container_reuse=True
    )
    
    # 2. Initialize hubs
    await ollama_hub.initialize()
    await docker_hub.initialize()
    
    # 3. Create resource manager
    resource_manager = ResourceManager()
    await resource_manager.add_hub("ollama", ollama_hub)
    await resource_manager.add_hub("docker", docker_hub)
    
    # 4. Create providers using hubs
    ollama_provider = OllamaProvider(
        provider_id="ollama",
        ollama_hub=ollama_hub
    )
    
    python_provider = PythonProvider(
        provider_id="python",
        docker_hub=docker_hub
    )
    
    # 5. Register providers
    registry = ProtocolProviderRegistry()
    await registry.register_provider("llm/v1", ollama_provider)
    await registry.register_provider("python/v1", python_provider)
    
    return registry, resource_manager

# Usage
async def main():
    registry, manager = await setup_system()
    
    # Execute task using provider (which uses hub resources)
    provider = await registry.get_provider_for_method("llm/chat")
    result = await provider.execute("chat", {
        "model": "llama3.2",
        "messages": [{"role": "user", "content": "Hello"}]
    })
    
    # Check global resource status
    metrics = await manager.get_global_metrics()
    print(f"Total resources: {metrics['total_resources']}")
    
    # Cleanup
    await manager.stop()
```

## Migration from Old Architecture

### Old Pattern (v0.0.4)
```python
# Provider handled everything
class OllamaProvider:
    def __init__(self):
        self.instances = []  # Provider managed resources
        
    async def start_instance(self):
        # Provider started servers
        pass
    
    async def check_health(self):
        # Provider monitored health
        pass
    
    async def execute(self):
        # Provider executed methods
        pass
```

### New Pattern (v0.0.5)
```python
# Separated concerns
class OllamaProvider:
    def __init__(self, hub):
        self.hub = hub  # Hub manages resources
    
    async def execute(self):
        instance = await self.hub.get_available_instance()
        # Provider only executes methods
        pass

class OllamaHub:
    async def start_instance(self):
        # Hub manages lifecycle
        pass
    
    async def check_health(self):
        # Hub monitors health
        pass
```

## Best Practices

### 1. Dependency Injection
Always inject hubs into providers:
```python
# Good
provider = OllamaProvider(hub=ollama_hub)

# Bad
class OllamaProvider:
    def __init__(self):
        self.hub = OllamaHub()  # Creates tight coupling
```

### 2. Interface Compliance
Providers should only use hub's public interface:
```python
# Good
instance = await hub.get_available_instance()

# Bad
instance = hub.instances[0]  # Accessing internals
```

### 3. Error Handling
Handle resource unavailability gracefully:
```python
async def handle_request(self, method, params):
    instance = await self.hub.get_available_instance()
    if not instance:
        # Graceful degradation
        raise ServiceUnavailable("No instances available")
    
    try:
        return await self._execute(instance, method, params)
    except Exception as e:
        # Report to hub for metrics
        await self.hub.report_error(instance.id, e)
        raise
```

### 4. Resource Cleanup
Let hubs handle resource cleanup:
```python
# Provider shouldn't cleanup resources
async def shutdown(self):
    # Only cleanup provider's own resources
    if self.session:
        await self.session.close()
    # Don't touch hub resources
```

## Event System

Hubs emit events that can be monitored:

```python
def on_instance_registered(data):
    print(f"New instance: {data['id']}")

def on_health_check_failed(data):
    alert_admin(f"Instance {data['id']} is unhealthy")

hub.on_event('instance_registered', on_instance_registered)
hub.on_event('health_check_failed', on_health_check_failed)
```

## Metrics and Monitoring

### Provider Metrics
```python
# Providers track execution metrics
{
    "requests_processed": 1000,
    "average_latency_ms": 250,
    "errors": 10,
    "success_rate": 0.99
}
```

### Hub Metrics
```python
# Hubs track resource metrics
{
    "total_instances": 5,
    "healthy_instances": 4,
    "cpu_usage_percent": 45.2,
    "memory_usage_mb": 2048,
    "health_check_failures": 2
}
```

### Combined View
```python
# ResourceManager provides global view
metrics = await resource_manager.get_global_metrics()
# {
#     "total_resources": 10,
#     "by_type": {"ollama": 5, "docker": 5},
#     "by_status": {"healthy": 8, "unhealthy": 2},
#     "total_cpu_percent": 62.5
# }
```

## Summary

The Hub-Provider architecture provides:
- **Clean separation** of protocol execution from resource management
- **Better testability** through dependency injection
- **Resource sharing** across multiple providers
- **Centralized monitoring** and management
- **Flexibility** to swap implementations

This architecture is a key improvement in v0.0.5 that makes the system more maintainable, testable, and scalable.