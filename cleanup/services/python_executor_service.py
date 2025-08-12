#!/usr/bin/env python3
"""
Python Executor Service

External service that executes Python tasks via Socket.IO.
Replaces native Python execution with isolated, scalable service architecture.
"""

import asyncio
import json
import os
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Dict, Any, Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster.core.external_service_node import (
    ExternalServiceNode, 
    ExternalServiceCapability
)
from gleitzeit_cluster.functions.registry import FunctionRegistry


class PythonExecutorService(ExternalServiceNode):
    """
    Python task executor running as an external Socket.IO service.
    Provides isolated Python execution with better resource management.
    """
    
    def __init__(self,
                 service_name: str = "Python Executor",
                 cluster_url: str = "http://localhost:8000",
                 max_workers: int = 4,
                 isolation_mode: str = "subprocess",
                 timeout: int = 300):
        """
        Initialize Python executor service.
        
        Args:
            service_name: Name of this executor service
            cluster_url: URL of Gleitzeit cluster
            max_workers: Maximum parallel Python tasks
            isolation_mode: Execution isolation ('subprocess', 'thread', 'direct')
            timeout: Maximum execution time per task (seconds)
        """
        super().__init__(
            service_name=service_name,
            cluster_url=cluster_url,
            capabilities=[
                ExternalServiceCapability.PYTHON_EXECUTION,
                ExternalServiceCapability.DATA_PROCESSING,
                ExternalServiceCapability.CUSTOM_PROCESSING
            ],
            max_concurrent_tasks=max_workers,
            heartbeat_interval=20
        )
        
        self.isolation_mode = isolation_mode
        self.timeout = timeout
        self.function_registry = FunctionRegistry()
        
        # Initialize executor based on isolation mode
        if isolation_mode == "subprocess":
            self.executor = ProcessPoolExecutor(max_workers=max_workers)
        else:
            self.executor = None
        
        # Register all available functions
        self._register_functions()
        
        # Register task handlers
        self.register_task_handler("python_execution", self.execute_python_task)
        self.register_task_handler("data_processing", self.execute_python_task)
        
        # Track execution metrics
        self.execution_metrics = {
            'total_executed': 0,
            'total_failed': 0,
            'avg_execution_time': 0
        }
    
    def _register_functions(self):
        """Register all available Python functions"""
        # FunctionRegistry already loads default functions in __init__
        # No need to register them again
        total_functions = len(self.function_registry._functions)
        categories = self.function_registry.list_categories()
        
        print(f"📚 Loaded {total_functions} Python functions")
        print(f"📂 Categories: {', '.join(categories)}")
    
    async def execute_python_task(self, task_data: dict) -> dict:
        """
        Execute Python function in isolated environment.
        
        Args:
            task_data: Task data including function name and parameters
            
        Returns:
            Execution result with success status
        """
        start_time = time.time()
        
        try:
            # Extract parameters
            params = task_data.get('parameters', {})
            
            # Handle both native and external parameter formats
            if 'external_parameters' in params:
                # External task format
                exec_params = params['external_parameters']
                function_name = exec_params.get('function_name')
                args = exec_params.get('args', [])
                kwargs = exec_params.get('kwargs', {})
            else:
                # Native task format (backwards compatibility)
                function_name = params.get('function_name')
                args = params.get('args', [])
                kwargs = params.get('kwargs', {})
            
            if not function_name:
                raise ValueError("No function_name provided")
            
            print(f"🔧 Executing Python function: {function_name}")
            
            # Resolve parameter references (e.g., "{{task.result}}")
            args = await self._resolve_parameters(args, task_data)
            kwargs = await self._resolve_parameters(kwargs, task_data)
            
            # Execute based on isolation mode
            if self.isolation_mode == "subprocess":
                result = await self._execute_subprocess(function_name, args, kwargs)
            elif self.isolation_mode == "thread":
                result = await self._execute_thread(function_name, args, kwargs)
            else:
                result = await self._execute_direct(function_name, args, kwargs)
            
            # Update metrics
            execution_time = time.time() - start_time
            self.execution_metrics['total_executed'] += 1
            self._update_avg_execution_time(execution_time)
            
            print(f"✅ Function {function_name} completed in {execution_time:.2f}s")
            
            return {
                'success': True,
                'result': result,
                'execution_time': execution_time,
                'executor': self.service_name
            }
            
        except Exception as e:
            self.execution_metrics['total_failed'] += 1
            error_msg = f"Python execution failed: {str(e)}"
            print(f"❌ {error_msg}")
            
            return {
                'success': False,
                'error': error_msg,
                'traceback': traceback.format_exc(),
                'execution_time': time.time() - start_time,
                'executor': self.service_name
            }
    
    async def _execute_subprocess(self, func_name: str, args: list, kwargs: dict) -> Any:
        """Execute function in subprocess for maximum isolation"""
        
        # Create execution script
        execution_script = f'''
import sys
import json
import pickle
import base64

# Add path for imports
sys.path.insert(0, "{os.getcwd()}")

# Import function registry
from gleitzeit_cluster.functions.registry import FunctionRegistry
from gleitzeit_cluster.functions import core_functions, data_functions

# Setup registry
registry = FunctionRegistry()

# Register functions
for func_name in dir(core_functions):
    if not func_name.startswith('_'):
        func = getattr(core_functions, func_name)
        if callable(func):
            registry.register_function(func_name, func, category="core")

for func_name in dir(data_functions):
    if not func_name.startswith('_'):
        func = getattr(data_functions, func_name)
        if callable(func):
            registry.register_function(func_name, func, category="data")

# Get function
func = registry.get_function("{func_name}")
if not func:
    raise ValueError(f"Function '{func_name}' not found")

# Deserialize arguments
args = {json.dumps(args)}
kwargs = {json.dumps(kwargs)}

# Execute function
result = func(*args, **kwargs)

# Serialize result
print(json.dumps({{"result": result}}))
'''
        
        # Run in subprocess with timeout
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, '-c', execution_script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), 
                timeout=self.timeout
            )
            
            if proc.returncode != 0:
                raise Exception(f"Subprocess failed: {stderr.decode()}")
            
            result_data = json.loads(stdout.decode())
            return result_data['result']
            
        except asyncio.TimeoutError:
            if proc:
                proc.kill()
            raise TimeoutError(f"Function execution exceeded {self.timeout}s timeout")
    
    async def _execute_thread(self, func_name: str, args: list, kwargs: dict) -> Any:
        """Execute function in thread pool"""
        loop = asyncio.get_event_loop()
        
        def run_function():
            func = self.function_registry.get_function(func_name)
            if not func:
                raise ValueError(f"Function {func_name} not found")
            return func(*args, **kwargs)
        
        return await loop.run_in_executor(None, run_function)
    
    async def _execute_direct(self, func_name: str, args: list, kwargs: dict) -> Any:
        """Execute function directly (no isolation)"""
        func = self.function_registry.get_function(func_name)
        if not func:
            raise ValueError(f"Function {func_name} not found in registry")
        
        # Handle async functions
        if asyncio.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        else:
            return func(*args, **kwargs)
    
    async def _resolve_parameters(self, params: Any, task_data: dict) -> Any:
        """Resolve parameter references like {{task.result}}"""
        if isinstance(params, str) and params.startswith("{{") and params.endswith("}}"):
            # This is a reference to another task's result
            ref = params[2:-2]
            parts = ref.split(".")
            
            if len(parts) == 2:
                task_name, field = parts
                # In real implementation, fetch from result cache
                # For now, return placeholder
                return f"<resolved: {ref}>"
        
        elif isinstance(params, list):
            return [await self._resolve_parameters(p, task_data) for p in params]
        
        elif isinstance(params, dict):
            return {k: await self._resolve_parameters(v, task_data) 
                   for k, v in params.items()}
        
        return params
    
    def _update_avg_execution_time(self, new_time: float):
        """Update average execution time metric"""
        total = self.execution_metrics['total_executed']
        if total == 1:
            self.execution_metrics['avg_execution_time'] = new_time
        else:
            avg = self.execution_metrics['avg_execution_time']
            self.execution_metrics['avg_execution_time'] = (
                (avg * (total - 1) + new_time) / total
            )
    
    def get_status(self) -> dict:
        """Get service status including execution metrics"""
        status = super().get_status()
        status.update({
            'execution_metrics': self.execution_metrics,
            'isolation_mode': self.isolation_mode,
            'max_workers': self.max_concurrent_tasks,
            'registered_functions': len(self.function_registry._functions)
        })
        return status


async def main():
    """Main entry point for Python executor service"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Python Executor Service")
    parser.add_argument("--name", default="Python Executor", help="Service name")
    parser.add_argument("--server", default="http://localhost:8000", help="Cluster URL")
    parser.add_argument("--workers", type=int, default=4, help="Max parallel tasks")
    parser.add_argument("--isolation", choices=["subprocess", "thread", "direct"], 
                       default="subprocess", help="Execution isolation mode")
    parser.add_argument("--timeout", type=int, default=300, help="Task timeout (seconds)")
    
    args = parser.parse_args()
    
    print("🐍 Starting Python Executor Service")
    print("=" * 50)
    print(f"📝 Service Name: {args.name}")
    print(f"🔗 Cluster URL: {args.server}")
    print(f"👥 Max Workers: {args.workers}")
    print(f"🔒 Isolation: {args.isolation}")
    print(f"⏱️ Timeout: {args.timeout}s")
    print()
    
    # Create and start executor service
    executor = PythonExecutorService(
        service_name=args.name,
        cluster_url=args.server,
        max_workers=args.workers,
        isolation_mode=args.isolation,
        timeout=args.timeout
    )
    
    try:
        print(f"🔌 Connecting to Gleitzeit cluster at {args.server}")
        await executor.start()
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
    except Exception as e:
        print(f"💥 Service failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n🧹 Cleaning up...")
        await executor.stop()


if __name__ == "__main__":
    asyncio.run(main())