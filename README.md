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
  - name: "extract_text"
    type: "vision"
    image_path: "document.pdf"
    prompt: "Extract all text from this document"
    
  - name: "summarize"
    type: "text" 
    prompt: "Summarize this text: {extract_text.result}"
    depends_on: ["extract_text"]
    
  - name: "translate"
    type: "text"
    prompt: "Translate to Spanish: {summarize.result}"
    depends_on: ["summarize"]
EOF

# Run the workflow
gleitzeit run --workflow document_analysis.yaml
```

### Batch Processing

```bash
# Process multiple images
gleitzeit run --vision "*.jpg" --prompt "Describe each image" --batch

# Analyze multiple documents
gleitzeit run --text "data/*.txt" --prompt "Extract key insights from each file" --batch

# Run function on multiple CSV files
gleitzeit run --function analyze_data --args files="reports/*.csv" --batch
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
from gleitzeit_cluster import GleitzeitCluster, Workflow

async def main():
    cluster = GleitzeitCluster()
    await cluster.start()
    
    # Create a multi-step workflow
    workflow = cluster.create_workflow("content_pipeline")
    
    # Step 1: Generate content
    workflow.add_task(
        "generate", 
        task_type="text",
        prompt="Write a blog post about AI safety",
        model="llama3"
    )
    
    # Step 2: Create summary (depends on step 1)
    workflow.add_task(
        "summarize",
        task_type="text", 
        prompt="Create a 2-sentence summary: {generate.result}",
        depends_on=["generate"]
    )
    
    # Step 3: Generate image prompt (parallel to summary)
    workflow.add_task(
        "image_prompt",
        task_type="text",
        prompt="Create an image description for: {generate.result}",
        depends_on=["generate"] 
    )
    
    # Execute workflow
    result = await cluster.execute_workflow(workflow)
    print(f"Summary: {result['summarize']}")
    print(f"Image prompt: {result['image_prompt']}")
    
    await cluster.stop()

asyncio.run(main())
```

## What Makes This Different?

- **Local-first**: Everything runs on your machine
- **No API keys**: No cloud dependencies or costs
- **Workflow orchestration**: Chain tasks with dependencies and data flow
- **Batch processing**: Handle multiple files with glob patterns
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
