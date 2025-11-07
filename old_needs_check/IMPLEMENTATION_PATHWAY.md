# Implementation Pathway: Providers → Handlers

## Overview
Complete migration from the complex Provider/Pool/Adapter system to the simpler Handler architecture.
**No backwards compatibility needed** - clean replacement.

## Current State
- **Task Model**: Pydantic-based `Task` with protocol/method/params
- **Enums**: TaskStatus, WorkflowStatus, Priority, BackoffStrategy
- **Errors**: Centralized ErrorCode enum and GleitzeitError hierarchy
- **Providers**: Complex with pools, adapters, orchestrators
- **Workers**: Use ProviderAdapter to execute tasks
- **State**: All providers return TaskResult

## Target State
- **Handlers**: Simple, stateless executors with auto-discovery
- **Workers**: Direct handler execution using Task objects
- **Validation**: Handler capabilities drive workflow validation
- **Error Handling**: Consistent use of GleitzeitError and ErrorCode

---

## Phase 1: Create Handler Infrastructure (Day 1)

### 1.1 Create Base Handler Structure
```bash
src/gleitzeit/handlers/
├── __init__.py       # Auto-discovery
├── base.py           # BaseHandler interface
├── registry.py       # HandlerRegistry
└── metrics.py        # HandlerMetrics
```

**Files to create:**

#### `handlers/base.py`
```python
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple
from ..core.models import Task, TaskResult, TaskStatus
from ..core.errors import GleitzeitError, ErrorCode

class BaseHandler(ABC):
    """Base handler interface - works with Task objects"""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        from .metrics import HandlerMetrics
        self.metrics = HandlerMetrics(self.__class__.__name__)

    @classmethod
    @abstractmethod
    def get_capabilities(cls) -> Dict:
        """
        Return handler capabilities for discovery

        Example:
        {
            'protocol': 'python/v1',
            'task_types': ['python', 'script'],  # For backward compat
            'methods': {
                'python/execute': {
                    'required': ['code'],
                    'optional': ['inputs', 'timeout']
                }
            }
        }
        """
        pass

    @abstractmethod
    async def execute(self, task: Task) -> TaskResult:
        """
        Execute task and return TaskResult

        Args:
            task: Task object with protocol, method, params

        Returns:
            TaskResult with status, result, or error
        """
        pass

    async def validate(self, task: Task) -> None:
        """
        Validate task can be executed

        Raises:
            GleitzeitError with appropriate ErrorCode if invalid
        """
        # Default implementation - check method is supported
        caps = self.get_capabilities()
        if task.method not in caps.get('methods', {}):
            raise GleitzeitError(
                f"Method {task.method} not supported by {caps['protocol']}",
                code=ErrorCode.METHOD_NOT_SUPPORTED,
                data={'method': task.method, 'protocol': caps['protocol']}
            )

    async def cleanup(self):
        """Cleanup resources"""
        pass
```

#### `handlers/registry.py`
```python
import logging
from typing import Dict, Type, Optional

logger = logging.getLogger(__name__)

class HandlerRegistry:
    """Global handler registry"""
    _handlers: Dict[str, Type['BaseHandler']] = {}
    _type_mapping: Dict[str, Type['BaseHandler']] = {}
    
    @classmethod
    def register(cls, handler_class):
        """Decorator to register handlers"""
        caps = handler_class.get_capabilities()
        protocol = caps['protocol']
        
        cls._handlers[protocol] = handler_class
        
        for task_type in caps.get('task_types', []):
            cls._type_mapping[task_type] = handler_class
        
        logger.info(f"Registered {handler_class.__name__} for {protocol}")
        return handler_class
    
    @classmethod
    def get_all_capabilities(cls):
        return {
            protocol: handler.get_capabilities()
            for protocol, handler in cls._handlers.items()
        }
    
    @classmethod
    def get_handler_for_type(cls, task_type: str):
        return cls._type_mapping.get(task_type)
    
    @classmethod
    def get_handler_for_protocol(cls, protocol: str):
        return cls._handlers.get(protocol)
```

#### `handlers/__init__.py`
```python
import pkgutil
import importlib
import logging

logger = logging.getLogger(__name__)

def _auto_import_handlers():
    """Import all handler modules"""
    import gleitzeit.handlers as pkg
    discovered = []
    
    for loader, module_name, is_pkg in pkgutil.walk_packages(pkg.__path__):
        if not is_pkg and not module_name.startswith('_'):
            try:
                importlib.import_module(f'{pkg.__name__}.{module_name}')
                discovered.append(module_name)
            except ImportError as e:
                logger.warning(f"Could not load {module_name}: {e}")
    
    return discovered

class LazyHandlerLoader:
    def __init__(self):
        self._loaded = False
    
    def _ensure_loaded(self):
        if not self._loaded:
            _auto_import_handlers()
            self._loaded = True
    
    def get_all_capabilities(self):
        self._ensure_loaded()
        from .registry import HandlerRegistry
        return HandlerRegistry.get_all_capabilities()
    
    def get_registry(self):
        self._ensure_loaded()
        from .registry import HandlerRegistry
        return HandlerRegistry

handler_loader = LazyHandlerLoader()
```

---

## Phase 2: Port Providers to Handlers (Day 1-2)

### 2.1 Port Python Provider → Handler

#### `handlers/python.py`
```python
import asyncio
import json
import tempfile
import sys
from pathlib import Path

from .base import BaseHandler
from .registry import HandlerRegistry
from ..core.models import Task, TaskResult, TaskStatus
from ..core.errors import GleitzeitError, ErrorCode

@HandlerRegistry.register
class PythonHandler(BaseHandler):
    """Execute Python code in subprocess"""

    @classmethod
    def get_capabilities(cls):
        return {
            'protocol': 'python/v1',
            'task_types': ['python', 'script', 'py'],  # For type mapping
            'methods': {
                'python/execute': {
                    'required': ['code'],
                    'optional': ['inputs', 'timeout']
                },
                'python/eval': {
                    'required': ['expression'],
                    'optional': ['context']
                },
                'python/exec_file': {
                    'required': ['file_path'],
                    'optional': ['args', 'env']
                }
            }
        }

    async def validate(self, task: Task) -> None:
        """Validate Python task"""
        await super().validate(task)  # Check method is supported

        if task.method == 'python/execute':
            if 'code' not in task.params:
                raise GleitzeitError(
                    "Missing required parameter 'code'",
                    code=ErrorCode.INVALID_PARAMS,
                    data={'task_id': task.id, 'method': task.method}
                )
        elif task.method == 'python/eval':
            if 'expression' not in task.params:
                raise GleitzeitError(
                    "Missing required parameter 'expression'",
                    code=ErrorCode.INVALID_PARAMS,
                    data={'task_id': task.id, 'method': task.method}
                )
        elif task.method == 'python/exec_file':
            if 'file_path' not in task.params:
                raise GleitzeitError(
                    "Missing required parameter 'file_path'",
                    code=ErrorCode.INVALID_PARAMS,
                    data={'task_id': task.id, 'method': task.method}
                )

    async def execute(self, task: Task) -> TaskResult:
        """Execute Python task"""
        try:
            # Validate first
            await self.validate(task)

            if task.method == 'python/execute':
                result = await self._execute_code(task)
            elif task.method == 'python/eval':
                result = await self._eval_expression(task)
            elif task.method == 'python/exec_file':
                result = await self._execute_file(task)
            else:
                raise GleitzeitError(
                    f"Unknown method: {task.method}",
                    code=ErrorCode.METHOD_NOT_SUPPORTED
                )

            return TaskResult(
                task_id=task.id,
                workflow_id=task.workflow_id,
                status=TaskStatus.COMPLETED,
                result=result
            )

        except asyncio.TimeoutError:
            return TaskResult(
                task_id=task.id,
                workflow_id=task.workflow_id,
                status=TaskStatus.FAILED,
                error=f"Task timed out after {task.timeout}s"
            )

        except GleitzeitError as e:
            return TaskResult(
                task_id=task.id,
                workflow_id=task.workflow_id,
                status=TaskStatus.FAILED,
                error=str(e),
                metadata={'error_code': e.code.value, 'error_data': e.data}
            )

        except Exception as e:
            return TaskResult(
                task_id=task.id,
                workflow_id=task.workflow_id,
                status=TaskStatus.FAILED,
                error=str(e),
                metadata={'error_type': type(e).__name__}
            )

    async def _execute_code(self, task: Task):
        """Execute Python code"""
        code = task.params['code']
        inputs = task.params.get('inputs', {})
        timeout = task.timeout or 300

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            wrapped = f'''
import json
inputs = {json.dumps(inputs)}
{code}
if 'result' in locals():
    print(json.dumps(result))
'''
            f.write(wrapped)
            path = f.name

        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable, path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )

            if process.returncode != 0:
                raise GleitzeitError(
                    f"Python execution failed: {stderr.decode()}",
                    code=ErrorCode.TASK_EXECUTION_FAILED,
                    data={'returncode': process.returncode}
                )

            output = stdout.decode().strip()
            return json.loads(output) if output else None

        finally:
            Path(path).unlink(missing_ok=True)
```

### 2.2 Port Timer Handler (System Task)

#### `handlers/timer.py`
```python
import time
from datetime import datetime

from .base import BaseHandler
from .registry import HandlerRegistry
from ..core.models import Task, TaskResult, TaskStatus
from ..core.errors import GleitzeitError, ErrorCode

@HandlerRegistry.register
class TimerHandler(BaseHandler):
    """Handle timer tasks - returns scheduling info for TimerWorker"""

    @classmethod
    def get_capabilities(cls):
        return {
            'protocol': 'timer/v1',
            'task_types': ['timer', 'sleep', 'delay'],
            'methods': {
                'timer/sleep': {'required': ['duration']},
                'timer/wait_until': {'required': ['timestamp']},
                'timer/schedule': {'required': ['interval']}
            }
        }

    async def validate(self, task: Task) -> None:
        """Validate timer task parameters"""
        await super().validate(task)

        if task.method == 'timer/sleep':
            if 'duration' not in task.params:
                raise GleitzeitError(
                    "Missing required parameter 'duration'",
                    code=ErrorCode.INVALID_PARAMS,
                    data={'task_id': task.id}
                )
            duration = task.params['duration']
            if not isinstance(duration, (int, float)) or duration < 0:
                raise GleitzeitError(
                    f"Invalid duration: {duration}",
                    code=ErrorCode.TASK_PARAMETER_ERROR,
                    data={'task_id': task.id, 'duration': duration}
                )

        elif task.method == 'timer/wait_until':
            if 'timestamp' not in task.params:
                raise GleitzeitError(
                    "Missing required parameter 'timestamp'",
                    code=ErrorCode.INVALID_PARAMS,
                    data={'task_id': task.id}
                )

    async def execute(self, task: Task) -> TaskResult:
        """Execute timer task - returns scheduling info"""
        try:
            await self.validate(task)

            if task.method == 'timer/sleep':
                duration = task.params['duration']

                if duration <= 0:
                    # Immediate completion
                    return TaskResult(
                        task_id=task.id,
                        workflow_id=task.workflow_id,
                        status=TaskStatus.COMPLETED,
                        result={'slept': 0}
                    )

                # Return SCHEDULED for TimerWorker to handle
                return TaskResult(
                    task_id=task.id,
                    workflow_id=task.workflow_id,
                    status=TaskStatus.SCHEDULED,
                    metadata={
                        'wake_time': time.time() + duration,
                        'duration': duration,
                        'timer_type': 'sleep'
                    }
                )

            elif task.method == 'timer/wait_until':
                timestamp = task.params['timestamp']

                # Parse timestamp if string
                if isinstance(timestamp, str):
                    target_time = datetime.fromisoformat(timestamp).timestamp()
                else:
                    target_time = float(timestamp)

                if target_time <= time.time():
                    # Already past target time
                    return TaskResult(
                        task_id=task.id,
                        workflow_id=task.workflow_id,
                        status=TaskStatus.COMPLETED,
                        result={'reached': True}
                    )

                return TaskResult(
                    task_id=task.id,
                    workflow_id=task.workflow_id,
                    status=TaskStatus.SCHEDULED,
                    metadata={
                        'wake_time': target_time,
                        'timer_type': 'wait_until'
                    }
                )

            elif task.method == 'timer/schedule':
                interval = task.params['interval']
                max_runs = task.params.get('max_runs', 0)

                return TaskResult(
                    task_id=task.id,
                    workflow_id=task.workflow_id,
                    status=TaskStatus.SCHEDULED,
                    metadata={
                        'wake_time': time.time() + interval,
                        'timer_type': 'schedule',
                        'interval': interval,
                        'max_runs': max_runs
                    }
                )

        except GleitzeitError:
            raise
        except Exception as e:
            raise GleitzeitError(
                f"Timer execution failed: {e}",
                code=ErrorCode.TASK_EXECUTION_FAILED,
                data={'task_id': task.id},
                cause=e
            )
```

### 2.3 Port Signal Handler (System Task)

#### `handlers/signal.py`
```python
from typing import List

from .base import BaseHandler
from .registry import HandlerRegistry
from ..core.models import Task, TaskResult, TaskStatus
from ..core.errors import GleitzeitError, ErrorCode

@HandlerRegistry.register
class SignalHandler(BaseHandler):
    """Handle signal tasks - returns waiting info for SignalWorker"""

    @classmethod
    def get_capabilities(cls):
        return {
            'protocol': 'signal/v1',
            'task_types': ['signal', 'event'],
            'methods': {
                'signal/wait': {'required': ['signal']},
                'signal/wait_any': {'required': ['signals']},
                'signal/wait_all': {'required': ['signals']}
            }
        }

    async def validate(self, task: Task) -> None:
        """Validate signal task parameters"""
        await super().validate(task)

        if task.method == 'signal/wait':
            if 'signal' not in task.params:
                raise GleitzeitError(
                    "Missing required parameter 'signal'",
                    code=ErrorCode.INVALID_PARAMS,
                    data={'task_id': task.id}
                )

        elif task.method in ['signal/wait_any', 'signal/wait_all']:
            if 'signals' not in task.params:
                raise GleitzeitError(
                    "Missing required parameter 'signals'",
                    code=ErrorCode.INVALID_PARAMS,
                    data={'task_id': task.id}
                )
            signals = task.params['signals']
            if not isinstance(signals, list) or len(signals) == 0:
                raise GleitzeitError(
                    "Parameter 'signals' must be a non-empty list",
                    code=ErrorCode.TASK_PARAMETER_ERROR,
                    data={'task_id': task.id, 'signals': signals}
                )

    async def execute(self, task: Task) -> TaskResult:
        """Execute signal task - returns waiting info"""
        try:
            await self.validate(task)

            # Collect signals to wait for
            signals: List[str] = []
            if task.method == 'signal/wait':
                signals = [task.params['signal']]
            else:
                signals = task.params['signals']

            # Get timeout from params or use default
            timeout = task.params.get('timeout', task.timeout or 3600)

            # Return WAITING for SignalWorker to handle
            return TaskResult(
                task_id=task.id,
                workflow_id=task.workflow_id,
                status=TaskStatus.WAITING,
                metadata={
                    'signals': signals,
                    'timeout': timeout,
                    'signal_type': task.method.split('/')[-1],  # wait, wait_any, wait_all
                    'started_at': time.time()
                }
            )

        except GleitzeitError:
            raise
        except Exception as e:
            raise GleitzeitError(
                f"Signal execution failed: {e}",
                code=ErrorCode.TASK_EXECUTION_FAILED,
                data={'task_id': task.id},
                cause=e
            )
```

---

## Phase 3: Update Workers (Day 2)

### 3.1 Create New TaskExecutionWorkerV4

#### `workers/task_execution_worker_v4.py`
```python
from typing import Dict, List, Any, Optional
import json
import logging

from .base import BaseWorker, WorkerConfig
from ..core.models import Task, TaskResult, TaskStatus
from ..core.errors import GleitzeitError, ErrorCode
from ..core.sharding import default_sharding
from ..handlers import handler_loader

logger = logging.getLogger(__name__)

class TaskExecutionWorkerV4(BaseWorker):
    """Task execution using handler system with Task objects"""
    
    def __init__(self, config: WorkerConfig):
        super().__init__(config)
        self.enabled_types = config.get('enabled_task_types', ['all'])
        self.handlers = {}
        self._init_handlers()
    
    def _init_handlers(self):
        """Initialize configured handlers"""
        registry = handler_loader.get_registry()
        all_caps = handler_loader.get_all_capabilities()
        
        if 'all' in self.enabled_types:
            # Load all available handlers
            for protocol, caps in all_caps.items():
                handler_class = registry.get_handler_for_protocol(protocol)
                if handler_class:
                    self.handlers[protocol] = handler_class(self.config)
                    # Also map by task types
                    for task_type in caps.get('task_types', []):
                        self.handlers[f'type:{task_type}'] = self.handlers[protocol]
        else:
            # Load only specified types
            for task_type in self.enabled_types:
                handler_class = registry.get_handler_for_type(task_type)
                if handler_class:
                    caps = handler_class.get_capabilities()
                    protocol = caps['protocol']
                    if protocol not in self.handlers:
                        self.handlers[protocol] = handler_class(self.config)
                    self.handlers[f'type:{task_type}'] = self.handlers[protocol]
        
        logger.info(f"Worker initialized with handlers: {list(self.handlers.keys())}")
    
    def get_base_streams(self) -> List[str]:
        return ["task:ready", "task:retry"]
    
    async def process_message(self, stream: str, message_id: str, data: Dict):
        """Process task with handlers"""
        workflow_id = data.get('workflow_id')
        task_id = data.get('task_id')

        try:
            # Get task object
            task_data = data.get('task')
            if isinstance(task_data, str):
                task_data = json.loads(task_data)

            # Create Task object from data
            task = Task(**task_data)

            # Ensure task has workflow_id
            if not task.workflow_id:
                task.workflow_id = workflow_id

            # Get handler by protocol
            protocol = task.protocol or self._extract_protocol(task.method)
        
            handler = self.handlers.get(protocol)

            if not handler:
                # Check for type-based fallback
                task_type = self._get_task_type(task)
                handler = self.handlers.get(f'type:{task_type}')

                if not handler:
                    # Re-queue for another worker
                    logger.debug(f"No handler for protocol={protocol}, type={task_type}, re-queuing")
                    await self.redis.xadd(stream.encode(), data)
                    return

            # Add resolved inputs to task params
            resolved_inputs = data.get('resolved_inputs', {})
            if resolved_inputs:
                task.params['inputs'] = resolved_inputs

            # Execute handler
            result = await handler.execute(task)

            # Handle different result statuses
            await self.handle_task_result(result, task.id, workflow_id)

        except GleitzeitError as e:
            logger.error(f"Task execution failed with error code {e.code.name}: {e}")
            await self.handle_task_failure(
                task_id=task.id,
                workflow_id=workflow_id,
                error=str(e),
                error_code=e.code.value,
                error_data=e.data
            )

        except Exception as e:
            logger.error(f"Unexpected error in task execution: {e}", exc_info=True)
            await self.handle_task_failure(
                task_id=task.id,
                workflow_id=workflow_id,
                error=str(e),
                error_code=ErrorCode.INTERNAL_ERROR.value
            )

    def _extract_protocol(self, method: str) -> Optional[str]:
        """Extract protocol from method name (e.g., 'python/execute' -> 'python/v1')"""
        if '/' in method:
            base = method.split('/')[0]
            return f"{base}/v1"  # Default to v1
        return None

    def _get_task_type(self, task: Task) -> Optional[str]:
        """Get task type from task for backward compatibility"""
        # Check if task has a 'type' field in params (legacy)
        return task.params.get('type')

    async def handle_task_result(self, result: TaskResult, task_id: str, workflow_id: str):
        """Handle task result based on status"""
        if result.status == TaskStatus.COMPLETED:
            await self.emit_task_completed(task_id, workflow_id, result.result)
        elif result.status == TaskStatus.FAILED:
            await self.emit_task_failed(task_id, workflow_id, result.error, result.metadata)
        elif result.status == TaskStatus.SCHEDULED:
            await self.emit_task_scheduled(task_id, workflow_id, result.metadata)
        elif result.status == TaskStatus.WAITING:
            await self.emit_task_waiting(task_id, workflow_id, result.metadata)
        else:
            logger.warning(f"Unknown task status: {result.status}")

    async def handle_task_failure(
        self,
        task_id: str,
        workflow_id: str,
        error: str,
        error_code: int = None,
        error_data: Dict = None
    ):
        """Handle task failure with error details"""
        await self.redis.hset(
            default_sharding.get_task_key(task_id, workflow_id).encode(),
            mapping={
                b"status": TaskStatus.FAILED.value.encode(),
                b"error": error.encode(),
                b"error_code": str(error_code or ErrorCode.TASK_EXECUTION_FAILED.value).encode(),
                b"error_data": json.dumps(error_data or {}).encode(),
                b"failed_at": datetime.utcnow().isoformat().encode()
            }
        )

        # Emit failure event
        await self.redis.xadd(
            default_sharding.get_stream_key("task:failed", workflow_id=workflow_id).encode(),
            {
                b"workflow_id": workflow_id.encode(),
                b"task_id": task_id.encode(),
                b"error": error.encode(),
                b"error_code": str(error_code or ErrorCode.TASK_EXECUTION_FAILED.value).encode(),
                b"timestamp": datetime.utcnow().isoformat().encode()
            }
        )
```

### 3.2 Update WorkflowLoaderWorkerV2

```python
# Add to __init__
from ..handlers import handler_loader
self.handler_registry = handler_loader.get_registry()
self.handler_capabilities = handler_loader.get_all_capabilities()

# Update type_to_protocol mapping
self.type_to_protocol = {}
for protocol, caps in self.handler_capabilities.items():
    for task_type in caps.get('task_types', []):
        self.type_to_protocol[task_type] = protocol

# Update validation to use handler capabilities
```

---

## Phase 4: Migration & Cleanup (Day 3)

### 4.1 Update Configuration

```yaml
# config/workers.yaml
workers:
  # New handler-based workers
  python_workers:
    class: TaskExecutionWorkerV4
    replicas: 5
    config:
      enabled_task_types: ["python"]
  
  coordination_workers:
    class: TaskExecutionWorkerV4
    replicas: 2
    config:
      enabled_task_types: ["timer", "signal"]
  
  general_workers:
    class: TaskExecutionWorkerV4
    replicas: 3
    config:
      enabled_task_types: ["all"]
```

### 4.2 Remove Provider System

```bash
# Files to remove
rm -rf src/gleitzeit/providers/
rm src/gleitzeit/workers/task_execution_worker_v3.py
rm src/gleitzeit/workers/provider_adapter.py

# Remove imports
# Update any remaining references
```

### 4.3 Update Tests

```python
# test_handler_system.py
async def test_handler_execution():
    from gleitzeit.handlers.python import PythonHandler
    
    handler = PythonHandler()
    result = await handler.execute({
        'code': 'result = 2 + 2',
        'inputs': {}
    })
    
    assert result.status == 'completed'
    assert result.result == 4

async def test_handler_discovery():
    from gleitzeit.handlers import handler_loader
    
    caps = handler_loader.get_all_capabilities()
    assert 'python/v1' in caps
    assert 'timer/v1' in caps
```

---

## Phase 5: Validation & Testing (Day 3-4)

### 5.1 Integration Tests

```bash
# Run existing tests with new system
python test_corrected_system.py

# Test workflow execution
python -c "
from gleitzeit.workers.workflow_loader_worker_v2 import WorkflowLoaderWorkerV2
from gleitzeit.workers.task_execution_worker_v4 import TaskExecutionWorkerV4

# Test workflow with mixed task types
workflow = {
    'name': 'test',
    'tasks': [
        {'id': '1', 'type': 'python', 'code': 'result = 42'},
        {'id': '2', 'type': 'timer', 'duration': 5},
        {'id': '3', 'type': 'signal', 'signal': 'ready'}
    ]
}
"
```

### 5.2 Performance Validation

```python
# Benchmark handler vs provider
import time

# Handler execution (direct)
start = time.time()
for _ in range(1000):
    await handler.execute(task)
handler_time = time.time() - start

# Should be faster without pool/adapter layers
```

### 5.3 Scaling Validation

```bash
# Deploy with different configurations
# Monitor metrics per handler type
# Verify type-specific scaling works
```

---

## Rollback Plan

If issues arise:

1. **Keep both systems temporarily**
   - Run TaskExecutionWorkerV3 (providers) and V4 (handlers) in parallel
   - Route by workflow tags

2. **Feature flag**
   ```python
   if config.get('use_handlers', False):
       worker = TaskExecutionWorkerV4(config)
   else:
       worker = TaskExecutionWorkerV3(config)
   ```

---

## Success Metrics

- ✅ All tests pass with handler system
- ✅ Performance improved (no pool overhead)
- ✅ Type-specific scaling works
- ✅ New handlers can be added without configuration
- ✅ Memory usage reduced (no pool instances)
- ✅ Code complexity reduced (fewer abstractions)

---

## Timeline

- **Day 1**: Create handler infrastructure, start porting providers
- **Day 2**: Complete handler ports, update workers
- **Day 3**: Migration, cleanup, initial testing
- **Day 4**: Full validation, performance testing
- **Day 5**: Deploy to production (if ready)

Total: 4-5 days for complete migration
