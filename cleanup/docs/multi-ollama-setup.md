# Multiple Local Ollama Hosts Setup

Quick guide to configure multiple Ollama servers on your local machine for distributed LLM processing with Gleitzeit.

## 🚀 Quick Setup (2 Servers)

### Step 1: Start Multiple Ollama Servers

```bash
# Terminal 1 - Primary server (default port)
ollama serve

# Terminal 2 - Secondary server (custom port)  
ollama serve --host 0.0.0.0 --port 11435
```

### Step 2: Install Models on Both Servers

```bash
# On primary server (port 11434)
ollama pull llama3
ollama pull llava

# On secondary server (port 11435)
OLLAMA_HOST=http://localhost:11435 ollama pull llama3
OLLAMA_HOST=http://localhost:11435 ollama pull codellama
```

### Step 3: Configure Gleitzeit

```python
from gleitzeit_cluster import GleitzeitCluster
from gleitzeit_cluster.execution.ollama_endpoint_manager import EndpointConfig, LoadBalancingStrategy

# Configure endpoints
endpoints = [
    EndpointConfig(
        name="primary",
        url="http://localhost:11434",
        priority=5,
        models=["llama3", "llava"],
        tags={"primary", "vision"}
    ),
    EndpointConfig(
        name="secondary", 
        url="http://localhost:11435",
        priority=3,
        models=["llama3", "codellama"],
        tags={"secondary", "code"}
    )
]

# Create cluster
cluster = GleitzeitCluster(
    ollama_endpoints=endpoints,
    ollama_strategy=LoadBalancingStrategy.LEAST_LOADED
)

# Your workflows now distribute across both servers automatically!
```

## 🏗️ Advanced Setup (4+ Servers)

### Multiple Port Configuration

```bash
# Start servers on different ports
ollama serve --port 11434  # Primary
ollama serve --port 11435  # Secondary  
ollama serve --port 11436  # GPU server
ollama serve --port 11437  # Backup
```

### Full Configuration Example

```python
endpoints = [
    # High-priority server with vision models
    EndpointConfig(
        name="gpu_server",
        url="http://localhost:11436", 
        priority=6,
        max_concurrent=10,
        models=["llama3", "llava", "mistral"],
        tags={"gpu", "vision", "fast"}
    ),
    
    # General purpose server
    EndpointConfig(
        name="main_server",
        url="http://localhost:11434",
        priority=5, 
        max_concurrent=8,
        models=["llama3", "codellama", "mistral"],
        tags={"general", "code"}
    ),
    
    # Specialized code server
    EndpointConfig(
        name="code_server", 
        url="http://localhost:11435",
        priority=4,
        max_concurrent=6,
        models=["codellama", "llama3"],
        tags={"code", "development"}
    ),
    
    # Backup server
    EndpointConfig(
        name="backup_server",
        url="http://localhost:11437",
        priority=2,
        max_concurrent=4,
        models=["llama3"],
        tags={"backup", "overflow"}
    )
]

cluster = GleitzeitCluster(
    ollama_endpoints=endpoints,
    ollama_strategy=LoadBalancingStrategy.LEAST_LOADED
)
```

## 📊 Load Balancing Strategies

Choose the best strategy for your use case:

### LEAST_LOADED (Recommended)
Routes to server with fewest active requests:
```python
ollama_strategy=LoadBalancingStrategy.LEAST_LOADED
```

### MODEL_AFFINITY
Prefers servers that already have the model loaded:
```python
ollama_strategy=LoadBalancingStrategy.MODEL_AFFINITY
```

### FASTEST_RESPONSE  
Routes to server with best average response time:
```python
ollama_strategy=LoadBalancingStrategy.FASTEST_RESPONSE
```

### ROUND_ROBIN
Simple rotation between healthy servers:
```python
ollama_strategy=LoadBalancingStrategy.ROUND_ROBIN
```

## 🔍 Usage Examples

### Automatic Distribution
```python
# Tasks automatically distributed across all healthy servers
workflow = cluster.create_workflow("Distributed Analysis")

workflow.add_text_task("Analysis 1", "Explain AI", "llama3")      # → Server A
workflow.add_text_task("Analysis 2", "Describe ML", "llama3")     # → Server B  
workflow.add_text_task("Code Review", "Review this code", "codellama")  # → Code server
workflow.add_vision_task("Image Analysis", "Describe image", "llava", "photo.jpg")  # → GPU server

# Execute - all tasks run in parallel across multiple servers
result = await cluster.submit_workflow(workflow)
```

### Manual Server Selection via Tags
```python
# Route to specific server types
workflow.add_text_task(
    "Fast Analysis", 
    "Quick analysis needed",
    "llama3",
    preferred_tags={"gpu", "fast"}  # Prefers GPU server
)

workflow.add_text_task(
    "Code Generation",
    "Write Python code",
    "codellama", 
    preferred_tags={"code"}  # Routes to code server
)
```

## 📊 Monitoring Multiple Servers

### Real-time Statistics
```python
# Get stats from all endpoints
manager = cluster.task_executor.ollama_manager
stats = manager.get_endpoint_stats()

for endpoint_name, data in stats.items():
    config = data["config"]
    metrics = data["stats"]
    
    print(f"{endpoint_name} ({config['url']}):")
    print(f"  Load: {metrics['current_load']}/{config['max_concurrent']}")
    print(f"  Success Rate: {metrics['success_rate']:.2%}")
    print(f"  Avg Response: {metrics['average_response_time']:.1f}s")
    print(f"  Models: {metrics['available_models']}")
```

### Health Monitoring
```python
# Check which servers are healthy
healthy = manager.get_healthy_endpoints()
print(f"Healthy servers: {healthy}")

# Force health check
await manager._check_all_endpoints_health()

# Check specific endpoint
endpoint_health = await manager.clients["gpu_server"].health_check()
```

## ⚡ Performance Tips

### Server Specialization
- **GPU Server**: Focus on vision models (llava, bakllava)
- **CPU Servers**: Text models (llama3, mistral, codellama)
- **Fast SSD**: Code and development models
- **Backup**: General models for overflow

### Resource Allocation
```python
EndpointConfig(
    name="gpu_server",
    max_concurrent=12,  # Higher for GPU
    priority=6          # Highest priority
),
EndpointConfig(
    name="cpu_server", 
    max_concurrent=6,   # Lower for CPU
    priority=3
)
```

### Model Distribution
```bash
# Distribute models across servers based on capability
# GPU Server - Vision models
OLLAMA_HOST=http://localhost:11436 ollama pull llava
OLLAMA_HOST=http://localhost:11436 ollama pull bakllava

# CPU Servers - Text models  
OLLAMA_HOST=http://localhost:11434 ollama pull llama3
OLLAMA_HOST=http://localhost:11434 ollama pull mistral

# Development Server - Code models
OLLAMA_HOST=http://localhost:11435 ollama pull codellama
```

## 🔧 Troubleshooting

### Common Issues

**"No healthy endpoints"**
- Check all Ollama servers are running
- Verify URLs and ports are correct
- Test connectivity: `curl http://localhost:11435/api/version`

**"Model not found"** 
- Ensure model is installed on at least one server
- Check `ollama list` on each server
- Use `OLLAMA_HOST` for specific servers

**Uneven load distribution**
- Check server priorities and max_concurrent settings
- Monitor with `get_endpoint_stats()`
- Consider different load balancing strategy

### Debug Commands
```bash
# Check server status
curl http://localhost:11434/api/version
curl http://localhost:11435/api/version

# List models on specific server
OLLAMA_HOST=http://localhost:11435 ollama list

# Test model on specific server  
OLLAMA_HOST=http://localhost:11435 ollama run llama3 "Hello"
```

## 🎯 Example Workflows

See `examples/multi_ollama_hosts.py` for complete examples:

```bash
# Run the multi-endpoint example
python examples/multi_ollama_hosts.py

# Shows:
# - 4-server configuration
# - Load balancing strategies  
# - Task distribution
# - Monitoring examples
```

---

**Benefits of Multiple Ollama Hosts:**
- ⚡ **Parallel Processing** - Multiple requests simultaneously
- 🔄 **Automatic Failover** - Continue if one server fails  
- ⚖️ **Load Distribution** - Optimal resource utilization
- 🎯 **Model Specialization** - Different servers for different models
- 📈 **Scalability** - Add more servers as needed