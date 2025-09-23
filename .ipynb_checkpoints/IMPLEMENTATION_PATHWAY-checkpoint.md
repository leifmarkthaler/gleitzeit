# Implementation Pathway: Providers → Handlers

## Overview
Complete migration from the complex Provider/Pool/Adapter system to the simpler Handler architecture.
**No backwards compatibility needed** - clean replacement.

## Current State
- Providers: Complex with pools, adapters, orchestrators
- Workers: Use ProviderAdapter to execute tasks
- State: All providers return TaskResult (recent fix)

## Target State  
- Handlers: Simple, stateless executors with auto-discovery
- Workers: Direct handler execution
- Validation: Handler capabilities drive workflow validation

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
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple

@dataclass
class HandlerResult:
    """Unified result from handler execution"""
    status: str  # 'completed', 'failed', 'scheduled', 'waiting'
    result: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = None

class BaseHandler(ABC):
    """Base handler interface"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        from .metrics import HandlerMetrics
        self.metrics = HandlerMetrics(self.__class__.__name__)
    
    @classmethod
    @abstractmethod
    def get_capabilities(cls) -> Dict:
        """Return handler capabilities for discovery"""
        pass
    
    @abstractmethod
    async def execute(self, task_data: Dict[str, Any]) -> HandlerResult:
        """Execute task and return result"""
        pass
    
    async def validate(self, task_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Simple validation - default accepts all"""
        return True, None
    
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
from typing import Dict, Any, Tuple, Optional

from .base import BaseHandler, HandlerResult
from .registry import HandlerRegistry

@HandlerRegistry.register
class PythonHandler(BaseHandler):
    """Execute Python code in subprocess"""
    
    @classmethod
    def get_capabilities(cls):
        return {
            'protocol': 'python/v1',
            'task_types': ['python', 'script', 'py'],
            'methods': {
                'execute': {
                    'required': ['code'],
                    'optional': ['inputs', 'timeout']
                }
            }
        }
    
    async def validate(self, task_data: Dict) -> Tuple[bool, Optional[str]]:
        if 'code' not in task_data:
            return False, "Missing 'code' parameter"
        return True, None
    
    async def execute(self, task_data: Dict) -> HandlerResult:
        code = task_data.get('code', '')
        inputs = task_data.get('inputs', {})
        timeout = task_data.get('timeout', 300)
        
        try:
            result = await self._run_python(code, inputs, timeout)
            return HandlerResult(status='completed', result=result)
        except asyncio.TimeoutError:
            return HandlerResult(status='failed', error=f'Timeout after {timeout}s')
        except Exception as e:
            return HandlerResult(status='failed', error=str(e))
    
    async def _run_python(self, code: str, inputs: Dict, timeout: int):
        # Copy implementation from PythonProvider._exec_code
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
        
        process = await asyncio.create_subprocess_exec(
            sys.executable, path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )
        
        if process.returncode != 0:
            raise Exception(f"Python error: {stderr.decode()}")
        
        output = stdout.decode().strip()
        return json.loads(output) if output else None
```

### 2.2 Port Timer Handler (System Task)

#### `handlers/timer.py`
```python
import time
from .base import BaseHandler, HandlerResult
from .registry import HandlerRegistry

@HandlerRegistry.register
class TimerHandler(BaseHandler):
    """Handle timer tasks - returns scheduling info"""
    
    @classmethod
    def get_capabilities(cls):
        return {
            'protocol': 'timer/v1',
            'task_types': ['timer', 'sleep', 'delay'],
            'methods': {
                'sleep': {'required': ['duration']},
                'wait_until': {'required': ['timestamp']},
                'schedule': {'required': ['interval']}
            }
        }
    
    async def execute(self, task_data: Dict) -> HandlerResult:
        method = task_data.get('method', 'sleep')
        
        if method == 'sleep':
            duration = task_data.get('duration', 0)
            if duration <= 0:
                return HandlerResult(status='completed', result={'slept': 0})
            
            return HandlerResult(
                status='scheduled',
                metadata={
                    'wake_time': time.time() + duration,
                    'duration': duration,
                    'timer_type': 'sleep'
                }
            )
        
        # Similar for wait_until and schedule...
```

### 2.3 Port Signal Handler (System Task)

#### `handlers/signal.py`
```python
from .base import BaseHandler, HandlerResult
from .registry import HandlerRegistry

@HandlerRegistry.register
class SignalHandler(BaseHandler):
    """Handle signal tasks - returns waiting info"""
    
    @classmethod
    def get_capabilities(cls):
        return {
            'protocol': 'signal/v1',
            'task_types': ['signal', 'event'],
            'methods': {
                'wait': {'required': ['signal']},
                'wait_any': {'required': ['signals']}
            }
        }
    
    async def execute(self, task_data: Dict) -> HandlerResult:
        signals = task_data.get('signals', [])
        if signal := task_data.get('signal'):
            signals = [signal]
        
        return HandlerResult(
            status='waiting',
            metadata={
                'signals': signals,
                'timeout': task_data.get('timeout', 3600)
            }
        )
```

---

## Phase 3: Update Workers (Day 2)

### 3.1 Create New TaskExecutionWorkerV4

#### `workers/task_execution_worker_v4.py`
```python
from typing import Dict, List, Any
import json
import logging

from .base import BaseWorker, WorkerConfig
from ..core.models import TaskStatus, TaskResult
from ..handlers import handler_loader

logger = logging.getLogger(__name__)

class TaskExecutionWorkerV4(BaseWorker):
    """Task execution using handler system"""
    
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
        task_data = data.get('task')
        
        if isinstance(task_data, str):
            task_data = json.loads(task_data)
        
        # Get handler by protocol or type
        protocol = task_data.get('protocol')
        task_type = task_data.get('type')
        
        handler = self.handlers.get(protocol) or self.handlers.get(f'type:{task_type}')
        
        if not handler:
            # Re-queue for another worker
            logger.debug(f"No handler for {protocol}/{task_type}, re-queuing")
            await self.redis.xadd(stream.encode(), data)
            return
        
        # Add resolved inputs to task data
        task_data['inputs'] = data.get('resolved_inputs', {})
        
        try:
            # Validate
            is_valid, error = await handler.validate(task_data)
            if not is_valid:
                await self.handle_task_failure(task_id, workflow_id, error)
                return
            
            # Execute
            result = await handler.execute(task_data)
            
            # Convert HandlerResult to TaskResult
            if result.status == 'completed':
                task_result = TaskResult(
                    task_id=task_id,
                    status=TaskStatus.COMPLETED,
                    result=result.result
                )
            elif result.status == 'failed':
                task_result = TaskResult(
                    task_id=task_id,
                    status=TaskStatus.FAILED,
                    error=result.error
                )
            elif result.status == 'scheduled':
                task_result = TaskResult(
                    task_id=task_id,
                    status=TaskStatus.SCHEDULED,
                    metadata=result.metadata
                )
            elif result.status == 'waiting':
                task_result = TaskResult(
                    task_id=task_id,
                    status=TaskStatus.WAITING,
                    metadata=result.metadata
                )
            
            # Handle result
            await self.handle_task_result(task_result, task_id, workflow_id)
            
        except Exception as e:
            logger.error(f"Handler execution failed: {e}")
            await self.handle_task_failure(task_id, workflow_id, str(e))
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
