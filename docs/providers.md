# Providers

Providers implement protocols and execute tasks. Gleitzeit includes several built-in providers and supports custom provider development.

## Built-in Providers

### OllamaProvider

Handles LLM operations using Ollama models.

**Protocol:** `llm/v1`

**Methods:**

#### llm/chat

Text generation with conversation context.

```yaml
method: "llm/chat"
parameters:
  model: "llama3.2"          # Required: Ollama model name
  messages:                  # Required: Conversation messages
    - role: "system"         # Optional system message
      content: "You are helpful"
    - role: "user"
      content: "Hello"
  temperature: 0.7           # Optional: 0-1, default 0.7
  max_tokens: 500           # Optional: Max response length
  top_p: 0.9                # Optional: Nucleus sampling
  top_k: 40                 # Optional: Top-k sampling
  seed: 42                  # Optional: For reproducibility
```

#### llm/vision

Image analysis with vision models.

```yaml
method: "llm/vision"
parameters:
  model: "llava"            # Required: Vision model
  images:                   # Required: Image paths
    - "photo.jpg"
  messages:
    - role: "user"
      content: "What's in this image?"
```

#### llm/generate

Direct text generation without conversation context.

```yaml
method: "llm/generate"
parameters:
  model: "llama3.2"
  prompt: "Complete this: Once upon a time"
  temperature: 0.8
```

#### llm/embeddings

Generate text embeddings.

```yaml
method: "llm/embeddings"
parameters:
  model: "llama3.2"
  text: "Text to embed"
```

**Available Models:**

Install models with Ollama:

```bash
# General purpose
ollama pull llama3.2
ollama pull mistral

# Code generation
ollama pull codellama
ollama pull deepseek-coder

# Vision
ollama pull llava
ollama pull bakllava

# Small/fast
ollama pull phi
ollama pull tinyllama
```

### PythonProvider

Executes Python scripts in isolated environments.

**Protocol:** `python/v1`

**Methods:**

#### python/execute

Execute a Python script file.

```yaml
method: "python/execute"
parameters:
  script: "process.py"      # Required: Script path
  args:                     # Optional: Arguments as JSON
    input: "data.csv"
    output: "results.json"
  timeout: 30              # Optional: Timeout in seconds
  env:                     # Optional: Environment variables
    PYTHONPATH: "/custom/path"
```

**Script Requirements:**

Scripts receive arguments via `sys.argv[1]` as JSON and should print JSON output:

```python
#!/usr/bin/env python3
import sys
import json

# Get arguments
args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}

# Process
result = {"status": "success", "data": process(args)}

# Output as JSON
print(json.dumps(result))
```

#### python/validate

Validate Python syntax without execution.

```yaml
method: "python/validate"
parameters:
  script: "code.py"
```

### SimpleMCPProvider

Implements Model Context Protocol tools.

**Protocol:** `mcp/v1`

**Built-in Methods:**

#### mcp/tool.echo

Echo a message.

```yaml
method: "mcp/tool.echo"
parameters:
  message: "Hello, MCP!"
```

#### mcp/tool.add

Add numbers.

```yaml
method: "mcp/tool.add"
parameters:
  a: 10
  b: 20
```

#### mcp/tool.multiply

Multiply numbers.

```yaml
method: "mcp/tool.multiply"
parameters:
  a: 5
  b: 7
```

#### mcp/tool.concat

Concatenate strings.

```yaml
method: "mcp/tool.concat"
parameters:
  strings: ["Hello", " ", "World"]
```

### TemplateProvider

Generates pre-built workflow templates for common multi-step patterns.

**Protocol:** `template/v1`

**Purpose:** Provides convenience templates that automatically create complex workflows with proper dependencies and parameter substitution.

**Methods:**

#### template/research

Generate a multi-step research workflow.

```yaml
method: "template/research"
parameters:
  topic: "Quantum Computing"     # Required: Research topic
  max_steps: 5                   # Optional: Number of research steps
  depth: "medium"                 # Optional: Research depth (shallow/medium/deep)
```

Creates a workflow that:
1. Plans research strategy
2. Gathers background information
3. Analyzes current trends
4. Performs analysis and implications
5. Generates comprehensive research report

#### template/code

Generate a code development workflow.

```yaml
method: "template/code"
parameters:
  task: "Create a REST API for user management"  # Required: Coding task
  language: "python"                              # Optional: Programming language
```

Creates a workflow that:
1. Analyzes requirements and plans approach
2. Generates initial code
3. Tests and validates code (for Python)
4. Reviews and optimizes code
5. Generates documentation

#### template/analyze

Generate a content analysis workflow.

```yaml
method: "template/analyze"
parameters:
  content: "Long document text..."              # Required: Content to analyze
  question: "What are the key insights?"        # Optional: Specific question
```

Creates a single-step analysis workflow that provides structured analysis of the content.

#### template/chat

Generate a simple chat workflow.

```yaml
method: "template/chat"
parameters:
  message: "Hello, how are you?"               # Required: Chat message
  session_id: "session_123"                    # Optional: Session identifier
```

Creates a single-step chat interaction workflow.

## Provider Configuration

### Ollama Configuration

```yaml
# In ~/.gleitzeit/config.yaml
providers:
  ollama:
    endpoint: http://localhost:11434
    timeout: 30
    max_retries: 3
    models:
      default: llama3.2
      vision: llava
      code: codellama
```

### Python Configuration

```yaml
providers:
  python:
    timeout: 60
    max_memory: "512M"
    allowed_modules:
      - json
      - csv
      - math
      - datetime
    sandbox: true  # Enable sandboxing
```

## Custom Providers

### Creating a Custom Provider

Create a provider by extending the base class:

```python
from gleitzeit.providers.base import BaseProvider
from gleitzeit.core.models import TaskResult
from typing import Dict, Any

class MyCustomProvider(BaseProvider):
    """Custom provider implementation"""
    
    def __init__(self):
        super().__init__()
        self.protocol = "custom/v1"
    
    async def execute(
        self,
        method: str,
        parameters: Dict[str, Any]
    ) -> TaskResult:
        """Execute a method"""
        
        if method == "custom/process":
            result = await self.process(parameters)
            return TaskResult(
                task_id=parameters.get("task_id"),
                status="completed",
                result=result
            )
        
        raise ValueError(f"Unknown method: {method}")
    
    async def process(self, params: Dict[str, Any]) -> Any:
        """Custom processing logic"""
        data = params.get("data")
        # Your processing here
        return {"processed": data}
    
    async def validate(self, method: str, parameters: Dict[str, Any]) -> bool:
        """Validate parameters"""
        if method == "custom/process":
            return "data" in parameters
        return False
```

### Registering a Custom Provider

```python
from gleitzeit.registry import ProtocolProviderRegistry
from my_providers import MyCustomProvider

# Register provider
registry = ProtocolProviderRegistry.get_instance()
provider = MyCustomProvider()
registry.register_provider("custom/v1", provider)

# Use in workflow
workflow = {
    "tasks": [{
        "id": "custom_task",
        "method": "custom/process",
        "parameters": {"data": "input"}
    }]
}
```

## Provider Selection

Providers are selected based on the method prefix:

- `llm/*` → OllamaProvider
- `python/*` → PythonProvider
- `mcp/*` → SimpleMCPProvider
- `template/*` → TemplateProvider

## Resource Management

### OllamaHub

Manages Ollama instances:

```python
# Auto-discovery on ports 11434-11439
# Health monitoring
# Load balancing across instances
# Model-aware routing
```

### DockerHub (Optional)

Manages Docker containers for Python execution:

```python
# Container lifecycle management
# Resource limits
# Security isolation
```

## Error Handling

Providers implement automatic retry logic:

```yaml
tasks:
  - id: "task"
    method: "llm/chat"
    retry:
      max_attempts: 3
      delay: 2
      exponential_backoff: true
```

## Performance Considerations

### Connection Pooling

Providers use connection pooling for efficiency:

```python
# OllamaProvider uses aiohttp session pooling
# Reuses connections across requests
# Configurable pool size
```

### Caching

Some providers implement caching:

```python
# Template compilation caching
# Python bytecode caching
# Model response caching (optional)
```

### Timeouts

All providers support configurable timeouts:

```yaml
parameters:
  timeout: 30  # Task-level timeout
```

## Provider Capabilities

| Provider | Async | Streaming | Batch | Caching | Sandboxed |
|----------|-------|-----------|-------|---------|-----------|
| Ollama | ✓ | ✓ | ✓ | ✗ | N/A |
| Python | ✓ | ✗ | ✗ | ✓ | ✓ |
| MCP | ✓ | ✗ | ✗ | ✗ | N/A |
| Template | ✓ | ✗ | ✓ | ✓ | N/A |

## Best Practices

1. **Set appropriate timeouts** - Prevent hanging tasks
2. **Use retry logic** - Handle transient failures
3. **Validate inputs** - Check parameters before execution
4. **Handle errors gracefully** - Provide useful error messages
5. **Log operations** - For debugging
6. **Use connection pooling** - For efficiency
7. **Implement caching** - Where appropriate
8. **Monitor resource usage** - Prevent resource exhaustion

## Examples

### Multi-Provider Workflow

```yaml
name: "Multi-Provider Example"
tasks:
  # Generate data with Python
  - id: "generate"
    method: "python/execute"
    parameters:
      script: "generate_data.py"
  
  # Analyze with LLM
  - id: "analyze"
    method: "llm/chat"
    dependencies: ["generate"]
    parameters:
      model: "llama3.2"
      messages:
        - content: "Analyze: ${generate.data}"
  
  # Use MCP tool for calculation
  - id: "calculate"
    method: "mcp/tool.add"
    dependencies: ["analyze"]
    parameters:
      a: 100
      b: 50
  
  # Generate final report
  - id: "report"
    method: "llm/chat"
    dependencies: ["analyze", "calculate"]
    parameters:
      model: "llama3.2"
      messages:
        - content: |
            Create a report with:
            Analysis: ${analyze.response}
            Calculation result: ${calculate.result}
```

### Using Template Provider

```yaml
name: "Template Provider Example"
tasks:
  # Generate a complete research workflow
  - id: "research_workflow"
    method: "template/research"
    parameters:
      topic: "Artificial Intelligence in Healthcare"
      depth: "deep"
      max_steps: 5
  
  # Or generate a code development workflow
  - id: "code_workflow"
    method: "template/code"
    parameters:
      task: "Create a Python script to parse CSV files"
      language: "python"
```