"""
Time Advance Worker for Gleitzeit

Emits time advance events to trigger timer processing.
This worker runs as leader and generates events when time buckets expire.
"""

import asyncio
import logging
import time
from typing import List, Optional
from datetime import datetime

from .base import BaseWorker, WorkerConfig
from ..core.sharding import default_sharding
from ..core.leader_election import LeaderElection, LeaderStatus
from ..core.events import EventType
from ..core.event_store import EventStore, EventLevel

logger = logging.getLogger(__name__)


class TimeAdvanceWorker(BaseWorker):
    """
    Worker that emits time advance events for timer processing.

    Features:
    - Leader election (only leader emits events)
    - Scans timer registry for expired buckets
    - Emits time advance events to stream
    - Auto-cleanup of old bucket registry keys
    """

    def __init__(self, config: WorkerConfig):
        super().__init__(config)
        self.leader_election: Optional[LeaderElection] = None
        self.leader_key = default_sharding.get_global_key("time_advance:leader")
        self.leader_ttl = 10  # seconds
        self.bucket_size = 60  # seconds (1 minute buckets)
        self.check_interval = 1  # Check every second
        self.last_bucket_processed = 0

    async def on_initialize(self):
        """Initialize time advance worker resources"""
        # Initialize event store
        self.event_store = EventStore(self.redis, config={
            'max_events_per_workflow': 10000,
            'event_ttl_seconds': 86400 * 30  # 30 days
        })

        # Initialize atomic leader election
        self.leader_election = LeaderElection(
            self.redis,
            self.leader_key,
            self.config.worker_id,
            self.leader_ttl
        )

        logger.info(f"TimeAdvanceWorker initialized with bucket_size={self.bucket_size}s")

    def get_base_streams(self) -> List[str]:
        """Return streams this worker consumes from"""
        # Time advance worker doesn't consume streams - it generates them
        return []

    async def run(self):
        """Main worker loop with leader election"""
        logger.info(f"Worker {self.config.worker_id} starting")

        self._running = True

        # Start heartbeat task (includes worker registration)
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        # Start leader election task
        election_task = asyncio.create_task(self._leader_election_loop())

        # Start time advance processing (only if leader)
        advance_task = asyncio.create_task(self._time_advance_loop())

        try:
            # Run all tasks
            await asyncio.gather(heartbeat_task, election_task, advance_task)
        except asyncio.CancelledError:
            logger.info("Worker cancelled")
        finally:
            # Cleanup
            heartbeat_task.cancel()
            if self.leader_election and self.leader_election.is_leader:
                await self.leader_election.release()

    async def _leader_election_loop(self):
        """Participate in atomic leader election"""
        logger.info(f"Starting leader election loop for {self.config.worker_id}")
        while self._running:
            try:
                # Atomic leader election
                status = await self.leader_election.try_elect()

                if status == LeaderStatus.BECAME_LEADER:
                    logger.info(f"Worker {self.config.worker_id} became time advance leader")
                elif status == LeaderStatus.LOST_LEADERSHIP:
                    logger.info(f"Worker {self.config.worker_id} lost time advance leadership")

                await asyncio.sleep(self.leader_ttl // 3)  # Heartbeat interval

            except Exception as e:
                logger.error(f"Leader election error: {e}")
                await asyncio.sleep(1)

    async def _time_advance_loop(self):
        """Emit time advance events for expired buckets (only when leader)"""
        logger.info(f"Time advance loop started for {self.config.worker_id}")

        while self._running:
            try:
                if self.leader_election and self.leader_election.is_leader:
                    await self._process_time_advance()

                await asyncio.sleep(self.check_interval)

            except Exception as e:
                logger.error(f"Time advance error: {e}", exc_info=True)
                await asyncio.sleep(1)

        logger.info(f"Time advance loop ended for {self.config.worker_id}")

    async def _process_time_advance(self):
        """Check for expired buckets and emit events"""
        current_time = time.time()
        current_bucket = default_sharding.get_timer_bucket(current_time, self.bucket_size)

        # Skip if we already processed this bucket
        if current_bucket == self.last_bucket_processed:
            return

        # Scan for timer registry keys: "timer:registry:{bucket}"
        registry_pattern = "timer:registry:*"
        expired_buckets = []

        cursor = 0
        while True:
            cursor, keys = await self.redis.scan(
                cursor,
                match=registry_pattern,
                count=100
            )

            for key in keys:
                # Parse bucket timestamp from key
                key_str = key.decode() if isinstance(key, bytes) else key
                parts = key_str.split(":")
                if len(parts) < 3:
                    continue

                try:
                    bucket_ts = int(parts[2])
                except (ValueError, IndexError):
                    logger.warning(f"Invalid timer registry key: {key_str}")
                    continue

                # Check if bucket has expired
                if bucket_ts <= current_bucket:
                    expired_buckets.append(bucket_ts)

            if cursor == 0:
                break

        # Emit time advance event for each expired bucket
        if expired_buckets:
            # Sort buckets to process in order
            expired_buckets.sort()

            for bucket_ts in expired_buckets:
                await self._emit_time_advance(bucket_ts, current_time)

                # Delete registry key (bucket processed)
                registry_key = f"timer:registry:{bucket_ts}"
                await self.redis.delete(registry_key.encode())

                logger.info(
                    f"Processed bucket {bucket_ts} "
                    f"({datetime.fromtimestamp(bucket_ts).strftime('%H:%M:%S')})"
                )

            self.last_bucket_processed = current_bucket

    async def _emit_time_advance(self, bucket: int, current_time: float):
        """Emit time advance event to stream"""
        stream_key = default_sharding.get_global_key("timer:time_advance")

        try:
            await self.redis.xadd(
                stream_key.encode(),
                {
                    b"bucket": str(bucket).encode(),
                    b"bucket_time": datetime.fromtimestamp(bucket).isoformat().encode(),
                    b"current_time": str(current_time).encode(),
                    b"timestamp": datetime.utcnow().isoformat().encode(),
                    b"bucket_size": str(self.bucket_size).encode()
                }
            )

            logger.info(
                f"Time advanced to bucket {bucket} "
                f"({datetime.fromtimestamp(bucket).strftime('%Y-%m-%d %H:%M:%S')})"
            )

        except Exception as e:
            logger.error(f"Failed to emit time advance event: {e}", exc_info=True)

    async def process_message(self, stream: str, message_id: str, data: dict) -> bool:
        """Process messages (not used for time advance worker)"""
        # Time advance worker doesn't consume streams
        return True
