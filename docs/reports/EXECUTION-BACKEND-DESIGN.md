# ExecutionBackend Design - Making Integration Easy

## Key Design Goals

1. **Easy to add new providers** - Minimal code, clear patterns
2. **Easy to add new backends** - Simple interface, good defaults
3. **Discoverable capabilities** - Backends declare what they can do
4. **Flexible but consistent** - Handle different execution patterns
5. **Resource management built-in** - Connection pools, rate limiting, etc.

## Core Design Questions

### 1. How should providers and backends communicate?

**Option A: Direct Method Mapping**
```python
# Backend implements exact methods
class OllamaBackend:
    async def generate(self, prompt: str, model: str, **kwargs):
        return await self._call_ollama("/api/generate", ...)
    
    async def chat(self, messages: list, model: str, **kwargs):
        return await self._call_ollama("/api/chat", ...)
```

**Option B: Generic Execute with Method Routing**
```python
# Backend has single execute method
class OllamaBackend:
    async def execute(self, method: str, params: dict):
        if method == "generate":
            return await self._generate(**params)
        elif method == "chat":
            return await self._chat(**params)
```

**Option C: Declarative Method Registry**
```python
# Backend declares methods with metadata
class OllamaBackend:
    @backend_method(
        name="generate",
        params=["prompt", "model"],
        optional=["temperature", "max_tokens"],
        returns="text"
    )
    async def generate(self, prompt: str, model: str, **kwargs):
        return await self._call_ollama("/api/generate", ...)
```

### 2. How should backends declare capabilities?

**Capability Manifest**
```python
class ExecutionBackend:
    @abstractmethod
    def get_capabilities(self) -> BackendCapabilities:
        """Return backend capabilities"""
        return BackendCapabilities(
            methods=["generate", "chat", "embeddings"],
            models=["llama3.2", "mistral"],
            features=["streaming", "batch", "async"],
            limits={"max_tokens": 4096, "rate_limit": 100}
        )
```

### 3. How should we handle different execution patterns?

**Execution Patterns to Support:**
- **Simple async** - Single request/response
- **Streaming** - Progressive response (LLM generation)
- **Batch** - Multiple operations at once
- **Long-running** - Tasks that take minutes/hours
- **Interactive** - Stateful sessions (REPL, chat)

**Unified Interface Approach:**
```python
class ExecutionBackend:
    async def execute(self, request: ExecutionRequest) -> ExecutionResponse:
        """Simple execution"""
        pass
    
    async def execute_stream(self, request: ExecutionRequest) -> AsyncIterator[ExecutionResponse]:
        """Streaming execution"""
        pass
    
    async def execute_batch(self, requests: List[ExecutionRequest]) -> List[ExecutionResponse]:
        """Batch execution"""
        pass
    
    async def create_session(self) -> ExecutionSession:
        """Create interactive session"""
        pass
```

## Proposed Design

### Core Components

```python
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, AsyncIterator
from abc import ABC, abstractmethod
from enum import Enum

class ExecutionMode(Enum):
    """Supported execution modes"""
    SIMPLE = "simple"       # Request/response
    STREAM = "stream"       # Streaming response
    BATCH = "batch"         # Batch processing
    SESSION = "session"     # Stateful session

@dataclass
class MethodSpec:
    """Specification for a backend method"""
    name: str
    description: str
    params: Dict[str, ParamSpec]  # param_name -> spec
    returns: ReturnSpec
    modes: List[ExecutionMode]
    examples: List[Dict[str, Any]]

@dataclass
class ParamSpec:
    """Parameter specification"""
    type: str  # "string", "number", "object", etc.
    required: bool
    default: Any = None
    description: str = ""
    validation: Optional[callable] = None

@dataclass
class BackendCapabilities:
    """What a backend can do"""
    protocol: str                    # "llm/v1", "docker/v1", etc.
    methods: Dict[str, MethodSpec]   # method_name -> spec
    features: List[str]              # ["streaming", "batch", "sessions"]
    limits: Dict[str, Any]           # {"rate_limit": 100, "max_concurrent": 10}
    models: Optional[List[str]]      # For LLM backends
    
@dataclass
class ExecutionRequest:
    """Request to execute a method"""
    method: str
    params: Dict[str, Any]
    mode: ExecutionMode = ExecutionMode.SIMPLE
    options: Dict[str, Any] = None  # timeout, retry, etc.
    context: Dict[str, Any] = None  # auth, headers, etc.

@dataclass
class ExecutionResponse:
    """Response from execution"""
    success: bool
    result: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = None  # timing, tokens used, etc.
```

### Base ExecutionBackend Class

```python
class ExecutionBackend(ABC):
    """
    Base class for all execution backends.
    
    Design principles:
    1. Declarative capabilities
    2. Flexible execution modes
    3. Built-in resource management
    4. Standardized error handling
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self._initialized = False
        self._resources = {}  # Managed resources (connections, pools, etc.)
        
    # ============= Core Interface =============
    
    @abstractmethod
    def get_capabilities(self) -> BackendCapabilities:
        """
        Declare what this backend can do.
        Called by providers to understand backend features.
        """
        pass
    
    @abstractmethod
    async def initialize(self) -> None:
        """
        Initialize backend resources.
        Called once before first execution.
        """
        pass
    
    @abstractmethod
    async def cleanup(self) -> None:
        """
        Cleanup backend resources.
        Called on shutdown.
        """
        pass
    
    # ============= Execution Methods =============
    
    async def execute(self, request: ExecutionRequest) -> ExecutionResponse:
        """
        Execute a single request.
        This is the main entry point for most executions.
        """
        # Validate request
        if not await self.validate_request(request):
            return ExecutionResponse(
                success=False,
                error="Invalid request"
            )
        
        # Route to appropriate handler
        method_name = request.method
        handler = self._get_method_handler(method_name)
        
        if not handler:
            return ExecutionResponse(
                success=False,
                error=f"Method not supported: {method_name}"
            )
        
        # Execute with error handling
        try:
            result = await handler(**request.params)
            return ExecutionResponse(
                success=True,
                result=result
            )
        except Exception as e:
            return ExecutionResponse(
                success=False,
                error=str(e)
            )
    
    async def execute_stream(
        self, 
        request: ExecutionRequest
    ) -> AsyncIterator[ExecutionResponse]:
        """
        Execute with streaming response.
        Override for streaming support.
        """
        # Default: convert single response to stream
        response = await self.execute(request)
        yield response
    
    async def execute_batch(
        self, 
        requests: List[ExecutionRequest]
    ) -> List[ExecutionResponse]:
        """
        Execute multiple requests.
        Override for optimized batch processing.
        """
        # Default: execute sequentially
        responses = []
        for request in requests:
            response = await self.execute(request)
            responses.append(response)
        return responses
    
    # ============= Helper Methods =============
    
    async def validate_request(self, request: ExecutionRequest) -> bool:
        """
        Validate a request against capabilities.
        Override for custom validation.
        """
        capabilities = self.get_capabilities()
        
        # Check method exists
        if request.method not in capabilities.methods:
            return False
        
        # Check mode is supported
        method_spec = capabilities.methods[request.method]
        if request.mode not in method_spec.modes:
            return False
        
        # Validate parameters
        for param_name, param_spec in method_spec.params.items():
            if param_spec.required and param_name not in request.params:
                return False
            
            if param_spec.validation:
                value = request.params.get(param_name)
                if not param_spec.validation(value):
                    return False
        
        return True
    
    def _get_method_handler(self, method: str) -> Optional[callable]:
        """
        Get handler for a method.
        Looks for method_<name> or falls back to generic handler.
        """
        # Try specific handler
        handler_name = f"_handle_{method.replace('/', '_')}"
        if hasattr(self, handler_name):
            return getattr(self, handler_name)
        
        # Try generic handler
        if hasattr(self, "_handle_generic"):
            return lambda **kwargs: self._handle_generic(method, kwargs)
        
        return None
```

### Example Backend Implementation

```python
class OllamaExecutionBackend(ExecutionBackend):
    """
    Ollama backend implementation.
    Shows how to implement a real backend.
    """
    
    def get_capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            protocol="llm/v1",
            methods={
                "generate": MethodSpec(
                    name="generate",
                    description="Generate text from prompt",
                    params={
                        "prompt": ParamSpec(type="string", required=True),
                        "model": ParamSpec(type="string", required=True),
                        "temperature": ParamSpec(type="number", required=False, default=0.7),
                    },
                    returns=ReturnSpec(type="string"),
                    modes=[ExecutionMode.SIMPLE, ExecutionMode.STREAM],
                    examples=[{
                        "prompt": "Hello",
                        "model": "llama3.2",
                        "temperature": 0.7
                    }]
                ),
                "chat": MethodSpec(
                    name="chat",
                    description="Chat conversation",
                    params={
                        "messages": ParamSpec(type="array", required=True),
                        "model": ParamSpec(type="string", required=True),
                    },
                    returns=ReturnSpec(type="object"),
                    modes=[ExecutionMode.SIMPLE, ExecutionMode.STREAM, ExecutionMode.SESSION],
                    examples=[{
                        "messages": [{"role": "user", "content": "Hello"}],
                        "model": "llama3.2"
                    }]
                )
            },
            features=["streaming", "sessions", "model_management"],
            limits={"rate_limit": 100, "max_concurrent": 10},
            models=["llama3.2", "mistral", "codellama"]
        )
    
    async def initialize(self) -> None:
        """Initialize Ollama connection"""
        # Create Ollama hub for instance management
        self._ollama_hub = OllamaHub(auto_discover=True)
        await self._ollama_hub.initialize()
        
        # Create connection pool
        import aiohttp
        self._session = aiohttp.ClientSession()
        
        self._initialized = True
    
    async def cleanup(self) -> None:
        """Cleanup resources"""
        if hasattr(self, '_session'):
            await self._session.close()
        if hasattr(self, '_ollama_hub'):
            await self._ollama_hub.cleanup()
    
    # Method handlers
    async def _handle_generate(self, prompt: str, model: str, **kwargs):
        """Handle generate method"""
        # Get Ollama instance
        instance = await self._ollama_hub.allocate_instance(model=model)
        
        try:
            # Make API call
            async with self._session.post(
                f"{instance.endpoint}/api/generate",
                json={"prompt": prompt, "model": model, **kwargs}
            ) as response:
                result = await response.json()
                return result["response"]
        finally:
            # Release instance
            await self._ollama_hub.release_instance(instance.id)
    
    async def _handle_chat(self, messages: list, model: str, **kwargs):
        """Handle chat method"""
        # Similar implementation
        pass
```

### Making Provider Integration Easy

```python
class AutoBackendProvider(ProtocolProvider):
    """
    Provider that automatically uses backend based on protocol.
    Minimal code needed for new providers.
    """
    
    def __init__(self, protocol: str, hub_factory: HubFactory = None):
        super().__init__(protocol_id=protocol)
        self.hub_factory = hub_factory or get_global_hub_factory()
        self.backend = None
    
    async def initialize(self):
        """Auto-initialize backend"""
        self.backend = await self.hub_factory.get_backend(self.protocol_id)
        
        # Auto-generate methods from backend capabilities
        capabilities = self.backend.get_capabilities()
        for method_name, method_spec in capabilities.methods.items():
            self._register_method(method_name, method_spec)
    
    def _register_method(self, name: str, spec: MethodSpec):
        """Auto-create method from spec"""
        async def method_impl(**kwargs):
            request = ExecutionRequest(
                method=name,
                params=kwargs
            )
            response = await self.backend.execute(request)
            if response.success:
                return response.result
            else:
                raise Exception(response.error)
        
        # Add method to provider
        setattr(self, name, method_impl)
        
    def get_supported_methods(self):
        """Get methods from backend"""
        if self.backend:
            capabilities = self.backend.get_capabilities()
            return list(capabilities.methods.keys())
        return []
```

### Usage Example - Adding New Provider/Backend

```python
# 1. Create new backend (implement 3 methods)
class RedisExecutionBackend(ExecutionBackend):
    def get_capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            protocol="cache/v1",
            methods={
                "get": MethodSpec(...),
                "set": MethodSpec(...),
                "delete": MethodSpec(...)
            }
        )
    
    async def initialize(self):
        self._redis = await aioredis.create_redis_pool(...)
    
    async def cleanup(self):
        self._redis.close()
    
    async def _handle_get(self, key: str):
        return await self._redis.get(key)

# 2. Register backend
hub_factory.register_backend("cache/v1", RedisExecutionBackend)

# 3. Create provider (2 lines!)
provider = AutoBackendProvider(protocol="cache/v1")
await provider.initialize()

# 4. Use it
result = await provider.get(key="mykey")
```

## Key Design Decisions

### 1. **Method Discovery**
- Backends declare capabilities with full method specs
- Providers can auto-generate methods from specs
- Enables automatic documentation and validation

### 2. **Flexible Execution Modes**
- Support different patterns (simple, stream, batch, session)
- Backends declare which modes they support per method
- Graceful fallbacks for unsupported modes

### 3. **Resource Management**
- Built into base ExecutionBackend class
- Backends manage their own resources (pools, connections)
- Automatic cleanup on shutdown

### 4. **Error Handling**
- Standardized ExecutionResponse with success/error
- Backends can provide detailed error information
- Consistent error propagation to providers

### 5. **Configuration**
- Backends accept config dict in constructor
- Can be configured before initialization
- Supports both programmatic and file-based config

## Benefits of This Design

1. **Easy Provider Creation**
   - Use `AutoBackendProvider` for zero-code providers
   - Or extend for custom logic
   - Methods auto-generated from backend

2. **Easy Backend Creation**
   - Implement 3 required methods
   - Use base class helpers for common patterns
   - Declarative capability definition

3. **Discoverable**
   - Backends declare full capabilities
   - Can generate docs from capabilities
   - Can validate at runtime

4. **Testable**
   - Mock backends easily
   - Test providers without real backends
   - Capability-based testing

5. **Extensible**
   - Add new execution modes
   - Add new capability fields
   - Custom validation and transformation

## Open Questions

1. **Authentication** - Should backends handle auth or providers?
2. **Caching** - Should we add caching layer between provider and backend?
3. **Metrics** - How to collect metrics across all backends?
4. **Circuit Breakers** - Should we add circuit breaker pattern?
5. **Priority/QoS** - How to handle priority requests?

## Next Steps

1. Finalize the ExecutionBackend interface
2. Implement base class with helpers
3. Create first backend (OllamaExecutionBackend)
4. Create AutoBackendProvider
5. Test with real workflow