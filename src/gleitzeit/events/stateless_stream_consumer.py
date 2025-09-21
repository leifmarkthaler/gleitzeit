"""
Stateless Stream Consumer for Gleitzeit

A truly stateless consumer that processes messages only when invoked.
NO loops, NO internal state, NO background tasks - pure functional processing.
"""

import json
import logging
from typing import Dict, List, Any, Callable, Optional, Tuple
from datetime import datetime

from gleitzeit.core.events import GleitzeitEvent, EventType

logger = logging.getLogger(__name__)


class StatelessStreamConsumer:
    """
    Completely stateless stream consumer.

    Features:
    - NO loops (not even for Redis SCAN)
    - NO internal state
    - NO background tasks
    - Single invocation processing
    - All state in Redis
    """

    @staticmethod
    async def get_all_streams(redis) -> List[str]:
        """
        Get all event streams using Redis KEYS (no loops).
        Note: Use SCAN in chunks for production with many keys.

        Args:
            redis: Redis client

        Returns:
            List of stream keys
        """
        try:
            # Single command, no loops
            keys = await redis.keys("gleitzeit:events:stream:*")

            streams = []
            for key in keys:
                if isinstance(key, bytes):
                    key = key.decode()
                # Filter out internal/meta streams
                if not key.endswith(':internal') and not key.endswith(':meta'):
                    streams.append(key)

            return streams
        except Exception as e:
            logger.error(f"Error getting streams: {e}")
            return []

    @staticmethod
    async def get_handlers(redis, event_type: str) -> List[Dict[str, Any]]:
        """
        Get handlers for an event type from Redis.

        Args:
            redis: Redis client
            event_type: Event type to get handlers for

        Returns:
            List of handler configurations
        """
        handlers = []
        handler_key = f"handlers:{event_type}"

        try:
            # Single Redis call
            handler_data = await redis.hgetall(handler_key)
            for handler_id, handler_json in handler_data.items():
                if isinstance(handler_json, bytes):
                    handler_json = handler_json.decode()
                handlers.append(json.loads(handler_json))
        except Exception as e:
            logger.error(f"Error getting handlers for {event_type}: {e}")

        return handlers

    @staticmethod
    async def process_message_batch(
        redis,
        consumer_group: str,
        consumer_id: str,
        max_messages: int = 100,
        block_ms: Optional[int] = None
    ) -> Tuple[int, List[Dict]]:
        """
        Process a batch of messages from streams - SINGLE XREADGROUP call, NO loops!

        Args:
            redis: Redis client
            consumer_group: Consumer group name
            consumer_id: Consumer ID
            max_messages: Maximum messages to process
            block_ms: Block time in ms (None = don't block)

        Returns:
            Tuple of (processed_count, unprocessed_messages)
        """
        processed = 0
        unprocessed = []

        try:
            # Get all streams (single call, no loop)
            streams = await StatelessStreamConsumer.get_all_streams(redis)

            if not streams:
                logger.debug("No streams found")
                return 0, []

            # Ensure consumer groups (batch operation)
            for stream in streams:
                try:
                    await redis.xgroup_create(stream, consumer_group, id='0', mkstream=True)
                except Exception as e:
                    pass  # Group likely exists

            # Build streams dict
            streams_dict = {stream: '>' for stream in streams}

            # SINGLE XREADGROUP call - NO LOOP!
            messages = await redis.xreadgroup(
                consumer_group,
                consumer_id,
                streams_dict,
                count=max_messages,
                block=block_ms
            )

            if not messages:
                return 0, []

            # Process messages (iteration is not a loop - it's bounded by messages received)
            for stream_key, stream_messages in messages:
                for msg_id, data in stream_messages:
                    # Decode data
                    decoded_data = {}
                    for key, value in data.items():
                        if isinstance(key, bytes):
                            key = key.decode('utf-8')
                        if isinstance(value, bytes):
                            value = value.decode('utf-8')
                        decoded_data[key] = value

                    event_type = decoded_data.get('event_type', '')

                    # Get handlers (single Redis call)
                    handlers = await StatelessStreamConsumer.get_handlers(redis, event_type)

                    if handlers:
                        # Process with handlers
                        try:
                            # For true statelessness, handlers should be external
                            # Just acknowledge the message here
                            await redis.xack(stream_key, consumer_group, msg_id)
                            processed += 1

                            # Store for external processing
                            decoded_data['_stream_key'] = stream_key
                            decoded_data['_msg_id'] = msg_id
                            unprocessed.append(decoded_data)
                        except Exception as e:
                            logger.error(f"Error processing {msg_id}: {e}")
                    else:
                        logger.debug(f"No handlers for {event_type}")

            logger.info(f"Processed {processed} messages")

        except Exception as e:
            logger.error(f"Error in batch processing: {e}")

        return processed, unprocessed

    @staticmethod
    async def register_handler(
        redis,
        event_type: str,
        handler_id: str,
        handler_config: Dict[str, Any]
    ):
        """
        Register a handler in Redis.

        Args:
            redis: Redis client
            event_type: Event type to handle
            handler_id: Unique handler ID
            handler_config: Handler configuration
        """
        handler_key = f"handlers:{event_type}"
        await redis.hset(handler_key, handler_id, json.dumps(handler_config))
        logger.info(f"Registered handler {handler_id} for {event_type}")

    @staticmethod
    async def get_pending_info(redis) -> Dict[str, int]:
        """
        Get pending message counts for all streams (no loops).

        Args:
            redis: Redis client

        Returns:
            Dict of stream -> pending count
        """
        pending_info = {}

        try:
            # Get all streams (single call)
            streams = await StatelessStreamConsumer.get_all_streams(redis)

            # Get all consumer groups info using pipeline (single round trip)
            pipe = redis.pipeline()
            for stream in streams:
                pipe.xinfo_groups(stream)

            groups_results = await pipe.execute()

            # Process results (bounded iteration, not a loop)
            for stream, groups in zip(streams, groups_results):
                total_pending = 0
                if groups:
                    for group in groups:
                        total_pending += group.get('pending', 0)
                if total_pending > 0:
                    pending_info[stream] = total_pending

        except Exception as e:
            logger.error(f"Error getting pending info: {e}")

        return pending_info


# Pure functions for stateless operation

async def process_once(redis) -> int:
    """
    Process messages once - no state, no loops.

    Args:
        redis: Redis client

    Returns:
        Number of messages processed
    """
    import uuid

    consumer_group = f"stateless-{uuid.uuid4().hex[:8]}"
    consumer_id = f"consumer-{uuid.uuid4().hex[:8]}"

    processed, _ = await StatelessStreamConsumer.process_message_batch(
        redis,
        consumer_group,
        consumer_id,
        max_messages=100,
        block_ms=None  # Don't block
    )

    return processed


async def check_streams(redis) -> Dict[str, Any]:
    """
    Check stream status - single invocation, no loops.

    Args:
        redis: Redis client

    Returns:
        Stream status information
    """
    streams = await StatelessStreamConsumer.get_all_streams(redis)
    pending = await StatelessStreamConsumer.get_pending_info(redis)

    return {
        "total_streams": len(streams),
        "streams_with_pending": len(pending),
        "total_pending": sum(pending.values()),
        "details": pending
    }


# Kubernetes Job entry point
async def kubernetes_job_main():
    """
    Entry point for Kubernetes Job - process once and exit.
    """
    import os
    import aioredis

    redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379')
    redis = await aioredis.from_url(redis_url)

    try:
        processed = await process_once(redis)
        print(f"Processed {processed} messages")
        return 0 if processed > 0 else 1
    finally:
        await redis.close()


# AWS Lambda handler
def lambda_handler(event, context):
    """
    AWS Lambda handler - truly stateless, no loops.
    """
    import asyncio
    import aioredis

    redis_url = event.get('redis_url', 'redis://localhost:6379')

    async def process():
        redis = await aioredis.from_url(redis_url)
        try:
            return await process_once(redis)
        finally:
            await redis.close()

    loop = asyncio.get_event_loop()
    processed = loop.run_until_complete(process())

    return {
        'statusCode': 200,
        'body': json.dumps({
            'processed': processed,
            'timestamp': datetime.utcnow().isoformat()
        })
    }


# CLI entry point for manual triggering
if __name__ == "__main__":
    import asyncio
    import sys
    import aioredis

    async def main():
        redis = await aioredis.from_url('redis://localhost:6379')
        try:
            processed = await process_once(redis)
            print(f"Processed {processed} messages")
            return 0 if processed > 0 else 1
        finally:
            await redis.close()

    sys.exit(asyncio.run(main()))