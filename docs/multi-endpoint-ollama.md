# Multi-Endpoint Ollama Implementation

The Gleitzeit Cluster supports multiple Ollama endpoints with intelligent load balancing, automatic failover, and model-aware routing. This document explains the technical implementation and usage.

## 🏗️ Architecture Overview

The multi-endpoint system is implemented through several interconnected components that work together to provide seamless distributed LLM execution:

```
┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐
│   TaskExecutor      │───▶│ OllamaEndpointMgr   │───▶│   OllamaClient      │
│   (Orchestration)   │    │   (Load Balancer)   │    │   (Endpoint A)      │
└─────────────────────┘    └─────────────────────┘    └─────────────────────┘
                                      │                 ┌─────────────────────┐
                                      └────────────────▶│   OllamaClient      │
                                                        │   (Endpoint B)      │
                                                        └─────────────────────┘
```

## 📋 Core Data Structures

### EndpointConfig
Configuration for each Ollama server endpoint:

```python
@dataclass
class EndpointConfig:
    name: str                      # Unique identifier
    url: str                       # Server URL (e.g., "http://localhost:11434")
    timeout: int = 300            # Request timeout in seconds
    max_concurrent: int = 10      # Maximum concurrent requests
    priority: int = 1             # Selection priority (higher = preferred)
    models: Optional[List[str]]   # Preferred models (None = any model)
    tags: Set[str]               # Capability tags (e.g., {"gpu", "vision"})
```

### EndpointStats
Real-time statistics and health tracking:

```python
@dataclass 
class EndpointStats:
    total_requests: int = 0              # Total requests processed
    successful_requests: int = 0         # Successful requests
    failed_requests: int = 0            # Failed requests  
    current_load: int = 0               # Currently active requests
    average_response_time: float = 0.0  # Exponential moving average
    is_healthy: bool = True             # Health status
    available_models: List[str]         # Models available on endpoint
    last_health_check: Optional[datetime] # Last health check time
    last_error: Optional[str]           # Last error message
```

## 🔧 Configuration and Usage

### Basic Configuration

```python
from gleitzeit_cluster.core.cluster import GleitzeitCluster
from gleitzeit_cluster.execution.ollama_endpoint_manager import EndpointConfig

# Simple multi-endpoint setup
endpoints = [
    EndpointConfig(name="primary", url="http://localhost:11434"),
    EndpointConfig(name="backup", url="http://remote-server:11434")
]

cluster = GleitzeitCluster(ollama_endpoints=endpoints)
```

### Advanced Configuration

```python
endpoints = [
    EndpointConfig(
        name="local_fast",
        url="http://localhost:11434",
        priority=3,                    # Higher priority
        max_concurrent=5,              # Request limit
        tags={"local", "fast"}         # Capabilities
    ),
    EndpointConfig(
        name="gpu_vision",
        url="http://gpu-server:11434", 
        priority=4,                    # Highest priority
        max_concurrent=8,
        models=["llava", "bakllava"],  # Vision-specific models
        tags={"gpu", "vision"}
    ),
    EndpointConfig(
        name="cloud_backup",
        url="http://cloud.example.com:11434",
        priority=1,                    # Fallback priority
        max_concurrent=20,
        tags={"cloud", "scalable"}
    )
]

cluster = GleitzeitCluster(
    ollama_endpoints=endpoints,
    ollama_strategy=LoadBalancingStrategy.LEAST_LOADED
)
```

### Using Existing Workflow Code

Your existing workflow code works unchanged - the system automatically handles endpoint selection:

```python
# This code works the same with single or multiple endpoints!
workflow = cluster.create_workflow("analysis", "Multi-endpoint workflow")

# Tasks are automatically routed to optimal endpoints
task1 = workflow.add_text_task("analyze", "Analyze this data", "llama3")
task2 = workflow.add_vision_task("describe", "Describe this image", "llava", "image.jpg")

result = await cluster.execute_workflow(workflow)
```

## ⚖️ Load Balancing Strategies

### 1. ROUND_ROBIN
Simple rotation between healthy endpoints:

```python
# Implementation
selected = candidates[self.round_robin_index % len(candidates)]
self.round_robin_index += 1
```

**Use Case**: Equal distribution when all endpoints have similar performance.

### 2. LEAST_LOADED (Default)
Selects endpoint with fewest active requests:

```python
# Implementation  
return min(candidates, key=lambda name: (
    self.stats[name].current_load,      # Primary: lowest load
    -self.endpoints[name].priority      # Tie-breaker: highest priority
))
```

**Use Case**: Optimal for varying request processing times and mixed workloads.

### 3. FASTEST_RESPONSE
Routes to endpoint with best average response time:

```python
# Implementation
return min(candidates, key=lambda name: (
    self.stats[name].average_response_time,  # Primary: fastest
    self.stats[name].current_load           # Tie-breaker: lowest load
))
```

**Use Case**: Latency-sensitive applications where response time is critical.

### 4. MODEL_AFFINITY
Prefers endpoints that already have the target model loaded:

```python
# Implementation
if model:
    model_ready = [name for name in candidates 
                   if model in self.stats[name].available_models]
    if model_ready:
        return min(model_ready, key=lambda name: self.stats[name].current_load)
```

**Use Case**: Reduces model loading overhead when endpoints specialize in specific models.

## 🎯 Intelligent Endpoint Selection

The `select_endpoint()` method implements a multi-stage filtering process:

### Stage 1: Health Filtering
```python
candidates = [name for name in self.get_healthy_endpoints() 
              if name not in exclude]
```
Only healthy endpoints are considered for selection.

### Stage 2: Model Filtering  
```python
if model:
    model_candidates = [name for name in candidates
                       if name in self.get_endpoints_with_model(model)]
```
Filters endpoints that have the required model available.

### Stage 3: Tag Filtering
```python
if tags:
    tag_candidates = [name for name in candidates
                     if tags.issubset(self.endpoints[name].tags)]
```
Matches endpoints with required capabilities (GPU, vision, etc.).

### Stage 4: Strategy Application
Applies the configured load balancing strategy to final candidates.

## 🔄 Automatic Failover Implementation

The failover system provides robust error handling with automatic retry:

```python
async def _execute_with_failover(self, method: str, model: str, **kwargs) -> Any:
    attempted_endpoints = set()
    last_error = None
    
    while True:
        # Select best available endpoint (excluding failed ones)
        endpoint_name = self.select_endpoint(
            model=model,
            exclude=attempted_endpoints
        )
        
        if not endpoint_name:
            # All suitable endpoints exhausted
            raise OllamaError(f"All endpoints failed. Last error: {last_error}")
        
        try:
            # Execute request
            stats = self.stats[endpoint_name]
            stats.current_load += 1  # Track concurrent load
            
            client = self.clients[endpoint_name]
            result = await getattr(client, method)(model=model, **kwargs)
            
            # Success: update statistics
            stats.successful_requests += 1
            stats.total_requests += 1
            return result
            
        except Exception as e:
            # Failure: mark endpoint as attempted, try next
            stats.failed_requests += 1 
            stats.total_requests += 1
            attempted_endpoints.add(endpoint_name)
            last_error = e
            
        finally:
            stats.current_load = max(0, stats.current_load - 1)
```

### Failover Features:
- **Progressive Retry**: Tries all suitable endpoints before failing
- **Load Tracking**: Maintains accurate concurrent request counts
- **Statistics Update**: Records success/failure rates for monitoring
- **Error Preservation**: Returns the last error if all endpoints fail

## 🏥 Health Monitoring System

### Background Health Checks
```python
async def _health_monitor_loop(self):
    while True:
        try:
            await asyncio.sleep(self.health_check_interval)  # Default: 60s
            await self._check_all_endpoints_health()
        except asyncio.CancelledError:
            break
```

### Concurrent Health Verification
```python
async def _check_all_endpoints_health(self):
    tasks = []
    for name in self.endpoints:
        task = asyncio.create_task(self._check_endpoint_health(name))
        tasks.append(task)
    
    # Run all health checks simultaneously
    await asyncio.gather(*tasks, return_exceptions=True)
```

### Individual Endpoint Health Check
```python
async def _check_endpoint_health(self, endpoint_name: str) -> bool:
    client = self.clients[endpoint_name]
    stats = self.stats[endpoint_name]
    
    try:
        start_time = time.time()
        
        # Health check with timeout
        healthy = await asyncio.wait_for(
            client.health_check(),
            timeout=self.health_check_timeout  # Default: 10s
        )
        
        if healthy:
            stats.is_healthy = True
            # Update response time (exponential moving average)
            response_time = time.time() - start_time
            if stats.average_response_time == 0:
                stats.average_response_time = response_time
            else:
                stats.average_response_time = (
                    0.7 * stats.average_response_time + 0.3 * response_time
                )
            
            # Refresh available models
            try:
                models = await client.list_models()
                stats.available_models = models
            except Exception:
                pass  # Model listing failure doesn't affect health status
                
        else:
            stats.is_healthy = False
            
    except Exception as e:
        stats.is_healthy = False
        stats.last_error = str(e)
    
    stats.last_health_check = datetime.utcnow()
    return stats.is_healthy
```

### Health Monitoring Features:
- **Concurrent Checks**: All endpoints checked simultaneously for efficiency
- **Configurable Intervals**: Health check frequency can be adjusted
- **Response Time Tracking**: Exponential moving average for performance metrics
- **Model Discovery**: Automatic detection of available models per endpoint
- **Graceful Degradation**: Endpoints automatically recovered when healthy

## 🔗 TaskExecutor Integration

The TaskExecutor seamlessly integrates single and multi-endpoint modes:

### Initialization Logic
```python
def __init__(self, ollama_endpoints: Optional[List[EndpointConfig]] = None, ...):
    if ollama_endpoints:
        # Multi-endpoint mode
        self.ollama_manager = OllamaEndpointManager(
            endpoints=ollama_endpoints,
            strategy=ollama_strategy
        )
        self.ollama_client = None
        self._multi_endpoint_mode = True
    else:
        # Single endpoint mode (backward compatibility)
        self.ollama_client = OllamaClient(base_url=ollama_url)
        self.ollama_manager = None
        self._multi_endpoint_mode = False
```

### Task Execution
```python
async def _execute_text_task(self, task: Task) -> str:
    params = task.parameters
    
    if self._multi_endpoint_mode:
        # Multi-endpoint execution with automatic routing
        result = await self.ollama_manager.execute_text_task(
            model=params.model_name or "llama3",
            prompt=params.prompt,
            temperature=params.temperature or 0.7,
            preferred_tags=getattr(params, 'endpoint_tags', None)
        )
    else:
        # Single endpoint execution
        result = await self.ollama_client.generate_text(
            model=params.model_name or "llama3",
            prompt=params.prompt,
            temperature=params.temperature or 0.7
        )
    
    return result
```

## 📊 Monitoring and Statistics

### Real-time Endpoint Statistics
```python
# Get comprehensive statistics for all endpoints
stats = cluster.task_executor.ollama_manager.get_endpoint_stats()

# Example output structure:
{
    "gpu_server": {
        "config": {
            "url": "http://gpu-server:11434",
            "priority": 4,
            "max_concurrent": 8,
            "tags": ["gpu", "vision"]
        },
        "stats": {
            "is_healthy": True,
            "current_load": 2,
            "total_requests": 150,
            "success_rate": 0.96,
            "average_response_time": 2.3,
            "available_models": ["llava", "llama3", "codellama"]
        }
    }
}
```

### Key Metrics:
- **Health Status**: Current endpoint availability
- **Load Metrics**: Active requests vs. capacity
- **Performance**: Success rates and response times
- **Model Availability**: Which models are ready on each endpoint

## 🛠️ Runtime Management

### Adding Endpoints Dynamically
```python
# Add new endpoint while system is running
new_endpoint = EndpointConfig(
    name="new_gpu_server",
    url="http://new-gpu:11434",
    tags={"gpu", "experimental"}
)

cluster.task_executor.ollama_manager.add_endpoint(new_endpoint)
```

### Removing Endpoints
```python
# Remove endpoint (gracefully handles active requests)
cluster.task_executor.ollama_manager.remove_endpoint("old_server")
```

### Health Check Management
```python
# Force immediate health check
await cluster.task_executor.ollama_manager._check_all_endpoints_health()

# Get healthy endpoints
healthy = cluster.task_executor.ollama_manager.get_healthy_endpoints()
print(f"Healthy endpoints: {healthy}")
```

## 🔄 Complete Request Flow

Here's how a request flows through the multi-endpoint system:

```
1. User Code
   workflow.add_text_task("analyze", "Prompt", "llama3")
                    ↓
2. TaskExecutor
   Detects multi-endpoint mode
                    ↓
3. EndpointManager.execute_text_task()
   model="llama3", prompt="...", preferred_tags=None
                    ↓
4. select_endpoint()
   • Filter healthy endpoints: ["primary", "gpu_server", "cloud_backup"]
   • Filter by model: ["primary", "gpu_server"] (both have llama3)
   • No tag filtering (preferred_tags=None)
   • Apply LEAST_LOADED strategy
                    ↓
5. _apply_strategy()
   • primary: current_load=3, priority=3
   • gpu_server: current_load=1, priority=4
   • Selected: "gpu_server" (lowest load)
                    ↓
6. _execute_with_failover()
   • endpoint_name = "gpu_server"
   • stats.current_load += 1  (now 2)
   • client = clients["gpu_server"]
   • await client.generate_text(model="llama3", prompt="...")
                    ↓
7. Result Handling
   SUCCESS: Update stats, return result
   FAILURE: Mark "gpu_server" as attempted, try "primary" next
```

## 🎛️ Advanced Configuration Examples

### GPU-Optimized Setup
```python
endpoints = [
    # Local CPU fallback
    EndpointConfig(
        name="cpu_local",
        url="http://localhost:11434",
        priority=1,
        models=["llama3", "mistral"],
        tags={"cpu", "local"}
    ),
    
    # High-end GPU server
    EndpointConfig(
        name="gpu_primary", 
        url="http://gpu-server-1:11434",
        priority=5,
        max_concurrent=12,
        models=["llama3", "llava", "codellama"],
        tags={"gpu", "primary", "vision", "code"}
    ),
    
    # Secondary GPU for overflow
    EndpointConfig(
        name="gpu_secondary",
        url="http://gpu-server-2:11434", 
        priority=4,
        max_concurrent=8,
        models=["llama3", "mistral"],
        tags={"gpu", "secondary"}
    )
]

cluster = GleitzeitCluster(
    ollama_endpoints=endpoints,
    ollama_strategy=LoadBalancingStrategy.MODEL_AFFINITY
)
```

### Multi-Region Setup
```python
endpoints = [
    # Local region (primary)
    EndpointConfig(
        name="us_west_1",
        url="http://ollama-usw1.company.com:11434",
        priority=5,
        max_concurrent=15,
        tags={"us-west", "primary", "low-latency"}
    ),
    
    # Backup region  
    EndpointConfig(
        name="us_east_1",
        url="http://ollama-use1.company.com:11434",
        priority=3,
        max_concurrent=15, 
        tags={"us-east", "backup"}
    ),
    
    # International fallback
    EndpointConfig(
        name="eu_central_1",
        url="http://ollama-euc1.company.com:11434",
        priority=1,
        max_concurrent=10,
        tags={"europe", "fallback"}
    )
]

cluster = GleitzeitCluster(
    ollama_endpoints=endpoints,
    ollama_strategy=LoadBalancingStrategy.FASTEST_RESPONSE
)
```

## 🚨 Error Handling and Recovery

### Automatic Error Recovery
- **Circuit Breaker**: Endpoints with high failure rates automatically excluded
- **Gradual Recovery**: Failed endpoints slowly reintroduced when healthy
- **Request Isolation**: Failures on one endpoint don't affect others
- **Comprehensive Logging**: All failures logged with context for debugging

### Error Categories
1. **Network Errors**: Connection timeouts, DNS failures → Retry on other endpoints
2. **Model Errors**: Model not found → Route to endpoints with the model  
3. **Capacity Errors**: Too many requests → Route to less loaded endpoints
4. **Server Errors**: Ollama server issues → Mark endpoint unhealthy, retry elsewhere

## 🔧 Performance Considerations

### Optimization Strategies
- **Connection Pooling**: Each endpoint maintains persistent HTTP connections
- **Concurrent Health Checks**: All endpoints checked simultaneously
- **Efficient Model Discovery**: Model lists cached and refreshed periodically
- **Load Balancing Overhead**: Minimal - selection algorithms are O(n) where n = endpoints

### Scaling Guidelines
- **10-50 endpoints**: Excellent performance with all strategies
- **50+ endpoints**: Consider regional clustering or custom selection logic
- **Health check frequency**: Balance between responsiveness and overhead
- **Model affinity**: Most effective with 3-10 endpoints per model type

## 📝 Best Practices

### Endpoint Configuration
1. **Use descriptive names**: `gpu_vision_server` vs `server_1`
2. **Set appropriate priorities**: Higher for more capable hardware
3. **Configure realistic limits**: `max_concurrent` based on server capacity
4. **Tag endpoints by capability**: `{"gpu", "vision", "fast"}`
5. **Group similar endpoints**: Same models and performance characteristics

### Load Balancing Strategy Selection
- **LEAST_LOADED**: Best default choice for mixed workloads
- **MODEL_AFFINITY**: When endpoints specialize in specific models
- **FASTEST_RESPONSE**: For latency-critical applications
- **ROUND_ROBIN**: When all endpoints have identical performance

### Monitoring and Maintenance
1. **Monitor success rates**: Alert when below 95%
2. **Track response times**: Identify performance degradation
3. **Watch load distribution**: Ensure requests spread evenly
4. **Health check intervals**: 30-60 seconds for production
5. **Log analysis**: Regular review of failover patterns

## 🎯 Production Deployment

### High Availability Setup
```python
# Production-ready configuration
endpoints = [
    # Primary data center
    EndpointConfig("dc1_gpu1", "http://dc1-gpu1:11434", priority=5, 
                  max_concurrent=10, tags={"dc1", "gpu", "primary"}),
    EndpointConfig("dc1_gpu2", "http://dc1-gpu2:11434", priority=5,
                  max_concurrent=10, tags={"dc1", "gpu", "primary"}),
    
    # Secondary data center  
    EndpointConfig("dc2_gpu1", "http://dc2-gpu1:11434", priority=3,
                  max_concurrent=10, tags={"dc2", "gpu", "backup"}),
    EndpointConfig("dc2_gpu2", "http://dc2-gpu2:11434", priority=3, 
                  max_concurrent=10, tags={"dc2", "gpu", "backup"}),
                  
    # CPU fallback
    EndpointConfig("cpu_fallback", "http://cpu-cluster:11434", priority=1,
                  max_concurrent=20, tags={"cpu", "fallback"})
]

cluster = GleitzeitCluster(
    ollama_endpoints=endpoints,
    ollama_strategy=LoadBalancingStrategy.LEAST_LOADED
)
```

### Monitoring Integration
```python
# Periodic statistics collection for monitoring
async def collect_metrics():
    stats = cluster.task_executor.ollama_manager.get_endpoint_stats()
    
    for endpoint_name, data in stats.items():
        metrics = data["stats"]
        
        # Send to monitoring system (Prometheus, DataDog, etc.)
        monitor.gauge("ollama.endpoint.load", metrics["current_load"], 
                     tags={"endpoint": endpoint_name})
        monitor.gauge("ollama.endpoint.success_rate", metrics["success_rate"],
                     tags={"endpoint": endpoint_name}) 
        monitor.gauge("ollama.endpoint.response_time", metrics["average_response_time"],
                     tags={"endpoint": endpoint_name})
```

## 🔍 Troubleshooting

### Common Issues

**Problem**: Requests always go to same endpoint
- **Cause**: Other endpoints marked unhealthy
- **Solution**: Check health status, verify connectivity

**Problem**: High response times
- **Cause**: Overloaded endpoints or network issues  
- **Solution**: Add more endpoints, check FASTEST_RESPONSE strategy

**Problem**: Model not found errors
- **Cause**: Model not available on selected endpoints
- **Solution**: Verify model availability, use MODEL_AFFINITY strategy

**Problem**: Connection failures
- **Cause**: Network issues or server downtime
- **Solution**: Check endpoint URLs, verify server status

### Debugging Commands
```python
# Check endpoint health
manager = cluster.task_executor.ollama_manager
healthy = manager.get_healthy_endpoints()
print(f"Healthy: {healthy}")

# Get detailed statistics  
stats = manager.get_endpoint_stats()
for name, data in stats.items():
    print(f"{name}: {data['stats']}")

# Force health check
await manager._check_all_endpoints_health()

# Test specific endpoint
client = manager.clients["endpoint_name"]
health = await client.health_check()
print(f"Health: {health}")
```

## 📚 API Reference

### EndpointConfig
```python
@dataclass
class EndpointConfig:
    name: str                      # Required: Unique endpoint name
    url: str                       # Required: Ollama server URL
    timeout: int = 300            # Optional: Request timeout (seconds)
    max_concurrent: int = 10      # Optional: Max concurrent requests
    priority: int = 1             # Optional: Selection priority
    models: Optional[List[str]] = None  # Optional: Preferred models
    tags: Set[str] = field(default_factory=set)  # Optional: Capability tags
```

### LoadBalancingStrategy
```python
class LoadBalancingStrategy(Enum):
    ROUND_ROBIN = "round_robin"        # Simple rotation
    LEAST_LOADED = "least_loaded"      # Minimum active requests
    FASTEST_RESPONSE = "fastest_response"  # Best response time
    MODEL_AFFINITY = "model_affinity"  # Prefer endpoints with target model
```

### OllamaEndpointManager
```python
class OllamaEndpointManager:
    def __init__(
        self, 
        endpoints: List[EndpointConfig],
        strategy: LoadBalancingStrategy = LoadBalancingStrategy.LEAST_LOADED,
        health_check_interval: int = 60,
        health_check_timeout: int = 10
    )
    
    async def start() -> None
    async def stop() -> None
    
    def select_endpoint(
        self, 
        model: Optional[str] = None,
        tags: Optional[Set[str]] = None, 
        exclude: Optional[Set[str]] = None
    ) -> Optional[str]
    
    def get_healthy_endpoints() -> List[str]
    def get_endpoints_with_model(self, model: str) -> List[str]
    def get_endpoint_stats() -> Dict[str, Dict[str, Any]]
    
    def add_endpoint(self, config: EndpointConfig) -> None
    def remove_endpoint(self, endpoint_name: str) -> None
    
    async def execute_text_task(...) -> str
    async def execute_vision_task(...) -> str
```

---

## 🎉 Summary

The multi-endpoint Ollama implementation provides enterprise-grade distributed LLM execution with:

- **Intelligent Routing**: Model-aware and capability-based endpoint selection
- **Load Balancing**: Four strategies for optimal request distribution  
- **Automatic Failover**: Seamless recovery from endpoint failures
- **Health Monitoring**: Real-time endpoint status and performance tracking
- **Runtime Management**: Dynamic endpoint addition/removal
- **Production Ready**: Comprehensive error handling and monitoring

The system is designed for scalability, reliability, and ease of use - your existing workflow code works unchanged while gaining all the benefits of distributed execution!