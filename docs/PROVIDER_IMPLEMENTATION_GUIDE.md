# Provider Implementation Guide for Gleitzeit V4

## Overview

This guide documents the implementation requirements and best practices for creating providers in Gleitzeit V4. It covers the protocol-based architecture, method naming conventions, response formats, and integration with the workflow system.

## Table of Contents

1. [Provider Architecture](#provider-architecture)
2. [Method Naming Conventions](#method-naming-conventions)
3. [Response Format Standards](#response-format-standards)
4. [Parameter Substitution in Workflows](#parameter-substitution-in-workflows)
5. [Provider Implementation Checklist](#provider-implementation-checklist)
6. [Common Issues and Solutions](#common-issues-and-solutions)

## Provider Architecture

### Base Provider Class

All providers must inherit from `ProtocolProvider` in `providers/base.py`:

```python
from gleitzeit.providers.base import ProtocolProvider

class MyProvider(ProtocolProvider):
    def __init__(self, provider_id: str, config: Dict[str, Any]):
        super().__init__(
            provider_id=provider_id,
            protocol_id="myprotocol/v1",  # Must match registered protocol
            name="My Provider",
            description="Description of what this provider does"
        )
```

### Automatic File Handling

The base `ProtocolProvider` class provides automatic file handling for all providers. When a request includes `file_path` or `image_path` parameters, the base class automatically:

1. **For text files**: Reads the file content and appends it to the prompt or messages
2. **For image files**: Reads and converts to base64, adds to `image_data` or `images` array

This happens transparently in the `execute_with_stats` method before `handle_request` is called, so providers don't need to implement file reading logic.

### Required Methods

Every provider must implement these abstract methods:

1. **`handle_request(method: str, params: Dict[str, Any]) -> Any`**
   - Handles incoming method calls
   - Returns results that must be JSON-serializable
   - Should handle both prefixed and non-prefixed method names

2. **`initialize() -> None`**
   - Sets up connections, sessions, or resources
   - Called before the provider starts handling requests

3. **`shutdown() -> None`**
   - Cleans up resources
   - Called when the provider is being stopped

4. **`health_check() -> Dict[str, Any]`**
   - Returns provider health status
   - Format: `{"status": "healthy|degraded|unhealthy", "details": {...}}`

5. **`get_supported_methods() -> List[str]`**
   - Returns list of supported methods WITH protocol prefix
   - Example: `["llm/chat", "llm/generate", "llm/embed"]`

## Method Naming Conventions

### Method Registration

Methods must be registered with their full protocol-prefixed names:

```python
def get_supported_methods(self) -> List[str]:
    """Return supported methods with protocol prefix"""
    return [
        "llm/chat",      # NOT just "chat"
        "llm/generate",  # NOT just "generate"
        "llm/embed"      # NOT just "embed"
    ]
```

### Method Handling

The `handle_request` method should handle both prefixed and non-prefixed method names for compatibility:

```python
async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
    """Handle protocol request"""
    
    # Strip protocol prefix if present for internal handling
    if method.startswith("llm/"):
        method = method[4:]  # Remove "llm/" prefix
    
    # Route to appropriate handler
    if method == "chat":
        return await self._handle_chat(params)
    elif method == "generate":
        return await self._handle_generate(params)
    else:
        raise ValueError(f"Unsupported method: {method}")
```

## Response Format Standards

### Standard Response Fields for LLM Providers

LLM providers should return responses with these standard fields for workflow compatibility:

```python
# For text generation/chat methods
return {
    "response": generated_text,     # PRIMARY: Used by workflows for parameter substitution
    "content": generated_text,       # OPTIONAL: For backward compatibility
    "model": model_name,
    "provider_id": self.provider_id,
    "tokens_used": token_count,
    "metadata": {
        # Additional provider-specific metadata
    }
}
```

### Why "response" Field is Required

Workflows use parameter substitution syntax like `${task_id.response}` to reference results from previous tasks. The `response` field is the standard field name that workflows expect for text content.

Example workflow:
```yaml
tasks:
  - id: "generate_topic"
    method: "llm/chat"
    parameters:
      prompt: "Generate a topic"
      
  - id: "write_about_topic"
    method: "llm/chat"
    dependencies: ["generate_topic"]
    parameters:
      prompt: "Write about: ${generate_topic.response}"  # References the 'response' field
```

### Standard Response Fields for Other Provider Types

#### Python Execution Providers

```python
return {
    "result": execution_result,      # Primary result
    "stdout": standard_output,
    "stderr": standard_error,
    "exit_code": exit_code,
    "execution_time": duration_seconds
}
```

#### Embedding Providers

```python
return {
    "embedding": embedding_vector,   # List of floats
    "model": model_name,
    "dimensions": len(embedding_vector)
}
```

## Parameter Substitution in Workflows

### How Parameter Substitution Works

1. **Syntax**: `${task_id.field_path}`
   - `task_id`: The ID of a previous task
   - `field_path`: Path to the desired field in the result

2. **Resolution Process**:
   - The execution engine stores results as `TaskResult` objects
   - Each `TaskResult` has a `result` field containing the provider's response
   - The engine automatically navigates from `TaskResult.result` to access provider response fields

3. **Examples**:
   ```yaml
   # Simple field access
   ${generate_topic.response}
   
   # Nested field access (if response is complex)
   ${analyze_data.metadata.score}
   
   # Array index access
   ${list_items.items[0]}
   ```

### TaskResult Structure

Understanding the TaskResult structure helps in designing provider responses:

```python
class TaskResult:
    task_id: str
    status: TaskStatus
    result: Any  # <-- Provider response goes here
    error: Optional[str]
    started_at: datetime
    completed_at: datetime
    duration_seconds: float
    metadata: Dict[str, Any]
```

When workflows reference `${task_id.response}`, the engine:
1. Retrieves the `TaskResult` for `task_id`
2. Accesses `TaskResult.result` (the provider's response)
3. Looks for the `response` field in that dictionary

## Provider Implementation Checklist

When implementing a new provider, ensure:

- [ ] **Inherits from `ProtocolProvider`**
- [ ] **Implements all required abstract methods**
- [ ] **`get_supported_methods()` returns methods with protocol prefix**
  - Example: `["myprotocol/method1", "myprotocol/method2"]`
- [ ] **`handle_request()` handles both prefixed and non-prefixed methods**
- [ ] **Returns standard response format**
  - LLM providers: Include `"response"` field
  - Python providers: Include `"result"` field
  - All providers: Ensure JSON-serializable
- [ ] **Proper error handling with meaningful messages**
- [ ] **Resource cleanup in `shutdown()` method**
- [ ] **Health check implementation**
- [ ] **Logging for debugging**

## Common Issues and Solutions

### Issue 1: "Unsupported method" Errors

**Problem**: Provider reports method as unsupported even though it's implemented.

**Cause**: Method name mismatch between what's registered and what's being called.

**Solution**:
```python
# In get_supported_methods()
return ["llm/chat"]  # WITH protocol prefix

# In handle_request()
if method.startswith("llm/"):
    method = method[4:]  # Strip prefix for internal routing
```

### Issue 2: Parameter Substitution Not Working

**Problem**: Workflows show "Field response not found" warning.

**Cause**: Provider not returning the expected field name.

**Solution**: Ensure LLM providers return a `"response"` field:
```python
return {
    "response": generated_text,  # Required for workflows
    # ... other fields
}
```

### Issue 3: Provider Not Found

**Problem**: Registry can't find provider for protocol/method.

**Cause**: Provider not properly registered or protocol mismatch.

**Solution**:
1. Ensure protocol_id matches registered protocol
2. Register provider with registry after initialization
3. Verify `get_supported_methods()` returns correct method names

### Issue 4: Async/Await Issues

**Problem**: Synchronous code in async methods causes blocking.

**Solution**: Use async libraries and proper await:
```python
# Wrong
response = requests.get(url)  # Blocks event loop

# Right
async with aiohttp.ClientSession() as session:
    async with session.get(url) as response:
        data = await response.json()
```

## Testing Your Provider

### Unit Testing

```python
import asyncio
import pytest

@pytest.mark.asyncio
async def test_provider():
    provider = MyProvider("test-provider", config={})
    await provider.initialize()
    
    # Test method handling
    result = await provider.handle_request(
        "myprotocol/mymethod",
        {"param": "value"}
    )
    
    assert "response" in result  # For LLM providers
    assert result["response"] is not None
    
    await provider.shutdown()
```

### Integration Testing with Workflows

Create a test workflow that uses your provider:

```yaml
name: "Test My Provider"
tasks:
  - id: "test_task"
    method: "myprotocol/mymethod"
    parameters:
      param: "test value"
```

Run with CLI:
```bash
python -m gleitzeit.cli run test_workflow.yaml
```

## Best Practices

1. **Always include standard fields** in responses for workflow compatibility
2. **Log important operations** for debugging
3. **Handle edge cases** (empty inputs, invalid parameters)
4. **Implement proper timeout handling** for external services
5. **Use connection pooling** for HTTP-based providers
6. **Document your provider's specific requirements** and response formats
7. **Version your protocol** for backward compatibility
8. **Test with real workflows** not just unit tests

## Example: Complete Provider Implementation

```python
from typing import Dict, List, Any
import aiohttp
import logging
from gleitzeit.providers.base import ProtocolProvider

logger = logging.getLogger(__name__)

class ExampleLLMProvider(ProtocolProvider):
    """Example LLM provider implementation"""
    
    def __init__(self, provider_id: str, api_url: str):
        super().__init__(
            provider_id=provider_id,
            protocol_id="llm/v1",
            name="Example LLM Provider",
            description="Example implementation of an LLM provider"
        )
        self.api_url = api_url
        self.session = None
    
    async def initialize(self) -> None:
        """Initialize HTTP session"""
        self.session = aiohttp.ClientSession()
        logger.info(f"Initialized {self.name}")
    
    async def shutdown(self) -> None:
        """Clean up resources"""
        if self.session:
            await self.session.close()
        logger.info(f"Shutdown {self.name}")
    
    async def health_check(self) -> Dict[str, Any]:
        """Check provider health"""
        try:
            async with self.session.get(f"{self.api_url}/health") as resp:
                if resp.status == 200:
                    return {"status": "healthy", "details": "API accessible"}
        except Exception as e:
            logger.error(f"Health check failed: {e}")
        
        return {"status": "unhealthy", "details": "API not accessible"}
    
    def get_supported_methods(self) -> List[str]:
        """Return supported methods with protocol prefix"""
        return ["llm/chat", "llm/generate"]
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Handle incoming requests"""
        logger.info(f"Handling request: {method}")
        
        # Handle both prefixed and non-prefixed methods
        if method.startswith("llm/"):
            method = method[4:]
        
        if method == "chat":
            return await self._handle_chat(params)
        elif method == "generate":
            return await self._handle_generate(params)
        else:
            raise ValueError(f"Unsupported method: {method}")
    
    async def _handle_chat(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle chat completion"""
        messages = params.get("messages", [])
        
        # Make API request
        async with self.session.post(
            f"{self.api_url}/chat",
            json={"messages": messages}
        ) as response:
            result = await response.json()
        
        # Return standard format
        return {
            "response": result["text"],      # Required for workflows
            "content": result["text"],        # Backward compatibility
            "model": result.get("model", "default"),
            "provider_id": self.provider_id
        }
    
    async def _handle_generate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle text generation"""
        prompt = params.get("prompt", "")
        
        # Make API request
        async with self.session.post(
            f"{self.api_url}/generate",
            json={"prompt": prompt}
        ) as response:
            result = await response.json()
        
        # Return standard format
        return {
            "response": result["text"],      # Required for workflows
            "content": result["text"],        # Backward compatibility
            "model": result.get("model", "default"),
            "provider_id": self.provider_id
        }
```

## Conclusion

Following these guidelines ensures your provider integrates seamlessly with Gleitzeit V4's workflow system. The key points are:

1. Use protocol-prefixed method names in `get_supported_methods()`
2. Return standard response formats (especially the `"response"` field for LLM providers)
3. Handle both prefixed and non-prefixed method names in `handle_request()`
4. Implement proper error handling and resource management

For more details on the overall architecture, see:
- [GLEITZEIT_V4_ARCHITECTURE.md](./GLEITZEIT_V4_ARCHITECTURE.md)
- [PROTOCOLS_PROVIDERS_EXECUTION.md](./PROTOCOLS_PROVIDERS_EXECUTION.md)