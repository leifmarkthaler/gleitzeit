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
from ..core.leader_election import LeaderElection, LeaderStatus

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
        self.leader_election: Optional[LeaderElection] = None
        self.leader_key = default_sharding.get_global_key("timer:leader")
        self.leader_ttl = 10  # seconds
        self.last_heartbeat = 0
        self.check_interval = 1  # seconds

    async def on_initialize(self):
        """Initialize timer worker resources"""
        # StatelessTimerManager uses static methods, no initialization needed
        self.timer_manager = StatelessTimerManager

        # Initialize atomic leader election
        self.leader_election = LeaderElection(
            self.redis,
            self.leader_key,
            self.config.worker_id,
            self.leader_ttl
        )

        logger.info(f"TimerWorker initialized with atomic leader election")

    def get_base_streams(self) -> List[str]:
        """Return streams this worker consumes from"""
        # Timer worker is stateless - monitors sorted sets, not streams
        return []

    async def run(self):
        """Enhanced run method with leader election and timer processing"""
        logger.info(f"Worker {self.config.worker_id} starting with consumer group {self.config.consumer_group}")

        self._running = True  # Important: Set running flag!

        # Start heartbeat task (includes worker registration and command checking)
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        # Start leader election task
        election_task = asyncio.create_task(self._leader_election_loop())

        # Start timer processing (only if leader)
        timer_task = asyncio.create_task(self._timer_processing_loop())

        try:
            # Run all tasks
            await asyncio.gather(heartbeat_task, election_task, timer_task)
        except asyncio.CancelledError:
            logger.info("Worker cancelled")
        finally:
            # Cleanup
            heartbeat_task.cancel()
            if self.leader_election and self.leader_election.is_leader:
                await self.leader_election.release()

    async def _leader_election_loop(self):
        """Participate in atomic leader election for timer processing"""
        logger.info(f"Starting atomic leader election loop for {self.config.worker_id}")
        while self._running:
            try:
                # Atomic leader election
                status = await self.leader_election.try_elect()

                if status == LeaderStatus.BECAME_LEADER:
                    logger.info(f"Worker {self.config.worker_id} became timer leader")
                elif status == LeaderStatus.LOST_LEADERSHIP:
                    logger.info(f"Worker {self.config.worker_id} lost timer leadership")

                await asyncio.sleep(self.leader_ttl // 3)  # Heartbeat interval

            except Exception as e:
                logger.error(f"Leader election error: {e}")
                await asyncio.sleep(1)

    async def _timer_processing_loop(self):
        """Process timers (only when leader)"""
        import time

        while self._running:
            try:
                if self.leader_election and self.leader_election.is_leader:
                    # Use StatelessTimerManager's comprehensive processing
                    # This handles: cancellation checks, recurring timers, metadata updates
                    processed, fired_timers = await StatelessTimerManager.process_due_timers(
                        self.redis,
                        max_timers=100
                    )

                    if fired_timers:
                        logger.info(f"Processing {len(fired_timers)} expired timers")

                        # Process each fired timer
                        for timer_data in fired_timers:
                            timer_id = timer_data['timer_id']
                            task_id = timer_data.get('task_id', '')
                            workflow_id = timer_data.get('workflow_id', '')

                            if not task_id or not workflow_id:
                                logger.warning(f"Timer {timer_id} missing task_id or workflow_id, skipping")
                                continue

                            # Check if this is a retry timer
                            # Format: "{workflow_id}:{task_id}:retry"
                            if ":retry" in timer_id:
                                await self._handle_retry_timer(task_id, workflow_id)
                            else:
                                # Regular timer - pass timer_data for enriched results
                                shard = default_sharding.get_shard(workflow_id)
                                await self._complete_timer_task(
                                    task_id,
                                    workflow_id,
                                    shard,
                                    timer_data  # Pass full timer data
                                )

                await asyncio.sleep(self.check_interval)

            except Exception as e:
                logger.error(f"Timer processing error: {e}")
                await asyncio.sleep(1)

    async def _release_leadership(self):
        """Release leadership when shutting down"""
        if self.is_leader:
            await self.redis.delete(self.leader_key.encode())
            logger.info(f"Worker {self.config.worker_id} released timer leadership")

    async def process_message(self, stream: str, message_id: str, data: Dict) -> bool:
        """Process timer-related messages (not used in stateless mode)

        Returns:
            True if message was processed successfully and should be ACK'd
            False if message failed and should not be ACK'd
        """
        try:
            if "timer:schedule" in stream:
                await self._handle_timer_schedule(data)
            elif "timer:cancel" in stream:
                await self._handle_timer_cancel(data)
            return True  # Successfully processed
        except Exception as e:
            logger.error(f"Error processing timer message: {e}", exc_info=True)
            return False  # Don't ACK, leave for retry

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

    async def _complete_timer_task(
        self,
        task_id: str,
        workflow_id: str,
        shard: int,
        timer_data: Dict = None
    ):
        """
        Mark timer task as completed and emit completion event.

        This method validates the task state before marking it complete to prevent
        marking cancelled or already-completed tasks. It also enriches the result
        data with timer metadata for better debugging and monitoring.

        Args:
            task_id: Task identifier
            workflow_id: Workflow identifier
            shard: Shard number for the workflow
            timer_data: Optional timer metadata dict containing:
                - timer_type: Type of timer (sleep, wait_until, schedule)
                - duration_seconds: Original timer duration
                - scheduled_time: When timer was scheduled
                - fired_at: When timer actually fired
                - created_at: Timer creation timestamp

        Returns:
            None (updates Redis and emits event)

        Note:
            Skips completion if task no longer exists or is already
            cancelled/completed/failed.
        """

        # Validate task state before completion
        task_key = default_sharding.get_task_key(task_id, workflow_id)
        task_state = await self.redis.hgetall(task_key.encode())

        if not task_state:
            logger.warning(f"Task {task_id} no longer exists, skipping timer completion")
            return

        current_status = task_state.get(b"status", b"").decode()
        if current_status in ["cancelled", "completed", "failed"]:
            logger.info(f"Task {task_id} is {current_status}, skipping timer completion")
            return

        logger.info(f"Completing timer task {task_id} for workflow {workflow_id}")

        # Build enriched result with timer metadata
        result_data = {"timer_fired": True, "message": "Timer expired"}

        if timer_data:
            result_data.update({
                "timer_type": timer_data.get('timer_type', 'unknown'),
                "duration_seconds": timer_data.get('duration_seconds', 0),
                "scheduled_time": timer_data.get('scheduled_time'),
                "fired_at": timer_data.get('fired_at'),
                "created_at": timer_data.get('created_at')
            })

        # Mark timer task as completed
        completion_time = datetime.utcnow().isoformat()
        await self.redis.hset(
            task_key.encode(),
            mapping={
                b"status": b"completed",
                b"completed_at": completion_time.encode(),
                b"timer_fired_at": completion_time.encode(),
                b"result": json.dumps(result_data).encode()
            }
        )

        # Emit completion event to dependency worker
        await self.redis.xadd(
            default_sharding.get_stream_key("task:completed", workflow_id).encode(),
            {
                b"workflow_id": workflow_id.encode(),
                b"task_id": task_id.encode(),
                b"result": json.dumps(result_data).encode(),
                b"timestamp": datetime.utcnow().isoformat().encode()
            }
        )

        logger.info(f"Timer task {task_id} marked as completed and event emitted to shard {shard}")

    async def _handle_retry_timer(
        self,
        task_id: str,
        workflow_id: str
    ):
        """Handle expired retry timer - put task back in ready queue"""
        logger.info(f"Retry timer expired for task {task_id} in workflow {workflow_id}")

        # Get workflow data to extract task definition
        workflow_data = await self.redis.hget(
            default_sharding.get_workflow_key("data", workflow_id).encode(),
            b"workflow"
        )

        if not workflow_data:
            logger.error(f"Workflow data not found for retry: {workflow_id}")
            return

        import json
        workflow = json.loads(workflow_data)

        # Find the task in the workflow
        task_data = None
        for task in workflow.get('tasks', []):
            if task['id'] == task_id:
                task_data = task
                break

        if not task_data:
            logger.error(f"Task {task_id} not found in workflow {workflow_id}")
            return

        # Update task status back to pending
        task_key = default_sharding.get_task_key(task_id, workflow_id).encode()
        await self.redis.hset(
            task_key,
            b"status", b"pending"
        )

        # Put task back in ready queue (same as DependencyWorker)
        ready_stream = default_sharding.get_stream_key("task:ready", workflow_id).encode()
        await self.redis.xadd(
            ready_stream,
            {
                b"workflow_id": workflow_id.encode(),
                b"task_id": task_id.encode(),
                b"task": json.dumps(task_data).encode(),
                b"timestamp": datetime.utcnow().isoformat().encode()
            }
        )

        logger.info(f"Task {task_id} re-queued to task:ready stream")