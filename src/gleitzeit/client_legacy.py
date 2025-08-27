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
import os
import time
from typing import Optional, Dict, Any, List, Union
from enum import Enum
from pathlib import Path
from datetime import datetime

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
        self._persistence_adapter = None
        self._batch_processor: Optional[BatchProcessor] = None
        self._resource_manager: Optional[ResourceManager] = None
        self._registry = None
        self._auth_enabled = False  # Default to false, updated during initialization
        
    async def __aenter__(self):
        """Async context manager entry"""
        await self.initialize()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.shutdown()
        
    async def _scan_for_api_servers(self, port_range: List[int] = None) -> Optional[int]:
        """Scan port range for running Gleitzeit API servers"""
        if port_range is None:
            # Use default range from config
            port_range = [8000, 8010]
        
        for port in range(port_range[0], port_range[-1] + 1):
            try:
                url = f"http://localhost:{port}/health"
                async with httpx.AsyncClient() as client:
                    response = await client.get(url, timeout=0.5)
                    if response.status_code == 200:
                        data = response.json()
                        if isinstance(data, dict) and 'status' in data and data['status'] == 'healthy':
                            return port
            except:
                continue
        return None
    
    async def initialize(self) -> None:
        """Initialize the client based on mode"""
        # Determine which mode to use
        if self.mode == ClientMode.AUTO:
            # Try configured API first
            if await self._check_api_available():
                self._active_mode = ClientMode.API
                logger.info(f"Using API mode (server at {self.api_url})")
            else:
                # Scan port range for any running servers
                port_range = self.native_config.get('server', {}).get('api', {}).get('port_range', [8000, 8010])
                found_port = await self._scan_for_api_servers(port_range)
                
                if found_port:
                    self.api_port = found_port
                    self.api_url = f"http://localhost:{found_port}"
                    self._active_mode = ClientMode.API
                    logger.info(f"Found Gleitzeit API server on port {found_port}, using API mode")
                elif self.auto_start_server:
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
            # Force native mode - but still check if API is available and warn
            if await self._check_api_available():
                logger.warning(f"Gleitzeit API server is already running at {self.api_url}")
                logger.warning("Consider using mode='api' to connect to existing server instead of starting new engine")
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
                if response.status_code == 200:
                    # Verify it's actually a Gleitzeit API
                    data = response.json()
                    return isinstance(data, dict) and 'status' in data and data['status'] == 'healthy'
                return False
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
        
        # Setup event-driven architecture first (BEFORE creating persistence adapter)
        from gleitzeit.events.base import EventBus
        from gleitzeit.events.task_handlers import TaskCompletedHandler
        from gleitzeit.events.workflow_handlers import WorkflowCompletedHandler
        from gleitzeit.core.events import EventType
        from gleitzeit.core.event_error_persistence import EventErrorPersistence
        
        # Create event bus with error persistence if available
        event_error_persistence = None
        if factory_kwargs.get('config', {}).get('persist_event_errors', True):
            # Will use the same persistence adapter once created
            event_error_persistence = EventErrorPersistence()
        
        event_bus = EventBus(
            isolate_errors=True,
            track_errors=True,
            error_persistence=event_error_persistence
        )
        
        # Create persistence adapter WITH event_bus for event-driven support
        factory_kwargs['event_bus'] = event_bus
        self._persistence_adapter = await PersistenceFactory.create(**factory_kwargs)
        
        # Initialize event error persistence with the adapter
        if event_error_persistence:
            event_error_persistence.persistence = self._persistence_adapter
            await event_error_persistence.initialize()
            
            # Also set it globally for access
            from gleitzeit.core.event_error_persistence import set_event_error_persistence
            set_event_error_persistence(event_error_persistence)
        
        # Setup execution components with persistence and event bus
        # IMPORTANT: All components share the SAME persistence adapter instance
        # Use regular QueueManager with integrated event handling
        from gleitzeit.task_queue.task_queue import QueueManager
        queue_manager = QueueManager(persistence=self._persistence_adapter, event_bus=event_bus)
        await queue_manager.initialize()  # Initialize to recover queued tasks from persistence
        dependency_resolver = DependencyResolver()
        registry = ProtocolProviderRegistry()
        self._registry = registry  # Store reference for system methods
        
        # Persistence is now handled directly by ExecutionEngine before emitting events
        # This follows the centralized event architecture where ExecutionEngine is the
        # sole source of task events and saves data before emitting
        
        # Store event bus for client use
        self._event_bus = event_bus
        
        # Enable TaskCompletedHandler so QueueManager gets notified of task completion
        # This is needed for workflow status management in QueueManager
        task_completed_handler = TaskCompletedHandler(
            persistence=self._persistence_adapter,
            queue_manager=queue_manager
        )
        event_bus.register(EventType.TASK_COMPLETED, task_completed_handler)
        
        # Register workflow completion handler (collects workflow results)
        self._workflow_completed_handler = WorkflowCompletedHandler()
        event_bus.register(EventType.WORKFLOW_COMPLETED, self._workflow_completed_handler)
        
        # Register workflow manager (tracks workflow state)
        from gleitzeit.core.event_driven_workflow_manager import EventDrivenWorkflowManager
        self._workflow_manager = EventDrivenWorkflowManager(
            persistence=self._persistence_adapter,
            event_bus=event_bus
        )
        
        # IMPORTANT: ExecutionEngine also uses the SAME persistence adapter instance
        self._execution_engine = ExecutionEngine(
            registry=registry,
            queue_manager=queue_manager,
            dependency_resolver=dependency_resolver,
            persistence=self._persistence_adapter,  # Same instance as all other components
            max_concurrent_tasks=self.native_config.get('max_concurrent_tasks', 5),
            event_bus=event_bus,
            task_timeout=self.native_config.get('task_timeout', 300)  # Configurable task timeout (default 5 minutes)
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
    
    async def process_directory(
        self,
        directory: str,
        file_extensions: List[str],
        workflow_yaml: str,
        max_concurrent: int = 5,
        recursive: bool = True
    ) -> Dict[str, Any]:
        """
        Process all files in a directory with specified extensions using a workflow
        
        Args:
            directory: Path to the directory to process
            file_extensions: List of file extensions to process (e.g., ['.txt', '.md', '.pdf'])
            workflow_yaml: YAML workflow definition to run on each file
            max_concurrent: Maximum number of concurrent workflows
            recursive: Whether to search subdirectories recursively
            
        Returns:
            Dictionary with results for each processed file
        """
        if self.get_mode() == "api":
            return await self._process_directory_api(
                directory, file_extensions, workflow_yaml, max_concurrent, recursive
            )
        else:
            return await self._process_directory_native(
                directory, file_extensions, workflow_yaml, max_concurrent, recursive
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
    
    async def _process_directory_api(
        self, directory: str, file_extensions: List[str], workflow_yaml: str,
        max_concurrent: int, recursive: bool
    ) -> Dict[str, Any]:
        """Process directory via API"""
        try:
            response = await self._api_client.post(
                "/bulk/directory",
                json={
                    "directory": directory,
                    "file_extensions": file_extensions,
                    "workflow_yaml": workflow_yaml,
                    "max_concurrent": max_concurrent,
                    "recursive": recursive
                }
            )
            return response.json()
        except Exception as e:
            return {"error": f"API error: {str(e)}", "results": {}}
        
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
        
        # Apply default retry configuration from client config if tasks don't have one
        if self.native_config and 'retry' in self.native_config:
            default_retry = self.native_config['retry']
            if default_retry.get('enabled', False):
                from gleitzeit.core.models import RetryConfig
                
                default_retry_config = RetryConfig(
                    max_attempts=default_retry.get('max_attempts', 3),
                    backoff_strategy=default_retry.get('backoff_strategy', 'exponential'),
                    base_delay=default_retry.get('base_delay', 1.0),
                    max_delay=default_retry.get('max_delay', 300.0),
                    jitter=default_retry.get('jitter', True)
                )
                
                # Apply to tasks without retry config
                for task in workflow.tasks:
                    if not task.retry_config:
                        task.retry_config = default_retry_config
        
        # Submit and execute
        await self._execution_engine.submit_workflow(workflow)
        await self._execution_engine._execute_workflow(workflow)
        
        # Wait for workflow completion event with results
        try:
            # Get timeout from workflow or use default
            timeout = workflow.timeout if workflow.timeout else 30.0
            workflow_result = await self._workflow_completed_handler.wait_for_workflow(
                workflow.id, 
                timeout=timeout
            )
            
            # Return the results from the event
            return {
                "workflow_id": workflow.id,
                "workflow_name": workflow_result.get("workflow_name", workflow.name),
                "status": workflow_result.get("status", "unknown"),
                "task_results": workflow_result.get("task_results", {}),
                "completed_tasks": workflow_result.get("completed_tasks", []),
                "failed_tasks": workflow_result.get("failed_tasks", []),
                "duration": workflow_result.get("duration", 0)
            }
        except TimeoutError as e:
            logger.error(f"Workflow {workflow.id} timed out: {e}")
            # Fallback to reading from persistence if timeout
            results = {}
            for task in workflow.tasks:
                task_result = await self.get_task_result(task.id)
                if task_result:
                    results[task.id] = {
                        "status": task_result.status,
                        "result": task_result.result,
                        "error": task_result.error
                    }
            
            return {
                "workflow_id": workflow.id,
                "status": "timeout",
                "results": results
            }
        
    
    # =========================================================================
    # Task Management Methods (from old client)
    # =========================================================================
    
    async def _refresh_persistence_session(self):
        """Refresh persistence session to ensure fresh data reads"""
        if hasattr(self._persistence_adapter, 'refresh_session'):
            await self._persistence_adapter.refresh_session()
        elif hasattr(self._persistence_adapter, '_session'):
            # For SQLAlchemy adapters, expire all objects and refresh
            if hasattr(self._persistence_adapter._session, 'expire_all'):
                self._persistence_adapter._session.expire_all()
    
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
            # In native mode, get directly from persistence (no events needed for reads)
            if not self._persistence_adapter:
                return None
            # Ensure we get fresh data from the database
            await self._refresh_persistence_session()
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
            # Ensure we get fresh data from the database
            await self._refresh_persistence_session()
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
                    # The API returns a WorkflowResponse, not a Workflow object
                    # So we'll return the response data as-is (dict)
                    return response.json()
                return None
            except Exception:
                return None
        else:
            if not hasattr(self, '_persistence_adapter') or not self._persistence_adapter:
                return None
            # Ensure we get fresh data from the database
            await self._refresh_persistence_session()
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
            # Ensure we get fresh data from the database
            await self._refresh_persistence_session()
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
            # Ensure we get fresh data from the database
            await self._refresh_persistence_session()
            # get_workflow_tasks is get_tasks_by_workflow in the adapter
            return await self._persistence_adapter.get_tasks_by_workflow(workflow_id)
    
    async def list_workflows(self, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """List workflows with optional filtering"""
        if self.get_mode() == "api":
            try:
                params = {"limit": limit, "offset": offset}
                if status:
                    params["status"] = status
                response = await self._api_client.get("/workflows", params=params)
                if response.status_code == 200:
                    return response.json()
                return {"workflows": [], "total": 0}
            except Exception:
                return {"workflows": [], "total": 0}
        else:
            if not self._persistence_adapter:
                return {"workflows": [], "total": 0}
            # Use keyword arguments to match the unified persistence adapter signature
            return await self._persistence_adapter.list_workflows(
                status=status,
                limit=limit,
                offset=offset
            )
    
    async def list_tasks(self, status: Optional[str] = None, workflow_id: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """List tasks with optional filtering"""
        if self.get_mode() == "api":
            try:
                params = {"limit": limit, "offset": offset}
                if status:
                    params["status"] = status
                if workflow_id:
                    params["workflow_id"] = workflow_id
                response = await self._api_client.get("/tasks", params=params)
                if response.status_code == 200:
                    return response.json()
                return {"tasks": [], "total": 0}
            except Exception:
                return {"tasks": [], "total": 0}
        else:
            if not self._persistence_adapter:
                return {"tasks": [], "total": 0}
            # Use keyword arguments to match the unified persistence adapter signature
            return await self._persistence_adapter.list_tasks(
                workflow_id=workflow_id,
                status=status,
                limit=limit,
                offset=offset
            )
    
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
                # Count active tasks from persistence instead of task_results
                active_tasks = 0
                try:
                    if hasattr(self._execution_engine, 'persistence') and self._execution_engine.persistence:
                        # This is a rough estimate - in event-driven architecture we don't track local task_results
                        active_tasks = 0  # TODO: Could query persistence for executing tasks count if needed
                except:
                    active_tasks = 0
                
                return {
                    "active_tasks": active_tasks,
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
    
    async def delete_task(self, task_id: str) -> bool:
        """
        Delete a task and its associated data
        
        Args:
            task_id: ID of the task to delete
            
        Returns:
            True if task was deleted, False otherwise
        """
        if self.get_mode() == "api":
            try:
                response = await self._api_client.delete(f"/tasks/{task_id}")
                return response.status_code == 200
            except Exception:
                return False
        else:
            if not self._persistence_adapter:
                return False
            return await self._persistence_adapter.delete_task(task_id)
    
    async def delete_workflow(self, workflow_id: str) -> bool:
        """
        Delete a workflow and all its associated tasks
        
        This will:
        - Delete all tasks belonging to the workflow
        - Delete all task results for those tasks
        - Delete workflow execution records
        - Clean up queue state references to deleted tasks
        
        Args:
            workflow_id: ID of the workflow to delete
            
        Returns:
            True if workflow was deleted, False otherwise
        """
        if self.get_mode() == "api":
            try:
                response = await self._api_client.delete(f"/workflows/{workflow_id}")
                return response.status_code == 200
            except Exception:
                return False
        else:
            if not self._persistence_adapter:
                return False
            return await self._persistence_adapter.delete_workflow(workflow_id)
    
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
        
        # Return basic metrics since ResourceManager may not have get_metrics
        try:
            return await self._resource_manager.get_metrics()
        except AttributeError:
            # Fallback if get_metrics doesn't exist
            return {
                "enabled": True,
                "resource_manager_id": getattr(self._resource_manager, "manager_id", "unknown"),
                "hubs_count": len(getattr(self._resource_manager, "_hubs", {}))
            }
    
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
    
    # Workflow Management Methods
    async def clone_workflow(self, workflow_id: str, new_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Clone an existing workflow
        
        Args:
            workflow_id: ID of workflow to clone
            new_name: Optional new name for cloned workflow
            
        Returns:
            Cloned workflow information
        """
        if self.get_mode() == "api":
            data = {"new_name": new_name} if new_name else {}
            response = await self._api_client.post(f"/workflows/{workflow_id}/clone", json=data)
            return response.json()
        else:
            if not self._persistence_adapter:
                raise RuntimeError("Persistence adapter not available")
            
            # Get original workflow
            original = await self._persistence_adapter.get_workflow(workflow_id)
            if not original:
                raise ValueError(f"Workflow {workflow_id} not found")
            
            # Create cloned workflow
            from ..models import Workflow
            cloned = Workflow(
                id=f"{workflow_id}_clone_{int(time.time())}",
                name=new_name or f"{original.name}_clone",
                tasks=original.tasks.copy() if original.tasks else [],
                dependencies=original.dependencies.copy() if original.dependencies else {},
                metadata=original.metadata.copy() if original.metadata else {}
            )
            
            # Store cloned workflow
            await self._persistence_adapter.store_workflow(cloned)
            
            return cloned.to_dict()
    
    async def cancel_workflows(self, workflow_ids: List[str]) -> Dict[str, Any]:
        """
        Cancel multiple workflows in bulk
        
        Args:
            workflow_ids: List of workflow IDs to cancel
            
        Returns:
            Results of bulk cancellation
        """
        if self.get_mode() == "api":
            response = await self._api_client.post("/workflows/bulk/cancel", json={"workflow_ids": workflow_ids})
            return response.json()
        else:
            if not self._execution_engine:
                raise RuntimeError("Execution engine not available")
            
            results = {"successful": [], "failed": []}
            
            for workflow_id in workflow_ids:
                try:
                    await self._execution_engine.cancel_workflow(workflow_id)
                    results["successful"].append(workflow_id)
                except Exception as e:
                    results["failed"].append({"workflow_id": workflow_id, "error": str(e)})
            
            return results
    
    async def retry_workflows(self, workflow_ids: List[str]) -> Dict[str, Any]:
        """
        Retry multiple failed workflows in bulk
        
        Args:
            workflow_ids: List of workflow IDs to retry
            
        Returns:
            Results of bulk retry
        """
        if self.get_mode() == "api":
            response = await self._api_client.post("/workflows/bulk/retry", json={"workflow_ids": workflow_ids})
            return response.json()
        else:
            if not self._execution_engine:
                raise RuntimeError("Execution engine not available")
            
            results = {"successful": [], "failed": []}
            
            for workflow_id in workflow_ids:
                try:
                    await self._execution_engine.retry_workflow(workflow_id)
                    results["successful"].append(workflow_id)
                except Exception as e:
                    results["failed"].append({"workflow_id": workflow_id, "error": str(e)})
            
            return results
    
    async def get_workflow_statistics(self) -> Dict[str, Any]:
        """
        Get workflow execution statistics
        
        Returns:
            Workflow statistics including counts by status
        """
        if self.get_mode() == "api":
            response = await self._api_client.get("/workflows/statistics")
            return response.json()
        else:
            if not self._persistence_adapter:
                raise RuntimeError("Persistence adapter not available")
            
            # Get basic stats from persistence
            workflows = await self._persistence_adapter.list_workflows()
            
            stats = {
                "total_workflows": len(workflows),
                "by_status": {},
                "by_provider": {},
                "execution_time_avg": 0
            }
            
            for workflow in workflows:
                status = getattr(workflow, 'status', 'unknown')
                provider = getattr(workflow, 'provider', 'unknown')
                
                stats["by_status"][status] = stats["by_status"].get(status, 0) + 1
                stats["by_provider"][provider] = stats["by_provider"].get(provider, 0) + 1
            
            return stats
    
    # System Utility Methods
    async def get_providers(self) -> List[Dict[str, Any]]:
        """
        Get list of available providers
        
        Returns:
            List of provider information
        """
        if self.get_mode() == "api":
            response = await self._api_client.get("/providers")
            return response.json()
        else:
            if not self._registry:
                return []
            
            providers = []
            for provider_id, provider_info in self._registry.providers.items():
                provider_instance = self._registry.provider_instances.get(provider_id)
                providers.append({
                    "id": provider_id,
                    "protocols": list(provider_info.protocols) if hasattr(provider_info, 'protocols') else [],
                    "class": provider_instance.__class__.__name__ if provider_instance else "Unknown",
                    "status": getattr(provider_info, 'status', 'unknown'),
                    "capabilities": getattr(provider_instance, "capabilities", {}) if provider_instance else {}
                })
            
            return providers
    
    async def get_protocols(self) -> List[Dict[str, Any]]:
        """
        Get list of supported protocols
        
        Returns:
            List of protocol information
        """
        if self.get_mode() == "api":
            response = await self._api_client.get("/protocols")
            return response.json()
        else:
            if not self._registry or not self._registry.protocol_registry:
                return []
            
            protocols = []
            for protocol_id, protocol_spec in self._registry.protocol_registry._protocols.items():
                protocols.append({
                    "id": protocol_id,
                    "version": getattr(protocol_spec, "version", "1.0"),
                    "description": getattr(protocol_spec, "description", ""),
                    "parameters": getattr(protocol_spec, "parameters", {}),
                    "result_schema": getattr(protocol_spec, "result_schema", {})
                })
            
            return protocols
    
    async def get_system_limits(self) -> Dict[str, Any]:
        """
        Get current system limits and resource constraints
        
        Returns:
            System limits information
        """
        if self.get_mode() == "api":
            response = await self._api_client.get("/system/limits")
            return response.json()
        else:
            limits = {
                "max_concurrent_workflows": getattr(self._execution_engine, "max_concurrent", "unlimited") if self._execution_engine else 0,
                "max_workflow_size": "unlimited",
                "max_task_timeout": "unlimited",
                "resource_pools": len(getattr(self._resource_manager, "_pools", {})) if self._resource_manager else 0,
                "persistence_type": self.persistence_backend
            }
            
            return limits
    
    async def get_system_status(self) -> Dict[str, Any]:
        """
        Get comprehensive system status
        
        Returns:
            System status including all components
        """
        if self.get_mode() == "api":
            response = await self._api_client.get("/system/status")
            return response.json()
        else:
            status = {
                "mode": self.get_mode(),
                "execution_engine": bool(self._execution_engine),
                "persistence_adapter": bool(self._persistence_adapter),
                "resource_manager": bool(self._resource_manager),
                "registry": bool(self._registry),
                "auth_enabled": self._auth_enabled,
                "persistence_backend": self.persistence_backend,
                "uptime": time.time() - getattr(self, '_start_time', time.time()),
                "version": "0.0.6"
            }
            
            # Add resource metrics if available
            if self._resource_manager:
                status["resource_metrics"] = await self.get_resource_metrics()
            
            return status
    
    # System Initialization Methods
    async def start_execution_engine(self, mode: str = "event_driven") -> bool:
        """
        Start the execution engine in the specified mode
        
        Args:
            mode: Execution mode (default: "event_driven")
            
        Returns:
            True if started successfully, False otherwise
        """
        if self.get_mode() == "api":
            # In API mode, assume the server handles engine startup
            return True
        else:
            if not self._execution_engine:
                return False
            
            try:
                from gleitzeit.core import ExecutionMode
                exec_mode = ExecutionMode.EVENT_DRIVEN if mode == "event_driven" else ExecutionMode.BATCH
                await self._execution_engine.start(exec_mode)
                return True
            except Exception as e:
                logger.error(f"Failed to start execution engine: {e}")
                return False
    
    async def get_event_bus(self) -> Optional[Any]:
        """
        Get the event bus for logging and monitoring setup
        
        Returns:
            Event bus instance or None
        """
        if self.get_mode() == "api":
            # In API mode, event bus is handled by the server
            return None
        else:
            if self._execution_engine and hasattr(self._execution_engine, 'event_bus'):
                return self._execution_engine.event_bus
            return None
    
    async def get_persistence_instance(self) -> Optional[Any]:
        """
        Get the persistence instance for logging and system setup
        
        Returns:
            Persistence instance or None
        """
        if self.get_mode() == "api":
            # In API mode, persistence is handled by the server
            return None
        else:
            if self._execution_engine and hasattr(self._execution_engine, 'persistence'):
                return self._execution_engine.persistence
            return None
    
    async def check_redis_persistence(self) -> Dict[str, Any]:
        """
        Check if Redis persistence is available and get connection info
        
        Returns:
            Dictionary with Redis availability and connection info
        """
        if self.get_mode() == "api":
            # In API mode, delegate to server
            try:
                response = await self._api_client.get("/system/redis-status")
                return response.json()
            except:
                return {"available": False, "reason": "API not available"}
        else:
            try:
                persistence = await self.get_persistence_instance()
                if not persistence:
                    return {"available": False, "reason": "No persistence adapter"}
                
                # Check for Redis in persistence
                if hasattr(persistence, '_adapters'):
                    # Hybrid adapter - check for Redis
                    for adapter in persistence._adapters:
                        if hasattr(adapter, 'redis') and adapter.redis:
                            return {
                                "available": True,
                                "type": "hybrid",
                                "adapter_type": adapter.__class__.__name__,
                                "connection": str(adapter.redis)
                            }
                elif hasattr(persistence, 'redis') and persistence.redis:
                    # Direct Redis adapter
                    return {
                        "available": True,
                        "type": "direct", 
                        "adapter_type": persistence.__class__.__name__,
                        "connection": str(persistence.redis)
                    }
                
                return {"available": False, "reason": "No Redis found in persistence"}
                
            except Exception as e:
                return {"available": False, "reason": f"Error checking Redis: {str(e)}"}
    
    async def initialize_logging_system(self) -> Dict[str, Any]:
        """
        Initialize the logging system with event bus and persistence
        
        Returns:
            Status of logging system initialization
        """
        if self.get_mode() == "api":
            return {"status": "delegated_to_api", "message": "Logging handled by API server"}
        else:
            try:
                event_bus = await self.get_event_bus()
                persistence = await self.get_persistence_instance()
                redis_info = await self.check_redis_persistence()
                
                # Initialize log collector if we have the required components
                from gleitzeit.core.log_collector import LogCollector, set_log_collector
                from gleitzeit.core.log_stream import LogStreamManager, set_log_stream_manager
                
                if event_bus and persistence and redis_info.get("available"):
                    # Initialize with Redis support
                    log_collector = LogCollector(
                        event_bus=event_bus,
                        persistence=persistence,
                        enable_streaming=True
                    )
                    set_log_collector(log_collector)
                    
                    log_stream_manager = LogStreamManager(log_collector)
                    set_log_stream_manager(log_stream_manager)
                    
                    return {
                        "status": "initialized",
                        "streaming_enabled": True,
                        "redis_available": True,
                        "components": ["LogCollector", "LogStreamManager"]
                    }
                else:
                    # Initialize with basic support
                    if event_bus:
                        log_collector = LogCollector(
                            event_bus=event_bus,
                            persistence=persistence,
                            enable_streaming=False
                        )
                        set_log_collector(log_collector)
                        
                        return {
                            "status": "initialized",
                            "streaming_enabled": False,
                            "redis_available": redis_info.get("available", False),
                            "components": ["LogCollector"]
                        }
                
                return {"status": "not_initialized", "reason": "Missing required components"}
                
            except Exception as e:
                logger.error(f"Failed to initialize logging system: {e}")
                return {"status": "error", "reason": str(e)}
        
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
    
    async def _process_directory_native(
        self, directory: str, file_extensions: List[str], workflow_yaml: str,
        max_concurrent: int, recursive: bool
    ) -> Dict[str, Any]:
        """Process directory using native execution engine"""
        import os
        import glob
        import yaml
        import asyncio
        from pathlib import Path
        
        # Parse the workflow YAML
        try:
            workflow_template = yaml.safe_load(workflow_yaml)
        except Exception as e:
            return {"error": f"Invalid workflow YAML: {str(e)}", "results": {}}
        
        # Find all matching files
        dir_path = Path(directory)
        if not dir_path.exists():
            return {"error": f"Directory not found: {directory}", "results": {}}
        
        matching_files = []
        for ext in file_extensions:
            if recursive:
                pattern = f"**/*{ext}"
                files = dir_path.glob(pattern)
            else:
                pattern = f"*{ext}"
                files = dir_path.glob(pattern)
            matching_files.extend([str(f) for f in files if f.is_file()])
        
        if not matching_files:
            return {
                "message": "No matching files found",
                "directory": directory,
                "extensions": file_extensions,
                "results": {}
            }
        
        # Process files with concurrency limit
        results = {}
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def process_file(file_path):
            async with semaphore:
                try:
                    # Create a workflow for this file
                    file_workflow = workflow_template.copy()
                    
                    # Replace ${file_path} placeholder in the workflow
                    workflow_str = yaml.dump(file_workflow)
                    workflow_str = workflow_str.replace("${file_path}", file_path)
                    workflow_str = workflow_str.replace("${file_name}", os.path.basename(file_path))
                    
                    # Save to temp file and run
                    import tempfile
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
                        f.write(workflow_str)
                        temp_path = f.name
                    
                    try:
                        result = await self.run_workflow(temp_path, watch=True)
                        results[file_path] = {"status": "success", "result": result}
                    finally:
                        os.unlink(temp_path)
                        
                except Exception as e:
                    results[file_path] = {"status": "failed", "error": str(e)}
        
        # Process all files
        tasks = [process_file(f) for f in matching_files]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # Summary
        successful = sum(1 for r in results.values() if r.get("status") == "success")
        failed = len(results) - successful
        
        return {
            "directory": directory,
            "file_extensions": file_extensions,
            "total_files": len(matching_files),
            "successful": successful,
            "failed": failed,
            "results": results
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
        
        # Get result from persistence instead of task_results
        if self._execution_engine.persistence:
            result = await self._execution_engine.persistence.get_task_result(task.id)
            if result and result.status == TaskStatus.COMPLETED:
                return result.result.get("response", "")
        
        # If no result found
        raise RuntimeError(f"Chat failed: {result.error if result else 'Unknown error'}")
    
    async def get_workflow_from_persistence(self, workflow_id: str):
        """Get workflow status from QueueManager via persistence (internal use)"""
        if not hasattr(self, '_persistence_adapter') or not self._persistence_adapter:
            raise RuntimeError("Persistence not initialized")
        
        # Get workflow from persistence (QueueManager is authoritative source)
        return await self._persistence_adapter.get_workflow(workflow_id)

    # =========================================================================
    # Authentication & User Management Methods
    # =========================================================================
    
    async def login(self, username: str, password: str) -> Dict[str, Any]:
        """
        Login with username/email and password
        
        Args:
            username: Username or email
            password: Password
            
        Returns:
            Login response with access token and user info
        """
        if self.get_mode() == "api":
            try:
                response = await self._api_client.post(
                    "/auth/login",
                    json={"username": username, "password": password}
                )
                if response.status_code == 200:
                    return response.json()
                else:
                    error = response.json() if response.status_code != 500 else {"detail": "Login failed"}
                    raise RuntimeError(f"Login failed: {error.get('detail', 'Unknown error')}")
            except Exception as e:
                raise RuntimeError(f"Login failed: {e}")
        else:
            # In native mode, handle authentication directly
            from .auth.basic_auth import is_basic_mode
            from .auth.database import get_auth_db
            from .auth.utils import verify_password, create_jwt_token, hash_api_key
            from datetime import timedelta
            
            if is_basic_mode():
                # Return basic user response
                from .auth.basic_auth import create_basic_auth_response
                return create_basic_auth_response()
            
            # Admin mode - perform actual authentication
            auth_db = get_auth_db()
            
            # Find user by email or username
            user = await auth_db.get_user_by_email(username)
            if not user:
                user = await auth_db.get_user_by_username(username)
            
            if not user or not user.is_active:
                raise RuntimeError("Invalid username or password")
            
            # Verify password
            if not user.password_hash or not verify_password(password, user.password_hash):
                raise RuntimeError("Invalid username or password")
            
            # Update last login
            await auth_db.update_user_last_login(user.id)
            
            # Create tokens
            jwt_secret = os.getenv("GLEITZEIT_AUTH_JWT_SECRET", "change-me-in-production")
            
            # Access token payload
            access_payload = {
                "sub": str(user.id),
                "email": user.email,
                "username": user.username,
                "roles": [role.name for role in user.roles],
                "is_superuser": user.is_superuser,
                "type": "access"
            }
            
            access_token = create_jwt_token(
                access_payload, jwt_secret, expires_delta=timedelta(hours=1)
            )
            
            # Refresh token payload
            refresh_payload = {"sub": str(user.id), "type": "refresh"}
            refresh_token = create_jwt_token(
                refresh_payload, jwt_secret, expires_delta=timedelta(days=30)
            )
            
            # Create session
            session_data = {
                "token_hash": hash_api_key(access_token),
                "refresh_token_hash": hash_api_key(refresh_token),
                "expires_at": datetime.utcnow() + timedelta(hours=1),
                "refresh_expires_at": datetime.utcnow() + timedelta(days=30)
            }
            
            await auth_db.create_session(user.id, session_data)
            
            # Log successful login
            await auth_db.create_audit_log(
                user_id=user.id,
                action="login",
                resource_type="auth",
                details={"method": "password"}
            )
            
            return {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "expires_in": 3600,
                "user": {
                    "id": str(user.id),
                    "email": user.email,
                    "username": user.username,
                    "full_name": user.full_name,
                    "roles": [role.name for role in user.roles],
                    "is_superuser": user.is_superuser
                }
            }
    
    async def logout(self) -> Dict[str, Any]:
        """
        Logout current user
        
        Returns:
            Logout confirmation
        """
        if self.get_mode() == "api":
            try:
                response = await self._api_client.post("/auth/logout")
                if response.status_code == 200:
                    return response.json()
                else:
                    raise RuntimeError("Logout failed")
            except Exception as e:
                raise RuntimeError(f"Logout failed: {e}")
        else:
            # In native mode, handle session cleanup if needed
            from .auth.basic_auth import is_basic_mode
            from .auth.database import get_auth_db
            
            if is_basic_mode():
                # In basic mode, just return success
                return {"message": "Logged out successfully"}
            
            # In admin mode, would need session context to clean up properly
            # For now, just return success (session cleanup would need user context)
            auth_db = get_auth_db()
            
            # Log logout (would need user context)
            # await auth_db.create_audit_log(
            #     user_id=user_id,
            #     action="logout",
            #     resource_type="auth"
            # )
            
            return {"message": "Logged out successfully"}
    
    async def get_current_user(self) -> Dict[str, Any]:
        """
        Get current authenticated user information
        
        Returns:
            Current user details
        """
        if self.get_mode() == "api":
            try:
                response = await self._api_client.get("/auth/me")
                if response.status_code == 200:
                    return response.json()
                else:
                    raise RuntimeError("Failed to get user info")
            except Exception as e:
                raise RuntimeError(f"Failed to get user info: {e}")
        else:
            # In native mode, return basic user
            from .auth.basic_auth import basic_auth
            return basic_auth.get_basic_user()
    
    async def create_user(self, email: str, password: str, username: str = None, 
                         full_name: str = None, roles: List[str] = None) -> Dict[str, Any]:
        """
        Create a new user (admin only)
        
        Args:
            email: User email
            password: User password
            username: Optional username
            full_name: Optional full name
            roles: Optional list of role names
            
        Returns:
            Created user information
        """
        if self.get_mode() == "api":
            try:
                user_data = {
                    "email": email,
                    "password": password,
                    "username": username,
                    "full_name": full_name
                }
                response = await self._api_client.post("/auth/users", json=user_data)
                if response.status_code == 201:
                    user = response.json()
                    # Assign roles if specified
                    if roles:
                        for role in roles:
                            await self.assign_user_role(user["id"], role)
                    return user
                else:
                    error = response.json() if response.status_code != 500 else {"detail": "User creation failed"}
                    raise RuntimeError(f"User creation failed: {error.get('detail', 'Unknown error')}")
            except Exception as e:
                raise RuntimeError(f"User creation failed: {e}")
        else:
            # In native mode, use auth database directly
            from .auth.database import get_auth_db
            from .auth.basic_auth import is_basic_mode
            
            if is_basic_mode():
                raise RuntimeError("User creation requires admin mode. Set GLEITZEIT_AUTH_MODE=admin")
            
            auth_db = get_auth_db()
            user_data = {
                "email": email,
                "username": username or email.split("@")[0],
                "password": password,
                "full_name": full_name,
                "is_active": True,
                "is_superuser": False
            }
            
            user = await auth_db.create_user(user_data)
            
            # Assign roles
            if roles:
                for role in roles:
                    await auth_db.add_user_role(user.id, role)
            else:
                await auth_db.add_user_role(user.id, "user")  # Default role
            
            return {
                "id": str(user.id),
                "email": user.email,
                "username": user.username,
                "full_name": user.full_name,
                "roles": roles or ["user"]
            }
    
    async def get_user(self, user_id: str) -> Dict[str, Any]:
        """
        Get user by ID
        
        Args:
            user_id: User ID
            
        Returns:
            User information
        """
        if self.get_mode() == "api":
            try:
                response = await self._api_client.get(f"/auth/users/{user_id}")
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 404:
                    raise RuntimeError("User not found")
                else:
                    raise RuntimeError("Failed to get user")
            except Exception as e:
                raise RuntimeError(f"Failed to get user: {e}")
        else:
            # In native mode, use auth database directly
            from .auth.database import get_auth_db
            from .auth.basic_auth import is_basic_mode
            
            if is_basic_mode():
                raise RuntimeError("User management requires admin mode. Set GLEITZEIT_AUTH_MODE=admin")
            
            auth_db = get_auth_db()
            user = await auth_db.get_user(user_id)
            
            if not user:
                raise RuntimeError("User not found")
            
            return {
                "id": str(user.id),
                "email": user.email,
                "username": user.username,
                "full_name": user.full_name,
                "roles": [role.name for role in user.roles],
                "is_superuser": user.is_superuser,
                "is_active": user.is_active,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "last_login": user.last_login.isoformat() if user.last_login else None
            }
    
    async def list_users(self, skip: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        """
        List all users (admin only)
        
        Args:
            skip: Number of users to skip
            limit: Maximum number of users to return
            
        Returns:
            List of users
        """
        if self.get_mode() == "api":
            try:
                response = await self._api_client.get(f"/auth/users?skip={skip}&limit={limit}")
                if response.status_code == 200:
                    return response.json()
                else:
                    raise RuntimeError("Failed to list users")
            except Exception as e:
                raise RuntimeError(f"Failed to list users: {e}")
        else:
            # In native mode, use auth database directly
            from .auth.database import get_auth_db
            from .auth.basic_auth import is_basic_mode
            
            if is_basic_mode():
                raise RuntimeError("User management requires admin mode. Set GLEITZEIT_AUTH_MODE=admin")
            
            auth_db = get_auth_db()
            users = await auth_db.list_users(skip=skip, limit=limit)
            
            return [
                {
                    "id": str(user.id),
                    "email": user.email,
                    "username": user.username,
                    "full_name": user.full_name,
                    "roles": [role.name for role in user.roles],
                    "is_superuser": user.is_superuser,
                    "is_active": user.is_active,
                    "created_at": user.created_at.isoformat() if user.created_at else None,
                    "last_login": user.last_login.isoformat() if user.last_login else None
                }
                for user in users
            ]
    
    async def update_user(self, user_id: str, **updates) -> Dict[str, Any]:
        """
        Update user information
        
        Args:
            user_id: User ID
            **updates: Fields to update (email, username, full_name, is_active, is_superuser)
            
        Returns:
            Updated user information
        """
        if self.get_mode() == "api":
            try:
                response = await self._api_client.put(f"/auth/users/{user_id}", json=updates)
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 404:
                    raise RuntimeError("User not found")
                else:
                    error = response.json() if response.status_code != 500 else {"detail": "User update failed"}
                    raise RuntimeError(f"User update failed: {error.get('detail', 'Unknown error')}")
            except Exception as e:
                raise RuntimeError(f"User update failed: {e}")
        else:
            # In native mode, use auth database directly
            from .auth.database import get_auth_db
            from .auth.basic_auth import is_basic_mode
            
            if is_basic_mode():
                raise RuntimeError("User management requires admin mode. Set GLEITZEIT_AUTH_MODE=admin")
            
            auth_db = get_auth_db()
            user = await auth_db.update_user(user_id, updates)
            
            if not user:
                raise RuntimeError("User not found")
            
            return {
                "id": str(user.id),
                "email": user.email,
                "username": user.username,
                "full_name": user.full_name,
                "roles": [role.name for role in user.roles],
                "is_superuser": user.is_superuser,
                "is_active": user.is_active
            }
    
    async def delete_user(self, user_id: str) -> bool:
        """
        Delete a user
        
        Args:
            user_id: User ID
            
        Returns:
            True if user was deleted
        """
        if self.get_mode() == "api":
            try:
                response = await self._api_client.delete(f"/auth/users/{user_id}")
                return response.status_code == 200
            except Exception:
                return False
        else:
            # In native mode, use auth database directly
            from .auth.database import get_auth_db
            from .auth.basic_auth import is_basic_mode
            
            if is_basic_mode():
                raise RuntimeError("User management requires admin mode. Set GLEITZEIT_AUTH_MODE=admin")
            
            auth_db = get_auth_db()
            return await auth_db.delete_user(user_id)
    
    async def assign_user_role(self, user_id: str, role_name: str) -> bool:
        """
        Assign a role to a user
        
        Args:
            user_id: User ID
            role_name: Role name
            
        Returns:
            True if role was assigned
        """
        if self.get_mode() == "api":
            try:
                response = await self._api_client.post(
                    f"/auth/users/{user_id}/roles",
                    json={"role": role_name}
                )
                return response.status_code == 200
            except Exception:
                return False
        else:
            # In native mode, use auth database directly
            from .auth.database import get_auth_db
            from .auth.basic_auth import is_basic_mode
            
            if is_basic_mode():
                raise RuntimeError("User management requires admin mode. Set GLEITZEIT_AUTH_MODE=admin")
            
            auth_db = get_auth_db()
            return await auth_db.add_user_role(user_id, role_name)
    
    async def remove_user_role(self, user_id: str, role_name: str) -> bool:
        """
        Remove a role from a user
        
        Args:
            user_id: User ID
            role_name: Role name
            
        Returns:
            True if role was removed
        """
        if self.get_mode() == "api":
            try:
                response = await self._api_client.delete(f"/auth/users/{user_id}/roles/{role_name}")
                return response.status_code == 200
            except Exception:
                return False
        else:
            # In native mode, use auth database directly
            from .auth.database import get_auth_db
            from .auth.basic_auth import is_basic_mode
            
            if is_basic_mode():
                raise RuntimeError("User management requires admin mode. Set GLEITZEIT_AUTH_MODE=admin")
            
            auth_db = get_auth_db()
            return await auth_db.remove_user_role(user_id, role_name)
    
    async def create_api_key(self, name: str, description: str = None, 
                           expires_in_days: int = None) -> Dict[str, Any]:
        """
        Create an API key for current user
        
        Args:
            name: API key name
            description: Optional description
            expires_in_days: Optional expiration in days
            
        Returns:
            API key information (including the key value - store it safely!)
        """
        if self.get_mode() == "api":
            try:
                key_data = {
                    "name": name,
                    "description": description,
                    "expires_in_days": expires_in_days
                }
                response = await self._api_client.post("/auth/api-keys", json=key_data)
                if response.status_code == 200:
                    return response.json()
                else:
                    error = response.json() if response.status_code != 500 else {"detail": "API key creation failed"}
                    raise RuntimeError(f"API key creation failed: {error.get('detail', 'Unknown error')}")
            except Exception as e:
                raise RuntimeError(f"API key creation failed: {e}")
        else:
            # In native mode, use auth database directly
            from .auth.database import get_auth_db
            from .auth.basic_auth import is_basic_mode
            
            if is_basic_mode():
                raise RuntimeError("API key management requires admin mode. Set GLEITZEIT_AUTH_MODE=admin")
            
            # Would need current user context in native mode
            raise RuntimeError("API key creation in native mode requires user context")
    
    async def list_api_keys(self) -> List[Dict[str, Any]]:
        """
        List API keys for current user
        
        Returns:
            List of API keys (without key values)
        """
        if self.get_mode() == "api":
            try:
                response = await self._api_client.get("/auth/api-keys")
                if response.status_code == 200:
                    return response.json()
                else:
                    raise RuntimeError("Failed to list API keys")
            except Exception as e:
                raise RuntimeError(f"Failed to list API keys: {e}")
        else:
            from .auth.basic_auth import is_basic_mode
            if is_basic_mode():
                raise RuntimeError("API key management requires admin mode. Set GLEITZEIT_AUTH_MODE=admin")
            raise RuntimeError("API key listing in native mode requires user context")
    
    async def revoke_api_key(self, key_id: str) -> bool:
        """
        Revoke an API key
        
        Args:
            key_id: API key ID
            
        Returns:
            True if key was revoked
        """
        if self.get_mode() == "api":
            try:
                response = await self._api_client.delete(f"/auth/api-keys/{key_id}")
                return response.status_code == 200
            except Exception:
                return False
        else:
            from .auth.basic_auth import is_basic_mode
            if is_basic_mode():
                raise RuntimeError("API key management requires admin mode. Set GLEITZEIT_AUTH_MODE=admin")
            return False
    
    async def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """
        Refresh access token using refresh token
        
        Args:
            refresh_token: Refresh token
            
        Returns:
            New access and refresh tokens
        """
        if self.get_mode() == "api":
            try:
                response = await self._api_client.post(
                    "/auth/refresh",
                    json={"refresh_token": refresh_token}
                )
                if response.status_code == 200:
                    return response.json()
                else:
                    error = response.json() if response.status_code != 500 else {"detail": "Token refresh failed"}
                    raise RuntimeError(f"Token refresh failed: {error.get('detail', 'Unknown error')}")
            except Exception as e:
                raise RuntimeError(f"Token refresh failed: {e}")
        else:
            # In native mode, use auth utils directly
            from .auth.utils import decode_jwt_token, create_jwt_token
            from .auth.database import get_auth_db
            from .auth.basic_auth import is_basic_mode
            from datetime import timedelta
            
            if is_basic_mode():
                # In basic mode, just return basic user response
                from .auth.basic_auth import create_basic_auth_response
                return create_basic_auth_response()
            
            # Decode refresh token
            jwt_secret = os.getenv("GLEITZEIT_AUTH_JWT_SECRET", "change-me-in-production")
            payload = decode_jwt_token(refresh_token, jwt_secret)
            if not payload or payload.get("type") != "refresh":
                raise RuntimeError("Invalid refresh token")
            
            # Get user and create new tokens
            auth_db = get_auth_db()
            user = await auth_db.get_user(payload.get("sub"))
            
            if not user or not user.is_active:
                raise RuntimeError("User not found or inactive")
            
            # Create new tokens
            access_payload = {
                "sub": str(user.id),
                "email": user.email,
                "username": user.username,
                "roles": [role.name for role in user.roles],
                "is_superuser": user.is_superuser,
                "type": "access"
            }
            
            new_access_token = create_jwt_token(
                access_payload, jwt_secret, expires_delta=timedelta(hours=1)
            )
            
            new_refresh_payload = {"sub": str(user.id), "type": "refresh"}
            new_refresh_token = create_jwt_token(
                new_refresh_payload, jwt_secret, expires_delta=timedelta(days=30)
            )
            
            return {
                "access_token": new_access_token,
                "refresh_token": new_refresh_token,
                "token_type": "bearer",
                "expires_in": 3600,
                "user": {
                    "id": str(user.id),
                    "email": user.email,
                    "username": user.username,
                    "full_name": user.full_name,
                    "roles": [role.name for role in user.roles],
                    "is_superuser": user.is_superuser
                }
            }
    
    async def change_password(self, old_password: str, new_password: str, user_id: str = None) -> Dict[str, Any]:
        """
        Change password for current user or specified user
        
        Args:
            old_password: Current password
            new_password: New password
            user_id: Optional user ID (for admin operations)
            
        Returns:
            Success confirmation
        """
        if self.get_mode() == "api":
            try:
                response = await self._api_client.post(
                    "/auth/change-password",
                    json={"old_password": old_password, "new_password": new_password}
                )
                if response.status_code == 200:
                    return response.json()
                else:
                    error = response.json() if response.status_code != 500 else {"detail": "Password change failed"}
                    raise RuntimeError(f"Password change failed: {error.get('detail', 'Unknown error')}")
            except Exception as e:
                raise RuntimeError(f"Password change failed: {e}")
        else:
            # In native mode, use auth database directly
            from .auth.database import get_auth_db
            from .auth.utils import verify_password, hash_password
            from .auth.basic_auth import is_basic_mode
            
            if is_basic_mode():
                raise RuntimeError("Password change requires admin mode. Set GLEITZEIT_AUTH_MODE=admin")
            
            auth_db = get_auth_db()
            
            # For now, assume current user (would need user context)
            if user_id:
                user_record = await auth_db.get_user(user_id)
            else:
                # Would need current user context - for now raise error
                raise RuntimeError("Password change in native mode requires user context")
            
            if not user_record:
                raise RuntimeError("User not found")
            
            # Verify old password
            if not verify_password(old_password, user_record.password_hash):
                raise RuntimeError("Invalid old password")
            
            # Update password
            user_record.password_hash = hash_password(new_password)
            await auth_db.update_user(user_record.id, {"password_hash": user_record.password_hash})
            
            # Log password change
            await auth_db.create_audit_log(
                user_id=user_record.id,
                action="change_password",
                resource_type="auth"
            )
            
            return {"message": "Password changed successfully"}
    
    async def register_user(self, email: str, password: str, username: str = None, 
                           full_name: str = None) -> Dict[str, Any]:
        """
        Register a new user (public registration)
        
        Args:
            email: User email
            password: User password  
            username: Optional username
            full_name: Optional full name
            
        Returns:
            Created user information
        """
        if self.get_mode() == "api":
            try:
                user_data = {
                    "email": email,
                    "password": password,
                    "username": username,
                    "full_name": full_name
                }
                response = await self._api_client.post("/auth/register", json=user_data)
                if response.status_code == 200:
                    return response.json()
                else:
                    error = response.json() if response.status_code != 500 else {"detail": "Registration failed"}
                    raise RuntimeError(f"Registration failed: {error.get('detail', 'Unknown error')}")
            except Exception as e:
                raise RuntimeError(f"Registration failed: {e}")
        else:
            # In native mode, check auth mode and use database
            from .auth.basic_auth import is_basic_mode
            from .auth.database import get_auth_db
            
            if is_basic_mode():
                raise RuntimeError("User registration requires admin mode. Set GLEITZEIT_AUTH_MODE=admin")
            
            # Check if registration is enabled
            if os.getenv("GLEITZEIT_AUTH_ALLOW_REGISTRATION", "false").lower() != "true":
                raise RuntimeError("User registration is disabled")
            
            auth_db = get_auth_db()
            
            # Check if email exists
            existing = await auth_db.get_user_by_email(email)
            if existing:
                raise RuntimeError("Email already registered")
            
            # Check if username exists
            if username:
                existing = await auth_db.get_user_by_username(username)
                if existing:
                    raise RuntimeError("Username already taken")
            
            # Create user
            user_data = {
                "email": email,
                "username": username or email.split("@")[0],
                "password": password,
                "full_name": full_name,
                "is_active": True,
                "is_superuser": False
            }
            
            user = await auth_db.create_user(user_data)
            
            # Add default role
            await auth_db.add_user_role(user.id, "viewer")
            
            # Log registration
            await auth_db.create_audit_log(
                user_id=user.id,
                action="register",
                resource_type="auth"
            )
            
            return {
                "message": "User registered successfully",
                "user": {
                    "id": str(user.id),
                    "email": user.email,
                    "username": user.username
                }
            }
    
    async def list_roles(self) -> List[Dict[str, Any]]:
        """
        List all available roles
        
        Returns:
            List of available roles
        """
        if self.get_mode() == "api":
            try:
                response = await self._api_client.get("/auth/roles")
                if response.status_code == 200:
                    return response.json()
                else:
                    raise RuntimeError("Failed to list roles")
            except Exception as e:
                raise RuntimeError(f"Failed to list roles: {e}")
        else:
            # In native mode, return default roles
            from .auth.basic_auth import is_basic_mode
            
            if is_basic_mode():
                raise RuntimeError("Role management requires admin mode. Set GLEITZEIT_AUTH_MODE=admin")
            
            # Return default roles
            from .auth.models import DEFAULT_ROLES
            return DEFAULT_ROLES
    
    async def get_audit_logs(self, user_id: str = None, action: str = None, 
                           resource_type: str = None, since: datetime = None,
                           skip: int = 0, limit: int = 100) -> Dict[str, Any]:
        """
        Get audit logs
        
        Args:
            user_id: Filter by user ID
            action: Filter by action
            resource_type: Filter by resource type
            since: Filter by date
            skip: Number of logs to skip
            limit: Maximum number of logs
            
        Returns:
            Audit logs with metadata
        """
        if self.get_mode() == "api":
            try:
                params = {"skip": skip, "limit": limit}
                if user_id:
                    params["user_id"] = user_id
                if action:
                    params["action"] = action
                if resource_type:
                    params["resource_type"] = resource_type
                if since:
                    params["since"] = since.isoformat()
                
                query_string = "&".join(f"{k}={v}" for k, v in params.items())
                response = await self._api_client.get(f"/auth/audit-logs?{query_string}")
                if response.status_code == 200:
                    return response.json()
                else:
                    raise RuntimeError("Failed to get audit logs")
            except Exception as e:
                raise RuntimeError(f"Failed to get audit logs: {e}")
        else:
            # In native mode, use auth database directly
            from .auth.database import get_auth_db
            from .auth.basic_auth import is_basic_mode
            
            if is_basic_mode():
                raise RuntimeError("Audit logs require admin mode. Set GLEITZEIT_AUTH_MODE=admin")
            
            auth_db = get_auth_db()
            
            # Get audit logs from database
            logs = await auth_db.get_audit_logs(
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                since=since,
                limit=limit,
                offset=skip
            )
            
            # Convert to response format
            audit_logs = []
            for log in logs:
                audit_logs.append({
                    "id": str(log.id),
                    "timestamp": log.created_at.isoformat(),
                    "user_id": str(log.user_id) if log.user_id else None,
                    "action": log.action,
                    "resource_type": log.resource_type,
                    "resource_id": log.resource_id,
                    "details": log.details,
                    "ip_address": log.ip_address,
                    "user_agent": log.user_agent
                })
            
            return {
                "audit_logs": audit_logs,
                "total": len(audit_logs),
                "offset": skip,
                "limit": limit
            }

    # =========================================================================
    # Workflow Management Methods
    # =========================================================================
    
    async def submit_workflow(self, workflow: 'Workflow') -> Dict[str, Any]:
        """
        Submit a workflow object for execution
        
        Args:
            workflow: Workflow object to submit
            
        Returns:
            Submission result with workflow ID and status
        """
        if self.get_mode() == "api":
            try:
                # Convert workflow object to API format
                workflow_data = {
                    "name": workflow.name,
                    "description": workflow.description,
                    "tasks": [
                        {
                            "name": task.name,
                            "id": task.id,
                            "protocol": task.protocol,
                            "method": task.method,
                            "params": task.params,
                            "depends_on": task.depends_on,
                            "priority": task.priority.value if hasattr(task.priority, 'value') else task.priority,
                            "timeout": task.timeout,
                            "retry_count": task.retry_count,
                            "metadata": task.metadata
                        }
                        for task in workflow.tasks
                    ],
                    "metadata": workflow.metadata
                }
                
                response = await self._api_client.post("/workflows", json=workflow_data)
                if response.status_code in [200, 201]:
                    result = response.json()
                    return {
                        "workflow_id": result.get("workflow_id"),
                        "status": result.get("status", "submitted"),
                        "message": "Workflow submitted successfully"
                    }
                else:
                    error = response.json() if response.status_code != 500 else {"detail": "Workflow submission failed"}
                    raise RuntimeError(f"Workflow submission failed: {error.get('detail', 'Unknown error')}")
            except Exception as e:
                raise RuntimeError(f"Workflow submission failed: {e}")
        else:
            # Native mode - submit directly to execution engine
            if hasattr(self, '_execution_engine') and self._execution_engine:
                try:
                    # Submit workflow to execution engine which handles persistence
                    await self._execution_engine.submit_workflow(workflow)
                    
                    return {
                        "workflow_id": workflow.id,
                        "status": "submitted",
                        "message": "Workflow submitted successfully"
                    }
                except Exception as e:
                    raise RuntimeError(f"Failed to submit workflow: {e}")
            else:
                raise RuntimeError("Execution engine not available in native mode")
    
    async def create_task(self, task: 'Task') -> Dict[str, Any]:
        """
        Create and submit a single task
        
        Args:
            task: Task object to create
            
        Returns:
            Task creation result
        """
        if self.get_mode() == "api":
            try:
                # Convert task object to API format
                task_data = {
                    "name": task.name,
                    "protocol": task.protocol,
                    "method": task.method,
                    "params": task.params,
                    "depends_on": task.depends_on,
                    "priority": task.priority.value if hasattr(task.priority, 'value') else task.priority,
                    "timeout": task.timeout,
                    "retry_count": task.retry_count,
                    "metadata": task.metadata
                }
                
                response = await self._api_client.post("/tasks", json=task_data)
                if response.status_code in [200, 201]:
                    result = response.json()
                    return {
                        "task_id": result.get("task_id"),
                        "status": result.get("status", "submitted"),
                        "message": "Task created successfully"
                    }
                else:
                    error = response.json() if response.status_code != 500 else {"detail": "Task creation failed"}
                    raise RuntimeError(f"Task creation failed: {error.get('detail', 'Unknown error')}")
            except Exception as e:
                raise RuntimeError(f"Task creation failed: {e}")
        else:
            # Native mode - submit directly to execution engine
            if hasattr(self, '_execution_engine') and self._execution_engine:
                try:
                    # Submit task to execution engine
                    await self._execution_engine.submit_task(task)
                    
                    return {
                        "task_id": task.id,
                        "status": "submitted", 
                        "message": "Task created successfully"
                    }
                except Exception as e:
                    raise RuntimeError(f"Failed to create task: {e}")
            else:
                raise RuntimeError("Execution engine not available in native mode")
    
    async def pause_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """
        Pause a running workflow
        
        Args:
            workflow_id: ID of workflow to pause
            
        Returns:
            Pause result
        """
        if self.get_mode() == "api":
            try:
                response = await self._api_client.post(f"/workflows/{workflow_id}/pause")
                if response.status_code == 200:
                    return response.json()
                else:
                    error = response.json() if response.status_code != 500 else {"detail": "Workflow pause failed"}
                    raise RuntimeError(f"Workflow pause failed: {error.get('detail', 'Unknown error')}")
            except Exception as e:
                raise RuntimeError(f"Failed to pause workflow: {e}")
        else:
            # Native mode - pause via persistence and execution engine
            if hasattr(self, '_persistence_adapter') and self._persistence_adapter:
                try:
                    workflow = await self._persistence_adapter.get_workflow(workflow_id)
                    if not workflow:
                        raise RuntimeError(f"Workflow {workflow_id} not found")
                    
                    if workflow.status != "running":
                        raise RuntimeError(f"Workflow {workflow_id} is not running (current: {workflow.status})")
                    
                    # Update workflow status
                    workflow.status = "paused"
                    await self._persistence_adapter.save_workflow(workflow)
                    
                    # Cancel pending tasks if execution engine available
                    if hasattr(self, '_execution_engine') and self._execution_engine:
                        tasks = await self._persistence_adapter.get_workflow_tasks(workflow_id)
                        cancelled_count = 0
                        for task in tasks:
                            if task.status in ["pending", "queued"]:
                                if await self._execution_engine.cancel_task(task.id):
                                    cancelled_count += 1
                    
                    return {
                        "message": f"Workflow {workflow_id} paused successfully",
                        "workflow_id": workflow_id,
                        "status": "paused"
                    }
                except Exception as e:
                    raise RuntimeError(f"Failed to pause workflow: {e}")
            else:
                raise RuntimeError("Persistence adapter not available in native mode")
    
    async def resume_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """
        Resume a paused workflow
        
        Args:
            workflow_id: ID of workflow to resume
            
        Returns:
            Resume result
        """
        if self.get_mode() == "api":
            try:
                response = await self._api_client.post(f"/workflows/{workflow_id}/resume")
                if response.status_code == 200:
                    return response.json()
                else:
                    error = response.json() if response.status_code != 500 else {"detail": "Workflow resume failed"}
                    raise RuntimeError(f"Workflow resume failed: {error.get('detail', 'Unknown error')}")
            except Exception as e:
                raise RuntimeError(f"Failed to resume workflow: {e}")
        else:
            # Native mode - resume via persistence and execution engine
            if hasattr(self, '_persistence_adapter') and self._persistence_adapter:
                try:
                    workflow = await self._persistence_adapter.get_workflow(workflow_id)
                    if not workflow:
                        raise RuntimeError(f"Workflow {workflow_id} not found")
                    
                    if workflow.status != "paused":
                        raise RuntimeError(f"Workflow {workflow_id} is not paused (current: {workflow.status})")
                    
                    # Update workflow status
                    workflow.status = "running"
                    await self._persistence_adapter.save_workflow(workflow)
                    
                    # Resubmit cancelled tasks if execution engine available
                    if hasattr(self, '_execution_engine') and self._execution_engine:
                        tasks = await self._persistence_adapter.get_workflow_tasks(workflow_id)
                        resubmitted_count = 0
                        for task in tasks:
                            if task.status == "cancelled":
                                task.status = "pending"
                                await self._persistence_adapter.save_task(task)
                                await self._execution_engine.submit_task(task)
                                resubmitted_count += 1
                    
                    return {
                        "message": f"Workflow {workflow_id} resumed successfully", 
                        "workflow_id": workflow_id,
                        "status": "running"
                    }
                except Exception as e:
                    raise RuntimeError(f"Failed to resume workflow: {e}")
            else:
                raise RuntimeError("Persistence adapter not available in native mode")
    
    async def cancel_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """
        Cancel a workflow
        
        Args:
            workflow_id: ID of workflow to cancel
            
        Returns:
            Cancel result
        """
        if self.get_mode() == "api":
            try:
                response = await self._api_client.delete(f"/workflows/{workflow_id}")
                if response.status_code == 200:
                    return response.json()
                else:
                    error = response.json() if response.status_code != 500 else {"detail": "Workflow cancellation failed"}
                    raise RuntimeError(f"Workflow cancellation failed: {error.get('detail', 'Unknown error')}")
            except Exception as e:
                raise RuntimeError(f"Failed to cancel workflow: {e}")
        else:
            # Native mode - cancel via persistence and execution engine
            if hasattr(self, '_persistence_adapter') and self._persistence_adapter:
                try:
                    workflow = await self._persistence_adapter.get_workflow(workflow_id)
                    if not workflow:
                        raise RuntimeError(f"Workflow {workflow_id} not found")
                    
                    # Cancel all tasks
                    tasks = await self._persistence_adapter.get_workflow_tasks(workflow_id)
                    cancelled_count = 0
                    for task in tasks:
                        if task.status in ["pending", "queued", "running"]:
                            if await self.cancel_task(task.id):
                                cancelled_count += 1
                    
                    # Update workflow status
                    workflow.status = "cancelled"
                    await self._persistence_adapter.save_workflow(workflow)
                    
                    return {
                        "message": f"Workflow {workflow_id} cancelled successfully",
                        "workflow_id": workflow_id,
                        "cancelled_tasks": cancelled_count,
                        "status": "cancelled"
                    }
                except Exception as e:
                    raise RuntimeError(f"Failed to cancel workflow: {e}")
            else:
                raise RuntimeError("Persistence adapter not available in native mode")

    # =========================================================================
    # Utility Methods
    # =========================================================================
    
    # =========================================================================
    # Queue Management Methods
    # =========================================================================
    
    async def get_queues(self) -> Dict[str, Any]:
        """Get all task queues with their status"""
        if self.get_mode() == "api":
            try:
                response = await self._api_client.get("/queues")
                return response.json()
            except Exception as e:
                return {"error": f"API error: {str(e)}", "queues": []}
        else:
            # Native mode - get queues from execution engine
            if hasattr(self, '_execution_engine') and self._execution_engine:
                try:
                    queue_manager = getattr(self._execution_engine, 'queue_manager', None)
                    if queue_manager:
                        queues = []
                        for queue_name in queue_manager.get_queue_names():
                            queue_info = queue_manager.get_queue_info(queue_name)
                            queues.append({
                                "name": queue_name,
                                "status": queue_info.get("status", "unknown"),
                                "size": queue_info.get("size", 0),
                                "processing": queue_info.get("processing", 0),
                                "workers": queue_info.get("workers", 0)
                            })
                        return {"queues": queues}
                    else:
                        return {"queues": []}
                except Exception as e:
                    return {"error": f"Queue access error: {str(e)}", "queues": []}
            else:
                return {"queues": []}
    
    async def get_queue_details(self, queue_name: str) -> Dict[str, Any]:
        """Get detailed information about a specific queue"""
        if self.get_mode() == "api":
            try:
                response = await self._api_client.get(f"/queues/{queue_name}")
                return response.json()
            except Exception as e:
                return {"error": f"API error: {str(e)}"}
        else:
            # Native mode - get queue details from execution engine
            if hasattr(self, '_execution_engine') and self._execution_engine:
                try:
                    queue_manager = getattr(self._execution_engine, 'queue_manager', None)
                    if queue_manager:
                        queue_info = queue_manager.get_queue_info(queue_name)
                        stats = queue_manager.get_queue_statistics(queue_name)
                        return {
                            "name": queue_name,
                            "status": queue_info.get("status", "unknown"),
                            "size": queue_info.get("size", 0),
                            "processing": queue_info.get("processing", 0),
                            "workers": queue_info.get("workers", 0),
                            "max_workers": queue_info.get("max_workers", 5),
                            "stats": {
                                "processed": stats.get("processed", 0),
                                "failed": stats.get("failed", 0),
                                "avg_time": stats.get("avg_time", 0)
                            }
                        }
                    else:
                        return {"error": "Queue manager not available"}
                except Exception as e:
                    return {"error": f"Queue access error: {str(e)}"}
            else:
                return {"error": "Execution engine not available"}
    
    async def pause_queue(self, queue_name: str) -> Dict[str, Any]:
        """Pause processing of a queue"""
        if self.get_mode() == "api":
            try:
                response = await self._api_client.post(f"/queues/{queue_name}/pause")
                return response.json()
            except Exception as e:
                return {"error": f"API error: {str(e)}"}
        else:
            # Native mode - pause queue via execution engine
            if hasattr(self, '_execution_engine') and self._execution_engine:
                try:
                    queue_manager = getattr(self._execution_engine, 'queue_manager', None)
                    if queue_manager:
                        result = queue_manager.pause_queue(queue_name)
                        return {"message": f"Queue {queue_name} paused", "success": result}
                    else:
                        return {"error": "Queue manager not available"}
                except Exception as e:
                    return {"error": f"Queue pause error: {str(e)}"}
            else:
                return {"error": "Execution engine not available"}
    
    async def resume_queue(self, queue_name: str) -> Dict[str, Any]:
        """Resume processing of a paused queue"""
        if self.get_mode() == "api":
            try:
                response = await self._api_client.post(f"/queues/{queue_name}/resume")
                return response.json()
            except Exception as e:
                return {"error": f"API error: {str(e)}"}
        else:
            # Native mode - resume queue via execution engine
            if hasattr(self, '_execution_engine') and self._execution_engine:
                try:
                    queue_manager = getattr(self._execution_engine, 'queue_manager', None)
                    if queue_manager:
                        result = queue_manager.resume_queue(queue_name)
                        return {"message": f"Queue {queue_name} resumed", "success": result}
                    else:
                        return {"error": "Queue manager not available"}
                except Exception as e:
                    return {"error": f"Queue resume error: {str(e)}"}
            else:
                return {"error": "Execution engine not available"}
    
    async def clear_queue(self, queue_name: str) -> Dict[str, Any]:
        """Clear all tasks from a queue"""
        if self.get_mode() == "api":
            try:
                response = await self._api_client.post(f"/queues/{queue_name}/clear")
                return response.json()
            except Exception as e:
                return {"error": f"API error: {str(e)}"}
        else:
            # Native mode - clear queue via execution engine
            if hasattr(self, '_execution_engine') and self._execution_engine:
                try:
                    queue_manager = getattr(self._execution_engine, 'queue_manager', None)
                    if queue_manager:
                        cleared_count = queue_manager.clear_queue(queue_name)
                        return {"message": f"Cleared {cleared_count} tasks from queue {queue_name}", "cleared": cleared_count}
                    else:
                        return {"error": "Queue manager not available"}
                except Exception as e:
                    return {"error": f"Queue clear error: {str(e)}"}
            else:
                return {"error": "Execution engine not available"}
    
    async def configure_queue(self, queue_name: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """Configure queue settings"""
        if self.get_mode() == "api":
            try:
                response = await self._api_client.put(f"/queues/{queue_name}/config", json=config)
                return response.json()
            except Exception as e:
                return {"error": f"API error: {str(e)}"}
        else:
            # Native mode - configure queue via execution engine
            if hasattr(self, '_execution_engine') and self._execution_engine:
                try:
                    queue_manager = getattr(self._execution_engine, 'queue_manager', None)
                    if queue_manager:
                        result = queue_manager.configure_queue(queue_name, config)
                        return {"message": f"Queue {queue_name} configured", "success": result}
                    else:
                        return {"error": "Queue manager not available"}
                except Exception as e:
                    return {"error": f"Queue config error: {str(e)}"}
            else:
                return {"error": "Execution engine not available"}

    # =========================================================================
    # Log Management Methods
    # =========================================================================
    
    async def query_logs(self, level: str = None, source: str = None, task_id: str = None, 
                        workflow_id: str = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """Query system logs with filters"""
        if self.get_mode() == "api":
            try:
                params = {"limit": limit, "offset": offset}
                if level:
                    params["level"] = level
                if source:
                    params["source"] = source
                if task_id:
                    params["task_id"] = task_id
                if workflow_id:
                    params["workflow_id"] = workflow_id
                    
                response = await self._api_client.get("/logs/query", params=params)
                return response.json()
            except Exception as e:
                return {"error": f"API error: {str(e)}", "logs": [], "total": 0}
        else:
            # Native mode - query logs from persistence layer
            if hasattr(self, '_persistence_adapter') and self._persistence_adapter:
                try:
                    log_manager = getattr(self._persistence_adapter, 'log_manager', None)
                    if log_manager:
                        filters = {}
                        if level:
                            filters["level"] = level
                        if source:
                            filters["source"] = source
                        if task_id:
                            filters["task_id"] = task_id
                        if workflow_id:
                            filters["workflow_id"] = workflow_id
                            
                        logs = log_manager.query_logs(filters, limit=limit, offset=offset)
                        total = log_manager.count_logs(filters)
                        
                        return {
                            "logs": [
                                {
                                    "timestamp": log.timestamp.isoformat(),
                                    "level": log.level,
                                    "source": log.source,
                                    "message": log.message,
                                    "task_id": log.task_id,
                                    "workflow_id": log.workflow_id
                                }
                                for log in logs
                            ],
                            "total": total
                        }
                    else:
                        return {"logs": [], "total": 0}
                except Exception as e:
                    return {"error": f"Log query error: {str(e)}", "logs": [], "total": 0}
            else:
                return {"logs": [], "total": 0}
    
    async def search_logs(self, query: str, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """Search logs by message content"""
        if self.get_mode() == "api":
            try:
                params = {"query": query, "limit": limit, "offset": offset}
                response = await self._api_client.get("/logs/search", params=params)
                return response.json()
            except Exception as e:
                return {"error": f"API error: {str(e)}", "logs": [], "total": 0}
        else:
            # Native mode - search logs from persistence layer
            if hasattr(self, '_persistence_adapter') and self._persistence_adapter:
                try:
                    log_manager = getattr(self._persistence_adapter, 'log_manager', None)
                    if log_manager:
                        logs = log_manager.search_logs(query, limit=limit, offset=offset)
                        total = log_manager.count_search_results(query)
                        
                        return {
                            "logs": [
                                {
                                    "timestamp": log.timestamp.isoformat(),
                                    "level": log.level,
                                    "source": log.source,
                                    "message": log.message,
                                    "task_id": log.task_id,
                                    "workflow_id": log.workflow_id
                                }
                                for log in logs
                            ],
                            "total": total
                        }
                    else:
                        return {"logs": [], "total": 0}
                except Exception as e:
                    return {"error": f"Log search error: {str(e)}", "logs": [], "total": 0}
            else:
                return {"logs": [], "total": 0}
    
    async def get_log_stats(self) -> Dict[str, Any]:
        """Get log statistics"""
        if self.get_mode() == "api":
            try:
                response = await self._api_client.get("/logs/stats")
                return response.json()
            except Exception as e:
                return {"error": f"API error: {str(e)}", "total_logs": 0}
        else:
            # Native mode - get stats from persistence layer
            if hasattr(self, '_persistence_adapter') and self._persistence_adapter:
                try:
                    log_manager = getattr(self._persistence_adapter, 'log_manager', None)
                    if log_manager:
                        stats = log_manager.get_statistics()
                        return {
                            "total_logs": stats.get("total", 0),
                            "by_level": stats.get("by_level", {}),
                            "storage_backend": stats.get("storage_backend", "unknown")
                        }
                    else:
                        return {"total_logs": 0, "by_level": {}, "storage_backend": "none"}
                except Exception as e:
                    return {"error": f"Log stats error: {str(e)}", "total_logs": 0}
            else:
                return {"total_logs": 0, "by_level": {}, "storage_backend": "none"}
    
    async def cleanup_logs(self, days: int = 30) -> Dict[str, Any]:
        """Cleanup old logs"""
        if self.get_mode() == "api":
            try:
                response = await self._api_client.delete(f"/logs/cleanup?days={days}")
                return response.json()
            except Exception as e:
                return {"error": f"API error: {str(e)}"}
        else:
            # Native mode - cleanup logs from persistence layer
            if hasattr(self, '_persistence_adapter') and self._persistence_adapter:
                try:
                    log_manager = getattr(self._persistence_adapter, 'log_manager', None)
                    if log_manager:
                        deleted_count = log_manager.cleanup_old_logs(days)
                        return {"message": f"Deleted {deleted_count} log entries older than {days} days", "deleted": deleted_count}
                    else:
                        return {"error": "Log manager not available"}
                except Exception as e:
                    return {"error": f"Log cleanup error: {str(e)}"}
            else:
                return {"error": "Persistence adapter not available"}

    # =========================================================================
    # Error Management Methods
    # =========================================================================
    
    async def get_event_errors(self, level: str = None, source: str = None, task_id: str = None,
                              limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """Get event errors with filters"""
        if self.get_mode() == "api":
            try:
                params = {"limit": limit, "offset": offset}
                if level:
                    params["level"] = level
                if source:
                    params["source"] = source
                if task_id:
                    params["task_id"] = task_id
                    
                response = await self._api_client.get("/event-errors", params=params)
                return response.json()
            except Exception as e:
                return {"error": f"API error: {str(e)}", "errors": [], "total": 0}
        else:
            # Native mode - get errors from persistence layer
            if hasattr(self, '_persistence_adapter') and self._persistence_adapter:
                try:
                    error_manager = getattr(self._persistence_adapter, 'error_manager', None)
                    if error_manager:
                        filters = {}
                        if level:
                            filters["level"] = level
                        if source:
                            filters["source"] = source
                        if task_id:
                            filters["task_id"] = task_id
                            
                        errors = error_manager.query_errors(filters, limit=limit, offset=offset)
                        total = error_manager.count_errors(filters)
                        
                        return {
                            "errors": [
                                {
                                    "id": error.id,
                                    "timestamp": error.timestamp.isoformat(),
                                    "level": error.level,
                                    "source": error.source,
                                    "message": error.message,
                                    "task_id": error.task_id,
                                    "workflow_id": error.workflow_id,
                                    "exception": error.exception,
                                    "stack_trace": error.stack_trace
                                }
                                for error in errors
                            ],
                            "total": total
                        }
                    else:
                        return {"errors": [], "total": 0}
                except Exception as e:
                    return {"error": f"Error query error: {str(e)}", "errors": [], "total": 0}
            else:
                return {"errors": [], "total": 0}
    
    async def get_event_error_stats(self) -> Dict[str, Any]:
        """Get error statistics"""
        if self.get_mode() == "api":
            try:
                response = await self._api_client.get("/event-errors/stats")
                return response.json()
            except Exception as e:
                return {"error": f"API error: {str(e)}", "total_errors": 0}
        else:
            # Native mode - get error stats from persistence layer
            if hasattr(self, '_persistence_adapter') and self._persistence_adapter:
                try:
                    error_manager = getattr(self._persistence_adapter, 'error_manager', None)
                    if error_manager:
                        stats = error_manager.get_statistics()
                        return {
                            "total_errors": stats.get("total", 0),
                            "by_level": stats.get("by_level", {}),
                            "recent_trends": stats.get("recent_trends", [])
                        }
                    else:
                        return {"total_errors": 0, "by_level": {}, "recent_trends": []}
                except Exception as e:
                    return {"error": f"Error stats error: {str(e)}", "total_errors": 0}
            else:
                return {"total_errors": 0, "by_level": {}, "recent_trends": []}
    
    async def get_event_error_details(self, error_id: str) -> Dict[str, Any]:
        """Get detailed information about a specific error"""
        if self.get_mode() == "api":
            try:
                response = await self._api_client.get(f"/event-errors/{error_id}")
                return response.json()
            except Exception as e:
                return {"error": f"API error: {str(e)}"}
        else:
            # Native mode - get error details from persistence layer
            if hasattr(self, '_persistence_adapter') and self._persistence_adapter:
                try:
                    error_manager = getattr(self._persistence_adapter, 'error_manager', None)
                    if error_manager:
                        error = error_manager.get_error_by_id(error_id)
                        if error:
                            return {
                                "id": error.id,
                                "timestamp": error.timestamp.isoformat(),
                                "level": error.level,
                                "source": error.source,
                                "message": error.message,
                                "task_id": error.task_id,
                                "workflow_id": error.workflow_id,
                                "exception": error.exception,
                                "stack_trace": error.stack_trace,
                                "context": error.context or {}
                            }
                        else:
                            return {"error": "Error not found"}
                    else:
                        return {"error": "Error manager not available"}
                except Exception as e:
                    return {"error": f"Error details error: {str(e)}"}
            else:
                return {"error": "Persistence adapter not available"}
    
    async def cleanup_event_errors(self, days: int = 30) -> Dict[str, Any]:
        """Cleanup old error records"""
        if self.get_mode() == "api":
            try:
                response = await self._api_client.delete(f"/event-errors/cleanup?days={days}")
                return response.json()
            except Exception as e:
                return {"error": f"API error: {str(e)}"}
        else:
            # Native mode - cleanup errors from persistence layer
            if hasattr(self, '_persistence_adapter') and self._persistence_adapter:
                try:
                    error_manager = getattr(self._persistence_adapter, 'error_manager', None)
                    if error_manager:
                        deleted_count = error_manager.cleanup_old_errors(days)
                        return {"message": f"Deleted {deleted_count} error records older than {days} days", "deleted": deleted_count}
                    else:
                        return {"error": "Error manager not available"}
                except Exception as e:
                    return {"error": f"Error cleanup error: {str(e)}"}
            else:
                return {"error": "Persistence adapter not available"}

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