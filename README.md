# Gleitzeit

**LLM Workflow Orchestration Platform**

A pure orchestration system for LLM tasks, workflows, and AI endpoints. Built on unified Socket.IO architecture for maximum scalability and simplicity.

## 🎯 Core Purpose

Gleitzeit orchestrates **LLM tasks**, **workflows**, and **AI endpoints** - your central hub for coordinating AI workloads across multiple models and services.

**Key Focus Areas:**
- 🧠 **LLM Task Orchestration** - Text generation, vision analysis, multi-model workflows
- 🔗 **Workflow Management** - Complex multi-step AI pipelines with dependencies
- 🏗️ **AI Endpoint Coordination** - Route tasks across internal Ollama and external providers
- 🐍 **Python Task Integration** - Simple decorator-based custom functions

## Quick Start

### Installation

```bash
# Install from source
pip install -e .

# Requirements
ollama serve                    # Start Ollama for local LLMs
redis-server                   # Start Redis for coordination
```

### Instant LLM Orchestration

```python
import asyncio
from gleitzeit_cluster import GleitzeitCluster
from gleitzeit_cluster.decorators import gleitzeit_task

# Define custom Python tasks with decorators
@gleitzeit_task(category="data")
def analyze_metrics(data: dict) -> dict:
    return {
        "total": sum(data.values()),
        "average": sum(data.values()) / len(data),
        "trend": "positive" if list(data.values())[-1] > list(data.values())[0] else "negative"
    }

async def main():
    # Create orchestrator (unified architecture by default)
    cluster = GleitzeitCluster()
    await cluster.start()
    
    # Create workflow mixing LLM and Python tasks
    workflow = cluster.create_workflow("Business Intelligence Pipeline")
    
    # Step 1: Analyze data with Python
    analysis = workflow.add_python_task(
        name="Analyze Sales",
        function_name="analyze_metrics", 
        args=[{"Q1": 150000, "Q2": 175000, "Q3": 190000, "Q4": 210000}]
    )
    
    # Step 2: Generate insights with local LLM
    insights = workflow.add_text_task(
        name="Generate Insights",
        prompt="Based on this sales analysis, provide strategic recommendations: {{Analyze Sales.result}}",
        model="llama3",  # Routes to internal Ollama
        dependencies=["Analyze Sales"]
    )
    
    # Step 3: Format report with external LLM
    report = workflow.add_text_task(
        name="Format Report", 
        prompt="Format this analysis into an executive summary: {{Generate Insights.result}}",
        model="gpt-4",  # Routes to OpenAI service
        dependencies=["Generate Insights"]
    )
    
    # Execute workflow
    workflow_id = await cluster.submit_workflow(workflow)
    result = await cluster.wait_for_workflow(workflow_id)
    
    print("📊 Final Report:")
    print(result.results["Format Report"])
    
    await cluster.stop()

asyncio.run(main())
```

## 🏗️ Unified Socket.IO Architecture

Gleitzeit uses a **pure orchestration** approach - it coordinates tasks but never executes them directly. Everything routes through Socket.IO services:

```
┌─────────────────┐    ┌─────────────────────────────┐
│   Gleitzeit     │    │      Socket.IO Services     │
│  Orchestrator   │───▶│                             │
│                 │    │  ┌─────────────────────────┐ │
│ • Workflows     │    │  │  Internal LLM Service   │ │
│ • Dependencies  │    │  │  (Ollama Integration)   │ │
│ • Coordination  │    │  └─────────────────────────┘ │
│ • Monitoring    │    │                             │
└─────────────────┘    │  ┌─────────────────────────┐ │
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

**Benefits:**
- ⚡ **Infinite Scalability** - Services scale independently
- 🔧 **Simple Integration** - Same API, better architecture  
- 🔄 **Pure Orchestration** - Focus on coordination, not execution
- 🎯 **Provider Flexibility** - Mix internal and external LLMs seamlessly

## 🧠 LLM Provider Integration

### Automatic Provider Detection

```python
# Routes automatically based on model name
workflow.add_text_task("Local", prompt="...", model="llama3")      # → Internal Ollama
workflow.add_text_task("OpenAI", prompt="...", model="gpt-4")      # → OpenAI Service  
workflow.add_text_task("Claude", prompt="...", model="claude-3")   # → Anthropic Service

# Explicit provider control
workflow.add_text_task("Custom", prompt="...", model="llama3", provider="internal")
workflow.add_text_task("Custom", prompt="...", model="gpt-4", provider="openai")
```

### Vision Tasks

```python
# Vision analysis with local models
workflow.add_vision_task(
    name="Analyze Image",
    prompt="What do you see in this image?",
    image_path="/path/to/image.jpg",
    model="llava"  # Routes to internal Ollama with vision support
)

# Mixed text + vision workflow
workflow.add_text_task(
    name="Summarize Analysis",
    prompt="Create a summary based on this image analysis: {{Analyze Image.result}}",
    model="gpt-4",
    dependencies=["Analyze Image"]
)
```

## 🐍 Python Task Integration

### Simple Decorator Pattern

```python
from gleitzeit_cluster.decorators import gleitzeit_task, start_task_service

# Define tasks with decorators
@gleitzeit_task(category="data")
def process_data(raw_data: list) -> dict:
    return {"processed": len(raw_data), "summary": "complete"}

@gleitzeit_task(category="analysis")
async def complex_analysis(data: dict) -> dict:
    # Your complex logic here
    await asyncio.sleep(0.1)  # Simulate processing
    return {"analysis": "complete", "insights": ["trend1", "trend2"]}

# Start task service (registers decorated functions)
async def main():
    # Start Python task service
    service_task = asyncio.create_task(start_task_service("My Tasks"))
    
    # Create workflow
    cluster = GleitzeitCluster()
    await cluster.start()
    
    workflow = cluster.create_workflow("Data Pipeline")
    
    # Add Python tasks (route to service)
    workflow.add_python_task("Process", function_name="process_data", args=[[1,2,3,4,5]])
    workflow.add_python_task("Analyze", function_name="complex_analysis", args=["{{Process.result}}"], dependencies=["Process"])
    
    # Execute
    workflow_id = await cluster.submit_workflow(workflow)
    result = await cluster.wait_for_workflow(workflow_id)
    
    await cluster.stop()
```

## 🚀 CLI Usage

### Quick Commands

```bash
# Start development environment
gleitzeit dev

# Run single LLM task
gleitzeit run --text "Explain quantum computing" --model llama3

# Run vision analysis
gleitzeit run --vision photo.jpg --prompt "Describe this image" --model llava

# Run custom Python function
gleitzeit run --function my_function --args data="test"

# Check system status
gleitzeit status
```

### Service Management

```bash
# Start individual services
python services/internal_llm_service.py      # Ollama integration
python services/external_llm_providers.py    # OpenAI, Anthropic
python services/python_executor_service.py   # Python task execution

# Monitor everything
gleitzeit monitor
```

## 📊 Real-World Examples

### Multi-Model AI Pipeline

```python
async def ai_content_pipeline():
    cluster = GleitzeitCluster()
    await cluster.start()
    
    workflow = cluster.create_workflow("Content Creation Pipeline")
    
    # Step 1: Generate outline (fast local model)
    outline = workflow.add_text_task(
        "Create Outline",
        prompt="Create an outline for a blog post about: AI in healthcare",
        model="llama3"  # Local Ollama
    )
    
    # Step 2: Write content (powerful external model)
    content = workflow.add_text_task(
        "Write Content", 
        prompt="Write a detailed blog post based on this outline: {{Create Outline.result}}",
        model="gpt-4",  # External OpenAI
        dependencies=["Create Outline"]
    )
    
    # Step 3: Review and edit (different external model)
    review = workflow.add_text_task(
        "Review Content",
        prompt="Review and improve this blog post: {{Write Content.result}}",
        model="claude-3",  # External Anthropic
        dependencies=["Write Content"]
    )
    
    # Execute and get results
    workflow_id = await cluster.submit_workflow(workflow)
    result = await cluster.wait_for_workflow(workflow_id)
    
    print("📝 Final Blog Post:")
    print(result.results["Review Content"])
```

### Business Intelligence Workflow

```python
@gleitzeit_task(category="analytics")
def calculate_kpis(sales_data: dict) -> dict:
    return {
        "revenue": sum(sales_data.values()),
        "growth": ((sales_data["Q4"] - sales_data["Q1"]) / sales_data["Q1"]) * 100,
        "best_quarter": max(sales_data, key=sales_data.get)
    }

async def business_intelligence():
    cluster = GleitzeitCluster()
    await cluster.start()
    
    workflow = cluster.create_workflow("Business Intelligence")
    
    # Calculate KPIs with Python
    kpis = workflow.add_python_task(
        "Calculate KPIs",
        function_name="calculate_kpis",
        args=[{"Q1": 150000, "Q2": 175000, "Q3": 190000, "Q4": 210000}]
    )
    
    # Generate insights with LLM
    insights = workflow.add_text_task(
        "Generate Insights",
        prompt="Analyze these business KPIs and provide strategic recommendations: {{Calculate KPIs.result}}",
        model="gpt-4",
        dependencies=["Calculate KPIs"]
    )
    
    # Create executive summary
    summary = workflow.add_text_task(
        "Executive Summary",
        prompt="Create a concise executive summary from these insights: {{Generate Insights.result}}",
        model="claude-3",
        dependencies=["Generate Insights"]
    )
    
    # Execute pipeline
    workflow_id = await cluster.submit_workflow(workflow)
    result = await cluster.wait_for_workflow(workflow_id)
    
    return result.results["Executive Summary"]
```

## 🔧 Configuration

### Simple Defaults

```python
# Works out of the box
cluster = GleitzeitCluster()

# Custom configuration (11 simple parameters)
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

### CLI Options

```bash
# Development mode with unified architecture
gleitzeit dev --unified --auto-llm --external-python

# Disable specific services
gleitzeit dev --no-auto-llm --no-external-python

# Custom ports and URLs  
gleitzeit dev --socketio-port 9000 --ollama-url http://gpu-server:11434
```

## 🔍 Monitoring & Debugging

### Real-Time Monitoring

```bash
# Live dashboard
gleitzeit monitor

# Watch specific workflow
gleitzeit watch workflow wf_abc123

# Stream events
gleitzeit events --json

# Check system health
gleitzeit status
```

### Error Handling

```bash
# Browse error catalog
gleitzeit errors list

# Search for specific issues  
gleitzeit errors search "connection"
gleitzeit errors search "model"

# Get detailed error info
gleitzeit errors show GZ1025
```

## 🌟 Key Features

- **🏛️ Pure Orchestrator** - Coordinates tasks, never executes directly
- **🔄 Unified Architecture** - Everything routes through Socket.IO services
- **🎯 LLM-Focused** - Optimized for AI workflow orchestration
- **⚡ Multi-Provider** - Mix local Ollama with OpenAI, Anthropic seamlessly
- **🐍 Simple Python Integration** - Decorator-based custom functions
- **📊 Real-Time Monitoring** - Socket.IO events, no polling
- **🔧 Clean API** - Simplified configuration, intelligent defaults
- **🚀 Production Ready** - Service-based scaling, robust error handling

## 📁 Project Structure

```
gleitzeit/
├── gleitzeit_cluster/           # Core orchestration library
│   ├── core/                    # Cluster, workflow, task management
│   ├── communication/           # Socket.IO client/server
│   ├── auth/                    # Authentication system
│   └── cli*.py                  # Command-line interfaces
├── services/                    # External Socket.IO services  
│   ├── internal_llm_service.py  # Ollama integration
│   ├── external_llm_providers.py # OpenAI, Anthropic
│   └── python_executor_service.py # Python task execution
└── examples/                    # Usage examples
```

## 🔗 Architecture Details

### Service Routing

| Task Type | Route | Service |
|-----------|-------|---------|
| `add_text_task()` with `model="llama3"` | → | Internal LLM Service |
| `add_text_task()` with `model="gpt-4"` | → | OpenAI Service |  
| `add_text_task()` with `model="claude-3"` | → | Anthropic Service |
| `add_vision_task()` | → | Internal LLM Service (Ollama) |
| `add_python_task()` | → | Python Executor Service |

### Task Types (Unified)

All tasks use external task types routed through Socket.IO:

- `EXTERNAL_CUSTOM` - LLM tasks (text, vision)
- `EXTERNAL_PROCESSING` - Python function execution
- `EXTERNAL_API` - HTTP requests and API calls
- `EXTERNAL_ML` - Machine learning tasks
- `EXTERNAL_DATABASE` - Database operations
- `EXTERNAL_WEBHOOK` - Webhook integrations

## 🛠️ Development

### Start Development Environment

```bash
# Full development environment with all services
gleitzeit dev

# Development with custom settings
gleitzeit dev --socketio-port 9000 --no-auto-llm
```

### Testing

```bash
# Test core functionality
python test_basic_functionality.py

# Test unified architecture
python test_unified_complete.py

# Test decorator system
python test_decorator_simple.py

# Test complete system
python test_complete_system.py
```

## 📚 Examples

- `examples/llm_orchestration_examples.py` - Complete LLM workflow examples
- `examples/decorator_example.py` - Python task decorator patterns
- `examples/batch_demo.py` - Batch processing workflows
- `examples/vision_demo.py` - Image analysis workflows

## 🔄 Workflow Patterns

### Sequential Processing

```python
# Task A → Task B → Task C
task_a = workflow.add_text_task("Step 1", prompt="...", model="llama3")
task_b = workflow.add_text_task("Step 2", prompt="Process: {{Step 1.result}}", model="gpt-4", dependencies=["Step 1"])
task_c = workflow.add_text_task("Step 3", prompt="Finalize: {{Step 2.result}}", model="claude-3", dependencies=["Step 2"])
```

### Parallel + Merge

```python
# Multiple parallel tasks → Single aggregation task
parallel_tasks = []
for i, prompt in enumerate(prompts):
    task = workflow.add_text_task(f"Analysis {i}", prompt=prompt, model="llama3")
    parallel_tasks.append(f"Analysis {i}")

# Aggregate results
workflow.add_text_task(
    "Final Report",
    prompt="Combine these analyses: " + " ".join([f"{{{task}.result}}" for task in parallel_tasks]),
    model="gpt-4",
    dependencies=parallel_tasks
)
```

### Mixed Python + LLM

```python
# Python → LLM → Python pattern
data_task = workflow.add_python_task("Process Data", function_name="clean_data", args=[raw_data])
llm_task = workflow.add_text_task("Analyze", prompt="Insights: {{Process Data.result}}", model="gpt-4", dependencies=["Process Data"])
report_task = workflow.add_python_task("Format", function_name="create_report", args=["{{Analyze.result}}"], dependencies=["Analyze"])
```

## 🎯 Use Cases

- **📊 Business Intelligence** - Analyze data with Python, generate insights with LLMs
- **📝 Content Creation** - Multi-model content pipelines (local + external LLMs)
- **🔍 Document Analysis** - Process documents with vision + text models
- **🤖 AI Agent Workflows** - Complex multi-step AI agent behaviors
- **📈 Research Pipelines** - Coordinate research workflows across multiple AI models
- **🎨 Creative Workflows** - Content generation, editing, and refinement

## 🔧 Requirements

- **Python 3.9+**
- **Redis** - `redis-server` (for coordination)
- **Ollama** - `ollama serve` (for local LLMs)
- **Models** - `ollama pull llama3 llava` (for text and vision)

### Optional External Providers

- **OpenAI API Key** - For GPT models
- **Anthropic API Key** - For Claude models

## 📈 Status

- **Version**: 0.0.1 (Alpha)
- **Architecture**: Production-ready unified Socket.IO design ✅
- **Core Features**: Complete LLM orchestration ✅  
- **API**: Stable and streamlined ✅
- **Testing**: Comprehensive test suite ✅

**Ready for**: LLM workflow orchestration, AI endpoint management, complex multi-model pipelines

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Test your changes (`python test_basic_functionality.py`)
4. Commit changes (`git commit -m 'Add amazing feature'`)
5. Push to branch (`git push origin feature/amazing-feature`)
6. Open Pull Request

**Repository**: https://github.com/leifmarkthaler/gleitzeit

---

**Gleitzeit** - *German for "flextime"* - Flexible orchestration for your AI workflows 🚀