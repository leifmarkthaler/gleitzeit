# Multi-Instance Ollama Management with Hub Architecture

## Table of Contents
1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Quick Start](#quick-start)
4. [Configuration](#configuration)
5. [Python API Usage](#python-api-usage)
6. [Health Monitoring & Metrics](#health-monitoring--metrics)
7. [Resource Management](#resource-management)
8. [Troubleshooting](#troubleshooting)

## Overview

**Note: This document has been updated to reflect the new Hub-Provider architecture in Gleitzeit V4.**

The Ollama Hub architecture provides:
- **Centralized management** of multiple Ollama instances
- **Automatic health monitoring** with configurable intervals
- **Resource lifecycle management** (start/stop/restart instances)
- **Metrics collection** for performance monitoring
- **Clean separation** between protocol execution (Provider) and resource management (Hub)

### Benefits

- **Simplified resource management**: Hub handles all Ollama instance lifecycle
- **Better reliability**: Automatic health checks and status tracking
- **Resource optimization**: Centralized metrics and monitoring
- **Clean architecture**: Providers focus on LLM execution, Hub manages resources

## Architecture

### Hub-Provider Separation

```
┌──────────────────────────────────────────────┐
│            ResourceManager                    │
│  (Orchestrates multiple resource hubs)        │
└────────────────┬─────────────────────────────┘
                 │
      ┌──────────┴──────────┐
      │                     │
┌─────▼──────┐     ┌────────▼────────┐
│ OllamaHub  │     │   DockerHub     │
│            │     │                 │
└─────┬──────┘     └────────┬────────┘
      │                     │
      │                     │
┌─────▼──────────────────────▼────────┐
│         OllamaProvider              │
│   (Handles LLM protocol execution)  │
└──────────────────────────────────────┘
```

### Key Components

1. **OllamaHub** (`hub/ollama_hub.py`)
   - Manages Ollama server instances
   - Monitors health and collects metrics
   - Handles instance lifecycle (start/stop/restart)

2. **OllamaProvider** (`providers/ollama_provider.py`)
   - Executes LLM protocol methods (chat, vision)
   - Uses healthy instances from OllamaHub
   - Focuses purely on protocol execution

3. **ResourceManager** (`hub/resource_manager.py`)
   - Orchestrates multiple hubs
   - Provides global resource view
   - Handles resource allocation

## Quick Start

### 1. Start Multiple Ollama Instances

```bash
# Instance 1 (default port)
ollama serve

# Instance 2 (custom port)
OLLAMA_HOST=127.0.0.1:11435 ollama serve

# Instance 3 (another custom port)
OLLAMA_HOST=127.0.0.1:11436 ollama serve
```

### 2. Using the Hub Architecture

```python
import asyncio
from gleitzeit.hub.ollama_hub import OllamaHub
from gleitzeit.hub.configs import OllamaConfig
from gleitzeit.providers.ollama_provider import OllamaProvider

async def main():
    # Create and initialize the hub
    hub = OllamaHub(hub_id="ollama-main")
    await hub.initialize()
    
    # Register Ollama instances
    configs = [
        OllamaConfig(host="127.0.0.1", port=11434),
        OllamaConfig(host="127.0.0.1", port=11435),
        OllamaConfig(host="127.0.0.1", port=11436)
    ]
    
    for config in configs:
        instance = await hub.start_instance(config)
        if instance:
            print(f"Started Ollama at {instance.endpoint}")
    
    # Create provider that uses the hub
    provider = OllamaProvider(
        provider_id="ollama-provider",
        ollama_hub=hub  # Provider uses hub for resource access
    )
    
    # Execute LLM tasks
    result = await provider.handle_request(
        method="chat",
        params={
            "model": "llama3.2",
            "messages": [
                {"role": "user", "content": "Hello, how are you?"}
            ]
        }
    )
    
    print(result["response"])
    
    # Cleanup
    await hub.cleanup()

asyncio.run(main())
```

## Configuration

### Hub Configuration

```python
from gleitzeit.hub.ollama_hub import OllamaHub

hub = OllamaHub(
    hub_id="ollama-hub",
    health_check_interval=30,  # Check health every 30 seconds
    max_health_failures=3,      # Mark unhealthy after 3 failures
    enable_auto_recovery=True,  # Auto-restart unhealthy instances
    enable_metrics=True,        # Collect performance metrics
    auto_discover=True          # Auto-discover running Ollama instances
)
```

### Instance Configuration

```python
from gleitzeit.hub.configs import OllamaConfig

config = OllamaConfig(
    host="127.0.0.1",
    port=11434,
    gpu_layers=35,           # Number of layers to offload to GPU
    cpu_threads=8,           # Number of CPU threads
    memory_limit="8GB",      # Memory limit
    environment={            # Environment variables
        "OLLAMA_NUM_PARALLEL": "4",
        "OLLAMA_MAX_LOADED_MODELS": "2"
    }
)
```

## Python API Usage

### Using with GleitzeitClient

```python
from gleitzeit import GleitzeitClient

async def main():
    async with GleitzeitClient() as client:
        # The client automatically manages hubs and providers
        result = await client.execute_task({
            "method": "llm/chat",
            "params": {
                "model": "llama3.2",
                "messages": [
                    {"role": "user", "content": "Explain quantum computing"}
                ]
            }
        })
        
        print(result["response"])
```

### Direct Hub Management

```python
from gleitzeit.hub.ollama_hub import OllamaHub
from gleitzeit.hub.base import ResourceStatus

async def manage_instances():
    hub = OllamaHub()
    await hub.initialize()
    
    # List all instances
    instances = await hub.list_instances()
    for instance in instances:
        print(f"{instance.id}: {instance.status.value}")
    
    # Get healthy instances only
    healthy = await hub.list_instances(status=ResourceStatus.HEALTHY)
    
    # Get specific instance
    instance = await hub.get_instance("ollama-127-0-0-1-11434")
    
    # Check health
    is_healthy = await hub.health_check(instance.id)
    
    # Restart an instance
    await hub.restart_instance(instance.id)
    
    # Stop an instance
    await hub.stop_instance(instance.id)
```

## Health Monitoring & Metrics

### Automatic Health Monitoring

The hub automatically monitors instance health:

```python
# Health check happens automatically based on interval
hub = OllamaHub(health_check_interval=30)  # Every 30 seconds

# Manual health check
metrics = await hub.check_resource_health(instance)
print(f"CPU: {metrics.cpu_percent}%")
print(f"Memory: {metrics.memory_mb}MB")
print(f"Status: {instance.status.value}")
```

### Metrics Collection

```python
# Get hub status and statistics
status = await hub.get_status()
print(f"Total instances: {status['instances']['total']}")
print(f"Healthy: {status['instances']['healthy']}")
print(f"Unhealthy: {status['instances']['unhealthy']}")

# Get metrics summary
metrics = await hub.get_metrics_summary()
print(f"Total CPU: {metrics['aggregate']['total_cpu_percent']}%")
print(f"Total Memory: {metrics['aggregate']['total_memory_mb']}MB")
```

## Resource Management

### With ResourceManager

```python
from gleitzeit.hub.resource_manager import ResourceManager
from gleitzeit.hub.ollama_hub import OllamaHub
from gleitzeit.hub.docker_hub import DockerHub

async def setup_resource_management():
    # Create resource manager
    manager = ResourceManager()
    
    # Add hubs
    ollama_hub = OllamaHub()
    docker_hub = DockerHub()
    
    await manager.add_hub("ollama", ollama_hub)
    await manager.add_hub("docker", docker_hub)
    
    # Start all hubs
    await manager.start()
    
    # Get global view
    metrics = await manager.get_global_metrics()
    print(f"Total resources: {metrics['total_resources']}")
    
    # Allocate resources
    instance = await manager.allocate_resource(
        ResourceType.OLLAMA,
        allocation_id="task-123"
    )
    
    # Release when done
    await manager.release_allocation("task-123")
    
    # Cleanup
    await manager.stop()
```

## Troubleshooting

### Common Issues

1. **Instances not discovered**
   ```python
   # Enable auto-discovery
   hub = OllamaHub(auto_discover=True)
   
   # Or manually register
   config = OllamaConfig(host="127.0.0.1", port=11434)
   instance = await hub.create_resource(config)
   ```

2. **Health check failures**
   ```python
   # Check logs
   import logging
   logging.basicConfig(level=logging.DEBUG)
   
   # Increase timeout
   hub = OllamaHub(
       health_check_interval=60,
       max_health_failures=5
   )
   ```

3. **Port conflicts**
   ```bash
   # Check what's using the port
   lsof -i :11434
   
   # Use different ports
   OLLAMA_HOST=127.0.0.1:11435 ollama serve
   ```

### Monitoring Hub Events

```python
# Register event handlers
def on_instance_registered(data):
    print(f"New instance: {data['id']}")

def on_status_changed(data):
    print(f"Status change: {data['instance_id']} -> {data['new_status']}")

hub.on_event('instance_registered', on_instance_registered)
hub.on_event('status_changed', on_status_changed)
```

## Migration from Old Architecture

If you were using the old `OllamaPoolProvider` (which no longer exists), here's how to migrate:

### Old Code (No longer works)
```python
# This class doesn't exist anymore
from gleitzeit.providers.ollama_pool_provider import OllamaPoolProvider
provider = OllamaPoolProvider(...)
```

### New Code (Use Hub architecture)
```python
from gleitzeit.hub.ollama_hub import OllamaHub
from gleitzeit.providers.ollama_provider import OllamaProvider

# Create hub for resource management
hub = OllamaHub()
await hub.initialize()

# Create provider for protocol execution
provider = OllamaProvider(
    provider_id="ollama",
    ollama_hub=hub
)
```

## Architecture Benefits

The new hub-provider separation provides:

1. **Clear separation of concerns**
   - Hubs manage resources (lifecycle, health, metrics)
   - Providers execute protocols (LLM operations)

2. **Better resource management**
   - Centralized health monitoring
   - Automatic recovery mechanisms
   - Comprehensive metrics collection

3. **Improved reliability**
   - Persistent resource tracking
   - Graceful degradation
   - Event-driven architecture

4. **Easier testing**
   - Hubs and providers can be tested independently
   - Mock hubs for provider testing
   - Mock providers for hub testing

## See Also

- [Unified Persistence Architecture](UNIFIED_PERSISTENCE_ARCHITECTURE.md)
- [Provider Implementation Guide](PROVIDER_IMPLEMENTATION_GUIDE.md)
- [Resource Manager Documentation](../src/gleitzeit/hub/resource_manager.py)
- [OllamaHub Source](../src/gleitzeit/hub/ollama_hub.py)