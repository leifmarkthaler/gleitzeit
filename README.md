# Gleitzeit Documentation

Gleitzeit is a workflow orchestration system for running LLM operations, Python scripts, and other tasks in sequence or parallel.

## Quick Start

### Install

```bash
pip install gleitzeit
ollama pull llama3.2
```

### Basic Example

Create a workflow file `example.yaml`:

```yaml
name: "Example"
tasks:
  - id: "greet"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Say hello"
```

Run it:

```bash
gleitzeit run example.yaml
```

### Use from Python

```python
import asyncio
from gleitzeit import GleitzeitClient

async def main():
    async with GleitzeitClient() as client:
        # Run a workflow
        result = await client.run_workflow("example.yaml")
        print(result)
        
        # Or chat directly
        response = await client.chat(
            "What is Python?",
            model="llama3.2"
        )
        print(response)

asyncio.run(main())
```

## Core Examples

### Chain Tasks Together

Create `pipeline.yaml`:

```yaml
name: "Analysis Pipeline"
tasks:
  - id: "extract"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Extract key points from: Meeting was productive, discussed Q2 goals"
  
  - id: "summarize"
    method: "llm/chat"
    dependencies: ["extract"]
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Create summary from: ${extract.response}"
```

### Process Multiple Files

```yaml
name: "Batch Processor"
type: "batch"
batch:
  directory: "documents"
  pattern: "*.txt"
template:
  method: "llm/chat"
  model: "llama3.2"
  messages:
    - role: "user"
      content: "Summarize: ${file_content}"
```

Or from Python:

```python
async with GleitzeitClient() as client:
    results = await client.batch_process(
        directory="documents",
        pattern="*.txt",
        prompt="Summarize this document",
        model="llama3.2"
    )
    for file, summary in results.items():
        print(f"{file}: {summary}")
```

### Execute Python Scripts

Create `process.py`:

```python
import sys
import json

args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
data = args.get('data', '')

# Process the data
result = {"processed": data.upper(), "length": len(data)}

print(json.dumps(result))
```

Use in workflow:

```yaml
name: "Mixed Workflow"
tasks:
  - id: "generate"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Generate a sentence about AI"
  
  - id: "process"
    method: "python/execute"
    dependencies: ["generate"]
    parameters:
      script: "process.py"
      args:
        data: "${generate.response}"
```

## Key Features

### Parallel Execution

Tasks without dependencies run in parallel:

```yaml
tasks:
  - id: "task1"
    method: "llm/chat"
    # Runs immediately
    
  - id: "task2"
    method: "llm/chat"
    # Runs in parallel with task1
    
  - id: "combine"
    dependencies: ["task1", "task2"]
    # Waits for both to complete
```

### Error Handling

```yaml
tasks:
  - id: "risky_task"
    method: "llm/chat"
    retry:
      max_attempts: 3
      delay: 2
    parameters:
      timeout: 30
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Process this"
```

### Client Modes

```python
# Auto mode (default) - uses API if available
client = GleitzeitClient()

# Force API mode
client = GleitzeitClient(mode="api")

# Force native mode (direct execution)
client = GleitzeitClient(mode="native")

# Custom API server
client = GleitzeitClient(
    mode="api",
    api_host="server.example.com",
    api_port=8000
)
```

### Async Operations

```python
import asyncio

async def parallel_tasks():
    async with GleitzeitClient() as client:
        tasks = [
            client.chat("Question 1", model="llama3.2"),
            client.chat("Question 2", model="llama3.2"),
            client.chat("Question 3", model="llama3.2")
        ]
        responses = await asyncio.gather(*tasks)
        return responses
```

## Available Models

```yaml
parameters:
  model: "llama3.2"      # Fast, general
  # model: "mistral"     # Better reasoning
  # model: "codellama"   # Code generation
  # model: "llava"       # Image analysis
```

## Documentation

- [Installation](docs/installation.md) - Detailed installation guide
- [Core Concepts](docs/concepts.md) - Understand the architecture
- [Workflows](docs/workflows.md) - Creating complex workflows
- [CLI Reference](docs/cli.md) - Command-line interface
- [Python API](docs/api.md) - Complete API reference
- [Providers](docs/providers.md) - Available providers and creating custom ones
- [Configuration](docs/configuration.md) - Configuration options
- [Troubleshooting](docs/troubleshooting.md) - Common issues and solutions

## Requirements

- Python 3.8 or higher
- Ollama (for LLM operations)
- Redis or SQLite (optional, for persistence)

## License

MIT