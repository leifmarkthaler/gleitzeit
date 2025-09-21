#!/usr/bin/env python3
"""
Cleanup dead consumers from Redis consumer groups.

This script uses the new ConsumerLifecycle system to:
1. Identify dead consumers
2. Clean them up
3. Report on the cleanup operation
"""

import asyncio
import redis.asyncio as redis
import logging
import sys
from typing import List

# Add src to path to import Gleitzeit modules
sys.path.insert(0, 'src')

from gleitzeit.events.consumer_lifecycle import ConsumerLifecycle, ConsumerCleanupService

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def check_consumer_groups(redis_client: redis.Redis) -> dict:
    """Check all consumer groups and their consumers."""
    groups_info = {}

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
                if group_name not in groups_info:
                    groups_info[group_name] = {
                        "streams": [],
                        "total_consumers": 0,
                        "total_pending": 0,
                        "consumers_detail": []
                    }

                groups_info[group_name]["streams"].append(stream_key)
                groups_info[group_name]["total_pending"] += group.get("pending", 0)

                # Get consumer details
                try:
                    consumers = await redis_client.xinfo_consumers(stream_key, group_name)
                    for consumer in consumers:
                        groups_info[group_name]["consumers_detail"].append({
                            "name": consumer["name"],
                            "pending": consumer.get("pending", 0),
                            "idle": consumer.get("idle", 0) / 1000,  # Convert to seconds
                            "stream": stream_key
                        })
                        groups_info[group_name]["total_consumers"] = len(
                            set(c["name"] for c in groups_info[group_name]["consumers_detail"])
                        )
                except Exception as e:
                    logger.error(f"Error getting consumers for {group_name} on {stream_key}: {e}")

        except Exception as e:
            logger.error(f"Error checking groups for {stream_key}: {e}")

    return groups_info


async def main():
    """Main cleanup function."""
    logger.info("=" * 60)
    logger.info("Dead Consumer Cleanup Tool")
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
        groups_before = await check_consumer_groups(redis_client)

        total_consumers_before = sum(g["total_consumers"] for g in groups_before.values())
        logger.info(f"\nFound {len(groups_before)} consumer groups with {total_consumers_before} total consumers")

        for group_name, info in groups_before.items():
            logger.info(f"\n  Group: {group_name}")
            logger.info(f"    Streams: {len(info['streams'])}")
            logger.info(f"    Consumers: {info['total_consumers']}")
            logger.info(f"    Total Pending: {info['total_pending']}")

            # Show idle consumers
            idle_consumers = [c for c in info["consumers_detail"] if c["idle"] > 60]
            if idle_consumers:
                logger.info(f"    ⚠️  Idle consumers (>60s):")
                for consumer in idle_consumers[:5]:  # Show first 5
                    logger.info(f"      - {consumer['name']}: idle {consumer['idle']:.0f}s, pending {consumer['pending']}")
                if len(idle_consumers) > 5:
                    logger.info(f"      ... and {len(idle_consumers) - 5} more")

        # Initialize cleanup service
        logger.info("\n🧹 Initializing cleanup service...")
        cleanup_service = ConsumerCleanupService(
            redis=redis_client,
            cleanup_interval=30  # Not used for one-time cleanup
        )

        # Discover stream keys
        stream_keys = await cleanup_service.discover_stream_keys()
        logger.info(f"Discovered {len(stream_keys)} stream keys")

        # Run cleanup
        logger.info("\n🗑️  Running dead consumer cleanup...")
        removed = await cleanup_service.run_cleanup_once()
        logger.info(f"✅ Removed {removed} dead consumers")

        # Check state after cleanup
        logger.info("\n📊 Checking consumer groups after cleanup...")
        groups_after = await check_consumer_groups(redis_client)

        total_consumers_after = sum(g["total_consumers"] for g in groups_after.values())
        logger.info(f"\nNow have {len(groups_after)} consumer groups with {total_consumers_after} total consumers")
        logger.info(f"🎉 Cleaned up {total_consumers_before - total_consumers_after} consumers total")

        # Generate health report
        logger.info("\n📋 Generating health report...")
        health_report = await cleanup_service.get_health_report()

        logger.info("\n🏥 System Health:")
        logger.info(f"  Active consumers: {health_report['consumer_stats']['total_active']}")

        if health_report['consumer_stats']['consumers']:
            logger.info("  Consumer details:")
            for consumer in health_report['consumer_stats']['consumers']:
                status = "✅" if consumer['healthy'] else "⚠️"
                logger.info(f"    {status} {consumer['id']} on {consumer['hostname']} (PID: {consumer['pid']}, age: {consumer['heartbeat_age']:.1f}s)")

        logger.info("\n  Stream health:")
        for stream in health_report['streams']:
            logger.info(f"    {stream['key']}: {stream['length']} messages")
            for group in stream['groups']:
                logger.info(f"      Group {group['name']}: {group['pending']} pending, {group['consumers']} consumers")

        logger.info("\n✅ Cleanup complete!")

    except Exception as e:
        logger.error(f"Error during cleanup: {e}", exc_info=True)
        return 1
    finally:
        await redis_client.close()

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)