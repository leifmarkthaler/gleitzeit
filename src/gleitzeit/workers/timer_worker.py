"""
Dedicated timer worker with leader election for Gleitzeit.

Multiple timer workers can run, but only the elected leader processes timers.
Provides high availability with automatic failover.
"""

import asyncio
import json
import logging
import os
import signal
import socket
import time
import uuid
from typing import Optional

logger = logging.getLogger(__name__)


class TimerWorker:
    """
    Dedicated timer worker with leader election.
    Multiple instances can run, but only the leader processes timers.
    """

    def __init__(self, system_manager, worker_id: Optional[str] = None, priority: int = 0):
        """
        Initialize timer worker.

        Args:
            system_manager: The existing ModularStreamSystemManager instance
            worker_id: Optional worker identifier
            priority: Leadership priority (higher = more likely to be leader)
        """
        self.system_manager = system_manager
        self.redis = system_manager.persistence.redis
        self.worker_id = worker_id or f"timer-{uuid.uuid4().hex[:8]}"
        self.priority = min(max(priority, 0), 10)  # Clamp to 0-10

        # Leadership configuration
        self.is_leader = False
        self.leader_key = "timer:leader"
        self.leader_ttl = 10  # seconds
        self.heartbeat_interval = 3  # seconds
        self.check_interval = 1  # seconds

        # Runtime state
        self._running = False
        self._leader_task = None
        self._shutdown_event = asyncio.Event()
        self.leadership_token = None

        # Metrics
        self.timers_processed = 0
        self.last_timer_check = 0

        # Register shutdown handlers
        signal.signal(signal.SIGTERM, lambda s, f: self._shutdown_event.set())
        signal.signal(signal.SIGINT, lambda s, f: self._shutdown_event.set())

    async def start(self):
        """Start timer worker and participate in election."""
        if self._running:
            return

        self._running = True
        logger.info(f"Starting timer worker {self.worker_id} with priority {self.priority}")

        try:
            # Register as a timer worker
            await self._register_timer_worker()

            # Main loop
            await self._run_loop()

        except Exception as e:
            logger.error(f"Timer worker {self.worker_id} error: {e}")
        finally:
            await self._cleanup()
            self._running = False
            logger.info(f"Timer worker {self.worker_id} stopped")

    async def _register_timer_worker(self):
        """Register this worker as a timer worker."""
        await self.redis.hset(
            "timer:workers",
            self.worker_id,
            json.dumps({
                "started": time.time(),
                "pid": os.getpid(),
                "host": socket.gethostname(),
                "priority": self.priority
            })
        )

    async def _run_loop(self):
        """Main loop - election and timer processing."""

        while self._running and not self._shutdown_event.is_set():
            try:
                if not self.is_leader:
                    # Try to become leader (with priority-based delay)
                    await asyncio.sleep(0.05 * (10 - self.priority))
                    await self._attempt_leadership()

                if self.is_leader:
                    # Process timers as leader
                    await self._process_timers_as_leader()
                else:
                    # Standby mode - monitor health
                    await self._standby_mode()

                # Brief pause between iterations
                await asyncio.sleep(self.check_interval)

            except Exception as e:
                logger.error(f"Timer worker loop error: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def _attempt_leadership(self):
        """Try to become the timer leader."""

        # Atomic set-if-not-exists with TTL
        success = await self.redis.set(
            self.leader_key,
            self.worker_id,
            nx=True,  # Only if not exists
            ex=self.leader_ttl
        )

        if success:
            logger.info(f"Timer worker {self.worker_id} became leader")
            self.is_leader = True
            self.leadership_token = uuid.uuid4().hex

            # Store leadership token for fencing
            await self.redis.set(
                f"{self.leader_key}:token",
                self.leadership_token,
                ex=self.leader_ttl
            )

            # Start heartbeat task
            if self._leader_task:
                self._leader_task.cancel()
            self._leader_task = asyncio.create_task(self._leader_heartbeat())

            # Emit leadership event
            await self._emit_leadership_change()

    async def _leader_heartbeat(self):
        """Maintain leadership with heartbeats."""

        while self.is_leader and self._running:
            try:
                await asyncio.sleep(self.heartbeat_interval)

                # Atomic check-and-extend with Lua script
                lua_script = """
                if redis.call('get', KEYS[1]) == ARGV[1] then
                    redis.call('expire', KEYS[1], ARGV[2])
                    redis.call('expire', KEYS[2], ARGV[2])
                    return 1
                else
                    return 0
                end
                """

                renewed = await self.redis.eval(
                    lua_script,
                    2,
                    self.leader_key,
                    f"{self.leader_key}:token",
                    self.worker_id,
                    self.leader_ttl
                )

                if not renewed:
                    logger.warning(f"Timer worker {self.worker_id} lost leadership")
                    self.is_leader = False
                    self.leadership_token = None

                    # Cancel heartbeat task
                    if self._leader_task:
                        self._leader_task.cancel()
                        self._leader_task = None

            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                self.is_leader = False

    async def _process_timers_as_leader(self):
        """Process expired timers (only when leader)."""

        # Verify leadership with fencing token
        stored_token = await self.redis.get(f"{self.leader_key}:token")
        if not stored_token or stored_token.decode() != self.leadership_token:
            logger.warning(f"Timer worker {self.worker_id} failed fencing check")
            self.is_leader = False
            self.leadership_token = None
            return

        now = time.time()

        # Skip if we checked too recently
        if now - self.last_timer_check < 0.5:
            return
        self.last_timer_check = now

        # Atomic get-and-remove expired timers with Lua script
        lua_script = """
        local expired = redis.call('zrangebyscore', KEYS[1], 0, ARGV[1], 'LIMIT', 0, 100)
        if #expired > 0 then
            redis.call('zrem', KEYS[1], unpack(expired))
        end
        return expired
        """

        try:
            expired = await self.redis.eval(
                lua_script,
                1,
                "timers:pending",
                now
            )

            if expired:
                logger.info(f"Leader {self.worker_id} processing {len(expired)} expired timers")

                # Emit events for expired timers
                for timer_key in expired:
                    if isinstance(timer_key, bytes):
                        timer_key = timer_key.decode()

                    # Extract task_id from timer key
                    # Format: "timer:task:{task_id}" or just "{task_id}"
                    parts = timer_key.split(":")
                    task_id = parts[-1] if parts else timer_key

                    # Add to task:ready stream for regular workers to process
                    await self.redis.xadd(
                        "gleitzeit:events:stream:task:ready",
                        {
                            "event_type": "task:ready",
                            "task_id": task_id,
                            "reason": "timer_expired",
                            "processed_by": self.worker_id,
                            "expired_at": str(now)
                        }
                    )

                    self.timers_processed += 1

                # Update metrics
                await self._update_leader_metrics(len(expired))

        except Exception as e:
            logger.error(f"Error processing timers: {e}", exc_info=True)

    async def _standby_mode(self):
        """Standby mode - monitor leader health and system state."""

        # Update our heartbeat as standby
        await self.redis.hset(
            "timer:workers:heartbeat",
            self.worker_id,
            time.time()
        )

        # Check if leader exists and is healthy
        leader = await self.redis.get(self.leader_key)

        if not leader:
            logger.debug(f"Timer worker {self.worker_id} detected no leader")
        else:
            # Monitor timer backlog for alerting
            await self._monitor_timer_backlog()

    async def _monitor_timer_backlog(self):
        """Monitor timer queue depth for alerting."""

        try:
            now = time.time()
            overdue_count = await self.redis.zcount("timers:pending", 0, now)
            total_count = await self.redis.zcard("timers:pending")

            # Alert if backlog is high
            if overdue_count > 100:
                logger.warning(
                    f"High timer backlog: {overdue_count} overdue, {total_count} total"
                )

                # Emit alert event
                await self.redis.xadd(
                    "gleitzeit:events:stream:alerts",
                    {
                        "event_type": "timer:backlog:high",
                        "overdue": str(overdue_count),
                        "total": str(total_count),
                        "worker": self.worker_id,
                        "timestamp": str(now)
                    },
                    maxlen=1000  # Keep last 1000 alerts
                )

        except Exception as e:
            logger.error(f"Error monitoring backlog: {e}")

    async def _cleanup(self):
        """Clean shutdown."""

        logger.info(f"Timer worker {self.worker_id} shutting down...")

        # Cancel heartbeat task
        if self._leader_task:
            self._leader_task.cancel()
            try:
                await self._leader_task
            except asyncio.CancelledError:
                pass

        # Remove from workers list
        await self.redis.hdel("timer:workers", self.worker_id)
        await self.redis.hdel("timer:workers:heartbeat", self.worker_id)

        # Release leadership gracefully if we have it
        if self.is_leader:
            current = await self.redis.get(self.leader_key)
            if current and current.decode() == self.worker_id:
                await self.redis.delete(self.leader_key)
                await self.redis.delete(f"{self.leader_key}:token")
                logger.info(f"Timer worker {self.worker_id} released leadership")

                # Emit leadership released event
                await self.redis.xadd(
                    "gleitzeit:events:stream:timer:leadership",
                    {
                        "event_type": "timer:leadership:released",
                        "previous_leader": self.worker_id,
                        "timestamp": str(time.time())
                    }
                )

    async def _emit_leadership_change(self):
        """Emit event when leadership changes."""

        await self.redis.xadd(
            "gleitzeit:events:stream:timer:leadership",
            {
                "event_type": "timer:leadership:acquired",
                "new_leader": self.worker_id,
                "priority": str(self.priority),
                "timestamp": str(time.time())
            }
        )

    async def _update_leader_metrics(self, processed_count):
        """Update processing metrics for monitoring."""

        # Update cumulative processed count
        await self.redis.hincrby(
            "timer:metrics:processed",
            self.worker_id,
            processed_count
        )

        # Update last processing time
        await self.redis.hset(
            "timer:metrics:last_run",
            self.worker_id,
            time.time()
        )

        # Update current throughput (timers/sec)
        await self.redis.hset(
            "timer:metrics:throughput",
            self.worker_id,
            processed_count  # Will be averaged over time by monitoring
        )

    async def transfer_leadership(self, target_worker_id: Optional[str] = None):
        """
        Gracefully transfer leadership to another worker.

        Args:
            target_worker_id: Specific worker to transfer to, or None for any
        """
        if not self.is_leader:
            return False

        logger.info(f"Timer worker {self.worker_id} transferring leadership...")

        if target_worker_id:
            # Transfer to specific worker
            success = await self.redis.set(
                self.leader_key,
                target_worker_id,
                xx=True,  # Only if exists (we're leader)
                ex=self.leader_ttl
            )
        else:
            # Just release, let election happen
            await self.redis.delete(self.leader_key)
            await self.redis.delete(f"{self.leader_key}:token")
            success = True

        if success:
            self.is_leader = False
            self.leadership_token = None

            # Cancel heartbeat
            if self._leader_task:
                self._leader_task.cancel()
                self._leader_task = None

            await self._emit_leadership_change()

        return success

    async def get_status(self) -> dict:
        """Get current worker status."""

        return {
            "worker_id": self.worker_id,
            "is_leader": self.is_leader,
            "priority": self.priority,
            "timers_processed": self.timers_processed,
            "uptime": time.time() - self.last_timer_check if self.last_timer_check else 0,
            "leadership_token": self.leadership_token[:8] if self.leadership_token else None
        }