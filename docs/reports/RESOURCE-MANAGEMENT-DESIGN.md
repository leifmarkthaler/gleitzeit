# Resource Management Design - Hubs as First-Class Citizens

## The Problem

We need to manage different types of execution resources:
- **Ollama instances** - Multiple Ollama servers, model management, load balancing
- **Docker containers** - Container lifecycle, volumes, networks
- **Local processes** - Shell/Python processes, sandboxing, resource limits
- **HTTP endpoints** - Connection pools, rate limiting, authentication

But we don't want to:
- Hide resource managers (OllamaHub) deep in backend code
- Create tight coupling between providers and resource managers
- Duplicate resource management logic

## Key Design Questions

### 1. Who owns the resource managers (Hubs)?

**Option A: Hubs as Standalone Services**
```python
# Hubs are created and managed separately
ollama_hub = OllamaHub(auto_discover=True)
docker_hub = DockerHub(max_containers=10)

# Passed to whoever needs them
backend = OllamaBackend(hub=ollama_hub)
provider = OllamaProvider(backend=backend)
```

**Option B: Hub Registry/Manager**
```python
# Central registry owns all hubs
class HubManager:
    def __init__(self):
        self.hubs = {
            "ollama": OllamaHub(auto_discover=True),
            "docker": DockerHub(max_containers=10),
            "local": LocalProcessHub(max_processes=20)
        }
    
    def get_hub(self, type: str):
        return self.hubs.get(type)

# Everyone gets hubs from manager
hub_manager = HubManager()
ollama_hub = hub_manager.get_hub("ollama")
```

**Option C: Hubs as Protocol Resources**
```python
# Each protocol has associated resources
class ProtocolResources:
    def __init__(self, protocol: str):
        self.protocol = protocol
        self.hub = self._create_hub(protocol)
    
    def _create_hub(self, protocol):
        if protocol == "llm/v1":
            return OllamaHub()
        elif protocol == "docker/v1":
            return DockerHub()
```

### 2. How do providers access resources?

**Option A: Direct Hub Access**
```python
class OllamaProvider:
    def __init__(self, ollama_hub: OllamaHub):
        self.hub = ollama_hub  # Direct access
    
    async def execute(self, method, params):
        instance = await self.hub.allocate_instance()
        result = await self._call_instance(instance, method, params)
        await self.hub.release_instance(instance)
        return result
```

**Option B: Through Execution Context**
```python
class ExecutionContext:
    """Context passed to providers for execution"""
    def __init__(self, hub: ResourceHub, config: dict):
        self.hub = hub
        self.config = config
        self.allocated_resources = []
    
    async def allocate_resource(self, **requirements):
        resource = await self.hub.allocate(**requirements)
        self.allocated_resources.append(resource)
        return resource
    
    async def cleanup(self):
        for resource in self.allocated_resources:
            await self.hub.release(resource)

class OllamaProvider:
    async def execute(self, method, params, context: ExecutionContext):
        resource = await context.allocate_resource(model=params["model"])
        result = await self._use_resource(resource, method, params)
        # Context handles cleanup
        return result
```

**Option C: Resource Injection Pattern**
```python
class ResourceInjector:
    """Injects resources into execution"""
    
    async def execute_with_resources(self, provider, method, params):
        # Determine what resources are needed
        protocol = provider.protocol_id
        hub = self.hub_manager.get_hub_for_protocol(protocol)
        
        # Allocate resources
        resources = await hub.allocate_for_method(method, params)
        
        try:
            # Inject and execute
            result = await provider.execute(method, params, resources=resources)
            return result
        finally:
            # Always cleanup
            await hub.release(resources)
```

## Proposed Design: Explicit Resource Management

### Core Principles
1. **Hubs are first-class citizens** - Not hidden in backends
2. **Explicit resource lifecycle** - Clear allocate/release
3. **Flexible ownership** - Hubs can be shared or dedicated
4. **Protocol-aware** - Different protocols need different resources

### Architecture

```
┌─────────────────────────────────────────────────────┐
│                 ResourceManager                      │
│         (Central resource management)                │
├─────────────────────────────────────────────────────┤
│ - Owns all resource hubs                            │
│ - Maps protocols to hubs                            │
│ - Handles resource allocation/release               │
│ - Monitors resource usage                           │
└────────────────────┬─────────────────────────────────┘
                     │
     ┌───────────────┼───────────────┐
     ▼               ▼               ▼
┌──────────┐   ┌──────────┐   ┌──────────┐
│OllamaHub │   │DockerHub │   │LocalHub  │
│          │   │          │   │          │
│- Ollama  │   │- Containers│ │- Processes│
│  instances│  │- Images   │  │- Files   │
│- Models  │   │- Volumes  │  │- Sandbox │
└──────────┘   └──────────┘   └──────────┘
     ▲               ▲               ▲
     └───────────────┼───────────────┘
                     │
              ExecutionBackend
                     │
                 Provider
```

### Implementation

```python
# 1. ResourceManager - Central resource management
class ResourceManager:
    """
    Manages all resource hubs and provides resource allocation.
    This is visible and configurable, not hidden.
    """
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.hubs = {}
        self.protocol_hub_mapping = {
            "llm/v1": "ollama",
            "docker/v1": "docker", 
            "python/v1": "local",
            "shell/v1": "local",
        }
        
    async def initialize(self):
        """Initialize all configured hubs"""
        # Create hubs based on config
        if self.config.get("enable_ollama", True):
            self.hubs["ollama"] = OllamaHub(
                auto_discover=self.config.get("ollama_auto_discover", True),
                ports=self.config.get("ollama_ports", [11434, 11435])
            )
            await self.hubs["ollama"].initialize()
            
        if self.config.get("enable_docker", False):
            self.hubs["docker"] = DockerHub(
                max_containers=self.config.get("max_containers", 10)
            )
            await self.hubs["docker"].initialize()
            
        if self.config.get("enable_local", True):
            self.hubs["local"] = LocalProcessHub(
                max_processes=self.config.get("max_processes", 20)
            )
            await self.hubs["local"].initialize()
    
    def get_hub_for_protocol(self, protocol: str) -> ResourceHub:
        """Get the hub that manages resources for a protocol"""
        hub_type = self.protocol_hub_mapping.get(protocol)
        return self.hubs.get(hub_type) if hub_type else None
    
    async def allocate_resource(self, protocol: str, requirements: dict) -> Resource:
        """Allocate a resource for a protocol"""
        hub = self.get_hub_for_protocol(protocol)
        if not hub:
            raise RuntimeError(f"No resource hub for protocol {protocol}")
        return await hub.allocate(requirements)
    
    async def release_resource(self, resource: Resource):
        """Release a resource back to its hub"""
        hub = self.hubs.get(resource.hub_type)
        if hub:
            await hub.release(resource)
    
    def get_status(self) -> dict:
        """Get status of all resources"""
        status = {}
        for name, hub in self.hubs.items():
            status[name] = hub.get_stats()
        return status

# 2. ExecutionBackend with explicit resource management
class ExecutionBackend:
    """
    Base backend that uses ResourceManager.
    Resources are explicit, not hidden.
    """
    
    def __init__(self, resource_manager: ResourceManager):
        self.resource_manager = resource_manager
        
    async def execute_with_resources(self, protocol: str, method: str, params: dict):
        """Execute with automatic resource management"""
        # Allocate resource
        resource = await self.resource_manager.allocate_resource(
            protocol=protocol,
            requirements=self._get_requirements(method, params)
        )
        
        try:
            # Execute with resource
            result = await self._execute(resource, method, params)
            return result
        finally:
            # Always release
            await self.resource_manager.release_resource(resource)
    
    @abstractmethod
    async def _execute(self, resource: Resource, method: str, params: dict):
        """Execute using the allocated resource"""
        pass

# 3. Specific backend implementation
class OllamaExecutionBackend(ExecutionBackend):
    """Ollama backend using explicit resources"""
    
    def _get_requirements(self, method: str, params: dict):
        """Determine resource requirements"""
        return {
            "model": params.get("model", "llama3.2"),
            "memory": params.get("max_memory", "8gb")
        }
    
    async def _execute(self, resource: Resource, method: str, params: dict):
        """Execute using Ollama instance resource"""
        # Resource contains the Ollama instance details
        endpoint = resource.metadata["endpoint"]  # e.g., "http://localhost:11434"
        
        if method == "generate":
            return await self._call_ollama(endpoint, "/api/generate", params)
        elif method == "chat":
            return await self._call_ollama(endpoint, "/api/chat", params)

# 4. Provider using backend
class OllamaProvider(ProtocolProvider):
    """Provider that uses backend with explicit resource management"""
    
    def __init__(self, backend: ExecutionBackend = None, **kwargs):
        super().__init__(**kwargs)
        self.backend = backend
        
    async def execute(self, method: str, params: dict):
        """Execute through backend"""
        if not self.backend:
            raise RuntimeError("No execution backend configured")
        
        return await self.backend.execute_with_resources(
            protocol=self.protocol_id,
            method=method,
            params=params
        )

# 5. Usage with visible resource management
async def main():
    # Create and configure resource manager (visible!)
    resource_manager = ResourceManager(config={
        "enable_ollama": True,
        "ollama_auto_discover": True,
        "ollama_ports": [11434, 11435, 11436],  # Check 3 ports
        "enable_docker": True,
        "max_containers": 5,
        "enable_local": True,
        "max_processes": 10
    })
    await resource_manager.initialize()
    
    # Check what resources we have
    print("Available resources:", resource_manager.get_status())
    # Output: {
    #   "ollama": {"instances": 3, "models": ["llama3.2", "mistral"]},
    #   "docker": {"containers": 0, "images": 5},
    #   "local": {"processes": 0, "max": 10}
    # }
    
    # Create backend with resource manager
    backend = OllamaExecutionBackend(resource_manager)
    
    # Create provider with backend
    provider = OllamaProvider(backend=backend)
    
    # Execute - resources are managed transparently but not hidden
    result = await provider.execute("generate", {
        "model": "llama3.2",
        "prompt": "Hello world"
    })
```

### Benefits of this approach

1. **Resources are visible and configurable**
   - ResourceManager is explicit, not hidden
   - Can inspect available resources
   - Can configure resource limits

2. **Clean separation of concerns**
   - ResourceManager: Manages hubs and allocation
   - Hubs: Manage specific resource types
   - Backends: Use resources for execution
   - Providers: Protocol interface

3. **Flexible resource allocation**
   - Can allocate based on requirements
   - Load balancing across instances
   - Resource limits and quotas

4. **Easy to extend**
   - Add new hub types
   - Add new allocation strategies
   - Add resource monitoring

### Alternative: Direct Hub Access

If we want even more visibility, providers could directly interact with hubs:

```python
class OllamaProvider:
    def __init__(self, ollama_hub: OllamaHub = None):
        self.ollama_hub = ollama_hub or get_global_ollama_hub()
    
    async def execute(self, method: str, params: dict):
        # Direct hub interaction - very explicit
        instance = await self.ollama_hub.allocate_instance(
            model=params.get("model")
        )
        
        try:
            if method == "generate":
                result = await self._generate(instance, params)
            elif method == "chat":
                result = await self._chat(instance, params)
            return result
        finally:
            await self.ollama_hub.release_instance(instance)
```

This is simpler but:
- ❌ Each provider needs resource management code
- ❌ No central resource monitoring
- ❌ Harder to change resource strategies

## Recommendation

Use the **ResourceManager** approach because:
1. Resources are explicit and visible (not hidden)
2. Central configuration and monitoring
3. Clean separation between protocol (Provider) and resources (Hubs)
4. Easy to extend and modify

The key insight: **Make resource management explicit and configurable, not hidden in backends**