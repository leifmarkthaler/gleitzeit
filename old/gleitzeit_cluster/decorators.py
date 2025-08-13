"""
Gleitzeit Decorators - Simple Socket.IO-based task registration

Allows any Python function to become a Gleitzeit task with a simple decorator.
"""

import asyncio
import functools
import inspect
from typing import Any, Callable, Dict, Optional, List
from pathlib import Path

from .core.external_service_node import ExternalServiceNode, ExternalServiceCapability


# Global registry for decorated functions
_decorated_functions: Dict[str, Callable] = {}
_service_instance: Optional[ExternalServiceNode] = None


def gleitzeit_task(
    name: Optional[str] = None,
    category: str = "custom",
    description: Optional[str] = None,
    timeout: int = 300
):
    """
    Decorator to register a Python function as a Gleitzeit task.
    
    Usage:
        @gleitzeit_task(name="process_data", category="data")
        def my_function(data):
            return processed_data
    
    The function automatically becomes available as a task in workflows.
    """
    def decorator(func: Callable) -> Callable:
        task_name = name or func.__name__
        task_description = description or func.__doc__ or f"Task: {task_name}"
        
        # Register in global registry
        _decorated_functions[task_name] = {
            'function': func,
            'category': category,
            'description': task_description,
            'timeout': timeout,
            'is_async': asyncio.iscoroutinefunction(func)
        }
        
        # Wrapper maintains original function behavior
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            if asyncio.iscoroutinefunction(func):
                loop = asyncio.get_event_loop()
                return loop.run_until_complete(func(*args, **kwargs))
            else:
                return func(*args, **kwargs)
        
        # Return appropriate wrapper
        if asyncio.iscoroutinefunction(func):
            wrapper = async_wrapper
        else:
            wrapper = sync_wrapper
            
        # Store metadata
        wrapper._gleitzeit_task = True
        wrapper._task_name = task_name
        wrapper._task_category = category
        wrapper._task_description = task_description
        wrapper._task_timeout = timeout
        
        return wrapper
    
    return decorator


class GleitzeitTaskService(ExternalServiceNode):
    """
    Auto-configured service for decorated tasks.
    Automatically discovers and registers all @gleitzeit_task decorated functions.
    """
    
    def __init__(
        self,
        service_name: str = "Python Tasks",
        cluster_url: str = "http://localhost:8000",
        auto_discover: bool = True,
        search_paths: List[str] = None
    ):
        super().__init__(
            service_name=service_name,
            cluster_url=cluster_url,
            capabilities=[
                ExternalServiceCapability.PYTHON_EXECUTION,
                ExternalServiceCapability.CUSTOM_PROCESSING
            ],
            max_concurrent_tasks=10
        )
        
        self.search_paths = search_paths or ["."]
        
        # Register all decorated functions
        self._register_decorated_functions()
        
        # Auto-discover if enabled
        if auto_discover:
            self._auto_discover_tasks()
    
    def _register_decorated_functions(self):
        """Register all functions decorated with @gleitzeit_task"""
        for task_name, task_info in _decorated_functions.items():
            self.register_task_handler(task_name, self._create_handler(task_info))
            print(f"📌 Registered task: {task_name} ({task_info['category']})")
    
    def _create_handler(self, task_info: dict):
        """Create handler for decorated function"""
        func = task_info['function']
        is_async = task_info['is_async']
        
        async def handler(task_data: dict) -> dict:
            try:
                # Extract parameters
                params = task_data.get('parameters', {})
                if 'external_parameters' in params:
                    exec_params = params['external_parameters']
                else:
                    exec_params = params
                
                args = exec_params.get('args', [])
                kwargs = exec_params.get('kwargs', {})
                
                # Execute function
                if is_async:
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)
                
                return {
                    'success': True,
                    'result': result
                }
                
            except Exception as e:
                return {
                    'success': False,
                    'error': str(e)
                }
        
        return handler
    
    def _auto_discover_tasks(self):
        """Auto-discover decorated tasks in Python files"""
        import importlib.util
        
        for search_path in self.search_paths:
            path = Path(search_path)
            if path.is_file() and path.suffix == '.py':
                files = [path]
            else:
                files = path.glob('**/*.py')
            
            for py_file in files:
                try:
                    # Load module
                    spec = importlib.util.spec_from_file_location(
                        py_file.stem, py_file
                    )
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        
                        # Find decorated functions
                        for name, obj in inspect.getmembers(module):
                            if hasattr(obj, '_gleitzeit_task'):
                                if obj._task_name not in _decorated_functions:
                                    _decorated_functions[obj._task_name] = {
                                        'function': obj,
                                        'category': obj._task_category,
                                        'description': obj._task_description,
                                        'timeout': obj._task_timeout,
                                        'is_async': asyncio.iscoroutinefunction(obj)
                                    }
                                    print(f"🔍 Discovered task: {obj._task_name}")
                                    
                except Exception as e:
                    # Skip files that can't be imported
                    pass
        
        # Register newly discovered tasks
        self._register_decorated_functions()


async def start_task_service(
    service_name: str = "Python Tasks",
    cluster_url: str = "http://localhost:8000",
    auto_discover: bool = True,
    search_paths: List[str] = None
):
    """
    Convenience function to start a task service with decorated functions.
    
    Usage:
        await start_task_service()
    """
    global _service_instance
    
    if _service_instance is None:
        _service_instance = GleitzeitTaskService(
            service_name=service_name,
            cluster_url=cluster_url,
            auto_discover=auto_discover,
            search_paths=search_paths
        )
    
    await _service_instance.start()
    return _service_instance


# Simplified workflow integration
def create_task_from_function(workflow, func: Callable, name: str = None, **kwargs):
    """
    Add a decorated function as a task to a workflow.
    
    Usage:
        @gleitzeit_task()
        def my_task(data):
            return process(data)
        
        workflow = cluster.create_workflow("My Workflow")
        create_task_from_function(workflow, my_task, args=[data])
    """
    if not hasattr(func, '_gleitzeit_task'):
        raise ValueError(f"Function {func.__name__} is not decorated with @gleitzeit_task")
    
    task_name = name or func._task_name
    
    return workflow.add_external_task(
        name=task_name,
        external_task_type="python_execution",
        service_name="Python Tasks",
        external_parameters={
            'function_name': func._task_name,
            'args': kwargs.get('args', []),
            'kwargs': kwargs.get('kwargs', {})
        },
        dependencies=kwargs.get('dependencies', [])
    )