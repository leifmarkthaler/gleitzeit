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

### Multi-Endpoint Ollama (Advanced)

Distribute LLM workloads across multiple Ollama servers for scalability and reliability:

```python
import asyncio
from gleitzeit_cluster import GleitzeitCluster, Workflow
from gleitzeit_cluster.execution.ollama_endpoint_manager import EndpointConfig, LoadBalancingStrategy

async def multi_endpoint_setup():
    # Configure multiple Ollama endpoints
    endpoints = [
        EndpointConfig(
            name="local_cpu",
            url="http://localhost:11434",
            priority=1,  # Lower priority for CPU
            models=["llama3", "mistral"],
            tags={"cpu", "local"}
        ),
        EndpointConfig(
            name="gpu_server",
            url="http://gpu-server:11434",
            priority=5,  # Higher priority for GPU
            max_concurrent=10,
            models=["llama3", "llava", "codellama"],
            tags={"gpu", "vision", "fast"}
        ),
        EndpointConfig(
            name="cloud_backup",
            url="http://cloud.example.com:11434",
            priority=2,
            max_concurrent=20,
            tags={"cloud", "scalable"}
        )
    ]
    
    # Create cluster with multi-endpoint support
    cluster = GleitzeitCluster(
        ollama_endpoints=endpoints,
        ollama_strategy=LoadBalancingStrategy.LEAST_LOADED  # or ROUND_ROBIN, FASTEST_RESPONSE, MODEL_AFFINITY
    )
    await cluster.start()
    
    # Your existing code works unchanged!
    workflow = Workflow(name="Multi-Endpoint Demo")
    
    # Automatically routed to best available endpoint
    text_task = workflow.add_text_task(
        name="Generate Text",
        prompt="Explain distributed computing",
        model="llama3"
    )
    
    # Vision tasks automatically routed to GPU endpoint
    vision_task = workflow.add_vision_task(
        name="Analyze Image",
        prompt="Describe this image",
        model="llava",
        image_path="photo.jpg"
    )
    
    # Submit and monitor
    workflow_id = await cluster.submit_workflow(workflow)
    
    # Get endpoint statistics
    stats = cluster.task_executor.ollama_manager.get_endpoint_stats()
    for endpoint, data in stats.items():
        print(f"{endpoint}: Load={data['stats']['current_load']}, Success={data['stats']['success_rate']:.2%}")
    
    await cluster.stop()

asyncio.run(multi_endpoint_setup())
```

**Multi-Endpoint Features:**
- **Automatic Failover**: Seamlessly retry on healthy endpoints if one fails
- **Load Balancing**: Distribute requests using LEAST_LOADED, ROUND_ROBIN, FASTEST_RESPONSE, or MODEL_AFFINITY strategies
- **Model Routing**: Automatically route to endpoints with required models
- **Health Monitoring**: Continuous health checks with automatic recovery
- **Priority-based Selection**: Prefer high-performance endpoints
- **Tag-based Routing**: Route by capabilities (gpu, vision, fast)

## What Makes This Different?

- **Local-first**: Everything runs on your machine
- **No API keys**: No cloud dependencies or costs
- **Workflow orchestration**: Chain tasks with dependencies and data flow
- **Built-in functions**: 30+ secure functions for data processing
- **Privacy**: Your data never leaves your computer
- **Simple**: Just install and run commands
- **Extensible**: 30+ built-in functions + Python API
- **Multi-Endpoint Support**: Scale across multiple Ollama servers with automatic failover

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