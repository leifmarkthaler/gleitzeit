# Handler Execution Modes Architecture

## Executive Summary

This document provides a comprehensive audit of Gleitzeit's handler architecture and proposes an enhanced design for supporting mixed-mode execution (Docker containers, native processes, and remote services). The current handler system is mode-agnostic, making it well-positioned for extension to support multiple execution strategies without breaking existing functionality.

## Table of Contents

1. [Current Architecture Analysis](#current-architecture-analysis)
2. [Handler Execution Modes](#handler-execution-modes)
3. [Proposed Architecture](#proposed-architecture)
4. [Implementation Strategy](#implementation-strategy)
5. [Migration Path](#migration-path)
6. [Security & Performance Considerations](#security--performance-considerations)

## Current Architecture Analysis

### Handler System Components

#### Core Components
- **BaseHandler** (`src/gleitzeit/handlers/base.py`): Abstract base class defining the handler interface
- **HandlerRegistry** (`src/gleitzeit/handlers/registry.py`): Global registry for auto-discovery and registration
- **TaskExecutionWorker** (`src/gleitzeit/workers/task_execution_worker.py`): Worker that loads and executes handlers

#### Handler Types
1. **Python Handler**: Executes Python code in subprocess pools
2. **Ollama Handler**: Connects to Ollama LLM service via HTTP
3. **HTTP Handler**: Makes HTTP requests to external services
4. **File Handler**: Manages file operations
5. **Timer Handler**: Schedules delayed execution
6. **Signal Handler**: Manages inter-workflow communication
7. **Workflow Handler**: Submits child workflows
8. **Validation Handler**: Validates task parameters

### Current Execution Model

#### Native Mode
```
┌─────────────────────────────────────┐
│         Task Execution Worker        │
│  ┌─────────────────────────────┐    │
│  │     Handler Registry         │    │
│  └─────────────────────────────┘    │
│            ↓                         │
│  ┌─────────────────────────────┐    │
│  │    Handler Instance          │    │
│  │  - Subprocess Pool (Python)  │    │
│  │  - Direct HTTP (Ollama)      │    │
│  │  - File System Access        │    │
│  └─────────────────────────────┘    │
└─────────────────────────────────────┘
```

#### Docker Mode (Planned)
```
┌──────────────────────────────────────┐
│         Docker Network               │
├──────────────────────────────────────┤
│  ┌────────────┐  ┌────────────┐     │
│  │  Worker    │  │  Worker    │     │
│  │ Container  │  │ Container  │     │
│  └────────────┘  └────────────┘     │
│         ↓              ↓             │
│  ┌────────────────────────────┐     │
│  │     Shared Services        │     │
│  │  - Redis                   │     │
│  │  - Ollama                  │     │
│  └────────────────────────────┘     │
└──────────────────────────────────────┘
```

### Key Findings

1. **Mode-Agnostic Handlers**: Handlers don't inherently know about execution mode
2. **Provider Integration**: External services (Ollama, HTTP) are accessed via configurable URLs
3. **Isolation Mechanisms**: Python handler already uses subprocess pools for isolation
4. **Registry Pattern**: Centralized registration enables easy handler discovery
5. **Metadata Tracking**: Handlers track execution metadata including provider URLs

## Handler Execution Modes

### Execution Mode Types

#### 1. Native Execution
- **Description**: Handler runs in the same process as the worker
- **Use Cases**: Lightweight operations, trusted code
- **Examples**: Timer, Signal, Validation handlers
- **Pros**: Lowest latency, direct memory access
- **Cons**: No isolation, resource competition

#### 2. Subprocess Execution
- **Description**: Handler runs in a separate process
- **Use Cases**: CPU-intensive tasks, moderate isolation needs
- **Examples**: Python code execution
- **Pros**: Process isolation, resource limits
- **Cons**: IPC overhead, process management complexity

#### 3. Container Execution
- **Description**: Handler runs in a Docker container
- **Use Cases**: Untrusted code, complex dependencies
- **Examples**: ML models, data processing pipelines
- **Pros**: Full isolation, dependency management
- **Cons**: Container startup overhead, network latency

#### 4. Remote Execution
- **Description**: Handler connects to a remote service
- **Use Cases**: Specialized hardware (GPU), shared services
- **Examples**: Ollama LLM, external APIs
- **Pros**: Scalability, resource sharing
- **Cons**: Network dependency, latency

#### 5. Hybrid Execution
- **Description**: Mode chosen dynamically based on availability and load
- **Use Cases**: High availability requirements
- **Pros**: Flexibility, fallback options
- **Cons**: Complex configuration, debugging challenges

### Mode Selection Matrix

| Handler Type | Native | Subprocess | Container | Remote | Recommended |
|--------------|--------|------------|-----------|---------|-------------|
| Python | ✓ | ✓ | ✓ | ✓ | Subprocess/Container |
| Ollama | ✗ | ✗ | ✓ | ✓ | Remote |
| HTTP | ✓ | ✗ | ✓ | ✓ | Native/Container |
| File | ✓ | ✗ | ✓ | ✗ | Native |
| Timer | ✓ | ✗ | ✗ | ✗ | Native |
| Signal | ✓ | ✗ | ✗ | ✗ | Native |
| Workflow | ✓ | ✗ | ✓ | ✓ | Native |
| Validation | ✓ | ✗ | ✗ | ✗ | Native |

## Proposed Architecture

### Enhanced Handler Capabilities

```python
from enum import Enum
from typing import Dict, Any, List

class ExecutionMode(Enum):
    NATIVE = "native"
    SUBPROCESS = "subprocess"
    CONTAINER = "container"
    REMOTE = "remote"
    HYBRID = "hybrid"

class IsolationLevel(Enum):
    NONE = "none"              # In-process
    PROCESS = "process"        # Subprocess
    CONTAINER = "container"    # Docker container
    VM = "vm"                 # Virtual machine

class HandlerCapabilities:
    @classmethod
    def get_capabilities(cls) -> Dict[str, Any]:
        return {
            'protocol': 'python/v1',
            'task_types': ['python', 'script'],
            'execution': {
                'modes': {
                    'supported': [ExecutionMode.NATIVE, ExecutionMode.SUBPROCESS, ExecutionMode.CONTAINER],
                    'preferred': ExecutionMode.SUBPROCESS,
                    'fallback': ExecutionMode.NATIVE
                },
                'isolation': {
                    'level': IsolationLevel.PROCESS,
                    'resource_limits': {
                        'cpu': '1.0',
                        'memory': '512M',
                        'timeout': 300
                    }
                },
                'container': {
                    'image': 'gleitzeit/python-handler:latest',
                    'network': 'gleitzeit',
                    'volumes': {
                        '/data': {'bind': '/data', 'mode': 'rw'}
                    },
                    'environment': {
                        'PYTHONPATH': '/app/src'
                    }
                },
                'remote': {
                    'endpoints': [
                        'http://python-handler-1:8080',
                        'http://python-handler-2:8080'
                    ],
                    'load_balancing': 'round_robin',
                    'health_check': '/health'
                }
            },
            'methods': {
                'python/execute': {
                    'description': 'Execute Python code',
                    'required': ['code'],
                    'optional': ['inputs', 'timeout']
                }
            }
        }
```

### Execution Strategy Pattern

```python
from abc import ABC, abstractmethod
import docker
import aiohttp
import asyncio

class ExecutionStrategy(ABC):
    """Base class for handler execution strategies"""

    @abstractmethod
    async def execute(self, handler: BaseHandler, task: Task) -> TaskResult:
        """Execute task using specific strategy"""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if execution method is available"""
        pass

class NativeExecutionStrategy(ExecutionStrategy):
    """Execute handler in current process"""

    async def execute(self, handler: BaseHandler, task: Task) -> TaskResult:
        return await handler.execute(task)

    async def health_check(self) -> bool:
        return True  # Always available

class SubprocessExecutionStrategy(ExecutionStrategy):
    """Execute handler in subprocess with resource limits"""

    def __init__(self, resource_limits: Dict[str, Any]):
        self.resource_limits = resource_limits
        self.pool = None

    async def execute(self, handler: BaseHandler, task: Task) -> TaskResult:
        # Use subprocess pool with resource limits
        if not self.pool:
            self.pool = await self._create_pool()

        return await self.pool.execute(handler, task, self.resource_limits)

    async def health_check(self) -> bool:
        return self.pool and self.pool.is_healthy()

class ContainerExecutionStrategy(ExecutionStrategy):
    """Execute handler in Docker container"""

    def __init__(self, image: str, **container_config):
        self.image = image
        self.container_config = container_config
        self.docker_client = docker.from_env()

    async def execute(self, handler: BaseHandler, task: Task) -> TaskResult:
        # Serialize task
        task_json = task.to_json()

        # Run container with task as input
        container = self.docker_client.containers.run(
            self.image,
            command=['python', '-m', 'gleitzeit.handler_runner'],
            environment={
                'TASK_JSON': task_json,
                'HANDLER_CLASS': handler.__class__.__name__
            },
            **self.container_config,
            detach=True
        )

        # Wait for completion and get result
        result = await self._wait_for_result(container)

        # Cleanup
        container.remove()

        return TaskResult.from_json(result)

    async def health_check(self) -> bool:
        try:
            self.docker_client.ping()
            return True
        except Exception:
            return False

class RemoteExecutionStrategy(ExecutionStrategy):
    """Execute handler via remote API"""

    def __init__(self, endpoints: List[str], load_balancing: str = 'round_robin'):
        self.endpoints = endpoints
        self.load_balancing = load_balancing
        self.current_endpoint = 0
        self.session = None

    async def execute(self, handler: BaseHandler, task: Task) -> TaskResult:
        if not self.session:
            self.session = aiohttp.ClientSession()

        # Select endpoint
        endpoint = self._select_endpoint()

        # Send task to remote handler
        async with self.session.post(
            f"{endpoint}/execute",
            json=task.to_dict(),
            headers={'Content-Type': 'application/json'}
        ) as response:
            result_data = await response.json()
            return TaskResult.from_dict(result_data)

    def _select_endpoint(self) -> str:
        if self.load_balancing == 'round_robin':
            endpoint = self.endpoints[self.current_endpoint]
            self.current_endpoint = (self.current_endpoint + 1) % len(self.endpoints)
            return endpoint
        # Add other load balancing strategies as needed

    async def health_check(self) -> bool:
        # Check at least one endpoint is healthy
        for endpoint in self.endpoints:
            try:
                async with self.session.get(f"{endpoint}/health") as response:
                    if response.status == 200:
                        return True
            except Exception:
                continue
        return False

class HybridExecutionStrategy(ExecutionStrategy):
    """Dynamically choose execution strategy based on availability"""

    def __init__(self, strategies: List[ExecutionStrategy]):
        self.strategies = strategies

    async def execute(self, handler: BaseHandler, task: Task) -> TaskResult:
        # Try strategies in order until one succeeds
        for strategy in self.strategies:
            if await strategy.health_check():
                try:
                    return await strategy.execute(handler, task)
                except Exception as e:
                    logger.warning(f"Strategy {strategy.__class__.__name__} failed: {e}")
                    continue

        raise GleitzeitError("All execution strategies failed")

    async def health_check(self) -> bool:
        # At least one strategy must be healthy
        for strategy in self.strategies:
            if await strategy.health_check():
                return True
        return False
```

### Enhanced Task Execution Worker

```python
class MixedModeTaskExecutionWorker(TaskExecutionWorker):
    """Task execution worker with mixed-mode handler support"""

    def __init__(self, config: WorkerConfig):
        super().__init__(config)
        self.execution_strategies = {}
        self._init_execution_strategies()

    def _init_execution_strategies(self):
        """Initialize execution strategies based on handler capabilities"""

        for protocol, handler_class in self.protocol_to_handler.items():
            caps = handler_class.get_capabilities()
            exec_config = caps.get('execution', {})

            # Get execution mode from config or capabilities
            mode = self.config.get(f'handler_{protocol}_mode') or \
                   exec_config.get('modes', {}).get('preferred') or \
                   ExecutionMode.NATIVE

            # Create strategy based on mode
            strategy = self._create_strategy(mode, exec_config)

            # Wrap in hybrid if fallback is configured
            if exec_config.get('modes', {}).get('fallback'):
                fallback_strategy = self._create_strategy(
                    exec_config['modes']['fallback'],
                    exec_config
                )
                strategy = HybridExecutionStrategy([strategy, fallback_strategy])

            self.execution_strategies[protocol] = strategy

            logger.info(f"Handler {protocol} configured with {mode} execution mode")

    def _create_strategy(self, mode: ExecutionMode, config: Dict) -> ExecutionStrategy:
        """Create execution strategy for given mode"""

        if mode == ExecutionMode.NATIVE:
            return NativeExecutionStrategy()

        elif mode == ExecutionMode.SUBPROCESS:
            return SubprocessExecutionStrategy(
                resource_limits=config.get('isolation', {}).get('resource_limits', {})
            )

        elif mode == ExecutionMode.CONTAINER:
            container_config = config.get('container', {})
            return ContainerExecutionStrategy(
                image=container_config.get('image'),
                network_mode=container_config.get('network'),
                volumes=container_config.get('volumes'),
                environment=container_config.get('environment')
            )

        elif mode == ExecutionMode.REMOTE:
            remote_config = config.get('remote', {})
            return RemoteExecutionStrategy(
                endpoints=remote_config.get('endpoints', []),
                load_balancing=remote_config.get('load_balancing', 'round_robin')
            )

        else:
            raise ValueError(f"Unknown execution mode: {mode}")

    async def process_message(self, stream: str, message_id: str, data: Dict) -> bool:
        """Process task with appropriate execution strategy"""

        # ... existing task retrieval code ...

        # Get handler and strategy
        handler = self.handlers[task.protocol]
        strategy = self.execution_strategies.get(task.protocol)

        if not strategy:
            # Fallback to direct execution
            logger.warning(f"No execution strategy for {task.protocol}, using direct execution")
            result = await handler.execute(task)
        else:
            # Execute with strategy
            try:
                result = await strategy.execute(handler, task)
            except Exception as e:
                logger.error(f"Strategy execution failed for {task.id}: {e}")
                # Could implement retry with different strategy here
                raise

        # ... existing result handling code ...
```

## Implementation Strategy

### Phase 1: Foundation (Week 1-2)

1. **Define Execution Mode Interfaces**
   - Create `ExecutionMode` and `IsolationLevel` enums
   - Define `ExecutionStrategy` abstract class
   - Update `BaseHandler.get_capabilities()` format

2. **Implement Native and Subprocess Strategies**
   - Create `NativeExecutionStrategy`
   - Create `SubprocessExecutionStrategy` with resource limits
   - Test with Python handler

### Phase 2: Container Support (Week 3-4)

1. **Create Handler Container Images**
   ```dockerfile
   # Dockerfile.python-handler
   FROM python:3.11-slim

   WORKDIR /app
   COPY src/gleitzeit/handlers /app/handlers
   COPY src/gleitzeit/core /app/core

   RUN pip install -r requirements.txt

   ENTRYPOINT ["python", "-m", "gleitzeit.handler_runner"]
   ```

2. **Implement Container Execution Strategy**
   - Create `ContainerExecutionStrategy`
   - Add Docker client integration
   - Implement task serialization/deserialization

3. **Container Orchestration**
   ```yaml
   # docker-compose.handlers.yml
   version: '3.8'

   services:
     python-handler:
       build:
         context: .
         dockerfile: Dockerfile.python-handler
       deploy:
         replicas: 3
       environment:
         - HANDLER_MODE=container
         - REDIS_URL=redis://redis:6379
       networks:
         - gleitzeit
       volumes:
         - shared-data:/data

     ollama-handler:
       image: gleitzeit/ollama-handler:latest
       environment:
         - OLLAMA_URL=http://ollama:11434
       networks:
         - gleitzeit
   ```

### Phase 3: Remote Execution (Week 5)

1. **Handler Service API**
   ```python
   # handler_service.py
   from fastapi import FastAPI
   from pydantic import BaseModel

   app = FastAPI()

   @app.post("/execute")
   async def execute_task(task: TaskModel) -> TaskResultModel:
       handler = get_handler(task.protocol)
       result = await handler.execute(task)
       return result

   @app.get("/health")
   async def health_check():
       return {"status": "healthy"}
   ```

2. **Implement Remote Execution Strategy**
   - Create `RemoteExecutionStrategy`
   - Add load balancing
   - Implement health checks

### Phase 4: Hybrid and Advanced Features (Week 6)

1. **Hybrid Execution Strategy**
   - Implement fallback mechanisms
   - Add strategy selection logic
   - Create monitoring and metrics

2. **Advanced Features**
   - Handler auto-scaling based on load
   - Dynamic strategy switching
   - Performance profiling per strategy

## Migration Path

### Step 1: Backward Compatibility

Ensure all existing handlers work without modification:

```python
class LegacyHandlerAdapter:
    """Adapter for handlers without execution mode support"""

    def __init__(self, handler_class):
        self.handler_class = handler_class

    def get_capabilities(self):
        caps = self.handler_class.get_capabilities()
        # Add default execution configuration
        if 'execution' not in caps:
            caps['execution'] = {
                'modes': {
                    'supported': [ExecutionMode.NATIVE],
                    'preferred': ExecutionMode.NATIVE
                }
            }
        return caps
```

### Step 2: Gradual Handler Migration

1. **Low Risk (Week 1)**
   - Timer Handler → Native only
   - Signal Handler → Native only
   - Validation Handler → Native only

2. **Medium Risk (Week 2-3)**
   - File Handler → Native + Container
   - HTTP Handler → Native + Container
   - Workflow Handler → Native + Remote

3. **High Risk (Week 4-5)**
   - Python Handler → Subprocess + Container
   - Ollama Handler → Remote + Container

### Step 3: Configuration Migration

```yaml
# config/handlers.yml
handlers:
  python:
    execution_mode: subprocess  # Start with subprocess
    fallback_mode: native      # Fallback for compatibility
    container:
      enabled: false           # Enable when ready
      image: gleitzeit/python-handler:latest

  ollama:
    execution_mode: remote
    remote:
      endpoints:
        - http://ollama:11434
    container:
      enabled: true
      image: ollama/ollama:latest
```

## Security & Performance Considerations

### Security

#### Isolation Levels by Handler Type

| Handler | Recommended Isolation | Reason |
|---------|----------------------|---------|
| Python | Container/Subprocess | Executes arbitrary code |
| HTTP | Container | External network access |
| File | Native/Container | File system access |
| Ollama | Remote | Resource intensive |
| Timer | Native | Lightweight, trusted |
| Signal | Native | Internal communication |

#### Security Policies

1. **Network Isolation**
   ```yaml
   networks:
     handlers:
       driver: bridge
       internal: true  # No external access
     providers:
       driver: bridge
   ```

2. **Resource Limits**
   ```yaml
   deploy:
     resources:
       limits:
         cpus: '1.0'
         memory: 512M
       reservations:
         memory: 128M
   ```

3. **Volume Restrictions**
   ```yaml
   volumes:
     - type: bind
       source: /data/input
       target: /data
       read_only: true  # Read-only for untrusted handlers
   ```

### Performance

#### Optimization Strategies

1. **Handler Pooling**
   - Pre-warm containers for frequently used handlers
   - Connection pooling for remote handlers
   - Subprocess pool reuse

2. **Caching**
   - Cache handler capabilities
   - Cache execution strategy decisions
   - Cache health check results (with TTL)

3. **Load Balancing**
   - Round-robin for stateless handlers
   - Least-connections for resource-intensive handlers
   - Geographic routing for distributed deployments

#### Performance Metrics

```python
class ExecutionMetrics:
    """Track performance by execution mode"""

    def __init__(self):
        self.metrics = {
            'native': {'count': 0, 'total_time': 0, 'errors': 0},
            'subprocess': {'count': 0, 'total_time': 0, 'errors': 0},
            'container': {'count': 0, 'total_time': 0, 'errors': 0},
            'remote': {'count': 0, 'total_time': 0, 'errors': 0}
        }

    async def record_execution(self, mode: str, duration: float, success: bool):
        self.metrics[mode]['count'] += 1
        self.metrics[mode]['total_time'] += duration
        if not success:
            self.metrics[mode]['errors'] += 1

    def get_statistics(self):
        stats = {}
        for mode, data in self.metrics.items():
            if data['count'] > 0:
                stats[mode] = {
                    'avg_time': data['total_time'] / data['count'],
                    'error_rate': data['errors'] / data['count'],
                    'total_executions': data['count']
                }
        return stats
```

## Monitoring and Observability

### Health Checks

```python
@app.get("/health/handlers")
async def handler_health():
    """Health check endpoint for all handlers"""
    health_status = {}

    for protocol, strategy in execution_strategies.items():
        health_status[protocol] = {
            'healthy': await strategy.health_check(),
            'mode': strategy.__class__.__name__,
            'last_execution': get_last_execution_time(protocol)
        }

    return health_status
```

### Metrics Collection

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'handlers'
    static_configs:
      - targets:
        - 'python-handler:9090'
        - 'ollama-handler:9090'
        - 'http-handler:9090'
    metrics_path: '/metrics'
```

### Logging

```python
import structlog

logger = structlog.get_logger()

class ExecutionLogger:
    """Structured logging for handler execution"""

    async def log_execution(self, task: Task, result: TaskResult, strategy: str):
        logger.info(
            "task_executed",
            task_id=task.id,
            protocol=task.protocol,
            method=task.method,
            execution_strategy=strategy,
            duration=result.duration_seconds,
            status=result.status,
            handler_id=result.handler_id,
            worker_id=result.worker_id
        )
```

## Conclusion

The proposed mixed-mode handler architecture provides:

1. **Flexibility**: Multiple execution strategies per handler
2. **Security**: Appropriate isolation levels for different risk profiles
3. **Performance**: Optimized execution based on handler characteristics
4. **Scalability**: Container and remote execution for horizontal scaling
5. **Reliability**: Fallback strategies and health checks
6. **Compatibility**: Backward compatible with existing handlers

This architecture positions Gleitzeit to handle diverse workloads efficiently while maintaining security and reliability. The phased implementation approach ensures smooth migration without disrupting existing functionality.