# Gleitzeit Examples Overview

## Core Examples

### 1. **LLM Orchestration Examples** (`examples/llm_orchestration_examples.py`)

**Primary Focus: Multi-endpoint LLM task distribution**

- **Document Analysis Pipeline**: Multiple specialized models analyzing different aspects
- **Translation Pipeline**: Multi-language translation with quality verification
- **Code Review Pipeline**: Automated code analysis with multiple models
- **Content Generation**: Research → Outline → Writing → Editing workflow
- **Model Comparison**: Compare responses from different models

```python
# Multi-endpoint setup
cluster = GleitzeitCluster(
    ollama_endpoints=[
        EndpointConfig("http://gpu-server-1:11434", priority=1, gpu=True),
        EndpointConfig("http://gpu-server-2:11434", priority=2, gpu=True),
        EndpointConfig("http://cpu-server:11434", priority=3, gpu=False),
    ],
    ollama_strategy=LoadBalancingStrategy.LEAST_LOADED
)

# Tasks automatically distributed across endpoints
workflow.add_text_task("Heavy Task", model="llama3:70b")  # → GPU server
workflow.add_text_task("Light Task", model="llama3")     # → Best available
```

### 2. **Python Task Patterns** (`examples/python_task_patterns.py`)

**Decorator-based Python task integration**

- **Data Processing**: CSV loading, statistics, anomaly detection
- **API Integration**: External API calls and aggregation
- **File Processing**: Text analysis and metadata extraction
- **Validation**: LLM output validation and quality scoring
- **Transformation**: Data formatting and merging

```python
@gleitzeit_task(category="data")
def calculate_statistics(data: Dict[str, Any]) -> Dict[str, float]:
    """Calculate statistical metrics"""
    values = data.get("sales", [])
    return {
        "mean": np.mean(values),
        "median": np.median(values),
        "std": np.std(values)
    }

# Use in workflow
workflow.add_external_task(
    name="Stats",
    service_name="Python Tasks",
    external_parameters={"function_name": "calculate_statistics"}
)
```

### 3. **Real-World Workflows** (`examples/real_world_workflows.py`)

**Production-ready scenarios**

- **Customer Support**: Ticket parsing → Analysis → Solution → Response drafting
- **Research Paper Analysis**: Multi-aspect analysis → Comprehensive review → Recommendations
- **Social Media Campaign**: Multi-platform content → Policy checks → A/B testing
- **E-commerce Launch**: Product description → SEO → Ads → Launch checklist

```python
# Customer Support Pipeline
workflow.add_text_task(
    "Analyze Ticket",
    prompt="Categorize and analyze: {{Parse Ticket.result}}",
    model="llama3"
)

workflow.add_text_task(
    "Generate Solution",
    prompt="Solve based on analysis: {{Analyze Ticket.result}}",
    model="mixtral"
)
```

## Key Patterns Demonstrated

### 1. **Multi-Model Orchestration**
```python
# Different models for different tasks
extraction = workflow.add_text_task("Extract", model="llama3")      # Fast
analysis = workflow.add_text_task("Analyze", model="mixtral")       # Reasoning
summary = workflow.add_text_task("Summary", model="llama3:70b")     # Complex
```

### 2. **Parallel Processing**
```python
# Process multiple items concurrently
for language in ["Spanish", "French", "German"]:
    workflow.add_text_task(f"Translate to {language}", model="llama3")
```

### 3. **Python + LLM Integration**
```python
# Python preprocessing → LLM analysis → Python formatting
preprocess = workflow.add_external_task("Preprocess", service_name="Python Tasks")
analyze = workflow.add_text_task("Analyze", dependencies=["Preprocess"])
format = workflow.add_external_task("Format", dependencies=["Analyze"])
```

### 4. **Quality Assurance**
```python
# Generate → Validate → Improve loop
draft = workflow.add_text_task("Draft Response")
validate = workflow.add_external_task("Validate", dependencies=["Draft"])
final = workflow.add_text_task("Final Response", dependencies=["Validate"])
```

### 5. **Load Balancing**
```python
# Heavy tasks → GPU servers, light tasks → CPU servers
heavy = workflow.add_text_task("Complex Analysis", model="llama3:70b")
light = workflow.add_text_task("Simple Extract", model="llama3")
```

## Running Examples

```bash
# Run LLM orchestration examples
python examples/llm_orchestration_examples.py

# Run Python task patterns
python examples/python_task_patterns.py

# Run real-world workflows
python examples/real_world_workflows.py

# Start decorator-based task service
python examples/decorator_example.py
```

## Architecture Benefits Demonstrated

1. **Clean Separation**: LLM tasks vs Python tasks via Socket.IO
2. **Intelligent Routing**: Tasks automatically distributed to best endpoints
3. **Scalability**: Each component scales independently
4. **Flexibility**: Easy to add new models, endpoints, or task types
5. **Reliability**: Built-in error handling and recovery
6. **Simplicity**: Decorator pattern makes Python integration trivial

The examples show how Gleitzeit excels at its core mission: **orchestrating LLM workflows across distributed endpoints** while cleanly integrating Python tasks when needed.