# Docker Container Execution Design for Gleitzeit Handlers

## Executive Summary

This design document outlines the implementation of Docker container execution mode for Gleitzeit handlers, enabling true mixed-mode execution where different handlers can run in different isolation levels (native, subprocess, container, or remote).

## Design Goals

1. **Seamless Integration**: Extend existing handler architecture without breaking changes
2. **Performance**: Minimize container startup overhead through pooling and caching
3. **Isolation**: Provide strong isolation for untrusted code execution
4. **Flexibility**: Support multiple execution modes per handler type
5. **Resource Management**: Control CPU, memory, and network resources
6. **Backward Compatibility**: Maintain existing subprocess and native modes

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                  TaskExecutionWorker                 │
├─────────────────────────────────────────────────────┤
│                    HandlerRegistry                   │
├─────────────┬────────────┬────────────┬────────────┤
│  Python     │  Ollama    │   HTTP     │   File     │
│  Handler    │  Handler   │  Handler   │  Handler   │
├─────────────┴────────────┴────────────┴────────────┤
│              ExecutionStrategyFactory                │
├──────┬──────────┬──────────────┬───────────────────┤
│Native│Subprocess│  Container    │      Remote       │
│      │   Pool   │   Executor    │     Client        │
└──────┴──────────┴──────────────┴───────────────────┘
                  │
                  ▼
         ┌──────────────┐
         │Docker Engine │
         └──────────────┘
```

## Core Components

### 1. Container Executor (`src/gleitzeit/core/container_executor.py`)

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
import asyncio
import docker
import json
import tempfile
from pathlib import Path

class ContainerExecutor:
    """
    Manages Docker container lifecycle for handler execution.

    Features:
    - Container pooling for performance
    - Volume management for data exchange
    - Network configuration
    - Resource limits enforcement
    - Output streaming
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.client = docker.from_env()
        self.container_pool = ContainerPool(
            image=config.get('image'),
            min_size=config.get('pool_min_size', 0),
            max_size=config.get('pool_max_size', 5)
        )

    async def execute(self,
                     code: str,
                     runtime: str = 'python',
                     inputs: Optional[Dict] = None,
                     timeout: int = 300) -> Dict[str, Any]:
        """
        Execute code in a Docker container.

        Args:
            code: Code to execute
            runtime: Runtime environment (python, node, etc.)
            inputs: Input data for the code
            timeout: Execution timeout in seconds

        Returns:
            Execution result with output, errors, and metadata
        """
        # Get or create container from pool
        container = await self.container_pool.acquire()

        try:
            # Prepare execution environment
            exec_id = await self._prepare_execution(
                container, code, runtime, inputs
            )

            # Execute and collect results
            result = await self._execute_in_container(
                container, exec_id, timeout
            )

            return result

        finally:
            # Return container to pool
            await self.container_pool.release(container)

    async def _prepare_execution(self, container, code, runtime, inputs):
        """Prepare container for code execution"""
        # Create temporary directory in container
        work_dir = f"/tmp/exec_{uuid.uuid4().hex}"

        # Copy code and inputs to container
        await self._copy_to_container(
            container,
            code,
            f"{work_dir}/code.{self._get_extension(runtime)}"
        )

        if inputs:
            await self._copy_to_container(
                container,
                json.dumps(inputs),
                f"{work_dir}/inputs.json"
            )

        return work_dir

    async def _execute_in_container(self, container, work_dir, timeout):
        """Execute code in container and collect results"""
        # Build execution command
        cmd = self._build_command(work_dir, self.config.get('runtime'))

        # Execute with timeout
        exec_result = await asyncio.wait_for(
            container.exec_run(
                cmd,
                stdout=True,
                stderr=True,
                workdir=work_dir
            ),
            timeout=timeout
        )

        return {
            'output': exec_result.output.decode('utf-8'),
            'exit_code': exec_result.exit_code,
            'container_id': container.id[:12],
            'execution_time': exec_result.duration
        }
```

### 2. Container Pool (`src/gleitzeit/core/container_pool.py`)

```python
class ContainerPool:
    """
    Manages a pool of Docker containers for reuse.

    Benefits:
    - Avoids container startup overhead
    - Maintains warm containers
    - Automatic cleanup and health checks
    """

    def __init__(self, image: str, min_size: int = 0, max_size: int = 10):
        self.image = image
        self.min_size = min_size
        self.max_size = max_size
        self.available = asyncio.Queue(maxsize=max_size)
        self.in_use = set()
        self._initialized = False

    async def initialize(self):
        """Pre-warm container pool"""
        for _ in range(self.min_size):
            container = await self._create_container()
            await self.available.put(container)
        self._initialized = True

    async def acquire(self) -> Container:
        """Get a container from pool or create new one"""
        if not self._initialized:
            await self.initialize()

        try:
            # Try to get available container
            container = self.available.get_nowait()
            if await self._health_check(container):
                self.in_use.add(container)
                return container
            else:
                # Container unhealthy, create new one
                await self._destroy_container(container)

        except asyncio.QueueEmpty:
            pass

        # Create new container if under limit
        if len(self.in_use) < self.max_size:
            container = await self._create_container()
            self.in_use.add(container)
            return container

        # Wait for container to become available
        container = await self.available.get()
        self.in_use.add(container)
        return container

    async def release(self, container: Container):
        """Return container to pool"""
        self.in_use.discard(container)

        # Clean container state
        await self._clean_container(container)

        # Return to pool if healthy
        if await self._health_check(container):
            await self.available.put(container)
        else:
            await self._destroy_container(container)

            # Maintain minimum pool size
            if self.available.qsize() < self.min_size:
                new_container = await self._create_container()
                await self.available.put(new_container)
```

### 3. Execution Strategy Pattern (`src/gleitzeit/core/execution_strategy.py`)

```python
from abc import ABC, abstractmethod

class ExecutionStrategy(ABC):
    """Abstract base class for execution strategies"""

    @abstractmethod
    async def execute(self, code: str, **kwargs) -> Dict[str, Any]:
        """Execute code using specific strategy"""
        pass

    @abstractmethod
    def get_resource_requirements(self) -> Dict[str, Any]:
        """Get resource requirements for this strategy"""
        pass


class NativeExecutionStrategy(ExecutionStrategy):
    """Execute code directly in process (dangerous, fast)"""

    async def execute(self, code: str, **kwargs):
        # Direct execution (use with caution)
        exec_globals = {}
        exec(code, exec_globals)
        return {'result': exec_globals.get('result')}


class SubprocessExecutionStrategy(ExecutionStrategy):
    """Execute code in subprocess (current implementation)"""

    def __init__(self, pool: Optional[SubprocessPool] = None):
        self.pool = pool

    async def execute(self, code: str, **kwargs):
        if self.pool:
            return await self.pool.execute_code(code, kwargs.get('inputs'))
        else:
            # Fallback to individual subprocess
            return await self._execute_subprocess(code, **kwargs)


class ContainerExecutionStrategy(ExecutionStrategy):
    """Execute code in Docker container"""

    def __init__(self, executor: ContainerExecutor):
        self.executor = executor

    async def execute(self, code: str, **kwargs):
        return await self.executor.execute(
            code=code,
            runtime=kwargs.get('runtime', 'python'),
            inputs=kwargs.get('inputs'),
            timeout=kwargs.get('timeout', 300)
        )

    def get_resource_requirements(self):
        return {
            'cpu': self.executor.config.get('cpu_limit', 1),
            'memory': self.executor.config.get('memory_limit', '512m'),
            'requires_docker': True
        }


class RemoteExecutionStrategy(ExecutionStrategy):
    """Execute via remote API call"""

    def __init__(self, client: RemoteClient):
        self.client = client

    async def execute(self, code: str, **kwargs):
        return await self.client.execute(code, **kwargs)
```

### 4. Enhanced Python Handler (`src/gleitzeit/handlers/python.py`)

```python
@HandlerRegistry.register
class PythonHandler(BaseHandler):
    """
    Enhanced Python handler with multiple execution strategies.
    """

    def __init__(self, config: Optional[Dict] = None):
        super().__init__(config)

        # Determine execution mode
        execution_mode = self.config.get('execution_mode', 'subprocess')

        # Initialize appropriate strategy
        self.strategy = self._create_strategy(execution_mode)

    def _create_strategy(self, mode: str) -> ExecutionStrategy:
        """Factory method to create execution strategy"""

        if mode == 'native':
            logger.warning("Native execution mode is dangerous!")
            return NativeExecutionStrategy()

        elif mode == 'subprocess':
            pool_config = self.config.get('subprocess_pool', {})
            if pool_config.get('enabled', True):
                pool = get_subprocess_pool(
                    min_size=pool_config.get('min_size', 2),
                    max_size=pool_config.get('max_size', 10)
                )
                return SubprocessExecutionStrategy(pool)
            return SubprocessExecutionStrategy()

        elif mode == 'container':
            container_config = self.config.get('container', {})
            executor = ContainerExecutor(container_config)
            return ContainerExecutionStrategy(executor)

        elif mode == 'remote':
            remote_config = self.config.get('remote', {})
            client = RemoteClient(remote_config['url'])
            return RemoteExecutionStrategy(client)

        else:
            raise ValueError(f"Unknown execution mode: {mode}")

    async def execute(self, task: Task) -> TaskResult:
        """Execute Python task using configured strategy"""

        try:
            # Validate task
            await self.validate(task)

            # Extract parameters
            code = task.params.get('code')
            inputs = task.params.get('inputs', {})
            timeout = task.params.get('timeout', self.config.get('default_timeout', 300))

            # Execute using strategy
            result = await self.strategy.execute(
                code=code,
                inputs=inputs,
                timeout=timeout,
                runtime='python'
            )

            # Create success result
            return self.create_result(
                task=task,
                status=TaskStatus.COMPLETED,
                result=result
            )

        except asyncio.TimeoutError:
            return self.create_result(
                task=task,
                status=TaskStatus.FAILED,
                error="Execution timeout"
            )
        except Exception as e:
            logger.error(f"Task {task.id} failed: {e}")
            return self.create_result(
                task=task,
                status=TaskStatus.FAILED,
                error=str(e)
            )
```

## Configuration Schema

### gleitzeit.yaml

```yaml
handlers:
  # Python handler with container execution
  python:
    execution:
      mode: container  # native, subprocess, container, remote

      # Container-specific configuration
      container:
        image: python:3.11-slim
        registry: docker.io  # Optional registry
        pull_policy: if_not_present  # always, never, if_not_present

        # Container pool settings
        pool:
          enabled: true
          min_size: 2  # Pre-warm containers
          max_size: 10
          health_check_interval: 30

        # Resource limits
        resources:
          cpu_limit: "1"  # 1 CPU core
          memory_limit: "512m"
          pids_limit: 100

        # Network configuration
        network:
          mode: bridge  # bridge, host, none
          dns: ["8.8.8.8", "8.8.4.4"]

        # Volume mounts
        volumes:
          - /tmp/gleitzeit:/tmp/gleitzeit:rw
          - /data/datasets:/data:ro

        # Environment variables
        environment:
          PYTHONUNBUFFERED: "1"
          TZ: "UTC"

        # Security
        security:
          read_only_root: false
          no_new_privileges: true
          user: "1000:1000"  # Run as non-root

    # Fallback configuration
    config:
      default_timeout: 300
      max_retries: 3

  # HTTP handler with native execution
  http:
    execution:
      mode: native  # Direct HTTP calls

  # Ollama handler with remote execution
  ollama:
    execution:
      mode: remote
      remote:
        url: http://localhost:11434
        timeout: 180

# Worker-specific overrides
workers:
  - worker_type: task_execution
    worker_class: gleitzeit.workers.task_execution_worker.TaskExecutionWorker
    count: 2
    handler_configs:
      "python/v1":
        execution_mode: container  # Override for this worker
        container:
          image: custom-python:latest
          pool:
            max_size: 20  # More containers for this worker
```

## Implementation Phases

### Phase 1: Core Infrastructure (Week 1-2)
1. Implement `ContainerExecutor` class
2. Create `ContainerPool` for container reuse
3. Add Docker client integration
4. Implement volume and network management

### Phase 2: Strategy Pattern (Week 2-3)
1. Create `ExecutionStrategy` abstract class
2. Implement concrete strategies (Native, Subprocess, Container, Remote)
3. Add strategy factory to handlers
4. Update `PythonHandler` to use strategies

### Phase 3: Configuration & Validation (Week 3-4)
1. Extend configuration schema
2. Add validation for container settings
3. Implement health checks
4. Add monitoring and metrics

### Phase 4: Performance Optimization (Week 4-5)
1. Implement container pooling
2. Add image caching
3. Optimize volume mounts
4. Add performance metrics

### Phase 5: Security & Testing (Week 5-6)
1. Implement security policies
2. Add resource limit enforcement
3. Create comprehensive tests
4. Security audit

## Security Considerations

### 1. Container Isolation
- Run containers with minimal privileges
- Use read-only root filesystems where possible
- Drop unnecessary capabilities
- Use non-root users inside containers

### 2. Network Security
- Default to bridge network mode
- Restrict container-to-container communication
- Use network policies for segmentation
- Disable host network mode by default

### 3. Resource Limits
- Enforce CPU and memory limits
- Set process limits (PIDs)
- Limit disk I/O
- Set execution timeouts

### 4. Image Security
- Scan images for vulnerabilities
- Use minimal base images
- Pin image versions
- Verify image signatures

## Performance Optimizations

### 1. Container Pooling
- Pre-warm containers at startup
- Reuse containers across executions
- Clean container state between uses
- Health check containers periodically

### 2. Image Management
- Cache frequently used images locally
- Use multi-stage builds for smaller images
- Share base layers across images
- Implement image garbage collection

### 3. Volume Optimization
- Use tmpfs for temporary data
- Minimize volume mount overhead
- Cache readonly data in containers
- Use efficient serialization formats

## Monitoring & Observability

### 1. Metrics
- Container creation/destruction rate
- Pool utilization
- Execution latency by mode
- Resource usage per container
- Cache hit rates

### 2. Logging
- Container lifecycle events
- Execution traces
- Error logs with context
- Performance logs

### 3. Tracing
- Distributed tracing across execution modes
- Container execution timeline
- Resource allocation traces

## Testing Strategy

### 1. Unit Tests
- Test each execution strategy independently
- Mock Docker API interactions
- Test error handling paths

### 2. Integration Tests
- Test handler with different execution modes
- Test container pool behavior
- Test resource limit enforcement

### 3. Performance Tests
- Benchmark execution modes
- Load test container pool
- Measure startup overhead

### 4. Security Tests
- Test privilege escalation prevention
- Test resource limit enforcement
- Test network isolation

## Migration Path

### 1. Backward Compatibility
- Default to subprocess mode
- No breaking changes to API
- Gradual rollout via configuration

### 2. Feature Flags
```yaml
features:
  container_execution:
    enabled: false  # Disabled by default
    rollout_percentage: 10  # Gradual rollout
```

### 3. Rollback Plan
- Keep subprocess mode as fallback
- Automatic fallback on container failures
- Configuration-based mode selection

## Success Criteria

1. **Functional**: Container execution works for Python, Node.js, and other runtimes
2. **Performance**: < 100ms overhead for warm container execution
3. **Security**: Pass security audit with no critical vulnerabilities
4. **Reliability**: 99.9% success rate for container executions
5. **Scalability**: Support 100+ concurrent container executions

## Conclusion

This design provides a comprehensive solution for adding Docker container execution to Gleitzeit handlers while maintaining backward compatibility and system integrity. The phased implementation approach ensures each component is properly tested before integration.

The strategy pattern allows for flexible execution modes, the container pool optimizes performance, and the configuration system provides fine-grained control over behavior. This design enables true mixed-mode execution where each handler can run in its optimal isolation level.