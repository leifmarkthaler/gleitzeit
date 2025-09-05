"""
WebSocket connection manager with auto-reconnection and message queuing.
"""

import asyncio
import json
import logging
import time
from typing import Optional, Dict, Any, Callable, List, Union
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import aiohttp
from aiohttp import ClientWebSocketResponse, WSMsgType

from .models import (
    ConnectionState, ClientEvent, WebSocketMessage,
    ConnectionConfig, EventStatistics
)
from .client_event_bus import ClientEventBus
from gleitzeit.core.events import GleitzeitEvent, EventType

logger = logging.getLogger(__name__)


@dataclass
class WebSocketConfig:
    """WebSocket connection configuration."""
    url: str
    reconnect_enabled: bool = True
    reconnect_interval: float = 1.0  # Initial reconnect interval
    reconnect_max_interval: float = 30.0  # Max reconnect interval
    reconnect_backoff_factor: float = 1.5  # Exponential backoff factor
    reconnect_max_attempts: Optional[int] = None  # None = infinite
    ping_interval: float = 30.0
    ping_timeout: float = 10.0
    message_timeout: float = 60.0
    max_message_size: int = 1024 * 1024  # 1MB
    queue_size: int = 10000
    
    # Authentication
    auth_token: Optional[str] = None
    auth_headers: Dict[str, str] = field(default_factory=dict)
    
    # Client identification  
    client_id: Optional[str] = None
    client_name: Optional[str] = "gleitzeit-client"
    client_version: Optional[str] = "1.0.0"


class WebSocketManager:
    """
    Manages WebSocket connection with auto-reconnection and event handling.
    
    Features:
    - Automatic reconnection with exponential backoff
    - Message queuing during disconnection
    - Health monitoring with ping/pong
    - Event translation and routing
    - Connection state management
    """
    
    def __init__(self,
                 config: WebSocketConfig,
                 event_bus: ClientEventBus,
                 on_connect: Optional[Callable] = None,
                 on_disconnect: Optional[Callable] = None,
                 on_error: Optional[Callable] = None):
        """
        Initialize WebSocket manager.
        
        Args:
            config: WebSocket configuration
            event_bus: Client event bus for event distribution
            on_connect: Optional callback for connection established
            on_disconnect: Optional callback for connection lost
            on_error: Optional callback for errors
        """
        self.config = config
        self.event_bus = event_bus
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.on_error = on_error
        
        # Connection state
        self.state = ConnectionState.DISCONNECTED
        self.websocket: Optional[ClientWebSocketResponse] = None
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Reconnection state
        self.reconnect_attempts = 0
        self.reconnect_interval = config.reconnect_interval
        self.last_connect_time: Optional[datetime] = None
        self.connection_id: Optional[str] = None
        
        # Tasks
        self._receive_task: Optional[asyncio.Task] = None
        self._ping_task: Optional[asyncio.Task] = None
        self._reconnect_task: Optional[asyncio.Task] = None
        
        # Message queue for offline buffering
        self.message_queue: asyncio.Queue = asyncio.Queue(maxsize=config.queue_size)
        self._send_task: Optional[asyncio.Task] = None
        
        # Statistics
        self.stats = EventStatistics()
        self._connection_start_time: Optional[float] = None
        
        # Running flag
        self._running = False
        
    async def connect(self) -> bool:
        """
        Establish WebSocket connection.
        
        Returns:
            True if connection successful
        """
        if self.state == ConnectionState.CONNECTED:
            logger.warning("Already connected")
            return True
            
        self.state = ConnectionState.CONNECTING
        self.stats.connection_state = ConnectionState.CONNECTING
        
        try:
            # Create session if needed
            if not self.session:
                timeout = aiohttp.ClientTimeout(total=self.config.message_timeout)
                self.session = aiohttp.ClientSession(timeout=timeout)
                
            # Prepare headers
            headers = dict(self.config.auth_headers)
            if self.config.auth_token:
                headers['Authorization'] = f'Bearer {self.config.auth_token}'
            headers['X-Client-ID'] = self.config.client_id or 'unknown'
            headers['X-Client-Name'] = self.config.client_name
            headers['X-Client-Version'] = self.config.client_version
            
            # Connect to WebSocket
            logger.info(f"Connecting to WebSocket: {self.config.url}")
            self.websocket = await self.session.ws_connect(
                self.config.url,
                headers=headers,
                max_msg_size=self.config.max_message_size,
                autoclose=False,
                autoping=False  # We'll handle ping/pong manually
            )
            
            # Update state
            self.state = ConnectionState.CONNECTED
            self.stats.connection_state = ConnectionState.CONNECTED
            self.reconnect_attempts = 0
            self.reconnect_interval = self.config.reconnect_interval
            self.last_connect_time = datetime.utcnow()
            self._connection_start_time = time.time()
            
            # Generate connection ID
            import uuid
            self.connection_id = str(uuid.uuid4())
            
            # Emit connection event
            await self.event_bus.emit(ClientEvent(
                event_type=EventType.CLIENT_CONNECTION_ESTABLISHED,
                data={
                    'url': self.config.url,
                    'connection_id': self.connection_id,
                    'reconnect_attempts': self.reconnect_attempts
                },
                client_id=self.config.client_id
            ))
            
            # Start background tasks
            self._running = True
            self._receive_task = asyncio.create_task(self._receive_loop())
            self._ping_task = asyncio.create_task(self._ping_loop())
            self._send_task = asyncio.create_task(self._send_loop())
            
            # Call connection callback
            if self.on_connect:
                try:
                    await self.on_connect()
                except Exception as e:
                    logger.error(f"Error in connection callback: {e}")
                    
            logger.info(f"WebSocket connected (ID: {self.connection_id})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            self.state = ConnectionState.FAILED
            self.stats.connection_state = ConnectionState.FAILED
            
            # Emit error event
            await self.event_bus.emit(ClientEvent(
                event_type=EventType.CLIENT_CONNECTION_ERROR,
                data={
                    'error': str(e),
                    'url': self.config.url
                },
                client_id=self.config.client_id
            ))
            
            # Start reconnection if enabled
            if self.config.reconnect_enabled:
                await self._schedule_reconnect()
                
            return False
            
    async def disconnect(self, code: int = 1000, message: str = "Normal closure"):
        """
        Disconnect WebSocket connection.
        
        Args:
            code: WebSocket close code
            message: Close message
        """
        if self.state == ConnectionState.DISCONNECTED:
            return
            
        logger.info(f"Disconnecting WebSocket (code: {code}, message: {message})")
        
        self._running = False
        self.state = ConnectionState.DISCONNECTED
        self.stats.connection_state = ConnectionState.DISCONNECTED
        
        # Cancel background tasks
        tasks = [self._receive_task, self._ping_task, self._send_task, self._reconnect_task]
        for task in tasks:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                    
        # Close WebSocket
        if self.websocket and not self.websocket.closed:
            await self.websocket.close(code=code, message=message.encode())
            
        # Close session
        if self.session:
            await self.session.close()
            self.session = None
            
        # Update stats
        if self._connection_start_time:
            self.stats.connection_uptime_seconds = time.time() - self._connection_start_time
            self._connection_start_time = None
            
        # Emit disconnection event
        await self.event_bus.emit(ClientEvent(
            event_type=EventType.CLIENT_CONNECTION_LOST,
            data={
                'code': code,
                'message': message,
                'connection_id': self.connection_id
            },
            client_id=self.config.client_id
        ))
        
        # Call disconnection callback
        if self.on_disconnect:
            try:
                await self.on_disconnect()
            except Exception as e:
                logger.error(f"Error in disconnection callback: {e}")
                
    async def send(self, message: Union[Dict[str, Any], ClientEvent, GleitzeitEvent]):
        """
        Send a message through WebSocket.
        
        Args:
            message: Message to send (dict, ClientEvent, or GleitzeitEvent)
        """
        # Convert to WebSocketMessage
        if isinstance(message, (ClientEvent, GleitzeitEvent)):
            ws_message = WebSocketMessage(
                type='event',
                event=message if isinstance(message, ClientEvent) else 
                      ClientEvent.from_server_event(message)
            )
        else:
            ws_message = WebSocketMessage(type='message', **message)
            
        # Queue message for sending
        try:
            await self.message_queue.put(ws_message)
            self.stats.queue_size = self.message_queue.qsize()
            self.stats.max_queue_size = max(self.stats.max_queue_size, self.stats.queue_size)
        except asyncio.QueueFull:
            logger.error("Message queue full, dropping message")
            self.stats.events_failed += 1
            
            await self.event_bus.emit(ClientEvent(
                event_type=EventType.QUEUE_FULL,
                data={'dropped_message': ws_message.dict()},
                client_id=self.config.client_id
            ))
            
    async def _send_loop(self):
        """Process outgoing message queue."""
        while self._running:
            try:
                # Get message from queue with timeout
                message = await asyncio.wait_for(
                    self.message_queue.get(),
                    timeout=1.0
                )
                
                # Send if connected
                if self.state == ConnectionState.CONNECTED and self.websocket:
                    try:
                        msg_json = message.json() if hasattr(message, 'json') else json.dumps(message)
                        await self.websocket.send_str(msg_json)
                        logger.debug(f"Sent message: {message.type}")
                    except Exception as e:
                        logger.error(f"Failed to send message: {e}")
                        # Re-queue message
                        await self.message_queue.put(message)
                        # Trigger reconnection
                        await self._handle_connection_error(e)
                else:
                    # Re-queue message if not connected
                    await self.message_queue.put(message)
                    await asyncio.sleep(0.1)
                    
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Error in send loop: {e}")
                
    async def _receive_loop(self):
        """Process incoming messages from WebSocket."""
        while self._running and self.websocket:
            try:
                msg = await self.websocket.receive()
                
                if msg.type == WSMsgType.TEXT:
                    await self._handle_message(msg.data)
                    
                elif msg.type == WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {msg.data}")
                    await self._handle_connection_error(msg.data)
                    
                elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED):
                    logger.info("WebSocket closed by server")
                    await self._handle_connection_loss()
                    break
                    
                elif msg.type == WSMsgType.PONG:
                    logger.debug("Received PONG")
                    
            except Exception as e:
                logger.error(f"Error in receive loop: {e}")
                await self._handle_connection_error(e)
                break
                
    async def _handle_message(self, data: str):
        """
        Handle incoming WebSocket message.
        
        Args:
            data: Raw message data
        """
        try:
            # Parse message
            message_dict = json.loads(data)
            
            # Handle different message types
            if message_dict.get('type') == 'event':
                # Convert to ClientEvent
                event_data = message_dict.get('event', {})
                
                # Handle server GleitzeitEvent
                if 'event_type' in event_data:
                    # Try to parse as known EventType
                    try:
                        event_type = EventType(event_data['event_type'])
                    except ValueError:
                        # Use as custom event type
                        event_type = event_data['event_type']
                        
                    event = ClientEvent(
                        event_type=event_type,
                        data=event_data.get('data', {}),
                        timestamp=datetime.fromisoformat(event_data.get('timestamp', datetime.utcnow().isoformat())),
                        client_id=self.config.client_id
                    )
                    
                    # Update statistics
                    self.stats.events_received += 1
                    self.stats.last_event_time = datetime.utcnow()
                    
                    # Calculate latency if timestamp present
                    if event.timestamp:
                        latency_ms = (datetime.utcnow() - event.timestamp).total_seconds() * 1000
                        self.stats.update_latency(latency_ms)
                        
                    # Emit to event bus
                    await self.event_bus.emit(event)
                    self.stats.events_processed += 1
                    
            elif message_dict.get('type') == 'ping':
                # Respond with pong
                await self.websocket.send_str(json.dumps({'type': 'pong'}))
                
            elif message_dict.get('type') == 'error':
                logger.error(f"Server error: {message_dict.get('error')}")
                self.stats.last_error_message = message_dict.get('error')
                self.stats.last_error_time = datetime.utcnow()
                
            else:
                logger.warning(f"Unknown message type: {message_dict.get('type')}")
                
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse message: {e}")
            self.stats.events_failed += 1
            
            await self.event_bus.emit(ClientEvent(
                event_type=EventType.CLIENT_ERROR,
                data={'error': str(e), 'raw_data': data[:1000]},
                client_id=self.config.client_id
            ))
            
        except Exception as e:
            logger.error(f"Error handling message: {e}")
            self.stats.events_failed += 1
            
    async def _ping_loop(self):
        """Send periodic ping messages to keep connection alive."""
        while self._running and self.websocket:
            try:
                await asyncio.sleep(self.config.ping_interval)
                
                if self.websocket and not self.websocket.closed:
                    await self.websocket.ping()
                    logger.debug("Sent PING")
                    
            except Exception as e:
                logger.error(f"Error in ping loop: {e}")
                await self._handle_connection_error(e)
                break
                
    async def _handle_connection_loss(self):
        """Handle loss of connection."""
        self.state = ConnectionState.DISCONNECTED
        self.stats.connection_state = ConnectionState.DISCONNECTED
        
        # Update uptime
        if self._connection_start_time:
            self.stats.connection_uptime_seconds = time.time() - self._connection_start_time
            self._connection_start_time = None
            
        # Emit event
        await self.event_bus.emit(ClientEvent(
            event_type=EventType.CLIENT_CONNECTION_LOST,
            data={'connection_id': self.connection_id},
            client_id=self.config.client_id
        ))
        
        # Schedule reconnection
        if self.config.reconnect_enabled and self._running:
            await self._schedule_reconnect()
            
    async def _handle_connection_error(self, error: Exception):
        """Handle connection error."""
        logger.error(f"Connection error: {error}")
        
        self.stats.last_error_message = str(error)
        self.stats.last_error_time = datetime.utcnow()
        
        # Call error callback
        if self.on_error:
            try:
                await self.on_error(error)
            except Exception as e:
                logger.error(f"Error in error callback: {e}")
                
        # Handle connection loss
        await self._handle_connection_loss()
        
    async def _schedule_reconnect(self):
        """Schedule reconnection attempt."""
        if self._reconnect_task and not self._reconnect_task.done():
            return  # Already scheduled
            
        self.state = ConnectionState.RECONNECTING
        self.stats.connection_state = ConnectionState.RECONNECTING
        
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())
        
    async def _reconnect_loop(self):
        """Attempt to reconnect with exponential backoff."""
        while self._running and self.config.reconnect_enabled:
            # Check max attempts
            if (self.config.reconnect_max_attempts and 
                self.reconnect_attempts >= self.config.reconnect_max_attempts):
                logger.error(f"Max reconnection attempts ({self.config.reconnect_max_attempts}) reached")
                
                await self.event_bus.emit(ClientEvent(
                    event_type=EventType.CLIENT_RECONNECTION_FAILED,
                    data={
                        'attempts': self.reconnect_attempts,
                        'max_attempts': self.config.reconnect_max_attempts
                    },
                    client_id=self.config.client_id
                ))
                
                self.state = ConnectionState.FAILED
                self.stats.connection_state = ConnectionState.FAILED
                break
                
            # Wait before reconnecting
            await asyncio.sleep(self.reconnect_interval)
            
            self.reconnect_attempts += 1
            self.stats.reconnection_count += 1
            
            logger.info(f"Reconnection attempt {self.reconnect_attempts}")
            
            await self.event_bus.emit(ClientEvent(
                event_type=EventType.CLIENT_RECONNECTION_ATTEMPT,
                data={
                    'attempt': self.reconnect_attempts,
                    'interval': self.reconnect_interval
                },
                client_id=self.config.client_id
            ))
            
            # Try to connect
            if await self.connect():
                logger.info("Reconnection successful")
                
                await self.event_bus.emit(ClientEvent(
                    event_type=EventType.CLIENT_RECONNECTION_SUCCESS,
                    data={
                        'attempts': self.reconnect_attempts,
                        'connection_id': self.connection_id
                    },
                    client_id=self.config.client_id
                ))
                break
            else:
                # Exponential backoff
                self.reconnect_interval = min(
                    self.reconnect_interval * self.config.reconnect_backoff_factor,
                    self.config.reconnect_max_interval
                )
                
    def get_statistics(self) -> EventStatistics:
        """Get connection and event statistics."""
        # Update current uptime
        if self._connection_start_time and self.state == ConnectionState.CONNECTED:
            self.stats.connection_uptime_seconds = time.time() - self._connection_start_time
            
        return self.stats
        
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return (self.state == ConnectionState.CONNECTED and 
                self.websocket is not None and 
                not self.websocket.closed)