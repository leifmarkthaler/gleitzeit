# OllamaHub Guide

The OllamaHub manages Ollama instances for LLM workflow execution, providing basic load balancing and resource management.

## Overview

OllamaHub provides:
- **Basic load balancing** across Ollama instances
- **Simple health monitoring** for availability
- **Model management** tracking

## Current Implementation

### Basic OllamaHub

The `OllamaHub` class manages Ollama instances:

```python
from gleitzeit.hub.ollama_hub import OllamaHub

# Initialize Ollama hub
ollama_hub = OllamaHub(config={
    "instances": [
        {
            "endpoint": "http://localhost:11434",
            "models": ["llama3.2", "mistral"]
        }
    ],
    "timeout": 300
})

# Make a chat request
response = await ollama_hub.chat_completion(
    model="llama3.2",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

### Configuration

```yaml
# ~/.gleitzeit/config.yaml
hubs:
  ollama:
    type: "OllamaHub"
    instances:
      - endpoint: "http://localhost:11434"
        models: ["llama3.2", "mistral", "codellama"]
      - endpoint: "http://localhost:11435"
        models: ["llava", "llama3.2:70b"]
    timeout: 300
```

## Usage in Workflows

### Through Ollama Provider

Most LLM execution happens through the `OllamaProvider`:

```python
from gleitzeit.providers.ollama_provider import OllamaProvider

provider = OllamaProvider(config={
    "endpoint": "http://localhost:11434",
    "timeout": 300,
    "default_model": "llama3.2"
})

# Execute chat request
result = await provider.execute("llm/chat", {
    "model": "llama3.2",
    "messages": [{"role": "user", "content": "Hello!"}]
})
```

### In Workflow YAML

```yaml
tasks:
  - id: "chat_task"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Generate a story"
```

## Basic Load Balancing

### Round-Robin Selection

The hub distributes requests across available instances:

```python
# Simple round-robin implementation
class OllamaHub:
    def __init__(self, config):
        self.instances = config["instances"]
        self.current_index = 0
    
    async def get_instance(self):
        instance = self.instances[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.instances)
        return instance
```

### Health Checking

Basic health checks verify instance availability:

```python
async def check_instance_health(instance):
    try:
        response = await httpx.get(f"{instance['endpoint']}/api/tags")
        return response.status_code == 200
    except:
        return False
```

## Model Management

### Available Models

The hub tracks which models are available on each instance:

```python
# Get available models
models = await ollama_hub.list_available_models()
# Returns: {"llama3.2": ["instance1"], "llava": ["instance2"]}
```

### Model Selection

The hub routes requests to instances with the required model:

```python
# Request specific model
response = await ollama_hub.chat_completion(
    model="llava",  # Will route to instance with llava
    messages=[...],
    image="base64_encoded_image"
)
```

## Error Handling

### Connection Failures

When an instance is unavailable:

```python
# Basic retry logic
async def chat_with_retry(hub, params, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await hub.chat_completion(**params)
        except ConnectionError:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
```

### Model Not Found

```python
# Error when model not available
{
    "error": "Model 'gpt-4' not found on any instance",
    "available_models": ["llama3.2", "mistral", "llava"]
}
```

## CLI Usage

### Status Command

```bash
# Check Ollama hub status
gleitzeit status

# Output includes:
# Ollama Instances:
#   - http://localhost:11434: Healthy
#     Models: llama3.2, mistral
#   - http://localhost:11435: Healthy  
#     Models: llava, llama3.2:70b
```

## Best Practices

### Instance Configuration

1. **List all models** available on each instance
2. **Use consistent endpoints** for reliability
3. **Monitor instance health** regularly

### Performance

1. **Distribute models** across instances based on usage
2. **Set appropriate timeouts** for long-running requests
3. **Monitor response times** to detect issues

## Limitations

Current OllamaHub implementation is basic:
- Simple round-robin load balancing only
- No advanced health monitoring or metrics
- No automatic failover or recovery
- No request queuing or rate limiting
- No model pulling or management
- Basic error handling only

## Future Enhancements

Planned improvements (not yet implemented):
- Weighted load balancing based on instance capacity
- Advanced health checks with model validation
- Automatic failover and circuit breakers
- Request queuing and priority handling
- Dynamic model loading and management
- Performance metrics and monitoring

## Example Workflows

### Simple Chat

```yaml
name: "Simple Chat"
tasks:
  - id: "chat"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Tell me a joke"
```

### Vision Analysis

```yaml
name: "Image Analysis"
tasks:
  - id: "analyze"
    method: "llm/vision"
    parameters:
      model: "llava"
      messages:
        - role: "user"
          content: "Describe this image"
      image: "${file.content}"
```

For production deployments requiring advanced load balancing and high availability, consider using external load balancers (nginx, HAProxy) or container orchestration platforms alongside Gleitzeit.