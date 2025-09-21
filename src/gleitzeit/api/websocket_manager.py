"""
WebSocket connection manager with Redis PubSub for cross-instance scalability.

This module provides a scalable WebSocket manager that uses Redis PubSub
to broadcast events across multiple API instances, ensuring all connected
clients receive updates regardless of which instance they're connected to.
"""

import os
import json
import asyncio
import logging
from typing import Dict, Set, Optional, Any, List
from collections import defaultdict, deque
from datetime import datetime, timedelta
from time import time

from fastapi import WebSocket
import redis.asyncio as redis

logger = logging.getLogger(__name__)


class RateLimiter:
    """Rate limiter for WebSocket connections."""
    
    def __init__(self, max_messages: int = 100, window_seconds: int = 60):
        """
        Initialize rate limiter.
        
        Args:
            max_messages: Maximum messages allowed in window
            window_seconds: Time window in seconds
        """
        self.max_messages = max_messages
        self.window = window_seconds
        self.messages: deque = deque()
    
    def check_rate(self) -> bool:
        """
        Check if rate limit allows another message.
        
        Returns:
            True if message allowed, False if rate limited
        """
        now = time()
        
        # Remove old messages outside window
        while self.messages and self.messages[0] < now - self.window:
            self.messages.popleft()
        
        # Check if under limit
        if len(self.messages) >= self.max_messages:
            return False
        
        # Record this message
        self.messages.append(now)
        return True


class ScalableWebSocketManager:
    """
    Scalable WebSocket connection manager with Redis PubSub support.
    
    Features:
    - Connection limits (total and per-IP)
    - Rate limiting per connection
    - Redis PubSub for cross-instance broadcasting
    - Heartbeat/keepalive mechanism
    - Origin validation
    - Automatic cleanup of dead connections
    """
    
    def __init__(self):
        """Initialize the WebSocket manager."""
        # Connection tracking
        self.active_connections: Dict[str, WebSocket] = {}
        self.subscriptions: Dict[str, Set[str]] = defaultdict(set)
        self.connection_ips: Dict[str, str] = {}
        self.ip_connections: Dict[str, Set[str]] = defaultdict(set)
        
        # Rate limiters per connection
        self.rate_limiters: Dict[str, RateLimiter] = {}
        
        # Heartbeat tracking
        self.last_heartbeat: Dict[str, datetime] = {}
        
        # Configuration from environment
        self.max_connections = int(os.getenv("GLEITZEIT_WEBSOCKET_MAX_CONNECTIONS", "1000"))
        self.max_connections_per_ip = int(os.getenv("GLEITZEIT_WEBSOCKET_MAX_CONNECTIONS_PER_IP", "10"))
        self.heartbeat_interval = int(os.getenv("GLEITZEIT_WEBSOCKET_HEARTBEAT_INTERVAL", "30"))
        self.heartbeat_timeout = int(os.getenv("GLEITZEIT_WEBSOCKET_HEARTBEAT_TIMEOUT", "90"))
        
        # Allowed origins for CORS
        allowed_origins_str = os.getenv("GLEITZEIT_WEBSOCKET_ALLOWED_ORIGINS", "")
        if allowed_origins_str:
            self.allowed_origins = set(allowed_origins_str.split(","))
        else:
            # Default allowed origins
            self.allowed_origins = {
                "http://localhost:3000",
                "http://localhost:8000",
                "http://127.0.0.1:3000",
                "http://127.0.0.1:8000"
            }
        
        # Redis PubSub
        self.redis_client: Optional[redis.Redis] = None
        self.pubsub: Optional[redis.client.PubSub] = None
        self.pubsub_task: Optional[asyncio.Task] = None
        self.instance_id = f"ws_{os.getpid()}_{id(self)}"
        
        logger.info(f"WebSocket manager initialized: instance_id={self.instance_id}, "
                   f"max_connections={self.max_connections}, "
                   f"max_per_ip={self.max_connections_per_ip}")
    
    async def initialize_redis(self):
        """Initialize Redis connection for PubSub."""
        try:
            redis_url = os.getenv("GLEITZEIT_REDIS_URL", "redis://localhost:6379/0")
            self.redis_client = await redis.from_url(redis_url, decode_responses=True)
            
            # Test connection
            await self.redis_client.ping()
            
            # Setup PubSub
            self.pubsub = self.redis_client.pubsub()
            await self.pubsub.subscribe("gleitzeit:websocket:events")
            
            # Start listening task
            self.pubsub_task = asyncio.create_task(self._redis_listener())
            
            logger.info(f"Redis PubSub initialized for WebSocket broadcasting")
            
        except Exception as e:
            logger.error(f"Failed to initialize Redis PubSub: {e}")
            logger.warning("WebSocket broadcasting will be limited to this instance only")
    
    async def _redis_listener(self):
        """Listen for Redis PubSub messages and broadcast to local connections."""
        try:
            async for message in self.pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        
                        # Skip messages from this instance
                        if data.get("instance_id") == self.instance_id:
                            continue
                        
                        # Broadcast to local connections
                        event_type = data.get("type")
                        channel = data.get("channel")
                        payload = data.get("payload", {})
                        
                        await self._broadcast_local(payload, channel)
                        
                    except json.JSONDecodeError:
                        logger.error(f"Invalid JSON in Redis message: {message['data']}")
                    except Exception as e:
                        logger.error(f"Error processing Redis message: {e}")
                        
        except asyncio.CancelledError:
            logger.info("Redis listener task cancelled")
        except Exception as e:
            logger.error(f"Redis listener error: {e}")
    
    def validate_origin(self, websocket: WebSocket) -> bool:
        """
        Validate WebSocket origin header.
        
        Args:
            websocket: WebSocket connection
            
        Returns:
            True if origin is allowed, False otherwise
        """
        # If no origins configured, allow all (development mode)
        if not self.allowed_origins:
            return True
        
        # Check Origin header
        origin = websocket.headers.get("Origin")
        if not origin:
            # No origin header - could be a non-browser client
            logger.warning("WebSocket connection without Origin header")
            return True  # Allow for now, could be stricter
        
        # Check if origin is allowed
        if origin in self.allowed_origins:
            return True
        
        # Check for wildcard patterns
        for allowed in self.allowed_origins:
            if allowed == "*":
                return True
            if allowed.endswith("*") and origin.startswith(allowed[:-1]):
                return True
        
        logger.warning(f"WebSocket connection rejected - invalid origin: {origin}")
        return False
    
    def check_connection_limits(self, connection_id: str, client_ip: str) -> tuple[bool, str]:
        """
        Check if connection limits allow a new connection.
        
        Args:
            connection_id: Unique connection ID
            client_ip: Client IP address
            
        Returns:
            Tuple of (allowed, reason_if_not)
        """
        # Check total connections
        if len(self.active_connections) >= self.max_connections:
            return False, f"Server at capacity ({self.max_connections} connections)"
        
        # Check per-IP limit
        if len(self.ip_connections.get(client_ip, set())) >= self.max_connections_per_ip:
            return False, f"Too many connections from IP ({self.max_connections_per_ip} max)"
        
        return True, ""
    
    async def connect(
        self,
        websocket: WebSocket,
        connection_id: str,
        client_ip: str,
        user: Dict[str, Any]
    ) -> bool:
        """
        Accept and track a new WebSocket connection.
        
        Args:
            websocket: WebSocket connection
            connection_id: Unique connection ID
            client_ip: Client IP address
            user: Authenticated user info
            
        Returns:
            True if connection accepted, False if rejected
        """
        # Validate origin
        if not self.validate_origin(websocket):
            await websocket.close(code=1008, reason="Origin not allowed")
            return False
        
        # Check connection limits
        allowed, reason = self.check_connection_limits(connection_id, client_ip)
        if not allowed:
            await websocket.accept()
            await websocket.send_json({
                "type": "error",
                "message": reason,
                "code": 1013
            })
            await websocket.close(code=1013, reason=reason)
            return False
        
        # Accept connection
        await websocket.accept()
        
        # Track connection
        self.active_connections[connection_id] = websocket
        self.connection_ips[connection_id] = client_ip
        self.ip_connections[client_ip].add(connection_id)
        self.subscriptions[connection_id] = set()
        self.rate_limiters[connection_id] = RateLimiter()
        self.last_heartbeat[connection_id] = datetime.utcnow()
        
        # Send connection confirmation
        await websocket.send_json({
            "type": "connection",
            "status": "connected",
            "connection_id": connection_id,
            "user": {
                "id": user.get("id"),
                "username": user.get("username"),
                "role": user.get("role")
            },
            "config": {
                "heartbeat_interval": self.heartbeat_interval,
                "rate_limit": {
                    "max_messages": 100,
                    "window_seconds": 60
                }
            },
            "timestamp": datetime.utcnow().isoformat()
        })
        
        logger.info(f"WebSocket connected: {connection_id} from {client_ip} as {user.get('username')}")
        return True
    
    def disconnect(self, connection_id: str):
        """
        Remove a WebSocket connection and clean up.
        
        Args:
            connection_id: Connection to remove
        """
        if connection_id not in self.active_connections:
            return
        
        # Clean up connection tracking
        del self.active_connections[connection_id]
        
        # Clean up IP tracking
        if connection_id in self.connection_ips:
            client_ip = self.connection_ips[connection_id]
            self.ip_connections[client_ip].discard(connection_id)
            if not self.ip_connections[client_ip]:
                del self.ip_connections[client_ip]
            del self.connection_ips[connection_id]
        
        # Clean up subscriptions
        if connection_id in self.subscriptions:
            del self.subscriptions[connection_id]
        
        # Clean up rate limiter
        if connection_id in self.rate_limiters:
            del self.rate_limiters[connection_id]
        
        # Clean up heartbeat tracking
        if connection_id in self.last_heartbeat:
            del self.last_heartbeat[connection_id]
        
        logger.info(f"WebSocket disconnected: {connection_id}")
    
    def check_rate_limit(self, connection_id: str) -> bool:
        """
        Check if connection is within rate limits.
        
        Args:
            connection_id: Connection to check
            
        Returns:
            True if within limits, False if rate limited
        """
        if connection_id not in self.rate_limiters:
            return False
        
        return self.rate_limiters[connection_id].check_rate()
    
    def update_heartbeat(self, connection_id: str):
        """
        Update heartbeat timestamp for connection.
        
        Args:
            connection_id: Connection that sent heartbeat
        """
        if connection_id in self.last_heartbeat:
            self.last_heartbeat[connection_id] = datetime.utcnow()
    
    async def check_dead_connections(self):
        """Check for and remove dead connections (no heartbeat)."""
        now = datetime.utcnow()
        timeout = timedelta(seconds=self.heartbeat_timeout)
        dead_connections = []
        
        for conn_id, last_beat in self.last_heartbeat.items():
            if now - last_beat > timeout:
                dead_connections.append(conn_id)
        
        for conn_id in dead_connections:
            logger.warning(f"Removing dead connection (no heartbeat): {conn_id}")
            
            # Try to close WebSocket
            if conn_id in self.active_connections:
                try:
                    websocket = self.active_connections[conn_id]
                    await websocket.close(code=1001, reason="Heartbeat timeout")
                except:
                    pass
            
            # Clean up
            self.disconnect(conn_id)
    
    async def subscribe(self, connection_id: str, channels: List[str]):
        """
        Subscribe connection to channels.
        
        Args:
            connection_id: Connection ID
            channels: List of channels to subscribe to
        """
        if connection_id in self.subscriptions:
            self.subscriptions[connection_id].update(channels)
            
            # Send confirmation
            if connection_id in self.active_connections:
                websocket = self.active_connections[connection_id]
                await websocket.send_json({
                    "type": "subscription",
                    "channels": list(self.subscriptions[connection_id]),
                    "status": "subscribed"
                })
    
    async def unsubscribe(self, connection_id: str, channels: List[str]):
        """
        Unsubscribe connection from channels.
        
        Args:
            connection_id: Connection ID
            channels: List of channels to unsubscribe from
        """
        if connection_id in self.subscriptions:
            for channel in channels:
                self.subscriptions[connection_id].discard(channel)
            
            # Send confirmation
            if connection_id in self.active_connections:
                websocket = self.active_connections[connection_id]
                await websocket.send_json({
                    "type": "subscription",
                    "channels": list(self.subscriptions[connection_id]),
                    "status": "unsubscribed"
                })
    
    async def send_to_connection(self, connection_id: str, message: Dict[str, Any]):
        """
        Send message to specific connection.
        
        Args:
            connection_id: Target connection
            message: Message to send
        """
        if connection_id in self.active_connections:
            websocket = self.active_connections[connection_id]
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Error sending to {connection_id}: {e}")
                self.disconnect(connection_id)
    
    async def _broadcast_local(self, message: Dict[str, Any], channel: Optional[str] = None):
        """
        Broadcast message to local connections.
        
        Args:
            message: Message to broadcast
            channel: Optional channel filter
        """
        # Add timestamp if not present
        if "timestamp" not in message:
            message["timestamp"] = datetime.utcnow().isoformat()
        
        disconnected = []
        
        for conn_id, websocket in self.active_connections.items():
            # Check channel subscription if specified
            if channel:
                if channel not in self.subscriptions.get(conn_id, set()):
                    if "*" not in self.subscriptions.get(conn_id, set()):
                        continue
            
            try:
                await websocket.send_json(message)
            except:
                disconnected.append(conn_id)
        
        # Clean up disconnected
        for conn_id in disconnected:
            self.disconnect(conn_id)
    
    async def broadcast(self, message: Dict[str, Any], channel: Optional[str] = None):
        """
        Broadcast message to all instances via Redis PubSub.
        
        Args:
            message: Message to broadcast
            channel: Optional channel filter
        """
        # Broadcast locally
        await self._broadcast_local(message, channel)
        
        # Publish to Redis for other instances
        if self.redis_client:
            try:
                redis_message = {
                    "instance_id": self.instance_id,
                    "type": "broadcast",
                    "channel": channel,
                    "payload": message
                }
                await self.redis_client.publish(
                    "gleitzeit:websocket:events",
                    json.dumps(redis_message)
                )
            except Exception as e:
                logger.error(f"Failed to publish to Redis: {e}")
    
    async def cleanup(self):
        """Clean up resources on shutdown."""
        # Cancel Redis listener
        if self.pubsub_task:
            self.pubsub_task.cancel()
            try:
                await self.pubsub_task
            except asyncio.CancelledError:
                pass
        
        # Close Redis connections
        if self.pubsub:
            await self.pubsub.unsubscribe()
            await self.pubsub.close()
        
        if self.redis_client:
            await self.redis_client.close()
        
        # Close all WebSocket connections
        for conn_id in list(self.active_connections.keys()):
            try:
                websocket = self.active_connections[conn_id]
                await websocket.close(code=1001, reason="Server shutting down")
            except:
                pass
            self.disconnect(conn_id)
        
        logger.info("WebSocket manager cleaned up")

    async def shutdown(self):
        """Alias for cleanup() to match expected interface."""
        await self.cleanup()


# Global instance
scalable_ws_manager = ScalableWebSocketManager()


async def get_websocket_manager() -> ScalableWebSocketManager:
    """
    Get the global WebSocket manager instance.
    
    Returns:
        ScalableWebSocketManager instance
    """
    # Initialize Redis if not already done
    if not scalable_ws_manager.redis_client:
        await scalable_ws_manager.initialize_redis()
    
    return scalable_ws_manager