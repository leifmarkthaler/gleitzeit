# Gleitzeit

**Local-First LLM Task Runner**

Run LLM and vision tasks locally with a simple CLI. No cloud dependencies, just pure local processing. 

## Quick Install

```bash
# One-line installer
curl -sSL https://raw.githubusercontent.com/leifmarkthaler/gleitzeit/main/install.sh | bash
```

After installation, restart your terminal.

## Simple Examples

### Text Generation with LLMs

```bash
# Start the task runner
gleitzeit dev

# Generate text with Ollama (requires ollama installed)
gleitzeit run --text "Write a Python function to calculate fibonacci numbers"

# Analyze text
gleitzeit run --text "Summarize the key benefits of renewable energy" --model llama3

# Creative writing
gleitzeit run --text "Write a short story about a robot learning to paint"
```

### Vision Tasks

```bash
# Analyze an image
gleitzeit run --vision photo.jpg --prompt "What's in this image?"

# Extract text from image
gleitzeit run --vision document.png --prompt "Extract all text from this image"

# Describe charts or graphs
gleitzeit run --vision chart.png --prompt "Explain what this chart shows"
```

### Python Functions

```bash
# List available functions
gleitzeit functions list

# Run built-in functions
gleitzeit run --function fibonacci_sequence --args n=10
gleitzeit run --function analyze_numbers --args numbers=[1,2,3,4,5]

# Process CSV data
gleitzeit run --function csv_filter --args file=data.csv column=age min_value=18
```

### Quick Monitoring

```bash
# Terminal monitoring (in new terminal)
gleitzeit pro

# Simple status check
gleitzeit status
```

## Requirements

- **Python 3.9+**
- **Ollama** (for LLM tasks): `curl -fsSL https://ollama.ai/install.sh | sh`
- **Models**: `ollama pull llama3` and `ollama pull llava` (for vision)

## Python API (Optional)

For more advanced workflows:

```python
import asyncio
from gleitzeit_cluster import GleitzeitCluster, Task, TaskType, TaskParameters

async def main():
    cluster = GleitzeitCluster()
    await cluster.start()
    
    # Text generation task
    task = Task(
        name="Generate Code",
        task_type=TaskType.TEXT,
        parameters=TaskParameters(
            prompt="Write a Python function to sort a list",
            model="llama3"
        )
    )
    
    result = await cluster.execute_task(task)
    print(result)
    
    await cluster.stop()

asyncio.run(main())
```

## What Makes This Different?

- **Local-first**: Everything runs on your machine
- **No API keys**: No cloud dependencies or costs
- **Simple**: Just install and run commands
- **Privacy**: Your data never leaves your computer
- **Extensible**: 30+ built-in functions + Python API

## Status

- **Version**: 0.0.1 (Early Development)
- **License**: MIT
- **Python**: 3.9+ required

## Roadmap

- [ ] More LLM integrations (OpenAI, Anthropic)
- [ ] Workflow templates
- [ ] Web interface
- [ ] Multi-machine clustering

## Contributing

This is an early-stage project. Issues and pull requests welcome!

**Repository**: https://github.com/leifmarkthaler/gleitzeit
