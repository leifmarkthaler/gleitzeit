"""
Streamlined Event Bus for Gleitzeit

This is the ONLY event bus implementation. Uses StatelessStreamConsumer exclusively.
No loops, no duplicate pathways, just one clean stream processing system.
"""

import json
import logging
import asyncio
from typing import Dict, List, Callable, Optional, Any, Union
from datetime import datetime

from gleitzeit.core.events import GleitzeitEvent, EventType
from gleitzeit.events.stateless_stream_consumer import StatelessStreamConsumer

logger = logging.getLogger(__name__)


class StreamlinedEventBus:
    """
    The ONE event bus for Gleitzeit.

    Features:
    - Uses ONLY StatelessStreamConsumer
    - NO loops
    - NO duplicate consumers
    - Pure Redis Streams
    - Externally triggered processing
    """

    def __init__(self, redis_client, instance_id: Optional[str] = None):
        """
        Initialize the streamlined event bus.

        Args:
            redis_client: Redis client
            instance_id: Instance identifier
        """
        self.redis = redis_client
        self.instance_id = instance_id or "default"
        self.consumer_group = "gleitzeit-processors"  # Single unified consumer group

        # Handler registry - maps event types to handlers
        self._handlers: Dict[str, List[Callable]] = {}

        logger.info(f"StreamlinedEventBus initialized: {self.instance_id}")

    async def emit(self, event: Union[GleitzeitEvent, Dict[str, Any]]) -> str:
        """
        Emit an event to Redis Streams.

        Args:
            event: Event to emit

        Returns:
            Message ID from Redis
        """
        # Handle both GleitzeitEvent and dict
        if isinstance(event, dict):
            event_type = event.get("event_type", "unknown")
            event_data = event
        else:
            # Handle GleitzeitEvent objects
            if hasattr(event, 'event_type') and event.event_type:
                event_type = event.event_type.value if hasattr(event.event_type, 'value') else str(event.event_type)
            else:
                event_type = "unknown"

            # Handle timestamp carefully - it might be None
            timestamp = None
            if hasattr(event, 'timestamp') and event.timestamp:
                timestamp = event.timestamp.isoformat() if hasattr(event.timestamp, 'isoformat') else str(event.timestamp)
            else:
                timestamp = datetime.utcnow().isoformat()

            # Handle data - ensure it's serializable
            data = {}
            if hasattr(event, 'data') and event.data:
                data = event.data if isinstance(event.data, dict) else {"value": str(event.data)}

            # Build event data with safe conversions
            event_data = {}
            event_data["event_type"] = str(event_type) if event_type is not None else "unknown"
            event_data["timestamp"] = str(timestamp) if timestamp is not None else datetime.utcnow().isoformat()
            event_data["data"] = json.dumps(data)
            event_data["source"] = str(event.source) if hasattr(event, 'source') and event.source is not None else ""
            event_data["correlation_id"] = str(event.correlation_id) if hasattr(event, 'correlation_id') and event.correlation_id is not None else ""

            # Handle severity
            if hasattr(event, 'severity') and event.severity:
                event_data["severity"] = event.severity.value if hasattr(event.severity, 'value') else str(event.severity)
            else:
                event_data["severity"] = "INFO"

            # Handle metadata/tags
            metadata = {}
            if hasattr(event, 'tags') and event.tags:
                metadata = event.tags if isinstance(event.tags, dict) else {}
            event_data["metadata"] = json.dumps(metadata)

        # Get stream key
        stream_key = f"gleitzeit:events:stream:{event_type.replace('_', ':').lower()}"

        # Ensure consumer group exists for this stream (auto-create on first emit)
        try:
            await self.redis.xgroup_create(
                stream_key,
                self.consumer_group,
                id='0',  # Start from beginning
                mkstream=True  # Create stream if it doesn't exist
            )
            logger.debug(f"Created consumer group {self.consumer_group} for {stream_key}")
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                logger.debug(f"Consumer group already exists for {stream_key}")

        # Add to stream
        msg_id = await self.redis.xadd(stream_key, event_data)

        logger.debug(f"Emitted {event_type} to {stream_key}: {msg_id}")

        return msg_id

    def register_handler(self, event_type: Union[str, EventType], handler: Callable):
        """
        Register a handler for an event type.

        Args:
            event_type: Type of event to handle
            handler: Handler function
        """
        # Normalize event type
        if isinstance(event_type, EventType):
            event_type = event_type.value

        # Convert to stream format (e.g., TASK_READY -> task:ready)
        normalized_type = event_type.lower().replace('_', ':')

        if normalized_type not in self._handlers:
            self._handlers[normalized_type] = []

        if handler not in self._handlers[normalized_type]:
            self._handlers[normalized_type].append(handler)
            logger.info(f"Registered handler for {normalized_type}")

    def unregister_handler(self, event_type: Union[str, EventType], handler: Callable):
        """
        Unregister a handler.

        Args:
            event_type: Type of event
            handler: Handler to remove
        """
        if isinstance(event_type, EventType):
            event_type = event_type.value

        normalized_type = event_type.lower().replace('_', ':')

        if normalized_type in self._handlers:
            if handler in self._handlers[normalized_type]:
                self._handlers[normalized_type].remove(handler)
                logger.info(f"Unregistered handler for {normalized_type}")

    # Compatibility methods for old API
    def register(self, event_type: Union[str, EventType], handler: Callable):
        """Compatibility method - calls register_handler."""
        return self.register_handler(event_type, handler)

    def unregister(self, event_type: Union[str, EventType], handler: Callable):
        """Compatibility method - calls unregister_handler."""
        return self.unregister_handler(event_type, handler)

    async def process_once(self) -> Dict[str, Any]:
        """
        Process events once using StatelessStreamConsumer.

        Returns:
            Processing statistics
        """
        stats = {
            "processed": 0,
            "errors": 0,
            "by_type": {}
        }

        try:
            # Process a batch of messages using StatelessStreamConsumer
            processed, messages = await StatelessStreamConsumer.process_message_batch(
                self.redis,
                self.consumer_group,
                self.instance_id,
                max_messages=100
            )

            stats["processed"] = processed

            # Process each message through handlers
            for stream_key, msg_id, event_data in messages:
                event_type = event_data.get("event_type", "")

                # Track by type
                if event_type not in stats["by_type"]:
                    stats["by_type"][event_type] = 0
                stats["by_type"][event_type] += 1

                # Get handlers for this event type
                handlers = self._handlers.get(event_type, [])

                if handlers:
                    # Create event object
                    event = self._decode_event(event_data)

                    # Call all handlers
                    for handler in handlers:
                        try:
                            if asyncio.iscoroutinefunction(handler):
                                await handler(event)
                            else:
                                handler(event)
                        except Exception as e:
                            logger.error(f"Handler error for {event_type}: {e}")
                            stats["errors"] += 1

        except Exception as e:
            logger.error(f"Error processing events: {e}")
            stats["errors"] += 1

        return stats

    def _decode_event(self, data: Dict) -> GleitzeitEvent:
        """
        Decode stream data into an event object.

        Args:
            data: Stream message data

        Returns:
            GleitzeitEvent object
        """
        # Parse JSON data
        event_data = {}
        if data.get('data'):
            try:
                event_data = json.loads(data['data'])
            except json.JSONDecodeError:
                event_data = {'raw': data.get('data')}

        # Parse metadata
        metadata = {}
        if data.get('metadata'):
            try:
                metadata = json.loads(data['metadata'])
            except json.JSONDecodeError:
                pass

        # Create event
        return GleitzeitEvent(
            event_type=EventType(data.get('event_type')) if data.get('event_type') else None,
            data=event_data,
            timestamp=datetime.fromisoformat(
                data.get('timestamp', datetime.utcnow().isoformat())
            ),
            source=data.get('source', ''),
            correlation_id=data.get('correlation_id', ''),
            tags=metadata
        )

    async def ensure_consumer_groups(self):
        """
        Ensure consumer groups exist for all streams.
        """
        # Get all streams
        streams = await StatelessStreamConsumer.get_all_streams(self.redis)

        # Create consumer groups
        for stream in streams:
            try:
                await self.redis.xgroup_create(
                    stream,
                    self.consumer_group,
                    id='0',  # Start from beginning
                    mkstream=True
                )
                logger.debug(f"Created consumer group for {stream}")
            except Exception as e:
                if "BUSYGROUP" not in str(e):
                    logger.error(f"Error creating consumer group for {stream}: {e}")

    async def get_statistics(self) -> Dict[str, Any]:
        """
        Get event bus statistics.

        Returns:
            Statistics dictionary
        """
        # Get stream info
        streams = await StatelessStreamConsumer.get_all_streams(self.redis)
        pending = await StatelessStreamConsumer.get_pending_info(self.redis)

        return {
            "instance_id": self.instance_id,
            "consumer_group": self.consumer_group,
            "total_streams": len(streams),
            "streams_with_pending": len(pending),
            "total_pending": sum(pending.values()),
            "registered_handlers": {k: len(v) for k, v in self._handlers.items()},
            "stateless": True,
            "has_loops": False
        }