# Getting Started with Gleitzeit

Gleitzeit is an **LLM Workflow Orchestration Platform** that coordinates AI tasks across multiple models and services using a unified Socket.IO architecture. This guide will get you running LLM workflows in minutes.

## 🎯 What Gleitzeit Does

Gleitzeit **orchestrates** (coordinates) rather than executes:
- 🧠 **LLM Task Orchestration** - Route tasks across internal Ollama and external providers (OpenAI, Anthropic)
- 🔗 **Workflow Management** - Complex multi-step AI pipelines with dependencies  
- 🐍 **Python Integration** - Simple decorator-based custom functions via Socket.IO services
- ⚡ **Pure Orchestration** - Gleitzeit coordinates; Socket.IO services execute

## 📋 Prerequisites

### Essential Requirements
```bash
# Python 3.9+
python --version

# Redis for coordination
redis-server

# Ollama for local LLM models
curl -fsSL https://ollama.ai/install.sh | sh
ollama serve

# Install basic models
ollama pull llama3
ollama pull llava  # For vision tasks
```

### Optional (External LLMs)
- **OpenAI API Key** - For GPT models
- **Anthropic API Key** - For Claude models

## 🚀 Installation

```bash
# Install from source
git clone https://github.com/leifmarkthaler/gleitzeit
cd gleitzeit
pip install -e .
```

## ⚡ Quick Start (5 Minutes)

### 1. Basic LLM Orchestration

```python
import asyncio
from gleitzeit_cluster import GleitzeitCluster

async def quick_start():
    # Create orchestrator (unified architecture by default)
    cluster = GleitzeitCluster()
    await cluster.start()
    
    # Create workflow
    workflow = cluster.create_workflow("My First AI Workflow")
    
    # Add LLM task (routes to internal Ollama automatically)
    analysis = workflow.add_text_task(
        name="AI Analysis",
        prompt="Explain the benefits of AI orchestration in 3 points",
        model="llama3"  # Routes to internal Ollama service
    )
    
    # Execute workflow  
    workflow_id = await cluster.submit_workflow(workflow)
    result = await cluster.wait_for_workflow(workflow_id)
    
    print("🧠 AI Analysis Result:")
    print(result.results["AI Analysis"])
    
    await cluster.stop()

# Run it
asyncio.run(quick_start())
```

### 2. Multi-Provider LLM Workflow

```python
async def multi_provider_example():
    cluster = GleitzeitCluster()
    await cluster.start()
    
    workflow = cluster.create_workflow("Multi-Provider AI Pipeline")
    
    # Task 1: Local Ollama (fast, private)
    outline = workflow.add_text_task(
        name="Create Outline",
        prompt="Create an outline for a blog post about AI orchestration",
        model="llama3"  # → Internal Ollama service
    )
    
    # Task 2: External OpenAI (powerful)
    content = workflow.add_text_task(
        name="Write Content",
        prompt="Write a detailed blog post based on: {{Create Outline.result}}",
        model="gpt-4",  # → OpenAI service (automatic routing)
        dependencies=["Create Outline"]
    )
    
    # Task 3: External Anthropic (different perspective)
    review = workflow.add_text_task(
        name="Review Content",
        prompt="Review and improve this content: {{Write Content.result}}",
        model="claude-3",  # → Anthropic service (automatic routing)
        dependencies=["Write Content"]
    )
    
    # Execute pipeline
    workflow_id = await cluster.submit_workflow(workflow)
    result = await cluster.wait_for_workflow(workflow_id)
    
    print("📝 Final Content:")
    print(result.results["Review Content"])
    
    await cluster.stop()

asyncio.run(multi_provider_example())
```

### 3. Python + LLM Integration

```python
from gleitzeit_cluster.decorators import gleitzeit_task

# Define custom Python tasks with decorators
@gleitzeit_task(category="data")
def analyze_sales(data: dict) -> dict:
    total = sum(data.values())
    growth = ((data["Q4"] - data["Q1"]) / data["Q1"]) * 100
    return {
        "total_revenue": total,
        "growth_rate": growth,
        "trend": "positive" if growth > 0 else "negative"
    }

async def mixed_workflow():
    cluster = GleitzeitCluster()
    await cluster.start()
    
    workflow = cluster.create_workflow("Business Intelligence Pipeline")
    
    # Python task (routes to Python Executor service)
    analysis = workflow.add_python_task(
        name="Analyze Data",
        function_name="analyze_sales",
        args=[{"Q1": 150000, "Q2": 175000, "Q3": 190000, "Q4": 210000}]
    )
    
    # LLM task using Python results
    insights = workflow.add_text_task(
        name="Generate Insights",
        prompt="Based on this business analysis, provide strategic recommendations: {{Analyze Data.result}}",
        model="gpt-4",
        dependencies=["Analyze Data"]
    )
    
    # Execute mixed workflow
    workflow_id = await cluster.submit_workflow(workflow)
    result = await cluster.wait_for_workflow(workflow_id)
    
    print("📊 Business Insights:")
    print(result.results["Generate Insights"])
    
    await cluster.stop()

asyncio.run(mixed_workflow())
```

## 🏗️ Architecture Overview

Gleitzeit uses a **pure orchestration** approach with Socket.IO services:

```
┌─────────────────────┐    ┌─────────────────────────────┐
│   Gleitzeit         │    │     Socket.IO Services      │
│   Orchestrator      │───▶│                             │
│                     │    │  ┌─────────────────────────┐ │
│ • Creates workflows │    │  │  Internal LLM Service   │ │
│ • Manages deps      │    │  │  (Ollama Integration)   │ │
│ • Routes tasks      │    │  └─────────────────────────┘ │
│ • Monitors progress │    │                             │
└─────────────────────┘    │  ┌─────────────────────────┐ │
                           │  │ External LLM Providers  │ │
                           │  │ (OpenAI, Anthropic)     │ │
                           │  └─────────────────────────┘ │
                           │                             │
                           │  ┌─────────────────────────┐ │
                           │  │ Python Executor Service │ │
                           │  │  (@gleitzeit_task)      │ │
                           │  └─────────────────────────┘ │
                           └─────────────────────────────┘
```

**Key Benefits:**
- ⚡ **Infinite Scalability** - Services scale independently
- 🔄 **Pure Orchestration** - Focus on coordination, not execution
- 🎯 **Provider Flexibility** - Mix local and external LLMs seamlessly
- 🐍 **Simple Integration** - Decorator-based Python tasks

## 🔧 Configuration

### Simple Configuration (11 Parameters)

```python
# Works out-of-the-box with defaults
cluster = GleitzeitCluster()

# Custom configuration
cluster = GleitzeitCluster(
    redis_url="redis://localhost:6379",
    socketio_url="http://localhost:8000",
    ollama_url="http://localhost:11434",
    enable_redis=True,
    enable_socketio=True,
    socketio_host="0.0.0.0",
    socketio_port=8000,
    auto_start_internal_llm_service=True,
    auto_start_python_executor=True,
    python_executor_workers=4,
    llm_service_workers=20
)
```

### External Provider Configuration

```python
import os

# Set API keys for external providers
os.environ["OPENAI_API_KEY"] = "your-openai-key"
os.environ["ANTHROPIC_API_KEY"] = "your-anthropic-key"

# Use external models automatically
workflow.add_text_task("OpenAI Task", "Analyze this", model="gpt-4")
workflow.add_text_task("Claude Task", "Review this", model="claude-3")
```

## 🚀 CLI Usage

### Development Environment

```bash
# Start development environment with all services
gleitzeit dev

# Custom development setup  
gleitzeit dev --socketio-port 9000 --no-auto-llm
```

### Direct Task Execution

```bash
# Single LLM task
gleitzeit run --text "Explain quantum computing" --model llama3

# Vision analysis
gleitzeit run --vision photo.jpg --prompt "Describe this image" --model llava

# Custom Python function (if registered)
gleitzeit run --function my_function --args data="test"
```

### System Management

```bash
# Check system status
gleitzeit status

# Monitor in real-time
gleitzeit monitor

# View error catalog
gleitzeit errors list
```

## 📊 Service Management

### Start Services Manually

```bash
# Start Socket.IO services individually
python services/internal_llm_service.py      # Ollama integration
python services/external_llm_providers.py    # OpenAI, Anthropic  
python services/python_executor_service.py   # Python task execution
```

### Service Configuration

```python
# Internal LLM Service (Ollama)
# - Automatically handles llama3, llava, mistral, etc.
# - Routes based on model name
# - Provides vision capabilities

# External LLM Providers
# - OpenAI: gpt-3.5-turbo, gpt-4, gpt-4-turbo
# - Anthropic: claude-3-haiku, claude-3-sonnet, claude-3-opus
# - Automatic routing based on model name

# Python Executor Service  
# - Executes @gleitzeit_task decorated functions
# - Handles both sync and async functions
# - Provides sandboxed execution environment
```

## 🎯 Task Types and Routing

### LLM Tasks (Automatic Routing)

```python
# Internal Ollama models
workflow.add_text_task("Local", prompt="...", model="llama3")      # → Internal LLM Service
workflow.add_text_task("Vision", prompt="...", model="llava")      # → Internal LLM Service

# External provider models  
workflow.add_text_task("OpenAI", prompt="...", model="gpt-4")      # → OpenAI Service
workflow.add_text_task("Claude", prompt="...", model="claude-3")   # → Anthropic Service

# Explicit provider control
workflow.add_text_task("Custom", prompt="...", model="llama3", provider="internal")
```

### Vision Tasks

```python
# Vision analysis (routes to internal Ollama with vision models)
workflow.add_vision_task(
    name="Analyze Image",
    prompt="What do you see in this image?",
    image_path="/path/to/image.jpg", 
    model="llava"
)
```

### Python Tasks (Decorator Pattern)

```python
@gleitzeit_task(category="analysis")
def custom_analysis(data: list) -> dict:
    return {"processed": len(data), "summary": "complete"}

# Routes to Python Executor service
workflow.add_python_task(
    name="Custom Processing",
    function_name="custom_analysis",
    args=[[1, 2, 3, 4, 5]]
)
```

## 🔄 Common Workflow Patterns

### Sequential Processing
```python
task_a = workflow.add_text_task("Step 1", prompt="...", model="llama3")
task_b = workflow.add_text_task("Step 2", prompt="Process: {{Step 1.result}}", 
                                model="gpt-4", dependencies=["Step 1"])
```

### Parallel + Aggregation
```python
# Multiple parallel analyses
parallel_tasks = []
for i, topic in enumerate(["AI", "ML", "Deep Learning"]):
    task = workflow.add_text_task(f"Analyze {topic}", f"Explain {topic}", "llama3")
    parallel_tasks.append(f"Analyze {topic}")

# Combine results
workflow.add_text_task("Summary", 
                      prompt="Combine: " + " ".join([f"{{{task}.result}}" for task in parallel_tasks]),
                      model="gpt-4", dependencies=parallel_tasks)
```

### Mixed Python + LLM
```python
# Python → LLM → Python pipeline
data = workflow.add_python_task("Clean", function_name="clean_data", args=[raw_data])
analysis = workflow.add_text_task("Analyze", prompt="{{Clean.result}}", model="gpt-4", dependencies=["Clean"])
report = workflow.add_python_task("Format", function_name="create_report", 
                                 args=["{{Analyze.result}}"], dependencies=["Analyze"])
```

## 📈 Monitoring

### Real-Time Monitoring

```python
# Event-driven progress tracking
async def on_task_completed(event):
    print(f"✅ {event['task_name']}: {event['result']}")

async def on_workflow_completed(event):  
    print(f"🎉 Workflow {event['workflow_id']} completed!")

cluster.on('task_completed', on_task_completed)
cluster.on('workflow_completed', on_workflow_completed)
```

### System Statistics

```bash
# CLI monitoring
gleitzeit monitor        # Live dashboard
gleitzeit status         # Quick status
gleitzeit events --json  # Event stream
```

## 🔍 Troubleshooting

### Common Issues

**"No suitable service found"**
- Check that required services are running
- Verify model availability: `ollama list`
- Check API keys for external providers

**"Connection refused"**
- Ensure Redis is running: `redis-server`
- Check Ollama is running: `ollama serve`
- Verify Socket.IO services are started

**"Model not found"**
- Install missing models: `ollama pull llama3`
- Check model name spelling
- Verify model exists on Ollama server

### Debug Commands

```python
# Check service health
cluster = GleitzeitCluster()
await cluster.start()

# Test internal LLM service
result = await cluster.test_service("Internal LLM Service", "llama3")
print(f"Internal LLM test: {result}")

# Test Python executor
result = await cluster.test_service("Python Executor", "test_function")
print(f"Python executor test: {result}")
```

## 📚 Next Steps

### Essential Examples
```bash
# Start with basics
python examples/simple_example.py

# Learn decorator patterns  
python examples/decorator_example.py

# Explore LLM orchestration
python examples/llm_orchestration_examples.py

# Try vision tasks
python examples/vision_demo.py
```

### Advanced Topics
- **Multiple Ollama Hosts**: See `docs/multi-ollama-setup.md`
- **Production Deployment**: See deployment examples
- **Custom Services**: Build your own Socket.IO services
- **Performance Tuning**: Optimize for your workload

### Resources
- **Repository**: https://github.com/leifmarkthaler/gleitzeit
- **Issues**: https://github.com/leifmarkthaler/gleitzeit/issues  
- **Examples**: Check the `examples/` directory
- **API Reference**: See source code docstrings

---

**Gleitzeit** - *German for "flextime"* - Flexible orchestration for your AI workflows 🚀

**Status**: Development prototype suitable for experimentation and testing