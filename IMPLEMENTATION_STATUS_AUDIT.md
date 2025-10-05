# Implementation Status Audit: Handler Execution Modes

## Executive Summary

**Good News:** Most of the infrastructure needed for mixed execution modes already exists.
**Gap:** Handlers don't actually use the execution mode configuration - they only support subprocess execution.

## What's Already Built ✅

### 1. Configuration Infrastructure
**Status: FULLY IMPLEMENTED**
- `gleitzeit.yaml` already supports execution mode configuration
- `ComponentOrchestrator` reads and propagates handler configs
- Configuration flows from YAML → Redis → Workers → Handlers

**Location:** `/src/gleitzeit/orchestrator/component_orchestrator.py` line 160
```python
handler_configs[protocol]['execution_mode'] = handler_config['execution']['mode']
```

### 2. Subprocess Execution
**Status: PRODUCTION-READY**
- `PythonSubprocessPool` provides high-performance process pooling
- Warm process maintenance (saves 50-100ms per execution)
- Automatic fallback to individual subprocess on pool failures
- JSON-based communication protocol

**Location:** `/src/gleitzeit/core/subprocess_pool.py`
```python
class PythonSubprocessPool:
    - Process lifecycle management
    - Health monitoring
    - Statistics and metrics
    - Graceful error handling
```

### 3. Docker Orchestration Layer
**Status: FULLY IMPLEMENTED (System Level)**
- `DockerOrchestrator` manages entire Gleitzeit deployment in Docker
- Docker Compose generation and management
- Service health checks and monitoring
- Network and volume management

**Location:** `/src/gleitzeit/cli/serve_docker.py`
```python
class DockerOrchestrator:
    - check_docker()
    - start_services()
    - stop_services()
    - generate_compose_file()
```

### 4. Environment Detection
**Status: IMPLEMENTED**
- Mode detection (Docker vs Native deployment)
- Service discovery utilities
- Process identification

**Location:** `/src/gleitzeit/cli/mode_utils.py`
```python
def detect_running_mode() -> Optional[str]:
    # Returns "docker", "native", or None
```

### 5. Handler Architecture
**Status: READY FOR EXTENSION**
- Clean `BaseHandler` abstract class
- Handler registry with auto-discovery
- Configuration passing to handlers
- Result tracking with metadata

**Location:** `/src/gleitzeit/handlers/base.py`

## What's Missing ❌

### 1. Handler-Level Docker Execution
**Status: NOT IMPLEMENTED**
- No Docker client in handlers
- No container lifecycle management for tasks
- No volume/network configuration for task containers
- No container pooling or reuse

**What Needs Building:**
```python
# MISSING: Container executor
class ContainerExecutor:
    async def execute(code, runtime, timeout) -> Dict
    async def _manage_container_lifecycle()
    async def _handle_volumes_and_networking()
```

### 2. Execution Strategy Pattern
**Status: NOT IMPLEMENTED**
- Handlers hardcoded to subprocess execution
- No strategy selection based on configuration
- No runtime mode switching

**What Needs Building:**
```python
# MISSING: Strategy pattern
class ExecutionStrategy(ABC):
    async def execute() -> Dict

class ContainerExecutionStrategy(ExecutionStrategy):
    # Docker container execution

class SubprocessExecutionStrategy(ExecutionStrategy):
    # Current implementation
```

### 3. Mode-Aware Handler Logic
**Status: NOT IMPLEMENTED**
- Handlers ignore `execution_mode` configuration
- No environment detection in handlers
- No automatic fallback logic

**Current Reality in Python Handler:**
```python
# Line 52-79: Only checks subprocess_pool_enabled
# Ignores execution.mode configuration entirely
self.use_pool = self.config.get('subprocess_pool_enabled', True)
# Never checks execution_mode
```

### 4. Docker → Native Bridge
**Status: NOT IMPLEMENTED**
- No host executor service
- No socket-based communication
- No shared volume management

**Would Need:**
- Host executor daemon
- Unix socket interface
- Security controls

## Implementation Difficulty Assessment

### Easy Wins (1-2 days each)

#### 1. Add Mode Detection to Handlers
```python
# Add to PythonHandler.__init__
self.execution_mode = self.config.get('execution_mode', 'subprocess')
if self.execution_mode == 'container':
    if self._is_running_in_docker():
        # Fallback to subprocess
    else:
        # Initialize container executor
```

#### 2. Create Basic Container Executor
- Use existing Docker knowledge from `DockerOrchestrator`
- Start with simple container run (no pooling)
- Reuse volume/network patterns

### Medium Effort (3-5 days)

#### 3. Implement Strategy Pattern
- Extract current subprocess logic into strategy
- Create container strategy
- Add factory method for strategy selection

#### 4. Add Container Pooling
- Adapt subprocess pool pattern for containers
- Implement container health checks
- Add cleanup and lifecycle management

### Complex (1-2 weeks)

#### 5. Docker → Native Execution
- Create host executor service
- Implement security controls
- Add socket communication
- Handle shared volumes

## Recommended Implementation Path

### Phase 1: Enable Native → Docker (1 week)
1. Add execution mode detection to Python handler
2. Create simple `ContainerExecutor` (no pooling)
3. Test with Python handler in container mode
4. Add fallback logic

### Phase 2: Optimize Performance (1 week)
1. Add container pooling
2. Implement warm container maintenance
3. Add metrics and monitoring
4. Performance testing

### Phase 3: Additional Handlers (1 week)
1. Add Node.js handler with container support
2. Add Go handler
3. Update HTTP/File handlers

### Phase 4: Advanced Features (Optional)
1. Docker → Native execution
2. Remote execution protocol
3. Distributed handlers

## Code Reuse Opportunities

### Can Reuse Directly:
1. **Subprocess Pool Pattern** → Adapt for container pool
2. **JSON Protocol** → Use for container communication
3. **Health Check Logic** → Apply to containers
4. **Configuration System** → Already supports modes
5. **Error Handling** → Similar patterns for containers

### Can Adapt:
1. **DockerOrchestrator** → Extract Docker client code
2. **Mode Detection** → Use in handlers
3. **Service Management** → Apply to container lifecycle

## Quick Start Implementation

To quickly enable container execution, minimal changes needed:

```python
# 1. Add to python.py imports
import docker

# 2. In __init__, add:
if self.config.get('execution_mode') == 'container':
    self.docker_client = docker.from_env()
    self.container_image = self.config.get('container', {}).get('image', 'python:3.11-slim')

# 3. In execute method, add:
if hasattr(self, 'docker_client'):
    container = self.docker_client.containers.run(
        self.container_image,
        f"python -c '{code}'",
        detach=True,
        remove=True
    )
    result = container.wait()
    logs = container.logs()
```

## Conclusion

The foundation is solid. The main gap is that handlers don't actually implement the execution modes specified in configuration. With the existing infrastructure, adding container execution support would be straightforward - most patterns can be adapted from the subprocess pool implementation.

**Estimated Total Effort:** 2-3 weeks for full implementation of Native → Docker execution with optimization.