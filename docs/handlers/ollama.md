# Ollama Handler

The Ollama handler provides integration with Ollama for local LLM inference in Gleitzeit workflows.

## Features

- **Text Generation**: Generate text from prompts with customizable parameters
- **Chat Completion**: Multi-turn conversations with context preservation
- **Embeddings**: Generate text embeddings for semantic analysis
- **Model Management**: List and pull available models
- **Streaming Support**: Stream responses for real-time output
- **Error Handling**: Robust error handling with retry-compatible error codes

## Installation

1. Install Ollama from [ollama.ai](https://ollama.ai)
2. Pull a model: `ollama pull llama2`
3. Ensure Ollama is running: `ollama serve`

## Configuration

```python
config = {
    'base_url': 'http://localhost:11434',  # Ollama server URL
    'timeout': 300,                         # Request timeout in seconds
    'default_model': 'llama2',             # Default model to use
    'default_options': {                    # Default generation options
        'temperature': 0.7,
        'num_predict': 100
    }
}
```

## Supported Methods

### ollama/generate
Generate text from a prompt.

**Parameters:**
- `prompt` (required): Input text prompt
- `model` (required): Model to use
- `options` (optional): Generation options (temperature, num_predict, etc.)
- `system` (optional): System prompt
- `template` (optional): Custom template
- `context` (optional): Context from previous generation
- `stream` (optional): Enable streaming (default: false)
- `raw` (optional): Raw mode without formatting

**Example:**
```python
task = Task(
    id='gen-1',
    workflow_id='workflow-1',
    protocol='ollama/v1',
    method='ollama/generate',
    params={
        'prompt': 'Explain quantum computing',
        'model': 'llama2',
        'options': {
            'temperature': 0.7,
            'num_predict': 200
        }
    }
)
```

### ollama/chat
Chat completion with conversation history.

**Parameters:**
- `messages` (required): List of message objects with 'role' and 'content'
- `model` (required): Model to use
- `options` (optional): Generation options
- `template` (optional): Custom template
- `stream` (optional): Enable streaming

**Example:**
```python
task = Task(
    id='chat-1',
    workflow_id='workflow-1',
    protocol='ollama/v1',
    method='ollama/chat',
    params={
        'messages': [
            {'role': 'system', 'content': 'You are a helpful assistant'},
            {'role': 'user', 'content': 'What is Python?'}
        ],
        'model': 'llama2'
    }
)
```

### ollama/embeddings
Generate embeddings for text.

**Parameters:**
- `prompt` (required): Text to embed
- `model` (required): Model to use (must support embeddings)
- `options` (optional): Embedding options

**Example:**
```python
task = Task(
    id='embed-1',
    workflow_id='workflow-1',
    protocol='ollama/v1',
    method='ollama/embeddings',
    params={
        'prompt': 'Machine learning concepts',
        'model': 'llama2'
    }
)
```

### ollama/list_models
List available models.

**Parameters:** None

**Example:**
```python
task = Task(
    id='list-1',
    workflow_id='workflow-1',
    protocol='ollama/v1',
    method='ollama/list_models',
    params={}
)
```

### ollama/pull_model
Pull a model from the Ollama registry.

**Parameters:**
- `model` (required): Model name to pull
- `stream` (optional): Stream progress updates

**Example:**
```python
task = Task(
    id='pull-1',
    workflow_id='workflow-1',
    protocol='ollama/v1',
    method='ollama/pull_model',
    params={
        'model': 'codellama:latest'
    }
)
```

## Error Handling

The handler uses Gleitzeit error codes for consistency:

- `PROVIDER_ERROR`: API errors from Ollama
- `CONNECTION_REFUSED`: Cannot connect to Ollama server
- `TASK_TIMEOUT`: Request timeout
- `INVALID_PARAMS`: Invalid parameters
- `METHOD_NOT_SUPPORTED`: Unsupported method

## Workflow Integration

Example workflow using Ollama:

```yaml
name: ai-assistant
version: 1.0.0

tasks:
  - id: generate-code
    name: Generate Python Code
    protocol: ollama/v1
    method: ollama/generate
    params:
      model: codellama
      prompt: "Write a Python function to calculate fibonacci numbers"
      options:
        temperature: 0.3
        num_predict: 500

  - id: explain-code
    name: Explain Generated Code
    protocol: ollama/v1
    method: ollama/chat
    params:
      model: llama2
      messages:
        - role: system
          content: "You are a programming teacher"
        - role: user
          content: "Explain this code: {{ tasks.generate-code.result.response }}"
    depends_on:
      - generate-code
```

## Performance Considerations

1. **Model Loading**: First request to a model may be slower due to loading
2. **Context Length**: Larger contexts increase memory usage and processing time
3. **Streaming**: Use streaming for better user experience with long generations
4. **Timeout**: Adjust timeout based on model size and expected response length

## Troubleshooting

### Connection Refused
- Ensure Ollama is running: `ollama serve`
- Check the base_url configuration
- Verify firewall settings

### Model Not Found
- List available models: `ollama list`
- Pull required model: `ollama pull <model>`

### Timeout Errors
- Increase timeout in configuration
- Use smaller num_predict values
- Consider using streaming for long responses

## Advanced Usage

### Custom System Prompts
```python
params = {
    'model': 'llama2',
    'prompt': 'User question',
    'system': 'You are an expert in quantum physics',
    'options': {'temperature': 0.5}
}
```

### Context Preservation
```python
# First generation
result1 = await handler.execute(task1)
context = result1.result.get('context')

# Continue with context
task2.params['context'] = context
result2 = await handler.execute(task2)
```

### Streaming with Progress
```python
params = {
    'model': 'llama2',
    'prompt': 'Long story prompt',
    'stream': True
}
# Handler collects streamed chunks automatically
```

## Models

Popular models for different use cases:

- **llama2**: General purpose conversations
- **codellama**: Code generation and explanation
- **mistral**: Fast, efficient general model
- **mixtral**: Larger, more capable model
- **phi**: Small, fast model for simple tasks

## See Also

- [Ollama Documentation](https://github.com/ollama/ollama)
- [Gleitzeit Handlers Guide](../handlers.md)
- [Example Scripts](../../examples/ollama_example.py)