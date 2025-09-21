"""
Triggered Stream Consumer for Gleitzeit

A truly stateless consumer that processes messages only when triggered
via Redis. No internal loops - consumption is driven entirely by
external triggers through Redis Streams.
"""

import asyncio
import json
import logging
import uuid
from typing import Dict, List, Any, Callable, Optional, Set
from datetime import datetime

from gleitzeit.core.events import GleitzeitEvent, EventType

logger = logging.getLogger(__name__)


class TriggeredStreamConsumer:
    """
    Stateless stream consumer triggered via Redis.

    Features:
    - No internal loops
    - Triggered via Redis Stream events
    - Processes messages on-demand
    - Truly stateless operation
    """

    TRIGGER_STREAM = "gleitzeit:consumer:triggers"
    TRIGGER_GROUP = "consumer-triggers"

    def __init__(
        self,
        redis=None,
        persistence=None,
        event_bus=None,
        handlers_registry: Optional[Dict[str, List[Callable]]] = None,
        consumer_group: str = "gleitzeit-processors",
        consumer_id: Optional[str] = None,
        instance_id: Optional[str] = None
    ):
        """
        Initialize the triggered consumer.

        Args:
            redis: Redis client (direct)
            persistence: Persistence adapter with redis attribute
            event_bus: Event bus for emitting events
            handlers_registry: Dict mapping event types to handler functions
            consumer_group: Consumer group name
            consumer_id: Unique consumer ID (auto-generated if not provided)
            instance_id: Instance ID for this consumer
        """
        # Get redis from persistence if not directly provided
        if redis:
            self.redis = redis
        elif persistence and hasattr(persistence, 'redis'):
            self.redis = persistence.redis
        else:
            raise ValueError("Either redis or persistence with redis attribute required")

        self.event_bus = event_bus
        self.handlers = handlers_registry or {}
        self.consumer_group = consumer_group
        self.consumer_id = consumer_id or f"consumer-{uuid.uuid4().hex[:8]}"
        self.instance_id = instance_id or f"instance-{uuid.uuid4().hex[:8]}"

        # Track discovered streams
        self._streams_cache: Set[str] = set()
        self._last_discovery = None

        logger.info(
            f"Initialized TriggeredStreamConsumer "
            f"(group: {consumer_group}, id: {self.consumer_id})"
        )

    async def setup_trigger_stream(self):
        """Set up the trigger stream and consumer group."""
        try:
            # Create trigger stream if it doesn't exist
            await self.redis.xadd(
                self.TRIGGER_STREAM,
                {"action": "init", "timestamp": datetime.utcnow().isoformat()},
                maxlen=1000  # Keep last 1000 triggers
            )

            # Create consumer group for triggers
            await self.redis.xgroup_create(
                self.TRIGGER_STREAM,
                self.TRIGGER_GROUP,
                id='0',
                mkstream=True
            )
            logger.info(f"Created trigger consumer group: {self.TRIGGER_GROUP}")
        except Exception as e:
            if "BUSYGROUP" in str(e):
                logger.debug("Trigger consumer group already exists")
            else:
                logger.error(f"Error setting up trigger stream: {e}")

    async def wait_for_trigger(self, timeout_ms: int = 0) -> Optional[Dict]:
        """
        Wait for a consumption trigger via Redis.

        Args:
            timeout_ms: Timeout in milliseconds (0 = block indefinitely)

        Returns:
            Trigger data if received, None on timeout
        """
        try:
            # Block waiting for trigger
            messages = await self.redis.xreadgroup(
                self.TRIGGER_GROUP,
                self.consumer_id,
                {self.TRIGGER_STREAM: '>'},
                count=1,
                block=timeout_ms
            )

            if messages:
                stream_key, stream_messages = messages[0]
                if stream_messages:
                    msg_id, data = stream_messages[0]

                    # Acknowledge trigger
                    await self.redis.xack(self.TRIGGER_STREAM, self.TRIGGER_GROUP, msg_id)

                    # Decode data
                    decoded_data = {}
                    for key, value in data.items():
                        if isinstance(key, bytes):
                            key = key.decode('utf-8')
                        if isinstance(value, bytes):
                            value = value.decode('utf-8')
                        decoded_data[key] = value

                    logger.debug(f"Received trigger: {decoded_data.get('action', 'unknown')}")
                    return decoded_data

            return None

        except Exception as e:
            logger.error(f"Error waiting for trigger: {e}")
            return None

    async def trigger_consumption(self, action: str = "consume", metadata: Optional[Dict] = None):
        """
        Send a trigger to consume messages.

        This can be called by any component to trigger consumption.

        Args:
            action: Trigger action (consume, discover, cleanup, etc.)
            metadata: Additional trigger metadata
        """
        trigger_data = {
            "action": action,
            "timestamp": datetime.utcnow().isoformat(),
            "source": self.instance_id
        }

        if metadata:
            trigger_data.update(metadata)

        # Add trigger to stream
        await self.redis.xadd(self.TRIGGER_STREAM, trigger_data)
        logger.debug(f"Sent trigger: {action}")

    async def consume_once(self, max_messages: int = 100) -> int:
        """
        Consume messages once (no loop).

        Args:
            max_messages: Maximum messages to process

        Returns:
            Number of messages processed
        """
        processed = 0

        # Discover streams if needed
        if not self._streams_cache:
            await self.discover_streams()

        if not self._streams_cache:
            logger.debug("No streams to consume")
            return 0

        try:
            # First, try to read any pending messages (messages added before consumer group creation)
            # Use '0' to read from the beginning of pending messages
            streams_dict = {stream: '0' for stream in self._streams_cache}

            # Try pending messages first
            messages = await self.redis.xreadgroup(
                self.consumer_group,
                self.consumer_id,
                streams_dict,
                count=max_messages,
                block=None  # Non-blocking!
            )

            # If no pending messages, try new messages
            if not messages:
                streams_dict = {stream: '>' for stream in self._streams_cache}
                messages = await self.redis.xreadgroup(
                    self.consumer_group,
                    self.consumer_id,
                    streams_dict,
                    count=max_messages,
                    block=None  # Non-blocking!
                )

            if messages:
                for stream_key, stream_messages in messages:
                    for msg_id, data in stream_messages:
                        success = await self.handle_message(stream_key, msg_id, data)
                        if success:
                            processed += 1

            if processed > 0:
                logger.info(f"Processed {processed} messages")

        except Exception as e:
            logger.error(f"Error consuming messages: {e}")

        return processed

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

                for key in keys:
                    if isinstance(key, bytes):
                        key = key.decode()
                    # Filter out internal/meta streams and the trigger stream
                    if (not key.endswith(':internal') and
                        not key.endswith(':meta') and
                        key != self.TRIGGER_STREAM):
                        streams.append(key)

                if cursor == 0:
                    break

            self._streams_cache = set(streams)
            self._last_discovery = datetime.utcnow()

            logger.debug(f"Discovered {len(streams)} streams")

        except Exception as e:
            logger.error(f"Error discovering streams: {e}")

        return streams

    async def ensure_consumer_groups(self):
        """Ensure consumer groups exist for all streams."""
        for stream in self._streams_cache:
            try:
                # Create consumer group starting from beginning ('0')
                # This ensures we can read ALL messages, not just new ones
                await self.redis.xgroup_create(
                    stream,
                    self.consumer_group,
                    id='0',  # Start from beginning to catch all messages
                    mkstream=True
                )
                logger.debug(f"Created consumer group for {stream}")
            except Exception as e:
                if "BUSYGROUP" not in str(e):
                    logger.error(f"Error creating consumer group for {stream}: {e}")

    async def handle_message(self, stream_key: str, msg_id: str, data: Dict) -> bool:
        """
        Process a single message from a stream.

        Args:
            stream_key: Stream the message came from
            msg_id: Message ID
            data: Message data

        Returns:
            True if successfully processed
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

            logger.debug(f"Processing event {event_type} from {stream_key}")

            # Create event object
            event = self.decode_event(decoded_data)

            # Emit event through event bus if available
            if self.event_bus:
                try:
                    await self.event_bus.emit(event)
                    success = True
                except Exception as e:
                    logger.error(f"Error emitting event through event bus: {e}")
                    success = False
            else:
                # Fall back to local handlers
                handlers = self.handlers.get(event_type, [])

                if not handlers:
                    logger.debug(f"No handlers for event type: {event_type}")
                    # Don't acknowledge - leave for when handler is registered
                    return False

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

            return success

        except Exception as e:
            logger.error(f"Error handling message: {e}")
            return False

    def decode_event(self, data: Dict) -> GleitzeitEvent:
        """Decode stream data into an event object."""
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

    def register_handler(self, event_type: str, handler: Callable):
        """Register a handler for an event type."""
        if event_type not in self.handlers:
            self.handlers[event_type] = []

        if handler not in self.handlers[event_type]:
            self.handlers[event_type].append(handler)
            logger.debug(f"Registered handler for {event_type}")

    async def process_with_trigger(self):
        """
        Process messages when triggered.

        This is the main entry point for triggered consumption.
        Waits for a trigger, then processes available messages.
        """
        # Wait for trigger
        trigger = await self.wait_for_trigger()

        if not trigger:
            return 0

        action = trigger.get('action', 'consume')

        if action == 'consume':
            # Process available messages
            return await self.consume_once()
        elif action == 'discover':
            # Rediscover streams
            await self.discover_streams()
            await self.ensure_consumer_groups()
            return 0
        elif action == 'shutdown':
            # Shutdown signal
            logger.info("Received shutdown trigger")
            return -1
        else:
            logger.debug(f"Unknown trigger action: {action}")
            return 0

    async def auto_trigger_on_stream_activity(self):
        """
        Automatically trigger consumption when new messages arrive in streams.

        This can be called periodically or by an external scheduler.
        """
        # Check if any streams have pending messages
        has_messages = False

        for stream in self._streams_cache:
            try:
                # Check pending messages for this consumer group
                info = await self.redis.xpending(stream, self.consumer_group)
                if info and info[0] > 0:  # Has pending messages
                    has_messages = True
                    break

                # Check for new messages
                last_id = await self.redis.xinfo_groups(stream)
                for group in last_id:
                    if group['name'] == self.consumer_group:
                        if group.get('lag', 0) > 0:
                            has_messages = True
                            break

            except Exception as e:
                logger.error(f"Error checking stream {stream}: {e}")

        if has_messages:
            # Trigger consumption
            await self.trigger_consumption("consume", {"reason": "messages_available"})
            return True

        return False