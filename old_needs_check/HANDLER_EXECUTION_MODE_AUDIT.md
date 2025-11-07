# Handler Execution Mode Audit

## Executive Summary

The current Gleitzeit implementation **does not support Docker container execution mode for individual handlers**. While the configuration structure exists in `gleitzeit.yaml` to specify execution modes (native, subprocess, container, remote), the actual handler implementations only support:

1. **Native/Subprocess execution** - Python handler uses subprocess pools
2. **Remote API calls** - Ollama handler calls external APIs

There is **no implementation** for running handler code inside Docker containers.

## Current State Analysis

### 1. Configuration Structure ✅ Exists

The configuration properly flows from `gleitzeit.yaml` to handlers:

```yaml
# gleitzeit.yaml
handlers:
  python:
    execution:
      mode: container  # This is configured but NOT implemented
      container:
        image: gleitzeit007-worker-task-execution-1:latest
        network: host
```

**Flow:**
1. `gleitzeit.yaml` defines handler configs
2. `ComponentOrchestrator._load_handler_configs()` reads configs at line 160:
   ```python
   handler_configs[protocol]['execution_mode'] = handler_config['execution']['mode']
   ```
3. `TaskExecutionWorker` passes config to handler at line 101:
   ```python
   handler_instance = handler_class(config=handler_config)
   ```

### 2. Handler Implementations ❌ Missing Container Support

#### Python Handler (`src/gleitzeit/handlers/python.py`)
- **Current:** Uses `asyncio.create_subprocess_exec()` to run Python in subprocess
- **No Docker:** No code to execute in containers
- **Lines 321, 398:** Direct subprocess execution only

#### Ollama Handler (`src/gleitzeit/handlers/ollama.py`)
- **Current:** Makes HTTP requests to Ollama API
- **Mode:** Always remote, no container execution needed

### 3. Missing Infrastructure

No container execution utilities found:
- No Docker client integration
- No container lifecycle management
- No volume mounting for code/data transfer
- No container output capture mechanisms

## Key Findings

### 1. Conceptual Confusion

There are two distinct concepts being conflated:

**A. Worker Deployment Mode**
- How Gleitzeit workers themselves run (native processes vs Docker containers)
- Controlled by `gleitzeit serve --mode [native|docker]`
- When mode=docker, entire workers run in containers via docker-compose

**B. Handler Execution Mode**
- How individual handlers execute tasks within a worker
- Supposedly configurable via `handlers.<name>.execution.mode`
- Currently NOT implemented for container mode

### 2. Current Execution Modes

| Handler | Configured Mode | Actual Mode | Implementation |
|---------|----------------|-------------|----------------|
| Python | container | subprocess | Uses subprocess pool |
| Ollama | remote | remote | HTTP API calls |

### 3. Why Container Mode Isn't Working

1. **No Implementation:** Handler classes don't check `execution_mode` config
2. **No Docker Integration:** No code to spawn/manage Docker containers
3. **Configuration Ignored:** The `execution.mode: container` setting has no effect

## Required Changes for True Mixed Mode

### 1. Implement Container Executor

Create `src/gleitzeit/core/container_executor.py`:
```python
class ContainerExecutor:
    async def execute(self, image: str, code: str, volumes: Dict,
                     network: str = 'host') -> Dict:
        # Docker client integration
        # Container lifecycle management
        # Output capture and return
```

### 2. Modify Python Handler

Update `src/gleitzeit/handlers/python.py`:
```python
async def execute(self, task: Task) -> TaskResult:
    execution_mode = self.config.get('execution_mode', 'subprocess')

    if execution_mode == 'container':
        return await self._execute_in_container(task)
    elif execution_mode == 'subprocess':
        return await self._execute_in_subprocess(task)
    # ...
```

### 3. Add Container Configuration Validation

Ensure required container settings are present:
- Image name
- Network configuration
- Volume mappings
- Resource limits

## Current Workarounds

### Option 1: All-or-Nothing Docker
Run entire Gleitzeit in Docker mode:
```bash
gleitzeit serve --mode docker
```
This runs ALL workers in containers, not selective handler execution.

### Option 2: Remote Execution Pattern
Like Ollama, handlers can call external containerized services:
- Run service in Docker separately
- Handler makes API calls to service
- Already works for Ollama

### Option 3: Subprocess Pools (Current)
Python handler uses subprocess pools for isolation:
- Faster than containers
- Less isolation than containers
- Currently working

## Recommendations

1. **Short Term:** Document that container execution mode is not implemented
2. **Medium Term:** Implement basic container executor for Python handler
3. **Long Term:** Full container orchestration with resource management

## Conclusion

The mixed mode execution (Python in Docker, Ollama remote) **is not actually working** as intended. The configuration exists but lacks implementation. Both handlers currently run in native mode within the worker process, with Python using subprocesses and Ollama making remote API calls.