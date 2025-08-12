# Gleitzeit Provider Tutorial

This tutorial will guide you through creating, configuring, and managing providers in the Gleitzeit cluster system. Providers extend Gleitzeit's capabilities by connecting to external services like LLMs, tools, and other resources.

## Table of Contents

1. [What are Providers?](#what-are-providers)
2. [Provider Types](#provider-types)
3. [Quick Start](#quick-start)
4. [Creating Your First Provider](#creating-your-first-provider)
5. [Configuration Management](#configuration-management)
6. [Advanced Provider Development](#advanced-provider-development)
7. [Best Practices](#best-practices)
8. [Troubleshooting](#troubleshooting)

## What are Providers?

Providers are Socket.IO-based services that extend Gleitzeit's capabilities. They run as separate processes and communicate with the cluster through real-time bidirectional connections. This architecture provides:

- **Isolation**: Providers run independently and can crash/restart without affecting the cluster
- **Scalability**: Multiple provider instances can run across different machines
- **Flexibility**: Mix and match different types of providers (LLMs, tools, extensions)
- **Real-time Communication**: Streaming responses and live status updates

## Provider Types

Gleitzeit supports three main provider types:

### LLM Providers
Connect to language models (local or remote):
- **Ollama**: Local models (llama3, phi3, etc.)
- **OpenAI**: GPT-4, GPT-3.5-turbo
- **Anthropic**: Claude models
- **Custom APIs**: Any REST/streaming LLM service

### Tool Providers
Provide specialized functionality:
- **File Operations**: Reading, writing, searching files
- **Web Services**: API calls, web scraping
- **System Tools**: Command execution, monitoring
- **Data Processing**: Calculations, transformations

### Extension Providers
Advanced integrations:
- **Database Connectors**: SQL, NoSQL, vector databases
- **Cloud Services**: AWS, GCP, Azure integrations
- **Custom Business Logic**: Domain-specific operations

## Quick Start

### 1. Check Existing Configuration

```bash
# View current provider configuration
gleitzeit config show

# List configured providers
gleitzeit config providers
```

### 2. Start with Pre-configured Ollama

If you have Ollama running locally:

```bash
# Validate the configuration
gleitzeit config validate

# Start the cluster with providers
gleitzeit serve --provider-config config/providers.yaml
```

### 3. Test Provider Integration

```bash
# List available providers
gleitzeit providers list

# Check provider health
gleitzeit providers health ollama

# Test a simple generation
gleitzeit providers invoke ollama generate --args '{"prompt": "Hello world!", "model": "llama3.2"}'
```

## Creating Your First Provider

Let's create a simple calculator tool provider:

### Step 1: Create the Provider Class

Create `my_calculator_provider.py`:

```python
#!/usr/bin/env python3
"""
Calculator Tool Provider for Gleitzeit

Provides basic mathematical operations
"""

import asyncio
import math
from typing import Any, Dict
from gleitzeit_extensions.socketio_provider_client import SocketIOProviderClient

class CalculatorProvider(SocketIOProviderClient):
    """Provider for mathematical calculations"""
    
    def __init__(self, **kwargs):
        super().__init__(
            name="calculator",
            provider_type="tool",
            models=["basic-math", "advanced-math"],
            capabilities=["arithmetic", "trigonometry", "logarithms"],
            description="Mathematical calculation provider",
            **kwargs
        )
    
    async def invoke(self, method: str, **kwargs) -> Any:
        """Handle calculation requests"""
        
        if method == "add":
            return await self._add(kwargs)
        elif method == "subtract":
            return await self._subtract(kwargs)
        elif method == "multiply":
            return await self._multiply(kwargs)
        elif method == "divide":
            return await self._divide(kwargs)
        elif method == "sin":
            return await self._sin(kwargs)
        elif method == "cos":
            return await self._cos(kwargs)
        elif method == "log":
            return await self._log(kwargs)
        else:
            raise ValueError(f"Unknown method: {method}")
    
    async def _add(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add two numbers"""
        a = params.get("a", 0)
        b = params.get("b", 0)
        result = a + b
        
        return {
            "operation": "addition",
            "inputs": {"a": a, "b": b},
            "result": result,
            "expression": f"{a} + {b} = {result}"
        }
    
    async def _subtract(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Subtract two numbers"""
        a = params.get("a", 0)
        b = params.get("b", 0)
        result = a - b
        
        return {
            "operation": "subtraction", 
            "inputs": {"a": a, "b": b},
            "result": result,
            "expression": f"{a} - {b} = {result}"
        }
    
    async def _multiply(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Multiply two numbers"""
        a = params.get("a", 1)
        b = params.get("b", 1)
        result = a * b
        
        return {
            "operation": "multiplication",
            "inputs": {"a": a, "b": b}, 
            "result": result,
            "expression": f"{a} * {b} = {result}"
        }
    
    async def _divide(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Divide two numbers"""
        a = params.get("a", 1)
        b = params.get("b", 1)
        
        if b == 0:
            raise ValueError("Division by zero is not allowed")
        
        result = a / b
        
        return {
            "operation": "division",
            "inputs": {"a": a, "b": b},
            "result": result,
            "expression": f"{a} / {b} = {result}"
        }
    
    async def _sin(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate sine of angle in radians"""
        x = params.get("x", 0)
        result = math.sin(x)
        
        return {
            "operation": "sine",
            "inputs": {"x": x},
            "result": result,
            "expression": f"sin({x}) = {result}"
        }
    
    async def _cos(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate cosine of angle in radians"""
        x = params.get("x", 0)
        result = math.cos(x)
        
        return {
            "operation": "cosine",
            "inputs": {"x": x},
            "result": result,
            "expression": f"cos({x}) = {result}"
        }
    
    async def _log(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate natural logarithm"""
        x = params.get("x", 1)
        
        if x <= 0:
            raise ValueError("Logarithm input must be positive")
        
        result = math.log(x)
        
        return {
            "operation": "natural_log",
            "inputs": {"x": x},
            "result": result,
            "expression": f"ln({x}) = {result}"
        }
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Check provider health"""
        try:
            # Test basic operations
            await self._add({"a": 1, "b": 1})
            await self._sin({"x": 0})
            
            return {
                "healthy": True,
                "capabilities": self.capabilities,
                "available_methods": ["add", "subtract", "multiply", "divide", "sin", "cos", "log"],
                "test_results": "All operations working"
            }
        except Exception as e:
            return {
                "healthy": False,
                "error": str(e)
            }

# Standalone execution for testing
async def main():
    """Run calculator provider"""
    print("🧮 Starting Calculator Provider")
    print("=" * 40)
    
    provider = CalculatorProvider()
    
    print(f"Provider: {provider.name}")
    print(f"Type: {provider.provider_type}")
    print(f"Capabilities: {', '.join(provider.capabilities)}")
    print("\\nStarting provider...")
    
    try:
        await provider.run()
    except KeyboardInterrupt:
        print("\\n🛑 Stopping provider...")
        await provider.stop()
        print("👋 Goodbye!")

if __name__ == "__main__":
    asyncio.run(main())
```

### Step 2: Add to Configuration

Add the calculator provider to `config/providers.yaml`:

```yaml
providers:
  calculator:
    enabled: true
    type: tool
    class: my_calculator_provider.CalculatorProvider
    config:
      name: calculator
      server_url: http://localhost:8000
    description: Mathematical calculation provider
    
  ollama:
    enabled: true
    type: llm
    class: my_local_llm_provider.OllamaProvider
    config:
      name: ollama
      ollama_url: http://localhost:11434
      server_url: http://localhost:8000
    description: Local Ollama LLM models
    auto_discover_models: true
```

### Step 3: Test the Provider

```bash
# Validate configuration
gleitzeit config validate

# Start cluster with providers
gleitzeit serve --provider-config config/providers.yaml

# In another terminal, test the calculator
gleitzeit providers invoke calculator add --args '{"a": 5, "b": 3}'
gleitzeit providers invoke calculator sin --args '{"x": 1.57}'  # π/2
gleitzeit providers health calculator
```

## Configuration Management

### Configuration File Structure

```yaml
global:
  # Global settings for all providers
  auto_start: true           # Auto-start enabled providers
  auto_restart: true         # Restart failed providers
  health_check_interval: 30  # Health check frequency (seconds)
  connection_timeout: 10     # Connection timeout (seconds)
  max_retry_attempts: 3      # Max connection retries
  default_server_url: http://localhost:8000

providers:
  provider_name:
    enabled: true|false      # Enable/disable provider
    type: llm|tool|extension # Provider type
    class: module.ClassName  # Python class path
    config:                  # Provider-specific configuration
      name: provider_name    # Required: provider identifier
      server_url: http://... # Required: Gleitzeit server URL
      # ... other config options
    description: "..."       # Human-readable description
    auto_discover_models: true|false  # For LLM providers
```

### Environment Variable Substitution

Use environment variables in configuration:

```yaml
providers:
  openai:
    enabled: true
    type: llm
    class: providers.openai_provider.OpenAIProvider
    config:
      name: openai
      api_key: ${OPENAI_API_KEY}        # From environment
      base_url: ${OPENAI_BASE_URL:-https://api.openai.com/v1}  # With default
      server_url: http://localhost:8000
```

### CLI Configuration Commands

```bash
# Show current configuration
gleitzeit config show

# Validate configuration syntax and structure
gleitzeit config validate

# List only the providers
gleitzeit config providers

# Create a new configuration template
gleitzeit config create --config-file my-providers.yaml

# Use custom config file
gleitzeit config show --config-file my-providers.yaml
```

## Advanced Provider Development

### Streaming Responses

For LLM providers that support streaming:

```python
async def stream(self, **kwargs) -> AsyncGenerator[Dict[str, Any], None]:
    """Stream text generation"""
    prompt = kwargs.get("prompt", "")
    model = kwargs.get("model", self.models[0])
    
    # Your streaming implementation
    async for chunk in your_streaming_api(prompt, model):
        yield {
            "token": chunk.text,
            "done": chunk.is_final,
            "model": model,
            "metadata": chunk.metadata
        }
```

### Error Handling and Retries

```python
import asyncio
from typing import Optional

class RobustProvider(SocketIOProviderClient):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.max_retries = kwargs.get("max_retries", 3)
        self.retry_delay = kwargs.get("retry_delay", 1.0)
    
    async def invoke_with_retry(self, method: str, **kwargs) -> Any:
        """Invoke with automatic retry logic"""
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                return await self.invoke(method, **kwargs)
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (2 ** attempt))
                    continue
                raise
        
        raise last_error
```

### Model Discovery

For LLM providers with dynamic model lists:

```python
async def discover_models(self) -> List[str]:
    """Dynamically discover available models"""
    try:
        # Call your API to get model list
        response = await self.api_client.get("/models")
        models = [model["name"] for model in response.json()["models"]]
        
        # Update provider models
        self.models = models
        return models
    except Exception as e:
        logger.warning(f"Model discovery failed: {e}")
        return self.models  # Return cached models
```

### Capability-based Routing

```python
class SmartProvider(SocketIOProviderClient):
    def __init__(self, **kwargs):
        super().__init__(
            capabilities=["text", "code", "math", "vision"],  # Declare capabilities
            **kwargs
        )
    
    async def invoke(self, method: str, **kwargs) -> Any:
        """Route based on capabilities"""
        if method == "generate":
            if self._requires_vision(kwargs):
                return await self._generate_with_vision(kwargs)
            elif self._requires_code(kwargs):
                return await self._generate_code(kwargs)
            else:
                return await self._generate_text(kwargs)
    
    def _requires_vision(self, params: Dict) -> bool:
        return "image" in params or "vision" in params.get("model", "")
    
    def _requires_code(self, params: Dict) -> bool:
        return "code" in params.get("prompt", "").lower()
```

## Best Practices

### 1. Provider Design

- **Single Responsibility**: Each provider should focus on one domain
- **Stateless**: Don't rely on internal state between requests
- **Idempotent**: Same input should produce same output
- **Fail Fast**: Validate inputs early and provide clear error messages

### 2. Configuration

```python
class WellConfiguredProvider(SocketIOProviderClient):
    def __init__(self, **kwargs):
        # Extract and validate configuration
        self.api_key = kwargs.get("api_key")
        if not self.api_key:
            raise ValueError("api_key is required")
        
        self.base_url = kwargs.get("base_url", "https://api.example.com")
        self.timeout = kwargs.get("timeout", 30.0)
        self.max_tokens = kwargs.get("max_tokens", 1000)
        
        # Remove config from kwargs before passing to parent
        config_keys = ["api_key", "base_url", "timeout", "max_tokens"]
        for key in config_keys:
            kwargs.pop(key, None)
        
        super().__init__(**kwargs)
```

### 3. Logging and Monitoring

```python
import logging
import time
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

class MonitoredProvider(SocketIOProviderClient):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.request_count = 0
        self.error_count = 0
        self.total_latency = 0.0
    
    @asynccontextmanager
    async def track_request(self, method: str):
        """Context manager for request tracking"""
        start_time = time.time()
        self.request_count += 1
        
        try:
            logger.info(f"Starting {method} request #{self.request_count}")
            yield
            logger.info(f"Completed {method} request in {time.time() - start_time:.2f}s")
        except Exception as e:
            self.error_count += 1
            logger.error(f"Request failed: {e}")
            raise
        finally:
            self.total_latency += time.time() - start_time
    
    async def invoke(self, method: str, **kwargs) -> Any:
        async with self.track_request(method):
            return await super().invoke(method, **kwargs)
    
    async def get_health_status(self) -> Dict[str, Any]:
        avg_latency = self.total_latency / max(self.request_count, 1)
        error_rate = self.error_count / max(self.request_count, 1)
        
        return {
            "healthy": error_rate < 0.1,  # Less than 10% errors
            "metrics": {
                "requests": self.request_count,
                "errors": self.error_count,
                "error_rate": error_rate,
                "avg_latency": avg_latency
            }
        }
```

### 4. Testing

Create comprehensive tests for your providers:

```python
import pytest
import asyncio
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_calculator_addition():
    provider = CalculatorProvider(server_url="http://test")
    
    result = await provider.invoke("add", a=5, b=3)
    
    assert result["result"] == 8
    assert result["expression"] == "5 + 3 = 8"

@pytest.mark.asyncio
async def test_provider_health():
    provider = CalculatorProvider(server_url="http://test")
    
    health = await provider.get_health_status()
    
    assert health["healthy"] is True
    assert "add" in health["available_methods"]

@pytest.mark.asyncio
async def test_division_by_zero():
    provider = CalculatorProvider(server_url="http://test")
    
    with pytest.raises(ValueError, match="Division by zero"):
        await provider.invoke("divide", a=10, b=0)
```

## Troubleshooting

### Common Issues

#### 1. Provider Won't Start

```bash
# Check configuration syntax
gleitzeit config validate

# Check if required dependencies are installed
pip install -r requirements.txt

# Check logs for specific errors
gleitzeit logs --provider calculator
```

#### 2. Connection Issues

```bash
# Check if cluster is running
gleitzeit status

# Verify server URL in configuration
gleitzeit config show

# Test network connectivity
curl http://localhost:8000/socket.io/
```

#### 3. Import Errors

```python
# Make sure your provider class is importable
python -c "from my_calculator_provider import CalculatorProvider"

# Check Python path
import sys
print(sys.path)
```

#### 4. Performance Issues

```bash
# Check provider health and metrics  
gleitzeit providers health calculator

# Monitor resource usage
gleitzeit monitor --provider calculator

# Enable debug logging
export PYTHONPATH=.
export LOG_LEVEL=DEBUG
python my_calculator_provider.py
```

### Debug Mode

Enable debug logging for detailed troubleshooting:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Or in your provider
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
```

### Provider Templates

Generate provider templates for different types:

```bash
# Create LLM provider template
gleitzeit providers create-template --type llm --name my_llm_provider

# Create tool provider template  
gleitzeit providers create-template --type tool --name my_tool_provider

# Create extension provider template
gleitzeit providers create-template --type extension --name my_extension_provider
```

## Next Steps

1. **Explore Examples**: Look at `my_local_llm_provider.py` for a complete LLM provider
2. **Join Community**: Share your providers and get help from other developers
3. **Advanced Features**: Learn about provider clustering, load balancing, and failover
4. **Integration**: Connect providers with workflows and batch processing

For more advanced topics, see:
- [Provider Architecture Guide](provider-architecture.md)
- [Socket.IO Protocol Reference](socketio-protocol.md) 
- [Performance Optimization](provider-performance.md)
- [Security Best Practices](provider-security.md)

Happy provider development! 🚀