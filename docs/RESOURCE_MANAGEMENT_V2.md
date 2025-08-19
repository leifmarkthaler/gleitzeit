# Resource Management Documentation (client_v2)

## Table of Contents
- [Overview](#overview)
- [Architecture](#architecture)
- [Getting Started](#getting-started)
- [Core Concepts](#core-concepts)
- [API Reference](#api-reference)
- [Allocation Strategies](#allocation-strategies)
- [Auto-Scaling](#auto-scaling)
- [Monitoring & Metrics](#monitoring--metrics)
- [Examples](#examples)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

## Overview

The Resource Management system in Gleitzeit client_v2 provides intelligent orchestration of external compute resources like Ollama instances, Docker containers, and other services. It enables efficient resource pooling, automatic scaling, and intelligent task routing.

### Key Benefits

- **Resource Efficiency**: Share expensive resources (LLM servers, GPUs) across multiple tasks
- **Automatic Scaling**: Scale resources up/down based on demand
- **Load Balancing**: Distribute tasks across multiple instances
- **Health Monitoring**: Track resource health and automatically handle failures
- **Cost Optimization**: Minimize resource usage while meeting performance requirements

### When to Use Resource Management

Resource management is beneficial when:
- Running multiple Ollama instances for load distribution
- Managing Docker containers for isolated Python execution
- Sharing GPU resources across tasks
- Operating in cloud environments with auto-scaling needs
- Running production workloads with high availability requirements

## Architecture

```
┌─────────────────────────────────────────────┐
│              Client (client_v2)              │
│         (Entry point for users)              │
└─────────────────┬───────────────────────────┘
                  │
┌─────────────────▼───────────────────────────┐
│           ResourceManager                    │
│    (High-level management interface)         │
└─────────────────┬───────────────────────────┘
                  │
┌─────────────────▼───────────────────────────┐
│          ResourceAllocator                   │
│   (Intelligent routing & queuing)            │
└─────────────────┬───────────────────────────┘
                  │
        ┌─────────┴─────────┬─────────────┐
        │                   │             │
┌───────▼──────┐  ┌────────▼──────┐  ┌───▼────┐
│ResourcePool 1│  │ResourcePool 2 │  │Pool N  │
│  (Ollama)    │  │   (Docker)    │  │  ...   │
└───────┬──────┘  └────────┬──────┘  └───┬────┘
        │                   │             │
┌───────▼──────────────────▼─────────────▼────┐
│          Resource Instances                  │
│   (Actual Ollama servers, containers, etc.)  │
└──────────────────────────────────────────────┘
```

### Components

1. **ResourceManager**: High-level interface for resource operations
2. **ResourceAllocator**: Handles allocation logic, queuing, and routing
3. **ResourcePool**: Manages a collection of similar resources
4. **ResourceInstance**: Represents an individual resource (e.g., one Ollama server)

## Getting Started

### Installation

Resource management is included in Gleitzeit v0.0.4+. No additional installation required.

### Basic Setup

```python
import asyncio
from gleitzeit import Client

async def main():
    # Enable resource management in client configuration
    async with Client(
        mode="native",
        native_config={
            'enable_resource_management': True
        }
    ) as client:
        # Resource management is now available
        await setup_resources(client)

async def setup_resources(client):
    # Create a resource pool
    await client.create_resource_pool(
        pool_id="ollama-pool",
        resource_type="ollama",
        min_instances=1,
        max_instances=5
    )
    
    # Register resource instances
    await client.register_resource(
        pool_id="ollama-pool",
        instance_id="ollama-1",
        endpoint="http://localhost:11434",
        capabilities=["llama3.2", "codellama"]
    )

asyncio.run(main())
```

## Core Concepts

### Resource Types

Gleitzeit supports several resource types:

| Type | Description | Use Cases |
|------|-------------|-----------|
| `ollama` | Ollama LLM servers | Text generation, code completion |
| `docker` | Docker containers | Isolated Python execution |
| `python` | Python interpreters | Script execution |
| `gpu` | GPU resources | ML model inference |
| `custom` | User-defined resources | Any external service |

### Resource Instance

A resource instance represents a single deployable unit:

```python
ResourceInstance(
    id="ollama-1",                        # Unique identifier
    resource_type=ResourceType.OLLAMA,    # Type of resource
    endpoint="http://localhost:11434",    # Connection endpoint
    status=ResourceStatus.AVAILABLE,      # Current status
    capabilities={"llama3.2", "codellama"}, # What it can do
    max_concurrent_tasks=3,               # Concurrency limit
    available_memory_mb=8192,             # Memory available
    available_cpu_cores=4                 # CPU cores
)
```

### Resource Pool

A pool manages multiple instances of the same resource type:

```python
ResourcePool(
    pool_id="ollama-pool",
    resource_type=ResourceType.OLLAMA,
    min_instances=1,    # Minimum instances to maintain
    max_instances=10,   # Maximum instances allowed
    health_check_interval=30  # Health check frequency (seconds)
)
```

### Resource Requirements

Tasks can specify their resource needs:

```python
ResourceRequirements(
    resource_type=ResourceType.OLLAMA,
    capabilities={"llama3.2"},  # Required capabilities
    min_memory_mb=4096,         # Minimum memory needed
    min_cpu_cores=2,            # Minimum CPU cores
    exclusive=False,            # Need exclusive access?
    timeout_seconds=30          # Max wait time
)
```

## API Reference

### Client Methods

#### create_resource_pool

Create a new resource pool.

```python
await client.create_resource_pool(
    pool_id: str,                    # Unique pool identifier
    resource_type: str,              # "ollama", "docker", etc.
    min_instances: int = 0,          # Minimum instances
    max_instances: int = 10,         # Maximum instances
    endpoints: List[str] = None      # Initial endpoints
) -> bool
```

**Example:**
```python
success = await client.create_resource_pool(
    pool_id="llm-pool",
    resource_type="ollama",
    min_instances=2,
    max_instances=10,
    endpoints=["http://localhost:11434", "http://localhost:11435"]
)
```

#### register_resource

Register a resource instance with a pool.

```python
await client.register_resource(
    pool_id: str,                    # Target pool ID
    instance_id: str,                # Unique instance ID
    endpoint: str,                   # Connection endpoint
    resource_type: str = "ollama",   # Resource type
    capabilities: List[str] = None,  # Instance capabilities
    max_concurrent: int = 3          # Max concurrent tasks
) -> bool
```

**Example:**
```python
registered = await client.register_resource(
    pool_id="llm-pool",
    instance_id="ollama-gpu-1",
    endpoint="http://gpu-server:11434",
    capabilities=["llama3.2", "llava", "codellama"],
    max_concurrent=5
)
```

#### allocate_resource

Allocate a resource for a task.

```python
await client.allocate_resource(
    task_id: str,                    # Task requiring resource
    resource_type: str,              # Type of resource needed
    capabilities: List[str] = None,  # Required capabilities
    strategy: str = "least_loaded"   # Allocation strategy
) -> Optional[Dict[str, Any]]
```

**Example:**
```python
resource = await client.allocate_resource(
    task_id="analysis-task-123",
    resource_type="ollama",
    capabilities=["llama3.2"],
    strategy="least_loaded"
)

if resource:
    print(f"Allocated: {resource['id']}")
    print(f"Endpoint: {resource['endpoint']}")
    print(f"Status: {resource['status']}")
```

#### release_resource

Release a resource allocated to a task.

```python
await client.release_resource(
    task_id: str                     # Task ID
) -> bool
```

**Example:**
```python
released = await client.release_resource("analysis-task-123")
```

#### get_resource_metrics

Get resource management metrics.

```python
await client.get_resource_metrics() -> Dict[str, Any]
```

**Example:**
```python
metrics = await client.get_resource_metrics()
print(f"Total instances: {metrics['allocator']['total_instances']}")
print(f"Available: {metrics['allocator']['available_instances']}")
print(f"Active allocations: {metrics['allocator']['active_allocations']}")
```

#### enable_auto_scaling

Enable automatic scaling for resource pools.

```python
await client.enable_auto_scaling(
    scale_up_threshold: float = 0.8,   # Scale up at 80% utilization
    scale_down_threshold: float = 0.2  # Scale down at 20% utilization
) -> None
```

**Example:**
```python
await client.enable_auto_scaling(
    scale_up_threshold=0.75,
    scale_down_threshold=0.25
)
```

## Allocation Strategies

The system supports multiple allocation strategies:

### least_loaded (Default)
Selects the instance with the fewest active tasks.

```python
resource = await client.allocate_resource(
    task_id="task-1",
    resource_type="ollama",
    strategy="least_loaded"
)
```

### best_fit
Scores instances based on how well they match requirements.

```python
resource = await client.allocate_resource(
    task_id="task-2",
    resource_type="ollama",
    capabilities=["llama3.2", "gpu"],
    strategy="best_fit"
)
```

### round_robin
Cycles through available instances.

```python
resource = await client.allocate_resource(
    task_id="task-3",
    resource_type="ollama",
    strategy="round_robin"
)
```

### fastest
Selects the instance with the lowest average response time.

```python
resource = await client.allocate_resource(
    task_id="task-4",
    resource_type="ollama",
    strategy="fastest"
)
```

### random
Random selection from available instances.

```python
resource = await client.allocate_resource(
    task_id="task-5",
    resource_type="ollama",
    strategy="random"
)
```

## Auto-Scaling

Auto-scaling automatically adjusts the number of resource instances based on utilization.

### Configuration

```python
await client.enable_auto_scaling(
    scale_up_threshold=0.8,    # Scale up when 80% utilized
    scale_down_threshold=0.2   # Scale down when 20% utilized
)
```

### How It Works

1. **Monitoring**: System checks utilization every 30 seconds
2. **Scale Up**: When utilization > threshold, adds instances (up to max)
3. **Scale Down**: When utilization < threshold, removes instances (down to min)
4. **Protection**: Won't remove instances with active tasks

### Example Scenario

```python
# Create pool with auto-scaling bounds
await client.create_resource_pool(
    pool_id="elastic-pool",
    resource_type="ollama",
    min_instances=2,    # Never go below 2
    max_instances=10    # Never exceed 10
)

# Enable auto-scaling
await client.enable_auto_scaling(
    scale_up_threshold=0.7,    # Add instances at 70% load
    scale_down_threshold=0.3   # Remove instances at 30% load
)

# As load increases, pool automatically scales
# 2 instances -> 3 -> 4 -> ... -> 10 (max)
# As load decreases, pool scales down
# 10 instances -> 9 -> ... -> 2 (min)
```

## Monitoring & Metrics

### Getting Metrics

```python
metrics = await client.get_resource_metrics()
```

### Metrics Structure

```json
{
  "manager_id": "default",
  "running": true,
  "auto_scaling": true,
  "allocator": {
    "pools": 2,
    "total_instances": 5,
    "available_instances": 3,
    "active_allocations": 2,
    "pending_requests": 0,
    "stats": {
      "total_allocations": 150,
      "successful_allocations": 148,
      "failed_allocations": 2,
      "avg_wait_time_ms": 125.5,
      "allocations_by_pool": {
        "ollama-pool": 100,
        "docker-pool": 50
      }
    },
    "pool_metrics": {
      "ollama-pool": {
        "instances": {
          "total": 3,
          "available": 2,
          "busy": 1,
          "failed": 0
        },
        "requests": {
          "total": 1000,
          "active": 5,
          "failed": 10,
          "error_rate": 1.0
        }
      }
    }
  }
}
```

### Health Monitoring

The system performs automatic health checks:

```python
# Health check results
health = await client.get_health()
# Returns resource health status along with other components
```

## Examples

### Example 1: Multi-Model Ollama Setup

```python
async def setup_multi_model_ollama(client):
    """Setup multiple Ollama instances with different models"""
    
    # Create pool
    await client.create_resource_pool(
        pool_id="multi-model-pool",
        resource_type="ollama",
        min_instances=3,
        max_instances=10
    )
    
    # Register instance with vision models
    await client.register_resource(
        pool_id="multi-model-pool",
        instance_id="vision-server",
        endpoint="http://vision:11434",
        capabilities=["llava", "bakllava"],
        max_concurrent=2
    )
    
    # Register instance with code models
    await client.register_resource(
        pool_id="multi-model-pool",
        instance_id="code-server",
        endpoint="http://code:11434",
        capabilities=["codellama", "deepseek-coder"],
        max_concurrent=3
    )
    
    # Register instance with general models
    await client.register_resource(
        pool_id="multi-model-pool",
        instance_id="general-server",
        endpoint="http://general:11434",
        capabilities=["llama3.2", "mistral", "mixtral"],
        max_concurrent=5
    )
    
    # Enable auto-scaling
    await client.enable_auto_scaling()
```

### Example 2: Task with Resource Requirements

```python
async def run_task_with_resources(client):
    """Submit a task that requires specific resources"""
    
    # Allocate resource first
    resource = await client.allocate_resource(
        task_id="code-review-001",
        resource_type="ollama",
        capabilities=["codellama"],
        strategy="best_fit"
    )
    
    if not resource:
        print("No suitable resource available")
        return
    
    try:
        # Submit task using allocated resource
        task = await client.submit_task(
            name="Code Review",
            protocol="llm/v1",
            method="chat",
            params={
                "model": "codellama",
                "messages": [
                    {"role": "user", "content": "Review this code: ..."}
                ],
                # Could pass resource endpoint to provider
                "_resource_endpoint": resource['endpoint']
            }
        )
        
        # Wait for completion
        result = await client.wait_for_task(task.id)
        return result
        
    finally:
        # Always release resource
        await client.release_resource("code-review-001")
```

### Example 3: Batch Processing with Resource Pool

```python
async def batch_process_with_pool(client, documents):
    """Process multiple documents using resource pool"""
    
    # Setup pool for batch processing
    await client.create_resource_pool(
        pool_id="batch-pool",
        resource_type="ollama",
        min_instances=3,
        max_instances=10,
        endpoints=[
            "http://localhost:11434",
            "http://localhost:11435",
            "http://localhost:11436"
        ]
    )
    
    # Enable auto-scaling for dynamic load
    await client.enable_auto_scaling(
        scale_up_threshold=0.7,
        scale_down_threshold=0.3
    )
    
    # Process documents in parallel
    tasks = []
    for i, doc in enumerate(documents):
        # Allocate resource for each document
        resource = await client.allocate_resource(
            task_id=f"doc-{i}",
            resource_type="ollama",
            strategy="least_loaded"
        )
        
        if resource:
            task = process_document(client, doc, f"doc-{i}")
            tasks.append(task)
    
    # Wait for all to complete
    results = await asyncio.gather(*tasks)
    
    # Release all resources
    for i in range(len(documents)):
        await client.release_resource(f"doc-{i}")
    
    return results
```

### Example 4: Monitoring Resource Usage

```python
async def monitor_resources(client):
    """Monitor resource usage over time"""
    
    while True:
        metrics = await client.get_resource_metrics()
        
        if metrics and "allocator" in metrics:
            alloc = metrics["allocator"]
            
            # Overall stats
            print(f"\n=== Resource Status ===")
            print(f"Total Instances: {alloc['total_instances']}")
            print(f"Available: {alloc['available_instances']}")
            print(f"Active Allocations: {alloc['active_allocations']}")
            print(f"Pending Requests: {alloc['pending_requests']}")
            
            # Per-pool stats
            for pool_id, pool_metrics in alloc.get("pool_metrics", {}).items():
                instances = pool_metrics["instances"]
                requests = pool_metrics["requests"]
                
                utilization = 0
                if instances["total"] > 0:
                    utilization = (instances["busy"] / instances["total"]) * 100
                
                print(f"\nPool: {pool_id}")
                print(f"  Utilization: {utilization:.1f}%")
                print(f"  Error Rate: {requests['error_rate']:.2f}%")
                print(f"  Active Requests: {requests['active']}")
        
        await asyncio.sleep(10)  # Check every 10 seconds
```

## Best Practices

### 1. Resource Pool Design

```python
# ✅ Good: Separate pools for different workloads
await client.create_resource_pool(
    pool_id="interactive-pool",
    resource_type="ollama",
    min_instances=2,  # Always have 2 ready
    max_instances=5   # Limit for interactive
)

await client.create_resource_pool(
    pool_id="batch-pool",
    resource_type="ollama",
    min_instances=0,  # Can scale to zero
    max_instances=20  # Allow heavy scaling for batch
)

# ❌ Bad: One pool for everything
await client.create_resource_pool(
    pool_id="everything-pool",
    resource_type="ollama",
    min_instances=1,
    max_instances=100  # Too broad
)
```

### 2. Resource Allocation

```python
# ✅ Good: Always release resources
resource = await client.allocate_resource(task_id="task-1", resource_type="ollama")
try:
    # Use resource
    result = await process_with_resource(resource)
finally:
    await client.release_resource("task-1")

# ❌ Bad: Forgetting to release
resource = await client.allocate_resource(task_id="task-2", resource_type="ollama")
result = await process_with_resource(resource)
# Resource leaked!
```

### 3. Capability Management

```python
# ✅ Good: Specific capability requirements
resource = await client.allocate_resource(
    task_id="vision-task",
    resource_type="ollama",
    capabilities=["llava"],  # Specific model needed
    strategy="best_fit"
)

# ❌ Bad: No capability specification
resource = await client.allocate_resource(
    task_id="vision-task",
    resource_type="ollama"
    # Might get instance without vision model
)
```

### 4. Auto-Scaling Configuration

```python
# ✅ Good: Reasonable thresholds with buffer
await client.enable_auto_scaling(
    scale_up_threshold=0.7,    # Scale before hitting limit
    scale_down_threshold=0.3   # Keep some buffer
)

# ❌ Bad: Too aggressive
await client.enable_auto_scaling(
    scale_up_threshold=0.95,   # Too late
    scale_down_threshold=0.05  # Too aggressive
)
```

### 5. Error Handling

```python
# ✅ Good: Handle allocation failures
resource = await client.allocate_resource(
    task_id="critical-task",
    resource_type="ollama",
    strategy="least_loaded"
)

if not resource:
    # Handle gracefully
    logger.warning("No resource available, queuing task")
    await queue_for_later("critical-task")
else:
    await process_with_resource(resource)

# ❌ Bad: Assume allocation succeeds
resource = await client.allocate_resource(...)
await process_with_resource(resource)  # May fail if resource is None
```

## Troubleshooting

### Common Issues

#### 1. Resource Allocation Fails

**Symptom:** `allocate_resource` returns `None`

**Possible Causes:**
- No instances registered in pool
- All instances are busy
- No instance matches requirements

**Solution:**
```python
# Check metrics to diagnose
metrics = await client.get_resource_metrics()
print(f"Available instances: {metrics['allocator']['available_instances']}")

# Check pool status
for pool_id, pool_metrics in metrics['allocator']['pool_metrics'].items():
    print(f"Pool {pool_id}: {pool_metrics['instances']}")
```

#### 2. Auto-Scaling Not Working

**Symptom:** Pools don't scale despite load

**Possible Causes:**
- Auto-scaling not enabled
- Already at min/max limits
- Thresholds not being met

**Solution:**
```python
# Verify auto-scaling is enabled
metrics = await client.get_resource_metrics()
print(f"Auto-scaling enabled: {metrics['auto_scaling']}")

# Check pool limits
# Ensure min < current < max for scaling to work
```

#### 3. Resources Not Released

**Symptom:** Resources remain busy after task completion

**Possible Causes:**
- Forgot to call `release_resource`
- Task ID mismatch
- Exception prevented release

**Solution:**
```python
# Always use try/finally
resource = await client.allocate_resource(task_id="task-1", ...)
try:
    await do_work(resource)
finally:
    await client.release_resource("task-1")
```

#### 4. High Error Rate

**Symptom:** High error rate in metrics

**Possible Causes:**
- Instances are unhealthy
- Network connectivity issues
- Resource overload

**Solution:**
```python
# Check instance health
metrics = await client.get_resource_metrics()
for pool_id, pool_metrics in metrics['allocator']['pool_metrics'].items():
    error_rate = pool_metrics['requests']['error_rate']
    if error_rate > 5.0:  # 5% threshold
        print(f"High error rate in {pool_id}: {error_rate}%")
        # Consider removing/replacing instances
```

### Debug Logging

Enable debug logging for detailed information:

```python
import logging

# Enable debug logging for resource management
logging.getLogger("gleitzeit.resources").setLevel(logging.DEBUG)
logging.getLogger("gleitzeit.client_v2").setLevel(logging.DEBUG)
```

### Resource State Inspection

```python
async def inspect_resources(client):
    """Detailed resource inspection"""
    metrics = await client.get_resource_metrics()
    
    print("=== Resource State ===")
    print(json.dumps(metrics, indent=2))
    
    # Check specific allocations
    if "allocator" in metrics:
        allocator = metrics["allocator"]
        print(f"\nActive Allocations: {allocator['active_allocations']}")
        print(f"Pending Requests: {allocator['pending_requests']}")
        
        # Check allocation history
        stats = allocator.get("stats", {})
        success_rate = 0
        if stats['total_allocations'] > 0:
            success_rate = (stats['successful_allocations'] / 
                          stats['total_allocations']) * 100
        print(f"Allocation Success Rate: {success_rate:.1f}%")
```

## Performance Considerations

### Resource Pool Sizing

- **Min Instances**: Set based on baseline load
- **Max Instances**: Set based on peak load and cost constraints
- **Health Check Interval**: Balance between responsiveness and overhead (30s default)

### Allocation Strategy Performance

| Strategy | Performance | Best For |
|----------|------------|----------|
| least_loaded | O(n) | General use, load balancing |
| best_fit | O(n * m) | Complex requirements |
| round_robin | O(1) | Even distribution |
| fastest | O(n) | Latency-sensitive tasks |
| random | O(1) | Simple scenarios |

### Memory and CPU Considerations

```python
# Configure instances with accurate resource limits
await client.register_resource(
    pool_id="gpu-pool",
    instance_id="gpu-1",
    endpoint="http://gpu-server:11434",
    capabilities=["llama3.2-70b"],
    max_concurrent=1  # Large model, limit concurrency
)
```

## Migration Guide

### From Old Client to client_v2

If you're migrating from the old resource management system:

```python
# Old way (original client)
async with GleitzeitClient() as client:
    await client.register_resource(
        hub_id="ollama-hub",
        instance_id="ollama-1",
        instance_data={...}
    )

# New way (client_v2)
async with Client(
    mode="native",
    native_config={'enable_resource_management': True}
) as client:
    await client.create_resource_pool(
        pool_id="ollama-pool",
        resource_type="ollama"
    )
    await client.register_resource(
        pool_id="ollama-pool",
        instance_id="ollama-1",
        endpoint="http://localhost:11434"
    )
```

### Key Differences

1. **Simplified API**: Fewer parameters, clearer methods
2. **Pool-Centric**: Resources organized in pools
3. **Strategy-Based**: Multiple allocation strategies
4. **Integrated Auto-Scaling**: Built-in scaling support
5. **Better Metrics**: More detailed metrics and monitoring

## Future Enhancements

Planned improvements for resource management:

1. **Resource Priorities**: Task-level priority for resource allocation
2. **Cost Optimization**: Track and optimize resource costs
3. **Predictive Scaling**: Scale based on historical patterns
4. **Resource Affinity**: Prefer certain resources for specific tasks
5. **Cross-Region Support**: Manage resources across regions
6. **Resource Templates**: Pre-defined resource configurations
7. **Webhook Support**: Notifications for resource events

## Support

For issues or questions about resource management:

1. Check the [troubleshooting section](#troubleshooting)
2. Review [examples](../examples/resource_management_example.py)
3. Open an issue on [GitHub](https://github.com/leifmarkthaler/gleitzeit/issues)
4. Check the [CLAUDE.md](../CLAUDE.md) for additional context

---

*Last updated: 2024*
*Version: 0.0.4*