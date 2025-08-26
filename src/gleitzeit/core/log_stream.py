"""
Log Stream Manager

Manages real-time log streaming to WebSocket clients.
Handles subscriptions, buffering, and event routing.
"""

import asyncio
import logging
from typing import Dict, Set, List, Optional, Any
from collections import defaultdict, deque
from datetime import datetime
from fastapi import WebSocket
from fastapi.websockets import WebSocketState

from gleitzeit.core.events import GleitzeitEvent, EventType
from gleitzeit.core.logs import LogEntry, LogLevel, LogSource
from gleitzeit.events.base import EventBus

logger = logging.getLogger(__name__)


class LogStreamManager:
    """Manages real-time log streaming to WebSocket clients"""
    
    def __init__(
        self,
        event_bus: EventBus,
        buffer_size: int = 1000,
        buffer_ttl: int = 3600  # seconds
    ):
        """
        Initialize log stream manager
        
        Args:
            event_bus: Event bus for receiving log events
            buffer_size: Number of logs to keep in buffer per stream
            buffer_ttl: Time to keep buffers after last activity (seconds)
        """
        self.event_bus = event_bus
        self.buffer_size = buffer_size
        self.buffer_ttl = buffer_ttl
        
        # Subscribers: stream_key -> set of WebSockets
        self.subscribers: Dict[str, Set[WebSocket]] = defaultdict(set)
        
        # Buffers: stream_key -> deque of log entries
        self.buffers: Dict[str, deque] = defaultdict(lambda: deque(maxlen=buffer_size))
        
        # Buffer timestamps: stream_key -> last activity time
        self.buffer_timestamps: Dict[str, datetime] = {}
        
        # Subscribe lock for thread safety
        self.subscribe_lock = asyncio.Lock()
        
        # Cleanup task
        self.cleanup_task: Optional[asyncio.Task] = None
        
        # Statistics
        self.stats = {
            "messages_sent": 0,
            "messages_buffered": 0,
            "send_errors": 0,
            "active_streams": 0,
            "total_subscribers": 0
        }
        
        # Register event handlers
        if event_bus:
            event_bus.register(EventType.LOG_MESSAGE, self._handle_log_event)
            event_bus.register(EventType.LOG_STREAM_START, self._handle_stream_start)
            event_bus.register(EventType.LOG_STREAM_END, self._handle_stream_end)
    
    async def start(self):
        """Start the stream manager"""
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("LogStreamManager started")
    
    async def stop(self):
        """Stop the stream manager"""
        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Close all WebSocket connections
        for subscribers in self.subscribers.values():
            for websocket in subscribers:
                try:
                    await websocket.close()
                except:
                    pass
        
        self.subscribers.clear()
        self.buffers.clear()
        
        logger.info(f"LogStreamManager stopped. Stats: {self.stats}")
    
    async def subscribe(
        self,
        websocket: WebSocket,
        task_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        send_buffer: bool = True,
        filter_level: Optional[LogLevel] = None
    ) -> str:
        """
        Subscribe a WebSocket client to a log stream
        
        Args:
            websocket: WebSocket connection
            task_id: Task to subscribe to (mutually exclusive with workflow_id)
            workflow_id: Workflow to subscribe to (mutually exclusive with task_id)
            send_buffer: Whether to send buffered logs to new subscriber
            filter_level: Minimum log level to send
        
        Returns:
            Stream key for the subscription
        """
        stream_key = self._get_stream_key(task_id, workflow_id)
        
        async with self.subscribe_lock:
            self.subscribers[stream_key].add(websocket)
            self.stats["total_subscribers"] += 1
            self.stats["active_streams"] = len([s for s in self.subscribers.values() if s])
            
            # Store subscription metadata on WebSocket
            if not hasattr(websocket, 'log_metadata'):
                websocket.log_metadata = {}
            websocket.log_metadata['stream_key'] = stream_key
            websocket.log_metadata['filter_level'] = filter_level
            
            logger.debug(f"Client subscribed to stream: {stream_key}")
        
        # Send buffered logs if requested
        if send_buffer and stream_key in self.buffers:
            buffer_copy = list(self.buffers[stream_key])
            for entry_dict in buffer_copy:
                # Check level filter
                if filter_level and self._get_level_value(entry_dict.get('level')) < self._get_level_value(filter_level):
                    continue
                
                try:
                    await websocket.send_json({
                        "type": "log:history",
                        "data": entry_dict
                    })
                except:
                    break  # Client disconnected
        
        # Send subscription confirmation
        try:
            await websocket.send_json({
                "type": "log:subscribed",
                "stream": stream_key,
                "buffered_count": len(self.buffers.get(stream_key, []))
            })
        except:
            pass
        
        return stream_key
    
    async def unsubscribe(self, websocket: WebSocket) -> None:
        """Remove a WebSocket from all subscriptions"""
        async with self.subscribe_lock:
            for stream_key, subscribers in self.subscribers.items():
                if websocket in subscribers:
                    subscribers.discard(websocket)
                    logger.debug(f"Client unsubscribed from stream: {stream_key}")
            
            self.stats["total_subscribers"] = max(0, self.stats["total_subscribers"] - 1)
            self.stats["active_streams"] = len([s for s in self.subscribers.values() if s])
    
    async def _handle_log_event(self, event: GleitzeitEvent) -> None:
        """Handle incoming log event from event bus"""
        try:
            data = event.data
            
            # Extract log entry data
            if 'entry' in data:
                # New format with LogEventData
                entry_data = data['entry']
            else:
                # Direct log data
                entry_data = data
            
            task_id = entry_data.get('task_id')
            workflow_id = entry_data.get('workflow_id')
            
            # Buffer the log for each relevant stream
            for stream_key in self._get_matching_stream_keys(task_id, workflow_id):
                self.buffers[stream_key].append(entry_data)
                self.buffer_timestamps[stream_key] = datetime.utcnow()
                self.stats["messages_buffered"] += 1
            
            # Send to all matching subscribers
            await self._broadcast_to_streams(entry_data, task_id, workflow_id)
            
        except Exception as e:
            logger.error(f"Error handling log event: {e}")
    
    async def _handle_stream_start(self, event: GleitzeitEvent) -> None:
        """Handle stream start event"""
        data = event.data
        task_id = data.get('task_id')
        workflow_id = data.get('workflow_id')
        
        notification = {
            "type": "log:stream_start",
            "data": data
        }
        
        # Send to relevant subscribers
        for stream_key in self._get_matching_stream_keys(task_id, workflow_id):
            await self._send_to_stream(stream_key, notification)
    
    async def _handle_stream_end(self, event: GleitzeitEvent) -> None:
        """Handle stream end event"""
        data = event.data
        task_id = data.get('task_id')
        workflow_id = data.get('workflow_id')
        
        notification = {
            "type": "log:stream_end",
            "data": data
        }
        
        # Send to relevant subscribers
        for stream_key in self._get_matching_stream_keys(task_id, workflow_id):
            await self._send_to_stream(stream_key, notification)
    
    async def _broadcast_to_streams(
        self,
        entry_data: Dict[str, Any],
        task_id: Optional[str],
        workflow_id: Optional[str]
    ) -> None:
        """Broadcast log entry to all matching streams"""
        message = {
            "type": "log:message",
            "data": entry_data
        }
        
        for stream_key in self._get_matching_stream_keys(task_id, workflow_id):
            await self._send_to_stream(stream_key, message, entry_data.get('level'))
    
    async def _send_to_stream(
        self,
        stream_key: str,
        message: Dict[str, Any],
        level: Optional[str] = None
    ) -> None:
        """Send message to all subscribers of a stream"""
        subscribers = self.subscribers.get(stream_key, set()).copy()
        
        for websocket in subscribers:
            # Check level filter if applicable
            if level and hasattr(websocket, 'log_metadata'):
                filter_level = websocket.log_metadata.get('filter_level')
                if filter_level and self._get_level_value(level) < self._get_level_value(filter_level):
                    continue
            
            try:
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.send_json(message)
                    self.stats["messages_sent"] += 1
                else:
                    # Remove disconnected client
                    await self.unsubscribe(websocket)
            except Exception as e:
                self.stats["send_errors"] += 1
                logger.warning(f"Failed to send log to client: {e}")
                await self.unsubscribe(websocket)
    
    def _get_stream_key(self, task_id: str = None, workflow_id: str = None) -> str:
        """Generate stream key from task/workflow ID"""
        if task_id:
            return f"task:{task_id}"
        elif workflow_id:
            return f"workflow:{workflow_id}"
        else:
            return "global"
    
    def _get_matching_stream_keys(
        self,
        task_id: Optional[str],
        workflow_id: Optional[str]
    ) -> List[str]:
        """Get all stream keys that should receive this log"""
        keys = ["global"]  # Global stream always receives everything
        
        if task_id:
            keys.append(f"task:{task_id}")
        
        if workflow_id:
            keys.append(f"workflow:{workflow_id}")
        
        return keys
    
    def _get_level_value(self, level: Any) -> int:
        """Convert log level to numeric value for comparison"""
        level_values = {
            LogLevel.DEBUG: 10,
            LogLevel.INFO: 20,
            LogLevel.WARNING: 30,
            LogLevel.ERROR: 40,
            LogLevel.CRITICAL: 50,
            "debug": 10,
            "info": 20,
            "warning": 30,
            "error": 40,
            "critical": 50
        }
        return level_values.get(level, 0)
    
    async def _cleanup_loop(self) -> None:
        """Periodically clean up old buffers"""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                
                now = datetime.utcnow()
                keys_to_remove = []
                
                for stream_key, timestamp in self.buffer_timestamps.items():
                    # Remove buffers inactive for TTL seconds
                    if (now - timestamp).total_seconds() > self.buffer_ttl:
                        # Only remove if no active subscribers
                        if not self.subscribers.get(stream_key):
                            keys_to_remove.append(stream_key)
                
                for key in keys_to_remove:
                    del self.buffers[key]
                    del self.buffer_timestamps[key]
                    logger.debug(f"Cleaned up buffer for stream: {key}")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get stream manager statistics"""
        return {
            **self.stats,
            "buffer_count": len(self.buffers),
            "total_buffered_logs": sum(len(b) for b in self.buffers.values())
        }


# Global stream manager instance
_log_stream_manager: Optional[LogStreamManager] = None


def get_log_stream_manager() -> Optional[LogStreamManager]:
    """Get the global log stream manager instance"""
    return _log_stream_manager


def set_log_stream_manager(manager: LogStreamManager) -> None:
    """Set the global log stream manager instance"""
    global _log_stream_manager
    _log_stream_manager = manager