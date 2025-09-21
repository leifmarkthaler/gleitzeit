"""
Multiplexed Stream Consumer for Gleitzeit

A scalable consumer that monitors all event-type-specific streams
using a single Redis XREADGROUP call. No polling loops - uses
Redis blocking operations.
"""

import asyncio
import json
import logging
import uuid
from typing import Dict, List, Any, Callable, Optional
from datetime import datetime

from gleitzeit.core.events import GleitzeitEvent, EventType

logger = logging.getLogger(__name__)


class MultiplexedStreamConsumer:
    """
    Scalable stream consumer using Redis XREADGROUP.

    Features:
    - Single consumer monitoring all event streams
    - Uses blocking XREADGROUP for efficiency
    - Routes events to registered handlers
    - Handles acknowledgments and error recovery
    """

    def __init__(
        self,
        redis,
        handlers_registry: Optional[Dict[str, List[Callable]]] = None,
        consumer_group: str = "gleitzeit-processors",
        consumer_id: Optional[str] = None
    ):
        """
        Initialize the multiplexed consumer.

        Args:
            redis: Redis client
            handlers_registry: Dict mapping event types to handler functions
            consumer_group: Consumer group name
            consumer_id: Unique consumer ID (auto-generated if not provided)
        """
        self.redis = redis
        self.handlers = handlers_registry or {}
        self.consumer_group = consumer_group
        self.consumer_id = consumer_id or f"consumer-{uuid.uuid4().hex[:8]}"
        self.running = False
        self.streams = []
        self._consumer_task = None

        logger.info(
            f"Initialized MultiplexedStreamConsumer "
            f"(group: {consumer_group}, id: {self.consumer_id})"
        )

    async def start(self):
        """Start the consumer."""
        if self.running:
            logger.warning("Consumer already running")
            return

        self.running = True

        # Discover all event streams
        self.streams = await self.discover_streams()
        logger.info(f"Discovered {len(self.streams)} event streams")

        # Ensure consumer groups exist
        for stream in self.streams:
            await self.ensure_consumer_group(stream)

        # Start consuming
        self._consumer_task = asyncio.create_task(self.consume_streams())
        logger.info("MultiplexedStreamConsumer started")

    async def stop(self):
        """Stop the consumer."""
        self.running = False

        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass

        logger.info("MultiplexedStreamConsumer stopped")

    async def discover_streams(self) -> List[str]:
        """
        Discover all event-type streams dynamically.

        Returns:
            List of stream keys
        """
        pattern = "gleitzeit:events:stream:*"
        streams = []
        cursor = 0

        try:
            while True:
                cursor, keys = await self.redis.scan(
                    cursor, match=pattern, count=100
                )
                # Filter out any internal or meta streams
                for key in keys:
                    if isinstance(key, bytes):
                        key = key.decode()
                    if not key.endswith(':internal') and not key.endswith(':meta'):
                        streams.append(key)

                if cursor == 0:
                    break

        except Exception as e:
            logger.error(f"Error discovering streams: {e}")

        return streams

    async def ensure_consumer_group(self, stream_key: str):
        """
        Ensure consumer group exists for a stream.

        Args:
            stream_key: Stream key
        """
        try:
            # Try to create consumer group
            await self.redis.xgroup_create(
                stream_key,
                self.consumer_group,
                id='0',
                mkstream=True
            )
            logger.debug(f"Created consumer group {self.consumer_group} for {stream_key}")
        except Exception as e:
            if "BUSYGROUP" in str(e):
                # Group already exists
                logger.debug(f"Consumer group {self.consumer_group} already exists for {stream_key}")
            else:
                logger.error(f"Error creating consumer group for {stream_key}: {e}")

    async def consume_streams(self):
        """
        Main consumption loop using blocking XREADGROUP.

        This is the only loop in the system - it blocks on Redis
        and wakes up when messages arrive.
        """
        logger.info(f"Starting stream consumption for {len(self.streams)} streams")

        while self.running:
            try:
                if not self.streams:
                    # No streams to consume, wait and retry discovery
                    await asyncio.sleep(5)
                    self.streams = await self.discover_streams()
                    continue

                # Build streams dict for XREADGROUP
                # '>' means get new messages for this consumer
                streams_dict = {stream: '>' for stream in self.streams}

                # Single call monitors ALL streams (blocking)
                # This blocks until ANY stream has messages
                messages = await self.redis.xreadgroup(
                    self.consumer_group,
                    self.consumer_id,
                    streams_dict,
                    count=100,  # Process up to 100 messages per batch
                    block=0     # Block indefinitely (no polling!)
                )

                # Process messages
                if messages:
                    for stream_key, stream_messages in messages:
                        for msg_id, data in stream_messages:
                            await self.handle_message(stream_key, msg_id, data)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in consume_streams: {e}")
                # Brief pause before retry
                await asyncio.sleep(1)

        logger.info("Stream consumption stopped")

    async def handle_message(self, stream_key: str, msg_id: str, data: Dict):
        """
        Process a single message from a stream.

        Args:
            stream_key: Stream the message came from
            msg_id: Message ID
            data: Message data
        """
        try:
            # Decode data if needed
            decoded_data = {}
            for key, value in data.items():
                if isinstance(key, bytes):
                    key = key.decode('utf-8')
                if isinstance(value, bytes):
                    value = value.decode('utf-8')
                decoded_data[key] = value

            # Extract event type
            event_type = decoded_data.get('event_type', '')

            logger.debug(f"Processing event {event_type} from {stream_key} (id: {msg_id})")

            # Create event object
            event = self.decode_event(decoded_data)

            # Get handlers for this event type
            handlers = self.handlers.get(event_type, [])

            if not handlers:
                logger.debug(f"No handlers registered for event type: {event_type}. Available handlers: {list(self.handlers.keys())}")
                # DON'T acknowledge - leave in pending for when handler is registered
                return

            # Invoke all handlers
            success = True
            for handler in handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(event)
                    else:
                        handler(event)
                except Exception as e:
                    logger.error(f"Handler error for {event_type}: {e}")
                    success = False

            # Only acknowledge if successfully processed
            if success:
                await self.redis.xack(stream_key, self.consumer_group, msg_id)
            else:
                logger.warning(f"Not acknowledging message {msg_id} due to handler errors")

        except Exception as e:
            logger.error(f"Error handling message {msg_id} from {stream_key}: {e}")
            # Don't acknowledge on error - message will be redelivered

    def decode_event(self, data: Dict) -> GleitzeitEvent:
        """
        Decode event data into GleitzeitEvent object.

        Args:
            data: Raw event data

        Returns:
            GleitzeitEvent object
        """
        # Parse event data
        event_data = {}
        if 'data' in data:
            try:
                event_data = json.loads(data['data'])
            except:
                event_data = data.get('data', {})

        # Create event object
        return GleitzeitEvent(
            event_type=EventType(data.get('event_type', '')) if data.get('event_type') else None,
            data=event_data,
            timestamp=datetime.fromisoformat(
                data.get('timestamp', datetime.utcnow().isoformat())
            ),
            source=data.get('source', ''),
            correlation_id=data.get('correlation_id', '')
        )

    def register_handler(self, event_type: str, handler: Callable):
        """
        Register a handler for an event type.

        Args:
            event_type: Event type to handle
            handler: Handler function
        """
        if event_type not in self.handlers:
            self.handlers[event_type] = []

        # Check if handler is already registered to avoid duplicates
        if handler not in self.handlers[event_type]:
            self.handlers[event_type].append(handler)
            logger.info(f"Registered handler for event type: {event_type}")
        else:
            logger.debug(f"Handler already registered for event type: {event_type}")

        # Process any pending messages for this event type
        if self.running:
            asyncio.create_task(self._process_pending_for_type(event_type))

    def unregister_handler(self, event_type: str, handler: Callable):
        """
        Unregister a handler for an event type.

        Args:
            event_type: Event type
            handler: Handler function to remove
        """
        if event_type in self.handlers:
            if handler in self.handlers[event_type]:
                self.handlers[event_type].remove(handler)
                logger.info(f"Unregistered handler for event type: {event_type}")

    async def _process_pending_for_type(self, event_type: str):
        """
        Process any pending messages for a specific event type.
        This is called when a handler is registered to catch up on missed messages.

        Args:
            event_type: Event type to process pending messages for
        """
        # Map event type to stream key
        stream_key = f"gleitzeit:events:stream:{event_type.replace(':', '_')}"

        try:
            # Check for pending messages for this consumer
            pending_info = await self.redis.xpending_range(
                stream_key,
                self.consumer_group,
                min='-',
                max='+',
                count=100
            )

            if pending_info:
                logger.info(f"Processing {len(pending_info)} pending {event_type} messages")

                for entry in pending_info:
                    msg_id = entry['message_id']
                    try:
                        # Claim and process the message
                        claimed = await self.redis.xclaim(
                            stream_key,
                            self.consumer_group,
                            self.consumer_id,
                            min_idle_time=0,
                            message_ids=[msg_id]
                        )

                        if claimed:
                            for claimed_msg_id, data in claimed:
                                await self.handle_message(stream_key, claimed_msg_id, data)

                    except Exception as e:
                        logger.error(f"Error claiming pending message {msg_id}: {e}")

        except Exception as e:
            # Stream might not exist yet, that's okay
            if "no such key" not in str(e).lower():
                logger.error(f"Error processing pending messages for {event_type}: {e}")

    async def get_statistics(self) -> Dict[str, Any]:
        """
        Get consumer statistics.

        Returns:
            Statistics dictionary
        """
        stats = {
            "consumer_id": self.consumer_id,
            "consumer_group": self.consumer_group,
            "running": self.running,
            "streams_monitored": len(self.streams),
            "handlers_registered": sum(len(h) for h in self.handlers.values()),
            "pending_messages": {}
        }

        # Get pending messages for each stream
        if self.running:
            for stream in self.streams:
                try:
                    info = await self.redis.xpending(stream, self.consumer_group)
                    stats["pending_messages"][stream] = info.get('pending', 0)
                except:
                    pass

        return stats