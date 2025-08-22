# vLLM Integration Roadmap for Gleitzeit

## Executive Summary

This document outlines a phased approach to integrate vLLM (Very Large Language Model) inference engine into Gleitzeit's workflow orchestration system. vLLM offers significant performance improvements over traditional inference engines through PagedAttention, continuous batching, and optimized CUDA kernels.

## Why vLLM?

### Performance Benefits
- **2-24x higher throughput** compared to HuggingFace Transformers
- **Continuous batching** for optimal GPU utilization
- **PagedAttention** for efficient KV cache management
- **Tensor parallelism** for multi-GPU deployments
- **Quantization support** (AWQ, GPTQ, SqueezeLLM)

### Compatibility
- **OpenAI-compatible API** - Drop-in replacement for existing LLM providers
- **Wide model support** - Llama, Mistral, Mixtral, Phi, Qwen, and more
- **Production ready** - Built-in metrics, health checks, and request queuing

## Integration Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Gleitzeit Core                        │
├─────────────────────────────────────────────────────────┤
│              Protocol Provider Registry                  │
├──────────────┬────────────────┬────────────────────────┤
│ OllamaProvider│  VLLMProvider │    MCPProvider         │
├──────────────┴────────────────┴────────────────────────┤
│                   Resource Manager                      │
├──────────────┬────────────────┬────────────────────────┤
│  OllamaHub   │    VLLMHub     │     DockerHub          │
└──────────────┴────────────────┴────────────────────────┘
```

## Phase 1: Basic VLLMProvider (Week 1-2)

### Goals
- Implement minimal viable VLLMProvider
- Support basic chat completions
- Connect to existing vLLM server

### Tasks

#### 1.1 Create VLLMProvider Class
```python
# src/gleitzeit/providers/vllm_provider.py
from gleitzeit.providers.base import HTTPServiceProvider
from gleitzeit.protocols.llm_protocol import LLMProtocol

class VLLMProvider(HTTPServiceProvider):
    """Provider for vLLM inference servers."""
    
    def __init__(
        self,
        provider_id: str = "vllm",
        protocol_id: str = "llm/v1",
        base_url: str = "http://localhost:8000",
        api_key: Optional[str] = None,
        **kwargs
    ):
        super().__init__(
            provider_id=provider_id,
            protocol_id=protocol_id,
            base_url=base_url,
            **kwargs
        )
        self.api_key = api_key
        self._protocol = LLMProtocol()
    
    def get_supported_methods(self) -> List[str]:
        return ["llm/chat", "llm/complete"]
    
    async def handle_request(
        self,
        method: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Route LLM protocol methods to vLLM endpoints."""
        if method == "llm/chat":
            return await self._handle_chat(params)
        elif method == "llm/complete":
            return await self._handle_complete(params)
        else:
            raise ValueError(f"Unsupported method: {method}")
    
    async def _handle_chat(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle chat completion requests."""
        # Transform Gleitzeit format to OpenAI format
        request = {
            "model": params.get("model", "default"),
            "messages": params.get("messages", []),
            "temperature": params.get("temperature", 0.7),
            "max_tokens": params.get("max_tokens", 2048),
            "stream": params.get("stream", False)
        }
        
        response = await self._post("/v1/chat/completions", request)
        
        # Transform OpenAI format back to Gleitzeit format
        return {
            "response": response["choices"][0]["message"]["content"],
            "model": response["model"],
            "usage": response.get("usage", {}),
            "metadata": {
                "provider": "vllm",
                "finish_reason": response["choices"][0]["finish_reason"]
            }
        }
```

#### 1.2 Configuration Support
```python
# src/gleitzeit/hub/configs.py (addition)
@dataclass
class VLLMConfig:
    """Configuration for vLLM server instances."""
    host: str = "127.0.0.1"
    port: int = 8000
    model: str = "meta-llama/Llama-2-7b-hf"
    
    # Model loading
    download_dir: Optional[str] = None
    load_format: str = "auto"  # auto, pt, safetensors
    dtype: str = "auto"  # float16, bfloat16, float32
    
    # Parallelism
    tensor_parallel_size: int = 1
    pipeline_parallel_size: int = 1
    
    # Memory management
    gpu_memory_utilization: float = 0.9
    max_model_len: Optional[int] = None
    max_num_seqs: int = 256
    
    # Optimization
    enable_prefix_caching: bool = False
    enable_chunked_prefill: bool = False
    max_num_batched_tokens: Optional[int] = None
    
    # Quantization
    quantization: Optional[str] = None  # awq, gptq, squeezellm
    
    # API settings
    api_key: Optional[str] = None
    served_model_name: Optional[str] = None
```

#### 1.3 Registration and Testing
```python
# src/gleitzeit/registry.py (addition)
async def register_vllm_provider(registry: ProtocolProviderRegistry):
    """Register vLLM provider with the registry."""
    from gleitzeit.providers.vllm_provider import VLLMProvider
    
    vllm_provider = VLLMProvider()
    await vllm_provider.initialize()
    registry.register_provider(vllm_provider)
```

### Deliverables
- [ ] VLLMProvider implementation
- [ ] Basic configuration support
- [ ] Unit tests for provider
- [ ] Integration test with running vLLM server
- [ ] Documentation for basic usage

### Example Usage
```yaml
# workflows/vllm_test.yaml
name: "vLLM Test Workflow"
tasks:
  - id: "generate"
    method: "llm/chat"
    provider: "vllm"  # Explicitly use vLLM provider
    parameters:
      model: "meta-llama/Llama-2-7b-hf"
      messages:
        - role: "user"
          content: "Explain quantum computing in simple terms"
      temperature: 0.7
      max_tokens: 500
```

## Phase 2: VLLMHub Resource Management (Week 3-4)

### Goals
- Implement VLLMHub for lifecycle management
- Support multiple vLLM instances
- Enable model-aware load balancing

### Tasks

#### 2.1 Create VLLMHub Class
```python
# src/gleitzeit/hub/vllm_hub.py
from gleitzeit.hub.base import ResourceHub, ResourceInstance
from gleitzeit.hub.configs import VLLMConfig
import asyncio
import aiohttp

class VLLMInstance(ResourceInstance[VLLMConfig]):
    """Represents a vLLM server instance."""
    
    def __init__(self, config: VLLMConfig):
        super().__init__(
            instance_id=f"vllm-{config.host}:{config.port}",
            resource_type=ResourceType.CUSTOM,
            config=config
        )
        self.base_url = f"http://{config.host}:{config.port}"
        self.model = config.model
        self.process = None
    
    async def get_capabilities(self) -> Set[str]:
        """Return model name as capability."""
        return {self.model, "vllm"}

class VLLMHub(ResourceHub[VLLMConfig]):
    """Manages vLLM server instances."""
    
    def __init__(self, hub_id: str = "vllm_hub"):
        super().__init__(hub_id=hub_id, resource_type=ResourceType.CUSTOM)
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def initialize(self):
        """Initialize the hub."""
        await super().initialize()
        self._session = aiohttp.ClientSession()
        await self._discover_instances()
    
    async def _discover_instances(self):
        """Discover running vLLM instances."""
        # Check common ports
        ports = [8000, 8001, 8002, 8003]
        for port in ports:
            config = VLLMConfig(port=port)
            if await self._check_server(config):
                instance = VLLMInstance(config)
                await self.register_instance(instance)
    
    async def _check_server(self, config: VLLMConfig) -> bool:
        """Check if vLLM server is running."""
        try:
            url = f"http://{config.host}:{config.port}/v1/models"
            async with self._session.get(url, timeout=2) as response:
                if response.status == 200:
                    data = await response.json()
                    # Update config with discovered model
                    if data.get("data"):
                        config.model = data["data"][0]["id"]
                    return True
        except:
            pass
        return False
    
    async def start_instance(self, config: VLLMConfig) -> VLLMInstance:
        """Start a new vLLM server instance."""
        instance = VLLMInstance(config)
        
        # Build command
        cmd = [
            "python", "-m", "vllm.entrypoints.openai.api_server",
            "--model", config.model,
            "--host", config.host,
            "--port", str(config.port),
            "--tensor-parallel-size", str(config.tensor_parallel_size),
            "--gpu-memory-utilization", str(config.gpu_memory_utilization),
        ]
        
        if config.max_model_len:
            cmd.extend(["--max-model-len", str(config.max_model_len)])
        
        if config.quantization:
            cmd.extend(["--quantization", config.quantization])
        
        # Start process
        instance.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # Wait for server to be ready
        for _ in range(60):  # 60 second timeout
            if await self._check_server(config):
                break
            await asyncio.sleep(1)
        else:
            raise TimeoutError("vLLM server failed to start")
        
        await self.register_instance(instance)
        return instance
    
    async def check_health(self, instance: VLLMInstance) -> bool:
        """Check health of vLLM instance."""
        try:
            url = f"{instance.base_url}/health"
            async with self._session.get(url, timeout=5) as response:
                return response.status == 200
        except:
            return False
    
    async def collect_metrics(self, instance: VLLMInstance) -> Dict[str, Any]:
        """Collect metrics from vLLM instance."""
        metrics = {}
        try:
            # Get model info
            url = f"{instance.base_url}/v1/models"
            async with self._session.get(url, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    metrics["models"] = data.get("data", [])
            
            # Get metrics if available
            url = f"{instance.base_url}/metrics"
            async with self._session.get(url, timeout=5) as response:
                if response.status == 200:
                    metrics["raw_metrics"] = await response.text()
                    # Parse Prometheus metrics
                    metrics["requests_total"] = self._parse_metric(
                        metrics["raw_metrics"], 
                        "vllm:num_requests_total"
                    )
        except:
            pass
        
        return metrics
```

#### 2.2 Integration with ResourceManager
```python
# src/gleitzeit/manager.py (modification)
async def initialize_resource_manager():
    """Initialize resource manager with all hubs."""
    manager = ResourceManager()
    
    # Existing hubs
    ollama_hub = OllamaHub()
    await ollama_hub.initialize()
    manager.register_hub(ollama_hub)
    
    # Add vLLM hub
    vllm_hub = VLLMHub()
    await vllm_hub.initialize()
    manager.register_hub(vllm_hub)
    
    return manager
```

### Deliverables
- [ ] VLLMHub implementation
- [ ] Instance lifecycle management
- [ ] Health monitoring
- [ ] Metrics collection
- [ ] Auto-discovery support
- [ ] Load balancing integration

## Phase 3: Advanced Features (Week 5-6)

### Goals
- Support streaming responses
- Implement advanced sampling parameters
- Add multi-modal support (for LLaVA models)
- Optimize performance

### Tasks

#### 3.1 Streaming Support
```python
async def _handle_chat_stream(self, params: Dict[str, Any]):
    """Handle streaming chat completions."""
    request = self._prepare_request(params)
    request["stream"] = True
    
    async with self._session.post(
        f"{self.base_url}/v1/chat/completions",
        json=request,
        headers=self._get_headers()
    ) as response:
        async for line in response.content:
            if line.startswith(b"data: "):
                data = line[6:].decode("utf-8").strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                yield {
                    "chunk": chunk["choices"][0]["delta"].get("content", ""),
                    "metadata": {"provider": "vllm"}
                }
```

#### 3.2 Advanced Sampling Parameters
```python
# Extended parameter support
VLLM_SAMPLING_PARAMS = {
    "temperature": float,
    "top_p": float,
    "top_k": int,
    "min_p": float,
    "frequency_penalty": float,
    "presence_penalty": float,
    "repetition_penalty": float,
    "length_penalty": float,
    "best_of": int,
    "use_beam_search": bool,
    "early_stopping": bool,
    "stop": list,
    "stop_token_ids": list,
    "ignore_eos": bool,
    "skip_special_tokens": bool,
    "spaces_between_special_tokens": bool,
}
```

#### 3.3 Multi-Modal Support
```python
async def _handle_vision(self, params: Dict[str, Any]) -> Dict[str, Any]:
    """Handle vision model requests (LLaVA, etc)."""
    # Process image inputs
    messages = params.get("messages", [])
    for message in messages:
        if "images" in message:
            # Convert images to base64 if needed
            message["content"] = self._prepare_multimodal_content(
                message["content"],
                message["images"]
            )
    
    # Use chat completions endpoint with multi-modal content
    return await self._handle_chat(params)
```

#### 3.4 Performance Optimizations
```python
class VLLMProvider(HTTPServiceProvider):
    """Enhanced vLLM provider with optimizations."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._connection_pool = None
        self._model_cache = {}
        self._request_queue = asyncio.Queue()
        self._batch_processor = None
    
    async def initialize(self):
        """Initialize with connection pooling and batching."""
        await super().initialize()
        # Setup connection pool
        connector = aiohttp.TCPConnector(
            limit=100,
            limit_per_host=30,
            ttl_dns_cache=300
        )
        self._session = aiohttp.ClientSession(connector=connector)
        
        # Start batch processor for high throughput
        self._batch_processor = asyncio.create_task(self._process_batches())
    
    async def _process_batches(self):
        """Process requests in batches for better throughput."""
        batch = []
        while True:
            try:
                # Collect requests for batching
                timeout = 0.01 if batch else None
                request = await asyncio.wait_for(
                    self._request_queue.get(),
                    timeout=timeout
                )
                batch.append(request)
                
                # Process batch when full or timeout
                if len(batch) >= 10 or timeout:
                    await self._submit_batch(batch)
                    batch = []
            except asyncio.TimeoutError:
                if batch:
                    await self._submit_batch(batch)
                    batch = []
```

### Deliverables
- [ ] Streaming response support
- [ ] Advanced sampling parameters
- [ ] Multi-modal model support
- [ ] Connection pooling
- [ ] Request batching
- [ ] Performance benchmarks

## Phase 4: Production Features (Week 7-8)

### Goals
- Implement monitoring and observability
- Add deployment configurations
- Create migration guides
- Performance testing

### Tasks

#### 4.1 Monitoring Integration
```python
# Prometheus metrics export
class VLLMMetricsExporter:
    """Export vLLM metrics to Prometheus."""
    
    def __init__(self, hub: VLLMHub):
        self.hub = hub
        self.request_counter = Counter(
            'gleitzeit_vllm_requests_total',
            'Total vLLM requests',
            ['model', 'method', 'status']
        )
        self.latency_histogram = Histogram(
            'gleitzeit_vllm_request_duration_seconds',
            'vLLM request latency',
            ['model', 'method']
        )
        self.gpu_utilization = Gauge(
            'gleitzeit_vllm_gpu_utilization',
            'GPU utilization percentage',
            ['instance', 'gpu_id']
        )
```

#### 4.2 Deployment Configurations

##### Docker Compose
```yaml
# docker-compose.vllm.yaml
version: '3.8'

services:
  vllm-llama2-7b:
    image: vllm/vllm-openai:latest
    ports:
      - "8000:8000"
    volumes:
      - ~/.cache/huggingface:/root/.cache/huggingface
    environment:
      - HF_TOKEN=${HF_TOKEN}
    command: >
      --model meta-llama/Llama-2-7b-hf
      --tensor-parallel-size 1
      --gpu-memory-utilization 0.9
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  vllm-mistral-7b:
    image: vllm/vllm-openai:latest
    ports:
      - "8001:8000"
    volumes:
      - ~/.cache/huggingface:/root/.cache/huggingface
    command: >
      --model mistralai/Mistral-7B-Instruct-v0.2
      --tensor-parallel-size 1
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

##### Kubernetes Deployment
```yaml
# k8s/vllm-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vllm-server
spec:
  replicas: 2
  selector:
    matchLabels:
      app: vllm
  template:
    metadata:
      labels:
        app: vllm
    spec:
      containers:
      - name: vllm
        image: vllm/vllm-openai:latest
        ports:
        - containerPort: 8000
        env:
        - name: HF_TOKEN
          valueFrom:
            secretKeyRef:
              name: hf-credentials
              key: token
        args:
        - "--model"
        - "meta-llama/Llama-2-7b-hf"
        - "--tensor-parallel-size"
        - "2"
        resources:
          limits:
            nvidia.com/gpu: 2
---
apiVersion: v1
kind: Service
metadata:
  name: vllm-service
spec:
  selector:
    app: vllm
  ports:
  - port: 8000
    targetPort: 8000
  type: LoadBalancer
```

#### 4.3 Migration Guide
```markdown
# Migration Guide: Ollama to vLLM

## Workflow Changes

### Before (Ollama)
```yaml
tasks:
  - id: "generate"
    method: "llm/chat"
    parameters:
      model: "llama2"
      messages:
        - role: "user"
          content: "Hello"
```

### After (vLLM)
```yaml
tasks:
  - id: "generate"
    method: "llm/chat"
    provider: "vllm"  # Specify provider
    parameters:
      model: "meta-llama/Llama-2-7b-hf"  # Use HF model ID
      messages:
        - role: "user"
          content: "Hello"
```

## Configuration Migration

### Ollama Config
```yaml
ollama:
  discovery_ports: [11434]
  default_model: llama2
```

### vLLM Config
```yaml
vllm:
  discovery_ports: [8000, 8001]
  default_model: meta-llama/Llama-2-7b-hf
  gpu_memory_utilization: 0.9
  tensor_parallel_size: 1
```
```

### Deliverables
- [ ] Monitoring and metrics
- [ ] Docker deployment configs
- [ ] Kubernetes deployment configs
- [ ] Migration documentation
- [ ] Performance comparison report
- [ ] Production checklist

## Testing Strategy

### Unit Tests
```python
# tests/unit/test_vllm_provider.py
import pytest
from gleitzeit.providers.vllm_provider import VLLMProvider

@pytest.mark.asyncio
async def test_vllm_provider_initialization():
    provider = VLLMProvider(base_url="http://localhost:8000")
    assert provider.provider_id == "vllm"
    assert provider.protocol_id == "llm/v1"
    assert "llm/chat" in provider.get_supported_methods()

@pytest.mark.asyncio
async def test_chat_request_transformation():
    provider = VLLMProvider()
    params = {
        "model": "meta-llama/Llama-2-7b-hf",
        "messages": [{"role": "user", "content": "test"}],
        "temperature": 0.5
    }
    request = provider._prepare_request(params)
    assert request["model"] == params["model"]
    assert request["temperature"] == 0.5
```

### Integration Tests
```python
# tests/integration/test_vllm_integration.py
@pytest.mark.integration
@pytest.mark.asyncio
async def test_vllm_workflow_execution():
    async with GleitzeitClient() as client:
        workflow = {
            "name": "vLLM Integration Test",
            "tasks": [{
                "id": "test",
                "method": "llm/chat",
                "provider": "vllm",
                "parameters": {
                    "model": "meta-llama/Llama-2-7b-hf",
                    "messages": [{"role": "user", "content": "Say 'test passed'"}],
                    "max_tokens": 10
                }
            }]
        }
        result = await client.run_workflow(workflow)
        assert "test passed" in result["test"]["response"].lower()
```

### Performance Tests
```python
# tests/performance/test_vllm_performance.py
@pytest.mark.performance
async def test_throughput_comparison():
    # Compare Ollama vs vLLM throughput
    ollama_times = []
    vllm_times = []
    
    for _ in range(100):
        # Test Ollama
        start = time.time()
        await client.chat("Test prompt", provider="ollama")
        ollama_times.append(time.time() - start)
        
        # Test vLLM
        start = time.time()
        await client.chat("Test prompt", provider="vllm")
        vllm_times.append(time.time() - start)
    
    assert np.mean(vllm_times) < np.mean(ollama_times) * 0.5  # Expect 2x speedup
```

## Success Metrics

### Performance Targets
- **Throughput**: 2-5x improvement over Ollama for batch processing
- **Latency**: <100ms p50, <500ms p99 for standard requests
- **GPU Utilization**: >80% during active processing
- **Concurrent Requests**: Support 100+ simultaneous requests

### Adoption Metrics
- Successfully migrate 3 production workflows
- Document 5+ example use cases
- Achieve 90% test coverage
- Zero breaking changes to existing workflows

## Risk Mitigation

### Technical Risks
1. **GPU Memory Management**
   - Mitigation: Implement memory monitoring and automatic model unloading
   
2. **Model Compatibility**
   - Mitigation: Maintain compatibility matrix and automated testing

3. **Network Latency**
   - Mitigation: Connection pooling and request batching

### Operational Risks
1. **Resource Costs**
   - Mitigation: Implement resource quotas and usage monitoring

2. **Migration Complexity**
   - Mitigation: Provide automated migration tools and fallback options

## Timeline Summary

| Phase | Duration | Key Deliverables |
|-------|----------|------------------|
| Phase 1: Basic Provider | Week 1-2 | VLLMProvider, basic tests |
| Phase 2: Resource Management | Week 3-4 | VLLMHub, lifecycle management |
| Phase 3: Advanced Features | Week 5-6 | Streaming, multi-modal, optimization |
| Phase 4: Production | Week 7-8 | Monitoring, deployment, migration |

## Next Steps

1. **Review and Approval**: Get stakeholder feedback on roadmap
2. **Environment Setup**: Prepare development environment with GPU access
3. **Prototype**: Build proof-of-concept VLLMProvider
4. **Benchmarking**: Establish performance baselines
5. **Implementation**: Begin Phase 1 development

## References

- [vLLM Documentation](https://docs.vllm.ai/)
- [vLLM GitHub Repository](https://github.com/vllm-project/vllm)
- [OpenAI API Specification](https://platform.openai.com/docs/api-reference)
- [Gleitzeit Architecture Docs](../docs/architecture.md)