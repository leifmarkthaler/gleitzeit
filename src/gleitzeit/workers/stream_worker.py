"""
Minimal Kafka-style stream worker for Gleitzeit.

This is all we need to make the system work automatically!
"""

import asyncio
import logging
import signal
from typing import Optional
import uuid

logger = logging.getLogger(__name__)


class StreamWorker:
    """Minimal worker that continuously consumes from Redis Streams."""

    def __init__(self, system_manager, worker_id: Optional[str] = None):
        """
        Initialize worker with existing system manager.

        Args:
            system_manager: The existing ModularStreamSystemManager instance
            worker_id: Optional worker identifier
        """
        self.system_manager = system_manager
        self.redis = system_manager.persistence.redis
        self.event_bus = system_manager.event_bus
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.consumer_group = "gleitzeit-processors"  # Use existing group

        self._running = False
        self._shutdown_event = asyncio.Event()

        # Register shutdown handlers
        signal.signal(signal.SIGTERM, lambda s, f: self._shutdown_event.set())
        signal.signal(signal.SIGINT, lambda s, f: self._shutdown_event.set())

    async def start(self):
        """Start the worker - begins continuous consumption."""
        if self._running:
            return

        logger.info(f"Starting worker {self.worker_id}")
        self._running = True

        try:
            await self._consume_loop()
        except Exception as e:
            logger.error(f"Worker {self.worker_id} error: {e}")
        finally:
            self._running = False
            logger.info(f"Worker {self.worker_id} stopped")

    async def _consume_loop(self):
        """
        Main consumption loop - this is the KEY addition!
        Instead of waiting for triggers, we continuously consume.
        """
        # Get all event streams
        streams = {
            "gleitzeit:events:stream:task:ready": ">",
            "gleitzeit:events:stream:task:completed": ">",
            "gleitzeit:events:stream:task:failed": ">",
            "gleitzeit:events:stream:workflow:submitted": ">",
            "gleitzeit:events:stream:workflow:completed": ">",
            "gleitzeit:events:stream:workflow:failed": ">"
        }

        while self._running and not self._shutdown_event.is_set():
            try:
                # This is the magic - BLOCKING READ that waits for messages!
                # This single line changes everything from manual to automatic
                messages = await self.redis.xreadgroup(
                    self.consumer_group,
                    self.worker_id,
                    streams,
                    count=10,
                    block=5000  # Block for 5 seconds
                )

                if messages:
                    # Process using existing event bus infrastructure
                    await self._process_messages(messages)

            except Exception as e:
                logger.error(f"Consumption error: {e}")
                await asyncio.sleep(1)

    async def _process_messages(self, messages):
        """Process messages using existing event bus."""
        for stream_key, stream_messages in messages.items():
            for msg_id, data in stream_messages:
                try:
                    # Use the existing event bus processing
                    # The handlers are already registered!
                    event_type = data.get(b'event_type', b'').decode()

                    # Get handlers from event bus
                    normalized_type = event_type.lower().replace('_', ':')
                    handlers = self.event_bus._handlers.get(normalized_type, [])

                    if handlers:
                        # Decode event using existing method
                        event = self.event_bus._decode_event({
                            k.decode() if isinstance(k, bytes) else k:
                            v.decode() if isinstance(v, bytes) else v
                            for k, v in data.items()
                        })

                        # Call all handlers
                        for handler in handlers:
                            if asyncio.iscoroutinefunction(handler):
                                await handler(event)
                            else:
                                handler(event)

                    # ACK the message
                    await self.redis.xack(stream_key, self.consumer_group, msg_id)

                except Exception as e:
                    logger.error(f"Failed to process message {msg_id}: {e}")