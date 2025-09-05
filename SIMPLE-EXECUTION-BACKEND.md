# Simple Execution Backend Design

## The Real Problem
- Providers need execution resources (OllamaHub, Docker client, etc.)
- ProviderPool creates providers but doesn't know about these dependencies
- We need to inject the right execution backend for each protocol

## Simple Solution

### 1. ExecutionBackend - Just what's needed
```python
class ExecutionBackend:
    """Base class for execution backends"""
    
    async def execute(self, method: str, params: dict) -> dict:
        """Execute a method with params"""
        raise NotImplementedError

class OllamaBackend(ExecutionBackend):
    """Ollama execution backend"""
    
    def __init__(self):
        self.hub = OllamaHub(auto_discover=True)
    
    async def execute(self, method: str, params: dict) -> dict:
        # Get instance from hub
        instance = await self.hub.allocate_instance(params.get("model"))
        
        # Make HTTP call
        if method == "generate":
            result = await self._call_ollama(instance, "/api/generate", params)
        elif method == "chat":
            result = await self._call_ollama(instance, "/api/chat", params)
        
        # Release instance
        await self.hub.release_instance(instance)
        return result

class LocalBackend(ExecutionBackend):
    """Local Python/Shell execution"""
    
    async def execute(self, method: str, params: dict) -> dict:
        if method == "python/execute":
            return await self._run_python_file(params["file"])
        elif method == "shell/execute":
            return await self._run_shell_command(params["command"])
```

### 2. Simple Backend Registry
```python
class BackendRegistry:
    """Simple registry of execution backends"""
    
    BACKENDS = {
        "llm/v1": OllamaBackend,
        "python/v1": LocalBackend,
        "shell/v1": LocalBackend,
        "docker/v1": DockerBackend,
    }
    
    def __init__(self):
        self.instances = {}
    
    def get_backend(self, protocol: str) -> ExecutionBackend:
        """Get or create backend for protocol"""
        if protocol not in self.instances:
            backend_class = self.BACKENDS.get(protocol)
            if backend_class:
                self.instances[protocol] = backend_class()
        return self.instances.get(protocol)

# Global registry
backend_registry = BackendRegistry()
```

### 3. Update ProviderPool to inject backend
```python
class ProviderPool:
    async def _create_provider(self) -> PooledProvider:
        """Create provider with backend injected"""
        
        # Get backend for this protocol
        protocol = f"{self.provider_type}/v1"  
        backend = backend_registry.get_backend(protocol)
        
        # Create provider with backend
        from gleitzeit.providers.factory import ProviderFactory
        factory = ProviderFactory()
        
        instance = factory.create_provider(
            self.provider_class,
            provider_id=self.provider_type,
            protocol_id=protocol,
            execution_backend=backend,  # Inject backend
            validate=True
        )
        
        await instance.initialize()
        
        return PooledProvider(
            provider_type=self.provider_type,
            instance=instance,
            state=ProviderState.AVAILABLE
        )
```

### 4. Update Provider to use backend
```python
class OllamaProvider(ProtocolProvider):
    def __init__(self, execution_backend=None, **kwargs):
        super().__init__(**kwargs)
        self.backend = execution_backend  # Injected by pool
    
    async def execute(self, method: str, params: dict):
        if not self.backend:
            raise RuntimeError("No execution backend")
        
        # Just delegate to backend
        return await self.backend.execute(method, params)
```

## That's It!

### What we achieved:
✅ Providers get their execution dependencies
✅ Clean separation of protocol (Provider) and execution (Backend)
✅ Pool manages backend injection
✅ Simple, understandable code

### What we avoided:
❌ Complex capability declarations
❌ Auto-generation magic
❌ Multiple execution modes
❌ Tons of abstraction layers

### To add a new protocol:
1. Create a backend class with `execute()` method
2. Register it in `BACKENDS` dict
3. Provider gets it automatically from pool

### Example flow:
```python
# Pool creates provider
pool = ProviderPool("ollama", OllamaProvider)
provider = await pool.acquire()

# Provider has backend injected
# provider.backend = OllamaBackend instance with OllamaHub

# Execute uses backend
result = await provider.execute("generate", {"prompt": "Hello"})
# This calls backend.execute() which uses OllamaHub
```

## Is this better?

**Yes!** Because:
- Solves the actual problem (dependency injection)
- Minimal new concepts
- Easy to understand and debug
- No over-engineering
- Can extend later if needed

The fancy capability system and auto-generation can wait until we actually need them!