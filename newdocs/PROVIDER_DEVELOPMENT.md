# Provider Development Guide

## Overview

Providers in Gleitzeit v0.0.5 are responsible for executing protocol methods. They implement specific protocols (like LLM, Python, MCP) and use Resource Hubs to access compute resources. This guide explains how to create custom providers.

## Provider Architecture

```
┌────────────────────────────────────────┐
│            Protocol Request             │
│         (method, parameters)            │
└──────────────────┬─────────────────────┘
                   │
┌──────────────────▼─────────────────────┐
│              Provider                  │
│                                        │
│  • Validates parameters                │
│  • Requests resources from Hub         │
│  • Executes protocol method            │
│  • Formats and returns results         │
└──────────────────┬─────────────────────┘
                   │
┌──────────────────▼─────────────────────┐
│           Resource Hub                 │
│      (Provides compute resources)      │
└────────────────────────────────────────┘
```

## Base Provider Class

All providers inherit from `ProtocolProvider`:

```python
from gleitzeit.providers.base import ProtocolProvider
from typing import Dict, Any, Optional, List

class ProtocolProvider(ABC):
    """Base class for all protocol providers"""
    
    def __init__(
        self,
        provider_id: str,
        protocol_id: str,
        name: str,
        version: str = "1.0.0",
        capabilities: Optional[List[str]] = None
    ):
        self.provider_id = provider_id
        self.protocol_id = protocol_id
        self.name = name
        self.version = version
        self.capabilities = capabilities or []
        self.metadata = {}
    
    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the provider"""
        pass
    
    @abstractmethod
    async def handle_request(
        self,
        method: str,
        params: Dict[str, Any]
    ) -> Any:
        """Handle a protocol method request"""
        pass
    
    @abstractmethod
    async def shutdown(self) -> None:
        """Clean shutdown of the provider"""
        pass
    
    async def validate_parameters(
        self,
        method: str,
        params: Dict[str, Any]
    ) -> bool:
        """Validate parameters for a method"""
        # Override for custom validation
        return True
    
    def supports_method(self, method: str) -> bool:
        """Check if provider supports a method"""
        return method in self.capabilities
```

## Creating a Custom Provider

### Step 1: Define Your Protocol

```python
# protocols/custom_protocol.py
CUSTOM_PROTOCOL = {
    "id": "custom/v1",
    "name": "Custom Protocol",
    "version": "1.0.0",
    "methods": {
        "process": {
            "description": "Process custom data",
            "parameters": {
                "input": {"type": "string", "required": True},
                "options": {"type": "object", "required": False}
            },
            "returns": {"type": "object"}
        },
        "analyze": {
            "description": "Analyze custom data",
            "parameters": {
                "data": {"type": "array", "required": True},
                "mode": {"type": "string", "enum": ["fast", "detailed"]}
            },
            "returns": {"type": "object"}
        }
    }
}
```

### Step 2: Implement the Provider

```python
from gleitzeit.providers.base import ProtocolProvider
from gleitzeit.hub.base import ResourceHub
from typing import Dict, Any, Optional
import aiohttp

class CustomProvider(ProtocolProvider):
    """Provider for custom protocol operations"""
    
    def __init__(
        self,
        provider_id: str = "custom",
        custom_hub: Optional[ResourceHub] = None,
        api_key: Optional[str] = None
    ):
        super().__init__(
            provider_id=provider_id,
            protocol_id="custom/v1",
            name="Custom Protocol Provider",
            version="1.0.0",
            capabilities=["process", "analyze"]
        )
        self.hub = custom_hub
        self.api_key = api_key
        self.session = None
    
    async def initialize(self) -> None:
        """Initialize HTTP session and validate configuration"""
        self.session = aiohttp.ClientSession()
        
        # Initialize hub if provided
        if self.hub:
            await self.hub.initialize()
        
        # Validate API key if required
        if not self.api_key:
            raise ValueError("API key required for CustomProvider")
    
    async def handle_request(
        self,
        method: str,
        params: Dict[str, Any]
    ) -> Any:
        """Route method to appropriate handler"""
        
        # Validate method is supported
        if not self.supports_method(method):
            raise ValueError(f"Method {method} not supported")
        
        # Validate parameters
        if not await self.validate_parameters(method, params):
            raise ValueError(f"Invalid parameters for {method}")
        
        # Route to method handler
        if method == "process":
            return await self._handle_process(params)
        elif method == "analyze":
            return await self._handle_analyze(params)
        else:
            raise ValueError(f"Unknown method: {method}")
    
    async def _handle_process(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle process method"""
        
        # Get resource from hub if available
        instance = None
        if self.hub:
            instance = await self.hub.get_available_instance()
            if not instance:
                raise RuntimeError("No instances available")
        
        # Process using instance or fallback
        endpoint = instance.endpoint if instance else "https://api.custom.com"
        
        async with self.session.post(
            f"{endpoint}/process",
            json={
                "input": params["input"],
                "options": params.get("options", {})
            },
            headers={"Authorization": f"Bearer {self.api_key}"}
        ) as response:
            result = await response.json()
        
        return {
            "result": result,
            "provider_id": self.provider_id,
            "instance_used": instance.id if instance else "external"
        }
    
    async def _handle_analyze(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle analyze method"""
        
        # Implementation for analyze method
        mode = params.get("mode", "fast")
        data = params["data"]
        
        # Perform analysis (simplified)
        analysis = {
            "count": len(data),
            "mode": mode,
            "summary": f"Analyzed {len(data)} items in {mode} mode"
        }
        
        if mode == "detailed":
            # Add detailed analysis
            analysis["details"] = [
                {"item": item, "score": len(str(item))}
                for item in data
            ]
        
        return {
            "analysis": analysis,
            "provider_id": self.provider_id
        }
    
    async def validate_parameters(
        self,
        method: str,
        params: Dict[str, Any]
    ) -> bool:
        """Validate parameters against protocol spec"""
        
        if method == "process":
            return "input" in params
        elif method == "analyze":
            return "data" in params and isinstance(params["data"], list)
        
        return False
    
    async def shutdown(self) -> None:
        """Clean shutdown"""
        if self.session:
            await self.session.close()
        if self.hub:
            await self.hub.stop()
```

### Step 3: Create a Custom Hub (Optional)

```python
from gleitzeit.hub.base import ResourceHub, ResourceInstance, ResourceStatus
from gleitzeit.hub.configs import BaseConfig
from dataclasses import dataclass
from typing import Optional

@dataclass
class CustomConfig(BaseConfig):
    """Configuration for custom resource"""
    endpoint: str
    api_key: str
    max_requests_per_minute: int = 60
    timeout: int = 30

class CustomHub(ResourceHub[CustomConfig]):
    """Hub for managing custom resources"""
    
    def __init__(self, hub_id: str = "custom-hub"):
        super().__init__(
            hub_id=hub_id,
            resource_type="CUSTOM",
            max_instances=10,
            health_check_interval=60
        )
        self.session = None
    
    async def initialize(self) -> None:
        """Initialize the hub"""
        await super().initialize()
        import aiohttp
        self.session = aiohttp.ClientSession()
    
    async def start_instance(self, config: CustomConfig) -> ResourceInstance:
        """Register a custom API endpoint as instance"""
        
        # Create instance representation
        instance = ResourceInstance(
            id=f"custom-{config.endpoint.replace('/', '-')}",
            name=f"Custom API at {config.endpoint}",
            type="CUSTOM",
            endpoint=config.endpoint,
            status=ResourceStatus.STARTING,
            config=config,
            metadata={
                "api_key": config.api_key,
                "rate_limit": config.max_requests_per_minute
            }
        )
        
        # Test the endpoint
        if await self.check_health(instance):
            instance.status = ResourceStatus.HEALTHY
        else:
            instance.status = ResourceStatus.UNHEALTHY
        
        # Register instance
        await self.register_instance_object(instance)
        
        return instance
    
    async def stop_instance(self, instance_id: str) -> None:
        """Stop tracking an instance"""
        if instance_id in self.instances:
            instance = self.instances[instance_id]
            instance.status = ResourceStatus.STOPPED
            del self.instances[instance_id]
    
    async def check_health(self, instance: ResourceInstance) -> bool:
        """Check if custom API is healthy"""
        try:
            async with self.session.get(
                f"{instance.endpoint}/health",
                timeout=5,
                headers={"Authorization": f"Bearer {instance.metadata['api_key']}"}
            ) as response:
                return response.status == 200
        except:
            return False
```

## Advanced Provider Features

### 1. Streaming Support

```python
class StreamingProvider(ProtocolProvider):
    """Provider with streaming support"""
    
    async def handle_stream_request(
        self,
        method: str,
        params: Dict[str, Any],
        stream_callback: Callable
    ) -> None:
        """Handle streaming request"""
        
        instance = await self.hub.get_available_instance()
        
        async with self.session.post(
            f"{instance.endpoint}/stream",
            json=params,
            headers={"Accept": "text/event-stream"}
        ) as response:
            async for line in response.content:
                if line:
                    data = json.loads(line.decode())
                    await stream_callback(data)
```

### 2. Batch Processing

```python
class BatchProvider(ProtocolProvider):
    """Provider with batch processing support"""
    
    async def handle_batch_request(
        self,
        method: str,
        batch_params: List[Dict[str, Any]]
    ) -> List[Any]:
        """Process multiple requests in parallel"""
        
        # Get multiple instances for parallel processing
        instances = await self.hub.get_instances(count=min(len(batch_params), 5))
        
        # Create tasks for parallel execution
        tasks = []
        for i, params in enumerate(batch_params):
            instance = instances[i % len(instances)]
            task = self._process_single(instance, method, params)
            tasks.append(task)
        
        # Execute in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle errors
        final_results = []
        for result in results:
            if isinstance(result, Exception):
                final_results.append({"error": str(result)})
            else:
                final_results.append(result)
        
        return final_results
```

### 3. Caching Support

```python
class CachingProvider(ProtocolProvider):
    """Provider with built-in caching"""
    
    def __init__(self, *args, cache_ttl: int = 3600, **kwargs):
        super().__init__(*args, **kwargs)
        self.cache = {}
        self.cache_ttl = cache_ttl
    
    async def handle_request(
        self,
        method: str,
        params: Dict[str, Any]
    ) -> Any:
        """Handle request with caching"""
        
        # Generate cache key
        cache_key = self._generate_cache_key(method, params)
        
        # Check cache
        if cache_key in self.cache:
            entry = self.cache[cache_key]
            if (datetime.now() - entry['timestamp']).seconds < self.cache_ttl:
                return entry['result']
        
        # Execute request
        result = await super().handle_request(method, params)
        
        # Cache result
        self.cache[cache_key] = {
            'result': result,
            'timestamp': datetime.now()
        }
        
        return result
    
    def _generate_cache_key(self, method: str, params: Dict) -> str:
        """Generate cache key from method and params"""
        import hashlib
        import json
        
        key_data = f"{method}:{json.dumps(params, sort_keys=True)}"
        return hashlib.sha256(key_data.encode()).hexdigest()
```

### 4. Retry Logic

```python
class ResilientProvider(ProtocolProvider):
    """Provider with retry logic"""
    
    async def handle_request_with_retry(
        self,
        method: str,
        params: Dict[str, Any],
        max_retries: int = 3,
        backoff_factor: float = 2.0
    ) -> Any:
        """Handle request with exponential backoff retry"""
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                return await self.handle_request(method, params)
            
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = backoff_factor ** attempt
                    await asyncio.sleep(wait_time)
                    
                    # Try different instance if available
                    if self.hub:
                        await self.hub.mark_instance_unhealthy(
                            self.last_used_instance
                        )
        
        raise last_error
```

## Provider Registration

### Register with Registry

```python
from gleitzeit.core.registry import ProtocolProviderRegistry

# Create registry
registry = ProtocolProviderRegistry()

# Register protocol
await registry.register_protocol(CUSTOM_PROTOCOL)

# Create and register provider
provider = CustomProvider(
    provider_id="custom-provider",
    custom_hub=custom_hub,
    api_key="secret-key"
)

await provider.initialize()
await registry.register_provider("custom/v1", provider)

# Provider is now available for use
provider = await registry.get_provider_for_method("custom/process")
```

### Integration with ExecutionEngine

```python
from gleitzeit.core.execution_engine import ExecutionEngine

# Create engine with registry
engine = ExecutionEngine(
    registry=registry,
    persistence=persistence
)

# Engine will automatically route tasks to your provider
result = await engine.execute_task({
    "id": "task-1",
    "protocol": "custom/v1",
    "method": "process",
    "parameters": {
        "input": "test data",
        "options": {"mode": "fast"}
    }
})
```

## Testing Your Provider

### Unit Tests

```python
import pytest
from unittest.mock import Mock, AsyncMock

@pytest.fixture
async def mock_hub():
    """Create mock hub for testing"""
    hub = Mock()
    hub.get_available_instance = AsyncMock(return_value=Mock(
        id="test-instance",
        endpoint="http://test.local",
        status="HEALTHY"
    ))
    return hub

@pytest.fixture
async def provider(mock_hub):
    """Create provider with mock hub"""
    provider = CustomProvider(
        provider_id="test",
        custom_hub=mock_hub,
        api_key="test-key"
    )
    await provider.initialize()
    return provider

@pytest.mark.asyncio
async def test_process_method(provider):
    """Test process method"""
    result = await provider.handle_request(
        "process",
        {"input": "test", "options": {}}
    )
    
    assert result["provider_id"] == "test"
    assert "result" in result

@pytest.mark.asyncio
async def test_parameter_validation(provider):
    """Test parameter validation"""
    # Missing required parameter
    with pytest.raises(ValueError):
        await provider.handle_request("process", {})
    
    # Invalid parameter type
    with pytest.raises(ValueError):
        await provider.handle_request("analyze", {"data": "not-a-list"})

@pytest.mark.asyncio
async def test_unsupported_method(provider):
    """Test unsupported method handling"""
    with pytest.raises(ValueError, match="not supported"):
        await provider.handle_request("unknown", {})
```

### Integration Tests

```python
@pytest.mark.integration
async def test_provider_with_real_hub():
    """Test provider with real hub"""
    # Create real hub
    hub = CustomHub()
    await hub.initialize()
    
    # Register instance
    config = CustomConfig(
        endpoint="http://localhost:8080",
        api_key="real-key"
    )
    instance = await hub.start_instance(config)
    
    # Create provider
    provider = CustomProvider(
        custom_hub=hub,
        api_key="real-key"
    )
    await provider.initialize()
    
    # Execute request
    result = await provider.handle_request(
        "process",
        {"input": "integration test"}
    )
    
    assert result["instance_used"] == instance.id
    
    # Cleanup
    await provider.shutdown()
    await hub.stop()
```

## Best Practices

### 1. Proper Resource Management
```python
class Provider(ProtocolProvider):
    async def handle_request(self, method, params):
        instance = None
        try:
            # Always get instance from hub
            instance = await self.hub.get_available_instance()
            result = await self._execute(instance, method, params)
            return result
        except Exception as e:
            # Report errors to hub for metrics
            if instance:
                await self.hub.report_error(instance.id, e)
            raise
```

### 2. Parameter Validation
```python
def validate_parameters(self, method: str, params: Dict) -> bool:
    """Comprehensive parameter validation"""
    spec = self.protocol_spec["methods"][method]
    
    for param_name, param_spec in spec["parameters"].items():
        if param_spec.get("required") and param_name not in params:
            raise ValueError(f"Missing required parameter: {param_name}")
        
        if param_name in params:
            value = params[param_name]
            expected_type = param_spec["type"]
            
            if not self._check_type(value, expected_type):
                raise TypeError(
                    f"Parameter {param_name} must be {expected_type}"
                )
    
    return True
```

### 3. Error Handling
```python
async def handle_request(self, method, params):
    try:
        return await self._execute(method, params)
    except ValidationError as e:
        return {"error": f"Validation failed: {e}", "code": "VALIDATION_ERROR"}
    except ResourceUnavailable as e:
        return {"error": f"No resources: {e}", "code": "RESOURCE_UNAVAILABLE"}
    except Exception as e:
        logger.error(f"Unexpected error in {method}: {e}")
        return {"error": "Internal error", "code": "INTERNAL_ERROR"}
```

### 4. Metrics Collection
```python
class MetricsProvider(ProtocolProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.metrics = {
            "requests": 0,
            "errors": 0,
            "total_latency": 0
        }
    
    async def handle_request(self, method, params):
        start_time = time.time()
        try:
            result = await super().handle_request(method, params)
            self.metrics["requests"] += 1
            return result
        except Exception as e:
            self.metrics["errors"] += 1
            raise
        finally:
            self.metrics["total_latency"] += time.time() - start_time
```

## Provider Lifecycle

### Initialization Phase
```python
async def initialize(self):
    """Complete initialization checklist"""
    # 1. Initialize dependencies
    self.session = aiohttp.ClientSession()
    
    # 2. Initialize hub if present
    if self.hub:
        await self.hub.initialize()
    
    # 3. Validate configuration
    self._validate_config()
    
    # 4. Warm up connections
    await self._warmup()
    
    # 5. Register with discovery service
    await self._register_with_discovery()
```

### Shutdown Phase
```python
async def shutdown(self):
    """Complete shutdown checklist"""
    # 1. Stop accepting new requests
    self.accepting_requests = False
    
    # 2. Wait for active requests
    await self._wait_for_active_requests()
    
    # 3. Close connections
    if self.session:
        await self.session.close()
    
    # 4. Shutdown hub
    if self.hub:
        await self.hub.stop()
    
    # 5. Unregister from discovery
    await self._unregister_from_discovery()
```

## Summary

Creating a custom provider in Gleitzeit v0.0.5 involves:
1. **Defining your protocol** specification
2. **Implementing the provider** class with proper method handlers
3. **Creating a custom hub** if you need resource management
4. **Registering the provider** with the registry
5. **Testing thoroughly** with mocks and integration tests
6. **Following best practices** for resource management and error handling

The provider architecture ensures clean separation between protocol execution and resource management, making your providers testable, maintainable, and scalable.