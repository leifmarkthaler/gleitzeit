# LLM Provider Implementation Guide

## Overview

The LLM provider in Gleitzeit enables integration with Large Language Model services. The current implementation uses Ollama as the backend, providing a protocol-compliant interface for LLM interactions.

## Architecture

### OllamaProvider Class

Located in `src/gleitzeit/providers/ollama_provider.py`, this provider implements the `llm/v1` protocol.

```python
class OllamaProvider(ProtocolProvider):
    """
    Provider for Ollama LLM service
    
    Supports:
    - Text generation (llm/chat)
    - Vision/image analysis (llm/vision)
    - Streaming responses
    - File content injection
    """
```

## Protocol Definition

### Protocol ID: `llm/v1`

The LLM protocol is defined in `src/gleitzeit/protocols/llm_protocol.py`:

```python
LLM_PROTOCOL_V1 = {
    "id": "llm/v1",
    "name": "LLM Protocol",
    "version": "1.0.0",
    "methods": {
        "chat": {
            "description": "Generate text responses",
            "parameters": {
                "model": {"type": "string", "required": True},
                "messages": {"type": "array", "required": True},
                "temperature": {"type": "number", "required": False},
                "max_tokens": {"type": "integer", "required": False},
                "stream": {"type": "boolean", "required": False}
            }
        },
        "vision": {
            "description": "Analyze images with vision models",
            "parameters": {
                "model": {"type": "string", "required": True},
                "messages": {"type": "array", "required": True},
                "image_path": {"type": "string", "required": True}
            }
        }
    }
}
```

## Provider Implementation Details

### Initialization

```python
def __init__(self, 
             provider_id: str = "ollama-1",
             base_url: str = "http://localhost:11434",
             timeout: int = 120):
    """
    Initialize Ollama provider
    
    Args:
        provider_id: Unique provider identifier
        base_url: Ollama API endpoint
        timeout: Request timeout in seconds
    """
    super().__init__(
        provider_id=provider_id,
        protocol_id="llm/v1",
        name="Ollama LLM Provider",
        description="LLM provider using Ollama backend"
    )
    self.base_url = base_url
    self.timeout = timeout
    self.session = None  # Async HTTP session
```

### Key Methods

#### 1. Request Handling

```python
async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
    """
    Handle incoming protocol requests
    
    Routes methods to appropriate handlers:
    - llm/chat -> _handle_chat()
    - llm/vision -> _handle_vision()
    """
    # Remove protocol prefix if present
    if method.startswith("llm/"):
        method = method[4:]
    
    if method == "chat":
        return await self._handle_chat(params)
    elif method == "vision":
        return await self._handle_vision(params)
    else:
        raise ValueError(f"Unsupported method: {method}")
```

#### 2. Chat Method Implementation

```python
async def _handle_chat(self, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle text generation requests
    
    Parameters:
        model: Model name (e.g., "llama3.2:latest")
        messages: Array of message objects
        temperature: Sampling temperature (0.0-2.0)
        max_tokens: Maximum tokens to generate
        stream: Enable streaming responses
        file_path: Optional file to include in context
    
    Returns:
        Dictionary with 'response' field containing generated text
    """
    # File content injection (if file_path provided)
    if 'file_path' in params:
        file_content = await self._read_file(params['file_path'])
        # Inject file content into last user message
        messages[-1]['content'] = f"{file_content}\n\n{messages[-1]['content']}"
    
    # Prepare Ollama API request
    payload = {
        "model": params.get("model", "llama3.2:latest"),
        "messages": params.get("messages", []),
        "stream": params.get("stream", False),
        "options": {}
    }
    
    # Add optional parameters
    if "temperature" in params:
        payload["options"]["temperature"] = params["temperature"]
    if "max_tokens" in params:
        payload["options"]["num_predict"] = params["max_tokens"]
    
    # Send request to Ollama
    response = await self._make_request("/api/chat", payload)
    
    return {
        "response": response.get("message", {}).get("content", ""),
        "model": response.get("model"),
        "total_duration": response.get("total_duration"),
        "tokens_used": response.get("eval_count", 0)
    }
```

#### 3. Vision Method Implementation

```python
async def _handle_vision(self, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle image analysis requests
    
    Parameters:
        model: Vision model name (e.g., "llava:latest")
        messages: Array of message objects
        image_path: Path to image file
    
    Returns:
        Dictionary with analysis results
    """
    # Read and encode image
    image_data = await self._encode_image(params['image_path'])
    
    # Add image to messages
    messages = params.get("messages", [])
    if messages and messages[-1].get("role") == "user":
        messages[-1]["images"] = [image_data]
    
    # Use chat endpoint with image data
    payload = {
        "model": params.get("model", "llava:latest"),
        "messages": messages,
        "stream": False
    }
    
    response = await self._make_request("/api/chat", payload)
    
    return {
        "response": response.get("message", {}).get("content", ""),
        "model": response.get("model"),
        "image_analyzed": params['image_path']
    }
```

### Helper Methods

#### File Reading
```python
async def _read_file(self, file_path: str) -> str:
    """Read text file content for inclusion in prompts"""
    try:
        async with aiofiles.open(file_path, 'r') as f:
            content = await f.read()
        return content
    except Exception as e:
        logger.error(f"Failed to read file {file_path}: {e}")
        return f"[Error reading file: {e}]"
```

#### Image Encoding
```python
async def _encode_image(self, image_path: str) -> str:
    """Encode image to base64 for vision models"""
    import base64
    try:
        async with aiofiles.open(image_path, 'rb') as f:
            image_data = await f.read()
        return base64.b64encode(image_data).decode('utf-8')
    except Exception as e:
        raise ValueError(f"Failed to encode image: {e}")
```

#### HTTP Communication
```python
async def _make_request(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Make HTTP request to Ollama API"""
    if not self.session:
        self.session = aiohttp.ClientSession()
    
    url = f"{self.base_url}{endpoint}"
    
    try:
        async with self.session.post(
            url, 
            json=data,
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        ) as response:
            response.raise_for_status()
            return await response.json()
    except aiohttp.ClientError as e:
        logger.error(f"Ollama API error: {e}")
        raise RuntimeError(f"LLM provider error: {e}")
```

## Provider Lifecycle

### Initialization
```python
async def initialize(self) -> None:
    """Initialize provider resources"""
    self.session = aiohttp.ClientSession()
    
    # Check Ollama availability
    try:
        async with self.session.get(f"{self.base_url}/api/tags") as resp:
            if resp.status == 200:
                models = await resp.json()
                logger.info(f"Ollama available with {len(models.get('models', []))} models")
    except Exception as e:
        logger.warning(f"Ollama not reachable: {e}")
```

### Shutdown
```python
async def shutdown(self) -> None:
    """Clean up provider resources"""
    if self.session:
        await self.session.close()
        self.session = None
```

## Integration with Gleitzeit

### Registration

Register the provider with the protocol registry:

```python
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.providers.ollama_provider import OllamaProvider
from gleitzeit.protocols.llm_protocol import LLM_PROTOCOL_V1

# Create registry
registry = ProtocolProviderRegistry()

# Register protocol
registry.register_protocol(LLM_PROTOCOL_V1)

# Create and register provider
ollama_provider = OllamaProvider(
    provider_id="ollama-main",
    base_url="http://localhost:11434"
)
await ollama_provider.initialize()

registry.register_provider(
    provider_id="ollama-main",
    protocol_id="llm/v1",
    provider_instance=ollama_provider
)
```

### Using in Workflows

Once registered, the provider handles tasks with protocol `llm/v1`:

```python
task = Task(
    id="generate-text",
    protocol="llm/v1",
    method="chat",
    params={
        "model": "llama3.2:latest",
        "messages": [
            {"role": "user", "content": "Hello!"}
        ]
    }
)
```

## Advanced Features

### Streaming Support

The provider supports streaming responses for real-time output:

```python
async def _handle_streaming_chat(self, params: Dict[str, Any]):
    """Handle streaming chat responses"""
    params["stream"] = True
    
    async for chunk in self._stream_request("/api/chat", params):
        # Process each chunk as it arrives
        yield chunk.get("message", {}).get("content", "")
```

### Model Management

Query available models:

```python
async def list_models(self) -> List[str]:
    """List available Ollama models"""
    async with self.session.get(f"{self.base_url}/api/tags") as resp:
        data = await resp.json()
        return [model["name"] for model in data.get("models", [])]
```

### Error Handling

The provider implements comprehensive error handling:

```python
async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
    try:
        return await self._route_request(method, params)
    except aiohttp.ClientError as e:
        # Network/connection errors
        raise RuntimeError(f"Ollama connection failed: {e}")
    except asyncio.TimeoutError:
        # Timeout errors
        raise RuntimeError(f"Request timed out after {self.timeout}s")
    except Exception as e:
        # Other errors
        logger.error(f"Provider error: {e}")
        raise
```

## Testing the Provider

### Unit Tests

```python
import pytest
from gleitzeit.providers.ollama_provider import OllamaProvider

@pytest.mark.asyncio
async def test_ollama_chat():
    provider = OllamaProvider()
    await provider.initialize()
    
    result = await provider.handle_request("chat", {
        "model": "llama3.2:latest",
        "messages": [{"role": "user", "content": "Say hello"}]
    })
    
    assert "response" in result
    assert len(result["response"]) > 0
    
    await provider.shutdown()
```

### Integration Tests

```python
@pytest.mark.asyncio
async def test_workflow_with_llm():
    # Setup
    engine = ExecutionEngine(...)
    
    # Create LLM task
    task = Task(
        id="test-llm",
        protocol="llm/v1",
        method="chat",
        params={
            "model": "llama3.2:latest",
            "messages": [{"role": "user", "content": "Test"}]
        }
    )
    
    # Execute
    result = await engine.execute_task(task)
    assert result.status == TaskStatus.COMPLETED
```

## Performance Considerations

### Connection Pooling

The provider uses a single `aiohttp.ClientSession` for connection pooling:

```python
# Reuses connections for better performance
self.session = aiohttp.ClientSession(
    connector=aiohttp.TCPConnector(
        limit=100,  # Total connection pool limit
        limit_per_host=30  # Per-host limit
    )
)
```

### Timeout Configuration

Configure timeouts based on model and prompt complexity:

```python
# Short timeout for simple prompts
provider = OllamaProvider(timeout=30)

# Longer timeout for complex generation
provider = OllamaProvider(timeout=300)
```

### Batch Processing

For batch operations, reuse the same provider instance:

```python
provider = OllamaProvider()
await provider.initialize()

# Process multiple requests with same provider
for prompt in prompts:
    result = await provider.handle_request("chat", {
        "model": "llama3.2:latest",
        "messages": [{"role": "user", "content": prompt}]
    })
    # Process result

await provider.shutdown()
```

## Troubleshooting

### Common Issues

1. **Connection Refused**
   - Ensure Ollama is running: `ollama serve`
   - Check base_url matches Ollama endpoint

2. **Model Not Found**
   - Pull required model: `ollama pull model_name`
   - Verify model name in request

3. **Timeout Errors**
   - Increase provider timeout
   - Use smaller models or reduce prompt size
   - Check system resources

4. **Memory Issues**
   - Monitor Ollama memory usage
   - Use quantized models
   - Implement request queuing

## Extending the Provider

### Adding New Methods

```python
async def _handle_embeddings(self, params: Dict[str, Any]) -> Any:
    """Generate text embeddings"""
    payload = {
        "model": params.get("model"),
        "prompt": params.get("text")
    }
    
    response = await self._make_request("/api/embeddings", payload)
    return {
        "embeddings": response.get("embedding"),
        "model": response.get("model")
    }
```

### Custom Model Parameters

```python
# Add support for additional Ollama parameters
OLLAMA_OPTIONS = {
    "temperature": "temperature",
    "top_k": "top_k", 
    "top_p": "top_p",
    "repeat_penalty": "repeat_penalty",
    "seed": "seed",
    "num_ctx": "num_ctx"
}

def _build_options(self, params: Dict[str, Any]) -> Dict[str, Any]:
    """Build Ollama options from parameters"""
    options = {}
    for param_key, ollama_key in OLLAMA_OPTIONS.items():
        if param_key in params:
            options[ollama_key] = params[param_key]
    return options
```

## Best Practices

1. **Always initialize and shutdown properly**
   ```python
   provider = OllamaProvider()
   try:
       await provider.initialize()
       # Use provider
   finally:
       await provider.shutdown()
   ```

2. **Handle model-specific requirements**
   - Vision models need base64-encoded images
   - Code models benefit from specific formatting
   - Chat models need proper message structure

3. **Implement retry logic for transient failures**
   ```python
   async def _retry_request(self, method, params, max_retries=3):
       for attempt in range(max_retries):
           try:
               return await self.handle_request(method, params)
           except RuntimeError as e:
               if attempt == max_retries - 1:
                   raise
               await asyncio.sleep(2 ** attempt)
   ```

4. **Log important events and errors**
   ```python
   logger.info(f"Processing {method} request with model {params.get('model')}")
   logger.error(f"Failed after {attempts} attempts: {error}")
   ```

5. **Validate parameters before processing**
   ```python
   def _validate_params(self, method: str, params: Dict[str, Any]):
       required = self.get_required_params(method)
       missing = [p for p in required if p not in params]
       if missing:
           raise ValueError(f"Missing required parameters: {missing}")
   ```