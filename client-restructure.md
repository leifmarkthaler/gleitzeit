# GleitzeitClient Restructuring Plan

**Status: PLANNED** - Not yet implemented. Current refactoring has added 34 public methods to support thin-layer architecture, but modularization is still pending.

## Current State Analysis

The `GleitzeitClient` class has grown to **3,712 lines** with **100+ methods**, making it difficult to maintain and extend. The class currently handles:

- API/Native mode switching
- Server lifecycle management
- Workflow operations
- Task operations
- Queue management
- Authentication & user management
- Resource management
- Logging operations
- Event error handling
- Batch processing
- Directory operations
- Chat functionality
- Persistence operations

## Problems with Current Structure

1. **Monolithic Design**: Single class handling too many responsibilities
2. **Code Duplication**: Many methods have `_api` and `_native` variants
3. **Poor Separation of Concerns**: Business logic mixed with transport logic
4. **Hard to Test**: Large surface area makes unit testing difficult
5. **Difficult Navigation**: Finding specific functionality requires scrolling through thousands of lines

## Proposed Modular Architecture

### 1. Core Client Structure

```
src/gleitzeit/client/
├── __init__.py              # Export main GleitzeitClient
├── base.py                  # Base client with core functionality
├── mixins/                  # Modular functionality mixins
│   ├── __init__.py
│   ├── workflow.py          # WorkflowMixin
│   ├── task.py             # TaskMixin  
│   ├── queue.py            # QueueMixin
│   ├── auth.py             # AuthMixin
│   ├── resource.py         # ResourceMixin
│   ├── batch.py            # BatchProcessingMixin
│   ├── logging.py          # LoggingMixin
│   └── events.py           # EventErrorMixin
├── adapters/               # Mode-specific adapters
│   ├── __init__.py
│   ├── base.py            # BaseAdapter interface
│   ├── api.py             # APIAdapter
│   └── native.py          # NativeAdapter
├── models/                 # Client-specific models
│   ├── __init__.py
│   └── responses.py       # Response models
└── utils/                  # Utility functions
    ├── __init__.py
    ├── server.py          # Server management utilities
    └── validation.py      # Input validation
```

### 2. Mixin-Based Design

Each mixin handles a specific domain:

```python
# mixins/workflow.py
class WorkflowMixin:
    """Workflow-related operations"""
    
    async def submit_workflow(self, workflow: Workflow) -> Dict[str, Any]:
        return await self._adapter.submit_workflow(workflow)
    
    async def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        return await self._adapter.get_workflow(workflow_id)
    
    async def list_workflows(self, **filters) -> Dict[str, Any]:
        return await self._adapter.list_workflows(**filters)
    
    async def cancel_workflow(self, workflow_id: str) -> Dict[str, Any]:
        return await self._adapter.cancel_workflow(workflow_id)
    
    async def pause_workflow(self, workflow_id: str) -> Dict[str, Any]:
        return await self._adapter.pause_workflow(workflow_id)
    
    async def resume_workflow(self, workflow_id: str) -> Dict[str, Any]:
        return await self._adapter.resume_workflow(workflow_id)
```

### 3. Adapter Pattern for Mode Switching

```python
# adapters/base.py
from abc import ABC, abstractmethod

class BaseAdapter(ABC):
    """Abstract base for mode adapters"""
    
    @abstractmethod
    async def submit_workflow(self, workflow: Workflow) -> Dict[str, Any]:
        pass
    
    @abstractmethod
    async def get_task(self, task_id: str) -> Optional[Task]:
        pass
    
    # ... other abstract methods
```

```python
# adapters/api.py
class APIAdapter(BaseAdapter):
    """API mode implementation"""
    
    def __init__(self, host: str, port: int):
        self.base_url = f"http://{host}:{port}"
        self.session = None
    
    async def submit_workflow(self, workflow: Workflow) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/workflows",
                json=workflow.dict()
            ) as response:
                return await response.json()
```

### 4. Simplified Main Client

```python
# base.py
from typing import Optional, Union
from enum import Enum

class ClientMode(Enum):
    AUTO = "auto"
    API = "api"
    NATIVE = "native"

class GleitzeitClient(
    WorkflowMixin,
    TaskMixin,
    QueueMixin,
    AuthMixin,
    ResourceMixin,
    BatchProcessingMixin,
    LoggingMixin,
    EventErrorMixin
):
    """Streamlined Gleitzeit client with modular functionality"""
    
    def __init__(
        self,
        mode: Union[str, ClientMode] = ClientMode.AUTO,
        api_host: str = "localhost",
        api_port: int = 8000,
        **kwargs
    ):
        self.mode = ClientMode(mode) if isinstance(mode, str) else mode
        self.api_host = api_host
        self.api_port = api_port
        self._adapter: Optional[BaseAdapter] = None
        self._config = kwargs
    
    async def __aenter__(self):
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.shutdown()
    
    async def initialize(self):
        """Initialize the appropriate adapter based on mode"""
        if self.mode == ClientMode.AUTO:
            self.mode = await self._detect_best_mode()
        
        if self.mode == ClientMode.API:
            self._adapter = APIAdapter(self.api_host, self.api_port)
        else:
            self._adapter = NativeAdapter(self._config)
        
        await self._adapter.initialize()
    
    async def shutdown(self):
        """Clean shutdown"""
        if self._adapter:
            await self._adapter.shutdown()
    
    def get_mode(self) -> str:
        """Get current operating mode"""
        return self.mode.value
```

## Implementation Benefits

### 1. **Improved Maintainability**
- Each mixin is responsible for one domain
- Easier to locate and modify specific functionality
- Reduced cognitive load when working on features

### 2. **Better Testing**
- Each mixin can be tested independently
- Adapters can be mocked easily
- Smaller test surface area per component

### 3. **Enhanced Extensibility**
- New features can be added as new mixins
- New transport modes can be added as adapters
- No need to modify existing code for new functionality

### 4. **Cleaner Code Organization**
- Logical grouping of related functionality
- Clear separation between business logic and transport
- Reduced file sizes (each mixin ~200-400 lines)

### 5. **Type Safety**
- Better type hints with smaller, focused interfaces
- Easier to maintain type consistency
- Protocol/ABC enforcement for adapters

## Migration Strategy

### Phase 1: Create Structure (Week 1)
1. Create new directory structure
2. Implement base classes and interfaces
3. Create adapter pattern framework

### Phase 2: Extract Mixins (Week 2-3)
1. Extract workflow operations → WorkflowMixin
2. Extract task operations → TaskMixin
3. Extract auth operations → AuthMixin
4. Extract remaining domains to mixins

### Phase 3: Implement Adapters (Week 3-4)
1. Create APIAdapter with all API calls
2. Create NativeAdapter with native implementations
3. Remove duplicate `_api` and `_native` methods

### Phase 4: Testing & Migration (Week 4-5)
1. Create comprehensive tests for each mixin
2. Create adapter tests
3. Update existing code to use new client
4. Deprecation warnings for old client

### Phase 5: Cleanup (Week 5-6)
1. Remove old monolithic client
2. Update documentation
3. Update examples

## Backward Compatibility

To maintain backward compatibility during migration:

```python
# __init__.py
from .base import GleitzeitClient as NewClient
from .legacy import GleitzeitClient as LegacyClient

class GleitzeitClient(NewClient):
    """Facade that provides backward compatibility"""
    
    def __init__(self, *args, use_legacy=False, **kwargs):
        if use_legacy:
            warnings.warn(
                "Legacy client is deprecated and will be removed in v1.0",
                DeprecationWarning
            )
            self.__class__ = LegacyClient
            LegacyClient.__init__(self, *args, **kwargs)
        else:
            super().__init__(*args, **kwargs)
```

## Example Usage After Restructuring

```python
from gleitzeit import GleitzeitClient

async with GleitzeitClient(mode="auto") as client:
    # Workflow operations (from WorkflowMixin)
    workflow = await client.submit_workflow(my_workflow)
    status = await client.get_workflow(workflow.id)
    
    # Task operations (from TaskMixin)
    task = await client.submit_task(my_task)
    result = await client.wait_for_task(task.id)
    
    # Batch operations (from BatchProcessingMixin)
    results = await client.batch_process(
        directory="/data",
        pattern="*.txt",
        prompt="Summarize"
    )
    
    # Auth operations (from AuthMixin)
    await client.login("user", "pass")
    user = await client.get_current_user()
```

## Additional Improvements

### 1. **Async Context Managers for Resources**
```python
async with client.allocate_resource("gpu", task_id) as resource:
    # Resource automatically released on exit
    await process_with_resource(resource)
```

### 2. **Stream Processing Support**
```python
async for event in client.stream_workflow_events(workflow_id):
    print(f"Event: {event.type} - {event.data}")
```

### 3. **Batch Operations with Progress**
```python
async for progress in client.batch_process_with_progress(directory, pattern):
    print(f"Processed {progress.completed}/{progress.total}")
```

### 4. **Plugin System**
```python
from gleitzeit.client.plugins import CustomPlugin

client.register_plugin(CustomPlugin())
await client.custom_operation()  # Added by plugin
```

## Performance Considerations

1. **Connection Pooling**: Reuse HTTP connections in APIAdapter
2. **Lazy Loading**: Load mixins only when needed
3. **Caching**: Add caching layer for frequently accessed data
4. **Batch Operations**: Optimize batch API calls
5. **Async Optimizations**: Use asyncio.gather() for parallel operations

## Conclusion

This restructuring plan will transform the monolithic 3,712-line GleitzeitClient into a modular, maintainable, and extensible architecture. The mixin-based design with adapter pattern provides:

- Clear separation of concerns
- Easy testing and maintenance
- Flexible extensibility
- Better performance
- Improved developer experience

The phased migration approach ensures backward compatibility while gradually moving to the new architecture. This investment will significantly improve code quality and development velocity for future features.