"""
Base Gleitzeit client with modular mixins.
"""

import asyncio
import aiohttp
from enum import Enum
from typing import Optional, Union, Any, Dict, List
from ..client.mixins import (
    WorkflowMixin, TaskMixin, QueueMixin, 
    BatchProcessingMixin, AuthMixin, SystemMixin, ReplayMixin
)
from ..client.adapters import BaseAdapter, APIAdapter, NativeAdapter


class ClientMode(Enum):
    """Client operation modes."""
    AUTO = "auto"
    API = "api"
    NATIVE = "native"


class ModularGleitzeitClient(
    WorkflowMixin,
    TaskMixin,
    QueueMixin,
    BatchProcessingMixin,
    AuthMixin,
    SystemMixin,
    ReplayMixin
):
    """
    Modular Gleitzeit client with clean separation of concerns.
    
    This client uses mixins for different functional areas and adapters
    for different execution modes (API vs Native).
    """
    
    def __init__(
        self,
        mode: Union[str, ClientMode] = ClientMode.AUTO,
        api_host: str = "localhost",
        api_port: int = 8000,
        auto_start_server: bool = True,
        keep_server_running: bool = True,
        **native_config
    ):
        """
        Initialize the Gleitzeit client.
        
        Args:
            mode: Operation mode (auto, api, native)
            api_host: API server hostname
            api_port: API server port
            auto_start_server: Auto-start API server if not running
            keep_server_running: Keep server running after client closes
            **native_config: Configuration for native mode
        """
        self.mode = ClientMode(mode) if isinstance(mode, str) else mode
        self.api_host = api_host
        self.api_port = api_port
        self.auto_start_server = auto_start_server
        self.keep_server_running = keep_server_running
        self.native_config = native_config
        
        self._adapter: Optional[BaseAdapter] = None
        self._server_process = None
        self._initialized = False
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.shutdown()
    
    async def initialize(self) -> None:
        """
        Initialize the client and select appropriate adapter.
        """
        if self._initialized:
            return
        
        # Auto-detect mode if needed
        if self.mode == ClientMode.AUTO:
            self.mode = await self._detect_best_mode()
        
        # Create and initialize appropriate adapter
        if self.mode == ClientMode.API:
            await self._init_api_mode()
        else:
            await self._init_native_mode()
        
        self._initialized = True
    
    async def shutdown(self) -> None:
        """
        Shutdown the client and cleanup resources.
        """
        if not self._initialized:
            return
        
        if self._adapter:
            await self._adapter.shutdown()
            self._adapter = None
        
        # Stop server if we started it and not keeping it running
        if self._server_process and not self.keep_server_running:
            self._server_process.terminate()
            await asyncio.sleep(1)
            if self._server_process.poll() is None:
                self._server_process.kill()
            self._server_process = None
        
        self._initialized = False
    
    async def _detect_best_mode(self) -> ClientMode:
        """
        Auto-detect the best mode to use.
        
        Returns:
            ClientMode.API if API server is available or can be started
            ClientMode.NATIVE otherwise
        """
        # Check if API server is running
        if await self._check_api_available():
            return ClientMode.API
        
        # Try to start API server if configured
        if self.auto_start_server:
            if await self._start_api_server():
                return ClientMode.API
        
        # Fall back to native mode
        return ClientMode.NATIVE
    
    async def _check_api_available(self) -> bool:
        """Check if API server is available."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"http://{self.api_host}:{self.api_port}/",
                    timeout=aiohttp.ClientTimeout(total=2)
                ) as response:
                    return response.status == 200
        except:
            return False
    
    async def _start_api_server(self) -> bool:
        """Attempt to start API server."""
        import subprocess
        import time
        
        try:
            # Start server process
            self._server_process = subprocess.Popen(
                [
                    "python", "-m", "gleitzeit.cli.gleitzeit_cli",
                    "serve", "--port", str(self.api_port),
                    "--host", self.api_host, "--headless"
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            # Wait for server to start (max 10 seconds)
            for _ in range(20):
                await asyncio.sleep(0.5)
                if await self._check_api_available():
                    return True
            
            # Server didn't start in time
            if self._server_process:
                self._server_process.terminate()
                self._server_process = None
            
            return False
            
        except Exception:
            return False
    
    async def _init_api_mode(self) -> None:
        """Initialize API mode with APIAdapter."""
        self._adapter = APIAdapter(self.api_host, self.api_port)
        await self._adapter.initialize()
    
    async def _init_native_mode(self) -> None:
        """Initialize native mode with NativeAdapter."""
        self._adapter = NativeAdapter(self.native_config)
        await self._adapter.initialize()
    
    def get_mode(self) -> str:
        """
        Get current operating mode.
        
        Returns:
            Current mode as string
        """
        return self.mode.value
    
    def is_initialized(self) -> bool:
        """
        Check if client is initialized.
        
        Returns:
            True if initialized
        """
        return self._initialized
    
    async def switch_mode(self, mode: Union[str, ClientMode]) -> None:
        """
        Switch to a different operating mode.
        
        Args:
            mode: New mode to switch to
        """
        # Shutdown current adapter
        if self._adapter:
            await self._adapter.shutdown()
            self._adapter = None
        
        # Update mode
        self.mode = ClientMode(mode) if isinstance(mode, str) else mode
        
        # Reinitialize with new mode
        self._initialized = False
        await self.initialize()
    
    @property
    def adapter(self) -> Optional[BaseAdapter]:
        """
        Get the current adapter.
        
        Returns:
            Current adapter or None
        """
        return self._adapter
    
    async def execute_raw(self, method: str, *args, **kwargs) -> Any:
        """
        Execute a raw method on the adapter.
        
        This provides access to adapter-specific methods not exposed
        through mixins.
        
        Args:
            method: Method name to call
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            Method result
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        
        if not hasattr(self._adapter, method):
            raise AttributeError(f"Adapter has no method '{method}'")
        
        fn = getattr(self._adapter, method)
        if asyncio.iscoroutinefunction(fn):
            return await fn(*args, **kwargs)
        return fn(*args, **kwargs)
    
    async def get_events(self, workflow_id: Optional[str] = None,
                        task_id: Optional[str] = None,
                        event_type: Optional[str] = None,
                        limit: int = 1000) -> List[Dict[str, Any]]:
        """
        Get persisted events.
        
        Args:
            workflow_id: Filter by workflow ID
            task_id: Filter by task ID
            event_type: Filter by event type
            limit: Maximum number of events to return
            
        Returns:
            List of event dictionaries
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        
        if hasattr(self._adapter, 'get_events'):
            return await self._adapter.get_events(
                workflow_id=workflow_id,
                task_id=task_id,
                event_type=event_type,
                limit=limit
            )
        else:
            return []
    
    async def start_engine(self, mode: str = 'EVENT_DRIVEN'):
        """
        Start the execution engine in background.
        
        Args:
            mode: Execution mode (EVENT_DRIVEN, BATCH, etc.)
        
        Returns:
            Background task if started
        """
        if self.mode != ClientMode.NATIVE:
            return None  # Only native mode has engine
        
        if hasattr(self._adapter, 'start_engine'):
            return await self._adapter.start_engine(mode)
        return None
    
    async def stop_engine(self):
        """Stop the execution engine."""
        if hasattr(self._adapter, 'stop_engine'):
            return await self._adapter.stop_engine()
    
    @property
    def execution_engine(self):
        """
        Get execution engine for backward compatibility.
        
        Returns:
            ExecutionEngine instance or None
        """
        if hasattr(self._adapter, 'execution_engine'):
            return self._adapter.execution_engine
        return None
    
    @property
    def _execution_engine(self):
        """Alias for backward compatibility with legacy code."""
        return self.execution_engine