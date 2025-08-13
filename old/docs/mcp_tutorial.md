# Gleitzeit Socket.IO Provider System Tutorial

## Table of Contents
1. [Introduction](#introduction)
2. [Architecture Overview](#architecture-overview)
3. [Installation](#installation)
4. [Quick Start](#quick-start)
5. [Creating Providers](#creating-providers)
6. [Provider Manager](#provider-manager)
7. [Provider Discovery & Routing](#provider-discovery--routing)
8. [Streaming & Real-time Communication](#streaming--real-time-communication)
9. [Integration with Cluster](#integration-with-cluster)
10. [Best Practices](#best-practices)
11. [Migration from MCP](#migration-from-mcp)
12. [Troubleshooting](#troubleshooting)

## Introduction

The Gleitzeit Provider System uses Socket.IO for all provider communication, creating a unified architecture consistent with the rest of the Gleitzeit cluster. This replaces the previous MCP (Model Context Protocol) stdio-based approach.

### Why Socket.IO?

- **Unified Architecture**: All Gleitzeit components (cluster, executors, providers) use the same communication protocol
- **Real-time Capabilities**: Bidirectional streaming perfect for LLM responses
- **Better Monitoring**: Built-in health checks, heartbeats, and connection tracking
- **Load Balancing**: Socket.IO rooms enable distributing requests across multiple provider instances
- **Resilience**: Automatic reconnection and error recovery

### Provider Types

| Type | Purpose | Examples |
|------|---------|----------|
| **LLM** | Language model providers | OpenAI, Anthropic, Ollama, Custom models |
| **Tool** | External tools and services | Calculators, databases, APIs |
| **Extension** | Gleitzeit-specific functionality | Custom processors, analyzers |

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                   Gleitzeit Server                       │
│                                                          │
│  ┌──────────────┐        ┌─────────────────────────┐   │
│  │  Socket.IO   │        │   Provider Manager      │   │
│  │   Server     │◄──────►│                         │   │
│  │              │        │  • Provider Registry    │   │
│  │ /cluster     │        │  • Model Routing        │   │
│  │ /providers   │        │  • Health Monitoring    │   │
│  └──────────────┘        └─────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
         ▲                           ▲                ▲
         │                           │                │
    Socket.IO                   Socket.IO        Socket.IO
    /providers                  /providers       /providers
         │                           │                │
    ┌─────────┐                ┌─────────┐      ┌─────────┐
    │  OpenAI │                │  Tool   │      │ Custom  │
    │ Provider│                │Provider │      │   LLM   │
    └─────────┘                └─────────┘      └─────────┘
```

## Installation

```bash
# Install Gleitzeit with Socket.IO support
pip install gleitzeit

# Install additional dependencies for providers
pip install python-socketio[asyncio_client]
pip install aiohttp

# For specific providers (optional)
pip install openai  # For OpenAI provider
pip install anthropic  # For Anthropic provider
```

## Quick Start

### 1. Start Server with Provider Support

```python
import asyncio
from gleitzeit_extensions.socketio_provider_manager import SocketIOProviderManager
from gleitzeit_cluster.communication.socketio_server import SocketIOServer

async def start_server():
    # Create Socket.IO server
    server = SocketIOServer(
        host="0.0.0.0",
        port=8000,
        cors_allowed_origins="*"
    )
    
    # Create and attach provider manager
    provider_manager = SocketIOProviderManager()
    provider_manager.attach_to_server(server.sio)
    
    # Start server
    await server.start()
    
    # Start health monitoring
    asyncio.create_task(provider_manager.monitor_health())
    
    print(f"✅ Server running with provider support on port 8000")
    
    # Keep running
    await asyncio.Event().wait()

asyncio.run(start_server())
```

### 2. Create and Connect a Provider

```python
import asyncio
from gleitzeit_extensions.socketio_provider_client import SocketIOProviderClient

class MyLLMProvider(SocketIOProviderClient):
    def __init__(self):
        super().__init__(
            name="my-llm",
            provider_type="llm",
            server_url="http://localhost:8000",
            models=["model-7b", "model-13b"],
            capabilities=["text", "streaming"],
            description="My custom LLM"
        )
    
    async def invoke(self, method: str, **kwargs):
        if method == "complete":
            prompt = kwargs.get('prompt', '')
            return f"Response to: {prompt}"
        raise ValueError(f"Unknown method: {method}")
    
    async def get_health_status(self):
        return {"healthy": True, "status": "ready"}

# Run provider
async def main():
    provider = MyLLMProvider()
    await provider.run()

asyncio.run(main())
```

### 3. Use the Provider

```python
# From another client or within the cluster
async def use_provider(provider_manager):
    # Find provider for model
    provider_name = provider_manager.find_provider_for_model("model-7b")
    
    # Invoke provider
    result = await provider_manager.invoke_provider(
        provider_name,
        "complete",
        prompt="Hello, world!",
        model="model-7b"
    )
    
    print(f"Response: {result}")
```

## Creating Providers

### Base Provider Class

All providers inherit from `SocketIOProviderClient`:

```python
from gleitzeit_extensions.socketio_provider_client import SocketIOProviderClient
from typing import Any, Dict, List

class CustomProvider(SocketIOProviderClient):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(
            name=config['name'],
            provider_type=config['type'],  # "llm", "tool", or "extension"
            server_url=config.get('server_url', 'http://localhost:8000'),
            models=config.get('models', []),
            capabilities=config.get('capabilities', []),
            description=config.get('description', ''),
            metadata=config.get('metadata', {})
        )
        
        # Initialize your provider-specific resources
        self.config = config
    
    async def invoke(self, method: str, **kwargs) -> Any:
        """Handle method invocations - REQUIRED"""
        pass
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Return health status - REQUIRED"""
        return {"healthy": True}
    
    async def on_connected(self):
        """Called when connected - OPTIONAL"""
        pass
    
    async def on_disconnected(self):
        """Called when disconnected - OPTIONAL"""
        pass
```

### LLM Provider Example

```python
import openai
from typing import AsyncGenerator

class OpenAIProvider(SocketIOProviderClient):
    def __init__(self, api_key: str):
        super().__init__(
            name="openai",
            provider_type="llm",
            models=["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"],
            capabilities=["text", "vision", "function_calling", "streaming"],
            description="OpenAI GPT models"
        )
        self.client = openai.AsyncOpenAI(api_key=api_key)
    
    async def invoke(self, method: str, **kwargs) -> Any:
        if method == "complete":
            return await self._complete(**kwargs)
        elif method == "embed":
            return await self._embed(**kwargs)
        else:
            raise ValueError(f"Unknown method: {method}")
    
    async def _complete(self, prompt: str, model: str = "gpt-4", **kwargs):
        response = await self.client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            **kwargs
        )
        return response.choices[0].message.content
    
    async def _embed(self, text: str, model: str = "text-embedding-3-small"):
        response = await self.client.embeddings.create(
            model=model,
            input=text
        )
        return response.data[0].embedding
    
    async def stream(self, prompt: str, model: str = "gpt-4", **kwargs):
        """Stream responses token by token"""
        stream = await self.client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
            **kwargs
        )
        
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield {
                    "token": chunk.choices[0].delta.content,
                    "done": False
                }
        
        yield {"token": "", "done": True}
    
    async def get_health_status(self) -> Dict[str, Any]:
        try:
            # Test API connectivity
            models = await self.client.models.list()
            return {
                "healthy": True,
                "models_available": len(models.data)
            }
        except Exception as e:
            return {
                "healthy": False,
                "error": str(e)
            }
```

### Tool Provider Example

```python
class DatabaseProvider(SocketIOProviderClient):
    def __init__(self, connection_string: str):
        super().__init__(
            name="database",
            provider_type="tool",
            capabilities=["sql", "query", "crud"],
            description="Database operations"
        )
        self.connection_string = connection_string
        self.connection = None
    
    async def on_connected(self):
        """Initialize database connection"""
        # self.connection = await create_db_connection(self.connection_string)
        pass
    
    async def on_disconnected(self):
        """Close database connection"""
        # if self.connection:
        #     await self.connection.close()
        pass
    
    async def invoke(self, method: str, **kwargs) -> Any:
        if method == "query":
            return await self._query(**kwargs)
        elif method == "insert":
            return await self._insert(**kwargs)
        elif method == "update":
            return await self._update(**kwargs)
        elif method == "delete":
            return await self._delete(**kwargs)
        else:
            raise ValueError(f"Unknown method: {method}")
    
    async def _query(self, sql: str, params: List = None):
        # Execute query and return results
        return {"results": [], "count": 0}
    
    async def get_tools(self) -> List[Dict[str, Any]]:
        """Return available database operations"""
        return [
            {
                "name": "query",
                "description": "Execute SQL query",
                "parameters": {
                    "sql": {"type": "string", "description": "SQL query"},
                    "params": {"type": "array", "description": "Query parameters"}
                }
            },
            {
                "name": "insert",
                "description": "Insert record",
                "parameters": {
                    "table": {"type": "string"},
                    "data": {"type": "object"}
                }
            }
        ]
    
    async def get_health_status(self) -> Dict[str, Any]:
        return {
            "healthy": self.connection is not None,
            "connected": self.connection is not None
        }
```

## Provider Manager

The `SocketIOProviderManager` handles all provider operations on the server side:

### Key Features

```python
from gleitzeit_extensions.socketio_provider_manager import SocketIOProviderManager

# Create manager
manager = SocketIOProviderManager()

# Attach to existing Socket.IO server
manager.attach_to_server(sio_server)

# Get all providers
providers = manager.get_all_providers()
# Returns: {"provider_name": {"type": "llm", "models": [...], ...}}

# Find provider for model
provider = manager.find_provider_for_model("gpt-4")
# Returns: "openai"

# Find providers by capability
providers = manager.find_providers_by_capability("streaming")
# Returns: ["openai", "custom-llm"]

# Invoke provider method
result = await manager.invoke_provider(
    "openai",
    "complete",
    prompt="Hello",
    model="gpt-4"
)

# Start health monitoring
await manager.monitor_health(interval=30)
```

### Provider Registration Flow

1. Provider connects to Socket.IO server
2. Provider sends registration with metadata
3. Manager validates and stores provider info
4. Manager adds provider to appropriate rooms
5. Manager updates routing tables
6. Provider sends periodic heartbeats

## Provider Discovery & Routing

### Model-based Routing

```python
# Automatic routing based on model
async def route_by_model(manager, model: str, prompt: str):
    provider = manager.find_provider_for_model(model)
    
    if not provider:
        raise ValueError(f"No provider found for model: {model}")
    
    result = await manager.invoke_provider(
        provider,
        "complete",
        prompt=prompt,
        model=model
    )
    
    return result

# Example usage
response = await route_by_model(manager, "gpt-4", "Explain quantum computing")
```

### Capability-based Discovery

```python
# Find all providers that support streaming
streaming_providers = manager.find_providers_by_capability("streaming")

# Find all providers that support vision
vision_providers = manager.find_providers_by_capability("vision")

# Use the first available provider with a capability
async def use_any_streaming_provider(manager, prompt: str):
    providers = manager.find_providers_by_capability("streaming")
    
    if not providers:
        raise ValueError("No streaming providers available")
    
    # Use first available (could implement load balancing here)
    provider = providers[0]
    
    # Stream response
    async for chunk in manager.stream_from_provider(provider, prompt=prompt):
        print(chunk['token'], end='')
```

### Dynamic Provider Selection

```python
class SmartRouter:
    def __init__(self, manager: SocketIOProviderManager):
        self.manager = manager
    
    async def route_request(self, request: Dict[str, Any]):
        """Smart routing based on request characteristics"""
        
        # Check if specific model requested
        if 'model' in request:
            provider = self.manager.find_provider_for_model(request['model'])
            if provider:
                return provider
        
        # Check required capabilities
        required_capabilities = request.get('capabilities', [])
        if required_capabilities:
            candidates = set()
            for cap in required_capabilities:
                providers = self.manager.find_providers_by_capability(cap)
                if not candidates:
                    candidates = set(providers)
                else:
                    candidates &= set(providers)
            
            if candidates:
                # Could implement load balancing or cost optimization here
                return list(candidates)[0]
        
        # Default to any available LLM provider
        all_providers = self.manager.get_all_providers()
        llm_providers = [
            name for name, info in all_providers.items()
            if info['type'] == 'llm'
        ]
        
        if llm_providers:
            return llm_providers[0]
        
        raise ValueError("No suitable provider found")
```

## Streaming & Real-time Communication

### Implementing Streaming in Providers

```python
class StreamingProvider(SocketIOProviderClient):
    async def stream(self, prompt: str, **kwargs):
        """Implement streaming as an async generator"""
        
        # Simulate token generation
        tokens = prompt.split()
        
        for token in tokens:
            # Yield each token
            yield {
                "token": token + " ",
                "done": False,
                "metadata": {"timestamp": time.time()}
            }
            
            # Simulate processing time
            await asyncio.sleep(0.05)
        
        # Signal completion
        yield {
            "token": "",
            "done": True,
            "metadata": {"total_tokens": len(tokens)}
        }
```

### Consuming Streams

```python
async def consume_stream(manager, provider_name: str, prompt: str):
    """Consumer example for streaming responses"""
    
    stream_id = str(uuid.uuid4())
    response_buffer = []
    
    # Setup stream listener
    @manager.sio.on(f'stream:data', namespace='/providers')
    async def on_stream_data(data):
        if data['stream_id'] == stream_id:
            token = data['data']['token']
            response_buffer.append(token)
            print(token, end='', flush=True)
    
    @manager.sio.on(f'stream:end', namespace='/providers')
    async def on_stream_end(data):
        if data['stream_id'] == stream_id:
            print("\n✅ Stream completed")
    
    @manager.sio.on(f'stream:error', namespace='/providers')
    async def on_stream_error(data):
        if data['stream_id'] == stream_id:
            print(f"\n❌ Stream error: {data['error']}")
    
    # Start streaming
    await manager.sio.emit(
        'provider:stream',
        {
            'provider': provider_name,
            'stream_id': stream_id,
            'args': {'prompt': prompt}
        },
        namespace='/providers'
    )
    
    return ''.join(response_buffer)
```

## Integration with Cluster

### Adding Provider Manager to Cluster

```python
from gleitzeit_cluster.core.cluster import GleitzeitCluster
from gleitzeit_extensions.socketio_provider_manager import SocketIOProviderManager

async def setup_cluster_with_providers():
    # Create cluster
    cluster = GleitzeitCluster(
        enable_real_execution=True,
        auto_start_services=True
    )
    
    # Create provider manager
    provider_manager = SocketIOProviderManager()
    
    # Attach to cluster's Socket.IO server
    provider_manager.attach_to_server(cluster.socketio_server.sio)
    
    # Store reference in cluster
    cluster.provider_manager = provider_manager
    
    # Start cluster
    await cluster.start()
    
    return cluster, provider_manager
```

### Using Providers in Workflows

```python
from gleitzeit_cluster.core.task import Task
from gleitzeit_cluster.core.workflow import Workflow

async def create_llm_workflow(cluster):
    """Create workflow that uses LLM providers"""
    
    workflow = Workflow(workflow_id="llm-workflow")
    
    # Task that uses provider
    async def generate_text(context):
        provider_manager = context.get('provider_manager')
        prompt = context.get('prompt')
        
        # Find provider for model
        provider = provider_manager.find_provider_for_model("gpt-4")
        
        # Generate text
        result = await provider_manager.invoke_provider(
            provider,
            "complete",
            prompt=prompt,
            model="gpt-4"
        )
        
        return {"generated_text": result}
    
    task = Task(
        task_id="generate",
        task_type="llm_generation",
        handler=generate_text,
        context={"provider_manager": cluster.provider_manager}
    )
    
    workflow.add_task(task)
    
    return workflow
```

## Best Practices

### 1. Provider Implementation

```python
class BestPracticeProvider(SocketIOProviderClient):
    def __init__(self, config):
        # Validate configuration
        self._validate_config(config)
        
        super().__init__(
            name=config['name'],
            provider_type=config['type'],
            **config
        )
        
        # Initialize resources
        self.resources = {}
        self.metrics = {
            'requests': 0,
            'errors': 0,
            'latency': []
        }
    
    async def on_connected(self):
        """Initialize resources on connection"""
        try:
            await self._initialize_resources()
            logger.info(f"Provider {self.name} initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize: {e}")
            raise
    
    async def on_disconnected(self):
        """Cleanup resources on disconnection"""
        await self._cleanup_resources()
    
    async def invoke(self, method: str, **kwargs):
        """Handle invocations with error handling and metrics"""
        start_time = time.time()
        
        try:
            # Validate method
            if method not in self.get_supported_methods():
                raise ValueError(f"Unsupported method: {method}")
            
            # Execute method
            result = await self._execute_method(method, **kwargs)
            
            # Update metrics
            self.metrics['requests'] += 1
            self.metrics['latency'].append(time.time() - start_time)
            
            return result
            
        except Exception as e:
            self.metrics['errors'] += 1
            logger.error(f"Method {method} failed: {e}")
            raise
    
    async def get_health_status(self):
        """Comprehensive health check"""
        return {
            "healthy": await self._check_health(),
            "metrics": self.metrics,
            "resources": await self._check_resources()
        }
```

### 2. Connection Management

```python
class ResilientProvider(SocketIOProviderClient):
    def __init__(self, config):
        super().__init__(**config)
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 5  # seconds
    
    async def run_with_reconnect(self):
        """Run with automatic reconnection"""
        while self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                await self.connect()
                self.reconnect_attempts = 0  # Reset on successful connection
                
                # Run normally
                while self.connected:
                    await asyncio.sleep(1)
                    
            except Exception as e:
                logger.error(f"Connection failed: {e}")
                self.reconnect_attempts += 1
                
                if self.reconnect_attempts < self.max_reconnect_attempts:
                    wait_time = self.reconnect_delay * self.reconnect_attempts
                    logger.info(f"Reconnecting in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error("Max reconnection attempts reached")
                    raise
```

### 3. Load Balancing

```python
class LoadBalancedProviderManager(SocketIOProviderManager):
    def __init__(self):
        super().__init__()
        self.request_counts = {}  # Track requests per provider
    
    async def invoke_provider_balanced(self, provider_type: str, method: str, **kwargs):
        """Invoke with load balancing across providers of same type"""
        
        # Get all providers of the specified type
        all_providers = self.get_all_providers()
        candidates = [
            name for name, info in all_providers.items()
            if info['type'] == provider_type and info.get('health', {}).get('healthy', False)
        ]
        
        if not candidates:
            raise ValueError(f"No healthy {provider_type} providers available")
        
        # Select provider with least requests (simple round-robin)
        provider = min(
            candidates,
            key=lambda p: self.request_counts.get(p, 0)
        )
        
        # Update request count
        self.request_counts[provider] = self.request_counts.get(provider, 0) + 1
        
        # Invoke provider
        return await self.invoke_provider(provider, method, **kwargs)
```

### 4. Monitoring & Observability

```python
import prometheus_client

class MonitoredProvider(SocketIOProviderClient):
    def __init__(self, config):
        super().__init__(**config)
        
        # Prometheus metrics
        self.request_counter = prometheus_client.Counter(
            'provider_requests_total',
            'Total provider requests',
            ['provider', 'method']
        )
        
        self.request_duration = prometheus_client.Histogram(
            'provider_request_duration_seconds',
            'Provider request duration',
            ['provider', 'method']
        )
        
        self.error_counter = prometheus_client.Counter(
            'provider_errors_total',
            'Total provider errors',
            ['provider', 'method', 'error_type']
        )
    
    async def invoke(self, method: str, **kwargs):
        """Invoke with monitoring"""
        
        with self.request_duration.labels(
            provider=self.name,
            method=method
        ).time():
            try:
                self.request_counter.labels(
                    provider=self.name,
                    method=method
                ).inc()
                
                result = await self._execute_method(method, **kwargs)
                return result
                
            except Exception as e:
                self.error_counter.labels(
                    provider=self.name,
                    method=method,
                    error_type=type(e).__name__
                ).inc()
                raise
```

## Migration from MCP

If you're migrating from the MCP-based system to Socket.IO providers:

### 1. Convert MCP Server to Socket.IO Provider

**Before (MCP):**
```python
# MCP server configuration
{
    "name": "openai",
    "command": "mcp-server-openai",
    "env": {"OPENAI_API_KEY": "..."},
    "models": ["gpt-4"],
    "capabilities": ["text"]
}
```

**After (Socket.IO):**
```python
from gleitzeit_extensions.socketio_provider_client import SocketIOProviderClient

class OpenAISocketIOProvider(SocketIOProviderClient):
    def __init__(self, api_key: str):
        super().__init__(
            name="openai",
            provider_type="llm",
            models=["gpt-4"],
            capabilities=["text"],
            server_url="http://localhost:8000"
        )
        self.api_key = api_key
    
    async def invoke(self, method: str, **kwargs):
        # Implement OpenAI API calls
        pass
    
    async def get_health_status(self):
        return {"healthy": True}

# Run provider
provider = OpenAISocketIOProvider(api_key="...")
await provider.run()
```

### 2. Update Manager Usage

**Before (MCP):**
```python
from gleitzeit_extensions.mcp_client import MCPClientManager

manager = MCPClientManager()
manager.add_server(name="openai", command="mcp-server-openai")
await manager.connect_server("openai")
result = await manager.call_tool("openai", "complete", {"prompt": "..."})
```

**After (Socket.IO):**
```python
from gleitzeit_extensions.socketio_provider_manager import SocketIOProviderManager

manager = SocketIOProviderManager()
manager.attach_to_server(sio_server)
# Providers connect automatically
result = await manager.invoke_provider("openai", "complete", prompt="...")
```

### 3. Migration Checklist

- [ ] Replace MCP server executables with Socket.IO provider implementations
- [ ] Update server to use `SocketIOProviderManager` instead of `MCPClientManager`
- [ ] Convert MCP configuration files to provider initialization code
- [ ] Update client code to use new provider invocation methods
- [ ] Test streaming functionality with Socket.IO events
- [ ] Verify health monitoring and heartbeats
- [ ] Update deployment scripts to start Socket.IO providers

## Troubleshooting

### Provider Won't Connect

**Problem:** Provider fails to connect to Socket.IO server

**Solutions:**

1. **Check server is running with provider support:**
   ```python
   # Ensure provider manager is attached
   manager = SocketIOProviderManager()
   manager.attach_to_server(server.sio)
   ```

2. **Verify correct server URL:**
   ```python
   provider = MyProvider(server_url="http://localhost:8000")  # Correct port
   ```

3. **Check namespace handlers are registered:**
   ```python
   # Server should have /providers namespace
   if '/providers' not in server.sio.namespace_handlers:
       print("Provider namespace not registered!")
   ```

4. **Enable debug logging:**
   ```python
   import logging
   logging.basicConfig(level=logging.DEBUG)
   ```

### Provider Not Found

**Problem:** `find_provider_for_model()` returns None

**Solutions:**

1. **Check provider is connected:**
   ```python
   all_providers = manager.get_all_providers()
   print(f"Connected providers: {list(all_providers.keys())}")
   ```

2. **Verify model list:**
   ```python
   provider_info = manager.get_all_providers().get('provider_name')
   print(f"Models: {provider_info['models']}")
   ```

3. **Clear routing cache:**
   ```python
   manager._model_routing.clear()
   provider = manager.find_provider_for_model("model_name")
   ```

### Streaming Not Working

**Problem:** Stream events not received

**Solutions:**

1. **Implement streaming in provider:**
   ```python
   async def stream(self, **kwargs):
       for chunk in data:
           yield {"token": chunk, "done": False}
       yield {"token": "", "done": True}
   ```

2. **Handle stream events on client:**
   ```python
   @sio.on('stream:data', namespace='/providers')
   async def on_stream_data(data):
       print(f"Received: {data}")
   ```

3. **Check stream ID matching:**
   ```python
   # Ensure stream_id is consistent between start and data events
   ```

### Health Check Failures

**Problem:** Provider marked as unhealthy

**Solutions:**

1. **Implement proper health check:**
   ```python
   async def get_health_status(self):
       try:
           # Test actual functionality
           await self.test_connection()
           return {"healthy": True}
       except Exception as e:
           return {"healthy": False, "error": str(e)}
   ```

2. **Send regular heartbeats:**
   ```python
   # Heartbeats are sent automatically by base class
   # Adjust interval if needed:
   provider._heartbeat_interval = 15  # seconds
   ```

3. **Monitor stale connections:**
   ```python
   # Server-side monitoring
   await manager.monitor_health(interval=30)
   ```

## Conclusion

The Socket.IO-based provider system offers a unified, real-time communication architecture for Gleitzeit. Key advantages:

- **Consistency**: All components use Socket.IO
- **Real-time**: Perfect for streaming LLM responses
- **Resilient**: Built-in reconnection and health monitoring
- **Scalable**: Support for multiple provider instances
- **Flexible**: Easy to add new provider types

For more information:
- [Socket.IO Documentation](https://socket.io/docs/v4/)
- [Gleitzeit Documentation](https://github.com/leifk/gleitzeit)
- [Example Providers](https://github.com/leifk/gleitzeit/tree/main/examples)