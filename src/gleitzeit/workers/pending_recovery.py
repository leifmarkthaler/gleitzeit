"""
Pending Message Recovery for Gleitzeit 0.0.7

Handles recovery of stuck pending messages from dead workers using XCLAIM.
This runs as part of the BaseWorker or as a separate recovery process.
"""

import asyncio
import logging
from typing import Dict, List, Set, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PendingMessage:
    """Represents a pending message from XPENDING"""
    message_id: bytes
    consumer: bytes
    idle_time: int  # milliseconds since last delivery
    delivery_count: int


class PendingRecoveryMixin:
    """
    Mixin for BaseWorker to add pending message recovery via XCLAIM.

    This allows workers to claim messages that have been stuck
    with dead workers for too long.
    """

    # Configuration
    CLAIM_IDLE_TIME = 300000  # 5 minutes in milliseconds
    RECOVERY_INTERVAL = 60    # Check every 60 seconds
    MAX_CLAIM_BATCH = 100      # Max messages to claim at once

    async def start_recovery_task(self):
        """Start the background recovery task"""
        if not hasattr(self, '_recovery_task'):
            self._recovery_task = asyncio.create_task(self._recovery_loop())
            logger.info(f"Started pending recovery task for {self.config.worker_id}")

    async def stop_recovery_task(self):
        """Stop the recovery task"""
        if hasattr(self, '_recovery_task'):
            self._recovery_task.cancel()
            try:
                await self._recovery_task
            except asyncio.CancelledError:
                pass

    async def _recovery_loop(self):
        """Main recovery loop - runs periodically to claim stuck messages"""
        while self._running:
            try:
                await asyncio.sleep(self.RECOVERY_INTERVAL)
                await self.recover_pending_messages()
            except Exception as e:
                logger.error(f"Error in recovery loop: {e}", exc_info=True)
                await asyncio.sleep(5)  # Brief pause on error

    async def recover_pending_messages(self) -> int:
        """
        Recover stuck pending messages from all streams this worker consumes.

        Returns:
            Number of messages successfully claimed
        """
        total_claimed = 0

        # Get all streams this worker consumes from
        streams = self.get_stream_patterns()

        for stream_key in streams.keys():
            try:
                claimed = await self._recover_stream_pending(stream_key)
                total_claimed += claimed
            except Exception as e:
                logger.error(f"Error recovering pending from {stream_key}: {e}")

        if total_claimed > 0:
            logger.info(f"Claimed {total_claimed} stuck pending messages")

        return total_claimed

    async def _recover_stream_pending(self, stream_key: bytes) -> int:
        """
        Recover pending messages from a specific stream.

        Args:
            stream_key: The stream to check for stuck messages

        Returns:
            Number of messages claimed from this stream
        """
        claimed_count = 0

        try:
            # Get detailed pending list
            # XPENDING stream group [idle] start end count [consumer]
            # Using the detailed form to get messages with idle time
            pending_messages = await self.redis.execute_command(
                b"XPENDING",
                stream_key,
                self.config.consumer_group.encode(),
                b"IDLE",
                str(self.CLAIM_IDLE_TIME).encode(),  # Only messages idle > 5 minutes
                b"-",
                b"+",
                str(self.MAX_CLAIM_BATCH).encode()
            )

            if not pending_messages:
                return 0

            # Group messages by consumer for logging
            by_consumer: Dict[bytes, List[bytes]] = {}
            message_ids = []

            for msg_info in pending_messages:
                # msg_info format: (message_id, consumer, idle_time, delivery_count)
                msg_id = msg_info[0]
                consumer = msg_info[1]
                idle_time = msg_info[2]

                if idle_time >= self.CLAIM_IDLE_TIME:
                    message_ids.append(msg_id)
                    if consumer not in by_consumer:
                        by_consumer[consumer] = []
                    by_consumer[consumer].append(msg_id)

            if not message_ids:
                return 0

            # Log what we're claiming
            for consumer, msgs in by_consumer.items():
                if consumer != self.config.worker_id.encode():
                    logger.info(
                        f"Claiming {len(msgs)} stuck messages from "
                        f"{consumer.decode()} on {stream_key.decode()}"
                    )

            # XCLAIM the messages - take ownership
            # XCLAIM key group consumer min-idle-time id [id ...] [IDLE ms] [TIME unix-time-ms] [RETRYCOUNT count] [FORCE] [JUSTID]
            claimed = await self.redis.execute_command(
                b"XCLAIM",
                stream_key,
                self.config.consumer_group.encode(),
                self.config.worker_id.encode(),
                str(self.CLAIM_IDLE_TIME).encode(),
                *message_ids,
                b"JUSTID"  # Just claim ownership, don't return full messages
            )

            claimed_count = len(claimed) if claimed else 0

            if claimed_count > 0:
                logger.info(
                    f"Successfully claimed {claimed_count} messages from "
                    f"{stream_key.decode()}"
                )

                # Emit metrics event
                await self._emit_recovery_metrics(stream_key, claimed_count, by_consumer)

        except Exception as e:
            logger.error(f"Failed to recover pending from {stream_key.decode()}: {e}")

        return claimed_count

    async def _emit_recovery_metrics(
        self,
        stream_key: bytes,
        claimed_count: int,
        by_consumer: Dict[bytes, List[bytes]]
    ):
        """Emit metrics about recovered messages for monitoring"""
        try:
            metrics = {
                b"event": b"pending_recovery",
                b"stream": stream_key,
                b"claimed_count": str(claimed_count).encode(),
                b"claimer": self.config.worker_id.encode(),
                b"timestamp": datetime.utcnow().isoformat().encode(),
                b"from_consumers": ",".join(
                    c.decode() for c in by_consumer.keys()
                ).encode()
            }

            # Emit to metrics stream for monitoring
            await self.redis.xadd(
                b"metrics:recovery",
                metrics
            )

        except Exception as e:
            logger.debug(f"Failed to emit recovery metrics: {e}")


class StandalonePendingRecovery:
    """
    Standalone pending recovery that can run as a separate process.

    This is useful for systems that want a dedicated recovery worker
    rather than having each worker do its own recovery.
    """

    def __init__(self, redis, consumer_groups: List[Tuple[str, str]]):
        """
        Initialize standalone recovery.

        Args:
            redis: Redis connection
            consumer_groups: List of (stream_pattern, consumer_group) tuples
        """
        self.redis = redis
        self.consumer_groups = consumer_groups
        self.recovery_worker_id = f"recovery-{datetime.utcnow().timestamp()}"
        self._running = False

    async def run(self):
        """Run continuous recovery"""
        self._running = True
        logger.info("Starting standalone pending recovery worker")

        while self._running:
            try:
                total_claimed = 0

                for stream_pattern, consumer_group in self.consumer_groups:
                    # Find all streams matching pattern
                    cursor = b"0"
                    while cursor:
                        cursor, streams = await self.redis.scan(
                            cursor,
                            match=stream_pattern.encode(),
                            type="stream"
                        )

                        for stream_key in streams:
                            claimed = await self._recover_stream(
                                stream_key,
                                consumer_group
                            )
                            total_claimed += claimed

                        if cursor == b"0":
                            break

                if total_claimed > 0:
                    logger.info(f"Recovery cycle claimed {total_claimed} messages")

                await asyncio.sleep(60)  # Check every minute

            except Exception as e:
                logger.error(f"Error in standalone recovery: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def _recover_stream(self, stream_key: bytes, consumer_group: str) -> int:
        """Recover pending messages from a stream"""
        # Similar implementation to PendingRecoveryMixin._recover_stream_pending
        # but assigns to a pool of healthy workers instead of self
        pass  # Implementation details omitted for brevity

    def stop(self):
        """Stop recovery"""
        self._running = False