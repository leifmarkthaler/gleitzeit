"""
Main task executor integrating all execution types
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from ..core.task import Task, TaskType, TaskStatus
from ..core.error_handling import RetryManager, RetryConfig, GleitzeitLogger
from .ollama_client import OllamaClient, OllamaError
from .ollama_endpoint_manager import OllamaEndpointManager, EndpointConfig, LoadBalancingStrategy
from .python_executor import PythonExecutor, PythonExecutionError
from ..functions.registry import get_function_registry


class TaskExecutionError(Exception):
    """Exception raised during task execution"""
    pass


class TaskExecutor:
    """
    Main task executor that handles all task types
    
    Coordinates between different execution engines (Ollama, Python, etc.)
    and provides a unified interface for task execution.
    """
    
    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        ollama_timeout: int = 300,
        python_max_workers: int = 4,
        ollama_endpoints: Optional[List[EndpointConfig]] = None,
        ollama_strategy: LoadBalancingStrategy = LoadBalancingStrategy.LEAST_LOADED,
        provider_manager: Optional[Any] = None  # SocketIOProviderManager
    ):
        """
        Initialize task executor
        
        Args:
            ollama_url: Single Ollama server URL (legacy mode)
            ollama_timeout: Timeout for Ollama requests
            python_max_workers: Max workers for Python function execution
            ollama_endpoints: List of Ollama endpoints for multi-endpoint mode
            ollama_strategy: Load balancing strategy for multiple endpoints
        """
        # Initialize Ollama execution - either single endpoint or multi-endpoint
        if ollama_endpoints:
            # Multi-endpoint mode
            self.ollama_manager = OllamaEndpointManager(
                endpoints=ollama_endpoints,
                strategy=ollama_strategy
            )
            self.ollama_client = None
            self._multi_endpoint_mode = True
            print(f"🔄 TaskExecutor: Multi-endpoint mode ({len(ollama_endpoints)} endpoints)")
        else:
            # Legacy single endpoint mode
            self.ollama_client = OllamaClient(
                base_url=ollama_url,
                timeout=ollama_timeout
            )
            self.ollama_manager = None
            self._multi_endpoint_mode = False
            print(f"🔄 TaskExecutor: Single endpoint mode ({ollama_url})")
        
        self.python_executor = PythonExecutor(max_workers=python_max_workers)
        self._is_started = False
        
        # Register secure functions from function registry
        self._register_secure_functions()
        
        # Provider manager for external tasks
        self.provider_manager = provider_manager
        
        # Error handling and retry
        self.logger = GleitzeitLogger("TaskExecutor")
        self.retry_manager = RetryManager(self.logger)
    
    async def start(self):
        """Start the executor and check dependencies"""
        print("🚀 Starting TaskExecutor...")
        
        # Start Ollama components
        if self._multi_endpoint_mode:
            # Start endpoint manager
            await self.ollama_manager.start()
            healthy_endpoints = self.ollama_manager.get_healthy_endpoints()
            print(f"✅ Ollama endpoints: {len(healthy_endpoints)} healthy")
            
            # Show available models across all endpoints
            all_models = set()
            for endpoint_name in healthy_endpoints:
                stats = self.ollama_manager.stats[endpoint_name]
                all_models.update(stats.available_models)
            
            if all_models:
                model_list = list(all_models)
                print(f"📋 Available models: {', '.join(model_list[:5])}{'...' if len(model_list) > 5 else ''}")
        else:
            # Single endpoint mode
            if await self.ollama_client.health_check():
                print("✅ Ollama server connected")
                try:
                    models = await self.ollama_client.list_models()
                    print(f"📋 Available models: {', '.join(models[:5])}{'...' if len(models) > 5 else ''}")
                except Exception as e:
                    print(f"⚠️  Could not list models: {e}")
            else:
                print("⚠️  Ollama server not available - LLM tasks will fail")
        
        self._is_started = True
        print("✅ TaskExecutor started successfully")
    
    async def stop(self):
        """Stop the executor and clean up resources"""
        print("🛑 Stopping TaskExecutor...")
        
        # Stop Ollama components
        if self._multi_endpoint_mode:
            await self.ollama_manager.stop()
        else:
            await self.ollama_client.close()
        
        await self.python_executor.close()
        
        self._is_started = False
        print("✅ TaskExecutor stopped")
    
    async def execute_task(self, task: Task) -> Any:
        """
        Execute a task based on its type
        
        Args:
            task: Task to execute
            
        Returns:
            Task execution result
            
        Raises:
            TaskExecutionError: If task execution fails
        """
        if not self._is_started:
            raise TaskExecutionError("TaskExecutor not started. Call start() first.")
        
        # Configure retry based on task type
        retry_config = self._get_retry_config_for_task(task)
        
        # Execute with retry logic
        context = {
            "task_id": task.id,
            "task_name": task.name,
            "task_type": task.task_type.value
        }
        
        async def execute():
            print(f"🔄 Executing task: {task.name} ({task.task_type.value})")
            
            # Route all task types through the provider system
            if task.task_type == TaskType.EXTERNAL_CUSTOM:
                return await self._execute_provider_task(task)
            elif task.task_type == TaskType.EXTERNAL_ML:
                return await self._execute_provider_task(task)
            elif task.task_type == TaskType.EXTERNAL_API:
                return await self._execute_provider_task(task)
            elif task.task_type == TaskType.EXTERNAL_PROCESSING:
                return await self._execute_provider_task(task)
            elif task.task_type == TaskType.EXTERNAL_DATABASE:
                return await self._execute_provider_task(task)
            elif task.task_type == TaskType.EXTERNAL_WEBHOOK:
                return await self._execute_provider_task(task)
            else:
                raise TaskExecutionError(f"Unsupported task type: {task.task_type}")
        
        try:
            return await self.retry_manager.execute_with_retry(
                execute, 
                retry_config, 
                service_name=f"task_executor_{task.task_type.value}",
                context=context
            )
        except Exception as e:
            error_msg = f"Task execution failed after retries: {e}"
            self.logger.logger.error(error_msg)
            raise TaskExecutionError(error_msg)
    
    def _get_retry_config_for_task(self, task: Task) -> RetryConfig:
        """Get retry configuration based on task type"""
        # ML/LLM tasks: more retries, longer delays
        if task.task_type in [TaskType.EXTERNAL_ML, TaskType.EXTERNAL_CUSTOM]:
            return RetryConfig(
                max_attempts=task.max_retries or 3,
                base_delay=2.0,
                max_delay=30.0
            )
        
        # Processing/API tasks: fewer retries, shorter delays  
        elif task.task_type in [TaskType.EXTERNAL_PROCESSING, TaskType.EXTERNAL_API]:
            return RetryConfig(
                max_attempts=task.max_retries or 2,
                base_delay=1.0,
                max_delay=10.0
            )
        
        # Database/Webhook tasks: minimal retries
        elif task.task_type in [TaskType.EXTERNAL_DATABASE, TaskType.EXTERNAL_WEBHOOK]:
            return RetryConfig(
                max_attempts=task.max_retries or 1,
                base_delay=0.5,
                max_delay=5.0
            )
        
        # Default
        return RetryConfig(max_attempts=task.max_retries or 2)
    
    async def _execute_text_task(self, task: Task) -> str:
        """Execute text-based LLM task"""
        params = task.parameters
        
        if not params.prompt:
            raise TaskExecutionError("Text task missing prompt parameter")
        
        try:
            if self._multi_endpoint_mode:
                # Use endpoint manager for multi-endpoint execution
                result = await self.ollama_manager.execute_text_task(
                    model=params.model or "llama3",
                    prompt=params.prompt,
                    temperature=params.temperature or 0.7,
                    max_tokens=params.max_tokens,
                    system_prompt=getattr(params, 'system_prompt', None),
                    preferred_tags=getattr(params, 'endpoint_tags', None)
                )
            else:
                # Single endpoint mode
                result = await self.ollama_client.generate_text(
                    model=params.model or "llama3",
                    prompt=params.prompt,
                    temperature=params.temperature or 0.7,
                    max_tokens=params.max_tokens,
                    system_prompt=getattr(params, 'system_prompt', None)
                )
            
            print(f"✅ Text task completed: {len(result)} characters generated")
            return result
            
        except OllamaError as e:
            raise TaskExecutionError(f"Ollama error: {e}")
    
    async def _execute_vision_task(self, task: Task) -> str:
        """Execute vision-based task"""
        params = task.parameters
        
        if not params.prompt:
            raise TaskExecutionError("Vision task missing prompt parameter")
        if not params.image_path:
            raise TaskExecutionError("Vision task missing image_path parameter")
        
        # Check if image file exists
        image_path = Path(params.image_path)
        if not image_path.exists():
            raise TaskExecutionError(f"Image file not found: {image_path}")
        
        try:
            if self._multi_endpoint_mode:
                # Use endpoint manager for multi-endpoint execution
                result = await self.ollama_manager.execute_vision_task(
                    model=params.model or "llava",
                    prompt=params.prompt,
                    image_path=str(image_path),
                    temperature=params.temperature or 0.4,
                    max_tokens=params.max_tokens,
                    preferred_tags=getattr(params, 'endpoint_tags', None)
                )
            else:
                # Single endpoint mode
                result = await self.ollama_client.generate_vision(
                    model=params.model or "llava",
                    prompt=params.prompt,
                    image_path=image_path,
                    temperature=params.temperature or 0.4,
                    max_tokens=params.max_tokens
                )
            
            print(f"✅ Vision task completed: {len(result)} characters generated")
            return result
            
        except OllamaError as e:
            raise TaskExecutionError(f"Ollama vision error: {e}")
    
    async def _execute_python_task(self, task: Task) -> Any:
        """Execute Python function task"""
        try:
            result = await self.python_executor.execute_task(task)
            print(f"✅ Python task completed: {type(result).__name__}")
            return result
            
        except PythonExecutionError as e:
            raise TaskExecutionError(f"Python execution error: {e}")
    
    async def _execute_http_task(self, task: Task) -> Dict[str, Any]:
        """Execute HTTP request task"""
        params = task.parameters
        
        if not params.url:
            raise TaskExecutionError("HTTP task missing URL parameter")
        
        import httpx
        
        try:
            async with httpx.AsyncClient() as client:
                method = params.method or "GET"
                
                response = await client.request(
                    method=method,
                    url=params.url,
                    headers=params.headers or {},
                    json=params.data if method in ["POST", "PUT", "PATCH"] else None,
                    timeout=params.timeout_seconds or 30
                )
                
                result = {
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "content": response.text,
                    "url": str(response.url)
                }
                
                print(f"✅ HTTP task completed: {response.status_code} {method} {params.url}")
                return result
                
        except Exception as e:
            raise TaskExecutionError(f"HTTP request failed: {e}")
    
    async def _execute_file_task(self, task: Task) -> str:
        """Execute file operation task"""
        params = task.parameters
        
        if not params.operation:
            raise TaskExecutionError("File task missing operation parameter")
        
        try:
            if params.operation == "read":
                if not params.source_path:
                    raise TaskExecutionError("File read operation missing source_path")
                
                file_path = Path(params.source_path)
                if not file_path.exists():
                    raise TaskExecutionError(f"File not found: {file_path}")
                
                content = file_path.read_text(encoding="utf-8")
                print(f"✅ File read completed: {len(content)} characters")
                return content
                
            elif params.operation == "write":
                if not params.target_path:
                    raise TaskExecutionError("File write operation missing target_path")
                if params.content is None:
                    raise TaskExecutionError("File write operation missing content")
                
                file_path = Path(params.target_path)
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(params.content, encoding="utf-8")
                
                result = f"Written {len(params.content)} characters to {file_path}"
                print(f"✅ File write completed: {result}")
                return result
                
            elif params.operation == "delete":
                if not params.source_path:
                    raise TaskExecutionError("File delete operation missing source_path")
                
                file_path = Path(params.source_path)
                if file_path.exists():
                    file_path.unlink()
                    result = f"Deleted file: {file_path}"
                else:
                    result = f"File not found (already deleted?): {file_path}"
                
                print(f"✅ File delete completed: {result}")
                return result
                
            else:
                raise TaskExecutionError(f"Unsupported file operation: {params.operation}")
                
        except Exception as e:
            raise TaskExecutionError(f"File operation failed: {e}")
    
    def register_python_function(self, name: str, func) -> None:
        """Register a Python function for execution"""
        self.python_executor.register_function(name, func)
    
    def register_python_functions(self, functions: Dict[str, Any]) -> None:
        """Register multiple Python functions"""
        self.python_executor.register_functions(functions)
    
    async def get_available_models(self) -> Dict[str, Any]:
        """Get information about available models"""
        try:
            if not await self.ollama_client.health_check():
                return {"error": "Ollama server not available"}
            
            models = await self.ollama_client.list_models()
            recommended = self.ollama_client.get_recommended_models()
            
            return {
                "available": models,
                "recommended": recommended,
                "total_count": len(models)
            }
            
        except Exception as e:
            return {"error": f"Failed to get models: {e}"}
    
    async def pull_model(self, model_name: str) -> bool:
        """Pull a model from Ollama"""
        try:
            return await self.ollama_client.pull_model(model_name)
        except Exception as e:
            print(f"❌ Failed to pull model {model_name}: {e}")
            return False
    
    def get_executor_stats(self) -> Dict[str, Any]:
        """Get executor statistics"""
        return {
            "is_started": self._is_started,
            "ollama_url": self.ollama_client.base_url,
            "python_stats": self.python_executor.get_stats()
        }
    
    async def __aenter__(self):
        """Async context manager entry"""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.stop()
    
    def _register_secure_functions(self):
        """Register secure functions from function registry"""
        try:
            # Get the global function registry
            registry = get_function_registry()
            
            # Get all functions from registry
            function_names = registry.list_functions()
            
            # Register each function with the Python executor
            registered_count = 0
            for name in function_names:
                func = registry.get_function(name)
                if func:
                    self.python_executor.register_function(name, func)
                    registered_count += 1
            
            print(f"📚 Registered {registered_count} secure functions")
            
            # Show function categories
            categories = registry.list_categories()
            stats = registry.get_stats()
            category_info = ", ".join([f"{cat}({stats['categories'][cat]})" for cat in categories])
            print(f"📂 Categories: {category_info}")
            
        except Exception as e:
            print(f"⚠️ Warning: Failed to register secure functions: {e}")
    
    async def _execute_provider_task(self, task: Task) -> Any:
        """Execute task using provider system"""
        params = task.parameters
        
        # Get provider name from task parameters
        provider_name = None
        if hasattr(params, 'provider') and params.provider:
            provider_name = params.provider
        elif hasattr(params, 'service_name') and params.service_name:
            provider_name = params.service_name
        else:
            # Check external_parameters for provider info
            if hasattr(params, 'external_parameters') and params.external_parameters:
                provider_name = params.external_parameters.get('provider')
        
        # Final fallback
        if not provider_name:
            provider_name = 'ollama'
        
        # Provider manager should be available from the cluster/server
        if not hasattr(self, 'provider_manager') or not self.provider_manager:
            raise TaskExecutionError("Provider manager not available - TaskExecutor should be initialized with provider_manager from cluster")
        
        # Prepare provider parameters
        provider_params = {
            'prompt': params.prompt if hasattr(params, 'prompt') else None,
            'model': params.model if hasattr(params, 'model') else None,
            'temperature': params.temperature if hasattr(params, 'temperature') else 0.7,
            'max_tokens': params.max_tokens if hasattr(params, 'max_tokens') else None,
        }
        
        # Add any external parameters
        if hasattr(params, 'external_parameters') and params.external_parameters:
            provider_params.update(params.external_parameters)
        
        # Remove None values
        provider_params = {k: v for k, v in provider_params.items() if v is not None}
        
        try:
            print(f"🔗 Routing task to provider: {provider_name}")
            print(f"   📝 Method: generate")
            print(f"   🤖 Model: {provider_params.get('model', 'default')}")
            
            # Route to provider via provider manager
            result = await self.provider_manager.invoke_provider(
                provider_name=provider_name,
                method="generate",
                **provider_params
            )
            
            print(f"✅ Provider task completed: {provider_name}")
            return result
            
        except Exception as e:
            error_msg = f"Provider task failed ({provider_name}): {e}"
            print(f"❌ {error_msg}")
            raise TaskExecutionError(error_msg)
    
    def __str__(self) -> str:
        return f"TaskExecutor(started={self._is_started}, ollama={self.ollama_client.base_url})"