"""
Gleitzeit Unified Client - Works in both Native and API modes

This client provides a unified interface that can:
1. Use the REST API (default for production)
2. Use native execution engine (for development/testing)
3. Automatically detect and switch between modes
"""

import asyncio
import logging
import httpx
import subprocess
import sys
from typing import Optional, Dict, Any, List, Union
from enum import Enum
from pathlib import Path

from gleitzeit.core.models import Task, Workflow, TaskResult, Priority, WorkflowExecution
from gleitzeit.core import ExecutionEngine, ExecutionMode
from gleitzeit.core.workflow_loader import load_workflow_from_file
from gleitzeit.task_queue import QueueManager, DependencyResolver
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.persistence.factory import PersistenceFactory
from gleitzeit.providers.python_provider import PythonProvider
from gleitzeit.providers.ollama_provider import OllamaProvider
from gleitzeit.providers.mcp_hub_provider import MCPHubProvider
from gleitzeit.hub.mcp_hub import MCPHub
from gleitzeit.protocols import PYTHON_PROTOCOL_V1, LLM_PROTOCOL_V1, MCP_PROTOCOL_V1
from gleitzeit.core.batch_processor import BatchProcessor
from gleitzeit.common.shutdown import unified_shutdown
from gleitzeit.api.client import GleitzeitAPIClient
# Resource management is now handled via hub system

logger = logging.getLogger(__name__)


class ClientMode(Enum):
    """Client operation modes"""
    API = "api"        # Use REST API
    NATIVE = "native"  # Use direct execution engine
    AUTO = "auto"      # Auto-detect (prefer API if available)


class GleitzeitClient:
    """
    Unified Gleitzeit client that supports both API and native modes
    
    Examples:
        # Auto mode (default) - uses API if available, falls back to native
        async with GleitzeitClient() as client:
            result = await client.run_workflow("workflow.yaml")
        
        # Force API mode
        async with GleitzeitClient(mode="api") as client:
            result = await client.run_workflow("workflow.yaml")
        
        # Force native mode (for development/testing)
        async with GleitzeitClient(mode="native") as client:
            result = await client.run_workflow("workflow.yaml")
        
        # Use specific API server
        async with GleitzeitClient(api_host="api.example.com", api_port=9000) as client:
            result = await client.run_workflow("workflow.yaml")
    """
    
    # Make ClientMode available as a class attribute
    Mode = ClientMode
    
    # Mode constants for convenience (string versions)
    API = "api"
    NATIVE = "native"
    AUTO = "auto"
    
    def __init__(
        self,
        mode: Union[str, ClientMode] = "auto",
        api_host: str = "localhost",
        api_port: int = 8000,
        auto_start_server: bool = True,
        keep_server_running: bool = True,
        native_config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the unified client
        
        Args:
            mode: Operation mode ("auto", "api", or "native") or ClientMode enum
            api_host: API server host
            api_port: API server port
            auto_start_server: Auto-start API server if not running (in API/AUTO mode)
            keep_server_running: Keep API server running after client shutdown (if we started it)
            native_config: Configuration for native mode
        """
        # Convert string mode to ClientMode enum if needed
        if isinstance(mode, str):
            mode_map = {
                "auto": ClientMode.AUTO,
                "api": ClientMode.API,
                "native": ClientMode.NATIVE
            }
            self.mode = mode_map.get(mode.lower(), ClientMode.AUTO)
        else:
            self.mode = mode
        self.api_host = api_host
        self.api_port = api_port
        self.api_url = f"http://{api_host}:{api_port}"
        self.auto_start_server = auto_start_server
        self.keep_server_running = keep_server_running
        self.native_config = native_config or {}
        
        # Runtime state
        self._active_mode: Optional[ClientMode] = None
        self._api_client: Optional[GleitzeitAPIClient] = None
        self._server_process: Optional[subprocess.Popen] = None
        self._we_started_server: bool = False  # Track if we started the server
        self._execution_engine: Optional[ExecutionEngine] = None
        self._persistence_backend = None
        self._batch_processor: Optional[BatchProcessor] = None
        self._resource_manager: Optional[ResourceManager] = None
        
    async def __aenter__(self):
        """Async context manager entry"""
        await self.initialize()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.shutdown()
        
    async def initialize(self) -> None:
        """Initialize the client based on mode"""
        # Determine which mode to use
        if self.mode == ClientMode.AUTO:
            # Try API first, fall back to native
            if await self._check_api_available():
                self._active_mode = ClientMode.API
                logger.info(f"Using API mode (server at {self.api_url})")
            else:
                if self.auto_start_server:
                    if await self._start_api_server():
                        self._active_mode = ClientMode.API
                        logger.info(f"Started API server and using API mode")
                    else:
                        self._active_mode = ClientMode.NATIVE
                        logger.info("Failed to start API server, using native mode")
                else:
                    self._active_mode = ClientMode.NATIVE
                    logger.info("API not available, using native mode")
        elif self.mode == ClientMode.API:
            # Force API mode
            if not await self._check_api_available():
                if self.auto_start_server:
                    if not await self._start_api_server():
                        raise RuntimeError(f"API server not available at {self.api_url} and could not start it")
                else:
                    raise RuntimeError(f"API server not available at {self.api_url}")
            self._active_mode = ClientMode.API
            logger.info(f"Using API mode (forced)")
        else:
            # Force native mode
            self._active_mode = ClientMode.NATIVE
            logger.info("Using native mode (forced)")
            
        # Initialize based on active mode
        if self._active_mode == ClientMode.API:
            await self._init_api_client()
        else:
            await self._init_native_client()
            
    async def shutdown(self) -> None:
        """Shutdown the client and cleanup resources"""
        if self._active_mode == ClientMode.API:
            if self._api_client:
                await self._api_client.__aexit__(None, None, None)
            
            # Only stop server if we started it AND keep_server_running is False
            if self._we_started_server and not self.keep_server_running and self._server_process:
                logger.info("Stopping API server that was started by this client")
                self._server_process.terminate()
                try:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, self._server_process.wait, 5)
                except subprocess.TimeoutExpired:
                    self._server_process.kill()
                self._server_process = None
            elif self._we_started_server and self.keep_server_running:
                logger.info(f"Keeping API server running at {self.api_url}")
        else:
            # Native mode shutdown - use unified shutdown
            await unified_shutdown(
                execution_engine=self._execution_engine,
                resource_manager=self._resource_manager,
                persistence_backend=self._persistence_backend,
                verbose=True  # Log info messages
            )
                
    async def _check_api_available(self) -> bool:
        """Check if API server is available"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.api_url}/health", timeout=2.0)
                return response.status_code == 200
        except:
            return False
            
    async def _start_api_server(self) -> bool:
        """Start API server in background"""
        try:
            logger.info(f"Starting API server at {self.api_host}:{self.api_port}")
            
            # Start server process
            self._server_process = subprocess.Popen(
                [sys.executable, "-m", "gleitzeit.cli.gleitzeit_cli", "serve", 
                 "--host", self.api_host, "--port", str(self.api_port)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Give the server a moment to start initialization
            await asyncio.sleep(2)
            
            # Wait for server to be ready (up to 30 seconds)
            start_time = asyncio.get_event_loop().time()
            timeout = 30.0
            
            while (asyncio.get_event_loop().time() - start_time) < timeout:
                if await self._check_api_available():
                    elapsed = asyncio.get_event_loop().time() - start_time
                    logger.info(f"API server started successfully after {elapsed:.1f} seconds")
                    self._we_started_server = True
                    return True
                
                # Check if process is still alive
                if self._server_process.poll() is not None:
                    # Process terminated
                    stdout, stderr = self._server_process.communicate()
                    logger.error(f"Server process terminated unexpectedly")
                    if stdout:
                        logger.error(f"stdout: {stdout}")
                    if stderr:
                        logger.error(f"stderr: {stderr}")
                    self._server_process = None
                    return False
                
                await asyncio.sleep(1)
                
            # Timeout - server didn't respond
            logger.error("API server failed to respond within timeout")
            self._server_process.terminate()
            self._server_process = None
            return False
            
        except Exception as e:
            logger.error(f"Failed to start API server: {e}")
            if self._server_process:
                self._server_process.terminate()
                self._server_process = None
            return False
            
    async def _init_api_client(self) -> None:
        """Initialize API client"""
        self._api_client = GleitzeitAPIClient(base_url=self.api_url)
        await self._api_client.__aenter__()
        
    async def _init_native_client(self) -> None:
        """Initialize native execution engine"""
        # Initialize persistence with configuration
        factory_kwargs = {}
        
        # Check for persistence configuration in native_config
        persistence_config = self.native_config.get('persistence', {})
        
        # Redis configuration
        redis_url = persistence_config.get('redis_url')
        if redis_url:
            factory_kwargs['redis_url'] = redis_url
        
        # SQL configuration
        sql_db_path = persistence_config.get('sql_db_path')
        if sql_db_path:
            factory_kwargs['sql_db_path'] = sql_db_path
            
        sql_connection = persistence_config.get('sql_connection')
        if sql_connection:
            factory_kwargs['sql_connection_string'] = sql_connection
        
        # Persistence type preference
        persistence_type = persistence_config.get('type', 'auto')
        if persistence_type != 'auto':
            from gleitzeit.persistence.factory import PersistenceType
            factory_kwargs['persistence_type'] = PersistenceType(persistence_type)
        
        self._persistence_adapter = await PersistenceFactory.create(**factory_kwargs)
        
        # Setup execution components
        queue_manager = QueueManager()
        dependency_resolver = DependencyResolver()
        registry = ProtocolProviderRegistry()
        
        self._execution_engine = ExecutionEngine(
            registry=registry,
            queue_manager=queue_manager,
            dependency_resolver=dependency_resolver,
            persistence=self._persistence_adapter,
            max_concurrent_tasks=self.native_config.get('max_concurrent_tasks', 5)
        )
        
        # Initialize batch processor
        self._batch_processor = BatchProcessor()
        
        # Initialize resource manager and hubs BEFORE registering providers
        if self.native_config.get('enable_resource_management', True):  # Default to True for consistency
            from gleitzeit.hub.resource_manager import ResourceManager
            from gleitzeit.hub.ollama_hub import OllamaHub
            
            self._resource_manager = ResourceManager("client-resources")
            
            # Create and add OllamaHub
            self._ollama_hub = OllamaHub(
                hub_id="ollama-hub",
                auto_discover=True,  # Auto-discover running Ollama instances
                persistence=self._persistence_adapter  # Pass persistence for consistency
            )
            await self._ollama_hub.initialize()
            await self._resource_manager.add_hub("ollama", self._ollama_hub)
            
            await self._resource_manager.start()
        else:
            self._resource_manager = None
            self._ollama_hub = None
        
        # Register providers AFTER resource manager is initialized
        await self._register_native_providers(registry)
        
    async def _register_native_providers(self, registry: ProtocolProviderRegistry) -> None:
        """Register providers for native mode"""
        # Python provider
        try:
            registry.register_protocol(PYTHON_PROTOCOL_V1)
            python_provider = PythonProvider(
                "python-provider",
                allow_local=True,
                resource_manager=self._resource_manager
            )
            await python_provider.initialize()
            registry.register_provider("python-provider", "python/v1", python_provider)
        except Exception as e:
            logger.warning(f"Python provider registration failed: {e}")
            
        # Ollama provider
        try:
            registry.register_protocol(LLM_PROTOCOL_V1)
            # Pass hub and resource manager to provider
            ollama_provider = OllamaProvider(
                "ollama-provider",
                auto_discover=False,
                resource_manager=self._resource_manager,
                hub=self._ollama_hub
            )
            await ollama_provider.initialize()
            registry.register_provider("ollama-provider", "llm/v1", ollama_provider)
        except Exception as e:
            logger.warning(f"Ollama provider registration failed: {e}")
            
        # MCP provider setup - try hub-based first, fallback to simple
        try:
            registry.register_protocol(MCP_PROTOCOL_V1)
            
            # Configure MCP provider - always use MCPHub
            mcp_config = self.native_config.get('mcp', {})
            
            # Always use MCPHub (even with no servers configured)
            logger.info("Setting up MCP Hub")
            mcp_hub = MCPHub(
                auto_discover=mcp_config.get('auto_discover', False),
                config_data=mcp_config
            )
            mcp_provider = MCPHubProvider(
                provider_id="mcp-provider",
                hub=mcp_hub,
                config_data=mcp_config
            )
            
            await mcp_provider.initialize()
            registry.register_provider("mcp-provider", "mcp/v1", mcp_provider)
            
        except Exception as e:
            logger.warning(f"MCP provider registration failed: {e}")
            
    
    # =========================================================================
    # Unified API Methods
    # =========================================================================
    
    async def run_workflow(
        self, 
        workflow_file: str,
        watch: bool = False
    ) -> Dict[str, Any]:
        """
        Run a workflow from file
        
        Args:
            workflow_file: Path to workflow YAML/JSON file
            watch: Watch execution progress
            
        Returns:
            Workflow execution results
        """
        if self._active_mode == ClientMode.API:
            return await self._run_workflow_api(workflow_file, watch)
        else:
            return await self._run_workflow_native(workflow_file, watch)
            
            
    async def batch_process(
        self,
        directory: str,
        pattern: str = "*",
        method: str = "llm/chat",
        prompt: str = "Analyze this file",
        model: str = "llama3.2:latest",
        max_concurrent: int = 5,
        name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process files in batch
        
        Args:
            directory: Directory containing files
            pattern: File pattern to match
            method: Method to use for processing
            prompt: Prompt for each file
            model: Model to use
            max_concurrent: Max concurrent tasks
            name: Optional batch name
            
        Returns:
            Batch processing results
        """
        if self._active_mode == ClientMode.API:
            return await self._batch_process_api(
                directory, pattern, method, prompt, model, max_concurrent, name
            )
        else:
            return await self._batch_process_native(
                directory, pattern, method, prompt, model, max_concurrent, name
            )
            
    async def chat(
        self,
        message: str,
        model: str = "llama3.2:latest",
        temperature: float = 0.7,
        session_id: Optional[str] = None
    ) -> str:
        """
        Simple chat interface
        
        Args:
            message: User message
            model: LLM model to use
            temperature: Generation temperature
            session_id: Optional session ID for context
            
        Returns:
            Model response
        """
        if self._active_mode == ClientMode.API:
            return await self._chat_api(message, model, temperature, session_id)
        else:
            return await self._chat_native(message, model, temperature, session_id)
    
    # =========================================================================
    # API Mode Implementations
    # =========================================================================
    
    async def _run_workflow_api(self, workflow_file: str, watch: bool) -> Dict[str, Any]:
        """Run workflow via API"""
        # Load and convert workflow
        workflow = load_workflow_from_file(workflow_file)
        
        # Convert to API format
        api_workflow = {
            "name": workflow.name,
            "description": workflow.description or "",
            "tasks": []
        }
        
        for task in workflow.tasks:
            api_task = {
                "id": task.id,
                "name": task.name,
                "protocol": task.protocol,
                "method": task.method,
                "params": task.params,
                "dependencies": task.dependencies,
                "priority": task.priority.value if hasattr(task.priority, 'value') else str(task.priority).lower()
            }
            if task.retry_config:
                api_task["retry"] = {
                    "max_attempts": task.retry_config.max_attempts,
                    "base_delay": task.retry_config.base_delay,
                    "backoff_strategy": task.retry_config.backoff_strategy.value
                }
            api_workflow["tasks"].append(api_task)
        
        # Submit workflow
        result = await self._api_client.submit_workflow(api_workflow)
        workflow_id = result["workflow_id"]
        
        # Watch if requested
        if watch:
            start_time = asyncio.get_event_loop().time()
            timeout = 120.0  # 2 minutes timeout for workflows
            
            while True:
                await asyncio.sleep(2)
                status = await self._api_client.get_workflow_status(workflow_id)
                
                if status["status"] in ["completed", "failed", "cancelled"]:
                    return status
                
                # Check timeout
                if asyncio.get_event_loop().time() - start_time > timeout:
                    status["status"] = "timeout"
                    status["error"] = "Workflow execution timed out"
                    return status
                    
        return result
        
    async def _batch_process_api(
        self, directory: str, pattern: str, method: str, 
        prompt: str, model: str, max_concurrent: int, name: Optional[str]
    ) -> Dict[str, Any]:
        """Batch process via API"""
        return await self._api_client.batch_process(
            directory=directory,
            pattern=pattern,
            prompt=prompt,
            model=model,
            max_concurrent=max_concurrent
        )
        
    async def _chat_api(
        self, message: str, model: str, temperature: float, session_id: Optional[str]
    ) -> str:
        """Chat via API"""
        result = await self._api_client.chat(
            message=message,
            model=model,
            temperature=temperature,
            session_id=session_id
        )
        return result["response"]
    
    # =========================================================================
    # Native Mode Implementations
    # =========================================================================
    
    async def _run_workflow_native(self, workflow_file: str, watch: bool) -> Dict[str, Any]:
        """Run workflow using native execution engine"""
        workflow = load_workflow_from_file(workflow_file)
        
        # Submit and execute
        await self._execution_engine.submit_workflow(workflow)
        await self._execution_engine._execute_workflow(workflow)
        
        # Collect results
        results = {}
        for task in workflow.tasks:
            task_result = self._execution_engine.task_results.get(task.id)
            if task_result:
                results[task.id] = {
                    "status": task_result.status,
                    "result": task_result.result,
                    "error": task_result.error
                }
                
        return {
            "workflow_id": workflow.id,
            "status": "completed",
            "results": results
        }
        
    
    # =========================================================================
    # Task Management Methods (from old client)
    # =========================================================================
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID"""
        if self.get_mode() == "api":
            # In API mode, query the server
            try:
                response = await self._api_client.get(f"/tasks/{task_id}")
                if response.status_code == 200:
                    task_data = response.json()
                    return Task(**task_data)
                return None
            except Exception as e:
                logger.error(f"Failed to get task {task_id}: {e}")
                return None
        else:
            # In native mode, get from persistence
            if not self._persistence_adapter:
                return None
            return await self._persistence_adapter.get_task(task_id)
    
    async def get_task_status(self, task_id: str) -> Optional[str]:
        """Get the status of a task"""
        if self.get_mode() == "api":
            try:
                response = await self._api_client.get(f"/tasks/{task_id}/status")
                if response.status_code == 200:
                    return response.json().get("status")
                return None
            except Exception:
                return None
        else:
            task = await self.get_task(task_id)
            return task.status if task else None
    
    async def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        """Get the result of a completed task"""
        if self.get_mode() == "api":
            try:
                response = await self._api_client.get(f"/tasks/{task_id}/result")
                if response.status_code == 200:
                    result_data = response.json()
                    return TaskResult(**result_data)
                return None
            except Exception as e:
                logger.error(f"Failed to get task result {task_id}: {e}")
                return None
        else:
            if not self._persistence_adapter:
                return None
            return await self._persistence_adapter.get_task_result(task_id)
    
    async def wait_for_task(
        self,
        task_id: str,
        timeout: Optional[float] = None,
        poll_interval: float = 1.0
    ) -> Optional[TaskResult]:
        """
        Wait for a task to complete and return its result
        
        Args:
            task_id: Task ID to wait for
            timeout: Maximum time to wait in seconds
            poll_interval: Interval between status checks
            
        Returns:
            Task result if completed, None if timeout
        """
        start_time = asyncio.get_event_loop().time()
        
        while True:
            # Check task status
            status = await self.get_task_status(task_id)
            if not status:
                logger.warning(f"Task {task_id} not found")
                return None
            
            # Check if completed
            if status in ["completed", "failed"]:
                return await self.get_task_result(task_id)
            
            # Check timeout
            if timeout:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed >= timeout:
                    logger.warning(f"Timeout waiting for task {task_id}")
                    return None
            
            # Wait before next check
            await asyncio.sleep(poll_interval)
    
    async def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a queued task
        
        Args:
            task_id: Task ID to cancel
            
        Returns:
            True if task was cancelled, False if not found or already executing
        """
        if self.get_mode() == "api":
            try:
                response = await self._api_client.post(f"/tasks/{task_id}/cancel")
                return response.status_code == 200
            except Exception:
                return False
        else:
            # In native mode, need to check task status and update
            task = await self.get_task(task_id)
            if not task:
                return False
            
            if task.status not in ["pending", "queued"]:
                logger.warning(f"Cannot cancel task {task_id} with status {task.status}")
                return False
            
            # Update task status
            task.status = "cancelled"
            if self._persistence_adapter:
                await self._persistence_adapter.save_task(task)
                logger.info(f"Cancelled task {task_id}")
                return True
            return False
    
    async def submit_task(
        self,
        name: str,
        protocol: str,
        method: str,
        params: Dict[str, Any],
        priority: Priority = Priority.NORMAL,
        queue: str = "default",
        resource_requirements: Optional[Dict[str, Any]] = None
    ) -> Task:
        """
        Submit a task for execution (primary method)
        
        This method submits a task to the queue and returns immediately.
        The task will be executed asynchronously by the execution engine.
        
        Args:
            name: Task name
            protocol: Protocol identifier
            method: Method to execute
            params: Method parameters
            priority: Task priority
            queue: Queue name
            resource_requirements: Optional resource requirements for task
            
        Returns:
            Task object with ID for tracking
        """
        # Create task object
        task = Task(
            name=name,
            protocol=protocol,
            method=method,
            params=params,
            priority=priority,
            status="pending",
            resource_requirements=resource_requirements
        )
        
        if self.get_mode() == "api":
            # Submit to API server using execute_task
            try:
                api_task = {
                    "name": name,
                    "protocol": protocol,
                    "method": method,
                    "params": params
                }
                result = await self._api_client.execute_task(api_task)
                task.id = result.get("task_id", result.get("id"))
                task.status = "pending"  # API returns immediately
            except Exception as e:
                logger.error(f"Failed to submit task via API: {e}")
                raise
        else:
            # Submit to native execution engine
            if self._execution_engine:
                await self._execution_engine.submit_task(task)
                # Save to persistence
                if self._persistence_adapter:
                    await self._persistence_adapter.save_task(task)
                
                # In native mode, start processing the task immediately
                # This runs the task asynchronously without blocking
                asyncio.create_task(self._process_task_async(task))
            else:
                raise RuntimeError("Execution engine not initialized")
        
        return task
    
    async def _process_task_async(self, task: Task) -> None:
        """Process a task asynchronously in the background"""
        try:
            # Execute the task
            result = await self._execution_engine._execute_task(task)
            # Update task status
            task.status = result.status
            # Save result to persistence
            if self._persistence_adapter:
                await self._persistence_adapter.save_task(task)
                await self._persistence_adapter.save_task_result(result)
        except Exception as e:
            logger.error(f"Error processing task {task.id}: {e}")
            task.status = "failed"
            if self._persistence_adapter:
                await self._persistence_adapter.save_task(task)
    
    async def execute_task(
        self,
        protocol: str,
        method: str,
        params: Dict[str, Any],
        name: Optional[str] = None,
        wait: bool = True
    ) -> TaskResult:
        """
        Execute a task and optionally wait for result (optional method)
        
        This is a convenience method that submits a task and waits for completion.
        For fire-and-forget operations, use submit_task instead.
        
        Args:
            protocol: Protocol ID (e.g., "python/v1")
            method: Method name
            params: Task parameters
            name: Optional task name
            wait: Whether to wait for completion (default True)
            
        Returns:
            Task execution result
        """
        # Submit the task
        task = await self.submit_task(
            name=name or "Direct Execution",
            protocol=protocol,
            method=method,
            params=params,
            priority=Priority.NORMAL
        )
        
        if not wait:
            # Return immediately with pending status
            return TaskResult(
                task_id=task.id,
                status="pending",
                result=None,
                error=None
            )
        
        # Wait for completion
        result = await self.wait_for_task(task.id, timeout=300)  # 5 minute timeout
        if result:
            return result
        else:
            # Timeout or error
            return TaskResult(
                task_id=task.id,
                status="failed",
                result=None,
                error="Task execution timed out"
            )
    
    # =========================================================================
    # Workflow Management Methods (from old client)
    # =========================================================================
    
    async def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Get a workflow by ID"""
        if self.get_mode() == "api":
            try:
                response = await self._api_client.get(f"/workflows/{workflow_id}")
                if response.status_code == 200:
                    return Workflow(**response.json())
                return None
            except Exception:
                return None
        else:
            if not self._persistence_adapter:
                return None
            return await self._persistence_adapter.get_workflow(workflow_id)
    
    async def get_workflow_execution(self, execution_id: str) -> Optional[WorkflowExecution]:
        """Get workflow execution details"""
        if self.get_mode() == "api":
            try:
                response = await self._api_client.get(f"/workflow-executions/{execution_id}")
                if response.status_code == 200:
                    return WorkflowExecution(**response.json())
                return None
            except Exception:
                return None
        else:
            if not self._persistence_adapter:
                return None
            return await self._persistence_adapter.get_workflow_execution(execution_id)
    
    async def get_workflow_tasks(self, workflow_id: str) -> List[Task]:
        """Get all tasks for a workflow"""
        if self.get_mode() == "api":
            try:
                response = await self._api_client.get(f"/workflows/{workflow_id}/tasks")
                if response.status_code == 200:
                    return [Task(**task) for task in response.json()]
                return []
            except Exception:
                return []
        else:
            if not self._persistence_adapter:
                return []
            # get_workflow_tasks is get_tasks_by_workflow in the adapter
            return await self._persistence_adapter.get_tasks_by_workflow(workflow_id)
    
    # =========================================================================
    # Statistics and Monitoring Methods (from old client)
    # =========================================================================
    
    async def get_task_statistics(self) -> Dict[str, int]:
        """Get task count by status"""
        if self.get_mode() == "api":
            try:
                response = await self._api_client.get("/statistics/tasks")
                if response.status_code == 200:
                    return response.json()
                return {}
            except Exception:
                return {}
        else:
            if not self._persistence_adapter:
                return {}
            return await self._persistence_adapter.get_task_count_by_status()
    
    async def get_queue_statistics(self) -> Dict[str, Any]:
        """Get queue statistics"""
        if self.get_mode() == "api":
            try:
                response = await self._api_client.get("/statistics/queues")
                if response.status_code == 200:
                    return response.json()
                return {}
            except Exception:
                return {}
        else:
            # In native mode, we don't have direct queue access in v2
            # Return basic statistics from execution engine
            if self._execution_engine:
                return {
                    "active_tasks": len(self._execution_engine.task_results),
                    "max_concurrent": self._execution_engine.max_concurrent_tasks
                }
            return {}
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform a health check on the client
        
        Returns:
            Dictionary with health status information
        """
        health = {
            "status": "healthy",
            "mode": self.get_mode(),
            "initialized": self._execution_engine is not None or self._api_client is not None
        }
        
        if self.get_mode() == "api":
            try:
                response = await self._api_client.get("/health")
                health["api_server"] = response.status_code == 200
            except Exception:
                health["api_server"] = False
                health["status"] = "degraded"
        else:
            # Check native components
            health["persistence"] = self._persistence_adapter is not None
            health["execution_engine"] = self._execution_engine is not None
            health["batch_processor"] = self._batch_processor is not None
            
            if self._persistence_adapter:
                health["persistence_backend"] = type(self._persistence_adapter).__name__
            
            if not all([health["persistence"], health["execution_engine"]]):
                health["status"] = "degraded"
        
        return health
    
    async def cleanup_old_data(self, days: int = 30) -> int:
        """
        Clean up old completed tasks and results
        
        Args:
            days: Number of days to keep data
            
        Returns:
            Number of items deleted
        """
        if self.get_mode() == "api":
            try:
                response = await self._api_client.post(
                    "/cleanup",
                    json={"days": days}
                )
                if response.status_code == 200:
                    return response.json().get("deleted", 0)
                return 0
            except Exception:
                return 0
        else:
            if not self._persistence_adapter:
                return 0
            
            from datetime import datetime, timedelta
            cutoff = datetime.utcnow() - timedelta(days=days)
            return await self._persistence_adapter.cleanup_old_data(cutoff)
    
    # ============== Resource Management Methods ==============
    
    async def create_resource_pool(
        self,
        pool_id: str,
        resource_type: str,
        min_instances: int = 0,
        max_instances: int = 10,
        endpoints: Optional[List[str]] = None
    ) -> bool:
        """
        Create a resource pool
        
        Args:
            pool_id: Unique pool identifier
            resource_type: Type of resource ("ollama", "docker", "python")
            min_instances: Minimum instances to maintain
            max_instances: Maximum instances allowed
            endpoints: Optional list of endpoints for initial instances
            
        Returns:
            Success status
        """
        if not self._resource_manager:
            logger.warning("Resource management not enabled")
            return False
        
        try:
            res_type = ResourceType(resource_type)
            
            if res_type == ResourceType.OLLAMA and endpoints:
                pool = await self._resource_manager.create_ollama_pool(
                    pool_id=pool_id,
                    endpoints=endpoints,
                    min_instances=min_instances,
                    max_instances=max_instances
                )
            elif res_type == ResourceType.DOCKER:
                pool = await self._resource_manager.create_docker_pool(
                    pool_id=pool_id,
                    min_instances=min_instances,
                    max_instances=max_instances
                )
            else:
                pool = await self._resource_manager.create_pool(
                    pool_id=pool_id,
                    resource_type=res_type,
                    min_instances=min_instances,
                    max_instances=max_instances
                )
            
            return pool is not None
            
        except Exception as e:
            logger.error(f"Failed to create resource pool: {e}")
            return False
    
    async def register_resource(
        self,
        pool_id: str,
        instance_id: str,
        endpoint: str,
        resource_type: str = "ollama",
        capabilities: Optional[List[str]] = None,
        max_concurrent: int = 3
    ) -> bool:
        """
        Register a resource instance with a pool
        
        Args:
            pool_id: Pool to register with
            instance_id: Unique instance identifier
            endpoint: Connection endpoint
            resource_type: Type of resource
            capabilities: List of capabilities (e.g., models)
            max_concurrent: Max concurrent tasks
            
        Returns:
            Success status
        """
        if not self._resource_manager:
            logger.warning("Resource management not enabled")
            return False
        
        try:
            instance = ResourceInstance(
                id=instance_id,
                name=f"{resource_type} instance {instance_id}",
                resource_type=ResourceType(resource_type),
                endpoint=endpoint,
                capabilities=set(capabilities) if capabilities else set(),
                max_concurrent_tasks=max_concurrent
            )
            
            return await self._resource_manager.register_instance(pool_id, instance)
            
        except Exception as e:
            logger.error(f"Failed to register resource: {e}")
            return False
    
    async def allocate_resource(
        self,
        task_id: str,
        resource_type: str,
        capabilities: Optional[List[str]] = None,
        strategy: str = "least_loaded"
    ) -> Optional[Dict[str, Any]]:
        """
        Allocate a resource for a task
        
        Args:
            task_id: Task requiring resource
            resource_type: Type of resource needed
            capabilities: Required capabilities
            strategy: Allocation strategy
            
        Returns:
            Allocated resource info or None
        """
        if not self._resource_manager:
            return None
        
        try:
            instance = await self._resource_manager.allocate_resource(
                task_id=task_id,
                resource_type=ResourceType(resource_type),
                capabilities=set(capabilities) if capabilities else None,
                strategy=strategy
            )
            
            if instance:
                return instance.to_dict()
            
        except Exception as e:
            logger.error(f"Resource allocation failed: {e}")
        
        return None
    
    async def release_resource(self, task_id: str) -> bool:
        """Release resources allocated to a task"""
        if not self._resource_manager:
            return False
        
        return await self._resource_manager.release_resource(task_id)
    
    async def get_resource_metrics(self) -> Dict[str, Any]:
        """Get resource management metrics"""
        if not self._resource_manager:
            return {"enabled": False}
        
        return await self._resource_manager.get_metrics()
    
    async def enable_auto_scaling(
        self,
        scale_up_threshold: float = 0.8,
        scale_down_threshold: float = 0.2
    ) -> None:
        """Enable auto-scaling for resource pools"""
        if self._resource_manager:
            await self._resource_manager.enable_auto_scaling(
                scale_up_threshold=scale_up_threshold,
                scale_down_threshold=scale_down_threshold
            )
    
    @property
    def persistence_backend(self) -> str:
        """Get the name of the current persistence backend"""
        if self.get_mode() == "api":
            return "API Server"
        elif self._persistence_adapter:
            return type(self._persistence_adapter).__name__
        return "Not initialized"
        
    async def _batch_process_native(
        self, directory: str, pattern: str, method: str,
        prompt: str, model: str, max_concurrent: int, name: Optional[str]
    ) -> Dict[str, Any]:
        """Batch process using native execution engine"""
        # Note: BatchProcessor doesn't support max_concurrent or name params yet
        # These could be added in future
        result = await self._batch_processor.process_batch(
            execution_engine=self._execution_engine,
            directory=directory,
            pattern=pattern,
            method=method,
            prompt=prompt,
            model=model
        )
        
        return {
            "batch_id": result.batch_id,
            "total_files": result.total_files,
            "successful": result.successful,
            "failed": result.failed,
            "processing_time": result.processing_time,
            "results": result.results
        }
        
    async def _chat_native(
        self, message: str, model: str, temperature: float, session_id: Optional[str]
    ) -> str:
        """Chat using native execution engine"""
        task = Task(
            name="Chat",
            protocol="llm/v1",
            method="llm/chat",
            params={
                "model": model,
                "messages": [{"role": "user", "content": message}],
                "temperature": temperature
            },
            priority=Priority.HIGH
        )
        
        await self._execution_engine.submit_task(task)
        await self._execution_engine.start(ExecutionMode.SINGLE_SHOT)
        
        result = self._execution_engine.task_results.get(task.id)
        if result and result.status == "completed":
            return result.result.get("response", "")
        else:
            raise RuntimeError(f"Chat failed: {result.error if result else 'Unknown error'}")
    
    # =========================================================================
    # Utility Methods
    # =========================================================================
    
    @property
    def is_api_mode(self) -> bool:
        """Check if client is using API mode"""
        return self._active_mode == ClientMode.API
        
    @property
    def is_native_mode(self) -> bool:
        """Check if client is using native mode"""
        return self._active_mode == ClientMode.NATIVE
        
    def get_mode(self) -> str:
        """Get current client mode"""
        return self._active_mode.value if self._active_mode else "not initialized"