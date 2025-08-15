# Gleitzeit Python API Quick Reference

## Installation
```bash
pip install -e .
```

## Basic Usage

```python
from gleitzeit import GleitzeitClient

# Async context manager (recommended)
async with GleitzeitClient() as client:
    response = await client.chat("Hello!")
```

## Core Methods

### Chat Completion
```python
response = await client.chat(
    prompt="Your question",
    model="llama3.2:latest",  # optional
    system="System prompt",    # optional
    temperature=0.7,           # optional
    max_tokens=100            # optional
)
```

### Image Analysis
```python
description = await client.vision(
    image_path="photo.jpg",
    prompt="What's in this image?",
    model="llava:latest"  # optional
)
```

### Python Script Execution
```python
result = await client.execute_python(
    script_file="script.py",
    context={"var": "value"},  # optional
    timeout=10                 # optional
)
```

## Workflows

### Run from YAML
```python
results = await client.run_workflow("workflow.yaml")
```

### Create Programmatically
```python
workflow = await client.create_workflow(
    name="My Workflow",
    tasks=[
        {
            "id": "task1",
            "method": "llm/chat",
            "params": {
                "model": "llama3.2:latest",
                "messages": [{"role": "user", "content": "Hello"}]
            }
        },
        {
            "id": "task2",
            "dependencies": ["task1"],
            "method": "llm/chat",
            "params": {
                "messages": [{"role": "user", "content": "Continue: ${task1.response}"}]
            }
        }
    ]
)
results = await client.run_workflow(workflow)
```

## Batch Processing

### Process Multiple Files
```python
results = await client.batch_chat(
    directory="documents",
    pattern="*.txt",
    prompt="Summarize this",
    model="llama3.2:latest"
)
```

## Client Configuration

```python
# Default (SQLite)
client = GleitzeitClient()

# Memory backend (testing)
client = GleitzeitClient(persistence="memory")

# Redis backend
client = GleitzeitClient(
    persistence="redis",
    redis_url="redis://localhost:6379/0"
)

# Custom Ollama URL
client = GleitzeitClient(
    ollama_url="http://remote:11434"
)
```

## Task Methods

| Method | Protocol | Description |
|--------|----------|-------------|
| `llm/chat` | `llm/v1` | Chat with LLM |
| `llm/vision` | `llm/v1` | Analyze images |
| `python/execute` | `python/v1` | Run Python scripts |
| `mcp/tool.echo` | `mcp/v1` | Echo message |
| `mcp/tool.add` | `mcp/v1` | Add numbers |
| `mcp/tool.multiply` | `mcp/v1` | Multiply numbers |
| `mcp/tool.concat` | `mcp/v1` | Concatenate strings |

## Parameter Substitution

Reference previous task results using `${task_id.field}`:

```python
tasks = [
    {"id": "task1", "method": "python/execute", ...},
    {
        "id": "task2",
        "dependencies": ["task1"],
        "params": {
            "input": "${task1.result}"  # Use task1's result
        }
    }
]
```

## Convenience Functions

Quick operations without client management:

```python
from gleitzeit.client import chat, vision, run_workflow

# One-liners
response = await chat("Quick question")
description = await vision("image.jpg")
results = await run_workflow("workflow.yaml")
```

## Complete Example

```python
import asyncio
from gleitzeit import GleitzeitClient

async def main():
    async with GleitzeitClient(persistence="memory") as client:
        # Chat
        joke = await client.chat("Tell me a joke")
        print(f"Joke: {joke}")
        
        # Run workflow
        workflow = await client.create_workflow(
            name="Analysis",
            tasks=[
                {
                    "id": "generate",
                    "method": "python/execute",
                    "params": {"file": "generate.py"}
                },
                {
                    "id": "analyze",
                    "dependencies": ["generate"],
                    "method": "llm/chat",
                    "params": {
                        "messages": [{
                            "role": "user",
                            "content": "Analyze: ${generate.result}"
                        }]
                    }
                }
            ]
        )
        results = await client.run_workflow(workflow)
        
        # Batch process
        batch_results = await client.batch_chat(
            directory="docs",
            pattern="*.txt",
            prompt="Summarize"
        )

asyncio.run(main())
```

## Error Handling

```python
try:
    result = await client.chat("Hello")
except RuntimeError as e:
    print(f"Failed: {e}")
```

## Environment Variables

```bash
export GLEITZEIT_PERSISTENCE_BACKEND=sqlite
export GLEITZEIT_SQLITE_PATH=~/.gleitzeit/db.sqlite
export GLEITZEIT_REDIS_URL=redis://localhost:6379
export GLEITZEIT_OLLAMA_URL=http://localhost:11434
```