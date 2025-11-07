# Gleitzeit Handler System Documentation

## Overview

The Gleitzeit Handler System is a dynamic, plugin-based architecture for executing tasks in distributed workflows. Handlers are stateless executors that process specific task types and return standardized results.

## Architecture

### Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                    Handler Registry                          │
│  (Auto-discovers and registers handlers at import)           │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  │ Registers via @decorator
                  ▼
┌─────────────────────────────────────────────────────────────┐
│                      Handler Classes                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │PythonHandler │  │TimerHandler  │  │SignalHandler │ ... │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
                  │
                  │ Validates & Executes
                  ▼
┌─────────────────────────────────────────────────────────────┐
│                         Tasks                                │
│  (Pydantic models with protocol/method/params)               │
└─────────────────────────────────────────────────────────────┘
                  │
                  │ Returns
                  ▼
┌─────────────────────────────────────────────────────────────┐
│                      TaskResult                              │
│  (Status: COMPLETED/FAILED/SCHEDULED/WAITING)                │
└─────────────────────────────────────────────────────────────┘
```

### Key Design Principles

1. **Stateless Execution**: Handlers are stateless and can be instantiated per request
2. **Auto-Discovery**: Handlers self-register via decorators when imported
3. **Protocol-Based**: Each handler declares its protocol and supported methods
4. **Type Safety**: Uses Pydantic models for Tasks and TaskResults
5. **Centralized Errors**: Uses GleitzeitError with ErrorCode enums

## Handler Implementation

### Creating a New Handler

```python
from gleitzeit.handlers.base import BaseHandler
from gleitzeit.handlers.registry import HandlerRegistry
from gleitzeit.core.models import Task, TaskResult, TaskStatus
from gleitzeit.core.errors import GleitzeitError, ErrorCode

@HandlerRegistry.register
class MyHandler(BaseHandler):
    """Handle my custom task type"""
    
    @classmethod
    def get_capabilities(cls) -> Dict[str, Any]:
        """Declare what this handler can do"""
        return {
            'protocol': 'mytype/v1',
            'task_types': ['mytype', 'custom'],  # Legacy task type mapping
            'methods': {
                'mytype/process': {
                    'description': 'Process custom data',
                    'required': ['data'],
                    'optional': ['format']
                },
                'mytype/validate': {
                    'description': 'Validate custom data',
                    'required': ['data']
                }
            }
        }
    
    async def validate(self, task: Task) -> None:
        """Validate task parameters"""
        await super().validate(task)  # Base validation
        
        # Custom validation
        if task.method == 'mytype/process':
            if 'data' not in task.params:
                raise GleitzeitError(
                    "Missing required parameter 'data'",
                    code=ErrorCode.INVALID_PARAMS,
                    data={'task_id': task.id}
                )
    
    async def execute(self, task: Task) -> TaskResult:
        """Execute the task"""
        try:
            # Validate
            await self.validate(task)
            
            # Process based on method
            if task.method == 'mytype/process':
                result = await self._process_data(task)
            elif task.method == 'mytype/validate':
                result = await self._validate_data(task)
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
            
        except GleitzeitError:
            raise
        except Exception as e:
            raise GleitzeitError(
                f"Execution failed: {e}",
                code=ErrorCode.TASK_EXECUTION_FAILED,
                cause=e
            )
```

### Handler Registration

Handlers are automatically registered when their module is imported:

```python
# In handlers/__init__.py
from gleitzeit.handlers import handler_loader

# This triggers auto-import of all handler modules
capabilities = handler_loader.get_all_capabilities()
```

## Core Handlers

### PythonHandler

**Protocol**: `python/v1`
**Task Types**: `python`, `script`, `py`

**Methods**:
- `python/execute`: Execute Python code block
- `python/eval`: Evaluate Python expression
- `python/exec_file`: Execute Python file

**Execution**: Runs Python code in isolated subprocess for safety

### TimerHandler

**Protocol**: `timer/v1`
**Task Types**: `timer`, `sleep`, `delay`, `schedule`

**Methods**:
- `timer/sleep`: Sleep for duration
- `timer/wait_until`: Wait until timestamp
- `timer/schedule`: Schedule recurring execution

**Returns**: `TaskStatus.SCHEDULED` for TimerWorker to handle actual waiting

### SignalHandler

**Protocol**: `signal/v1`
**Task Types**: `signal`, `sync`, `event`

**Methods**:
- `signal/wait`: Wait for single signal
- `signal/wait_any`: Wait for any of multiple signals
- `signal/wait_all`: Wait for all signals
- `signal/send`: Send signal to current or specific workflows (NEW)
- `signal/broadcast`: Broadcast signal system-wide (NEW)

**Returns**:
- Wait methods: `TaskStatus.WAITING` for SignalWorker to handle coordination
- Send/Broadcast methods: `TaskStatus.COMPLETED` with emission metadata

## Integration with Workers

### WorkflowLoaderWorkerV2

The workflow loader dynamically discovers handlers at startup:

```python
def _build_protocol_mappings(self):
    """Build protocol mappings from handler registry"""
    capabilities = handler_loader.get_all_capabilities()
    
    for protocol, caps in capabilities.items():
        # Map task types to protocols
        for task_type in caps.get('task_types', []):
            self.type_to_protocol[task_type] = protocol
        
        # Track supported methods for validation
        self.supported_methods[protocol] = caps.get('methods', {})
```

**Validation** checks:
- Protocol is supported (registered handler exists)
- Method is supported by the protocol
- Required parameters are present

### TaskExecutionWorker

The execution worker uses handlers to process tasks:

```python
async def execute_task(self, task: Task) -> TaskResult:
    """Execute task using appropriate handler"""
    # Get handler for protocol
    handler_class = HandlerRegistry.get_handler(task.protocol)
    if not handler_class:
        return TaskResult(
            task_id=task.id,
            status=TaskStatus.FAILED,
            error=f"No handler for protocol {task.protocol}"
        )
    
    # Create handler instance
    handler = handler_class(config=self.handler_config)
    
    # Execute
    return await handler.execute(task)
```

## Task Flow

1. **Workflow Definition** (YAML/JSON/Python)
   ```yaml
   tasks:
     - name: compute
       type: python
       code: "result = 2 + 2"
   ```

2. **WorkflowLoader** transforms to protocol-based task:
   ```python
   {
       'id': 'compute',
       'protocol': 'python/v1',  # From handler registry
       'method': 'python/execute',  # Default for type
       'params': {'code': 'result = 2 + 2'}
   }
   ```

3. **Validation** ensures protocol and method are supported

4. **TaskExecutionWorker** routes to PythonHandler

5. **Handler** validates, executes, returns TaskResult

6. **Worker** processes result, updates workflow state

## Benefits of Handler Architecture

1. **Extensibility**: Add new task types by creating handlers
2. **Auto-Discovery**: No configuration needed for new handlers
3. **Type Safety**: Pydantic models ensure data consistency
4. **Separation of Concerns**: Handlers focus on execution, Workers on orchestration
5. **Dynamic Validation**: Workflows validated against actual capabilities
6. **No Hardcoding**: System adapts to available handlers

## Testing

### Unit Testing a Handler

```python
async def test_handler():
    handler = MyHandler(config={})
    
    task = Task(
        id="test-1",
        name="Test Task",
        workflow_id="test-workflow",
        protocol="mytype/v1",
        method="mytype/process",
        params={'data': 'test'}
    )
    
    result = await handler.execute(task)
    assert result.status == TaskStatus.COMPLETED
```

### Integration Testing

```python
# Test discovery
capabilities = handler_loader.get_all_capabilities()
assert 'mytype/v1' in capabilities

# Test registration
handler_class = HandlerRegistry.get_handler('mytype/v1')
assert handler_class is not None

# Test method lookup
handler = HandlerRegistry.get_handler_for_method('mytype/process')
assert handler == MyHandler
```

## Migration from Provider System

The handler system replaces the previous provider architecture:

**Before** (Provider System):
- Providers with pools and adapters
- Complex initialization
- Hardcoded type mappings
- Stateful execution

**After** (Handler System):
- Simple handler classes
- Auto-discovery via decorators
- Dynamic type mappings
- Stateless execution

## Future Enhancements

1. **Handler Composition**: Chain handlers for complex operations
2. **Handler Middleware**: Add logging, metrics, retries
3. **Handler Versioning**: Support multiple protocol versions
4. **Handler Hot-Reload**: Update handlers without restart
5. **Handler Marketplace**: Share handlers as plugins

## Signal Handler Examples (NEW)

### Sending Signals Within Workflows

The SignalHandler now supports sending signals in addition to waiting for them:

#### 1. Send to Current Workflow (Default)
```yaml
tasks:
  - id: process_data
    type: python
    code: "# Process data"
  
  - id: notify_complete
    type: signal
    signal_action: send  # NEW
    signal_name: processing-done
    payload:
      status: success
    dependencies: [process_data]
  
  - id: cleanup
    type: signal
    signal_action: wait
    signal_name: processing-done
    dependencies: [notify_complete]
```

#### 2. Send to Specific Workflows
```yaml
tasks:
  - id: notify_others
    type: signal
    signal_action: send
    signal_name: data-ready
    target_workflows: ['workflow-123', 'workflow-456']  # NEW
    payload:
      location: /data/output.json
```

#### 3. Broadcast System-Wide
```yaml
tasks:
  - id: system_alert
    type: signal
    signal_action: broadcast  # NEW
    signal_name: maintenance-mode
    payload:
      message: System maintenance starting
      duration: 3600
```

### Key Changes

1. **signal_action** now supports:
   - `wait` - Wait for signal (existing)
   - `wait_any` - Wait for any signal (existing)  
   - `wait_all` - Wait for all signals (existing)
   - `send` - Send to workflow(s) (NEW)
   - `broadcast` - Broadcast system-wide (NEW)

2. **Scoping**:
   - `send` without `target_workflows` → Current workflow only
   - `send` with `target_workflows` → Specified workflows only
   - `broadcast` → All workflows (no restrictions)

3. **Implementation**:
   - SignalHandler returns `COMPLETED` with `emit_signal: true` metadata
   - TaskExecutionWorker detects flag and emits via StatelessSignalManager
   - Maintains stateless handler architecture

For complete documentation, see: `docs/SIGNAL_SEND_BROADCAST.md`
