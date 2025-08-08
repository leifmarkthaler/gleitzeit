# Gleitzeit

**Distributed Workflow Orchestration System**

A local-first distributed computing platform for orchestrating tasks, workflows, and batch processing. Built for LLM tasks, data processing, and complex multi-step workflows.

## Quick Install

```bash
# Install from source
pip install -e .

# Or use the installer
curl -sSL https://raw.githubusercontent.com/leifmarkthaler/gleitzeit/main/install.sh | bash
```

## Core Concepts

### 🎯 Tasks
Individual units of work that can be executed independently.

- **Text Tasks**: LLM text generation and analysis
- **Vision Tasks**: Image analysis and processing  
- **Function Tasks**: Execute built-in or custom Python functions
- **HTTP Tasks**: Make API calls and process responses

### 🔄 Workflows
Orchestrate multiple tasks with dependencies and data flow.

- **Parallel execution**: Tasks run simultaneously when possible
- **Dependencies**: Control execution order with task dependencies
- **Data flow**: Pass results between tasks using `{{task_id.result}}`
- **Error handling**: Configure how workflows handle task failures

### 📦 Batch Processing
Process multiple items efficiently with parallel execution.

- **Parallel batching**: Process lists of items simultaneously
- **Staged processing**: Multi-stage batch pipelines
- **Auto-scaling**: Automatically scale processing based on load

### 🖥️ Cluster Management
Distributed execution across multiple nodes.

- **Auto-start**: Automatically start required services
- **Service management**: Redis and executor nodes managed automatically
- **Real-time monitoring**: Track progress across distributed execution

## CLI Usage

### Basic Task Execution

```bash
# Text generation
gleitzeit run --text "Explain quantum computing" --model llama3

# Image analysis
gleitzeit run --vision photo.jpg --prompt "Describe this image" --model llava

# Function execution
gleitzeit run --function fibonacci --args n=10

# List available functions
gleitzeit functions list
```

### Workflow Management

```bash
# Start development environment
gleitzeit dev

# Run workflow from file
gleitzeit run --workflow my_workflow.yaml

# Check cluster status
gleitzeit status

# Monitor with professional interface
gleitzeit pro
```

### Batch Processing

```bash
# Process multiple images
gleitzeit run --function async_batch_process --args 'items=["img1.jpg","img2.jpg","img3.jpg"]' delay=0.5

# Batch text analysis
gleitzeit run --workflow batch_analysis.yaml
```

## Python API

### Simple Task Execution

```python
import asyncio
from gleitzeit_cluster import GleitzeitCluster

async def main():
    # Create cluster
    cluster = GleitzeitCluster()
    await cluster.start()
    
    # Quick text analysis
    result = await cluster.analyze_text("Explain machine learning")
    print(result)
    
    # Quick image analysis
    results = await cluster.batch_analyze_images(
        "Describe the image",
        ["photo1.jpg", "photo2.jpg"]
    )
    print(results)
    
    await cluster.stop()

asyncio.run(main())
```

### Advanced Workflows

```python
import asyncio
from gleitzeit_cluster import GleitzeitCluster, Workflow, Task, TaskType, TaskParameters

async def main():
    cluster = GleitzeitCluster()
    await cluster.start()
    
    # Create workflow
    workflow = Workflow(name="Data Processing Pipeline")
    
    # Task 1: Generate data
    generate_task = workflow.add_python_task(
        name="Generate Dataset",
        function_name="fibonacci",
        kwargs={"n": 10}
    )
    
    # Task 2: Analyze data (depends on Task 1)
    analyze_task = workflow.add_python_task(
        name="Analyze Numbers", 
        function_name="analyze_numbers",
        kwargs={"numbers": "{{Generate Dataset.result}}"},
        dependencies=["Generate Dataset"]
    )
    
    # Task 3: Summarize with LLM (depends on Task 2)
    summary_task = workflow.add_text_task(
        name="Generate Summary",
        prompt="Create a summary of this analysis: {{Analyze Numbers.result}}",
        model="llama3",
        dependencies=["Analyze Numbers"]
    )
    
    # Submit and monitor workflow
    workflow_id = await cluster.submit_workflow(workflow)
    
    # Wait for completion
    while True:
        status = await cluster.get_workflow_status(workflow_id)
        print(f"Progress: {status['completed_tasks']}/{status['total_tasks']}")
        
        if status["status"] == "completed":
            print("Results:", status["task_results"])
            break
        elif status["status"] == "failed":
            print("Workflow failed:", status.get("error"))
            break
            
        await asyncio.sleep(1)
    
    await cluster.stop()

asyncio.run(main())
```

### Batch Processing

```python
import asyncio
from gleitzeit_cluster import GleitzeitCluster, Workflow, Task, TaskType, TaskParameters

async def batch_text_analysis():
    cluster = GleitzeitCluster()
    await cluster.start()
    
    # Batch processing workflow
    workflow = Workflow(name="Batch Text Analysis")
    
    texts = [
        "Artificial intelligence is transforming industries",
        "Climate change requires immediate action",  
        "Space exploration opens new frontiers"
    ]
    
    # Create parallel analysis tasks
    for i, text in enumerate(texts):
        workflow.add_python_task(
            name=f"Analyze Text {i+1}",
            function_name="count_words",
            kwargs={"text": text}
        )
        
        workflow.add_python_task(
            name=f"Extract Keywords {i+1}",
            function_name="extract_keywords", 
            kwargs={"text": text, "max_keywords": 3}
        )
    
    # Aggregation task
    workflow.add_text_task(
        name="Generate Report",
        prompt='''Create a report from these analyses:
        Text 1 words: {{Analyze Text 1.result}}, keywords: {{Extract Keywords 1.result}}
        Text 2 words: {{Analyze Text 2.result}}, keywords: {{Extract Keywords 2.result}}
        Text 3 words: {{Analyze Text 3.result}}, keywords: {{Extract Keywords 3.result}}''',
        model="llama3",
        dependencies=[f"Analyze Text {i+1}" for i in range(3)] + [f"Extract Keywords {i+1}" for i in range(3)]
    )
    
    # Execute batch workflow
    workflow_id = await cluster.submit_workflow(workflow)
    
    # Monitor progress
    while True:
        status = await cluster.get_workflow_status(workflow_id)
        if status["status"] in ["completed", "failed"]:
            break
        await asyncio.sleep(1)
    
    if status["status"] == "completed":
        print("Batch Results:")
        for task_name, result in status["task_results"].items():
            print(f"  {task_name}: {result}")
    
    await cluster.stop()

asyncio.run(batch_text_analysis())
```

## Built-in Functions

The system includes 30+ secure functions for common tasks:

```python
# Data processing
analyze_numbers(numbers=[1,2,3,4,5])
fibonacci(n=10)
current_timestamp()

# Text processing  
count_words(text="Hello world")
extract_keywords(text="AI and machine learning", max_keywords=3)
text_stats(text="Sample text")
word_frequency(text="hello world hello")

# Batch processing
async_batch_process(items=["item1", "item2"], delay=0.5)

# And many more...
```

## Workflow YAML Format

```yaml
name: "Document Processing Pipeline"
description: "Extract, analyze, and summarize documents"
error_strategy: "continue_on_error"
max_parallel_tasks: 3

tasks:
  - name: "Extract Text"
    type: "vision"
    image_path: "document.png"  
    prompt: "Extract all text from this document"
    model: "llava"
    
  - name: "Word Count"
    type: "function"
    function_name: "count_words"
    args:
      text: "{{Extract Text.result}}"
    dependencies: ["Extract Text"]
    
  - name: "Generate Summary"
    type: "text"
    prompt: "Summarize this text: {{Extract Text.result}}"
    model: "llama3"
    dependencies: ["Extract Text"]
    
  - name: "Final Report"  
    type: "text"
    prompt: |
      Create a final report:
      - Original text: {{Extract Text.result}}
      - Word count: {{Word Count.result}}
      - Summary: {{Generate Summary.result}}
    model: "llama3"
    dependencies: ["Word Count", "Generate Summary"]
```

## CLI Commands Reference

### Core Commands
- `gleitzeit run` - Execute tasks and workflows
- `gleitzeit dev` - Start development environment  
- `gleitzeit status` - Check cluster status
- `gleitzeit pro` - Professional monitoring interface

### Task Execution
- `--text "prompt"` - Text generation task
- `--vision image.jpg --prompt "..."` - Vision analysis task
- `--function func_name --args key=value` - Function execution
- `--workflow file.yaml` - Workflow execution

### Function Management
- `gleitzeit functions list` - List all functions
- `gleitzeit functions info func_name` - Function details
- `gleitzeit functions categories` - List function categories

### System Management  
- `gleitzeit executor` - Start executor node
- `gleitzeit setup` - Post-installation setup

## Features

✅ **Local-First**: Everything runs on your infrastructure  
✅ **Distributed**: Scale across multiple machines  
✅ **Auto-Start**: Services start automatically when needed  
✅ **Batch Processing**: Efficient parallel processing of multiple items  
✅ **Workflow Orchestration**: Complex multi-step workflows with dependencies  
✅ **30+ Built-in Functions**: Ready-to-use secure functions  
✅ **Real-time Monitoring**: Track progress with professional interface  
✅ **LLM Integration**: Works with Ollama, OpenAI, and more  
✅ **Vision Tasks**: Image analysis and processing  
✅ **No Cloud Dependencies**: Complete privacy and control  

## Requirements

- **Python 3.9+**
- **Redis** (auto-started if needed)
- **Ollama** (for LLM tasks): `curl -fsSL https://ollama.ai/install.sh | sh`

### Recommended Models
```bash
# For text tasks
ollama pull llama3

# For vision tasks  
ollama pull llava

# For code tasks
ollama pull codellama
```

## Development

```bash
# Clone repository
git clone https://github.com/leifmarkthaler/gleitzeit.git
cd gleitzeit

# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest tests/

# Run specific test categories
pytest tests/ -m "not slow"  # Skip slow tests
pytest tests/test_batch_processing.py  # Batch tests only
```

## Status

- **Version**: 0.0.1 (Alpha)
- **License**: MIT  
- **Python**: 3.9+ required
- **Platform**: macOS, Linux (Windows support planned)

## Contributing

This project is in active development. Contributions welcome!

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

**Repository**: https://github.com/leifmarkthaler/gleitzeit