# Implementation Plan: Mixed Handler Execution Modes

## Overview
Enable Gleitzeit handlers to execute in different modes (native, subprocess, container) regardless of how Gleitzeit itself is deployed.

## Goals
1. **Immediate**: Enable Python handler to use Docker containers when configured
2. **Short-term**: Add execution strategy pattern for clean mode switching
3. **Medium-term**: Support bidirectional execution (Native→Docker, Docker→Native)
4. **Long-term**: Add container pooling and performance optimizations

## Phase 1: Minimum Viable Implementation (Week 1)

### Goal: Get Python handler working with Docker containers

### Day 1-2: Basic Container Executor

#### Task 1.1: Create Container Executor
**File**: `src/gleitzeit/core/container_executor.py` (NEW)
```python
class ContainerExecutor:
    def __init__(self, config: Dict[str, Any]):
        self.docker_client = docker.from_env()
        self.image = config.get('image', 'python:3.11-slim')
        self.timeout = config.get('timeout', 300)

    async def execute(self, code: str, inputs: Dict = None) -> Dict:
        # Simple container run without pooling
        # Write code to temp file
        # Run container with volume mount
        # Collect output and cleanup
```

**Dependencies**:
- Add `docker` to pyproject.toml dependencies
- Test Docker availability

#### Task 1.2: Add Mode Detection
**File**: `src/gleitzeit/handlers/python.py` (MODIFY)
```python
def __init__(self, config: Optional[Dict] = None):
    super().__init__(config)

    # NEW: Check execution mode
    self.execution_mode = self.config.get('execution_mode', 'subprocess')

    # NEW: Detect if running in Docker
    self.in_docker = self._detect_docker_environment()

    # Initialize executor based on mode
    self._init_executor()

def _detect_docker_environment(self) -> bool:
    """Check if we're running inside Docker"""
    return Path('/.dockerenv').exists()

def _init_executor(self):
    """Initialize the appropriate executor"""
    if self.execution_mode == 'container' and not self.in_docker:
        try:
            from ..core.container_executor import ContainerExecutor
            self.executor = ContainerExecutor(self.config.get('container', {}))
            self.executor_type = 'container'
        except Exception as e:
            logger.warning(f"Container execution unavailable: {e}, falling back to subprocess")
            self._init_subprocess_executor()
    else:
        self._init_subprocess_executor()
```

#### Task 1.3: Update Execute Method
**File**: `src/gleitzeit/handlers/python.py` (MODIFY)
```python
async def execute(self, task: Task) -> TaskResult:
    try:
        code = task.params.get('code')
        inputs = task.params.get('inputs', {})

        # Use appropriate executor
        if self.executor_type == 'container':
            result = await self.executor.execute(code, inputs)
        else:
            # Existing subprocess logic
            result = await self._execute_subprocess(code, inputs)

        return self.create_result(
            task=task,
            status=TaskStatus.COMPLETED,
            result=result,
            metadata={'executor_type': self.executor_type}
        )
```

### Day 3: Testing & Debugging

#### Task 1.4: Create Test Workflows
**File**: `test_container_execution.yaml` (NEW)
```yaml
workflow:
  id: test-container-execution
  name: Test Container Execution
  tasks:
    - id: python-in-container
      type: python
      params:
        code: |
          import sys
          import platform
          import os
          result = {
              'python_version': sys.version,
              'hostname': platform.node(),
              'in_container': os.path.exists('/.dockerenv'),
              'message': 'Executed in container'
          }
          print(result)
```

#### Task 1.5: Integration Testing
- Test with `execution_mode: container` in gleitzeit.yaml
- Verify fallback to subprocess when Docker unavailable
- Test error handling and timeouts

### Deliverables Phase 1:
- [ ] ContainerExecutor class with basic Docker execution
- [ ] Python handler with mode detection and switching
- [ ] Test workflows demonstrating container execution
- [ ] Documentation of configuration options

---

## Phase 2: Strategy Pattern Implementation (Week 2)

### Goal: Clean architecture with execution strategies

### Day 4-5: Extract Strategy Pattern

#### Task 2.1: Create Strategy Interface
**File**: `src/gleitzeit/core/execution_strategy.py` (NEW)
```python
from abc import ABC, abstractmethod

class ExecutionStrategy(ABC):
    @abstractmethod
    async def execute(self, code: str, **kwargs) -> Dict:
        pass

    @abstractmethod
    def get_info(self) -> Dict:
        """Return strategy information for logging"""
        pass
```

#### Task 2.2: Implement Concrete Strategies
**Files**:
- `src/gleitzeit/core/strategies/subprocess_strategy.py` (NEW)
- `src/gleitzeit/core/strategies/container_strategy.py` (NEW)
- `src/gleitzeit/core/strategies/pool_strategy.py` (NEW)

```python
class SubprocessStrategy(ExecutionStrategy):
    # Move existing subprocess logic here

class ContainerStrategy(ExecutionStrategy):
    # Move container executor logic here

class PoolStrategy(ExecutionStrategy):
    # Move pool execution logic here
```

#### Task 2.3: Strategy Factory
**File**: `src/gleitzeit/core/execution_factory.py` (NEW)
```python
class ExecutionStrategyFactory:
    @staticmethod
    def create_strategy(mode: str, config: Dict, environment: str) -> ExecutionStrategy:
        """Create appropriate strategy based on mode and environment"""

        if environment == 'docker' and mode == 'container':
            # Already in Docker, use subprocess
            return SubprocessStrategy(config)

        if mode == 'container':
            if ContainerStrategy.is_available():
                return ContainerStrategy(config)
            return SubprocessStrategy(config)  # Fallback

        if mode == 'pool':
            return PoolStrategy(config)

        return SubprocessStrategy(config)  # Default
```

### Day 6: Refactor Handlers

#### Task 2.4: Update Python Handler
**File**: `src/gleitzeit/handlers/python.py` (MODIFY)
```python
def __init__(self, config: Optional[Dict] = None):
    super().__init__(config)

    # Use factory to create strategy
    from ..core.execution_factory import ExecutionStrategyFactory

    self.strategy = ExecutionStrategyFactory.create_strategy(
        mode=self.config.get('execution_mode', 'subprocess'),
        config=self.config,
        environment=self._detect_environment()
    )

    logger.info(f"Python handler using {self.strategy.get_info()}")

async def execute(self, task: Task) -> TaskResult:
    # Simplified - delegate to strategy
    result = await self.strategy.execute(
        code=task.params.get('code'),
        inputs=task.params.get('inputs'),
        timeout=task.params.get('timeout', 300)
    )

    return self.create_result(task, TaskStatus.COMPLETED, result)
```

### Deliverables Phase 2:
- [ ] Clean strategy pattern implementation
- [ ] Factory for strategy selection
- [ ] Refactored Python handler
- [ ] Unit tests for each strategy

---

## Phase 3: Additional Handlers (Week 3)

### Goal: Extend container execution to other languages

### Day 7-8: Node.js Handler

#### Task 3.1: Create Node.js Handler
**File**: `src/gleitzeit/handlers/nodejs.py` (NEW)
```python
@HandlerRegistry.register
class NodeJSHandler(BaseHandler):
    def __init__(self, config: Optional[Dict] = None):
        super().__init__(config)

        # Reuse strategy factory
        self.strategy = ExecutionStrategyFactory.create_strategy(
            mode=self.config.get('execution_mode', 'container'),
            config=self.config,
            environment=self._detect_environment()
        )

    @classmethod
    def get_capabilities(cls) -> Dict:
        return {
            'protocol': 'nodejs/v1',
            'task_types': ['nodejs', 'javascript'],
            'methods': {
                'nodejs/execute': {
                    'description': 'Execute Node.js code',
                    'required': ['code'],
                    'optional': ['inputs', 'timeout']
                }
            }
        }
```

### Day 9: Shell/Bash Handler

#### Task 3.2: Create Shell Handler
**File**: `src/gleitzeit/handlers/shell.py` (NEW)
- Support for shell commands with security restrictions
- Whitelist of allowed commands
- Container execution for isolation

### Deliverables Phase 3:
- [ ] Node.js handler with container support
- [ ] Shell/Bash handler with security controls
- [ ] Test workflows for each language
- [ ] Multi-language workflow examples

---

## Phase 4: Bidirectional Execution (Week 4)

### Goal: Enable Docker→Native execution for special cases

### Day 10-11: Host Executor Service

#### Task 4.1: Create Host Executor
**File**: `src/gleitzeit/services/host_executor.py` (NEW)
- Unix socket server running on host
- Accepts execution requests from Docker containers
- Security controls and command whitelisting

#### Task 4.2: Host Communication Strategy
**File**: `src/gleitzeit/core/strategies/host_strategy.py` (NEW)
```python
class HostStrategy(ExecutionStrategy):
    """Execute on host machine from Docker container"""
    def __init__(self, config):
        self.socket_path = config.get('host_socket', '/var/run/gleitzeit/executor.sock')

    async def execute(self, code: str, **kwargs):
        # Communicate with host executor via socket
```

### Day 12: Security & Configuration

#### Task 4.3: Security Controls
- Add `ALLOW_HOST_EXECUTION` environment variable
- Implement command whitelisting
- Add audit logging for host execution

### Deliverables Phase 4:
- [ ] Host executor service
- [ ] Host execution strategy
- [ ] Security documentation
- [ ] Deployment guide for bidirectional setup

---

## Phase 5: Performance Optimization (Week 5)

### Goal: Production-ready performance

### Day 13-14: Container Pooling

#### Task 5.1: Container Pool Implementation
**File**: `src/gleitzeit/core/container_pool.py` (NEW)
```python
class ContainerPool:
    """Pool of reusable Docker containers"""
    def __init__(self, image: str, min_size: int = 0, max_size: int = 10):
        self.available = asyncio.Queue()
        self.in_use = set()

    async def acquire(self) -> Container:
        # Get or create container

    async def release(self, container: Container):
        # Return to pool or destroy
```

#### Task 5.2: Warm Container Maintenance
- Pre-create containers at startup
- Health checks and container refresh
- Automatic cleanup of unhealthy containers

### Day 15: Metrics & Monitoring

#### Task 5.3: Performance Metrics
- Execution time by strategy
- Container pool utilization
- Fallback frequency tracking
- Resource usage monitoring

### Deliverables Phase 5:
- [ ] Container pooling implementation
- [ ] Performance benchmarks
- [ ] Monitoring dashboard
- [ ] Optimization guide

---

## Testing Plan

### Unit Tests
- [ ] Each execution strategy independently
- [ ] Strategy factory logic
- [ ] Environment detection
- [ ] Fallback scenarios

### Integration Tests
- [ ] End-to-end workflow execution
- [ ] Mode switching based on config
- [ ] Error handling and recovery
- [ ] Resource cleanup

### Performance Tests
- [ ] Execution overhead comparison
- [ ] Container pool efficiency
- [ ] Concurrent execution scaling
- [ ] Memory and CPU usage

### Security Tests
- [ ] Container isolation verification
- [ ] Host execution restrictions
- [ ] Resource limit enforcement
- [ ] Command injection prevention

---

## Rollout Strategy

### Stage 1: Development (Week 1-2)
- Enable in development environments
- Feature flag: `ENABLE_CONTAINER_EXECUTION=true`
- Extensive logging for debugging

### Stage 2: Staging (Week 3)
- Deploy to staging with subset of workloads
- Monitor performance and errors
- Gather feedback from early users

### Stage 3: Production (Week 4-5)
- Gradual rollout (10% → 50% → 100%)
- Keep subprocess as fallback
- Monitor metrics closely

### Rollback Plan
- Feature flag to disable container execution
- Automatic fallback to subprocess on errors
- Configuration override per handler

---

## Success Metrics

### Functional
- [ ] Container execution works for Python, Node.js, Shell
- [ ] Automatic fallback on Docker unavailability
- [ ] Configuration-driven mode selection

### Performance
- [ ] < 200ms overhead for cold container start
- [ ] < 50ms overhead with container pooling
- [ ] Pool hit rate > 80% under normal load

### Reliability
- [ ] 99.9% success rate for executions
- [ ] Zero container leaks after 24h run
- [ ] Graceful degradation on failures

### Security
- [ ] Pass security audit
- [ ] No privilege escalation vulnerabilities
- [ ] Audit trail for all executions

---

## Risk Mitigation

### Risk 1: Docker Unavailability
**Mitigation**: Automatic fallback to subprocess execution

### Risk 2: Container Resource Leaks
**Mitigation**: Aggressive timeout and cleanup policies

### Risk 3: Security Vulnerabilities
**Mitigation**:
- Run containers with minimal privileges
- Use read-only root filesystems
- Network isolation by default

### Risk 4: Performance Degradation
**Mitigation**:
- Container pooling for warm starts
- Configurable pool sizes
- Performance monitoring and alerts

---

## Documentation Requirements

### User Documentation
- [ ] Configuration guide for execution modes
- [ ] Examples for each handler type
- [ ] Troubleshooting guide
- [ ] Performance tuning guide

### Developer Documentation
- [ ] Architecture overview
- [ ] Adding new execution strategies
- [ ] Creating new handlers
- [ ] Testing guide

### Operations Documentation
- [ ] Deployment guide
- [ ] Monitoring setup
- [ ] Security best practices
- [ ] Disaster recovery procedures

---

## Timeline Summary

| Week | Phase | Deliverable |
|------|-------|-------------|
| 1 | Phase 1 | Basic container execution for Python |
| 2 | Phase 2 | Strategy pattern implementation |
| 3 | Phase 3 | Additional language handlers |
| 4 | Phase 4 | Bidirectional execution |
| 5 | Phase 5 | Performance optimization |

## Next Steps

1. **Immediate**: Start with Phase 1 - Basic container executor
2. **This Week**: Get Python handler working with containers
3. **Next Week**: Refactor to strategy pattern
4. **Review**: After Phase 2, reassess priorities for Phases 3-5

## Implementation Checklist

### Prerequisites
- [ ] Add `docker` package to dependencies
- [ ] Update gleitzeit.yaml schema documentation
- [ ] Create test Docker images

### Phase 1 Checklist
- [ ] ContainerExecutor class
- [ ] Python handler modifications
- [ ] Basic tests passing
- [ ] Documentation updated

### Go/No-Go Criteria for Production
- [ ] All tests passing
- [ ] Performance benchmarks met
- [ ] Security review completed
- [ ] Documentation complete
- [ ] Rollback plan tested