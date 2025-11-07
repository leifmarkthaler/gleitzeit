# TaskExecutionWorker with Handler Architecture

## Overview

Replace the complex Provider/Pool/Adapter system with a simpler, more efficient handler-based architecture that maintains clustering and enables type-specific scaling.

## Core Principles

1. **Handlers not Providers** - Lightweight, stateless execution units
2. **Maintain Sharding** - All workers read from sharded streams
3. **Type-Specific Scaling** - Workers can specialize via configuration
4. **Direct Execution** - No abstraction layers between worker and execution

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Redis Cluster                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │task:ready:0  │  │task:ready:1  │  │task:ready:2  │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
           │                 │                 │
           ▼                 ▼                 ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│TaskExecWorker-1 │ │TaskExecWorker-2 │ │TaskExecWorker-3 │
│ ┌─────────────┐ │ │ ┌─────────────┐ │ │ ┌─────────────┐ │
│ │PythonHandler│ │ │ │TimerHandler │ │ │ │HTTPHandler  │ │
│ │HTTPHandler  │ │ │ │SignalHandler│ │ │ │LLMHandler   │ │
│ └─────────────┘ │ │ └─────────────┘ │ │ └─────────────┘ │
│ enabled_types:  │ │ enabled_types:  │ │ enabled_types:  │
│ [python, http]  │ │ [timer,signal]  │ │ [http, llm]     │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

## Validation Flow

### Current System (with Providers):
1. **WorkflowLoaderWorkerV2** - Structural validation at load time
   - Validates workflow structure (required fields, dependencies)
   - Transforms tasks to protocol format
   - Does NOT validate if provider can execute

2. **Provider.validate()** - Execution validation at runtime
   - Validates parameters for execution
   - Checks resource availability
   - Provider-specific validation

### New Handler System:
1. **WorkflowLoaderWorkerV2** - Same structural validation
   - Still validates workflow structure
   - Still transforms to protocol format
   - No change needed here

2. **Handler.validate()** - Runtime validation (simpler)
   - Just validates required parameters exist
   - Basic type checking
   - Much simpler than provider validation

## Handler Interface

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple

@dataclass
class HandlerResult:
    """Result from handler execution"""
    status: str  # 'completed', 'failed', 'scheduled', 'waiting'
    result: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = None

class BaseHandler(ABC):
    """Base handler interface"""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.metrics = HandlerMetrics(self.__class__.__name__)

    @abstractmethod
    async def execute(self, task_data: Dict[str, Any]) -> HandlerResult:
        """Execute the task and return result"""
        pass

    async def validate(self, task_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validate task can be executed.

        Simple validation - just check required fields exist.
        Complex validation happens at workflow load time.

        Returns:
            (is_valid, error_message)
        """
        # Default implementation - override for specific validation
        return True, None

    async def cleanup(self):
        """Cleanup handler resources"""
        pass
```

## Handler Implementations

### PythonHandler

```python
class PythonHandler(BaseHandler):
    """Execute Python code in isolated subprocess"""
    
    def __init__(self, config=None):
        super().__init__(config)
        self.timeout = config.get('timeout', 300)
        self.max_concurrent = config.get('max_concurrent', 2)
        self.semaphore = asyncio.Semaphore(self.max_concurrent)
    
    async def execute(self, task_data: Dict) -> HandlerResult:
        async with self.semaphore:
            code = task_data.get('code', '')
            inputs = task_data.get('inputs', {})  # Pre-resolved by DependencyWorker
            
            try:
                result = await self._run_python_subprocess(code, inputs)
                return HandlerResult(
                    status='completed',
                    result=result
                )
            except asyncio.TimeoutError:
                return HandlerResult(
                    status='failed',
                    error=f'Execution timeout after {self.timeout}s'
                )
            except Exception as e:
                return HandlerResult(
                    status='failed',
                    error=str(e)
                )
    
    async def validate(self, task_data: Dict) -> Tuple[bool, Optional[str]]:
        # Simple validation - just check code exists
        # WorkflowLoader already validated structure
        if 'code' not in task_data:
            return False, "Missing 'code' parameter"
        return True, None
```

### TimerHandler

```python
class TimerHandler(BaseHandler):
    """Handle timer/delay tasks"""
    
    async def execute(self, task_data: Dict) -> HandlerResult:
        duration = task_data.get('duration', 0)
        
        if duration <= 0:
            # Immediate completion
            return HandlerResult(
                status='completed',
                result={'slept': 0}
            )
        
        # Return scheduled status for TimerWorker to handle
        wake_time = time.time() + duration
        return HandlerResult(
            status='scheduled',
            metadata={
                'wake_time': wake_time,
                'duration': duration,
                'timer_type': 'sleep'
            }
        )
    
    async def validate(self, task_data: Dict) -> Tuple[bool, Optional[str]]:
        if 'duration' not in task_data:
            return False, "Missing 'duration' parameter"
        return True, None
```

### SignalHandler

```python
class SignalHandler(BaseHandler):
    """Handle signal/event waiting"""
    
    async def execute(self, task_data: Dict) -> HandlerResult:
        signals = task_data.get('signals', [])
        if signal := task_data.get('signal'):
            signals = [signal]
        
        timeout = task_data.get('timeout', 3600)
        
        # Return waiting status for SignalWorker to handle
        return HandlerResult(
            status='waiting',
            metadata={
                'signals': signals,
                'timeout': timeout,
                'signal_type': 'wait_any' if len(signals) > 1 else 'wait'
            }
        )
    
    async def validate(self, task_data: Dict) -> Tuple[bool, Optional[str]]:
        if 'signal' not in task_data and 'signals' not in task_data:
            return False, "Missing 'signal' or 'signals' parameter"
        return True, None
```

### HTTPHandler

```python
class HTTPHandler(BaseHandler):
    """Execute HTTP requests"""
    
    def __init__(self, config=None):
        super().__init__(config)
        self.session = None
        self.max_concurrent = config.get('max_concurrent', 50)
        self.semaphore = asyncio.Semaphore(self.max_concurrent)
    
    async def execute(self, task_data: Dict) -> HandlerResult:
        async with self.semaphore:
            url = task_data.get('url')
            method = task_data.get('method', 'GET')
            headers = task_data.get('headers', {})
            body = task_data.get('body')
            
            if not self.session:
                self.session = aiohttp.ClientSession()
            
            try:
                async with self.session.request(method, url, headers=headers, json=body) as resp:
                    result = {
                        'status': resp.status,
                        'headers': dict(resp.headers),
                        'body': await resp.json() if 'json' in resp.content_type else await resp.text()
                    }
                    return HandlerResult(status='completed', result=result)
            except Exception as e:
                return HandlerResult(status='failed', error=str(e))
```

## TaskExecutionWorker Implementation

```python
class TaskExecutionWorkerV4(BaseWorker):
    """Simplified task execution with handlers"""
    
    def __init__(self, config: WorkerConfig):
        super().__init__(config)
        self.enabled_types = config.get('enabled_task_types', ['all'])
        self.handlers = {}
        self._init_handlers()
    
    def _init_handlers(self):
        """Initialize only configured handlers"""
        all_handlers = {
            'python': PythonHandler,
            'timer': TimerHandler,
            'signal': SignalHandler,
            'http': HTTPHandler,
            'shell': ShellHandler,
            'llm': LLMHandler
        }
        
        if 'all' in self.enabled_types:
            # Load all handlers
            for name, handler_class in all_handlers.items():
                self.handlers[name] = handler_class(self.config.get(f'{name}_config'))
        else:
            # Load only specified handlers
            for task_type in self.enabled_types:
                if task_type in all_handlers:
                    handler_class = all_handlers[task_type]
                    self.handlers[task_type] = handler_class(self.config.get(f'{task_type}_config'))
        
        logger.info(f"Worker initialized with handlers: {list(self.handlers.keys())}")
    
    def get_base_streams(self) -> List[str]:
        """Subscribe to sharded task:ready streams"""
        return ["task:ready", "task:retry"]
    
    async def process_message(self, stream: str, message_id: str, data: Dict):
        """Process task from stream"""
        workflow_id = data.get('workflow_id')
        task_id = data.get('task_id')
        task_data = data.get('task')
        
        if isinstance(task_data, str):
            task_data = json.loads(task_data)
        
        task_type = task_data.get('type')
        
        # Check if we handle this task type
        if task_type not in self.handlers:
            # Not our responsibility - re-queue for another worker
            logger.debug(f"Task type {task_type} not handled by this worker, re-queuing")
            await self.redis.xadd(
                stream.encode(),  # Same stream
                data
            )
            return
        
        # Execute with appropriate handler
        handler = self.handlers[task_type]
        resolved_inputs = data.get('resolved_inputs', {})
        
        # Merge resolved inputs into task data
        task_data['inputs'] = resolved_inputs
        
        try:
            # Validate first
            is_valid, error_msg = await handler.validate(task_data)
            if not is_valid:
                await self.handle_task_failure(
                    task_id, workflow_id,
                    error_msg or f"Validation failed for {task_type} task"
                )
                return
            
            # Execute
            with self.metrics.timer(f'{task_type}_execution'):
                result = await handler.execute(task_data)
            
            # Handle result based on status
            await self.handle_execution_result(
                task_id, workflow_id, task_type, result
            )
            
        except Exception as e:
            logger.error(f"Handler execution failed for task {task_id}: {e}")
            await self.handle_task_failure(task_id, workflow_id, str(e))
    
    async def handle_execution_result(
        self, 
        task_id: str, 
        workflow_id: str, 
        task_type: str,
        result: HandlerResult
    ):
        """Handle different result statuses"""
        
        if result.status == 'completed':
            # Normal completion
            await self.emit_task_completed(task_id, workflow_id, result.result)
            
        elif result.status == 'failed':
            # Task failed
            await self.handle_task_failure(task_id, workflow_id, result.error)
            
        elif result.status == 'scheduled':
            # Timer task - emit to timer worker
            await self.emit_task_scheduled(task_id, workflow_id, result.metadata)
            
        elif result.status == 'waiting':
            # Signal task - emit to signal worker
            await self.emit_task_waiting(task_id, workflow_id, result.metadata)
        
        else:
            logger.warning(f"Unknown result status: {result.status}")
    
    async def report_metrics(self):
        """Report handler-level metrics"""
        while self._running:
            metrics = {}
            for name, handler in self.handlers.items():
                metrics[name] = handler.metrics.get_snapshot()
            
            await self.redis.hset(
                f"metrics:worker:{self.worker_id}",
                mapping={
                    'enabled_types': json.dumps(self.enabled_types),
                    'handler_metrics': json.dumps(metrics),
                    'timestamp': time.time()
                }
            )
            await asyncio.sleep(10)
    
    async def cleanup(self):
        """Cleanup all handlers"""
        for handler in self.handlers.values():
            await handler.cleanup()
        await super().cleanup()
```

## Deployment Configuration

```yaml
# Python-heavy workload deployment
python_workers:
  replicas: 5
  resources:
    cpu: 4
    memory: 8Gi
  config:
    enabled_task_types: ["python", "shell"]
    python_config:
      max_concurrent: 2
      timeout: 300

# Coordination workers (lightweight)
coordination_workers:
  replicas: 2
  resources:
    cpu: 0.5
    memory: 512Mi
  config:
    enabled_task_types: ["timer", "signal"]

# I/O workers
io_workers:
  replicas: 10
  resources:
    cpu: 1
    memory: 2Gi
  config:
    enabled_task_types: ["http", "webhook"]
    http_config:
      max_concurrent: 100
      timeout: 30

# General purpose workers
general_workers:
  replicas: 3
  resources:
    cpu: 2
    memory: 4Gi
  config:
    enabled_task_types: ["all"]  # Handle any task type
```

## Benefits Over Provider System

1. **Simpler Architecture**
   - No Provider/Pool/Adapter layers
   - Direct handler execution
   - Cleaner code path

2. **Better Resource Control**
   - Per-handler concurrency limits
   - Type-specific worker deployment
   - Efficient resource usage

3. **Easier Monitoring**
   - Handler-level metrics
   - Direct performance visibility
   - Simpler debugging

4. **Flexible Scaling**
   - Deploy workers by task type
   - Scale based on actual workload
   - Mix general and specialized workers

5. **Maintains Clustering**
   - Still uses sharded streams
   - Preserves workflow locality
   - No changes to core architecture

## Migration Path

1. Keep existing provider implementations
2. Wrap them as handlers initially
3. Gradually simplify to direct execution
4. Remove provider abstraction layers

## Handler Auto-Discovery System

### Handler Registration

```python
# handlers/registry.py
class HandlerRegistry:
    """Global registry for handlers - populated automatically"""
    _handlers = {}
    _type_mapping = {}  # task_type -> handler

    @classmethod
    def register(cls, handler_class):
        """Decorator to auto-register handlers on import"""
        caps = handler_class.get_capabilities()
        protocol = caps['protocol']

        # Register by protocol
        cls._handlers[protocol] = handler_class

        # Register by task type for reverse lookup
        for task_type in caps.get('task_types', []):
            cls._type_mapping[task_type] = handler_class

        logger.info(f"Registered handler: {handler_class.__name__} for protocol {protocol}")
        return handler_class

    @classmethod
    def get_all_capabilities(cls):
        """Get capabilities from all registered handlers"""
        return {
            protocol: handler.get_capabilities()
            for protocol, handler in cls._handlers.items()
        }

    @classmethod
    def get_handler_for_type(cls, task_type: str):
        """Get handler class for a task type"""
        return cls._type_mapping.get(task_type)

    @classmethod
    def get_handler_for_protocol(cls, protocol: str):
        """Get handler class for a protocol"""
        return cls._handlers.get(protocol)
```

### Auto-Import System

```python
# handlers/__init__.py
"""
Handler package with automatic discovery.
All handler modules in this directory are automatically imported and registered.
"""
import pkgutil
import importlib
import logging

logger = logging.getLogger(__name__)

# Auto-import all handler modules in this package
def _auto_import_handlers():
    """Import all handler modules to trigger registration"""
    import gleitzeit.handlers as pkg

    discovered = []
    for loader, module_name, is_pkg in pkgutil.walk_packages(pkg.__path__):
        if not is_pkg and not module_name.startswith('_'):
            try:
                # Import triggers @register decorator
                importlib.import_module(f'{pkg.__name__}.{module_name}')
                discovered.append(module_name)
            except ImportError as e:
                # Log but don't fail - allows partial handler sets
                logger.warning(f"Could not load handler module {module_name}: {e}")

    logger.info(f"Auto-discovered handler modules: {discovered}")
    return discovered

# Lazy loader for on-demand import
class LazyHandlerLoader:
    """Lazy load handlers only when accessed"""

    def __init__(self):
        self._loaded = False
        self._discovered_modules = []

    def _ensure_loaded(self):
        """Load all handlers on first access"""
        if not self._loaded:
            self._discovered_modules = _auto_import_handlers()
            self._loaded = True

    def get_all_capabilities(self):
        """Get all handler capabilities - triggers loading"""
        self._ensure_loaded()
        from gleitzeit.handlers.registry import HandlerRegistry
        return HandlerRegistry.get_all_capabilities()

    def get_registry(self):
        """Get the handler registry"""
        self._ensure_loaded()
        from gleitzeit.handlers.registry import HandlerRegistry
        return HandlerRegistry

# Export the loader
handler_loader = LazyHandlerLoader()
```

### Handler Implementation with Registration

```python
# handlers/python.py
from gleitzeit.handlers.registry import HandlerRegistry
from gleitzeit.handlers.base import BaseHandler

@HandlerRegistry.register
class PythonHandler(BaseHandler):
    """Python code execution handler - auto-registered on import"""

    @classmethod
    def get_capabilities(cls):
        return {
            'protocol': 'python/v1',
            'task_types': ['python', 'script', 'py'],
            'methods': {
                'execute': {
                    'description': 'Execute Python code',
                    'required': ['code'],
                    'optional': ['inputs', 'timeout']
                },
                'eval': {
                    'description': 'Evaluate Python expression',
                    'required': ['expression'],
                    'optional': ['context']
                },
                'exec_file': {
                    'description': 'Execute Python file',
                    'required': ['file_path'],
                    'optional': ['args', 'env']
                }
            }
        }

    async def execute(self, task_data: Dict) -> HandlerResult:
        # Implementation...
        pass
```

### WorkflowLoader Integration

```python
# workers/workflow_loader_worker_v2.py
class WorkflowLoaderWorkerV2(BaseWorker):
    def __init__(self, config: WorkerConfig):
        super().__init__(config)

        # Auto-discover all handlers - no hardcoding!
        from gleitzeit.handlers import handler_loader
        self.handler_registry = handler_loader.get_registry()
        self.handler_capabilities = handler_loader.get_all_capabilities()

        logger.info(f"Available handlers: {list(self.handler_capabilities.keys())}")

        # Build type-to-protocol mapping
        self.type_to_protocol = {}
        for protocol, caps in self.handler_capabilities.items():
            for task_type in caps.get('task_types', []):
                self.type_to_protocol[task_type] = protocol

    async def transform_task(self, raw_task: Dict, workflow_id: str) -> Dict:
        """Transform raw task with handler validation"""
        task_type = raw_task.get('type', 'python')

        # Get protocol from type mapping or use explicit protocol
        protocol = raw_task.get('protocol')
        if not protocol:
            protocol = self.type_to_protocol.get(task_type)
            if not protocol:
                raise WorkflowValidationError(f"Unknown task type: {task_type}")

        # Validate against handler capabilities
        if protocol not in self.handler_capabilities:
            raise WorkflowValidationError(f"No handler for protocol: {protocol}")

        caps = self.handler_capabilities[protocol]
        method = raw_task.get('method', self._get_default_method(caps))

        # Validate method exists
        if method not in caps.get('methods', {}):
            available = list(caps.get('methods', {}).keys())
            raise WorkflowValidationError(
                f"Method '{method}' not supported by {protocol}. "
                f"Available methods: {available}"
            )

        # Validate required parameters
        method_spec = caps['methods'][method]
        params = raw_task.get('params', {})

        for required_param in method_spec.get('required', []):
            if required_param not in params:
                raise WorkflowValidationError(
                    f"Task '{raw_task.get('id')}' missing required parameter "
                    f"'{required_param}' for {protocol}.{method}"
                )

        # Build validated task
        return {
            'id': raw_task.get('id', str(uuid.uuid4())),
            'workflow_id': workflow_id,
            'type': task_type,
            'protocol': protocol,
            'method': method,
            'params': params,
            'dependencies': raw_task.get('dependencies', []),
            'timeout': raw_task.get('timeout', 300)
        }

    def _get_default_method(self, capabilities: Dict) -> str:
        """Get default method for a handler"""
        methods = capabilities.get('methods', {})
        if methods:
            # Use 'execute' if available, otherwise first method
            return 'execute' if 'execute' in methods else list(methods.keys())[0]
        return 'execute'
```

### Adding New Handlers

To add a new handler, simply create a new file in the `handlers/` directory:

```python
# handlers/custom.py
from gleitzeit.handlers.registry import HandlerRegistry
from gleitzeit.handlers.base import BaseHandler

@HandlerRegistry.register
class CustomHandler(BaseHandler):
    """Custom handler - automatically discovered and registered!"""

    @classmethod
    def get_capabilities(cls):
        return {
            'protocol': 'custom/v1',
            'task_types': ['custom', 'special'],
            'methods': {
                'process': {
                    'description': 'Process custom task',
                    'required': ['data'],
                    'optional': ['options']
                }
            }
        }

    async def execute(self, task_data: Dict) -> HandlerResult:
        # Your implementation here
        pass

# That's it! No registration code needed elsewhere
```

The handler is automatically:
1. Discovered when the handlers package is imported
2. Registered with its capabilities
3. Available in WorkflowLoader for validation
4. Available in TaskExecutionWorker for execution

### Benefits

1. **Zero Configuration** - Just add a file with `@register`
2. **No Hardcoding** - WorkflowLoader discovers handlers dynamically
3. **Extensible** - Easy to add custom handlers
4. **Validation** - WorkflowLoader validates against actual handler capabilities
5. **Type Mapping** - Automatic task type to protocol mapping
6. **Clean Separation** - Handlers define capabilities, WorkflowLoader validates

## Future Enhancements

1. **Handler Plugins** - Load handlers dynamically
2. **Handler Composition** - Chain handlers for complex tasks
3. **Handler Versioning** - Support multiple handler versions
4. **Cross-handler Communication** - Shared state/cache between handlers
