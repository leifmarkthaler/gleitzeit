# Gleitzeit - Simple LLM Workflow Orchestration

Run LLM workflows with a single command. Chain tasks, process files in batch, and integrate Python code - all without complexity.

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
      messages:
        - role: "user"
          content: "Write a haiku about coding"
```

Run it:
```bash
gleitzeit run workflow.yaml
```

That's it. No configuration needed - it uses local Ollama by default.

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
    # Simple chat
    response = await client.chat("Hello, how are you?")
    
    # Process files in batch
    results = await client.batch_process(
        directory="reports",
        pattern="*.txt",
        prompt="Extract key points"
    )
```

### 3. YAML Workflows - For Complex Pipelines

```yaml
name: "Document Analyzer"
tasks:
  - id: "read"
    method: "python/execute"
    parameters:
      code: |
        with open('data.txt') as f:
            content = f.read()
        return content

  - id: "analyze"
    method: "llm/chat"
    dependencies: ["read"]
    parameters:
      messages:
        - role: "user"
          content: "Analyze this: ${read.result}"

  - id: "save"
    method: "python/execute"
    dependencies: ["analyze"]
    parameters:
      code: |
        with open('analysis.txt', 'w') as f:
            f.write('${analyze.response}')
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
      messages:
        - content: "Generate a story idea"
  
  - id: "step2"
    method: "llm/chat"
    dependencies: ["step1"]
    parameters:
      messages:
        - content: "Expand this idea: ${step1.response}"
```

### Mix Python and LLMs
```python
async with Client() as client:
    # Get LLM response
    analysis = await client.chat("Analyze this sales data: ...")
    
    # Process with Python
    result = await client.execute_python(f"""
        data = '{analysis}'
        # Process the analysis
        return processed_data
    """)
```

## Why Gleitzeit?

- **Zero Config** - Works out of the box with local Ollama
- **Simple** - One command to run workflows
- **Flexible** - Use CLI, Python, or YAML
- **Fast** - Parallel task execution
- **Reliable** - Automatic retries and error handling

## Next Steps

- [5-Minute Tutorial](tutorial.md) - Build your first workflow
- [Examples](examples.md) - Copy-paste ready examples
- [Python API](python.md) - For developers
- [CLI Reference](cli.md) - All commands

## Requirements

- Python 3.9+
- Ollama (for local LLMs) or API keys for cloud providers

---

**Getting Help:** [GitHub Issues](https://github.com/gleitzeit/gleitzeit) | [Documentation](https://gleitzeit.dev)