"""
Stateless Event Consumer for Horizontal Scaling.

This module provides a truly stateless event consumer that:
- Has no persistent loops
- Can be triggered externally
- Supports multiple instances without collision
- Integrates with idempotency framework
- Uses consumer lifecycle management
"""

import asyncio
import logging
import json
import uuid
from typing import Dict, Set, Callable, Optional, Any, List
from datetime import datetime
from contextlib import asynccontextmanager

from gleitzeit.core.events import GleitzeitEvent, EventType
from gleitzeit.core.idempotency import (
    IdempotencyManager,
    IdempotencyStrategy,
    IdempotencyKey
)
from gleitzeit.events.consumer_lifecycle import ConsumerLifecycle

logger = logging.getLogger(__name__)


class StatelessEventConsumer:
    """
    Stateless event consumer that processes messages on-demand.

    Key differences from StreamEventBus:
    - NO persistent loops (no while self._running)
    - Processes messages on explicit trigger
    - Integrates idempotency checks
    - Uses consumer lifecycle management
    - Instance-specific consumer groups
    """

    def __init__(
        self,
        redis_client,
        instance_id: Optional[str] = None,
        consumer_group_prefix: str = "gleitzeit",
        idempotency_manager: Optional[IdempotencyManager] = None
    ):
        """
        Initialize stateless consumer.

        Args:
            redis_client: Redis connection
            instance_id: Unique instance identifier
            consumer_group_prefix: Prefix for consumer group names
            idempotency_manager: Optional idempotency manager
        """
        self.redis = redis_client
        self.instance_id = instance_id or f"instance_{uuid.uuid4().hex[:8]}"

        # Instance-specific consumer group to prevent collision
        self.consumer_group = f"{consumer_group_prefix}-{self.instance_id}"
        self.consumer_id = f"consumer_{uuid.uuid4().hex[:8]}"

        # Handlers registry
        self._handlers: Dict[str, List[Callable]] = {}

        # Consumer lifecycle management
        self.lifecycle = ConsumerLifecycle(
            redis=redis_client,
            consumer_group=self.consumer_group
        )

        # Idempotency management
        self.idempotency = idempotency_manager or IdempotencyManager(
            redis=redis_client
        )

        # Track registered streams
        self._registered_streams: Set[str] = set()

        logger.info(
            f"Initialized stateless consumer: "
            f"instance={self.instance_id}, "
            f"group={self.consumer_group}, "
            f"consumer={self.consumer_id}"
        )

    def _get_stream_key(self, event_type: str) -> str:
        """Get Redis stream key for event type."""
        # Normalize event type
        if not event_type.startswith("gleitzeit:events:stream:"):
            event_type = event_type.replace(".", ":")
            if not event_type.startswith("gleitzeit:"):
                event_type = f"gleitzeit:events:stream:{event_type}"
        return event_type

    async def register_handler(
        self,
        event_type: str,
        handler: Callable,
        idempotency_strategy: IdempotencyStrategy = IdempotencyStrategy.CHECK_STATE
    ):
        """
        Register event handler with idempotency strategy.

        Args:
            event_type: Event type to handle
            handler: Handler function
            idempotency_strategy: How to check idempotency
        """
        stream_key = self._get_stream_key(event_type)

        # Store handler with metadata
        if stream_key not in self._handlers:
            self._handlers[stream_key] = []

        # Create handler wrapper to store idempotency strategy
        # (can't set attributes on bound methods)
        handler_info = {
            'handler': handler,
            'idempotency_strategy': idempotency_strategy
        }
        self._handlers[stream_key].append(handler_info)

        # Create consumer group if needed
        if stream_key not in self._registered_streams:
            await self._ensure_consumer_group(stream_key)
            self._registered_streams.add(stream_key)

        logger.info(
            f"Registered handler for {event_type} "
            f"with strategy {idempotency_strategy.value}"
        )

    async def _ensure_consumer_group(self, stream_key: str):
        """Ensure consumer group exists for stream."""
        try:
            # Try to create consumer group
            await self.redis.xgroup_create(
                stream_key,
                self.consumer_group,
                id='0',
                mkstream=True
            )
            logger.info(f"Created consumer group {self.consumer_group} for {stream_key}")
        except Exception as e:
            if "BUSYGROUP" in str(e):
                # Group already exists
                logger.debug(f"Consumer group {self.consumer_group} already exists")
            else:
                logger.error(f"Error creating consumer group: {e}")

    async def initialize(self):
        """
        Initialize consumer with lifecycle management.

        This should be called once when the consumer starts.
        """
        # Register consumer with TTL
        await self.lifecycle.register_consumer(self.consumer_id)

        # Start heartbeat to keep consumer alive
        await self.lifecycle.start_heartbeat_loop()

        logger.info(f"Consumer {self.consumer_id} initialized with lifecycle management")

    async def shutdown(self):
        """
        Shutdown consumer cleanly.

        This should be called when the consumer stops.
        """
        # Stop heartbeat
        await self.lifecycle.stop_heartbeat_loop()

        # Unregister consumer
        await self.lifecycle.unregister_consumer()

        logger.info(f"Consumer {self.consumer_id} shutdown complete")

    async def process_batch(
        self,
        max_messages: int = 100,
        block_ms: int = 0
    ) -> int:
        """
        Process a batch of messages (stateless, single execution).

        This is the main entry point for processing. It:
        1. Reads available messages
        2. Checks idempotency
        3. Processes if safe
        4. Acknowledges completion

        Args:
            max_messages: Maximum messages to process
            block_ms: How long to wait for messages (0 = don't wait)

        Returns:
            Number of messages processed
        """
        if not self._handlers:
            logger.debug("No handlers registered")
            return 0

        processed_count = 0

        # Prepare streams for reading
        streams = {stream: '>' for stream in self._handlers.keys()}

        try:
            # Read messages from streams (NO LOOP!)
            messages = await self.redis.xreadgroup(
                self.consumer_group,
                self.consumer_id,
                streams,
                count=max_messages,
                block=block_ms
            )

            if not messages:
                return 0

            # Process each message
            for stream_key, stream_messages in messages:
                for msg_id, data in stream_messages:
                    try:
                        # Process single message
                        success = await self._process_message(
                            stream_key,
                            msg_id,
                            data
                        )

                        if success:
                            # Acknowledge processed message
                            await self.redis.xack(
                                stream_key,
                                self.consumer_group,
                                msg_id
                            )
                            processed_count += 1

                    except Exception as e:
                        logger.error(
                            f"Error processing message {msg_id} "
                            f"from {stream_key}: {e}"
                        )

        except Exception as e:
            logger.error(f"Error reading messages: {e}")

        return processed_count

    async def _process_message(
        self,
        stream_key: str,
        msg_id: str,
        data: Dict
    ) -> bool:
        """
        Process a single message with idempotency check.

        Args:
            stream_key: Stream the message came from
            msg_id: Message ID
            data: Message data

        Returns:
            True if processed successfully
        """
        # Decode data if needed
        decoded_data = {}
        for key, value in data.items():
            if isinstance(key, bytes):
                key = key.decode('utf-8')
            if isinstance(value, bytes):
                value = value.decode('utf-8')
            decoded_data[key] = value

        # Extract event data
        event_type = decoded_data.get('event_type', '')
        event_data = json.loads(decoded_data.get('data', '{}'))

        # Create unique task ID for idempotency
        task_id = f"{stream_key}:{msg_id}"

        # Get handlers for this stream
        handlers = self._handlers.get(stream_key, [])

        if not handlers:
            logger.warning(f"No handlers for {stream_key}")
            return False

        success = True

        for handler_info in handlers:
            try:
                # Extract handler and strategy from info dict
                if isinstance(handler_info, dict):
                    handler = handler_info['handler']
                    strategy = handler_info.get('idempotency_strategy', IdempotencyStrategy.CHECK_STATE)
                else:
                    # Fallback for old-style handlers
                    handler = handler_info
                    strategy = IdempotencyStrategy.CHECK_STATE

                # Get handler name for logging
                handler_name = getattr(handler, '__name__', str(handler))

                # Check if we can execute
                can_execute, reason = await self.idempotency.check_can_execute(
                    task_id=f"{task_id}:{handler_name}",
                    strategy=strategy,
                    params=event_data
                )

                if not can_execute:
                    logger.info(
                        f"Skipping handler {handler_name} "
                        f"for {task_id}: {reason}"
                    )
                    continue

                # Record execution start
                idempotency_key = await self.idempotency.record_execution_start(
                    task_id=f"{task_id}:{handler_name}",
                    params=event_data
                )

                # Create event object
                event = GleitzeitEvent(
                    event_type=EventType(event_type) if event_type else None,
                    data=event_data,
                    timestamp=datetime.fromisoformat(
                        decoded_data.get('timestamp', datetime.utcnow().isoformat())
                    ),
                    source=decoded_data.get('source', ''),
                    correlation_id=decoded_data.get('correlation_id', '')
                )

                # Execute handler
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)

                # Record successful completion
                await self.idempotency.record_execution_complete(
                    idempotency_key=idempotency_key
                )

                logger.debug(
                    f"Handler {handler.__name__} completed "
                    f"for {task_id}"
                )

            except Exception as e:
                logger.error(
                    f"Handler {handler.__name__} failed "
                    f"for {task_id}: {e}"
                )

                # Record failure
                if 'idempotency_key' in locals():
                    await self.idempotency.record_execution_complete(
                        idempotency_key=idempotency_key,
                        error=str(e)
                    )

                success = False

        return success

    async def claim_idle_messages(
        self,
        idle_time_ms: int = 60000,
        max_messages: int = 100
    ) -> int:
        """
        Claim and process idle messages (single execution, no loop).

        This handles messages from dead consumers.

        Args:
            idle_time_ms: How long a message must be idle
            max_messages: Maximum messages to claim

        Returns:
            Number of messages claimed and processed
        """
        claimed_count = 0

        for stream_key in self._handlers.keys():
            try:
                # Claim idle messages
                claimed = await self.redis.xautoclaim(
                    stream_key,
                    self.consumer_group,
                    self.consumer_id,
                    min_idle_time=idle_time_ms,
                    count=max_messages
                )

                if not claimed or not claimed[1]:  # claimed[1] contains messages
                    continue

                # Process claimed messages
                for msg_id, data in claimed[1]:
                    if data:  # Skip deleted messages
                        success = await self._process_message(
                            stream_key,
                            msg_id,
                            data
                        )

                        if success:
                            await self.redis.xack(
                                stream_key,
                                self.consumer_group,
                                msg_id
                            )
                            claimed_count += 1

            except Exception as e:
                logger.error(f"Error claiming idle messages from {stream_key}: {e}")

        if claimed_count > 0:
            logger.info(f"Claimed and processed {claimed_count} idle messages")

        return claimed_count


class StatelessEventProcessor:
    """
    External processor that triggers stateless consumers.

    This can be called by:
    - Cron jobs
    - External schedulers
    - HTTP endpoints
    - Message queue triggers
    """

    def __init__(
        self,
        consumer: StatelessEventConsumer,
        process_interval_seconds: int = 1,
        claim_interval_seconds: int = 30
    ):
        """
        Initialize processor.

        Args:
            consumer: Stateless consumer to trigger
            process_interval_seconds: How often to process
            claim_interval_seconds: How often to claim idle
        """
        self.consumer = consumer
        self.process_interval = process_interval_seconds
        self.claim_interval = claim_interval_seconds
        self.last_claim = 0

    async def trigger_once(self) -> Dict[str, int]:
        """
        Trigger processing once (stateless).

        Returns:
            Statistics about processing
        """
        stats = {
            "processed": 0,
            "claimed": 0
        }

        # Process regular messages
        stats["processed"] = await self.consumer.process_batch(
            max_messages=100,
            block_ms=100  # Brief wait
        )

        # Periodically claim idle messages
        now = asyncio.get_event_loop().time()
        if now - self.last_claim > self.claim_interval:
            stats["claimed"] = await self.consumer.claim_idle_messages()
            self.last_claim = now

        return stats

    async def trigger_for_duration(
        self,
        duration_seconds: int
    ) -> Dict[str, int]:
        """
        Trigger processing for a specific duration.

        This is useful for Lambda/Cloud Functions with time limits.

        Args:
            duration_seconds: How long to process

        Returns:
            Total statistics
        """
        total_stats = {
            "processed": 0,
            "claimed": 0,
            "triggers": 0
        }

        start_time = asyncio.get_event_loop().time()

        while (asyncio.get_event_loop().time() - start_time) < duration_seconds:
            stats = await self.trigger_once()

            total_stats["processed"] += stats["processed"]
            total_stats["claimed"] += stats["claimed"]
            total_stats["triggers"] += 1

            # Brief sleep between triggers
            await asyncio.sleep(self.process_interval)

        return total_stats