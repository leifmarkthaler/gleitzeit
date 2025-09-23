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

## Handler Interface

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, Optional

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
    
    @abstractmethod
    async def validate(self, task_data: Dict[str, Any]) -> bool:
        """Validate task can be executed"""
        pass
    
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
    
    async def validate(self, task_data: Dict) -> bool:
        # Check for required fields and valid Python syntax
        return 'code' in task_data
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
    
    async def validate(self, task_data: Dict) -> bool:
        return 'duration' in task_data
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
    
    async def validate(self, task_data: Dict) -> bool:
        return 'signal' in task_data or 'signals' in task_data
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
            if not await handler.validate(task_data):
                await self.handle_task_failure(
                    task_id, workflow_id, 
                    f"Validation failed for {task_type} task"
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

## Handler Registry (Optional)

```python
# For dynamic handler discovery
class HandlerRegistry:
    handlers = {}
    
    @classmethod
    def register(cls, task_type: str):
        def decorator(handler_class):
            cls.handlers[task_type] = handler_class
            return handler_class
        return decorator
    
    @classmethod
    def get(cls, task_type: str):
        return cls.handlers.get(task_type)

# Usage
@HandlerRegistry.register('python')
class PythonHandler(BaseHandler):
    ...
```

## Future Enhancements

1. **Handler Plugins** - Load handlers dynamically
2. **Handler Composition** - Chain handlers for complex tasks
3. **Handler Versioning** - Support multiple handler versions
4. **Cross-handler Communication** - Shared state/cache between handlers
