"""
Native adapter for Gleitzeit client.
"""

import asyncio
from typing import Any, Dict, List, Optional
from gleitzeit.core.models import Task, Workflow, TaskResult
from gleitzeit.core.execution_engine import ExecutionEngine
from gleitzeit.task_queue.task_queue import QueueManager
from gleitzeit.task_queue.dependency_resolver import DependencyResolver
from gleitzeit.persistence.factory import create_persistence
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.events.base import EventBus
from gleitzeit.events.store import EventStore
from .base import BaseAdapter


class NativeAdapter(BaseAdapter):
    """Adapter for native mode operations."""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.execution_engine = None
        self.persistence = None
        self.registry = None
        self.event_bus = None
        self.event_store = None
        self.queue_manager = None
        self.dependency_resolver = None
        self._engine_task = None  # Track engine background task
    
    async def initialize(self) -> None:
        """Initialize native components."""
        import logging
        logger = logging.getLogger(__name__)
        
        # Create persistence backend
        persistence_type = self.config.get('persistence_type', 'memory')
        # Only pass persistence-specific config to the factory
        persistence_config = {}
        # Known persistence parameters
        if 'redis_url' in self.config:
            persistence_config['redis_url'] = self.config['redis_url']
        if 'sql_connection' in self.config:
            persistence_config['sql_connection'] = self.config['sql_connection']
        if 'sql_db_path' in self.config:
            persistence_config['sql_db_path'] = self.config['sql_db_path']
        
        self.persistence = await create_persistence(persistence_type, **persistence_config)
        
        # Create event bus with optional event persistence
        persist_events = self.config.get('persist_events', False)
        logger.info(f"NativeAdapter: persist_events={persist_events}, config keys={list(self.config.keys())}")
        self.event_bus = EventBus(isolate_errors=True, track_errors=True)
        
        if persist_events:
            # Create event store for persistence
            self.event_store = EventStore(persistence=self.persistence)
            # Connect event store to event bus
            self.event_bus.event_store = self.event_store
        
        # Create provider registry
        self.registry = ProtocolProviderRegistry()
        
        # Initialize hub-based auto-discovery system
        await self._initialize_auto_discovery()
        
        # Create queue manager and dependency resolver
        self.queue_manager = QueueManager(persistence=self.persistence, event_bus=self.event_bus)
        self.dependency_resolver = DependencyResolver()
        
        # Create execution engine with all dependencies
        self.execution_engine = ExecutionEngine(
            registry=self.registry,
            queue_manager=self.queue_manager,
            dependency_resolver=self.dependency_resolver,
            persistence=self.persistence,
            event_bus=self.event_bus,
            max_concurrent_tasks=self.config.get('max_concurrent_tasks', 10)
        )
        # Don't start the execution engine here - it blocks!
        # The engine should be started in a background task if needed
    
    async def _initialize_auto_discovery(self) -> None:
        """Initialize hub-based auto-discovery system."""
        import logging
        logger = logging.getLogger(__name__)
        
        # Import required components
        try:
            from gleitzeit.hub.resource_manager import ResourceManager
            from gleitzeit.hub.ollama_hub import OllamaHub
            from gleitzeit.hub.mcp_hub import MCPHub
            from gleitzeit.protocols import PYTHON_PROTOCOL_V1, LLM_PROTOCOL_V1, MCP_PROTOCOL_V1
            from gleitzeit.providers.python_provider import PythonProvider
            from gleitzeit.providers.ollama_provider import OllamaProvider
            from gleitzeit.providers.mcp_hub_provider import MCPHubProvider
            
            # Initialize resource manager for hub coordination
            self.resource_manager = ResourceManager("native-resource-manager")
            
            # Always register Python protocol and provider (doesn't require discovery)
            try:
                self.registry.register_protocol(PYTHON_PROTOCOL_V1)
                python_provider = PythonProvider(
                    "native-python-provider",
                    allow_local=True
                )
                await python_provider.initialize()
                self.registry.register_provider("native-python-provider", "python/v1", python_provider)
                logger.info("✓ Python provider registered in NativeAdapter")
            except Exception as e:
                logger.warning(f"⚠️  Failed to register Python provider: {e}")
            
            # Auto-discover Ollama instances via OllamaHub
            try:
                ollama_hub = OllamaHub(
                    hub_id="native-ollama-hub",
                    auto_discover=True,  # Enable auto-discovery
                    persistence=self.persistence
                )
                await ollama_hub.initialize()
                await self.resource_manager.add_hub("ollama", ollama_hub)
                
                # Register LLM protocol and Ollama provider with hub
                self.registry.register_protocol(LLM_PROTOCOL_V1)
                ollama_provider = OllamaProvider(
                    "native-ollama-provider",
                    auto_discover=False,  # Hub handles discovery
                    resource_manager=self.resource_manager,
                    hub=ollama_hub
                )
                await ollama_provider.initialize()
                self.registry.register_provider("native-ollama-provider", "llm/v1", ollama_provider)
                logger.info("✓ Ollama provider with auto-discovery registered in NativeAdapter")
                
            except Exception as e:
                logger.debug(f"Ollama auto-discovery not available: {e}")
            
            # Auto-discover MCP servers if configured
            try:
                # Check for MCP configuration
                mcp_config = self.config.get('mcp', {})
                if mcp_config.get('enabled', False) or mcp_config.get('auto_discover', False):
                    mcp_hub = MCPHub(
                        hub_id="native-mcp-hub",
                        auto_discover=mcp_config.get('auto_discover', True),
                        config_data=mcp_config
                    )
                    await mcp_hub.initialize()
                    await self.resource_manager.add_hub("mcp", mcp_hub)
                    
                    # Register MCP protocol and provider
                    self.registry.register_protocol(MCP_PROTOCOL_V1)
                    mcp_provider = MCPHubProvider(
                        provider_id="native-mcp-provider",
                        hub=mcp_hub,
                        config_data=mcp_config
                    )
                    await mcp_provider.initialize()
                    self.registry.register_provider("native-mcp-provider", "mcp/v1", mcp_provider)
                    logger.info("✓ MCP provider with auto-discovery registered in NativeAdapter")
                
            except Exception as e:
                logger.debug(f"MCP auto-discovery not available: {e}")
            
            logger.info("Auto-discovery system initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize auto-discovery system: {e}")
            # Fallback to basic Python provider only
            try:
                from gleitzeit.protocols import PYTHON_PROTOCOL_V1
                from gleitzeit.providers.python_provider import PythonProvider
                
                self.registry.register_protocol(PYTHON_PROTOCOL_V1)
                python_provider = PythonProvider("native-python-provider", allow_local=True)
                await python_provider.initialize()
                self.registry.register_provider("native-python-provider", "python/v1", python_provider)
                logger.info("✓ Fallback Python provider registered")
            except Exception as fallback_error:
                logger.error(f"Even fallback provider registration failed: {fallback_error}")
    
    async def start_engine(self, mode='EVENT_DRIVEN'):
        """Start execution engine in background."""
        if not self.execution_engine:
            raise RuntimeError("Execution engine not initialized")
        
        if self._engine_task and not self._engine_task.done():
            return  # Already running
        
        # Import ExecutionMode here to avoid circular imports
        from gleitzeit.core.execution_engine import ExecutionMode
        exec_mode = ExecutionMode[mode] if isinstance(mode, str) else mode
        
        # Start engine in background task
        self._engine_task = asyncio.create_task(
            self.execution_engine.start(exec_mode)
        )
        
        # Wait a moment for engine to initialize
        await asyncio.sleep(0.1)
        
        return self._engine_task
    
    async def stop_engine(self) -> None:
        """Stop execution engine."""
        if self.execution_engine:
            self.execution_engine.running = False
            
        if self._engine_task and not self._engine_task.done():
            self._engine_task.cancel()
            try:
                await self._engine_task
            except asyncio.CancelledError:
                pass
    
    async def shutdown(self) -> None:
        """Shutdown native components."""
        # Stop engine first
        await self.stop_engine()
        
        if self.execution_engine:
            await self.execution_engine.stop()
        
        # Shutdown resource manager and hubs
        if hasattr(self, 'resource_manager') and self.resource_manager:
            await self.resource_manager.stop()
        
        if self.persistence:
            await self.persistence.shutdown()
    
    # Workflow operations
    async def submit_workflow(self, workflow: Workflow) -> Dict[str, Any]:
        """Submit workflow natively."""
        if not self.execution_engine:
            raise RuntimeError("Execution engine not initialized")
        
        # Don't auto-start engine - let client control lifecycle
        result = await self.execution_engine.submit_workflow(workflow)
        return {"workflow_id": workflow.id, "status": "submitted"}
    
    async def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Get workflow natively."""
        if not self.persistence:
            raise RuntimeError("Persistence not initialized")
        return await self.persistence.get_workflow(workflow_id)
    
    async def list_workflows(self, status: Optional[str] = None,
                           limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """List workflows natively."""
        if not self.persistence:
            raise RuntimeError("Persistence not initialized")
        
        workflows = await self.persistence.list_workflows(
            status=status, limit=limit, offset=offset
        )
        return {"workflows": workflows, "total": len(workflows)}
    
    async def cancel_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Cancel workflow natively."""
        if not self.execution_engine:
            raise RuntimeError("Execution engine not initialized")
        
        success = await self.execution_engine.cancel_workflow(workflow_id)
        return {"success": success, "workflow_id": workflow_id}
    
    async def pause_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Pause workflow natively."""
        # Would need execution engine support
        return {"error": "Pause not yet implemented in native mode"}
    
    async def resume_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Resume workflow natively."""
        # Would need execution engine support
        return {"error": "Resume not yet implemented in native mode"}
    
    async def delete_workflow(self, workflow_id: str) -> bool:
        """Delete workflow natively."""
        if not self.persistence:
            raise RuntimeError("Persistence not initialized")
        return await self.persistence.delete_workflow(workflow_id)
    
    async def get_workflow_tasks(self, workflow_id: str) -> List[Task]:
        """Get workflow tasks natively."""
        if not self.persistence:
            raise RuntimeError("Persistence not initialized")
        return await self.persistence.get_workflow_tasks(workflow_id)
    
    # Task operations
    async def submit_task(self, task: Task) -> Dict[str, Any]:
        """Submit task natively."""
        if not self.execution_engine:
            raise RuntimeError("Execution engine not initialized")
        
        result = await self.execution_engine.submit_task(task)
        return {"task_id": result.id, "status": "submitted"}
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get task natively."""
        if not self.persistence:
            raise RuntimeError("Persistence not initialized")
        return await self.persistence.get_task(task_id)
    
    async def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        """Get task result natively."""
        if not self.persistence:
            raise RuntimeError("Persistence not initialized")
        return await self.persistence.get_task_result(task_id)
    
    async def list_tasks(self, status: Optional[str] = None,
                        workflow_id: Optional[str] = None,
                        limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """List tasks natively."""
        if not self.persistence:
            raise RuntimeError("Persistence not initialized")
        
        tasks = await self.persistence.list_tasks(
            status=status, workflow_id=workflow_id,
            limit=limit, offset=offset
        )
        return {"tasks": tasks, "total": len(tasks)}
    
    async def cancel_task(self, task_id: str) -> bool:
        """Cancel task natively."""
        if not self.execution_engine:
            raise RuntimeError("Execution engine not initialized")
        return await self.execution_engine.cancel_task(task_id)
    
    async def delete_task(self, task_id: str) -> bool:
        """Delete task natively."""
        if not self.persistence:
            raise RuntimeError("Persistence not initialized")
        return await self.persistence.delete_task(task_id)
    
    async def wait_for_task(self, task_id: str, timeout: float = 300.0,
                           poll_interval: float = 1.0) -> Optional[TaskResult]:
        """Wait for task completion natively."""
        import time
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            task = await self.get_task(task_id)
            if task and task.status in ['completed', 'failed', 'cancelled']:
                return await self.get_task_result(task_id)
            
            await asyncio.sleep(poll_interval)
        
        return None
    
    # Queue operations
    async def get_queues(self) -> Dict[str, Any]:
        """Get queues natively."""
        if not self.execution_engine:
            raise RuntimeError("Execution engine not initialized")
        
        # Would need queue manager access
        return {"default": {"size": 0, "status": "active"}}
    
    async def get_queue_details(self, queue_name: str) -> Dict[str, Any]:
        """Get queue details natively."""
        return {"name": queue_name, "size": 0, "status": "active"}
    
    async def pause_queue(self, queue_name: str) -> Dict[str, Any]:
        """Pause queue natively."""
        return {"error": "Queue operations not yet implemented in native mode"}
    
    async def resume_queue(self, queue_name: str) -> Dict[str, Any]:
        """Resume queue natively."""
        return {"error": "Queue operations not yet implemented in native mode"}
    
    async def clear_queue(self, queue_name: str) -> Dict[str, Any]:
        """Clear queue natively."""
        return {"error": "Queue operations not yet implemented in native mode"}
    
    # Batch operations
    async def batch_process(self, directory: str, pattern: str = "*",
                           method: str = "llm/chat", prompt: str = None,
                           model: str = "llama3.2:latest",
                           max_concurrent: int = 5,
                           name: Optional[str] = None) -> Dict[str, Any]:
        """Batch process natively."""
        # Simple implementation - would be expanded
        from pathlib import Path
        import glob
        
        files = glob.glob(f"{directory}/{pattern}")
        results = {}
        
        for file_path in files[:max_concurrent]:
            task = Task(
                method=method,
                parameters={"file": file_path, "prompt": prompt, "model": model}
            )
            result = await self.submit_task(task)
            results[file_path] = result
        
        return results
    
    async def process_directory(self, directory: str, file_extensions: List[str],
                               workflow_yaml: str, max_concurrent: int = 5,
                               recursive: bool = True) -> Dict[str, Any]:
        """Process directory natively."""
        # Simplified implementation
        from pathlib import Path
        import yaml
        
        dir_path = Path(directory)
        results = {}
        
        for ext in file_extensions:
            if recursive:
                files = dir_path.rglob(f"*{ext}")
            else:
                files = dir_path.glob(f"*{ext}")
            
            for file_path in files:
                # Parse and substitute workflow
                workflow_dict = yaml.safe_load(workflow_yaml)
                workflow_dict['name'] = f"Process {file_path.name}"
                
                # Simple substitution
                workflow_yaml_substituted = workflow_yaml.replace("${file_path}", str(file_path))
                workflow_yaml_substituted = workflow_yaml_substituted.replace("${file_name}", file_path.name)
                
                workflow = Workflow(**yaml.safe_load(workflow_yaml_substituted))
                result = await self.submit_workflow(workflow)
                results[str(file_path)] = result
        
        return results
    
    # Chat operations  
    async def chat(self, message: str, model: str = "llama3.2:latest",
                  temperature: float = 0.7,
                  session_id: Optional[str] = None) -> Dict[str, Any]:
        """Chat natively."""
        task = Task(
            method="llm/chat",
            parameters={"message": message, "model": model, "temperature": temperature}
        )
        result = await self.submit_task(task)
        return result
    
    # System operations
    async def get_system_status(self) -> Dict[str, Any]:
        """Get system status natively."""
        return {
            "status": "running",
            "mode": "native",
            "persistence": self.persistence.__class__.__name__ if self.persistence else "none"
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Health check natively."""
        return {
            "status": "healthy",
            "components": {
                "execution_engine": self.execution_engine is not None,
                "persistence": self.persistence is not None,
                "registry": self.registry is not None
            }
        }
    
    async def get_providers(self) -> List[Dict[str, Any]]:
        """Get providers natively."""
        if not self.registry:
            return []
        
        providers = []
        for protocol in self.registry.list_protocols():
            provider = self.registry.get_provider(protocol)
            if provider:
                providers.append({
                    "protocol": protocol,
                    "provider": provider.__class__.__name__
                })
        
        return providers
    
    async def get_protocols(self) -> List[Dict[str, Any]]:
        """Get protocols natively."""
        if not self.registry:
            return []
        
        return [{"protocol": p} for p in self.registry.list_protocols()]
    
    # Event operations
    async def get_events(self, workflow_id: Optional[str] = None,
                        task_id: Optional[str] = None,
                        event_type: Optional[str] = None,
                        limit: int = 1000) -> List[Dict[str, Any]]:
        """Get persisted events."""
        if not self.event_store:
            return []
        
        return await self.event_store.get_events(
            workflow_id=workflow_id,
            task_id=task_id,
            event_type=event_type,
            limit=limit
        )