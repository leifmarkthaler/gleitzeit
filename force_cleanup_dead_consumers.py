#!/usr/bin/env python3
"""
Force cleanup of dead consumers from Redis consumer groups.

This directly removes consumers that have been idle for too long,
without requiring the new TTL-based registration system.
"""

import asyncio
import redis.asyncio as redis
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def force_cleanup_dead_consumers(
    redis_client: redis.Redis,
    max_idle_seconds: int = 300  # 5 minutes default
) -> int:
    """
    Force removal of idle consumers from all consumer groups.

    Args:
        redis_client: Redis connection
        max_idle_seconds: Maximum idle time before considering consumer dead

    Returns:
        Number of consumers removed
    """
    removed_count = 0
    max_idle_ms = max_idle_seconds * 1000  # Convert to milliseconds

    # Find all stream keys
    stream_patterns = [
        "gleitzeit:events:*",
        "gleitzeit:stream:*"
    ]

    all_streams = []
    for pattern in stream_patterns:
        async for key in redis_client.scan_iter(match=pattern):
            # Verify it's actually a stream
            try:
                await redis_client.xinfo_stream(key)
                all_streams.append(key)
            except:
                pass

    logger.info(f"Found {len(all_streams)} stream keys")

    for stream_key in all_streams:
        try:
            groups = await redis_client.xinfo_groups(stream_key)

            for group in groups:
                group_name = group["name"]

                # Get consumers in this group
                try:
                    consumers = await redis_client.xinfo_consumers(stream_key, group_name)

                    for consumer in consumers:
                        consumer_name = consumer["name"]
                        idle_time = consumer.get("idle", 0)

                        # Check if consumer is idle beyond threshold
                        if idle_time > max_idle_ms:
                            # Remove dead consumer
                            await redis_client.xgroup_delconsumer(
                                stream_key,
                                group_name,
                                consumer_name
                            )
                            removed_count += 1
                            logger.info(
                                f"Removed idle consumer {consumer_name} from {group_name} on {stream_key} "
                                f"(idle: {idle_time/1000:.1f}s)"
                            )

                except Exception as e:
                    logger.error(f"Error checking consumers for {group_name} on {stream_key}: {e}")

        except Exception as e:
            logger.error(f"Error checking groups for {stream_key}: {e}")

    return removed_count


async def main():
    """Main cleanup function."""
    logger.info("=" * 60)
    logger.info("Force Dead Consumer Cleanup Tool")
    logger.info("=" * 60)

    # Connect to Redis
    redis_client = redis.Redis(
        host='localhost',
        port=6379,
        decode_responses=False  # We need bytes for xinfo commands
    )

    try:
        # Check current state
        logger.info("\n📊 Checking current consumer groups...")

        # Count consumers before
        total_before = 0
        stream_patterns = ["gleitzeit:events:*", "gleitzeit:stream:*"]
        for pattern in stream_patterns:
            async for key in redis_client.scan_iter(match=pattern):
                try:
                    groups = await redis_client.xinfo_groups(key)
                    for group in groups:
                        consumers = await redis_client.xinfo_consumers(key, group["name"])
                        total_before += len(consumers)
                except:
                    pass

        logger.info(f"Found {total_before} total consumers before cleanup")

        # Run force cleanup - use 5 minute idle threshold
        logger.info("\n🗑️  Running force cleanup (removing consumers idle > 5 minutes)...")
        removed = await force_cleanup_dead_consumers(redis_client, max_idle_seconds=300)
        logger.info(f"✅ Removed {removed} dead consumers")

        # Count consumers after
        total_after = 0
        for pattern in stream_patterns:
            async for key in redis_client.scan_iter(match=pattern):
                try:
                    groups = await redis_client.xinfo_groups(key)
                    for group in groups:
                        consumers = await redis_client.xinfo_consumers(key, group["name"])
                        total_after += len(consumers)
                except:
                    pass

        logger.info(f"\n📊 Now have {total_after} total consumers")
        logger.info(f"🎉 Total reduction: {total_before - total_after} consumers")

        # Show remaining consumers
        if total_after > 0:
            logger.info("\n📋 Remaining consumers:")
            for pattern in stream_patterns:
                async for key in redis_client.scan_iter(match=pattern):
                    try:
                        groups = await redis_client.xinfo_groups(key)
                        for group in groups:
                            consumers = await redis_client.xinfo_consumers(key, group["name"])
                            if consumers:
                                logger.info(f"  {group['name']} on {key}: {len(consumers)} consumers")
                                for consumer in consumers[:3]:  # Show first 3
                                    idle_seconds = consumer.get("idle", 0) / 1000
                                    logger.info(f"    - {consumer['name']}: idle {idle_seconds:.1f}s, pending {consumer.get('pending', 0)}")
                                if len(consumers) > 3:
                                    logger.info(f"    ... and {len(consumers) - 3} more")
                    except:
                        pass

        logger.info("\n✅ Force cleanup complete!")

    except Exception as e:
        logger.error(f"Error during cleanup: {e}", exc_info=True)
        return 1
    finally:
        await redis_client.aclose()

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)