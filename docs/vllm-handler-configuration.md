# vLLM Handler Configuration

The vLLM handler provides integration with vLLM for high-performance LLM inference using the OpenAI-compatible API.

## Configuration

Add vLLM handler configuration to your `gleitzeit.yaml`:

```yaml
handlers:
  vllm:
    base_url: "http://localhost:8000"  # vLLM server URL
    timeout: 300                        # Request timeout in seconds
    default_model: "meta-llama/Llama-2-7b-hf"  # Optional default model
    default_max_tokens: 256             # Optional default max tokens
    default_temperature: 0.7            # Optional default temperature
    api_key: null                       # Optional API key for authentication
    circuit_breaker:                    # Optional circuit breaker config
      failure_threshold: 5
      success_threshold: 2
      reset_timeout: 60
      half_open_max_calls: 3
```

## Starting vLLM Server

### Basic Usage

```bash
# Install vLLM
pip install vllm

# Start vLLM server with a model
vllm serve meta-llama/Llama-2-7b-hf

# Or with specific port and GPU
vllm serve meta-llama/Llama-2-7b-hf --port 8000 --gpu-memory-utilization 0.9
```

### Advanced Options

```bash
# Enable tensor parallelism for multi-GPU
vllm serve meta-llama/Llama-2-70b-hf --tensor-parallel-size 4

# Set quantization for lower memory
vllm serve meta-llama/Llama-2-7b-hf --quantization awq

# Custom max model length
vllm serve meta-llama/Llama-2-7b-hf --max-model-len 4096
```

## Supported Methods

### 1. Text Completions (`vllm/completions`)

Generate text from a prompt.

**Required Parameters:**
- `prompt` (string): Input text
- `model` (string): Model identifier

**Optional Parameters:**
- `max_tokens` (int): Maximum tokens to generate
- `temperature` (float): Sampling temperature (0.0-2.0)
- `top_p` (float): Nucleus sampling threshold
- `top_k` (int): Top-k sampling
- `frequency_penalty` (float): Penalize repeated tokens
- `presence_penalty` (float): Penalize existing tokens
- `stop` (string/list): Stop sequences
- `stream` (bool): Enable streaming
- `logprobs` (int): Return log probabilities
- `echo` (bool): Echo back the prompt
- `n` (int): Number of completions
- `best_of` (int): Generate N and return best

**Example:**

```yaml
tasks:
  - id: generate_text
    type: vllm
    method: vllm/completions
    params:
      model: "meta-llama/Llama-2-7b-hf"
      prompt: "Write a short story about"
      max_tokens: 200
      temperature: 0.8
      top_p: 0.95
      stop: ["\n\n"]
```

### 2. Chat Completions (`vllm/chat`)

Multi-turn conversations with chat history.

**Required Parameters:**
- `messages` (list): Conversation history
- `model` (string): Model identifier

**Message Format:**
```yaml
messages:
  - role: "system"
    content: "You are a helpful assistant"
  - role: "user"
    content: "Hello!"
  - role: "assistant"
    content: "Hi! How can I help?"
  - role: "user"
    content: "Tell me about Python"
```

**Optional Parameters:**
Same as completions (except `echo`, `best_of`)

**Example:**

```yaml
tasks:
  - id: chat_task
    type: vllm
    method: vllm/chat
    params:
      model: "meta-llama/Llama-2-7b-hf"
      messages:
        - role: "system"
          content: "You are a coding expert"
        - role: "user"
          content: "Explain async/await in Python"
      max_tokens: 300
      temperature: 0.7
```

### 3. List Models (`vllm/models`)

Get available models from the vLLM server.

**Parameters:** None

**Example:**

```yaml
tasks:
  - id: list_models
    type: vllm
    method: vllm/models
    params: {}
```

## Response Format

### Completions Response

```python
{
    'text': 'Generated text here...',
    'model': 'meta-llama/Llama-2-7b-hf',
    'finish_reason': 'stop',  # or 'length'
    'usage': {
        'prompt_tokens': 10,
        'completion_tokens': 50,
        'total_tokens': 60
    },
    'id': 'cmpl-xxx',
    'created': 1234567890
}
```

### Chat Response

```python
{
    'message': {
        'role': 'assistant',
        'content': 'Response text here...'
    },
    'model': 'meta-llama/Llama-2-7b-hf',
    'finish_reason': 'stop',
    'usage': {
        'prompt_tokens': 20,
        'completion_tokens': 100,
        'total_tokens': 120
    }
}
```

### Streaming Response

When `stream: true`, response includes:
```python
{
    'text': 'Full accumulated text',
    'chunks': 42,  # Number of chunks received
    'finish_reason': 'stop',
    'usage': {...}
}
```

## Complete Workflow Examples

### Simple Text Generation

```yaml
name: vllm-text-generation
tasks:
  - id: generate
    type: vllm
    method: vllm/completions
    params:
      model: "meta-llama/Llama-2-7b-hf"
      prompt: "Explain quantum computing in simple terms:"
      max_tokens: 200
      temperature: 0.7
    timeout: 60
```

### Conversational Workflow

```yaml
name: vllm-conversation
tasks:
  - id: greet
    type: vllm
    method: vllm/chat
    params:
      model: "meta-llama/Llama-2-7b-hf"
      messages:
        - role: "system"
          content: "You are a friendly AI assistant"
        - role: "user"
          content: "Hi there!"
      max_tokens: 100

  - id: follow_up
    type: vllm
    method: vllm/chat
    params:
      model: "meta-llama/Llama-2-7b-hf"
      messages:
        - role: "system"
          content: "You are a friendly AI assistant"
        - role: "user"
          content: "Tell me a joke"
      max_tokens: 150
    depends_on: [greet]
```

### Streaming Generation

```yaml
name: vllm-streaming
tasks:
  - id: stream_story
    type: vllm
    method: vllm/completions
    params:
      model: "meta-llama/Llama-2-7b-hf"
      prompt: "Write a haiku about code:"
      max_tokens: 50
      temperature: 0.8
      stream: true  # Enable streaming
```

## Error Handling

The vLLM handler includes:

- **Circuit Breaker**: Automatically opens after 5 consecutive failures, preventing cascading failures
- **Timeout Protection**: Configurable timeouts prevent hanging requests
- **Retry Support**: Works with Gleitzeit's retry mechanism
- **Detailed Errors**: Clear error messages with error codes

### Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `CONNECTION_REFUSED` | vLLM server not running | Start vLLM with `vllm serve <model>` |
| `PROVIDER_ERROR` | Invalid model or parameters | Check model name and parameters |
| `TIMEOUT` | Request took too long | Increase timeout or reduce max_tokens |
| `CIRCUIT_BREAKER_OPEN` | Too many failures | Wait for circuit breaker to reset |

## Best Practices

1. **Model Selection**: Use smaller models (7B) for faster responses, larger (70B+) for better quality
2. **Temperature**: Use 0.0-0.3 for factual tasks, 0.7-1.0 for creative tasks
3. **Max Tokens**: Set reasonable limits to prevent runaway generation
4. **Streaming**: Enable for long-form content to see progress
5. **Circuit Breaker**: Keep default settings unless you have specific needs
6. **Timeouts**: Set based on your model size and hardware (larger models need more time)

## Performance Tips

1. **GPU Memory**: Use `--gpu-memory-utilization 0.9` for better throughput
2. **Batch Size**: vLLM automatically batches requests
3. **Quantization**: Use AWQ or GPTQ for 2-4x speedup with minimal quality loss
4. **Tensor Parallelism**: Use multiple GPUs for large models
5. **Max Model Length**: Reduce if you don't need long context

## Example: Complete Production Setup

```yaml
# gleitzeit.yaml
handlers:
  vllm:
    base_url: "http://localhost:8000"
    timeout: 120
    default_model: "meta-llama/Llama-2-13b-hf"
    default_max_tokens: 512
    default_temperature: 0.7
    circuit_breaker:
      failure_threshold: 3
      success_threshold: 2
      reset_timeout: 30

# Start vLLM (in separate terminal)
# vllm serve meta-llama/Llama-2-13b-hf --gpu-memory-utilization 0.9 --max-model-len 4096

# Workflow
name: production-vllm-workflow
tasks:
  - id: classify
    type: vllm
    method: vllm/chat
    params:
      messages:
        - role: "system"
          content: "Classify the sentiment as positive, negative, or neutral"
        - role: "user"
          content: "I love this product!"
      max_tokens: 10
      temperature: 0.1
    timeout: 30

  - id: generate_response
    type: vllm
    method: vllm/completions
    params:
      prompt: "Generate a customer service response for positive feedback:"
      max_tokens: 150
      temperature: 0.7
    depends_on: [classify]
    timeout: 60
```

## Related

- [Ollama Handler](ollama-handler.md) - Similar handler for Ollama
- [HTTP Handler](http-handler.md) - Generic HTTP client
- [vLLM Documentation](https://docs.vllm.ai/) - Official vLLM docs
