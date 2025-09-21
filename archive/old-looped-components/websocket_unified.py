"""
Unified WebSocket endpoint that consumes from Redis Streams.

This replaces the isolated WebSocket implementation with one that
integrates directly with the Redis Streams event bus for real-time updates.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends
from typing import List, Dict, Any, Set, Optional
import asyncio
import json
import logging
from datetime import datetime
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

router = APIRouter()


class UnifiedWebSocketManager:
    """
    Manages WebSocket connections and forwards Redis Stream events.
    
    This creates a bridge between Redis Streams (internal event bus)
    and WebSocket connections (client presentation layer).
    """
    
    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        self.active_connections: Dict[WebSocket, Set[str]] = {}
        self.consumer_tasks: Dict[WebSocket, asyncio.Task] = {}
        self.consumer_group = "websocket_consumers"
        
    async def connect(self, websocket: WebSocket, channels: List[str] = None):
        """Accept and track a new WebSocket connection with stream subscriptions."""
        await websocket.accept()
        
        # Track connection and subscriptions
        self.active_connections[websocket] = set(channels) if channels else set()
        
        # Send initial connection confirmation
        await websocket.send_json({
            "type": "connection",
            "status": "connected",
            "timestamp": datetime.now().isoformat(),
            "subscriptions": list(self.active_connections[websocket])
        })
        
        # Start consumer task for this connection
        if channels:
            await self._start_consumer(websocket, channels)
    
    async def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection and stop its consumer."""
        # Cancel consumer task
        if websocket in self.consumer_tasks:
            self.consumer_tasks[websocket].cancel()
            try:
                await self.consumer_tasks[websocket]
            except asyncio.CancelledError:
                pass
            del self.consumer_tasks[websocket]
        
        # Remove connection tracking
        if websocket in self.active_connections:
            del self.active_connections[websocket]
    
    async def subscribe(self, websocket: WebSocket, channels: List[str]):
        """Subscribe a connection to specific Redis Stream channels."""
        if websocket not in self.active_connections:
            return
        
        # Add new channels
        new_channels = set(channels) - self.active_connections[websocket]
        if new_channels:
            self.active_connections[websocket].update(new_channels)
            
            # Restart consumer with new channels
            await self._restart_consumer(websocket)
            
            await websocket.send_json({
                "type": "subscription",
                "action": "subscribed",
                "channels": list(self.active_connections[websocket]),
                "timestamp": datetime.now().isoformat()
            })
    
    async def unsubscribe(self, websocket: WebSocket, channels: List[str]):
        """Unsubscribe a connection from specific channels."""
        if websocket not in self.active_connections:
            return
        
        # Remove channels
        for channel in channels:
            self.active_connections[websocket].discard(channel)
        
        # Restart consumer without those channels
        if self.active_connections[websocket]:
            await self._restart_consumer(websocket)
        else:
            # No channels left, stop consumer
            if websocket in self.consumer_tasks:
                self.consumer_tasks[websocket].cancel()
                del self.consumer_tasks[websocket]
        
        await websocket.send_json({
            "type": "subscription",
            "action": "unsubscribed",
            "channels": list(self.active_connections[websocket]),
            "timestamp": datetime.now().isoformat()
        })
    
    async def _start_consumer(self, websocket: WebSocket, channels: List[str]):
        """Start a Redis Streams consumer for this WebSocket connection."""
        # Cancel existing consumer if any
        if websocket in self.consumer_tasks:
            self.consumer_tasks[websocket].cancel()
        
        # Create consumer ID unique to this connection
        consumer_id = f"ws_{id(websocket)}"
        
        # Start consumer task
        self.consumer_tasks[websocket] = asyncio.create_task(
            self._consume_streams(websocket, channels, consumer_id)
        )
    
    async def _restart_consumer(self, websocket: WebSocket):
        """Restart consumer with updated channels."""
        if websocket in self.active_connections:
            channels = list(self.active_connections[websocket])
            if channels:
                await self._start_consumer(websocket, channels)
    
    async def _consume_streams(self, websocket: WebSocket, channels: List[str], consumer_id: str):
        """
        Consume from Redis Streams and forward to WebSocket.
        
        This creates a direct bridge from internal event bus to client.
        """
        try:
            # Ensure consumer groups exist for each channel
            for channel in channels:
                stream_key = self._get_stream_key(channel)
                try:
                    await self.redis.xgroup_create(
                        stream_key,
                        self.consumer_group,
                        id="$",  # Start from new messages only
                        mkstream=True
                    )
                except Exception as e:
                    if "BUSYGROUP" not in str(e):
                        logger.warning(f"Could not create consumer group for {stream_key}: {e}")
            
            # NOTE: Changed from while loop to single batch consumption
            # This should be called periodically by the scheduler instead
            await self._consume_batch(websocket, channels, consumer_id)

        except Exception as e:
            logger.error(f"Fatal error in WebSocket consumer: {e}")
        finally:
            # Cleanup on exit
            logger.debug(f"WebSocket consumer {consumer_id} stopped")

    async def _consume_batch(self, websocket: WebSocket, channels: List[str], consumer_id: str):
        """Consume a single batch of messages from Redis Streams."""
        try:
            # Build streams dict for XREADGROUP
            streams = {self._get_stream_key(ch): ">" for ch in channels}

            if not streams:
                return

            # Read from streams with timeout
            messages = await self.redis.xreadgroup(
                self.consumer_group,
                consumer_id,
                streams,
                block=1000,  # 1 second timeout
                count=10
            )

            if not messages:
                return

            # Process and forward messages
            for stream_key, entries in messages:
                for msg_id, data in entries:
                    try:
                        # Extract channel from stream key
                        channel = self._get_channel_from_key(stream_key)

                        # Parse event data
                        event_data = self._parse_stream_data(data)

                        # Forward to WebSocket
                        await websocket.send_json({
                            "type": "event",
                            "channel": channel,
                            "data": event_data,
                            "message_id": msg_id,
                            "timestamp": datetime.now().isoformat()
                        })

                        # Acknowledge message
                        await self.redis.xack(stream_key, self.consumer_group, msg_id)

                    except Exception as e:
                        logger.error(f"Error processing stream message: {e}")

        except WebSocketDisconnect:
            raise
        except Exception as e:
            logger.error(f"Error in batch consumer: {e}")
    
    def _get_stream_key(self, channel: str) -> str:
        """Convert channel name to Redis Stream key."""
        # Match the key format used by StreamEventBus
        if channel.startswith("gleitzeit:events:stream:"):
            return channel
        return f"gleitzeit:events:stream:{channel}"
    
    def _get_channel_from_key(self, stream_key: str) -> str:
        """Extract channel name from stream key."""
        if isinstance(stream_key, bytes):
            stream_key = stream_key.decode()
        return stream_key.replace("gleitzeit:events:stream:", "")
    
    def _parse_stream_data(self, data: Dict[bytes, bytes]) -> Dict[str, Any]:
        """Parse Redis Stream data into JSON."""
        parsed = {}
        for key, value in data.items():
            if isinstance(key, bytes):
                key = key.decode()
            if isinstance(value, bytes):
                value = value.decode()
            
            # Try to parse JSON values
            if key in ("data", "metadata"):
                try:
                    parsed[key] = json.loads(value)
                except:
                    parsed[key] = value
            else:
                parsed[key] = value
        
        return parsed
    
    async def broadcast_to_channel(self, channel: str, message: Dict[str, Any]):
        """
        Broadcast a message to all WebSocket clients subscribed to a channel.
        
        This is used for server-initiated messages that don't come from Redis Streams.
        """
        disconnected = []
        
        for websocket, subscriptions in self.active_connections.items():
            if channel in subscriptions:
                try:
                    await websocket.send_json({
                        "type": "broadcast",
                        "channel": channel,
                        "data": message,
                        "timestamp": datetime.now().isoformat()
                    })
                except:
                    disconnected.append(websocket)
        
        # Clean up disconnected clients
        for ws in disconnected:
            await self.disconnect(ws)


# Global manager instance (will be initialized with Redis)
manager: Optional[UnifiedWebSocketManager] = None


async def get_redis_client():
    """Get Redis client from system manager or create one."""
    try:
        from ....system import get_system_manager
        system_manager = get_system_manager()
        if system_manager and hasattr(system_manager.persistence, 'redis'):
            return system_manager.persistence.redis
    except:
        pass
    
    # Fallback: create Redis client
    import redis.asyncio as redis
    return await redis.from_url("redis://localhost:6379")


@router.on_event("startup")
async def startup():
    """Initialize the WebSocket manager with Redis connection."""
    global manager
    redis_client = await get_redis_client()
    manager = UnifiedWebSocketManager(redis_client)
    logger.info("Unified WebSocket manager initialized with Redis Streams")


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    channels: Optional[str] = Query(None, description="Comma-separated list of channels to subscribe")
):
    """
    WebSocket endpoint for real-time event streaming.
    
    Clients can subscribe to specific channels to receive events from Redis Streams.
    
    Example channels:
    - "TASK_*" - All task events
    - "WORKFLOW_*" - All workflow events
    - "TASK_COMPLETED" - Specific event type
    - "logs" - Log streaming
    """
    global manager
    
    if not manager:
        await websocket.close(code=1011, reason="WebSocket manager not initialized")
        return
    
    # Parse channels
    channel_list = []
    if channels:
        channel_list = [ch.strip() for ch in channels.split(",")]
    
    # Connect with initial subscriptions
    await manager.connect(websocket, channel_list)
    
    try:
        # Handle incoming messages (event-driven, no loop)
        async for data in websocket.iter_json():
            message_type = data.get("type")

            if message_type == "subscribe":
                channels = data.get("channels", [])
                await manager.subscribe(websocket, channels)

            elif message_type == "unsubscribe":
                channels = data.get("channels", [])
                await manager.unsubscribe(websocket, channels)

            elif message_type == "ping":
                await websocket.send_json({
                    "type": "pong",
                    "timestamp": datetime.now().isoformat()
                })

            else:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Unknown message type: {message_type}",
                    "timestamp": datetime.now().isoformat()
                })
    
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await manager.disconnect(websocket)


@router.websocket("/ws/logs")
async def websocket_logs_endpoint(
    websocket: WebSocket,
    task_id: Optional[str] = Query(None),
    workflow_id: Optional[str] = Query(None),
    level: Optional[str] = Query(None)
):
    """
    Specialized WebSocket endpoint for log streaming.
    
    Automatically subscribes to appropriate log channels based on parameters.
    """
    global manager
    
    if not manager:
        await websocket.close(code=1011, reason="WebSocket manager not initialized")
        return
    
    # Build channel list based on parameters
    channels = []
    if task_id:
        channels.append(f"logs:task:{task_id}")
    if workflow_id:
        channels.append(f"logs:workflow:{workflow_id}")
    if not task_id and not workflow_id:
        channels.append("logs:all")
    
    # Add level filter as metadata
    await manager.connect(websocket, channels)
    
    try:
        # Keep connection alive (event-driven, no loop)
        async for data in websocket.iter_json():
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket logs error: {e}")
        await manager.disconnect(websocket)