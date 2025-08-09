# Gleitzeit Examples

Essential examples demonstrating the unified Socket.IO architecture and LLM orchestration capabilities.

## 🎯 Core Examples

### **`simple_example.py`**
Basic LLM orchestration and Python task integration
- Single LLM task execution
- Basic Python function calls
- Introduction to the API

### **`decorator_example.py`**
Python task decorator pattern with Socket.IO routing
- `@gleitzeit_task` decorator usage
- Mixed Python + LLM workflows
- Service-based task execution

### **`llm_orchestration_examples.py`**
Complete LLM workflow orchestration patterns
- Multi-provider routing (internal Ollama, OpenAI, Anthropic)
- Complex dependencies and data flow
- Real-world AI pipeline examples

### **`vision_demo.py`**
Image analysis and vision tasks
- Vision task creation with local models
- Mixed text + vision workflows
- Image processing pipelines

### **`batch_demo.py`**
Batch processing workflows
- Parallel task execution
- Aggregation patterns
- Scalable data processing

### **`real_world_workflows.py`**
Production-style workflow examples
- Business intelligence pipelines
- Content creation workflows
- Multi-step AI agent behaviors

### **`auth_demo.py`**
Authentication and security examples
- API key authentication
- User management
- Secure workflow execution

## 🚀 Quick Start

```bash
# 1. Start with basics
python examples/simple_example.py

# 2. Learn decorator pattern
python examples/decorator_example.py

# 3. Explore LLM orchestration
python examples/llm_orchestration_examples.py

# 4. Try vision tasks (requires ollama pull llava)
python examples/vision_demo.py

# 5. Test batch processing
python examples/batch_demo.py
```

## 📋 Requirements

### Essential
- **Python 3.9+**
- **Redis**: `redis-server`
- **Ollama**: `ollama serve`
- **Models**: `ollama pull llama3`

### For Vision Examples
- **Vision Model**: `ollama pull llava`
- **Test Images**: Any JPG/PNG files

### For External LLM Examples
- **OpenAI API Key** (optional)
- **Anthropic API Key** (optional)

## 🏗️ Architecture Demonstrated

All examples showcase the **unified Socket.IO architecture**:

```
Gleitzeit Orchestrator → Socket.IO Services → AI Models/Python Functions
```

**Key Patterns:**
- 🧠 **LLM Tasks** route to appropriate services (internal/external)
- 🐍 **Python Tasks** use decorator pattern + Socket.IO execution
- 🔗 **Workflows** coordinate multiple tasks with dependencies
- 📊 **Monitoring** via real-time Socket.IO events

## 🎯 Example Focus Areas

| Example | Focus | Architecture Demo |
|---------|-------|-------------------|
| `simple_example.py` | Basic API | Single task execution |
| `decorator_example.py` | Python Integration | Decorator + service routing |
| `llm_orchestration_examples.py` | Multi-Provider LLMs | Provider flexibility |
| `vision_demo.py` | Vision Tasks | Ollama vision integration |
| `batch_demo.py` | Parallel Processing | Scalable batch workflows |
| `real_world_workflows.py` | Production Patterns | Complex business workflows |
| `auth_demo.py` | Security | Authentication patterns |

## 🔄 Common Patterns

### Sequential Processing
```python
task_a = workflow.add_text_task("Step 1", prompt="...", model="llama3")
task_b = workflow.add_text_task("Step 2", prompt="{{Step 1.result}}", dependencies=["Step 1"])
```

### Parallel + Aggregation
```python
# Multiple parallel tasks
tasks = []
for i, data in enumerate(datasets):
    task = workflow.add_python_task(f"Process {i}", function_name="analyze", args=[data])
    tasks.append(f"Process {i}")

# Aggregate results
workflow.add_text_task("Summary", prompt="Combine: " + "{{" + ".result}} {{".join(tasks) + ".result}}", dependencies=tasks)
```

### Mixed Python + LLM
```python
# Python preprocessing → LLM analysis → Python formatting
preprocess = workflow.add_python_task("Clean", function_name="clean_data", args=[raw_data])
analyze = workflow.add_text_task("Analyze", prompt="{{Clean.result}}", model="gpt-4", dependencies=["Clean"])
format = workflow.add_python_task("Format", function_name="create_report", args=["{{Analyze.result}}"], dependencies=["Analyze"])
```

---

**Status**: All examples work with the current unified Socket.IO architecture ✅