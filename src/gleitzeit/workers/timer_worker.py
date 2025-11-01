"""
Timer worker for Gleitzeit 0.0.7

Simple, direct-scanning timer system.
No buckets, no time_advance events, just scan and fire.
"""

import asyncio
import json
import logging
import os
from typing import Dict, Any, List, Optional
from datetime import datetime
import time

from .base import BaseWorker, WorkerConfig
from ..core.sharding import default_sharding
from ..core.events import EventType
from ..core.event_store import EventStore, EventLevel

logger = logging.getLogger(__name__)


class TimerWorker(BaseWorker):
    """
    Worker that scans for expired timers and fires them.

    Features:
    - Scans all timer metadata every 1 second
    - Fires timers where wake_time <= current_time
    - Atomic check-and-delete using Lua script (prevents duplicate firing)
    - Full audit trail for every timer
    - No buckets, no registry keys, no TTLs
    - Handles both regular timers and retry timers
    """

    def __init__(self, config: WorkerConfig):
        super().__init__(config)
        self.timers_fired = 0
        self.scan_interval = 1.0  # Scan every 1 second
        self.lua_script = None
        self.lua_script_sha = None

    async def on_initialize(self):
        """Initialize timer worker resources"""
        # Initialize event store for publishing timer events
        self.event_store = EventStore(self.redis, config={
            'max_events_per_workflow': 10000,
            'event_ttl_seconds': 86400 * 30  # 30 days
        })

        # Load and register Lua script for atomic timer deletion
        await self._load_lua_script()

        logger.info(f"TimerWorker initialized (direct-scan mode, {self.scan_interval}s interval)")

    async def _load_lua_script(self):
        """Load Lua script for atomic timer check-and-delete"""
        script_path = os.path.join(
            os.path.dirname(__file__),
            'lua',
            'get_and_delete_timer_if_expired.lua'
        )

        try:
            with open(script_path, 'r') as f:
                self.lua_script = f.read()

            # Register script with Redis
            self.lua_script_sha = await self.redis.script_load(self.lua_script.encode())
            # script_load may return bytes or str depending on Redis client
            sha_str = self.lua_script_sha.decode() if isinstance(self.lua_script_sha, bytes) else self.lua_script_sha
            logger.info(f"Loaded Lua script: {sha_str}")

        except FileNotFoundError:
            logger.error(f"Lua script not found at {script_path}")
            raise
        except Exception as e:
            logger.error(f"Failed to load Lua script: {e}")
            raise

    def get_base_streams(self) -> List[str]:
        """Return streams this worker consumes from"""
        # Timer worker doesn't consume streams - it scans metadata directly
        return []

    async def process_message(
        self,
        stream: str,
        message_id: str,
        data: Dict
    ) -> bool:
        """Timer worker doesn't process stream messages"""
        # This method is required by BaseWorker but not used by TimerWorker
        # since we scan metadata directly instead of consuming streams
        return True

    async def run(self):
        """Main worker loop - scan for expired timers every second"""
        logger.info(f"Worker {self.config.worker_id} starting timer scan loop")

        self._running = True

        # Start heartbeat task (includes worker registration)
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        # Start timer scanning task
        scan_task = asyncio.create_task(self._timer_scan_loop())

        try:
            # Wait for tasks
            await asyncio.gather(heartbeat_task, scan_task)
        except asyncio.CancelledError:
            logger.info(f"Worker {self.config.worker_id} cancelled")
        finally:
            self._running = False
            await self._cleanup()

    async def _timer_scan_loop(self):
        """Continuously scan for expired timers"""
        logger.info("Timer scan loop started")

        while self._running:
            try:
                current_time = time.time()
                await self._scan_all_shards_for_expired_timers(current_time)
                await asyncio.sleep(self.scan_interval)

            except Exception as e:
                logger.error(f"Error in timer scan loop: {e}", exc_info=True)
                await self.log_worker_error("timer_scan_loop", e)
                await asyncio.sleep(self.scan_interval)

        logger.info("Timer scan loop ended")

    async def _scan_all_shards_for_expired_timers(self, current_time: float):
        """Scan all shards for expired timers"""
        fired_count = 0

        for shard in range(16):  # Assuming 16 shards
            shard_fired = await self._scan_shard_for_expired_timers(shard, current_time)
            fired_count += shard_fired

        if fired_count > 0:
            self.timers_fired += fired_count
            logger.info(f"Fired {fired_count} timers (total: {self.timers_fired})")

    async def _scan_shard_for_expired_timers(self, shard: int, current_time: float) -> int:
        """Scan one shard for expired timers"""
        pattern = f"{{shard:{shard}}}:timer:metadata:*"
        fired_count = 0

        cursor = 0
        while True:
            try:
                cursor, keys = await self.redis.scan(
                    cursor,
                    match=pattern.encode(),
                    count=100
                )

                # Process each timer key atomically
                for key in keys:
                    metadata = await self._try_fire_timer(key, current_time)
                    if metadata:
                        fired_count += 1

                if cursor == 0:
                    break

            except Exception as e:
                logger.error(f"Error scanning shard {shard}: {e}", exc_info=True)
                break

        return fired_count

    async def _try_fire_timer(self, key: bytes, current_time: float) -> Optional[Dict]:
        """
        Atomically check if timer is expired and delete it.
        Returns metadata if timer was fired, None otherwise.
        """
        try:
            # Use Lua script for atomic check-and-delete
            result = await self.redis.evalsha(
                self.lua_script_sha,
                1,
                key,
                str(current_time).encode()
            )

            if not result:
                # Timer not expired or already deleted by another worker
                return None

            # Parse metadata from Lua result (list of alternating keys/values)
            metadata = {}
            for i in range(0, len(result), 2):
                k = result[i].decode() if isinstance(result[i], bytes) else result[i]
                v = result[i+1].decode() if isinstance(result[i+1], bytes) else result[i+1]
                metadata[k] = v

            # Fire the timer
            await self._fire_timer(metadata)

            return metadata

        except Exception as e:
            logger.error(f"Error firing timer {key}: {e}", exc_info=True)
            await self.log_worker_error("try_fire_timer", e, timer_key=key.decode())
            return None

    async def _fire_timer(self, metadata: Dict[str, str]):
        """Fire an expired timer"""
        workflow_id = metadata.get('workflow_id')
        task_id = metadata.get('task_id')
        timer_type = metadata.get('timer_type', 'sleep')
        wake_time = float(metadata.get('wake_time', 0))

        if not workflow_id or not task_id:
            logger.warning(f"Invalid timer metadata: missing workflow_id or task_id")
            return

        logger.info(
            f"Firing {timer_type} timer for task {task_id} "
            f"(wake_time={datetime.fromtimestamp(wake_time).isoformat()})"
        )

        # Emit TIMER_FIRED event for audit
        await self.event_store.store_event(
            event_type=EventType.TIMER_FIRED,
            workflow_id=workflow_id,
            task_id=task_id,
            level=EventLevel.IMPORTANT,
            data={
                'timer_type': timer_type,
                'wake_time': wake_time,
                'fired_at': time.time(),
                'scheduled_at': metadata.get('created_at')
            }
        )

        # Process based on timer type
        if timer_type == "retry":
            await self._handle_retry_timer(workflow_id, task_id, metadata)
        else:
            await self._complete_timer_task(workflow_id, task_id, metadata)

        # Remove from pending set
        pending_key = default_sharding.get_timer_key("pending", workflow_id)
        await self.redis.srem(pending_key.encode(), task_id.encode())

    async def _complete_timer_task(
        self,
        workflow_id: str,
        task_id: str,
        metadata: Dict[str, str]
    ):
        """
        Mark timer task as completed and emit completion event.
        """
        logger.info(f"Completing timer task {task_id} for workflow {workflow_id}")

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

        # Build result data
        timer_type = metadata.get('timer_type', 'sleep')
        result_data = {
            "timer_fired": True,
            "timer_type": timer_type,
            "fired_at": datetime.utcnow().isoformat()
        }

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

        logger.info(f"Timer task {task_id} marked as completed and event emitted")

    async def _handle_retry_timer(
        self,
        workflow_id: str,
        task_id: str,
        metadata: Dict[str, str]
    ):
        """
        Handle expired retry timer - re-queue task to ready stream.
        """
        logger.info(f"Retry timer expired for task {task_id} in workflow {workflow_id}")

        # Get workflow data to extract task definition
        workflow_data = await self.redis.hget(
            default_sharding.get_workflow_key("data", workflow_id).encode(),
            b"workflow"
        )

        if not workflow_data:
            logger.error(f"Workflow data not found for retry: {workflow_id}")
            return

        try:
            workflow = json.loads(workflow_data)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse workflow data: {e}")
            return

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

        # Put task back in ready queue
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

        logger.info(f"Task {task_id} re-queued to task:ready stream for retry")
