"""
Python function execution for Gleitzeit Cluster
"""

import asyncio
import importlib.util
import inspect
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union
from concurrent.futures import ThreadPoolExecutor
import threading

from ..core.task import Task, TaskType, TaskParameters


class PythonExecutionError(Exception):
    """Exception raised during Python function execution"""
    pass


class PythonExecutor:
    """
    Executor for Python function tasks
    
    Handles both async and sync Python functions with proper isolation
    and error handling.
    """
    
    def __init__(self, max_workers: int = 4):
        """
        Initialize Python executor
        
        Args:
            max_workers: Maximum number of threads for sync function execution
        """
        self.max_workers = max_workers
        self._thread_pool = ThreadPoolExecutor(max_workers=max_workers)
        self._loaded_modules: Dict[str, Any] = {}
        self._function_registry: Dict[str, Callable] = {}
    
    async def close(self):
        """Clean up resources"""
        if self._thread_pool:
            self._thread_pool.shutdown(wait=True)
    
    def register_function(self, name: str, func: Callable) -> None:
        """
        Register a function for execution
        
        Args:
            name: Function name identifier
            func: Python function to register
        """
        self._function_registry[name] = func
    
    def register_functions(self, functions: Dict[str, Callable]) -> None:
        """Register multiple functions at once"""
        self._function_registry.update(functions)
    
    async def execute_task(self, task: Task) -> Any:
        """
        Execute a Python function task
        
        Args:
            task: Task containing Python function parameters
            
        Returns:
            Function execution result
        """
        if task.task_type != TaskType.EXTERNAL_PROCESSING:
            raise PythonExecutionError(f"Invalid task type: {task.task_type}")
        
        params = task.parameters
        
        # Get function
        if params.function_name in self._function_registry:
            # Use registered function
            func = self._function_registry[params.function_name]
        elif params.module_path:
            # Load function from module file
            func = await self._load_function_from_module(
                params.module_path, 
                params.function_name
            )
        else:
            raise PythonExecutionError(
                f"Function '{params.function_name}' not found in registry and no module path provided"
            )
        
        # Execute function
        args = params.args or []
        kwargs = params.kwargs or {}
        
        try:
            if asyncio.iscoroutinefunction(func):
                return await self._execute_async_function(func, args, kwargs)
            else:
                return await self._execute_sync_function(func, args, kwargs)
                
        except Exception as e:
            raise PythonExecutionError(f"Function execution failed: {e}")
    
    async def _execute_async_function(
        self, 
        func: Callable, 
        args: List[Any], 
        kwargs: Dict[str, Any]
    ) -> Any:
        """Execute async function directly"""
        return await func(*args, **kwargs)
    
    async def _execute_sync_function(
        self, 
        func: Callable, 
        args: List[Any], 
        kwargs: Dict[str, Any]
    ) -> Any:
        """Execute sync function in thread pool"""
        loop = asyncio.get_event_loop()
        
        def wrapper():
            return func(*args, **kwargs)
        
        return await loop.run_in_executor(self._thread_pool, wrapper)
    
    async def _load_function_from_module(
        self, 
        module_path: Union[str, Path], 
        function_name: str
    ) -> Callable:
        """
        Load a function from a Python module file
        
        Args:
            module_path: Path to Python module file
            function_name: Name of function to load
            
        Returns:
            Function object
        """
        module_path = Path(module_path)
        
        if not module_path.exists():
            raise PythonExecutionError(f"Module file not found: {module_path}")
        
        if not module_path.suffix == ".py":
            raise PythonExecutionError(f"Module file must be .py file: {module_path}")
        
        # Check if module already loaded
        cache_key = str(module_path.absolute())
        if cache_key in self._loaded_modules:
            module = self._loaded_modules[cache_key]
        else:
            # Load module
            try:
                spec = importlib.util.spec_from_file_location(
                    f"dynamic_module_{id(module_path)}", 
                    module_path
                )
                if spec is None or spec.loader is None:
                    raise PythonExecutionError(f"Could not load module spec from {module_path}")
                
                module = importlib.util.module_from_spec(spec)
                
                # Add module directory to sys.path temporarily
                module_dir = str(module_path.parent)
                sys_path_modified = False
                if module_dir not in sys.path:
                    sys.path.insert(0, module_dir)
                    sys_path_modified = True
                
                try:
                    spec.loader.exec_module(module)
                    self._loaded_modules[cache_key] = module
                finally:
                    if sys_path_modified:
                        sys.path.remove(module_dir)
                        
            except Exception as e:
                raise PythonExecutionError(f"Failed to load module {module_path}: {e}")
        
        # Get function from module
        if not hasattr(module, function_name):
            raise PythonExecutionError(
                f"Function '{function_name}' not found in module {module_path}"
            )
        
        func = getattr(module, function_name)
        if not callable(func):
            raise PythonExecutionError(
                f"'{function_name}' in {module_path} is not callable"
            )
        
        return func
    
    def get_function_info(self, function_name: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a registered function
        
        Args:
            function_name: Name of function to inspect
            
        Returns:
            Function information dictionary or None if not found
        """
        if function_name not in self._function_registry:
            return None
        
        func = self._function_registry[function_name]
        
        try:
            signature = inspect.signature(func)
            
            return {
                "name": function_name,
                "is_async": asyncio.iscoroutinefunction(func),
                "is_generator": inspect.isgeneratorfunction(func),
                "parameters": [
                    {
                        "name": param.name,
                        "kind": param.kind.name,
                        "default": param.default if param.default != param.empty else None,
                        "annotation": str(param.annotation) if param.annotation != param.empty else None
                    }
                    for param in signature.parameters.values()
                ],
                "return_annotation": str(signature.return_annotation) if signature.return_annotation != signature.empty else None,
                "docstring": inspect.getdoc(func),
                "source_file": inspect.getfile(func) if hasattr(func, "__code__") else None
            }
        except Exception as e:
            return {
                "name": function_name,
                "error": f"Could not inspect function: {e}"
            }
    
    def list_registered_functions(self) -> List[str]:
        """List all registered function names"""
        return list(self._function_registry.keys())
    
    def clear_registry(self) -> None:
        """Clear all registered functions"""
        self._function_registry.clear()
    
    def clear_module_cache(self) -> None:
        """Clear loaded module cache"""
        self._loaded_modules.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get executor statistics"""
        return {
            "max_workers": self.max_workers,
            "registered_functions": len(self._function_registry),
            "loaded_modules": len(self._loaded_modules),
            "thread_pool_active": self._thread_pool is not None
        }
    
    def __str__(self) -> str:
        return f"PythonExecutor(workers={self.max_workers}, functions={len(self._function_registry)})"


# Example functions that can be registered

async def example_async_function(data: List[int]) -> Dict[str, float]:
    """Example async function for testing"""
    await asyncio.sleep(0.1)  # Simulate async work
    
    return {
        "count": len(data),
        "sum": sum(data),
        "average": sum(data) / len(data) if data else 0,
        "min": min(data) if data else 0,
        "max": max(data) if data else 0
    }


def example_sync_function(text: str) -> Dict[str, Any]:
    """Example sync function for testing"""
    import time
    time.sleep(0.1)  # Simulate work
    
    words = text.split()
    return {
        "text": text,
        "word_count": len(words),
        "character_count": len(text),
        "first_word": words[0] if words else "",
        "last_word": words[-1] if words else ""
    }


def register_example_functions(executor: PythonExecutor) -> None:
    """Register example functions with executor"""
    executor.register_functions({
        "async_data_analysis": example_async_function,
        "text_analysis": example_sync_function
    })