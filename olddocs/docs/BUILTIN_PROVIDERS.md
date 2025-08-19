# Built-in Providers

Gleitzeit includes several built-in providers that implement common protocols for LLM interactions, Python execution, and MCP tool integration.

## Provider Architecture

Providers implement specific protocols and handle the actual execution of tasks. Each provider:
- Implements a specific protocol interface
- Manages connections to external services
- Handles authentication and configuration
- Provides error handling and retry logic

## Ollama Provider

Handles LLM interactions through the Ollama service.

### Configuration

```yaml
# ~/.gleitzeit/config.yaml
providers:
  ollama:
    endpoint: "http://localhost:11434"
    timeout: 300
    default_models:
      chat: "llama3.2:latest"
      vision: "llava:latest"
    model_aliases:
      "gpt": "llama3.2:latest"
      "vision": "llava:latest"
```

### Supported Methods

#### `llm/chat` - Text Generation

```yaml
- id: "chat_task"
  method: "llm/chat"
  parameters:
    model: "llama3.2:latest"
    messages:
      - role: "system"
        content: "You are a helpful assistant"
      - role: "user"
        content: "Explain quantum computing"
    temperature: 0.7
    max_tokens: 1000
    stream: false
```

**Parameters:**
- `model` (required): Ollama model name
- `messages` (required): Chat message history
- `temperature` (optional): Randomness (0.0-2.0, default: 0.8)
- `max_tokens` (optional): Maximum response tokens
- `stream` (optional): Stream response (default: false)
- `stop` (optional): Stop sequences
- `top_p` (optional): Nucleus sampling parameter

#### `llm/vision` - Image Analysis

```yaml
- id: "vision_task"
  method: "llm/vision"
  parameters:
    model: "llava:latest"
    messages:
      - role: "user"
        content: "What do you see in this image?"
    image: "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD..."
    temperature: 0.5
```

**Parameters:**
- `model` (required): Vision-capable model (e.g., llava)
- `messages` (required): Chat messages
- `image` (required): Base64 encoded image or image URL
- `temperature` (optional): Response randomness
- `max_tokens` (optional): Maximum response length

### Error Handling

The Ollama provider handles:
- Connection failures with automatic retry
- Model loading delays
- Rate limiting
- Invalid model names
- Malformed requests

### Model Management

```python
# Check available models
from gleitzeit.providers.ollama_provider import OllamaProvider

provider = OllamaProvider(endpoint="http://localhost:11434")
models = await provider.list_models()
print(f"Available models: {models}")

# Pull a new model
await provider.pull_model("mistral:latest")
```

## Python Provider

Executes Python code in controlled environments.

### Configuration

```yaml
providers:
  python:
    execution_mode: "docker"  # docker|local
    timeout: 300
    memory_limit: "512MB"
    allowed_packages:
      - "numpy"
      - "pandas" 
      - "requests"
    docker:
      image: "python:3.11-slim"
      network_mode: "none"  # No network access
```

### Supported Methods

#### `python/execute` - Code Execution

```yaml
- id: "python_task"
  method: "python/execute"
  parameters:
    code: |
      import math
      import json
      
      def calculate_area(radius):
          return math.pi * radius ** 2
      
      result = {
          "area": calculate_area(5),
          "circumference": 2 * math.pi * 5
      }
      
      print(f"Circle calculations: {result}")
    timeout: 30
    packages: ["numpy"]
    environment: "docker"
```

**Parameters:**
- `code` (required): Python code to execute
- `timeout` (optional): Execution timeout in seconds (default: 300)
- `packages` (optional): List of pip packages to install
- `environment` (optional): Execution environment (docker|local)
- `working_directory` (optional): Working directory for execution

#### `python/validate` - Syntax Validation

```yaml
- id: "validate_task"
  method: "python/validate"
  parameters:
    code: |
      def hello_world():
          print("Hello, world!")
          return True
```

**Parameters:**
- `code` (required): Python code to validate

### Security Features

#### Docker Isolation

```yaml
# Secure execution configuration
parameters:
  environment: "docker"
  # Runs in isolated container with:
  # - No network access
  # - Limited filesystem access
  # - Memory limits
  # - CPU limits
  # - Execution timeout
```

#### Package Restrictions

```python
# Only allow specific packages
allowed_packages = [
    "numpy", "pandas", "matplotlib", "scipy", 
    "requests", "beautifulsoup4", "lxml"
]

# Block dangerous packages
blocked_packages = [
    "subprocess", "os", "sys", "importlib",
    "eval", "exec", "compile"
]
```

### Response Format

```json
{
  "response": "Circle calculations: {'area': 78.54, 'circumference': 31.42}",
  "metadata": {
    "exit_code": 0,
    "execution_time": 0.150,
    "stdout": "Circle calculations: {'area': 78.54, 'circumference': 31.42}\n",
    "stderr": "",
    "environment": "docker",
    "python_version": "3.11.5",
    "packages_installed": ["numpy"],
    "memory_used": "45MB",
    "cpu_time": 0.120
  }
}
```

### Error Handling

Common error scenarios:
- Syntax errors in code
- Runtime exceptions
- Timeout exceeded
- Memory limit exceeded
- Package installation failures
- Docker container issues

## MCP Provider

Integrates with Model Context Protocol servers for tool access.

### Configuration

```yaml
providers:
  mcp:
    servers:
      simple:
        endpoint: "http://localhost:8000"
        timeout: 30
      filesystem:
        endpoint: "unix:///tmp/mcp-filesystem.sock"
        auth:
          type: "token"
          token: "${MCP_AUTH_TOKEN}"
```

### Supported Methods

#### Dynamic Tool Methods

The MCP provider dynamically exposes tools as `mcp/tool.{tool_name}` methods:

```yaml
# Echo tool
- id: "echo_test"
  method: "mcp/tool.echo"
  parameters:
    message: "Hello from MCP!"

# Math tools
- id: "add_numbers"
  method: "mcp/tool.add"
  parameters:
    a: 15
    b: 27

- id: "multiply"
  method: "mcp/tool.multiply"
  parameters:
    x: 6
    y: 7

# String operations
- id: "concat_strings"
  method: "mcp/tool.concat"
  parameters:
    strings: ["Hello", " ", "World", "!"]
```

### Tool Discovery

```python
# List available tools
from gleitzeit.providers.simple_mcp_provider import SimpleMCPProvider

provider = SimpleMCPProvider(endpoint="http://localhost:8000")
tools = await provider.list_tools()

for tool in tools:
    print(f"Tool: {tool.name}")
    print(f"Description: {tool.description}")
    print(f"Parameters: {tool.parameters}")
```

### Error Handling

MCP provider handles:
- Server connection failures
- Tool execution errors
- Invalid parameters
- Timeout errors
- Authentication failures

## Provider Selection

### Automatic Selection

Providers are automatically selected based on the method prefix:

```yaml
tasks:
  - method: "llm/chat"      # → OllamaProvider
  - method: "python/execute" # → PythonProvider  
  - method: "mcp/tool.echo"  # → MCPProvider
```

### Explicit Provider Configuration

```yaml
# Override default provider selection
- id: "custom_llm"
  method: "llm/chat"
  provider: "openai"  # Use OpenAI instead of Ollama
  parameters:
    model: "gpt-4"
    messages:
      - role: "user"
        content: "Hello"
```

## Custom Provider Development

### Basic Provider Structure

```python
from gleitzeit.providers.base import BaseProvider
from gleitzeit.core.protocol import Protocol

class CustomProvider(BaseProvider):
    def __init__(self, config: dict):
        super().__init__(config)
        self.client = None
    
    async def initialize(self) -> None:
        """Initialize provider resources"""
        self.client = await self._create_client()
    
    async def cleanup(self) -> None:
        """Cleanup provider resources"""
        if self.client:
            await self.client.close()
    
    async def execute(self, method: str, parameters: dict) -> dict:
        """Execute method with parameters"""
        if method == "custom/action":
            return await self._handle_action(parameters)
        else:
            raise ValueError(f"Unknown method: {method}")
    
    async def _handle_action(self, params: dict) -> dict:
        # Implementation
        result = await self.client.perform_action(params)
        
        return {
            "response": result,
            "metadata": {
                "provider": "custom",
                "execution_time": 0.150
            }
        }
```

### Provider Registration

```python
from gleitzeit.registry import ProtocolProviderRegistry

# Register custom provider
registry = ProtocolProviderRegistry()
registry.register_provider("custom/v1", CustomProvider)

# Use in workflows
workflow = {
    "tasks": [
        {
            "method": "custom/action",
            "parameters": {"data": "test"}
        }
    ]
}
```

## Provider Monitoring

### Health Checks

```python
# Check provider health
async with GleitzeitClient() as client:
    health = await client.check_provider_health("ollama")
    print(f"Ollama status: {health.status}")
    
    if health.status == "unhealthy":
        print(f"Issues: {health.issues}")
```

### Performance Metrics

```python
# Get provider performance metrics
metrics = await client.get_provider_metrics("ollama")
print(f"Average response time: {metrics.avg_response_time}ms")
print(f"Success rate: {metrics.success_rate}%")
print(f"Active connections: {metrics.active_connections}")
```

## Best Practices

### Configuration Management

1. **Environment variables**: Use env vars for sensitive config
2. **Default values**: Provide sensible defaults
3. **Validation**: Validate configuration on startup
4. **Hot reloading**: Support config changes without restart

### Error Handling

1. **Graceful degradation**: Handle provider unavailability
2. **Retry logic**: Implement exponential backoff
3. **Circuit breakers**: Prevent cascading failures
4. **Detailed logging**: Log errors with context

### Performance

1. **Connection pooling**: Reuse connections where possible
2. **Caching**: Cache expensive operations
3. **Resource limits**: Set appropriate timeouts and limits
4. **Monitoring**: Track performance metrics

### Security

1. **Input validation**: Validate all parameters
2. **Sandboxing**: Isolate execution environments
3. **Authentication**: Secure provider connections
4. **Audit logging**: Log all provider interactions

These built-in providers cover the most common use cases while providing a foundation for extending Gleitzeit with custom providers for specialized needs.