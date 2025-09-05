"""
Event-driven Gleitzeit client with real-time capabilities.

This is the main client implementation providing WebSocket-based
real-time event handling without any polling.
"""

import asyncio
import logging
from typing import Optional, Union, Any, Dict, List, Callable
from enum import Enum
from pathlib import Path

from gleitzeit.core.events import EventType, GleitzeitEvent
from gleitzeit.core.models import Task, Workflow, TaskResult

from .events import ClientEventBus, ClientEvent, ConnectionState
from .adapters.api import APIAdapter
from .mixins.event_workflow import EventWorkflowMixin
from .mixins.event_task import EventTaskMixin
from .mixins.task import TaskMixin
from .mixins.workflow import WorkflowMixin
from .mixins.system import SystemMixin
from .mixins.admin import AdminMixin
from .mixins.monitoring import MonitoringMixin
from .mixins.auth import AuthMixin
from .mixins.logs import LogMixin

logger = logging.getLogger(__name__)


class ClientMode(Enum):
    """Client operation mode."""
    API = "api"      # Use SystemManager via HTTP/WebSocket
    NATIVE = "native"  # Direct access to persistence (for API server)


class EventMode(Enum):
    """Event handling modes."""
    WEBSOCKET = "websocket"  # Use WebSocket for events
    DIRECT = "direct"  # Direct event bus connection (native only)


class GleitzeitClient(
    EventWorkflowMixin,
    EventTaskMixin,
    TaskMixin,
    WorkflowMixin,
    SystemMixin,
    AdminMixin,
    MonitoringMixin,
    AuthMixin,
    LogMixin
):
    """
    Event-driven Gleitzeit client with WebSocket and real-time capabilities.
    
    This client provides:
    - WebSocket connection for real-time events
    - Event bus for local event handling
    - Event-driven task and workflow tracking
    - Zero polling overhead
    - Direct event bus connection in native mode
    
    Usage:
        ```python
        # Create client
        client = GleitzeitClient()
        await client.initialize()
        
        # Register event handlers
        @client.on_event(EventType.TASK_COMPLETED)
        async def on_task_complete(event):
            logger.info(f"Task {event.data['task_id']} completed")
            
        # Submit task with event tracking
        result = await client.submit_task_with_tracking(
            task,
            on_complete=lambda t, r: logger.debug(f"Task done: {r}"),
            auto_wait=True
        )
        ```
    """
    
    # Class-level service token for NATIVE mode (set by API at startup)
    _SERVICE_TOKEN: Optional[str] = None
    
    @classmethod
    def set_service_token(cls, token: str) -> None:
        """Set the service token for NATIVE mode (API startup only).
        
        Args:
            token: Secure service token for authenticating NATIVE mode access
        """
        cls._SERVICE_TOKEN = token
        logger.info("Service token configured for NATIVE mode authentication")
    
    def _validate_service_token(self, token: str) -> bool:
        """Validate a service token for NATIVE mode access.
        
        Args:
            token: Token to validate
            
        Returns:
            True if token is valid, False otherwise
        """
        import hmac
        
        # Use constant-time comparison to prevent timing attacks
        if not self._SERVICE_TOKEN:
            return False
            
        return hmac.compare_digest(token, self._SERVICE_TOKEN)
    
    def __init__(self,
                 mode: Union[str, ClientMode] = ClientMode.API,
                 event_mode: Union[str, EventMode] = EventMode.WEBSOCKET,
                 api_host: str = "localhost",
                 api_port: int = 8000,
                 enable_events: bool = True,
                 event_bus: Optional[ClientEventBus] = None,
                 auto_start_server: bool = True,  # Auto-start SystemManager if needed
                 **kwargs):  # For compatibility
        """
        Initialize event-driven client.
        
        Args:
            mode: Client operation mode (API for external, NATIVE for internal)
            event_mode: Event handling mode (websocket, direct)
            api_host: API server hostname
            api_port: API server port
            enable_events: Enable event-driven features
            event_bus: Optional shared event bus instance
            auto_start_server: Auto-start SystemManager server if not running (API mode only)
            
        Note: Authentication tokens are managed by the backend persistence layer.
        Pass tokens to individual methods that need them, not stored in client.
        """
        # Parse mode
        if isinstance(mode, str):
            mode = ClientMode(mode)
            
        # SECURITY: NATIVE mode requires service token authentication
        if mode == ClientMode.NATIVE:
            service_token = kwargs.get('service_token')
            if not service_token:
                raise ValueError(
                    "NATIVE mode requires service_token parameter. "
                    "This mode is restricted to internal API use."
                )
            
            # Validate service token
            if not self._validate_service_token(service_token):
                logger.error("SECURITY: Invalid service token for NATIVE mode!")
                raise PermissionError(
                    "Invalid service token. NATIVE mode is restricted to internal API use."
                )
            
        # Configuration
        self.mode = mode
        self.event_mode = EventMode(event_mode) if isinstance(event_mode, str) else event_mode
        self.api_host = api_host
        self.api_port = api_port
        self.enable_events = enable_events and (mode == ClientMode.API)  # Events only for API mode
        self.auto_start_server = auto_start_server and (mode == ClientMode.API)
        
        # Core components
        self.event_bus = event_bus or (ClientEventBus() if self.enable_events else None)
        self._adapter = None  # Will be APIAdapter or NativeAdapter based on mode
        self._initialized = False
        
        # Event handler storage
        self._user_handlers: Dict[EventType, List[Callable]] = {}
            
        logger.info(f"GleitzeitClient configured with SystemManager at {api_host}:{api_port}")
        
            
    async def initialize(self) -> None:
        """Initialize the client and establish connections."""
        if self._initialized:
            return
            
        # Auto-start SystemManager server if needed (API mode only)
        if self.mode == ClientMode.API and self.auto_start_server:
            await self._ensure_system_manager_running()
            
        # Start event bus (API mode only)
        if self.event_bus and self.mode == ClientMode.API:
            await self.event_bus.start()
        
        # Create appropriate adapter based on mode
        if self.mode == ClientMode.NATIVE:
            # Native mode - direct access to persistence
            from .adapters.native import NativeAdapter
            self._adapter = NativeAdapter()
            logger.info("Using NativeAdapter for direct persistence access")
        else:
            # API mode - use SystemManager via HTTP
            self._adapter = APIAdapter(
                host=self.api_host,
                port=self.api_port,
                enable_events=self.enable_events,
                enable_websocket=(self.event_mode == EventMode.WEBSOCKET),
                event_bus=self.event_bus
        )
            
        # Initialize adapter
        await self._adapter.initialize()
        
        # Register default event handlers
        # Only register handlers if we have an event bus (API mode)
        if self.event_bus:
            self._register_default_handlers()
        
        # Emit ready event (API mode only)
        if self.event_bus:
            await self.event_bus.emit(ClientEvent(
                event_type=EventType.CLIENT_READY,
                data={'mode': self.mode.value, 'event_mode': self.event_mode.value}
            ))
        
        self._initialized = True
        logger.info("GleitzeitClient initialized with SystemManager support")
    
    async def _ensure_system_manager_running(self) -> None:
        """Ensure SystemManager server is running, start if needed."""
        import aiohttp
        import subprocess
        import asyncio
        
        # Check if server is already running
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://{self.api_host}:{self.api_port}/health",
                                     timeout=aiohttp.ClientTimeout(total=2)) as resp:
                    if resp.status == 200:
                        logger.info(f"SystemManager already running at {self.api_host}:{self.api_port}")
                        return
        except:
            pass
        
        # Start SystemManager server
        logger.info(f"Starting SystemManager server at {self.api_host}:{self.api_port}...")
        process = subprocess.Popen(
            ["python", "-m", "uvicorn", "gleitzeit.api.main:app",
             "--host", self.api_host, "--port", str(self.api_port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        # Wait for server to start
        for i in range(30):
            await asyncio.sleep(1)
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"http://{self.api_host}:{self.api_port}/health",
                                         timeout=aiohttp.ClientTimeout(total=2)) as resp:
                        if resp.status == 200:
                            logger.info("SystemManager server started successfully")
                            return
            except:
                continue
        
        raise RuntimeError(f"Failed to start SystemManager server at {self.api_host}:{self.api_port}")
        
    def _register_default_handlers(self) -> None:
        """Register default event handlers."""
        # Log important events
        @self.event_bus.on(EventType.ENGINE_STARTED)
        async def on_engine_start(event):
            logger.info("Execution engine started")
            
        @self.event_bus.on(EventType.ENGINE_STOPPED)
        async def on_engine_stop(event):
            logger.info("Execution engine stopped")
            
        # Connection events
        @self.event_bus.on(EventType.CLIENT_CONNECTION_LOST)
        async def on_connection_lost(event):
            logger.warning("WebSocket connection lost")
            
        @self.event_bus.on(EventType.CLIENT_RECONNECTION_SUCCESS)
        async def on_reconnection(event):
            logger.info("WebSocket reconnected successfully")
            
    async def shutdown(self) -> None:
        """Shutdown the client and clean up resources."""
        if not self._initialized:
            return
            
        # Emit shutdown event
        await self.event_bus.emit(ClientEvent(
            event_type=EventType.CLIENT_SHUTTING_DOWN,
            data={'mode': self.mode.value}
        ))
        
        # Shutdown adapter
        if self._adapter:
            await self._adapter.shutdown()
            self._adapter = None
            
        # Stop event bus
        await self.event_bus.stop()
        
        self._initialized = False
        logger.info("GleitzeitClient shutdown complete")
        
    def is_initialized(self) -> bool:
        """Check if client is initialized."""
        return self._initialized
        
    # Event handling methods
    
    def on_event(self, 
                 event_type: Union[EventType, str],
                 priority: Optional[int] = None,
                 filter: Optional[Callable] = None) -> Callable:
        """
        Decorator for registering event handlers.
        
        Usage:
            @client.on_event(EventType.TASK_COMPLETED)
            async def handle_task_complete(event):
                logger.debug(f"Task completed: {event.data}")
                
        Args:
            event_type: Event type to handle
            priority: Optional handler priority
            filter: Optional filter function
            
        Returns:
            Decorator function
        """
        def decorator(handler: Callable) -> Callable:
            # Store user handler
            if event_type not in self._user_handlers:
                self._user_handlers[event_type] = []
            self._user_handlers[event_type].append(handler)
            
            # Register with event bus
            from .events.client_event_bus import SubscriptionPriority
            priority_enum = SubscriptionPriority.NORMAL
            if priority is not None:
                if priority == 0:
                    priority_enum = SubscriptionPriority.CRITICAL
                elif priority == 1:
                    priority_enum = SubscriptionPriority.HIGH
                elif priority == 3:
                    priority_enum = SubscriptionPriority.LOW
                    
            self.event_bus.register(event_type, handler, priority_enum, filter)
            
            return handler
            
        return decorator
        
    def once(self, event_type: Union[EventType, str]) -> Callable:
        """
        Decorator for one-time event handlers.
        
        Usage:
            @client.once(EventType.ENGINE_STARTED)
            async def on_first_start(event):
                logger.info("Engine started for the first time")
                
        Args:
            event_type: Event type to handle once
            
        Returns:
            Decorator function
        """
        return self.event_bus.once(event_type)
        
    async def wait_for_event(self,
                           event_type: Union[EventType, str],
                           filter: Optional[Callable] = None,
                           timeout: Optional[float] = None) -> Optional[ClientEvent]:
        """
        Wait for a specific event to occur.
        
        Args:
            event_type: Event type to wait for
            filter: Optional filter function
            timeout: Optional timeout in seconds
            
        Returns:
            The event when it occurs, or None if timeout
        """
        return await self.event_bus.wait_for(event_type, filter, timeout)
    
    # Simplified startup methods for scripts and notebooks
    
    @classmethod
    def start_sync(cls, 
                   mode: Union[str, ClientMode] = ClientMode.API,
                   **kwargs) -> 'GleitzeitClient':
        """
        Create and start a client synchronously (for scripts/notebooks).
        
        This method handles async initialization in a sync context,
        making it easy to use from regular Python scripts or Jupyter notebooks.
        
        Usage:
            client = GleitzeitClient.start_sync()
            # Client is ready to use!
            result = client.run_workflow_sync("workflow.yaml")
            
        Args:
            mode: Client mode (always API for SystemManager)
            **kwargs: Additional client configuration
            
        Returns:
            Initialized GleitzeitClient ready for use
        """
        import asyncio
        
        # Create client
        client = cls(mode=mode, **kwargs)
        
        # Handle async initialization
        try:
            # Try to get running loop (Jupyter with %autoawait)
            loop = asyncio.get_running_loop()
            # We're in an async context, need to run in a task
            task = loop.create_task(client.initialize())
            loop.run_until_complete(task)
        except RuntimeError:
            # No running loop - normal Python script
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(client.initialize())
            finally:
                # Keep the loop for future operations
                client._sync_loop = loop
                
        return client
    
    def run_workflow_sync(self, workflow: Union[str, Dict, Workflow]) -> Any:
        """
        Run a workflow synchronously (for scripts/notebooks).
        
        Args:
            workflow: Workflow to run (path, dict, or Workflow object)
            
        Returns:
            Workflow execution results
        """
        import asyncio
        
        # Parse workflow if needed
        if isinstance(workflow, str):
            # Load from file
            import yaml
            from pathlib import Path
            with open(Path(workflow), 'r') as f:
                workflow_data = yaml.safe_load(f)
            workflow = Workflow(**workflow_data)
        elif isinstance(workflow, dict):
            workflow = Workflow(**workflow)
            
        # Run async method in sync context
        if hasattr(self, '_sync_loop'):
            # Use the loop we created during start_sync
            return self._sync_loop.run_until_complete(
                self.submit_workflow(workflow)
            )
        else:
            # Try to run in existing or new loop
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(self.submit_workflow(workflow))
                return loop.run_until_complete(task)
            except RuntimeError:
                return asyncio.run(self.submit_workflow(workflow))
    
    def run_task_sync(self, task: Union[Dict, Task]) -> TaskResult:
        """
        Run a task synchronously (for scripts/notebooks).
        
        Args:
            task: Task to run (dict or Task object)
            
        Returns:
            Task execution result
        """
        import asyncio
        
        # Parse task if needed
        if isinstance(task, dict):
            task = Task(**task)
            
        # Run async method in sync context
        if hasattr(self, '_sync_loop'):
            return self._sync_loop.run_until_complete(
                self.submit_task(task)
            )
        else:
            try:
                loop = asyncio.get_running_loop()
                task_future = loop.create_task(self.submit_task(task))
                return loop.run_until_complete(task_future)
            except RuntimeError:
                return asyncio.run(self.submit_task(task))
    
    def stop_sync(self) -> None:
        """
        Stop the client synchronously (cleanup).
        """
        import asyncio
        
        if hasattr(self, '_sync_loop'):
            self._sync_loop.run_until_complete(self.shutdown())
            self._sync_loop.close()
            self._sync_loop = None
        else:
            try:
                loop = asyncio.get_running_loop()
                loop.run_until_complete(self.shutdown())
            except RuntimeError:
                asyncio.run(self.shutdown())
        
    async def emit_event(self, 
                        event: Union[ClientEvent, Dict[str, Any], str],
                        data: Optional[Dict[str, Any]] = None) -> None:
        """
        Emit a custom event.
        
        Args:
            event: Event to emit (ClientEvent, dict, or event type string)
            data: Optional event data (if event is a string)
        """
        # Handle different input types
        if isinstance(event, str):
            event = ClientEvent(
                event_type=event,
                data=data or {}
            )
        elif isinstance(event, dict):
            event = ClientEvent(**event)
            
        await self.event_bus.emit(event)
        
    def get_event_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive event statistics.
        
        Returns:
            Dictionary with event bus and adapter statistics
        """
        stats = {
            'event_bus': self.event_bus.get_metrics(),
            'mode': self.mode.value,
            'event_mode': self.event_mode.value,
            'initialized': self._initialized
        }
        
        # Add adapter statistics
        if self._adapter and hasattr(self._adapter, 'get_event_statistics'):
            adapter_stats = self._adapter.get_event_statistics()
            stats.update(adapter_stats)
            
        # User handlers
        stats['user_handlers'] = {
            str(event_type): len(handlers) 
            for event_type, handlers in self._user_handlers.items()
        }
        
        return stats
        
    def is_event_mode_active(self) -> bool:
        """
        Check if event mode is currently active.
        
        Returns:
            True if events are being received via WebSocket/direct connection
        """
        if not self._adapter:
            return False
        return self._adapter.is_event_mode_active()
        
    def get_connection_state(self) -> Optional[ConnectionState]:
        """
        Get current WebSocket connection state.
        
        Returns:
            ConnectionState enum value or None
        """
        if not self._adapter:
            return None
        return self._adapter.get_connection_state()
        
    async def reconnect_events(self) -> bool:
        """
        Manually trigger WebSocket reconnection.
        
        Returns:
            True if reconnection successful
        """
        if not self._adapter:
            return False
            
        if hasattr(self._adapter, 'websocket_manager'):
            ws_manager = self._adapter.websocket_manager
            if ws_manager:
                return await ws_manager.connect()
                
        return False
        
    async def batch_submit_with_progress(self,
                                        tasks: List[Task],
                                        on_progress: Optional[Callable] = None) -> List[TaskResult]:
        """
        Submit multiple tasks and track progress via events.
        
        Args:
            tasks: List of tasks to submit
            on_progress: Progress callback
            
        Returns:
            List of task results
        """
        results = []
        completed = 0
        total = len(tasks)
        
        async def task_complete_handler(event):
            nonlocal completed
            task_id = event.data.get('task_id')
            
            # Check if it's one of our tasks
            if task_id in [t.id for t in tasks]:
                completed += 1
                
                if on_progress:
                    progress = (completed / total) * 100
                    await on_progress(progress, completed, total)
                    
        # Register handler
        sub_id = None
        if self.event_bus:
            sub_id = self.event_bus.register(EventType.TASK_COMPLETED, task_complete_handler)
            
        try:
            # Submit all tasks
            futures = []
            for task in tasks:
                response = await self.submit_task(task)
                if self._adapter:
                    future = self._adapter.wait_for_task(task.id)
                    futures.append(future)
                    
            # Wait for all completions
            if futures:
                results = await asyncio.gather(*futures)
            else:
                # Fallback to polling
                for task in tasks:
                    result = await self.wait_for_task(task.id)
                    results.append(result)
                    
        finally:
            # Cleanup handler
            if sub_id and self.event_bus:
                self.event_bus.unregister(sub_id)
                
        return results


# Make this the default export
EventDrivenClient = GleitzeitClient