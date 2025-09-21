# Hub Factory Architecture V2 - Execution Backend Layer

## Core Concept

**HubFactory** is the execution backend layer that provides the actual implementation for protocol methods. Similar to how ProviderFactory validates and exposes protocol methods, HubFactory provides the execution path for those methods.

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                   Provider                           │
│         (Protocol Interface & Methods)                │
│   - Defines what methods are available (generate,    │
│     execute, chat, etc.)                             │
│   - Validates parameters                             │
│   - Routes to execution backend                      │
└────────────────────────┬─────────────────────────────┘
                         │
                    ▼ needs execution backend
┌─────────────────────────────────────────────────────┐
│                  HubFactory                          │
│          (Execution Backend Registry)                │
│   - Maps protocols to execution backends             │
│   - Provides actual implementation                   │
│   - Manages execution resources                      │
└────────────────────────┬─────────────────────────────┘
                         │
        ┌────────────────┼────────────────────┐
        ▼                ▼                    ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
│ OllamaBackend│ │DockerBackend │ │LocalBackend      │
│              │ │              │ │                  │
│ - HTTP calls │ │ - Container  │ │ - subprocess     │
│   to Ollama  │ │   management │ │ - file system    │
│ - Model mgmt │ │ - Volume     │ │ - sandbox        │
└──────────────┘ └──────────────┘ └──────────────────┘
```

## How It Works

### 1. Provider Declares Protocol & Methods
```python
class OllamaProvider(ProtocolProvider):
    def get_supported_methods(self):
        return ["llm/generate", "llm/chat", "llm/embeddings"]
    
    async def execute(self, method: str, params: Dict):
        # Get execution backend from HubFactory
        backend = self.hub_factory.get_backend("llm/v1")
        return await backend.execute(method, params)
```

### 2. HubFactory Provides Execution Backend
```python
class HubFactory:
    """Registry of execution backends for protocols"""
    
    BACKEND_REGISTRY = {
        "llm/v1": OllamaExecutionBackend,
        "docker/v1": DockerExecutionBackend,
        "python/v1": LocalPythonBackend,
        "shell/v1": LocalShellBackend,
        "http/v1": HTTPProxyBackend,
    }
    
    def get_backend(self, protocol: str) -> ExecutionBackend:
        """Get the execution backend for a protocol"""
        backend_class = self.BACKEND_REGISTRY[protocol]
        return self._get_or_create_backend(backend_class)
```

### 3. Execution Backend Implements Actual Logic
```python
class OllamaExecutionBackend:
    """Actual implementation for LLM protocol"""
    
    def __init__(self):
        self.ollama_hub = OllamaHub()  # Manages Ollama instances
        self.connection_pool = None
    
    async def execute(self, method: str, params: Dict):
        if method == "llm/generate":
            # Get Ollama instance from hub
            instance = await self.ollama_hub.allocate_instance(
                model=params.get("model")
            )
            
            # Make actual HTTP call to Ollama
            response = await self._call_ollama(
                instance.endpoint,
                "/api/generate",
                params
            )
            
            # Release instance
            await self.ollama_hub.release_instance(instance)
            
            return response
```

## Key Design Principles

### 1. **Separation of Interface and Implementation**
- **Provider**: Defines WHAT can be done (protocol methods)
- **HubFactory**: Provides HOW it's done (execution backend)
- **Backend**: Implements the actual execution logic

### 2. **Protocol-Driven Architecture**
```python
# Protocol defines the contract
protocol = {
    "id": "llm/v1",
    "methods": {
        "generate": {
            "params": ["model", "prompt", "temperature"],
            "returns": "text"
        }
    }
}

# Provider exposes the protocol
provider = OllamaProvider(protocol="llm/v1")

# HubFactory provides the execution
backend = hub_factory.get_backend("llm/v1")
```

### 3. **Pluggable Backends**
```python
# Register custom backend
hub_factory.register_backend(
    protocol="custom/v1",
    backend_class=MyCustomBackend
)

# Provider automatically uses it
provider = GenericProvider(protocol="custom/v1")
result = await provider.execute("custom/method", params)
```

## Implementation Components

### 1. **ExecutionBackend Base Class**
```python
class ExecutionBackend(ABC):
    """Base class for all execution backends"""
    
    @abstractmethod
    async def initialize(self):
        """Initialize the backend resources"""
        pass
    
    @abstractmethod
    async def execute(self, method: str, params: Dict) -> Any:
        """Execute a method with parameters"""
        pass
    
    @abstractmethod
    async def validate(self, method: str, params: Dict) -> bool:
        """Validate if method can be executed"""
        pass
    
    @abstractmethod
    async def cleanup(self):
        """Cleanup backend resources"""
        pass
```

### 2. **Specific Backend Implementations**

#### OllamaExecutionBackend
- Manages Ollama HTTP connections
- Handles model loading/unloading
- Connection pooling to Ollama instances
- Load balancing across instances

#### DockerExecutionBackend
- Container lifecycle management
- Volume and network management
- Resource limits and monitoring
- Image pulling and caching

#### LocalPythonBackend
- Python subprocess execution
- Virtual environment management
- Module isolation
- Resource sandboxing

#### LocalShellBackend
- Shell command execution
- Process management
- Environment variables
- Working directory management

#### HTTPProxyBackend
- HTTP client with connection pooling
- Rate limiting
- Authentication management
- Request/response transformation

### 3. **HubFactory Enhancement**
```python
class HubFactory:
    def __init__(self):
        self.backends = {}  # Cached backend instances
        self.backend_configs = {}  # Backend configurations
        
    def register_backend(self, protocol: str, backend_class: Type[ExecutionBackend]):
        """Register a new backend for a protocol"""
        self.BACKEND_REGISTRY[protocol] = backend_class
        
    def configure_backend(self, protocol: str, config: Dict):
        """Configure a backend before initialization"""
        self.backend_configs[protocol] = config
        
    def get_backend(self, protocol: str) -> ExecutionBackend:
        """Get or create backend for protocol"""
        if protocol not in self.backends:
            backend_class = self.BACKEND_REGISTRY[protocol]
            config = self.backend_configs.get(protocol, {})
            self.backends[protocol] = backend_class(**config)
        return self.backends[protocol]
```

## Integration with Existing Components

### ProviderFactory Integration
```python
class ProviderFactory:
    def __init__(self, hub_factory: HubFactory = None):
        self.hub_factory = hub_factory or get_global_hub_factory()
        
    def create_provider(self, provider_class, **kwargs):
        # Create provider
        provider = provider_class(**kwargs)
        
        # Inject execution backend
        protocol = provider.protocol_id
        backend = self.hub_factory.get_backend(protocol)
        provider.set_execution_backend(backend)
        
        # Validate methods match backend capabilities
        self._validate_backend_compatibility(provider, backend)
        
        return provider
```

### Provider Base Class Enhancement
```python
class ProtocolProvider:
    def __init__(self, protocol_id: str, **kwargs):
        self.protocol_id = protocol_id
        self.execution_backend = None  # Set by factory
        
    def set_execution_backend(self, backend: ExecutionBackend):
        """Set the execution backend for this provider"""
        self.execution_backend = backend
        
    async def execute(self, method: str, params: Dict):
        """Execute using the backend"""
        if not self.execution_backend:
            raise RuntimeError("No execution backend configured")
        
        # Provider can add validation/transformation
        validated_params = self.validate_params(method, params)
        
        # Delegate to backend
        result = await self.execution_backend.execute(method, validated_params)
        
        # Provider can post-process
        return self.transform_result(result)
```

## Benefits of This Architecture

1. **Clean Separation**
   - Protocol definition (what) vs execution (how)
   - Providers focus on protocol compliance
   - Backends focus on execution efficiency

2. **Reusability**
   - Multiple providers can share the same backend
   - One backend can serve multiple protocol versions
   - Backends can be swapped without changing providers

3. **Testability**
   - Mock backends for testing providers
   - Test backends independently
   - Protocol compliance testing separate from execution testing

4. **Extensibility**
   - Add new protocols without new backends
   - Add new backends without changing providers
   - Custom backends for special requirements

5. **Resource Efficiency**
   - Shared connection pools
   - Centralized resource management
   - Backend-specific optimizations

## Example: Complete Flow

```python
# 1. Initialize HubFactory with backends
hub_factory = HubFactory()
hub_factory.configure_backend("llm/v1", {
    "ollama_urls": ["http://localhost:11434"],
    "max_connections": 10
})

# 2. Create provider with factory
provider_factory = ProviderFactory(hub_factory=hub_factory)
ollama_provider = provider_factory.create_provider(
    OllamaProvider,
    protocol_id="llm/v1"
)

# 3. Execute method (provider -> backend flow)
result = await ollama_provider.execute("llm/generate", {
    "model": "llama3.2",
    "prompt": "Hello world"
})

# Behind the scenes:
# - Provider validates method and params
# - Provider gets backend from hub_factory
# - Backend manages Ollama connection
# - Backend executes HTTP request
# - Backend returns result
# - Provider transforms and returns to user
```

## Migration Strategy

1. **Phase 1**: Create ExecutionBackend base class and HubFactory
2. **Phase 2**: Implement backends for each protocol
3. **Phase 3**: Update providers to use backends
4. **Phase 4**: Remove redundant execution code from providers
5. **Phase 5**: Optimize backend resource management

This architecture makes the execution path pluggable and reusable, similar to how ProviderFactory makes provider creation validated and consistent.