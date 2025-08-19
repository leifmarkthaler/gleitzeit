# Resource Management Integration Plan

## Executive Summary

Gleitzeit already has a resource management system through the **Hub architecture** (OllamaHub, DockerHub, etc.). The new resource management system created in client_v2 duplicates this functionality. This document outlines how to properly integrate resource management using the existing Hub architecture.

## Current State Analysis

### What Exists Already

1. **Hub System** (`/src/gleitzeit/hub/`)
   - `OllamaHub`: Manages Ollama instances, auto-discovery, health checks
   - `DockerHub`: Manages Docker containers
   - `ResourceHub` (base): Common resource management interface
   - `ResourceManager`: Orchestrates multiple hubs

2. **Provider System** (`/src/gleitzeit/providers/`)
   - `OllamaProvider`: Executes LLM methods
   - Currently uses hardcoded `default_endpoint = "http://localhost:11434"`
   - NOT connected to OllamaHub (this is the gap!)

3. **New Resource Management** (`/src/gleitzeit/resources/`)
   - `ResourcePool`, `ResourceAllocator`, `ResourceManager`
   - Duplicates Hub functionality
   - Created because providers aren't using hubs

### The Problem

```
Current Flow (Broken):
Workflow → Task → ExecutionEngine → Provider → [Hardcoded Endpoint]
                                                        ↓
                                                 Always localhost:11434

What Should Happen:
Workflow → Task → ExecutionEngine → Provider → Hub → [Available Instance]
                                                 ↓
                                         Allocates best instance
```

## Proper Integration Approach

### Option 1: Connect Providers to Hubs (Recommended)

This follows the original Hub-Provider architecture design.

```python
# In client initialization
async def _init_native_client(self):
    # Create hub for resource management
    ollama_hub = OllamaHub(
        hub_id="ollama-hub",
        auto_discover=True  # Finds running instances
    )
    await ollama_hub.initialize()
    
    # Create provider with hub dependency
    ollama_provider = OllamaProvider(
        provider_id="ollama-provider",
        ollama_hub=ollama_hub  # Pass hub to provider
    )
    
    # Register provider
    registry.register_provider("ollama-provider", "llm/v1", ollama_provider)
```

**Provider Implementation:**
```python
class OllamaProvider(ProtocolProvider):
    def __init__(self, provider_id: str, ollama_hub: OllamaHub):
        self.hub = ollama_hub  # Store hub reference
    
    async def execute(self, method: str, params: Dict[str, Any]):
        # Get instance from hub
        instance = await self.hub.get_available_instance(
            capabilities={params.get('model')}
        )
        
        if not instance:
            # Fallback to default
            instance = ResourceInstance(endpoint="http://localhost:11434")
        
        # Use instance endpoint
        endpoint = instance.endpoint
        # ... execute request using endpoint
        
        # Hub tracks metrics automatically
```

**Advantages:**
- Uses existing, tested Hub system
- Follows documented architecture
- Auto-discovery works
- Health monitoring included
- Metrics collection built-in

**Disadvantages:**
- Requires modifying provider initialization
- Need to pass hub references

### Option 2: Use New Resource Management as Bridge

Keep the new resource management system but use it as a bridge to the Hub system.

```python
# ResourceManager wraps OllamaHub
class ResourceManager:
    def __init__(self):
        self.ollama_hub = OllamaHub(auto_discover=True)
        
    async def allocate_resource(self, task_id: str, resource_type: str, ...):
        if resource_type == "ollama":
            instance = await self.ollama_hub.get_available_instance(...)
            # Wrap in new ResourceInstance format
            return ResourceInstance(
                id=instance.id,
                endpoint=instance.endpoint,
                ...
            )
```

**Advantages:**
- Can keep new API
- Gradual migration path

**Disadvantages:**
- Two layers of resource management
- More complexity
- Duplicate concepts

### Option 3: Provider Self-Allocation (Current Attempt)

Make providers aware of resource management and self-allocate.

```python
class OllamaProvider:
    def __init__(self):
        self.resource_manager = None  # Set later if available
    
    async def execute(self, method: str, params: Dict[str, Any]):
        if self.resource_manager:
            resource = await self.resource_manager.allocate_resource(...)
            endpoint = resource.endpoint
        else:
            endpoint = self.default_endpoint
```

**Advantages:**
- Minimal changes to architecture
- Optional resource management

**Disadvantages:**
- Providers become complex
- Not following Hub-Provider separation
- Each provider needs allocation logic

## Recommended Implementation Plan

### Phase 1: Fix Provider-Hub Connection

1. **Update OllamaProvider constructor** to accept optional hub:
```python
def __init__(self, provider_id: str, ollama_hub: Optional[OllamaHub] = None):
    self.hub = ollama_hub
```

2. **Update provider execution** to use hub:
```python
async def execute(self, method: str, params: Dict[str, Any]):
    endpoint = self.default_endpoint
    
    if self.hub:
        instance = await self.hub.get_available_instance()
        if instance:
            endpoint = instance.endpoint
    
    # Continue with execution using endpoint
```

3. **Initialize hub in client_v2**:
```python
# In _init_native_client
if self.native_config.get('enable_resource_management', False):
    # Create and start OllamaHub
    self._ollama_hub = OllamaHub(auto_discover=True)
    await self._ollama_hub.initialize()
    
    # Pass to provider
    ollama_provider = OllamaProvider("ollama", ollama_hub=self._ollama_hub)
```

### Phase 2: Enhance Hub Functionality

1. **Add model-based allocation** to OllamaHub:
```python
async def get_instance_for_model(self, model: str) -> Optional[ResourceInstance]:
    # Find instance that has this model
    for instance in self.instances.values():
        if model in instance.capabilities:
            if instance.is_available():
                return instance
    return None
```

2. **Add load balancing strategies**:
```python
async def get_available_instance(
    self, 
    strategy: str = "least_loaded",
    capabilities: Set[str] = None
) -> Optional[ResourceInstance]:
    # Implementation similar to ResourceAllocator
```

### Phase 3: Clean Up

1. **Remove duplicate resource management** from `/src/gleitzeit/resources/`
2. **Update documentation** to reflect Hub-based resource management
3. **Add tests** for Hub-Provider integration

## How Workflows Will Work

With proper Hub integration, workflows remain unchanged:

```yaml
# workflow.yaml - No changes needed!
tasks:
  - id: "task1"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages: [...]
```

**Execution Flow:**

1. Workflow loaded, task created
2. ExecutionEngine routes task to OllamaProvider
3. OllamaProvider asks OllamaHub for instance with "llama3.2"
4. OllamaHub returns best available instance (or starts one)
5. Provider executes on that instance
6. Hub tracks metrics, updates instance status
7. Result returned to workflow

## Benefits of Using Existing Hub System

1. **Already Implemented**: OllamaHub has discovery, health checks, metrics
2. **Tested**: Hub system is already in use
3. **Documented**: Architecture docs explain Hub-Provider pattern
4. **Auto-Discovery**: Finds Ollama instances on ports 11434-11439
5. **Process Management**: Can start/stop Ollama instances
6. **Model Awareness**: Tracks which models each instance has
7. **Connection Pooling**: Shared aiohttp session for performance

## Migration Path

### Step 1: Minimal Working Integration (1 day)
- Add hub parameter to OllamaProvider
- Pass hub from client_v2 to provider
- Test with simple workflow

### Step 2: Feature Parity (2-3 days)
- Add allocation strategies to hub
- Implement model-based routing
- Add queuing for busy instances

### Step 3: Deprecate New System (1 day)
- Remove `/src/gleitzeit/resources/`
- Update imports and tests
- Update documentation

## Testing Strategy

```python
# Test hub-provider integration
async def test_ollama_with_hub():
    # Create hub with mock instances
    hub = OllamaHub(auto_discover=False)
    await hub.register_instance(
        ResourceInstance(
            id="test-1",
            endpoint="http://localhost:11434",
            capabilities={"llama3.2"}
        )
    )
    
    # Create provider with hub
    provider = OllamaProvider("test", ollama_hub=hub)
    
    # Execute method
    result = await provider.execute("llm/chat", {
        "model": "llama3.2",
        "messages": [{"role": "user", "content": "test"}]
    })
    
    # Verify correct instance was used
    assert hub.instances["test-1"].metrics.total_requests == 1
```

## Conclusion

The proper approach is to **use the existing Hub system** rather than creating a parallel resource management system. The Hub architecture is already designed for this purpose and just needs to be properly connected to the providers.

The key insight is that **resource management should be transparent to workflows** - they shouldn't need to know about resource allocation. The Hub-Provider pattern handles this elegantly by having providers request resources from hubs as needed.

## Next Steps

1. **Decision**: Choose Option 1 (Connect Providers to Hubs)
2. **Implement**: Start with Phase 1 - minimal hub connection
3. **Test**: Verify workflows work with multiple Ollama instances
4. **Document**: Update user docs to explain resource management
5. **Clean up**: Remove duplicate resource management code

## Questions to Resolve

1. Should hubs be initialized in client_v2 or in ExecutionEngine?
2. How to handle provider initialization in API mode vs native mode?
3. Should we keep any parts of the new resource management system?
4. How to handle backwards compatibility?

## Code Locations

- Hub System: `/src/gleitzeit/hub/`
  - `base.py`: ResourceHub base class
  - `ollama_hub.py`: Ollama instance management
  - `resource_manager.py`: Multi-hub orchestration

- Providers: `/src/gleitzeit/providers/`
  - `ollama_provider.py`: Needs hub integration
  - `base.py`: ProtocolProvider base class

- New Resource System: `/src/gleitzeit/resources/` (to be deprecated?)
  - `manager.py`, `allocator.py`, `pool.py`, `models.py`

- Client: `/src/gleitzeit/client_v2.py`
  - Where hub initialization should happen