"""
Consumer Group Manager for Redis Streams.

Manages consumer groups, handles consumer lifecycle, and provides
monitoring and cleanup utilities for stream-based event processing.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Set, Tuple
from dataclasses import dataclass

from ..persistence.unified_persistence import UnifiedPersistenceAdapter

logger = logging.getLogger(__name__)


def _safe_decode(value):
    """Safely decode bytes to string, or return string as-is."""
    return value.decode() if isinstance(value, bytes) else value


@dataclass
class ConsumerInfo:
    """Information about a stream consumer."""
    name: str
    pending_count: int
    idle_time: int  # milliseconds
    last_seen: datetime


@dataclass
class StreamInfo:
    """Information about a Redis stream."""
    name: str
    length: int
    groups: List[str]
    first_entry_id: Optional[str]
    last_entry_id: Optional[str]


class ConsumerGroupManager:
    """
    Manages Redis Stream consumer groups and consumers.

    Responsibilities:
    - Create and manage consumer groups
    - Monitor consumer health
    - Clean up idle consumers
    - Handle consumer failover
    - Provide stream statistics
    """

    def __init__(
        self,
        persistence: UnifiedPersistenceAdapter,
        consumer_group: str = "event-processors",
        consumer_timeout_seconds: int = 300,  # 5 minutes
        cleanup_interval_seconds: int = 60  # 1 minute
    ):
        """
        Initialize Consumer Group Manager.

        Args:
            persistence: Redis persistence adapter
            consumer_group: Default consumer group name
            consumer_timeout_seconds: Time before marking consumer as idle
            cleanup_interval_seconds: Interval between cleanup runs
        """
        self.persistence = persistence
        self.consumer_group = consumer_group
        self.consumer_timeout_seconds = consumer_timeout_seconds
        self.cleanup_interval_seconds = cleanup_interval_seconds

        # Cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

        # Statistics
        self._consumers_cleaned = 0
        self._messages_reclaimed = 0

        logger.info(f"Initialized ConsumerGroupManager (group: {consumer_group})")

    async def start_monitoring(self):
        """Start consumer monitoring and cleanup."""
        if self._running:
            return

        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("ConsumerGroupManager monitoring started")

    async def stop_monitoring(self):
        """Stop consumer monitoring."""
        self._running = False

        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        logger.info("ConsumerGroupManager monitoring stopped")

    async def ensure_consumer_group(self, stream_name: str, group_name: Optional[str] = None) -> bool:
        """
        Ensure a consumer group exists for a stream.

        Args:
            stream_name: Name of the stream
            group_name: Consumer group name (defaults to self.consumer_group)

        Returns:
            True if group was created or already exists
        """
        group_name = group_name or self.consumer_group

        try:
            # First, try to create the group with mkstream=True
            # This handles both cases: stream doesn't exist, or stream exists but group doesn't
            await self.persistence.redis.xgroup_create(
                stream_name,
                group_name,
                id="0",
                mkstream=True
            )
            logger.info(f"Created consumer group '{group_name}' for stream '{stream_name}'")
            return True

        except Exception as e:
            error_str = str(e)

            if "BUSYGROUP" in error_str:
                # Group already exists - this is success
                logger.debug(f"Consumer group '{group_name}' already exists for stream '{stream_name}'")
                return True
            elif "WRONGTYPE" in error_str:
                # Key exists but is wrong type - delete and recreate as stream
                logger.warning(f"Key '{stream_name}' exists with wrong type, recreating as stream")
                try:
                    await self.persistence.redis.delete(stream_name)
                    await self.persistence.redis.xgroup_create(
                        stream_name,
                        group_name,
                        id="0",
                        mkstream=True
                    )
                    logger.info(f"Recreated stream '{stream_name}' and created consumer group '{group_name}'")
                    return True
                except Exception as cleanup_error:
                    logger.error(f"Failed to recreate stream {stream_name}: {cleanup_error}")
                    return False
            elif "no such key" in error_str:
                # This shouldn't happen with mkstream=True, but handle it anyway
                logger.warning(f"Stream '{stream_name}' doesn't exist despite mkstream=True: {error_str}")
                return False
            else:
                logger.error(f"Error ensuring consumer group {group_name} for {stream_name}: {e}")
                return False

    async def get_stream_info(self, stream_name: str) -> Optional[StreamInfo]:
        """Get information about a stream."""
        try:
            # Get stream info
            info = await self.persistence.redis.xinfo_stream(stream_name)
            groups_info = await self.persistence.redis.xinfo_groups(stream_name)

            groups = [_safe_decode(group['name']) for group in groups_info]

            return StreamInfo(
                name=stream_name,
                length=info.get('length', 0),
                groups=groups,
                first_entry_id=info.get('first-entry', [None])[0],
                last_entry_id=info.get('last-entry', [None])[0]
            )

        except Exception as e:
            logger.error(f"Error getting stream info for {stream_name}: {e}")
            return None

    async def get_consumer_info(self, stream_name: str, group_name: Optional[str] = None) -> List[ConsumerInfo]:
        """Get information about consumers in a group."""
        group_name = group_name or self.consumer_group
        consumers = []

        try:
            consumer_info = await self.persistence.redis.xinfo_consumers(stream_name, group_name)

            for info in consumer_info:
                consumer = ConsumerInfo(
                    name=_safe_decode(info['name']),
                    pending_count=info.get('pending', 0),
                    idle_time=info.get('idle', 0),
                    last_seen=datetime.utcnow() - timedelta(milliseconds=info.get('idle', 0))
                )
                consumers.append(consumer)

        except Exception as e:
            logger.error(f"Error getting consumer info for {stream_name}/{group_name}: {e}")

        return consumers

    async def cleanup_idle_consumers(self, stream_name: str, group_name: Optional[str] = None) -> int:
        """
        Clean up idle consumers and reclaim their pending messages.

        Args:
            stream_name: Name of the stream
            group_name: Consumer group name

        Returns:
            Number of consumers cleaned up
        """
        group_name = group_name or self.consumer_group
        cleaned_count = 0

        try:
            consumers = await self.get_consumer_info(stream_name, group_name)
            current_time = datetime.utcnow()

            for consumer in consumers:
                # Check if consumer is idle
                idle_duration = current_time - consumer.last_seen

                if idle_duration.total_seconds() > self.consumer_timeout_seconds:
                    logger.info(f"Cleaning up idle consumer {consumer.name} (idle: {idle_duration})")

                    # Get pending messages for this consumer
                    pending = await self.persistence.redis.xpending_range(
                        stream_name,
                        group_name,
                        min="-",
                        max="+",
                        count=1000,
                        consumer=consumer.name
                    )

                    # Claim pending messages to reclaim them
                    if pending:
                        message_ids = [msg[0] for msg in pending]

                        # Claim messages with a very low min-idle time to force reclaim
                        claimed = await self.persistence.redis.xclaim(
                            stream_name,
                            group_name,
                            "cleanup-consumer",  # Temporary consumer for cleanup
                            min_idle_time=0,
                            message_ids=message_ids
                        )

                        # Acknowledge the claimed messages to remove them from pending
                        if claimed:
                            claimed_ids = [msg[0] for msg in claimed]
                            await self.persistence.redis.xack(stream_name, group_name, *claimed_ids)
                            self._messages_reclaimed += len(claimed_ids)
                            logger.info(f"Reclaimed {len(claimed_ids)} messages from {consumer.name}")

                    # Delete the idle consumer
                    await self.persistence.redis.xgroup_delconsumer(stream_name, group_name, consumer.name)
                    cleaned_count += 1
                    self._consumers_cleaned += 1

        except Exception as e:
            logger.error(f"Error cleaning up consumers for {stream_name}/{group_name}: {e}")

        return cleaned_count

    async def reclaim_pending_messages(
        self,
        stream_name: str,
        group_name: Optional[str] = None,
        min_idle_time: int = 60000  # 1 minute in milliseconds
    ) -> int:
        """
        Reclaim pending messages that have been idle too long.

        Args:
            stream_name: Name of the stream
            group_name: Consumer group name
            min_idle_time: Minimum idle time in milliseconds

        Returns:
            Number of messages reclaimed
        """
        group_name = group_name or self.consumer_group
        reclaimed_count = 0

        try:
            # Get pending messages summary
            pending_info = await self.persistence.redis.xpending(stream_name, group_name)

            if not pending_info or pending_info[0] == 0:
                return 0

            # Get detailed pending messages
            pending_messages = await self.persistence.redis.xpending_range(
                stream_name,
                group_name,
                min="-",
                max="+",
                count=1000
            )

            # Find messages that are idle too long
            idle_messages = []
            for msg_id, consumer, idle_time, delivery_count in pending_messages:
                if idle_time >= min_idle_time:
                    idle_messages.append(msg_id)

            if idle_messages:
                # Claim idle messages
                claimed = await self.persistence.redis.xclaim(
                    stream_name,
                    group_name,
                    "reclaim-consumer",  # Temporary consumer
                    min_idle_time=min_idle_time,
                    message_ids=idle_messages
                )

                # Process claimed messages or acknowledge them
                if claimed:
                    claimed_ids = [msg[0] for msg in claimed]
                    # For now, just acknowledge to remove from pending
                    # In practice, you might want to reprocess these messages
                    await self.persistence.redis.xack(stream_name, group_name, *claimed_ids)
                    reclaimed_count = len(claimed_ids)
                    self._messages_reclaimed += reclaimed_count

                    logger.info(f"Reclaimed {reclaimed_count} idle messages from {stream_name}")

        except Exception as e:
            logger.error(f"Error reclaiming pending messages for {stream_name}/{group_name}: {e}")

        return reclaimed_count

    async def get_pending_summary(self, stream_name: str, group_name: Optional[str] = None) -> Dict[str, Any]:
        """Get summary of pending messages for a consumer group."""
        group_name = group_name or self.consumer_group

        try:
            pending_info = await self.persistence.redis.xpending(stream_name, group_name)

            if not pending_info or pending_info[0] == 0:
                return {
                    "total_pending": 0,
                    "consumers": {},
                    "oldest_pending": None,
                    "newest_pending": None
                }

            # Get consumer breakdown
            consumers = {}
            if len(pending_info) > 3 and pending_info[3]:
                for consumer_data in pending_info[3]:
                    consumer_name = _safe_decode(consumer_data[0])
                    consumer_pending = consumer_data[1]
                    consumers[consumer_name] = consumer_pending

            return {
                "total_pending": pending_info[0],
                "oldest_pending": _safe_decode(pending_info[1]) if pending_info[1] else None,
                "newest_pending": _safe_decode(pending_info[2]) if pending_info[2] else None,
                "consumers": consumers
            }

        except Exception as e:
            logger.error(f"Error getting pending summary for {stream_name}/{group_name}: {e}")
            return {"error": str(e)}

    async def _cleanup_loop(self):
        """Main cleanup loop that runs periodically."""
        try:
            while self._running:
                await asyncio.sleep(self.cleanup_interval_seconds)

                if not self._running:
                    break

                # Get list of streams to monitor
                # For now, monitor common stream patterns
                stream_patterns = [
                    "events:*",
                    "timers:*",
                    "signals:*"
                ]

                streams_to_monitor = set()
                for pattern in stream_patterns:
                    try:
                        keys = await self.persistence.redis.keys(pattern)
                        for key in keys:
                            key = _safe_decode(key)
                            # Check if it's actually a stream
                            try:
                                await self.persistence.redis.xinfo_stream(key)
                                streams_to_monitor.add(key)
                            except:
                                # Not a stream, skip
                                pass
                    except Exception as e:
                        logger.debug(f"Error scanning for streams with pattern {pattern}: {e}")

                # Clean up each stream
                for stream_name in streams_to_monitor:
                    try:
                        cleaned = await self.cleanup_idle_consumers(stream_name)
                        if cleaned > 0:
                            logger.info(f"Cleaned {cleaned} idle consumers from {stream_name}")

                        reclaimed = await self.reclaim_pending_messages(stream_name)
                        if reclaimed > 0:
                            logger.info(f"Reclaimed {reclaimed} pending messages from {stream_name}")

                    except Exception as e:
                        logger.error(f"Error cleaning up stream {stream_name}: {e}")

        except asyncio.CancelledError:
            logger.info("Consumer cleanup loop cancelled")
        except Exception as e:
            logger.error(f"Error in cleanup loop: {e}")

    def get_statistics(self) -> Dict[str, Any]:
        """Get consumer group manager statistics."""
        return {
            "consumer_group": self.consumer_group,
            "consumer_timeout_seconds": self.consumer_timeout_seconds,
            "cleanup_interval_seconds": self.cleanup_interval_seconds,
            "consumers_cleaned": self._consumers_cleaned,
            "messages_reclaimed": self._messages_reclaimed,
            "monitoring_active": self._running
        }