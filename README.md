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

### Workflows (Multiple Tasks)

```bash
# Create a workflow file
cat > document_analysis.yaml << EOF
name: "Document Analysis Pipeline"
tasks:
  - name: "Extract Text"
    image: "document.png"
    prompt: "Extract all text from this document"
    model: "llava"
    
  - name: "Summarize"
    prompt: "Summarize this text: {{task_1.result}}"
    model: "llama3"
    dependencies: ["task_1"]
    
  - name: "Translate"  
    prompt: "Translate to Spanish: {{task_2.result}}"
    model: "llama3"
    dependencies: ["task_2"]
EOF

# Run the workflow
gleitzeit run --workflow document_analysis.yaml
```

### Built-in Functions

```bash
# Data analysis functions
gleitzeit run --function random_data --args data_type=numbers count=100 min=1 max=1000
gleitzeit run --function analyze_numbers --args numbers="[1,5,10,15,20]"

# Text processing functions  
gleitzeit run --function count_words --args text="Hello world from Gleitzeit"
gleitzeit run --function extract_keywords --args text="Machine learning and AI"

# CSV data processing
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

For programmatic workflows:

```python
import asyncio
from gleitzeit_cluster import GleitzeitCluster, Task, TaskType, TaskParameters, Workflow

async def main():
    cluster = GleitzeitCluster()
    await cluster.start()
    
    # Create tasks
    generate_task = Task(
        name="Generate Content",
        task_type=TaskType.TEXT,
        parameters=TaskParameters(
            prompt="Write a blog post about AI safety",
            model_name="llama3"
        )
    )
    
    summarize_task = Task(
        name="Summarize",
        task_type=TaskType.TEXT,
        parameters=TaskParameters(
            prompt="Create a 2-sentence summary: {{task_1.result}}",
            model_name="llama3"
        ),
        dependencies=["task_1"]
    )
    
    # Create and submit workflow
    workflow = Workflow(
        name="Content Pipeline",
        tasks=[generate_task, summarize_task]
    )
    
    workflow_id = await cluster.submit_workflow(workflow)
    
    # Wait for completion
    while True:
        status = await cluster.get_workflow_status(workflow_id)
        if status["status"] in ["completed", "failed"]:
            break
        await asyncio.sleep(1)
    
    if status["status"] == "completed":
        print("Results:", status["task_results"])
    
    await cluster.stop()

asyncio.run(main())
```

## What Makes This Different?

- **Local-first**: Everything runs on your machine
- **No API keys**: No cloud dependencies or costs
- **Workflow orchestration**: Chain tasks with dependencies and data flow
- **Built-in functions**: 30+ secure functions for data processing
- **Privacy**: Your data never leaves your computer
- **Simple**: Just install and run commands
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
