# Gleitzeit 0.0.7 Provider Architecture V2 - Clean Slate Design

## Executive Summary

With no backward compatibility constraints, we can design a clean, modern provider architecture that fully leverages the clustered event stream model while providing maximum simplicity, scalability, and maintainability.

## Core Design Principles

1. **Single Responsibility**: Each provider does one thing well
2. **Stateless Operation**: All state in Redis, providers are ephemeral
3. **Event-First**: All provider interactions through event streams
4. **Protocol Agnostic**: Providers implement protocols, not task types
5. **Cloud Native**: Built for Kubernetes/container orchestration from day one

## New Provider Architecture

### 1. Streamlined Provider Contract

```python
# src/gleitzeit/providers/core.py

from abc import ABC, abstractmethod
from typing import Dict, Any, AsyncIterator
from dataclasses import dataclass
import asyncio

@dataclass
class ExecutionRequest:
    """Standard execution request"""
    request_id: str
    method: str
    params: Dict[str, Any]
    timeout: int = 300
    priority: int = 0

@dataclass
class ExecutionResponse:
    """Standard execution response"""
    request_id: str
    status: str  # success, error, timeout
    result: Any = None
    error: Dict[str, Any] = None
    metrics: Dict[str, float] = None

class Provider(ABC):
    """Minimal provider interface"""

    protocol: str

    @abstractmethod
    async def execute(self, request: ExecutionRequest) -> ExecutionResponse:
        """Execute a single request"""
        pass

    @abstractmethod
    async def execute_stream(
        self,
        request: ExecutionRequest
    ) -> AsyncIterator[ExecutionResponse]:
        """Execute with streaming response"""
        pass

    @abstractmethod
    async def validate(self, request: ExecutionRequest) -> bool:
        """Validate if request can be handled"""
        pass
```

### 2. Event-Driven Provider Manager

```python
# src/gleitzeit/providers/manager.py

class ProviderManager:
    """Manages providers through event streams"""

    def __init__(self, redis_cluster):
        self.redis = redis_cluster
        self.providers: Dict[str, Provider] = {}
        self.event_stream = EventStream(redis_cluster)

    async def start(self):
        """Start listening to provider events"""
        async for event in self.event_stream.subscribe("provider:*"):
            await self.handle_event(event)

    async def handle_event(self, event):
        """Route events to appropriate providers"""
        if event.type == "provider:execute":
            provider = self.providers[event.protocol]
            request = ExecutionRequest(**event.data)

            # Execute in background, publish result via event
            asyncio.create_task(
                self.execute_and_publish(provider, request)
            )

    async def execute_and_publish(self, provider, request):
        """Execute and publish result as event"""
        try:
            response = await provider.execute(request)
            await self.event_stream.publish(
                f"provider:response:{request.request_id}",
                response
            )
        except Exception as e:
            await self.event_stream.publish(
                f"provider:error:{request.request_id}",
                {"error": str(e)}
            )
```

### 3. Simplified Provider Implementations

```python
# src/gleitzeit/providers/impl/python.py

class PythonProvider(Provider):
    """Clean Python execution provider"""

    protocol = "python/v2"

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.executor = ProcessPoolExecutor(
            max_workers=config.get("max_workers", 4)
        )

    async def execute(self, request: ExecutionRequest) -> ExecutionResponse:
        """Execute Python code in isolated process"""
        start_time = time.time()

        try:
            # Simple execution - no complex dependency management
            result = await asyncio.get_event_loop().run_in_executor(
                self.executor,
                self._run_python,
                request.params["code"],
                request.params.get("args", {})
            )

            return ExecutionResponse(
                request_id=request.request_id,
                status="success",
                result=result,
                metrics={"execution_time": time.time() - start_time}
            )
        except Exception as e:
            return ExecutionResponse(
                request_id=request.request_id,
                status="error",
                error={"message": str(e), "type": type(e).__name__}
            )

    def _run_python(self, code: str, args: Dict) -> Any:
        """Run Python code in subprocess"""
        # Clean, isolated execution
        namespace = {"args": args}
        exec(code, namespace)
        return namespace.get("result")

    async def execute_stream(self, request: ExecutionRequest):
        """Not implemented for Python provider"""
        yield await self.execute(request)

    async def validate(self, request: ExecutionRequest) -> bool:
        """Validate Python execution request"""
        return "code" in request.params
```

```python
# src/gleitzeit/providers/impl/http.py

class HTTPProvider(Provider):
    """Clean HTTP client provider"""

    protocol = "http/v2"

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(
                total=config.get("timeout", 30)
            )
        )

    async def execute(self, request: ExecutionRequest) -> ExecutionResponse:
        """Execute HTTP request"""
        params = request.params

        try:
            async with self.session.request(
                method=params.get("method", "GET"),
                url=params["url"],
                headers=params.get("headers"),
                json=params.get("body"),
                params=params.get("query")
            ) as response:
                return ExecutionResponse(
                    request_id=request.request_id,
                    status="success",
                    result={
                        "status": response.status,
                        "headers": dict(response.headers),
                        "body": await response.json() if response.content_type == "application/json" else await response.text()
                    }
                )
        except Exception as e:
            return ExecutionResponse(
                request_id=request.request_id,
                status="error",
                error={"message": str(e)}
            )

    async def execute_stream(self, request: ExecutionRequest):
        """Stream HTTP response"""
        params = request.params

        async with self.session.request(
            method=params.get("method", "GET"),
            url=params["url"],
            headers=params.get("headers")
        ) as response:
            async for chunk in response.content.iter_chunked(1024):
                yield ExecutionResponse(
                    request_id=request.request_id,
                    status="streaming",
                    result={"chunk": chunk.decode()}
                )
```

```python
# src/gleitzeit/providers/impl/llm.py

class LLMProvider(Provider):
    """Clean LLM provider for Ollama/OpenAI"""

    protocol = "llm/v2"

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.client = self._create_client(config)

    async def execute(self, request: ExecutionRequest) -> ExecutionResponse:
        """Execute LLM completion"""
        params = request.params

        try:
            response = await self.client.chat.completions.create(
                model=params.get("model", "llama2"),
                messages=params["messages"],
                temperature=params.get("temperature", 0.7),
                max_tokens=params.get("max_tokens", 1000)
            )

            return ExecutionResponse(
                request_id=request.request_id,
                status="success",
                result={
                    "content": response.choices[0].message.content,
                    "usage": response.usage.dict() if response.usage else {}
                }
            )
        except Exception as e:
            return ExecutionResponse(
                request_id=request.request_id,
                status="error",
                error={"message": str(e)}
            )

    async def execute_stream(self, request: ExecutionRequest):
        """Stream LLM response"""
        params = request.params

        stream = await self.client.chat.completions.create(
            model=params.get("model", "llama2"),
            messages=params["messages"],
            stream=True
        )

        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield ExecutionResponse(
                    request_id=request.request_id,
                    status="streaming",
                    result={"content": chunk.choices[0].delta.content}
                )
```

### 4. Provider Registry with Auto-Discovery

```python
# src/gleitzeit/providers/registry.py

class ProviderRegistry:
    """Simple provider registry with auto-discovery"""

    def __init__(self, redis_cluster):
        self.redis = redis_cluster
        self.providers: Dict[str, Type[Provider]] = {}
        self.instances: Dict[str, List[Provider]] = {}

    def discover_providers(self):
        """Auto-discover provider implementations"""
        import pkgutil
        import gleitzeit.providers.impl

        for importer, modname, ispkg in pkgutil.iter_modules(
            gleitzeit.providers.impl.__path__,
            gleitzeit.providers.impl.__name__ + "."
        ):
            module = importer.find_module(modname).load_module(modname)
            for name, obj in inspect.getmembers(module):
                if (inspect.isclass(obj) and
                    issubclass(obj, Provider) and
                    obj != Provider):
                    self.register(obj)

    def register(self, provider_class: Type[Provider]):
        """Register a provider class"""
        self.providers[provider_class.protocol] = provider_class

    async def instantiate(self, protocol: str, count: int = 3) -> List[Provider]:
        """Create provider instances"""
        provider_class = self.providers[protocol]
        config = await self.redis.hget(f"provider:config:{protocol}")

        instances = []
        for i in range(count):
            instance = provider_class(config or {})
            instances.append(instance)

        self.instances[protocol] = instances
        return instances
```

### 5. Provider Orchestrator

```python
# src/gleitzeit/providers/orchestrator.py

class ProviderOrchestrator:
    """Orchestrates provider execution across the cluster"""

    def __init__(self, redis_cluster):
        self.redis = redis_cluster
        self.registry = ProviderRegistry(redis_cluster)
        self.manager = ProviderManager(redis_cluster)
        self.load_balancer = RoundRobinBalancer()

    async def start(self):
        """Start the orchestrator"""
        # Discover and register providers
        self.registry.discover_providers()

        # Instantiate provider pools
        for protocol in self.registry.providers:
            instances = await self.registry.instantiate(protocol)
            for instance in instances:
                self.manager.providers[f"{protocol}:{id(instance)}"] = instance

        # Start manager
        await self.manager.start()

    async def execute(
        self,
        protocol: str,
        method: str,
        params: Dict[str, Any]
    ) -> ExecutionResponse:
        """Execute a provider method with load balancing"""
        # Select provider instance
        instances = self.registry.instances.get(protocol, [])
        if not instances:
            raise ValueError(f"No providers for protocol: {protocol}")

        provider = self.load_balancer.select(instances)

        # Create request
        request = ExecutionRequest(
            request_id=str(uuid.uuid4()),
            method=method,
            params=params
        )

        # Execute
        return await provider.execute(request)
```

### 6. Configuration System

```yaml
# config/providers.yaml

cluster:
  provider_pools:
    python:
      min_instances: 2
      max_instances: 10
      scale_metric: "queue_depth"
      scale_threshold: 100

    http:
      min_instances: 3
      max_instances: 20
      scale_metric: "request_rate"
      scale_threshold: 1000

    llm:
      min_instances: 1
      max_instances: 5
      scale_metric: "response_time"
      scale_threshold: 5000  # ms

providers:
  python/v2:
    max_workers: 4
    timeout: 300
    memory_limit: "512Mi"

  http/v2:
    timeout: 30
    max_connections: 100
    retry_count: 3

  llm/v2:
    backend: "ollama"  # or "openai"
    base_url: "http://localhost:11434"
    default_model: "llama2"
    timeout: 120
```

### 7. Kubernetes-Native Deployment

```yaml
# k8s/provider-deployment.yaml

apiVersion: apps/v1
kind: Deployment
metadata:
  name: gleitzeit-providers
spec:
  replicas: 3
  selector:
    matchLabels:
      app: gleitzeit-providers
  template:
    metadata:
      labels:
        app: gleitzeit-providers
    spec:
      containers:
      - name: provider-orchestrator
        image: gleitzeit/provider-orchestrator:0.0.7
        env:
        - name: REDIS_CLUSTER_NODES
          value: "redis-0:6379,redis-1:6379,redis-2:6379"
        - name: PROVIDER_CONFIG
          value: "/config/providers.yaml"
        volumeMounts:
        - name: config
          mountPath: /config
        resources:
          requests:
            memory: "256Mi"
            cpu: "500m"
          limits:
            memory: "1Gi"
            cpu: "2000m"
      volumes:
      - name: config
        configMap:
          name: provider-config
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: provider-autoscaler
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: gleitzeit-providers
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Pods
    pods:
      metric:
        name: provider_queue_depth
      target:
        type: AverageValue
        averageValue: "100"
```

## Implementation Roadmap

### Week 1: Core Framework
- [ ] Implement base `Provider` class
- [ ] Create `ProviderManager` with event handling
- [ ] Implement `ProviderRegistry` with auto-discovery
- [ ] Set up event streaming infrastructure

### Week 2: Provider Implementations
- [ ] Implement `PythonProvider` with process isolation
- [ ] Implement `HTTPProvider` with connection pooling
- [ ] Implement `LLMProvider` with streaming support
- [ ] Implement `TimerProvider` and `SignalProvider`

### Week 3: Orchestration & Scaling
- [ ] Implement `ProviderOrchestrator`
- [ ] Add load balancing strategies
- [ ] Implement auto-scaling logic
- [ ] Add health checking and circuit breakers

### Week 4: Production Features
- [ ] Add comprehensive metrics and tracing
- [ ] Implement provider middleware system
- [ ] Create Kubernetes operators
- [ ] Add provider composition/chaining

## Key Benefits of Clean Slate Design

### 1. **Simplicity**
- Single, clear provider interface
- No legacy compatibility code
- Clean separation of concerns

### 2. **Performance**
- Event-driven architecture reduces latency
- Efficient resource pooling
- Native streaming support

### 3. **Scalability**
- Horizontal scaling at provider level
- Kubernetes-native design
- Auto-scaling based on metrics

### 4. **Reliability**
- Process isolation for providers
- Automatic failover
- Circuit breaker patterns

### 5. **Developer Experience**
- Simple to add new providers
- Clear debugging path
- Comprehensive testing support

## Provider Development Guide

### Creating a New Provider

```python
# src/gleitzeit/providers/impl/custom.py

class CustomProvider(Provider):
    """Example custom provider"""

    protocol = "custom/v1"

    async def execute(self, request: ExecutionRequest) -> ExecutionResponse:
        # Your implementation here
        pass

    async def execute_stream(self, request: ExecutionRequest):
        # Streaming implementation (optional)
        pass

    async def validate(self, request: ExecutionRequest) -> bool:
        # Validation logic
        return True
```

That's it! The provider will be auto-discovered and registered.

## Testing Strategy

```python
# tests/test_provider.py

async def test_provider_execution():
    """Test provider execution"""
    provider = PythonProvider({})

    request = ExecutionRequest(
        request_id="test-1",
        method="exec",
        params={"code": "result = 1 + 1"}
    )

    response = await provider.execute(request)
    assert response.status == "success"
    assert response.result == 2

async def test_provider_orchestration():
    """Test full orchestration"""
    orchestrator = ProviderOrchestrator(redis_cluster)
    await orchestrator.start()

    response = await orchestrator.execute(
        protocol="python/v2",
        method="exec",
        params={"code": "result = sum(range(10))"}
    )

    assert response.result == 45
```

## Monitoring & Observability

### Metrics
- Provider execution latency
- Request queue depth per provider
- Success/error rates
- Resource utilization

### Events
- `provider:registered` - Provider registered
- `provider:execute` - Execution requested
- `provider:response` - Execution completed
- `provider:error` - Execution failed
- `provider:scaled` - Provider pool scaled

### Tracing
All provider executions include trace context for distributed tracing with OpenTelemetry.

## Conclusion

This clean slate design eliminates all the complexity of backward compatibility while providing a modern, scalable, and maintainable provider architecture. The event-driven design fits perfectly with the clustered architecture, and the simplified provider interface makes it easy to add new capabilities.

The system is designed to run efficiently in Kubernetes with automatic scaling, health checking, and observability built in from the start.