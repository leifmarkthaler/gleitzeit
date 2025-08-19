# Resource Management Design in Gleitzeit

## 📋 Overview

Resource management was designed as a **distributed compute resource orchestration system** to manage external services (Ollama, Docker containers, etc.) that tasks depend on. Think of it as a "Kubernetes-lite" for LLM and compute resources.

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────┐
│                  ResourceManager                      │
│  (Central orchestrator for all resource types)        │
└─────────────┬────────────────┬──────────────────────┘
              │                │
      ┌───────▼──────┐  ┌──────▼──────┐
      │  OllamaHub   │  │  DockerHub  │
      │              │  │             │
      └───────┬──────┘  └──────┬──────┘
              │                │
      ┌───────▼──────────────────▼──────┐
      │     ResourceInstances            │
      │  (Actual Ollama/Docker instances)│
      └──────────────────────────────────┘
```

## 🎯 Purpose & Goals

### What it was meant to solve:
1. **Resource Pooling** - Share expensive resources (LLM servers) across tasks
2. **Auto-scaling** - Start/stop Ollama instances based on demand
3. **Load Balancing** - Distribute tasks across multiple Ollama instances
4. **Health Monitoring** - Track resource health and auto-restart failed instances
5. **Resource Limits** - Enforce CPU/memory limits per resource
6. **Multi-tenancy** - Isolate resources between different workflows

## 🔧 Core Components

### 1. **ResourceInstance** (`hub/base.py`)
```python
@dataclass
class ResourceInstance:
    id: str                    # Unique identifier
    type: ResourceType         # OLLAMA, DOCKER, etc.
    endpoint: str             # URL to connect to
    status: ResourceStatus    # HEALTHY, DEGRADED, etc.
    metrics: ResourceMetrics  # CPU, memory, requests
    capabilities: Set[str]    # What it can do
```

### 2. **ResourceHub** (Base class)
- Manages lifecycle of specific resource type
- Handles health checks
- Collects metrics
- Implements auto-scaling

### 3. **OllamaHub** (`hub/ollama_hub.py`)
Specific implementation for Ollama:
- Auto-discovers Ollama instances
- Manages model loading/unloading
- Routes requests to appropriate instance
- Handles model-specific routing

### 4. **ResourceManager** (`hub/resource_manager.py`)
Central orchestrator:
```python
class ResourceManager:
    async def allocate_resource(request) -> ResourceInstance
    async def release_resource(instance_id)
    async def get_metrics(hub_id) -> ResourceMetrics
```

## 🔄 How It Was Supposed to Work

### Task Execution Flow:
```
1. Task submitted: "Generate text with llama3.2"
   ↓
2. Provider requests resource from OllamaHub
   ↓
3. OllamaHub finds/starts Ollama instance with llama3.2
   ↓
4. Returns endpoint (e.g., http://localhost:11434)
   ↓
5. Provider executes task on that instance
   ↓
6. Metrics collected, resource released
```

### Example Usage:
```python
# In old client
async with GleitzeitClient() as client:
    # Register an Ollama instance
    await client.register_resource(
        hub_id="ollama-hub",
        instance_id="ollama-1",
        instance_data={
            "endpoint": "http://localhost:11434",
            "models": ["llama3.2", "codellama"],
            "max_concurrent": 5
        }
    )
    
    # Submit task - would automatically use registered resource
    task = await client.submit_task(
        name="Generate",
        protocol="llm/v1",
        method="chat",
        params={"model": "llama3.2", "prompt": "..."}
    )
    
    # Get metrics for the resource
    metrics = await client.get_resource_metrics("ollama-1")
    print(f"CPU: {metrics['cpu_percent']}%")
```

## 🚧 Implementation Status

### What was built:
✅ Base classes (ResourceInstance, ResourceHub, ResourceMetrics)
✅ OllamaHub implementation
✅ DockerHub stub
✅ ResourceManager orchestrator
✅ Persistence layer support
✅ Basic health checking
✅ Metrics collection

### What was NOT completed:
❌ Auto-scaling logic
❌ Load balancing algorithms
❌ Resource allocation strategies
❌ Integration with ExecutionEngine
❌ Automatic resource discovery
❌ Resource limits enforcement
❌ Multi-tenancy isolation

## 💭 Why It Wasn't Critical

1. **Single Instance Works** - Most users run one Ollama instance locally
2. **Complexity vs Value** - Added significant complexity for edge cases
3. **Provider Handles It** - OllamaProvider already manages connections
4. **Not Task-Critical** - Tasks work fine without resource management

## 🔮 Future Integration Path

If needed in client_v2, it could be added as:

```python
class Client:
    async def register_resource_hub(hub: ResourceHub)
    async def allocate_resource(requirements: Dict) -> ResourceInstance
    async def get_resource_metrics(instance_id: str) -> ResourceMetrics
```

But would need to:
1. Integrate with ExecutionEngine
2. Modify providers to use ResourceManager
3. Add resource requirements to Task model
4. Implement allocation strategies

## 📊 Use Cases That Would Benefit

1. **Production Deployments** - Multiple Ollama servers
2. **Cloud Environments** - Auto-scaling based on load
3. **Resource Constrained** - Sharing GPU across tasks
4. **Multi-tenant** - Isolating resources per user
5. **Cost Optimization** - Start/stop expensive resources

## 🎯 Verdict

Resource management was designed as an **enterprise feature** for managing distributed compute resources. It's not needed for:
- Single-user deployments
- Local development
- Simple workflows
- Most common use cases

It would be valuable for:
- Production deployments with multiple LLM servers
- Cloud-based auto-scaling scenarios
- Multi-tenant environments

**Current Status**: The foundation exists but it's not integrated or essential for core functionality.