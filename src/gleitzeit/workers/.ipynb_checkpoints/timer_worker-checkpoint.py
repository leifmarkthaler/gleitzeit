"""
Timer worker for Gleitzeit 0.0.7

Handles scheduled task execution and timer-based workflows using the worker architecture.
"""

import asyncio
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import time

from .base import BaseWorker, WorkerConfig
from ..core.sharding import default_sharding
from ..timers.stateless_timer_manager import StatelessTimerManager

logger = logging.getLogger(__name__)


class TimerWorker(BaseWorker):
    """
    Worker that processes timer events and scheduled tasks.

    Features:
    - Scheduled task execution
    - Recurring timers
    - Delay-based task scheduling
    - Leader election for timer processing (only one worker processes timers)
    """

    def __init__(self, config: WorkerConfig):
        super().__init__(config)
        self.timer_manager: Optional[StatelessTimerManager] = None
        self.is_leader = False
        self.leader_key = default_sharding.get_global_key("timer:leader")
        self.leader_ttl = 10  # seconds
        self.last_heartbeat = 0
        self.check_interval = 1  # seconds

    async def on_initialize(self):
        """Initialize timer worker resources"""
        # StatelessTimerManager uses static methods, no initialization needed
        self.timer_manager = StatelessTimerManager

        logger.info(f"TimerWorker initialized")

    def get_base_streams(self) -> List[str]:
        """Return streams this worker consumes from"""
        # Timer worker doesn't consume streams - it monitors Redis sorted sets
        return []

    async def run(self):
        """Enhanced run method with leader election and timer processing"""
        logger.info(f"Worker {self.config.worker_id} starting with consumer group {self.config.consumer_group}")

        self._running = True  # Important: Set running flag!

        # Start leader election task
        election_task = asyncio.create_task(self._leader_election_loop())

        # Start timer processing (only if leader)
        timer_task = asyncio.create_task(self._timer_processing_loop())

        try:
            # Run all tasks
            await asyncio.gather(election_task, timer_task)
        except asyncio.CancelledError:
            logger.info("Worker cancelled")
        finally:
            # Cleanup
            if self.is_leader:
                await self._release_leadership()

    async def _leader_election_loop(self):
        """Participate in leader election for timer processing"""
        logger.info(f"Starting leader election loop for {self.config.worker_id}")
        while self._running:
            try:
                # Try to become leader
                logger.debug(f"Attempting to become leader: {self.config.worker_id}")
                result = await self.redis.set(
                    self.leader_key.encode(),
                    self.config.worker_id.encode(),
                    nx=True,  # Only set if not exists
                    ex=self.leader_ttl
                )

                if result:
                    if not self.is_leader:
                        logger.info(f"Worker {self.config.worker_id} became timer leader")
                        self.is_leader = True
                else:
                    # Check if we're still the leader
                    current_leader = await self.redis.get(self.leader_key.encode())
                    if current_leader and current_leader.decode() == self.config.worker_id:
                        # Extend our leadership
                        await self.redis.expire(self.leader_key.encode(), self.leader_ttl)
                        self.is_leader = True
                    else:
                        if self.is_leader:
                            logger.info(f"Worker {self.config.worker_id} lost timer leadership")
                            self.is_leader = False

                await asyncio.sleep(self.leader_ttl // 3)  # Heartbeat interval

            except Exception as e:
                logger.error(f"Leader election error: {e}")
                await asyncio.sleep(1)

    async def _timer_processing_loop(self):
        """Process timers (only when leader)"""
        import time

        while self._running:
            try:
                if self.is_leader:
                    now = time.time()

                    # Atomic get-and-remove expired timers with Lua script
                    lua_script = """
                    local expired = redis.call('zrangebyscore', KEYS[1], 0, ARGV[1], 'LIMIT', 0, 100)
                    if #expired > 0 then
                        redis.call('zrem', KEYS[1], unpack(expired))
                    end
                    return expired
                    """

                    expired = await self.redis.eval(
                        lua_script,
                        1,
                        default_sharding.get_global_key("timers:pending"),
                        now
                    )

                    if expired:
                        logger.info(f"Processing {len(expired)} expired timers")

                        # Process each expired timer
                        for timer_key in expired:
                            if isinstance(timer_key, bytes):
                                timer_key = timer_key.decode()

                            # Extract task_id from timer key
                            # Format: "timer:task:{task_id}"
                            parts = timer_key.split(":")
                            task_id = parts[-1] if parts else timer_key

                            # Get timer metadata
                            timer_meta = await self.redis.hgetall(default_sharding.get_global_key(f"timer:metadata:{task_id}").encode())

                            if timer_meta:
                                workflow_id = timer_meta.get(b"workflow_id", b"").decode()
                                shard = int(timer_meta.get(b"shard", b"0").decode())

                                # Mark timer task as completed
                                await self._complete_timer_task(task_id, workflow_id, shard)

                await asyncio.sleep(self.check_interval)

            except Exception as e:
                logger.error(f"Timer processing error: {e}")
                await asyncio.sleep(1)

    async def _release_leadership(self):
        """Release leadership when shutting down"""
        if self.is_leader:
            await self.redis.delete(self.leader_key.encode())
            logger.info(f"Worker {self.config.worker_id} released timer leadership")

    async def process_message(self, stream: str, message_id: str, data: Dict):
        """Process timer-related messages"""
        if "timer:schedule" in stream:
            await self._handle_timer_schedule(data)
        elif "timer:cancel" in stream:
            await self._handle_timer_cancel(data)

    async def _handle_timer_schedule(self, data: Dict):
        """Handle timer scheduling request"""
        timer_id = data.get('timer_id')
        workflow_id = data.get('workflow_id')
        task_id = data.get('task_id')
        timer_type = data.get('type', 'delay')  # delay, cron, interval

        if not timer_id or not workflow_id:
            logger.error(f"Invalid timer schedule request: {data}")
            return

        logger.info(f"Scheduling timer {timer_id} for workflow {workflow_id}")

        if timer_type == 'delay':
            # Simple delay timer
            delay_seconds = float(data.get('delay', 60))

            # Use static method to create timer
            created_timer_id = await self.timer_manager.create_timer(
                redis=self.redis,
                workflow_id=workflow_id,
                duration_seconds=delay_seconds,
                task_id=task_id,
                timer_type='delay',
                payload=data.get('metadata', {}),
                timer_id=timer_id
            )

        logger.info(f"Timer {timer_id} scheduled successfully")

    async def _handle_timer_cancel(self, data: Dict):
        """Handle timer cancellation request"""
        timer_id = data.get('timer_id')

        if not timer_id:
            logger.error(f"Invalid timer cancel request: {data}")
            return

        logger.info(f"Cancelling timer {timer_id}")

        # Use static method to cancel timer
        success = await self.timer_manager.cancel_timer(self.redis, timer_id)

        if success:
            logger.info(f"Timer {timer_id} cancelled successfully")
        else:
            logger.warning(f"Timer {timer_id} not found or already fired")

    async def _complete_timer_task(self, task_id: str, workflow_id: str, shard: int):
        """Mark timer task as completed and emit completion event"""
        logger.info(f"Completing timer task {task_id} for workflow {workflow_id}")

        # Mark timer task as completed
        await self.redis.hset(
            default_sharding.get_task_key(task_id, workflow_id).encode(),
            mapping={
                b"status": b"completed",
                b"timer_fired_at": datetime.utcnow().isoformat().encode(),
                b"result": json.dumps({"timer_fired": True, "message": "Timer expired"}).encode()
            }
        )

        # Emit completion event to dependency worker
        await self.redis.xadd(
            default_sharding.get_stream_key("task:completed", workflow_id).encode(),
            {
                b"workflow_id": workflow_id.encode(),
                b"task_id": task_id.encode(),
                b"result": json.dumps({"timer_fired": True}).encode(),
                b"timestamp": datetime.utcnow().isoformat().encode()
            }
        )

        logger.info(f"Timer task {task_id} marked as completed and event emitted to shard {shard}")