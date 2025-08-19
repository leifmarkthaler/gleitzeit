# Gleitzeit - Local LLM Workflow Orchestration

Run LLM workflows locally with Ollama. Chain tasks, process files in batch, and execute Python scripts - all on your machine.

## Prerequisites

```bash
# Install and start Ollama
brew install ollama  # or see ollama.ai for other platforms
ollama serve

# Pull a model
ollama pull llama3.2
```

## Install

```bash
pip install gleitzeit
```

## Run Your First Workflow

Create `workflow.yaml`:
```yaml
name: "My Assistant"
tasks:
  - id: "chat"
    method: "llm/chat"
    parameters:
      model: "llama3.2"  # Must be an Ollama model
      messages:
        - role: "user"
          content: "Write a haiku about coding"
```

Run it:
```bash
gleitzeit run workflow.yaml
```

Uses your local Ollama instance - no API keys needed.

## Three Ways to Use Gleitzeit

### 1. CLI - For Quick Tasks

```bash
# Chat with an LLM
gleitzeit chat "Explain quantum computing in simple terms"

# Process multiple files
gleitzeit batch documents --pattern "*.pdf" --prompt "Summarize this document"

# Run a workflow
gleitzeit run workflow.yaml
```

### 2. Python - For Scripts

```python
from gleitzeit import Client

async with Client() as client:
    # Chat with local Ollama models
    response = await client.chat("Hello, how are you?", model="llama3.2")
    
    # Process files in batch
    results = await client.batch_process(
        directory="reports",
        pattern="*.txt",
        prompt="Extract key points",
        model="llama3.2"
    )
```

### 3. YAML Workflows - For Complex Pipelines

```yaml
name: "Document Analyzer"
tasks:
  - id: "read"
    method: "python/execute"
    parameters:
      script: "scripts/read_file.py"  # Python scripts as files
      args:
        filename: "data.txt"

  - id: "analyze"
    method: "llm/chat"
    dependencies: ["read"]
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Analyze this: ${read.result}"

  - id: "save"
    method: "python/execute"
    dependencies: ["analyze"]
    parameters:
      script: "scripts/save_file.py"
      args:
        content: "${analyze.response}"
        filename: "analysis.txt"
```

## Common Use Cases

### Batch Process Documents
```bash
gleitzeit batch reports --pattern "*.pdf" --prompt "Summarize in 3 bullets"
```

### Chain LLM Calls
```yaml
tasks:
  - id: "step1"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages:
        - content: "Generate a story idea"
  
  - id: "step2"
    method: "llm/chat"
    dependencies: ["step1"]
    parameters:
      model: "llama3.2"
      messages:
        - content: "Expand this idea: ${step1.response}"
```

### Mix Python Scripts and LLMs

Create `process_data.py`:
```python
import sys
import json

def main(data):
    # Process the LLM analysis
    processed = data.upper()  # Your processing logic
    return {"processed": processed}

if __name__ == "__main__":
    data = sys.argv[1]
    result = main(data)
    print(json.dumps(result))
```

Use in workflow:
```yaml
tasks:
  - id: "analyze"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages:
        - content: "Analyze this sales data..."
  
  - id: "process"
    method: "python/execute"
    dependencies: ["analyze"]
    parameters:
      script: "process_data.py"
      args:
        data: "${analyze.response}"
```

## Why Gleitzeit?

- **100% Local** - All processing on your machine with Ollama
- **No API Keys** - No cloud dependencies or costs
- **Simple** - One command to run workflows
- **Fast** - Parallel task execution
- **Reliable** - Automatic retries and error handling

## Available Ollama Models

```bash
# Text generation
ollama pull llama3.2       # Fast, general purpose
ollama pull mistral        # Good for code
ollama pull codellama      # Specialized for coding

# Vision models (for images)
ollama pull llava          # Image understanding
ollama pull bakllava       # Alternative vision model
```

## Next Steps

- [5-Minute Tutorial](tutorial.md) - Build your first workflow
- [Examples](examples.md) - Copy-paste ready examples
- [Python API](python.md) - For developers
- [CLI Reference](cli.md) - All commands

## Requirements

- Python 3.9+
- Ollama installed and running
- At least one Ollama model pulled

---

**Getting Help:** [GitHub Issues](https://github.com/gleitzeit/gleitzeit) | [Documentation](https://gleitzeit.dev)