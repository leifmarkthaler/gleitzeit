"""
Event Broadcaster Service for WebSocket Support

Subscribes to Redis Pub/Sub and broadcasts workflow/task events to WebSocket clients.
"""

import json
import asyncio
import logging
from typing import Set, Dict, List, Optional
from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Global broadcaster instance
_broadcaster: Optional['EventBroadcaster'] = None


class EventBroadcaster:
    """
    Subscribes to Redis Pub/Sub and broadcasts to WebSocket clients
    """

    def __init__(self, redis_url: str):
        """
        Initialize EventBroadcaster with redis_url.

        Creates its own dedicated Redis connection to avoid conflicts
        with the worker's connection.

        Args:
            redis_url: Redis connection URL (e.g., "redis://localhost:6379")
        """
        self.redis_url = redis_url
        self.redis = None  # Will be created in start()
        self.pubsub = None
        self.active_connections: Set[WebSocket] = set()
        self.subscription_filters: Dict[WebSocket, Set[str]] = {}
        self._listen_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        """Subscribe to Redis pub/sub channel"""
        import redis.asyncio as aioredis

        logger.info(f"Starting EventBroadcaster with redis_url={self.redis_url}")

        # Create dedicated Redis connection for pubsub
        # This avoids connection reuse issues with the worker's Redis instance
        self.redis = await aioredis.from_url(self.redis_url)
        logger.info("EventBroadcaster created dedicated Redis connection")

        # Create pubsub instance
        self.pubsub = self.redis.pubsub()
        logger.info("EventBroadcaster created pubsub instance")

        # Subscribe to gleitzeit events channel
        await self.pubsub.subscribe('gleitzeit:events')
        logger.info("EventBroadcaster subscribed to gleitzeit:events")

        # Start listening task
        self._running = True
        self._listen_task = asyncio.create_task(self._listen_to_redis())

        logger.info("EventBroadcaster started and listening to gleitzeit:events")

    async def stop(self):
        """Cleanup pub/sub subscription"""
        logger.info("Stopping EventBroadcaster...")

        self._running = False

        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

        if self.pubsub:
            await self.pubsub.unsubscribe('gleitzeit:events')
            await self.pubsub.close()

        # Close all active connections
        for websocket in list(self.active_connections):
            try:
                await websocket.close()
            except Exception as e:
                logger.error(f"Error closing WebSocket: {e}")

        self.active_connections.clear()
        self.subscription_filters.clear()

        logger.info("EventBroadcaster stopped")

    async def _listen_to_redis(self):
        """Background task to listen to Redis pub/sub"""
        try:
            while self._running:
                try:
                    message = await self.pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)

                    if message and message['type'] == 'message':
                        # Parse event data
                        event_data = json.loads(message['data'].decode() if isinstance(message['data'], bytes) else message['data'])

                        logger.debug(f"Received event from Redis: {event_data.get('event_type')}")

                        # Broadcast to connected clients
                        await self.broadcast_event(event_data)

                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Error processing Redis message: {e}")

        except asyncio.CancelledError:
            logger.info("Redis listener task cancelled")
        except Exception as e:
            logger.error(f"Fatal error in Redis listener: {e}")

    async def broadcast_event(self, event: dict):
        """Broadcast event to subscribed WebSocket clients"""
        if not self.active_connections:
            return

        disconnected = set()

        for websocket in self.active_connections:
            try:
                # Check if client has filters
                filters = self.subscription_filters.get(websocket, set())

                # If client has filters, check if event matches
                if filters:
                    workflow_id = event.get('workflow_id')
                    task_id = event.get('task_id')

                    # Only send if event matches filter
                    if not (workflow_id in filters or task_id in filters):
                        continue

                # Send event to client
                await websocket.send_json(event)

            except Exception as e:
                logger.error(f"Error sending event to WebSocket: {e}")
                disconnected.add(websocket)

        # Clean up disconnected clients
        for ws in disconnected:
            await self.remove_client(ws)

    async def add_client(self, websocket: WebSocket, filters: Optional[List[str]] = None):
        """Add WebSocket client with optional workflow/task filters"""
        self.active_connections.add(websocket)

        if filters:
            self.subscription_filters[websocket] = set(filters)
        else:
            self.subscription_filters[websocket] = set()

        logger.info(f"WebSocket client connected. Total: {len(self.active_connections)}, Filters: {filters or 'none'}")

    async def update_filters(self, websocket: WebSocket, filters: List[str]):
        """Update client subscription filters"""
        if websocket in self.active_connections:
            self.subscription_filters[websocket] = set(filters)
            logger.debug(f"Updated filters for WebSocket: {filters}")

    async def remove_client(self, websocket: WebSocket):
        """Remove WebSocket client"""
        self.active_connections.discard(websocket)
        self.subscription_filters.pop(websocket, None)
        logger.info(f"WebSocket client disconnected. Total: {len(self.active_connections)}")


def get_broadcaster() -> EventBroadcaster:
    """Get global broadcaster instance"""
    if _broadcaster is None:
        raise RuntimeError("EventBroadcaster not initialized. Call set_broadcaster() first.")
    return _broadcaster


def set_broadcaster(broadcaster: EventBroadcaster):
    """Set global broadcaster instance"""
    global _broadcaster
    _broadcaster = broadcaster
