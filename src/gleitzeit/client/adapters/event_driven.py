"""
Event-driven adapter base class for Gleitzeit client.
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List, Callable, Union
from datetime import datetime
from abc import abstractmethod

from gleitzeit.core.models import Task, Workflow, TaskResult, TaskStatus
from gleitzeit.core.events import EventType, GleitzeitEvent
from ..events import (
    ClientEventBus, ClientEvent, EventType,
    WebSocketManager, WebSocketConfig, ConnectionState
)
from .base import BaseAdapter

logger = logging.getLogger(__name__)


class EventDrivenAdapter(BaseAdapter):
    """
    Base adapter with event-driven capabilities.
    
    This adapter provides:
    - Event bus integration
    - WebSocket connection management
    - Event-based task/workflow tracking
    - Automatic state synchronization
    - Fallback to polling when events unavailable
    """
    
    def __init__(self, 
                 enable_events: bool = True,
                 enable_websocket: bool = True,
                 fallback_to_polling: bool = True,
                 event_bus: Optional[ClientEventBus] = None):
        """
        Initialize event-driven adapter.
        
        Args:
            enable_events: Enable event-driven features
            enable_websocket: Enable WebSocket connection
            fallback_to_polling: Fall back to polling if events unavailable
            event_bus: Optional shared event bus instance
        """
        super().__init__()
        
        self.enable_events = enable_events
        self.enable_websocket = enable_websocket
        self.fallback_to_polling = fallback_to_polling
        
        # Event infrastructure
        self.event_bus = event_bus or ClientEventBus() if enable_events else None
        self.websocket_manager: Optional[WebSocketManager] = None
        
        # Task/workflow tracking (futures only for event coordination)
        self._task_futures: Dict[str, asyncio.Future] = {}
        self._workflow_futures: Dict[str, asyncio.Future] = {}
        
        # Event subscriptions
        self._subscription_ids: List[str] = []
        
        # State
        self._initialized = False
        self._event_mode_available = False
        
    async def initialize(self) -> None:
        """Initialize the event-driven adapter."""
        if self._initialized:
            return
            
        # Start event bus if enabled
        if self.event_bus:
            await self.event_bus.start()
            self._register_event_handlers()
            
        # Initialize WebSocket if enabled
        if self.enable_websocket and self.enable_events:
            await self._init_websocket()
            
        self._initialized = True
        logger.info("Event-driven adapter initialized")
        
    async def shutdown(self) -> None:
        """Shutdown the adapter and cleanup resources."""
        if not self._initialized:
            return
            
        # Cancel pending futures
        for future in list(self._task_futures.values()) + list(self._workflow_futures.values()):
            if not future.done():
                future.cancel()
                
        self._task_futures.clear()
        self._workflow_futures.clear()
        
        # Unregister event handlers
        for sub_id in self._subscription_ids:
            if self.event_bus:
                self.event_bus.unregister(sub_id)
        self._subscription_ids.clear()
        
        # Disconnect WebSocket
        if self.websocket_manager:
            await self.websocket_manager.disconnect()
            self.websocket_manager = None
            
        # Stop event bus
        if self.event_bus:
            await self.event_bus.stop()
            
        self._initialized = False
        logger.info("Event-driven adapter shutdown")
        
    def _register_event_handlers(self):
        """Register handlers for task and workflow events."""
        if not self.event_bus:
            return
            
        # Task events
        handlers = [
            (EventType.TASK_STARTED, self._on_task_started),
            (EventType.TASK_COMPLETED, self._on_task_completed),
            (EventType.TASK_FAILED, self._on_task_failed),
            (EventType.TASK_CANCELLED, self._on_task_cancelled),
            (EventType.TASK_TIMEOUT, self._on_task_timeout),
            
            # Workflow events
            (EventType.WORKFLOW_STARTED, self._on_workflow_started),
            (EventType.WORKFLOW_COMPLETED, self._on_workflow_completed),
            (EventType.WORKFLOW_FAILED, self._on_workflow_failed),
            (EventType.WORKFLOW_CANCELLED, self._on_workflow_cancelled),
            
            # Retry events
            (EventType.RETRY_SCHEDULED, self._on_retry_scheduled),
            (EventType.TASK_READY_FOR_RETRY, self._on_task_ready_for_retry),
        ]
        
        for event_type, handler in handlers:
            sub_id = self.event_bus.register(event_type, handler)
            self._subscription_ids.append(sub_id)
            
        logger.debug(f"Registered {len(handlers)} event handlers")
        
    @abstractmethod
    async def _init_websocket(self) -> None:
        """
        Initialize WebSocket connection.
        
        Must be implemented by subclasses to provide WebSocket URL and config.
        """
        pass
        
    async def _create_websocket_manager(self, url: str, **config_kwargs) -> WebSocketManager:
        """
        Create and configure WebSocket manager.
        
        Args:
            url: WebSocket URL
            **config_kwargs: Additional configuration
            
        Returns:
            Configured WebSocketManager instance
        """
        config = WebSocketConfig(url=url, **config_kwargs)
        
        manager = WebSocketManager(
            config=config,
            event_bus=self.event_bus,
            on_connect=self._on_websocket_connect,
            on_disconnect=self._on_websocket_disconnect,
            on_error=self._on_websocket_error
        )
        
        return manager
        
    async def _on_websocket_connect(self):
        """Handle WebSocket connection established."""
        self._event_mode_available = True
        logger.info("WebSocket connected - event mode available")
        
        # Subscribe to relevant events on server
        await self._subscribe_to_server_events()
        
    async def _on_websocket_disconnect(self):
        """Handle WebSocket disconnection."""
        self._event_mode_available = False
        logger.warning("WebSocket disconnected - falling back to polling if enabled")
        
    async def _on_websocket_error(self, error: Exception):
        """Handle WebSocket error."""
        logger.error(f"WebSocket error: {error}")
        self._event_mode_available = False
        
    async def _subscribe_to_server_events(self):
        """Subscribe to relevant events on the server."""
        if not self.websocket_manager or not self.websocket_manager.is_connected():
            return
            
        # Send subscription request
        await self.websocket_manager.send({
            'type': 'subscribe',
            'event_types': [
                'task:*',  # All task events
                'workflow:*',  # All workflow events
                'retry:*',  # Retry events
            ],
            'client_id': self.websocket_manager.config.client_id
        })
        
    # Event handlers
    
    async def _on_task_started(self, event: Union[GleitzeitEvent, ClientEvent]):
        """Handle task started event."""
        task_id = event.data.get('task_id')
        logger.debug(f"Task {task_id} started")
        
    async def _on_task_completed(self, event: Union[GleitzeitEvent, ClientEvent]):
        """Handle task completed event."""
        task_id = event.data.get('task_id')
        result_data = event.data.get('result')
        
        # Create TaskResult
        result = TaskResult(
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            result=result_data,
            error=None,
            started_at=event.data.get('started_at'),
            completed_at=event.data.get('completed_at', datetime.utcnow())
        )
        
        # Resolve future if waiting
        if task_id in self._task_futures:
            future = self._task_futures.pop(task_id)
            if not future.done():
                future.set_result(result)
                
        logger.info(f"Task {task_id} completed")
        
    async def _on_task_failed(self, event: Union[GleitzeitEvent, ClientEvent]):
        """Handle task failed event."""
        task_id = event.data.get('task_id')
        error_message = event.data.get('error_message', 'Unknown error')
        is_permanent = event.data.get('is_permanent', False)
        
        if not is_permanent:
            # Task will be retried
            logger.info(f"Task {task_id} failed (will retry): {error_message}")
            return
            
        # Create TaskResult for permanent failure
        result = TaskResult(
            task_id=task_id,
            status=TaskStatus.FAILED,
            result=None,
            error=error_message,
            started_at=event.data.get('started_at'),
            completed_at=event.data.get('completed_at', datetime.utcnow())
        )
        
        # Resolve future if waiting
        if task_id in self._task_futures:
            future = self._task_futures.pop(task_id)
            if not future.done():
                future.set_result(result)
                
        logger.error(f"Task {task_id} failed permanently: {error_message}")
        
    async def _on_task_cancelled(self, event: Union[GleitzeitEvent, ClientEvent]):
        """Handle task cancelled event."""
        task_id = event.data.get('task_id')
        
        result = TaskResult(
            task_id=task_id,
            status=TaskStatus.CANCELLED,
            result=None,
            error="Task cancelled",
            completed_at=datetime.utcnow()
        )
        
        self._task_results[task_id] = result
        
        if task_id in self._task_futures:
            future = self._task_futures.pop(task_id)
            if not future.done():
                future.set_result(result)
                
        logger.info(f"Task {task_id} cancelled")
        
    async def _on_task_timeout(self, event: Union[GleitzeitEvent, ClientEvent]):
        """Handle task timeout event."""
        task_id = event.data.get('task_id')
        timeout = event.data.get('timeout')
        
        result = TaskResult(
            task_id=task_id,
            status=TaskStatus.FAILED,
            result=None,
            error=f"Task timed out after {timeout} seconds",
            completed_at=datetime.utcnow()
        )
        
        self._task_results[task_id] = result
        
        if task_id in self._task_futures:
            future = self._task_futures.pop(task_id)
            if not future.done():
                future.set_result(result)
                
        logger.error(f"Task {task_id} timed out")
        
    async def _on_workflow_started(self, event: Union[GleitzeitEvent, ClientEvent]):
        """Handle workflow started event."""
        workflow_id = event.data.get('workflow_id')
        logger.info(f"Workflow {workflow_id} started")
        
    async def _on_workflow_completed(self, event: Union[GleitzeitEvent, ClientEvent]):
        """Handle workflow completed event."""
        workflow_id = event.data.get('workflow_id')
        results = event.data.get('results', [])
        
        # Resolve future if waiting
        if workflow_id in self._workflow_futures:
            future = self._workflow_futures.pop(workflow_id)
            if not future.done():
                future.set_result(results)
                
        logger.info(f"Workflow {workflow_id} completed with {len(results)} results")
        
    async def _on_workflow_failed(self, event: Union[GleitzeitEvent, ClientEvent]):
        """Handle workflow failed event."""
        workflow_id = event.data.get('workflow_id')
        error = event.data.get('error', 'Workflow failed')
        
        # Resolve future with error
        if workflow_id in self._workflow_futures:
            future = self._workflow_futures.pop(workflow_id)
            if not future.done():
                future.set_exception(Exception(error))
                
        logger.error(f"Workflow {workflow_id} failed: {error}")
        
    async def _on_workflow_cancelled(self, event: Union[GleitzeitEvent, ClientEvent]):
        """Handle workflow cancelled event."""
        workflow_id = event.data.get('workflow_id')
        
        if workflow_id in self._workflow_futures:
            future = self._workflow_futures.pop(workflow_id)
            if not future.done():
                future.cancel()
                
        logger.info(f"Workflow {workflow_id} cancelled")
        
    async def _on_retry_scheduled(self, event: Union[GleitzeitEvent, ClientEvent]):
        """Handle retry scheduled event."""
        task_id = event.data.get('task_id')
        retry_at = event.data.get('retry_at')
        attempt = event.data.get('attempt_number')
        
        logger.info(f"Task {task_id} retry #{attempt} scheduled for {retry_at}")
        
    async def _on_task_ready_for_retry(self, event: Union[GleitzeitEvent, ClientEvent]):
        """Handle task ready for retry event."""
        task_id = event.data.get('task_id')
        attempt = event.data.get('attempt_number')
        
        logger.info(f"Task {task_id} ready for retry attempt #{attempt}")
        
    # Enhanced task/workflow methods with event support
    
    async def wait_for_task(self, 
                           task_id: str, 
                           timeout: float = 300.0,
                           poll_interval: float = 1.0) -> Optional[TaskResult]:
        """
        Wait for task completion using events or polling.
        
        Args:
            task_id: Task ID to wait for
            timeout: Maximum wait time in seconds
            poll_interval: Polling interval if events unavailable
            
        Returns:
            Task result when complete or None if timeout
        """
        # Use events if available
        if self._event_mode_available and self.event_bus:
            # Create future for this task
            future = asyncio.Future()
            self._task_futures[task_id] = future
            
            try:
                # Wait for completion event
                result = await asyncio.wait_for(future, timeout=timeout)
                return result
                
            except asyncio.TimeoutError:
                logger.warning(f"Timeout waiting for task {task_id}")
                self._task_futures.pop(task_id, None)
                
                # Fall back to polling if enabled
                if self.fallback_to_polling:
                    return await self._poll_for_task(task_id, timeout, poll_interval)
                    
                return None
                
        # Use polling if events not available
        elif self.fallback_to_polling:
            return await self._poll_for_task(task_id, timeout, poll_interval)
            
        else:
            logger.error("Event mode not available and polling disabled")
            return None
            
    @abstractmethod
    async def _poll_for_task(self, 
                            task_id: str,
                            timeout: float,
                            poll_interval: float) -> Optional[TaskResult]:
        """
        Poll for task completion (must be implemented by subclasses).
        
        Args:
            task_id: Task ID to poll for
            timeout: Maximum time to poll
            poll_interval: Interval between polls
            
        Returns:
            Task result or None if timeout
        """
        pass
        
    async def wait_for_workflow(self,
                               workflow_id: str,
                               timeout: float = 600.0,
                               poll_interval: float = 2.0) -> List[TaskResult]:
        """
        Wait for workflow completion using events or polling.
        
        Args:
            workflow_id: Workflow ID to wait for
            timeout: Maximum wait time in seconds
            poll_interval: Polling interval if events unavailable
            
        Returns:
            List of task results when workflow completes
        """
        # Use events if available
        if self._event_mode_available and self.event_bus:
            # Create future for this workflow
            future = asyncio.Future()
            self._workflow_futures[workflow_id] = future
            
            try:
                # Wait for completion event
                results = await asyncio.wait_for(future, timeout=timeout)
                return results
                
            except asyncio.TimeoutError:
                logger.warning(f"Timeout waiting for workflow {workflow_id}")
                self._workflow_futures.pop(workflow_id, None)
                
                # Fall back to polling if enabled
                if self.fallback_to_polling:
                    return await self._poll_for_workflow(workflow_id, timeout, poll_interval)
                    
                return []
                
        # Use polling if events not available
        elif self.fallback_to_polling:
            return await self._poll_for_workflow(workflow_id, timeout, poll_interval)
            
        else:
            logger.error("Event mode not available and polling disabled")
            return []
            
    @abstractmethod
    async def _poll_for_workflow(self,
                                workflow_id: str,
                                timeout: float,
                                poll_interval: float) -> List[TaskResult]:
        """
        Poll for workflow completion (must be implemented by subclasses).
        
        Args:
            workflow_id: Workflow ID to poll for
            timeout: Maximum time to poll
            poll_interval: Interval between polls
            
        Returns:
            List of task results or empty list if timeout
        """
        pass
        
    def is_event_mode_active(self) -> bool:
        """Check if event mode is currently active."""
        return self._event_mode_available and self.websocket_manager and self.websocket_manager.is_connected()
        
    def get_connection_state(self) -> Optional[ConnectionState]:
        """Get WebSocket connection state."""
        if self.websocket_manager:
            return self.websocket_manager.state
        return None