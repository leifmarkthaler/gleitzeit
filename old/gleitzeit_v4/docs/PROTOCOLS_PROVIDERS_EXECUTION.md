# Protocols, Providers, and Execution Architecture for Gleitzeit V4

## Overview

Gleitzeit V4 implements a sophisticated protocol-based execution system where tasks are routed to appropriate providers based on protocol specifications. This document details the complete architecture of protocols, provider management, and task execution.

## Architecture Overview

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│    Protocol     │───▶│    Provider      │───▶│   Execution     │
│  Specification  │    │    Registry      │    │    Engine       │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                        │                        │
         ▼                        ▼                        ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│ Method Schema   │    │ Provider Pool    │    │ Task Execution  │
│ Validation      │    │ Management       │    │ Coordination    │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                        │                        │
         ▼                        ▼                        ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│ Parameter       │    │ Health           │    │ Result          │
│ Substitution    │    │ Monitoring       │    │ Processing      │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

## Protocol System

### Protocol Specification (`core/protocol.py`)

Protocols define the contract between the execution system and providers, specifying available methods, parameters, and validation rules.

#### Protocol Structure

```python
@dataclass
class ProtocolSpec:
    name: str                           # Protocol identifier
    version: str                        # Version (e.g., "v1.2.0")
    description: Optional[str]          # Human-readable description
    extends: Optional[str]              # Parent protocol inheritance
    methods: Dict[str, MethodSpec]      # Available methods
    author: Optional[str]               # Protocol author
    license: Optional[str]              # License information
    documentation_url: Optional[str]    # Documentation URL
    tags: List[str]                     # Categorization tags
    
    @property
    def protocol_id(self) -> str:
        return f"{self.name}/{self.version}"
```

#### Method Specification

```python
@dataclass  
class MethodSpec:
    name: str                                    # Method name
    description: Optional[str]                   # Method description
    params_schema: Dict[str, ParameterSpec]      # Parameter definitions
    returns_schema: Optional[ParameterSpec]      # Return value schema
    examples: List[Dict[str, Any]]               # Usage examples
    deprecated: bool = False                     # Deprecation flag
    
    # Method metadata
    timeout_seconds: Optional[int] = None        # Default timeout
    retry_policy: Optional[RetryPolicy] = None   # Retry configuration
    resource_requirements: Optional[ResourceRequirements] = None
    security_requirements: Optional[SecurityRequirements] = None
```

#### Parameter Specification

```python
@dataclass
class ParameterSpec:
    type: Union[ParameterType, List[ParameterType]]  # Data type(s)
    description: Optional[str]                       # Parameter description
    required: bool = True                            # Required flag
    default: Optional[Any] = None                    # Default value
    
    # Validation constraints
    enum: Optional[List[Any]] = None                 # Allowed values
    minimum: Optional[Union[int, float]] = None      # Min value (numbers)
    maximum: Optional[Union[int, float]] = None      # Max value (numbers)
    min_length: Optional[int] = None                 # Min length (strings/arrays)
    max_length: Optional[int] = None                 # Max length (strings/arrays)
    pattern: Optional[str] = None                    # Regex pattern (strings)
    
    # Complex types
    items: Optional["ParameterSpec"] = None          # Array item schema
    properties: Optional[Dict[str, "ParameterSpec"]] = None  # Object properties
    additional_properties: bool = True               # Allow extra properties
```

### Built-in Protocol Types

#### 1. Python Execution Protocol (`protocols/python_protocol.py`)

```python
# Python Protocol v1.0
python_protocol = ProtocolSpec(
    name="python",
    version="v1.0",
    description="Python code execution protocol",
    methods={
        "execute": MethodSpec(
            name="execute",
            description="Execute Python code",
            params_schema={
                "code": ParameterSpec(
                    type=ParameterType.STRING,
                    description="Python code to execute",
                    required=True,
                    min_length=1,
                    max_length=10000
                ),
                "timeout": ParameterSpec(
                    type=ParameterType.INTEGER,
                    description="Execution timeout in seconds",
                    required=False,
                    default=30,
                    minimum=1,
                    maximum=3600
                ),
                "environment": ParameterSpec(
                    type=ParameterType.OBJECT,
                    description="Environment variables",
                    required=False,
                    additional_properties=True
                ),
                "imports": ParameterSpec(
                    type=ParameterType.ARRAY,
                    description="Modules to import",
                    required=False,
                    items=ParameterSpec(type=ParameterType.STRING)
                )
            },
            returns_schema=ParameterSpec(
                type=ParameterType.OBJECT,
                properties={
                    "result": ParameterSpec(type=ParameterType.STRING),
                    "stdout": ParameterSpec(type=ParameterType.STRING),
                    "stderr": ParameterSpec(type=ParameterType.STRING),
                    "execution_time": ParameterSpec(type=ParameterType.NUMBER),
                    "exit_code": ParameterSpec(type=ParameterType.INTEGER)
                }
            ),
            examples=[
                {
                    "params": {
                        "code": "print('Hello, World!')",
                        "timeout": 10
                    },
                    "result": {
                        "result": "Hello, World!\n",
                        "stdout": "Hello, World!\n", 
                        "stderr": "",
                        "execution_time": 0.001,
                        "exit_code": 0
                    }
                }
            ]
        ),
        "validate": MethodSpec(
            name="validate",
            description="Validate Python code syntax",
            params_schema={
                "code": ParameterSpec(
                    type=ParameterType.STRING,
                    required=True
                )
            },
            returns_schema=ParameterSpec(
                type=ParameterType.OBJECT,
                properties={
                    "is_valid": ParameterSpec(type=ParameterType.BOOLEAN),
                    "errors": ParameterSpec(
                        type=ParameterType.ARRAY,
                        items=ParameterSpec(type=ParameterType.STRING)
                    )
                }
            )
        )
    }
)
```

#### 2. LLM Protocol (`protocols/llm_protocol.py`)

```python
# LLM Protocol v1.0
llm_protocol = ProtocolSpec(
    name="llm",
    version="v1.0", 
    description="Large Language Model interaction protocol",
    methods={
        "chat": MethodSpec(
            name="chat",
            description="Chat with language model",
            params_schema={
                "messages": ParameterSpec(
                    type=ParameterType.ARRAY,
                    description="Conversation messages",
                    required=True,
                    min_length=1,
                    items=ParameterSpec(
                        type=ParameterType.OBJECT,
                        properties={
                            "role": ParameterSpec(
                                type=ParameterType.STRING,
                                enum=["system", "user", "assistant"],
                                required=True
                            ),
                            "content": ParameterSpec(
                                type=ParameterType.STRING,
                                required=True,
                                min_length=1
                            )
                        }
                    )
                ),
                "model": ParameterSpec(
                    type=ParameterType.STRING,
                    description="Model to use",
                    required=False,
                    default="llama3.2"
                ),
                "temperature": ParameterSpec(
                    type=ParameterType.NUMBER,
                    description="Sampling temperature",
                    required=False,
                    default=0.7,
                    minimum=0.0,
                    maximum=2.0
                ),
                "max_tokens": ParameterSpec(
                    type=ParameterType.INTEGER,
                    description="Maximum tokens to generate",
                    required=False,
                    minimum=1,
                    maximum=32768
                ),
                "stream": ParameterSpec(
                    type=ParameterType.BOOLEAN,
                    description="Stream response",
                    required=False,
                    default=False
                )
            },
            returns_schema=ParameterSpec(
                type=ParameterType.OBJECT,
                properties={
                    "response": ParameterSpec(type=ParameterType.STRING),
                    "model": ParameterSpec(type=ParameterType.STRING),
                    "tokens_used": ParameterSpec(type=ParameterType.INTEGER),
                    "finish_reason": ParameterSpec(type=ParameterType.STRING),
                    "metadata": ParameterSpec(type=ParameterType.OBJECT)
                }
            )
        ),
        "embed": MethodSpec(
            name="embed",
            description="Generate embeddings for text",
            params_schema={
                "text": ParameterSpec(
                    type=ParameterType.STRING,
                    required=True,
                    min_length=1
                ),
                "model": ParameterSpec(
                    type=ParameterType.STRING,
                    required=False,
                    default="nomic-embed-text"
                )
            },
            returns_schema=ParameterSpec(
                type=ParameterType.OBJECT,
                properties={
                    "embedding": ParameterSpec(
                        type=ParameterType.ARRAY,
                        items=ParameterSpec(type=ParameterType.NUMBER)
                    ),
                    "model": ParameterSpec(type=ParameterType.STRING),
                    "dimensions": ParameterSpec(type=ParameterType.INTEGER)
                }
            )
        )
    }
)
```

### Protocol Registry

```python
class ProtocolRegistry:
    """Central registry for protocol management"""
    
    def __init__(self):
        self._protocols: Dict[str, ProtocolSpec] = {}
        self._method_index: Dict[str, List[str]] = {}  # method -> protocol_ids
        
    def register(self, protocol: ProtocolSpec) -> None:
        """Register a protocol specification"""
        protocol_id = protocol.protocol_id
        self._protocols[protocol_id] = protocol
        
        # Update method index
        for method_name in protocol.methods.keys():
            if method_name not in self._method_index:
                self._method_index[method_name] = []
            self._method_index[method_name].append(protocol_id)
        
        logger.info(f"Registered protocol: {protocol_id}")
    
    def validate_task(self, protocol_id: str, method: str, 
                     params: Union[Dict[str, Any], List[Any]]) -> None:
        """Validate task parameters against protocol"""
        protocol = self.get(protocol_id)
        if not protocol:
            raise ProtocolNotFoundError(f"Protocol not found: {protocol_id}")
        
        method_spec = protocol.get_method(method)
        if not method_spec:
            raise MethodNotFoundError(f"Method '{method}' not found in {protocol_id}")
        
        # Validate parameters
        method_spec.validate_params(params)
    
    def find_compatible_protocols(self, method: str) -> List[ProtocolSpec]:
        """Find all protocols that support a method"""
        protocol_ids = self._method_index.get(method, [])
        return [self._protocols[pid] for pid in protocol_ids]
```

## Provider System

### Provider Base Class (`providers/base.py`)

```python
class BaseProvider(ABC):
    """Abstract base class for all providers"""
    
    def __init__(self, provider_id: str, config: Dict[str, Any]):
        self.provider_id = provider_id
        self.config = config
        self._health_status = HealthStatus.UNKNOWN
        self._capabilities: Set[str] = set()
        self._supported_protocols: Set[str] = set()
        
    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the provider"""
        pass
    
    @abstractmethod
    async def execute_task(self, task: Task) -> TaskResult:
        """Execute a task and return result"""
        pass
    
    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """Check provider health"""
        pass
    
    @abstractmethod
    async def shutdown(self) -> None:
        """Gracefully shutdown the provider"""
        pass
    
    def supports_protocol(self, protocol_id: str) -> bool:
        """Check if provider supports a protocol"""
        return protocol_id in self._supported_protocols
    
    def supports_method(self, protocol_id: str, method: str) -> bool:
        """Check if provider supports a specific method"""
        capability = f"{protocol_id}:{method}"
        return capability in self._capabilities
```

### Provider Implementations

#### 1. Python Function Provider (`providers/python_function_provider.py`)

```python
class PythonFunctionProvider(BaseProvider):
    """Provider for executing Python functions"""
    
    def __init__(self, provider_id: str, config: Dict[str, Any]):
        super().__init__(provider_id, config)
        self._supported_protocols = {"python/v1.0"}
        self._capabilities = {
            "python/v1.0:execute",
            "python/v1.0:validate"
        }
        self._executor_pool: Optional[ProcessPoolExecutor] = None
        
    async def initialize(self) -> None:
        """Initialize Python execution environment"""
        max_workers = self.config.get("max_workers", 4)
        self._executor_pool = ProcessPoolExecutor(
            max_workers=max_workers,
            initializer=self._init_worker,
            initargs=(self.config,)
        )
        
        # Test execution environment
        test_code = "print('Provider initialized')"
        await self._execute_python_code(test_code, timeout=5)
        
        self._health_status = HealthStatus.HEALTHY
        logger.info(f"Python provider {self.provider_id} initialized")
    
    async def execute_task(self, task: Task) -> TaskResult:
        """Execute Python task"""
        start_time = datetime.utcnow()
        
        try:
            # Validate task
            if task.protocol != "python/v1.0":
                raise UnsupportedProtocolError(f"Unsupported protocol: {task.protocol}")
            
            if task.method == "execute":
                result = await self._execute_python_code(
                    task.parameters["code"],
                    timeout=task.parameters.get("timeout", 30),
                    environment=task.parameters.get("environment", {}),
                    imports=task.parameters.get("imports", [])
                )
            elif task.method == "validate":
                result = await self._validate_python_code(task.parameters["code"])
            else:
                raise UnsupportedMethodError(f"Unsupported method: {task.method}")
            
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            
            return TaskResult(
                task_id=task.id,
                status=TaskStatus.COMPLETED,
                result=result,
                execution_time=execution_time,
                provider_id=self.provider_id,
                completed_at=datetime.utcnow()
            )
            
        except Exception as e:
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            return TaskResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                error=str(e),
                execution_time=execution_time,
                provider_id=self.provider_id,
                completed_at=datetime.utcnow()
            )
    
    async def _execute_python_code(self, code: str, timeout: int = 30,
                                 environment: Dict[str, Any] = None,
                                 imports: List[str] = None) -> Dict[str, Any]:
        """Execute Python code in isolated environment"""
        
        # Prepare execution context
        exec_context = {
            "code": code,
            "timeout": timeout,
            "environment": environment or {},
            "imports": imports or [],
            "provider_id": self.provider_id
        }
        
        # Execute in process pool for isolation
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            self._executor_pool,
            self._run_python_code,
            exec_context
        )
        
        return result
    
    @staticmethod
    def _run_python_code(context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Python code in subprocess (static method for pickling)"""
        import subprocess
        import json
        import tempfile
        import os
        
        code = context["code"]
        timeout = context["timeout"]
        environment = context["environment"]
        imports = context["imports"]
        
        # Prepare execution script
        import_statements = "\n".join(f"import {imp}" for imp in imports)
        full_code = f"""
import sys
import traceback
import time
import json

# Add imports
{import_statements}

# Set environment variables
{repr(environment)}
for key, value in {repr(environment)}.items():
    os.environ[key] = str(value)

start_time = time.time()
stdout_capture = []
stderr_capture = []

class OutputCapture:
    def __init__(self, target_list):
        self.target_list = target_list
    
    def write(self, text):
        self.target_list.append(text)
    
    def flush(self):
        pass

# Redirect stdout/stderr
old_stdout = sys.stdout
old_stderr = sys.stderr
sys.stdout = OutputCapture(stdout_capture)
sys.stderr = OutputCapture(stderr_capture)

try:
    # Execute user code
    exec_globals = {{'__name__': '__main__'}}
    exec_locals = {{}}
    
    exec(compile({repr(code)}, '<string>', 'exec'), exec_globals, exec_locals)
    
    # Capture result (last expression if any)
    result = exec_locals.get('result', None)
    exit_code = 0
    
except Exception as e:
    result = f"Error: {{e}}"
    traceback.print_exc()
    exit_code = 1

finally:
    sys.stdout = old_stdout
    sys.stderr = old_stderr
    
execution_time = time.time() - start_time

# Prepare result
output_result = {{
    "result": str(result) if result is not None else "",
    "stdout": "".join(stdout_capture),
    "stderr": "".join(stderr_capture),
    "execution_time": execution_time,
    "exit_code": exit_code
}}

print(json.dumps(output_result))
"""
        
        # Write to temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(full_code)
            temp_file = f.name
        
        try:
            # Execute with timeout
            result = subprocess.run(
                [sys.executable, temp_file],
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, **environment}
            )
            
            if result.returncode == 0:
                return json.loads(result.stdout.strip())
            else:
                return {
                    "result": "",
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "execution_time": 0,
                    "exit_code": result.returncode
                }
                
        except subprocess.TimeoutExpired:
            return {
                "result": "",
                "stdout": "",
                "stderr": f"Execution timed out after {timeout} seconds",
                "execution_time": timeout,
                "exit_code": -1
            }
        finally:
            os.unlink(temp_file)
```

#### 2. Ollama LLM Provider (`providers/ollama_provider.py`)

```python
class OllamaProvider(BaseProvider):
    """Provider for Ollama LLM services"""
    
    def __init__(self, provider_id: str, config: Dict[str, Any]):
        super().__init__(provider_id, config)
        self._supported_protocols = {"llm/v1.0"}
        self._capabilities = {
            "llm/v1.0:chat",
            "llm/v1.0:embed"
        }
        self.base_url = config.get("base_url", "http://localhost:11434")
        self.default_model = config.get("default_model", "llama3.2")
        self._session: Optional[aiohttp.ClientSession] = None
        
    async def initialize(self) -> None:
        """Initialize Ollama connection"""
        connector = aiohttp.TCPConnector(
            limit=self.config.get("max_connections", 10),
            ttl_dns_cache=300,
            use_dns_cache=True
        )
        
        timeout = aiohttp.ClientTimeout(
            total=self.config.get("timeout", 300),
            connect=self.config.get("connect_timeout", 10)
        )
        
        self._session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={"User-Agent": f"Gleitzeit-V4-{self.provider_id}"}
        )
        
        # Test connection
        await self._health_check()
        
        self._health_status = HealthStatus.HEALTHY
        logger.info(f"Ollama provider {self.provider_id} initialized")
    
    async def execute_task(self, task: Task) -> TaskResult:
        """Execute LLM task"""
        start_time = datetime.utcnow()
        
        try:
            if task.protocol != "llm/v1.0":
                raise UnsupportedProtocolError(f"Unsupported protocol: {task.protocol}")
            
            if task.method == "chat":
                result = await self._chat(task.parameters)
            elif task.method == "embed":
                result = await self._embed(task.parameters)
            else:
                raise UnsupportedMethodError(f"Unsupported method: {task.method}")
            
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            
            return TaskResult(
                task_id=task.id,
                status=TaskStatus.COMPLETED,
                result=result,
                execution_time=execution_time,
                provider_id=self.provider_id,
                completed_at=datetime.utcnow()
            )
            
        except Exception as e:
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            return TaskResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                error=str(e),
                execution_time=execution_time,
                provider_id=self.provider_id,
                completed_at=datetime.utcnow()
            )
    
    async def _chat(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute chat completion"""
        model = params.get("model", self.default_model)
        messages = params["messages"]
        temperature = params.get("temperature", 0.7)
        max_tokens = params.get("max_tokens")
        stream = params.get("stream", False)
        
        # Prepare request
        payload = {
            "model": model,
            "messages": messages,
            "options": {
                "temperature": temperature
            },
            "stream": stream
        }
        
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        
        # Make request
        async with self._session.post(
            f"{self.base_url}/api/chat",
            json=payload
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                raise ProviderError(f"Ollama API error: {response.status} - {error_text}")
            
            if stream:
                # Handle streaming response
                content_parts = []
                async for line in response.content:
                    if line:
                        chunk = json.loads(line.decode())
                        if chunk.get("message", {}).get("content"):
                            content_parts.append(chunk["message"]["content"])
                        
                        if chunk.get("done", False):
                            break
                
                response_text = "".join(content_parts)
                tokens_used = chunk.get("eval_count", 0) + chunk.get("prompt_eval_count", 0)
                finish_reason = "stop" if chunk.get("done") else "incomplete"
                
            else:
                # Handle non-streaming response
                result = await response.json()
                response_text = result["message"]["content"]
                tokens_used = result.get("eval_count", 0) + result.get("prompt_eval_count", 0)
                finish_reason = "stop"
        
        return {
            "response": response_text,
            "model": model,
            "tokens_used": tokens_used,
            "finish_reason": finish_reason,
            "metadata": {
                "provider": "ollama",
                "provider_id": self.provider_id,
                "base_url": self.base_url
            }
        }
    
    async def _embed(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate text embeddings"""
        model = params.get("model", "nomic-embed-text")
        text = params["text"]
        
        payload = {
            "model": model,
            "prompt": text
        }
        
        async with self._session.post(
            f"{self.base_url}/api/embeddings",
            json=payload
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                raise ProviderError(f"Ollama embedding error: {response.status} - {error_text}")
            
            result = await response.json()
            
            return {
                "embedding": result["embedding"],
                "model": model,
                "dimensions": len(result["embedding"]),
                "metadata": {
                    "provider": "ollama", 
                    "provider_id": self.provider_id
                }
            }
```

### Provider Registry (`registry.py`)

```python
class ProtocolProviderRegistry:
    """Registry for managing protocol providers"""
    
    def __init__(self):
        self._providers: Dict[str, BaseProvider] = {}
        self._protocol_providers: Dict[str, Set[str]] = {}  # protocol -> provider_ids
        self._method_providers: Dict[str, Set[str]] = {}    # method -> provider_ids
        self._provider_health: Dict[str, HealthStatus] = {}
        self._load_balancer = RoundRobinLoadBalancer()
        
    async def register_provider(self, provider: BaseProvider) -> None:
        """Register a provider"""
        provider_id = provider.provider_id
        
        # Initialize provider
        await provider.initialize()
        
        # Store provider
        self._providers[provider_id] = provider
        
        # Index by protocols and methods
        for protocol_id in provider._supported_protocols:
            if protocol_id not in self._protocol_providers:
                self._protocol_providers[protocol_id] = set()
            self._protocol_providers[protocol_id].add(provider_id)
        
        for capability in provider._capabilities:
            if ":" in capability:
                protocol_id, method = capability.split(":", 1)
                method_key = f"{protocol_id}:{method}"
                if method_key not in self._method_providers:
                    self._method_providers[method_key] = set()
                self._method_providers[method_key].add(provider_id)
        
        # Initial health check
        health = await provider.health_check()
        self._provider_health[provider_id] = health
        
        logger.info(f"Registered provider: {provider_id}")
    
    async def get_provider_for_task(self, task: Task) -> Optional[BaseProvider]:
        """Get best provider for a task"""
        method_key = f"{task.protocol}:{task.method}"
        
        # Get available providers for this method
        provider_ids = self._method_providers.get(method_key, set())
        if not provider_ids:
            return None
        
        # Filter by health status
        healthy_providers = [
            pid for pid in provider_ids
            if self._provider_health.get(pid) == HealthStatus.HEALTHY
        ]
        
        if not healthy_providers:
            # No healthy providers, try degraded ones
            degraded_providers = [
                pid for pid in provider_ids
                if self._provider_health.get(pid) == HealthStatus.DEGRADED
            ]
            healthy_providers = degraded_providers
        
        if not healthy_providers:
            return None
        
        # Use load balancer to select provider
        selected_id = self._load_balancer.select(healthy_providers, task)
        return self._providers.get(selected_id)
    
    async def health_check_all(self) -> Dict[str, HealthStatus]:
        """Perform health checks on all providers"""
        health_results = {}
        
        for provider_id, provider in self._providers.items():
            try:
                health = await asyncio.wait_for(
                    provider.health_check(),
                    timeout=10.0
                )
                health_results[provider_id] = health
                self._provider_health[provider_id] = health
            except asyncio.TimeoutError:
                health_results[provider_id] = HealthStatus.UNHEALTHY
                self._provider_health[provider_id] = HealthStatus.UNHEALTHY
            except Exception as e:
                logger.error(f"Health check failed for {provider_id}: {e}")
                health_results[provider_id] = HealthStatus.UNHEALTHY
                self._provider_health[provider_id] = HealthStatus.UNHEALTHY
        
        return health_results
```

## Execution Engine (`core/execution_engine.py`)

### Task Execution Coordination

```python
class ExecutionEngine:
    """Central execution coordinator"""
    
    def __init__(self, 
                 registry: ProtocolProviderRegistry,
                 queue_manager: QueueManager,
                 dependency_resolver: DependencyResolver,
                 persistence: PersistenceBackend,
                 max_concurrent_tasks: int = 10):
        
        self.registry = registry
        self.queue_manager = queue_manager
        self.dependency_resolver = dependency_resolver
        self.persistence = persistence
        self.max_concurrent_tasks = max_concurrent_tasks
        
        # Task execution state
        self.running = False
        self.active_tasks: Dict[str, Task] = {}
        self.task_results: Dict[str, TaskResult] = {}
        self.execution_semaphore = asyncio.Semaphore(max_concurrent_tasks)
        
        # Event handling
        self.event_handlers: Dict[str, List[Callable]] = {}
        
        # Metrics
        self.stats = ExecutionStats()
        
    async def start(self) -> None:
        """Start the execution engine"""
        if self.running:
            return
        
        self.running = True
        
        # Start background tasks
        self._execution_task = asyncio.create_task(self._execution_loop())
        self._health_task = asyncio.create_task(self._health_check_loop())
        
        await self.emit_event("engine:started", {
            "max_concurrent_tasks": self.max_concurrent_tasks,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        logger.info("Execution engine started")
    
    async def _execution_loop(self) -> None:
        """Main execution loop"""
        while self.running:
            try:
                # Check if we can process more tasks
                if len(self.active_tasks) >= self.max_concurrent_tasks:
                    await asyncio.sleep(0.1)
                    continue
                
                # Get next available task
                task = await self.queue_manager.get_next_task()
                if not task:
                    await asyncio.sleep(0.5)
                    continue
                
                # Process task asynchronously
                asyncio.create_task(self._execute_task(task))
                
            except Exception as e:
                logger.error(f"Error in execution loop: {e}")
                await asyncio.sleep(1.0)
    
    async def _execute_task(self, task: Task) -> None:
        """Execute a single task"""
        async with self.execution_semaphore:
            task_id = task.id
            
            try:
                # Mark task as executing
                self.active_tasks[task_id] = task
                task.status = TaskStatus.EXECUTING
                task.started_at = datetime.utcnow()
                
                await self.persistence.update_task_status(task_id, TaskStatus.EXECUTING)
                
                # Emit task started event
                await self.emit_event("task:started", {
                    "task_id": task_id,
                    "workflow_id": task.workflow_id,
                    "protocol": task.protocol,
                    "method": task.method,
                    "provider_requested": True
                })
                
                # Get provider for task
                provider = await self.registry.get_provider_for_task(task)
                if not provider:
                    raise ProviderNotFoundError(
                        f"No available provider for {task.protocol}:{task.method}"
                    )
                
                # Execute task
                result = await provider.execute_task(task)
                
                # Process result
                await self._handle_task_completion(task, result)
                
            except Exception as e:
                # Handle task failure
                await self._handle_task_failure(task, e)
                
            finally:
                # Clean up
                self.active_tasks.pop(task_id, None)
    
    async def _handle_task_completion(self, task: Task, result: TaskResult) -> None:
        """Handle successful task completion"""
        task_id = task.id
        
        # Store result
        self.task_results[task_id] = result
        await self.persistence.store_task_result(result)
        
        # Update task status
        task.status = TaskStatus.COMPLETED
        task.completed_at = result.completed_at
        await self.persistence.update_task_status(task_id, TaskStatus.COMPLETED, result)
        
        # Emit completion event
        await self.emit_event("task:completed", {
            "task_id": task_id,
            "workflow_id": task.workflow_id,
            "execution_time": result.execution_time,
            "provider_id": result.provider_id,
            "result_size": len(str(result.result)) if result.result else 0
        })
        
        # Update statistics
        self.stats.tasks_processed += 1
        self.stats.tasks_succeeded += 1
        
        # Resolve dependent tasks
        await self._resolve_dependent_tasks(task_id)
        
        logger.info(f"Task {task_id} completed successfully")
    
    async def _handle_task_failure(self, task: Task, error: Exception) -> None:
        """Handle task failure"""
        task_id = task.id
        error_message = str(error)
        
        # Determine if task should be retried
        is_retryable = self._is_retryable_error(error)
        
        if is_retryable and task.attempt_count < task.max_retries:
            # Schedule retry
            await self._schedule_retry(task, error_message)
        else:
            # Mark as permanently failed
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.utcnow()
            
            result = TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error=error_message,
                execution_time=0,
                provider_id=None,
                completed_at=datetime.utcnow()
            )
            
            await self.persistence.update_task_status(task_id, TaskStatus.FAILED, result)
            
            # Emit failure event
            await self.emit_event("task:failed", {
                "task_id": task_id,
                "workflow_id": task.workflow_id,
                "error_message": error_message,
                "is_retryable": is_retryable,
                "attempt_count": task.attempt_count,
                "max_retries": task.max_retries
            })
            
            # Update statistics
            self.stats.tasks_processed += 1
            self.stats.tasks_failed += 1
            
            # Handle workflow failure if critical task
            await self._check_workflow_failure(task.workflow_id, task_id)
        
        logger.error(f"Task {task_id} failed: {error_message}")
    
    async def _resolve_dependent_tasks(self, completed_task_id: str) -> None:
        """Resolve tasks that depend on the completed task"""
        # Get dependent tasks
        dependent_tasks = await self.dependency_resolver.get_dependent_tasks(completed_task_id)
        
        for dep_task_id in dependent_tasks:
            # Check if all dependencies are satisfied
            can_execute = await self.dependency_resolver.can_execute_task(dep_task_id)
            
            if can_execute:
                # Resolve parameters with dependency results
                resolved_task = await self.dependency_resolver.resolve_task_parameters(dep_task_id)
                
                # Queue the resolved task
                await self.queue_manager.enqueue_task(resolved_task)
                
                logger.info(f"Queued dependent task: {dep_task_id}")
```

### Load Balancing Strategies

```python
class LoadBalancingStrategy(ABC):
    """Abstract base for load balancing strategies"""
    
    @abstractmethod
    def select(self, providers: List[str], task: Task) -> str:
        """Select a provider for the task"""
        pass

class RoundRobinLoadBalancer(LoadBalancingStrategy):
    """Round-robin load balancing"""
    
    def __init__(self):
        self._counters: Dict[str, int] = {}
    
    def select(self, providers: List[str], task: Task) -> str:
        """Select provider using round-robin"""
        method_key = f"{task.protocol}:{task.method}"
        
        if method_key not in self._counters:
            self._counters[method_key] = 0
        
        index = self._counters[method_key] % len(providers)
        self._counters[method_key] += 1
        
        return providers[index]

class WeightedLoadBalancer(LoadBalancingStrategy):
    """Weighted load balancing based on provider capacity"""
    
    def __init__(self, weights: Dict[str, float]):
        self.weights = weights
        self._last_selected: Dict[str, str] = {}
    
    def select(self, providers: List[str], task: Task) -> str:
        """Select provider using weighted random selection"""
        import random
        
        # Get weights for available providers
        provider_weights = [self.weights.get(pid, 1.0) for pid in providers]
        
        # Weighted random selection
        total_weight = sum(provider_weights)
        r = random.uniform(0, total_weight)
        
        cumulative = 0
        for i, weight in enumerate(provider_weights):
            cumulative += weight
            if r <= cumulative:
                return providers[i]
        
        return providers[-1]  # Fallback

class LeastConnectionsLoadBalancer(LoadBalancingStrategy):
    """Load balancing based on current connection count"""
    
    def __init__(self, registry: ProtocolProviderRegistry):
        self.registry = registry
    
    def select(self, providers: List[str], task: Task) -> str:
        """Select provider with least active connections"""
        min_connections = float('inf')
        selected_provider = providers[0]
        
        for provider_id in providers:
            provider = self.registry._providers.get(provider_id)
            if provider:
                # Get current connection count (implementation-specific)
                connections = getattr(provider, 'active_connections', 0)
                if connections < min_connections:
                    min_connections = connections
                    selected_provider = provider_id
        
        return selected_provider
```

### Resource Management

```python
@dataclass
class ResourceRequirements:
    """Resource requirements for task execution"""
    cpu_cores: Optional[float] = None       # CPU cores needed
    memory_mb: Optional[int] = None         # Memory in MB
    gpu_memory_mb: Optional[int] = None     # GPU memory in MB
    disk_space_mb: Optional[int] = None     # Temporary disk space
    network_bandwidth_mbps: Optional[int] = None  # Network bandwidth
    execution_timeout: Optional[int] = None # Maximum execution time

class ResourceManager:
    """Manages resource allocation for task execution"""
    
    def __init__(self, total_resources: ResourceRequirements):
        self.total_resources = total_resources
        self.allocated_resources = ResourceRequirements()
        self._allocation_lock = asyncio.Lock()
    
    async def can_allocate(self, requirements: ResourceRequirements) -> bool:
        """Check if resources can be allocated"""
        async with self._allocation_lock:
            # Check each resource type
            if requirements.cpu_cores:
                allocated_cpu = self.allocated_resources.cpu_cores or 0
                total_cpu = self.total_resources.cpu_cores or float('inf')
                if allocated_cpu + requirements.cpu_cores > total_cpu:
                    return False
            
            if requirements.memory_mb:
                allocated_memory = self.allocated_resources.memory_mb or 0
                total_memory = self.total_resources.memory_mb or float('inf')
                if allocated_memory + requirements.memory_mb > total_memory:
                    return False
            
            # Check other resources similarly...
            
            return True
    
    async def allocate_resources(self, requirements: ResourceRequirements) -> str:
        """Allocate resources and return allocation ID"""
        allocation_id = str(uuid.uuid4())
        
        async with self._allocation_lock:
            # Update allocated resources
            if requirements.cpu_cores:
                current_cpu = self.allocated_resources.cpu_cores or 0
                self.allocated_resources.cpu_cores = current_cpu + requirements.cpu_cores
            
            if requirements.memory_mb:
                current_memory = self.allocated_resources.memory_mb or 0
                self.allocated_resources.memory_mb = current_memory + requirements.memory_mb
            
            # Store allocation for later release
            self._allocations[allocation_id] = requirements
        
        return allocation_id
    
    async def release_resources(self, allocation_id: str) -> None:
        """Release allocated resources"""
        async with self._allocation_lock:
            if allocation_id in self._allocations:
                requirements = self._allocations.pop(allocation_id)
                
                # Release resources
                if requirements.cpu_cores:
                    self.allocated_resources.cpu_cores -= requirements.cpu_cores
                
                if requirements.memory_mb:
                    self.allocated_resources.memory_mb -= requirements.memory_mb
```

### Security and Sandboxing

```python
class SecurityManager:
    """Manages security policies for task execution"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.sandbox_enabled = config.get("sandbox_enabled", True)
        self.allowed_modules = set(config.get("allowed_modules", []))
        self.blocked_modules = set(config.get("blocked_modules", ["os", "subprocess", "sys"]))
        
    async def validate_task_security(self, task: Task) -> None:
        """Validate task against security policies"""
        if task.protocol == "python/v1.0" and task.method == "execute":
            await self._validate_python_code_security(task.parameters["code"])
    
    async def _validate_python_code_security(self, code: str) -> None:
        """Validate Python code for security issues"""
        import ast
        
        try:
            # Parse code to AST
            tree = ast.parse(code)
            
            # Check for dangerous imports
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in self.blocked_modules:
                            raise SecurityError(f"Blocked module import: {alias.name}")
                
                elif isinstance(node, ast.ImportFrom):
                    if node.module in self.blocked_modules:
                        raise SecurityError(f"Blocked module import: {node.module}")
                
                # Check for dangerous function calls
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        if node.func.id in ["eval", "exec", "__import__"]:
                            raise SecurityError(f"Dangerous function call: {node.func.id}")
        
        except SyntaxError:
            raise SecurityError("Invalid Python syntax")

class SandboxedExecutor:
    """Executes tasks in sandboxed environments"""
    
    def __init__(self, sandbox_type: str = "docker"):
        self.sandbox_type = sandbox_type
        
    async def execute_in_sandbox(self, task: Task, provider: BaseProvider) -> TaskResult:
        """Execute task in sandboxed environment"""
        if self.sandbox_type == "docker":
            return await self._execute_in_docker(task, provider)
        elif self.sandbox_type == "chroot":
            return await self._execute_in_chroot(task, provider)
        else:
            # Fallback to regular execution
            return await provider.execute_task(task)
    
    async def _execute_in_docker(self, task: Task, provider: BaseProvider) -> TaskResult:
        """Execute task in Docker container"""
        import aiodocker
        
        docker = aiodocker.Docker()
        
        # Prepare container configuration
        container_config = {
            "Image": "python:3.11-slim",
            "Cmd": ["python", "-c", task.parameters["code"]],
            "WorkingDir": "/workspace",
            "NetworkMode": "none",  # No network access
            "Memory": 256 * 1024 * 1024,  # 256MB limit
            "CpuShares": 512,  # CPU limit
            "AttachStdout": True,
            "AttachStderr": True
        }
        
        try:
            # Create and start container
            container = await docker.containers.create(container_config)
            await container.start()
            
            # Wait for completion with timeout
            timeout = task.parameters.get("timeout", 30)
            await asyncio.wait_for(container.wait(), timeout=timeout)
            
            # Get output
            logs = await container.log(stdout=True, stderr=True)
            stdout = "".join([log for log in logs if log['stream'] == 'stdout'])
            stderr = "".join([log for log in logs if log['stream'] == 'stderr'])
            
            # Get exit code
            container_info = await container.show()
            exit_code = container_info['State']['ExitCode']
            
            result = {
                "result": stdout,
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": exit_code,
                "execution_time": 0  # TODO: calculate actual time
            }
            
            return TaskResult(
                task_id=task.id,
                status=TaskStatus.COMPLETED if exit_code == 0 else TaskStatus.FAILED,
                result=result,
                execution_time=0,
                provider_id=provider.provider_id,
                completed_at=datetime.utcnow()
            )
            
        except asyncio.TimeoutError:
            await container.kill()
            raise TaskTimeoutError(f"Task {task.id} timed out after {timeout} seconds")
        
        finally:
            # Clean up container
            try:
                await container.delete()
            except:
                pass
            
            await docker.close()
```

### Monitoring and Observability

```python
class ExecutionMonitor:
    """Monitors execution engine performance and health"""
    
    def __init__(self, execution_engine: ExecutionEngine):
        self.engine = execution_engine
        self.metrics_collector = MetricsCollector()
        
    async def start_monitoring(self) -> None:
        """Start monitoring tasks"""
        asyncio.create_task(self._collect_metrics_loop())
        asyncio.create_task(self._health_check_loop())
    
    async def _collect_metrics_loop(self) -> None:
        """Collect performance metrics"""
        while self.engine.running:
            try:
                metrics = await self._collect_current_metrics()
                await self.metrics_collector.record_metrics(metrics)
                
                # Emit metrics event
                await self.engine.emit_event("metrics:collected", {
                    "timestamp": datetime.utcnow().isoformat(),
                    "metrics": metrics
                })
                
            except Exception as e:
                logger.error(f"Error collecting metrics: {e}")
            
            await asyncio.sleep(60)  # Collect every minute
    
    async def _collect_current_metrics(self) -> Dict[str, Any]:
        """Collect current performance metrics"""
        return {
            "active_tasks": len(self.engine.active_tasks),
            "completed_tasks": self.engine.stats.tasks_succeeded,
            "failed_tasks": self.engine.stats.tasks_failed,
            "average_execution_time": self.engine.stats.average_task_duration,
            "throughput_per_minute": await self._calculate_throughput(),
            "memory_usage_mb": await self._get_memory_usage(),
            "provider_health": await self.engine.registry.health_check_all()
        }

class PerformanceProfiler:
    """Profiles task execution performance"""
    
    def __init__(self):
        self.execution_times: Dict[str, List[float]] = {}
        self.memory_usage: Dict[str, List[int]] = {}
        
    async def profile_task_execution(self, task: Task, provider: BaseProvider) -> TaskResult:
        """Profile task execution"""
        import psutil
        import time
        
        method_key = f"{task.protocol}:{task.method}"
        
        # Start profiling
        start_time = time.time()
        process = psutil.Process()
        start_memory = process.memory_info().rss
        
        try:
            # Execute task
            result = await provider.execute_task(task)
            
            # Record metrics
            execution_time = time.time() - start_time
            peak_memory = process.memory_info().rss
            memory_delta = peak_memory - start_memory
            
            # Store performance data
            if method_key not in self.execution_times:
                self.execution_times[method_key] = []
            self.execution_times[method_key].append(execution_time)
            
            if method_key not in self.memory_usage:
                self.memory_usage[method_key] = []
            self.memory_usage[method_key].append(memory_delta)
            
            # Add profiling info to result
            if isinstance(result.result, dict):
                result.result["_profiling"] = {
                    "execution_time": execution_time,
                    "memory_delta_bytes": memory_delta,
                    "peak_memory_bytes": peak_memory
                }
            
            return result
            
        except Exception as e:
            # Record failed execution time
            execution_time = time.time() - start_time
            if method_key not in self.execution_times:
                self.execution_times[method_key] = []
            self.execution_times[method_key].append(execution_time)
            
            raise
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get performance summary for all methods"""
        summary = {}
        
        for method_key, times in self.execution_times.items():
            if times:
                summary[method_key] = {
                    "avg_execution_time": sum(times) / len(times),
                    "min_execution_time": min(times),
                    "max_execution_time": max(times),
                    "total_executions": len(times)
                }
                
                if method_key in self.memory_usage:
                    memory_data = self.memory_usage[method_key]
                    summary[method_key].update({
                        "avg_memory_delta": sum(memory_data) / len(memory_data),
                        "max_memory_delta": max(memory_data),
                        "min_memory_delta": min(memory_data)
                    })
        
        return summary
```

This comprehensive documentation covers the complete protocol, provider, and execution architecture of Gleitzeit V4, providing developers with the knowledge needed to understand, extend, and maintain the system.