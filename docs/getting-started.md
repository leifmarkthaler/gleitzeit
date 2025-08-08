# Getting Started with Gleitzeit Cluster

## 🚀 Quick Start

### 1. Installation

```bash
pip install gleitzeit-cluster
```

### 2. Start Infrastructure

Start Redis and Socket.IO servers:

```bash
docker-compose up -d redis socketio-server
```

### 3. Basic Usage

```python
import asyncio
from gleitzeit_cluster import GleitzeitCluster

async def main():
    # Initialize cluster
    cluster = GleitzeitCluster()
    await cluster.start()
    
    try:
        # Quick text analysis
        result = await cluster.analyze_text("Explain quantum computing")
        print(f"Result: {result}")
        
        # Create complex workflow
        workflow = cluster.create_workflow("my-analysis")
        workflow.add_text_task("summarize", "Summarize this document...")
        workflow.add_text_task("keywords", "Extract keywords...")
        
        # Execute workflow
        result = await cluster.execute_workflow(workflow)
        print(f"Workflow completed: {result.status}")
        
    finally:
        await cluster.stop()

asyncio.run(main())
```

## 📖 Core Concepts

### Workflows

Workflows are collections of tasks with dependencies:

```python
workflow = cluster.create_workflow("document-analysis")

# Tasks can depend on other tasks
task1 = workflow.add_text_task("summarize", "Summarize document")
task2 = workflow.add_text_task("keywords", "Extract keywords", 
                               dependencies=[task1.id])
```

### Task Types

- **Text Tasks**: LLM-based text processing
- **Vision Tasks**: Image analysis with vision models  
- **Python Tasks**: Pure Python computation
- **HTTP Tasks**: API calls and web requests
- **File Tasks**: File operations

### Executor Nodes

Register nodes to handle different task types:

```python
from gleitzeit_cluster import ExecutorNode, NodeCapabilities, TaskType

node = ExecutorNode(
    name="gpu-worker-1",
    capabilities=NodeCapabilities(
        supported_task_types={TaskType.TEXT_PROMPT, TaskType.VISION_TASK},
        available_models=["llama3", "llava"],
        has_gpu=True
    )
)

await cluster.register_node(node)
```

## 🔧 Configuration

### Environment Variables

```bash
export REDIS_URL="redis://localhost:6379"
export SOCKETIO_URL="http://localhost:8000"
export OLLAMA_URL="http://localhost:11434"
```

### Error Handling

Configure how workflows handle failures:

```python
from gleitzeit_cluster.core.workflow import WorkflowErrorStrategy

workflow.error_strategy = WorkflowErrorStrategy.CONTINUE_ON_ERROR
workflow.max_parallel_tasks = 5
```

## 🎯 Examples

See the `examples/` directory for:

- **minimal_example.py** - Basic cluster usage
- **workflow_examples.py** - Complex workflow patterns
- **distributed_setup.py** - Multi-node deployment

## 🚀 Next Steps

1. **Set up Ollama**: Install and configure Ollama with your preferred models
2. **Deploy Executors**: Start executor nodes on different machines
3. **Build Dashboards**: Create monitoring interfaces with Socket.IO
4. **Scale Up**: Add more Redis instances and load balancing