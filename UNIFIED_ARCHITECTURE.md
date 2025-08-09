# Gleitzeit Unified Socket.IO Architecture

## Vision: Pure Orchestrator + Service Ecosystem

Gleitzeit is now a **pure orchestrator** that coordinates tasks across a unified ecosystem of Socket.IO services. No execution happens within the orchestrator itself.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                 Gleitzeit Pure Orchestrator                 │
│                                                              │
│  📋 Workflow Management    🔄 Task Scheduling               │
│  🗃️ Redis State           📊 Unified Monitoring             │
│  🔗 Socket.IO Hub         ⚡ Dependency Resolution          │
└─────────────────────┬───────────────────────────────────────┘
                      │
                   Socket.IO
                      │
    ┌─────────────────┼─────────────────────────────────────────┐
    │                 │                                         │
    ▼                 ▼                                         ▼
┌─────────────┐  ┌─────────────┐                      ┌─────────────┐
│ Internal    │  │ External    │                      │ Python      │
│ LLM Service │  │ LLM Services│                      │ Services    │
│             │  │             │                      │             │
│ • Ollama    │  │ • OpenAI    │          ...         │ • @decorated│
│ • Load Bal. │  │ • Anthropic │                      │ • Custom    │
│ • GPU Mgmt  │  │ • Gemini    │                      │ • Legacy    │
└─────────────┘  └─────────────┘                      └─────────────┘
```

## Key Benefits

### 1. **Pure Orchestration**
- Gleitzeit focuses **only** on coordination
- No execution logic in orchestrator
- Clean separation of concerns

### 2. **Unified Communication**
- **All tasks** use Socket.IO protocol
- Same monitoring, logging, and error handling
- Consistent service interface

### 3. **Provider Flexibility**
```python
# Mix any providers seamlessly
workflow.add_text_task("Internal", model="llama3", provider="internal")
workflow.add_text_task("OpenAI", model="gpt-4", provider="openai") 
workflow.add_text_task("Claude", model="claude-3", provider="anthropic")
```

### 4. **Independent Scaling**
- Scale LLM services independently
- Scale Python services independently  
- Add/remove providers dynamically

## Service Types

### **Internal Services** (Managed by Gleitzeit)

#### 1. Internal LLM Service
```python
# Wraps existing Ollama functionality
InternalLLMService(
    ollama_endpoints=[
        EndpointConfig("http://gpu-1:11434", gpu=True),
        EndpointConfig("http://gpu-2:11434", gpu=True)
    ],
    strategy=LoadBalancingStrategy.LEAST_LOADED
)
```
- All existing Ollama features preserved
- Load balancing, endpoint management
- Model loading, GPU optimization

#### 2. Python Executor Service
```python
@gleitzeit_task(category="data")
def my_function(data):
    return process(data)

# Auto-registered via decorator
```
- Decorator-based function registration
- Isolated execution environments
- Built-in function registry

### **External Services** (Third-party integrations)

#### 3. External LLM Providers
```python
# OpenAI Service
OpenAIService(api_key="sk-...")

# Anthropic Service  
AnthropicService(api_key="ant-...")

# Custom LLM Service
CustomLLMService(endpoint="https://my-api.com")
```

#### 4. External Business Services
```python
# Database services
DatabaseService(connection_string="...")

# API services
APIService(base_url="https://external-api.com")

# Custom business logic
CustomBusinessService()
```

## Migration Path

### Phase 1: Parallel Operation
```python
# Old way still works
cluster = GleitzeitCluster(use_unified_socketio_architecture=False)

# New way available
cluster = GleitzeitCluster(use_unified_socketio_architecture=True)
```

### Phase 2: Default Switch
- Change default to `use_unified_socketio_architecture=True`
- Auto-start internal services
- Deprecate direct execution

### Phase 3: Pure Orchestrator
- Remove all direct execution code
- Gleitzeit becomes purely coordinative
- All tasks route through services

## Usage Examples

### Basic Usage
```python
# Enable unified architecture
cluster = GleitzeitCluster(use_unified_socketio_architecture=True)
await cluster.start()  # Auto-starts internal services

workflow = cluster.create_workflow("My Workflow")

# All these route to appropriate services automatically
workflow.add_text_task("Local", model="llama3")         # → Internal LLM Service
workflow.add_text_task("GPT", model="gpt-4")            # → OpenAI Service
workflow.add_text_task("Claude", model="claude-3")      # → Anthropic Service
workflow.add_python_task("Process", "my_function")      # → Python Service
```

### Advanced Multi-Provider
```python
# Financial analysis using multiple providers
workflow = cluster.create_workflow("Financial Analysis")

# Internal Ollama for fast extraction
extract = workflow.add_text_task(
    "Extract Numbers", 
    prompt=f"Extract financial metrics: {document}",
    model="llama3",
    provider="internal"
)

# OpenAI for strategic analysis  
strategy = workflow.add_text_task(
    "Strategic Analysis",
    prompt="Analyze strategy: {{Extract Numbers.result}}",
    model="gpt-4",
    provider="openai",
    dependencies=["Extract Numbers"]
)

# Claude for risk assessment
risk = workflow.add_text_task(
    "Risk Assessment", 
    prompt="Assess risks: {{Extract Numbers.result}}",
    model="claude-3-sonnet",
    provider="anthropic",
    dependencies=["Extract Numbers"]
)

# Python for final formatting
report = workflow.add_python_task(
    "Format Report",
    function_name="create_report",
    args=["{{Strategic Analysis.result}}", "{{Risk Assessment.result}}"],
    dependencies=["Strategic Analysis", "Risk Assessment"]
)
```

## Service Auto-Start

```python
cluster = GleitzeitCluster(
    use_unified_socketio_architecture=True,
    
    # Auto-start internal services
    auto_start_internal_llm_service=True,
    auto_start_python_executor=True,
    
    # Configure internal services
    llm_service_workers=20,
    python_executor_workers=4
)

await cluster.start()
# ✅ Internal LLM Service started automatically
# ✅ Python Executor Service started automatically
```

## Monitoring

All services appear uniformly in monitoring:

```bash
python gleitzeit_cluster/cli_monitor_live.py
```

```
🔗 External Services (4 active):
   🟢 🧠 Internal LLM Service    Tasks: 2/20  Success: 98.5%  (llm_generation)
   🟢 🌐 OpenAI Service          Tasks: 1/10  Success: 95.2%  (llm_generation)  
   🟢 🤖 Anthropic Service       Tasks: 0/10  Success: 97.8%  (llm_generation)
   🟢 🐍 Python Tasks            Tasks: 1/4   Success: 100%   (python_execution)
```

## Benefits Summary

### **For Gleitzeit Core**
- **Simplified codebase**: Pure orchestration logic
- **Better testing**: No execution complexity
- **Cleaner APIs**: Uniform task interface

### **For LLM Management**
- **Provider flexibility**: Mix internal + external seamlessly
- **Same API**: Existing code works unchanged
- **Better isolation**: LLM services run independently

### **For Python Tasks**
- **Clean integration**: Simple decorator pattern
- **Better security**: Isolated execution
- **Scalability**: Independent scaling

### **For Operations**
- **Unified monitoring**: All services in one dashboard
- **Simplified deployment**: Services deploy independently
- **Better reliability**: Fault isolation between services

## Summary

The unified Socket.IO architecture transforms Gleitzeit into a **pure orchestrator** that coordinates a flexible ecosystem of services. This maintains all existing LLM orchestration capabilities while adding clean Python task integration and unlimited provider flexibility.

**Same simple API, much more powerful and flexible architecture.**