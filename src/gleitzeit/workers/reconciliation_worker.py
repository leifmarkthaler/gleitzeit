"""
Workflow State Reconciliation Worker

Periodically scans workflows and ensures state consistency.
Fixes workflows stuck in incorrect states due to worker crashes.
"""

import asyncio
import logging
import json
import uuid
from typing import Dict, List, Optional
from datetime import datetime
from contextlib import asynccontextmanager

from .base import BaseWorker, WorkerConfig
from ..core.models import WorkflowStatus
from ..core.sharding import default_sharding

logger = logging.getLogger(__name__)


class LockAcquisitionError(Exception):
    """Raised when unable to acquire distributed lock"""
    pass


class ReconciliationLock:
    """Context manager for distributed shard lock"""

    def __init__(self, redis, lock_key: str, lock_value: str, ttl: int):
        self.redis = redis
        self.lock_key = lock_key
        self.lock_value = lock_value
        self.ttl = ttl
        self._released = False

    async def release(self):
        """Release the lock if we still own it"""
        if self._released:
            return

        # Use Lua script to ensure we only delete our own lock
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """

        try:
            await self.redis.eval(
                lua_script.encode(),
                1,
                self.lock_key.encode(),
                self.lock_value.encode()
            )
            self._released = True
            logger.debug(f"Released lock {self.lock_key}")
        except Exception as e:
            logger.warning(f"Failed to release lock {self.lock_key}: {e}")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.release()


class WorkflowReconciliationWorker(BaseWorker):
    """
    Periodically scans workflows and fixes inconsistent states.

    Unlike other workers that consume Redis Streams, this worker:
    - Runs on a timer-based loop (configurable interval)
    - Scans all shards for running workflows
    - Uses distributed locks to coordinate with other instances
    - Fixes inconsistencies found in workflow states

    Reconciliation Checks:
    1. Task count consistency - Recalculates if counts don't match reality
    2. Hard fail policy - Marks workflows as failed if any task failed
    3. Completion detection - Marks workflows as completed when all tasks done
    4. Zombie detection - Identifies workflows stuck with no activity
    """

    # Configuration defaults
    SCAN_INTERVAL = 60  # seconds between scans
    BATCH_SIZE = 100  # workflows per batch
    LOCK_TTL = 120  # seconds for distributed lock
    ZOMBIE_THRESHOLD = 600  # 10 minutes of inactivity
    MAX_CONCURRENT = 5  # max workflows to reconcile concurrently

    def __init__(self, config: WorkerConfig):
        super().__init__(config)

        # Load configuration from config.extra or use defaults
        self.scan_interval = config.extra.get('scan_interval', self.SCAN_INTERVAL)
        self.batch_size = config.extra.get('batch_size', self.BATCH_SIZE)
        self.lock_ttl = config.extra.get('lock_ttl', self.LOCK_TTL)
        self.zombie_threshold = config.extra.get('zombie_threshold', self.ZOMBIE_THRESHOLD)
        self.max_concurrent_reconciliations = config.extra.get('max_concurrent', self.MAX_CONCURRENT)

        # Bug #19: Removed in-memory metrics - worker is now stateless
        # Use structured logging via LoggingMixin for observability

        # Reconciliation semaphore
        self._reconciliation_semaphore = asyncio.Semaphore(self.max_concurrent_reconciliations)

    async def on_initialize(self):
        """Initialize worker resources"""
        logger.info(
            f"WorkflowReconciliationWorker initialized: "
            f"scan_interval={self.scan_interval}s, "
            f"batch_size={self.batch_size}, "
            f"shards={self.assigned_shards}"
        )

    def get_base_streams(self) -> List[str]:
        """
        This worker doesn't consume streams - it uses timer-based scanning.
        Return empty list to satisfy BaseWorker interface.
        """
        return []

    async def process_message(self, stream: str, message_id: str, data: Dict) -> bool:
        """
        This worker doesn't process messages from streams.
        Return True to satisfy BaseWorker interface.
        """
        return True

    async def run(self):
        """
        Main reconciliation loop - timer-based instead of stream-based.

        Overrides BaseWorker.run() to implement custom timer loop.
        """
        self._running = True

        # Setup graceful shutdown
        import signal
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_shutdown)

        # Start heartbeat task
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        try:
            # Initial delay to let system stabilize
            await asyncio.sleep(5)

            while self._running:
                try:
                    scan_start = datetime.utcnow()

                    # Reconcile all assigned shards
                    await self.reconcile_all_shards()

                    scan_duration = (datetime.utcnow() - scan_start).total_seconds()

                    await self.log_worker_info(
                        "reconciliation_cycle_completed",
                        f"Reconciliation cycle completed in {scan_duration:.2f}s",
                        scan_duration=scan_duration
                    )

                    # Wait for next scan interval
                    await asyncio.sleep(self.scan_interval)

                except Exception as e:
                    await self.log_worker_error(
                        "reconciliation_cycle_failed",
                        e
                    )
                    # Wait before retrying
                    await asyncio.sleep(10)

        finally:
            self._running = False
            heartbeat_task.cancel()
            await self._cleanup()

    async def reconcile_all_shards(self):
        """Scan and reconcile all assigned shards"""
        logger.debug(f"Starting reconciliation scan for {len(self.assigned_shards)} shards")
        for shard in self.assigned_shards:
            try:
                async with self.acquire_shard_lock(shard):
                    # Bug #16: Scan multiple workflow statuses, not just running
                    await self.reconcile_shard(shard, status='running')
                    await self.reconcile_shard(shard, status='waiting')
            except LockAcquisitionError:
                # Another worker is handling this shard
                logger.debug(f"Could not acquire lock for shard {shard}, skipping")
                continue
            except Exception as e:
                logger.error(f"Error reconciling shard {shard}: {e}", exc_info=True)
                await self.log_worker_error(
                    "shard_reconciliation_failed",
                    e,
                    shard=shard
                )
        logger.debug("Reconciliation scan completed")

    @asynccontextmanager
    async def acquire_shard_lock(self, shard: int):
        """
        Acquire distributed lock for shard reconciliation.

        Uses Redis SET NX EX pattern with unique lock value.
        """
        lock_key = f"{{shard:{shard}}}:reconciliation:lock"
        lock_value = f"{self.config.worker_id}:{uuid.uuid4()}"

        # Try to acquire lock
        acquired = await self.redis.set(
            lock_key.encode(),
            lock_value.encode(),
            nx=True,  # Only set if not exists
            ex=self.lock_ttl  # Expire after TTL
        )

        if not acquired:
            raise LockAcquisitionError(f"Could not acquire lock for shard {shard}")

        logger.debug(f"Acquired reconciliation lock for shard {shard}")

        lock = ReconciliationLock(self.redis, lock_key, lock_value, self.lock_ttl)

        try:
            yield lock
        finally:
            await lock.release()

    async def reconcile_shard(self, shard: int, status: str = 'running'):
        """Reconcile workflows with specific status on a shard (Bug #16)"""
        offset = 0
        shard_workflows_scanned = 0

        while True:
            # Scan for workflows with given status
            workflow_ids = await self.scan_workflows_by_status(shard, status, offset, self.batch_size)

            if not workflow_ids:
                break

            # Reconcile workflows concurrently (with semaphore limit)
            tasks = []
            for workflow_id in workflow_ids:
                task = asyncio.create_task(
                    self._reconcile_workflow_with_semaphore(workflow_id, shard)
                )
                tasks.append(task)

            # Wait for batch to complete
            await asyncio.gather(*tasks, return_exceptions=True)

            shard_workflows_scanned += len(workflow_ids)
            offset += self.batch_size

        logger.debug(f"Shard {shard} status={status} reconciliation: {shard_workflows_scanned} workflows scanned")

    async def _reconcile_workflow_with_semaphore(self, workflow_id: str, shard: int):
        """Reconcile workflow with concurrency control"""
        async with self._reconciliation_semaphore:
            await self.reconcile_workflow(workflow_id, shard)

    async def scan_workflows_by_status(
        self, shard: int, status: str, offset: int, limit: int
    ) -> List[str]:
        """
        Scan for workflows with specific status on a shard (Bug #16).

        Uses sorted set for efficient scanning:
        {shard:N}:workflows:by_status:{status}
        """
        key = f"{{shard:{shard}}}:workflows:by_status:{status}"

        try:
            workflow_ids = await self.redis.zrange(
                key.encode(),
                offset,
                offset + limit - 1
            )

            return [wf_id.decode() for wf_id in workflow_ids]
        except Exception as e:
            logger.error(f"Failed to scan {status} workflows on shard {shard}: {e}")
            return []

    async def reconcile_workflow(self, workflow_id: str, shard: int):
        """
        Reconcile a single workflow.

        Performs all consistency checks and fixes inconsistencies.
        """
        try:
            # Get workflow state
            workflow = await self.get_workflow(workflow_id, shard)
            if not workflow:
                logger.warning(f"Workflow {workflow_id} not found during reconciliation")
                return

            # Bug #10: Use WorkflowStatus enum instead of hardcoded string
            status_bytes = workflow.get(b'status', b'unknown')
            status_str = status_bytes.decode() if isinstance(status_bytes, bytes) else str(status_bytes)

            if status_str != WorkflowStatus.RUNNING.value:
                return

            # Run consistency checks
            inconsistencies = await self.check_workflow_consistency(workflow_id, workflow, shard)

            if inconsistencies:
                await self.log_worker_warning(
                    "workflow_inconsistency_detected",
                    f"Workflow {workflow_id} has {len(inconsistencies)} inconsistencies",
                    workflow_id=workflow_id,
                    shard=shard,
                    inconsistencies=inconsistencies
                )

                # Fix inconsistencies
                await self.fix_workflow_state(workflow_id, workflow, inconsistencies, shard)

                await self.log_worker_info(
                    "workflow_reconciled",
                    f"Workflow {workflow_id} reconciled successfully",
                    workflow_id=workflow_id,
                    shard=shard,
                    fixes_applied=len(inconsistencies)
                )

        except Exception as e:
            await self.log_worker_error(
                "reconciliation_failed",
                e,
                workflow_id=workflow_id,
                shard=shard
            )

    async def get_workflow(self, workflow_id: str, shard: int) -> Optional[Dict]:
        """Get workflow state from Redis"""
        # Bug #1: Fix key pattern to use get_workflow_key helper
        key = default_sharding.get_workflow_key("state", workflow_id)

        try:
            workflow_data = await self.redis.hgetall(key.encode())
            return workflow_data if workflow_data else None
        except Exception as e:
            logger.error(f"Failed to get workflow {workflow_id}: {e}")
            return None

    async def check_workflow_consistency(
        self, workflow_id: str, workflow: Dict, shard: int
    ) -> List[str]:
        """
        Check workflow for inconsistencies.

        Returns:
            List of inconsistency descriptions
        """
        inconsistencies = []

        # Parse workflow counts
        def get_int(key: bytes, default: int = 0) -> int:
            val = workflow.get(key, b'0')
            if isinstance(val, bytes):
                val = val.decode()
            return int(val) if val else default

        total_tasks = get_int(b'total_tasks', 0)
        completed_tasks = get_int(b'completed_tasks', 0)
        failed_tasks = get_int(b'failed_tasks', 0)
        running_tasks = get_int(b'running_tasks', 0)
        pending_tasks = get_int(b'pending_tasks', 0)
        # Bug #2, #4, #9: Extract all task counters
        waiting_tasks = get_int(b'waiting_tasks', 0)
        blocked_tasks = get_int(b'blocked_tasks', 0)
        skipped_tasks = get_int(b'skipped_tasks', 0)

        # Check 1: Task count consistency (include all counters)
        total_accounted = (completed_tasks + failed_tasks + running_tasks +
                          pending_tasks + waiting_tasks + blocked_tasks + skipped_tasks)
        if total_accounted != total_tasks:
            inconsistencies.append(
                f"task_count_mismatch: total={total_tasks} but "
                f"accounted={total_accounted} "
                f"(completed={completed_tasks}, failed={failed_tasks}, "
                f"running={running_tasks}, pending={pending_tasks}, "
                f"waiting={waiting_tasks}, blocked={blocked_tasks}, skipped={skipped_tasks})"
            )

        # Check 2: Hard fail policy enforcement
        if failed_tasks > 0:
            inconsistencies.append(
                f"hard_fail_policy: workflow has {failed_tasks} failed tasks "
                f"but status is still 'running'"
            )

        # Check 3: Completion detection
        if completed_tasks == total_tasks and total_tasks > 0 and failed_tasks == 0:
            inconsistencies.append(
                f"completion_undetected: all {total_tasks} tasks completed "
                f"but status is still 'running'"
            )

        # Bug #3: Fix zombie detection to account for waiting tasks
        # Check 4: Zombie workflow detection
        if (running_tasks == 0 and pending_tasks == 0 and waiting_tasks == 0 and
            completed_tasks < total_tasks):
            # No active tasks but workflow incomplete - check last activity
            last_activity = await self.get_last_workflow_activity(workflow_id, shard)
            if last_activity:
                time_since_activity = (datetime.utcnow() - last_activity).total_seconds()
                if time_since_activity > self.zombie_threshold:
                    inconsistencies.append(
                        f"zombie_workflow: no active tasks for {time_since_activity:.0f}s "
                        f"(threshold={self.zombie_threshold}s)"
                    )

        # Get scheduled tasks count
        scheduled_tasks = get_int(b'scheduled_tasks', 0)

        # Bug #6: Check if workflow should transition to waiting status
        if running_tasks == 0 and pending_tasks == 0 and waiting_tasks > 0 and scheduled_tasks == 0:
            inconsistencies.append(
                f"status_should_be_waiting: workflow has {waiting_tasks} waiting tasks "
                f"but status is 'running'"
            )

        # Check if workflow should transition to scheduled status
        if running_tasks == 0 and pending_tasks == 0 and waiting_tasks == 0 and scheduled_tasks > 0:
            inconsistencies.append(
                f"status_should_be_scheduled: workflow has {scheduled_tasks} scheduled tasks "
                f"but status is 'running'"
            )

        return inconsistencies

    async def fix_workflow_state(
        self, workflow_id: str, workflow: Dict, inconsistencies: List[str], shard: int
    ):
        """Fix workflow state based on detected inconsistencies"""

        # Check what needs fixing
        has_task_count_mismatch = any('task_count_mismatch' in i for i in inconsistencies)
        has_failed_tasks = any('hard_fail_policy' in i for i in inconsistencies)
        is_completed = any('completion_undetected' in i for i in inconsistencies)
        is_zombie = any('zombie_workflow' in i for i in inconsistencies)
        should_be_waiting = any('status_should_be_waiting' in i for i in inconsistencies)
        should_be_scheduled = any('status_should_be_scheduled' in i for i in inconsistencies)

        # Recalculate task counts if mismatch detected
        if has_task_count_mismatch:
            await self.recalculate_task_counts(workflow_id, shard)
            # Re-fetch workflow after recalculation
            workflow = await self.get_workflow(workflow_id, shard)
            if not workflow:
                return

        # Apply state fixes (priority order matters)
        if has_failed_tasks:
            # Enforce hard fail policy
            await self.mark_workflow_failed(
                workflow_id,
                shard,
                reason="Task failure detected during reconciliation"
            )
        elif is_completed:
            # Mark as completed
            await self.mark_workflow_completed(workflow_id, shard)
        elif is_zombie:
            # Mark as stalled/failed
            await self.mark_workflow_failed(
                workflow_id,
                shard,
                reason="Workflow stalled with no activity"
            )
        elif should_be_scheduled:
            # Transition to scheduled status
            await self.mark_workflow_scheduled(workflow_id, shard)
        elif should_be_waiting:
            # Bug #6: Transition to waiting status
            await self.mark_workflow_waiting(workflow_id, shard)

    async def recalculate_task_counts(self, workflow_id: str, shard: int):
        """
        Recalculate workflow task counts from actual task states.
        """
        try:
            # Bug #15: Get all task IDs from workflow data (not from a non-existent set)
            task_ids = await self.get_workflow_task_ids(workflow_id, shard)

            # Bug #7: Track all task statuses, not just 5
            counts = {
                'pending': 0,
                'running': 0,      # Also includes: executing, queued, routed, validating
                'completed': 0,
                'failed': 0,
                'waiting': 0,      # Also includes: waiting_signal
                'scheduled': 0,    # Timer/scheduled tasks
                'blocked': 0,
                'skipped': 0,
                'cancelled': 0,
                'paused': 0,
                'other': 0
            }

            # Fetch actual task states
            for task_id in task_ids:
                task = await self.get_task(task_id, workflow_id, shard)
                if task:
                    status = task.get(b'status', b'pending').decode() if isinstance(task.get(b'status'), bytes) else task.get('status', 'pending')

                    # Map status to workflow counter (with status aliasing)
                    if status == 'pending':
                        counts['pending'] += 1
                    elif status in ['running', 'executing', 'queued', 'routed', 'validating']:
                        counts['running'] += 1
                    elif status in ['waiting', 'waiting_signal']:
                        counts['waiting'] += 1
                    elif status in ['scheduled', 'sleeping']:
                        counts['scheduled'] += 1
                    elif status == 'completed':
                        counts['completed'] += 1
                    elif status == 'failed':
                        counts['failed'] += 1
                    elif status == 'blocked':
                        counts['blocked'] += 1
                    elif status == 'skipped':
                        counts['skipped'] += 1
                    elif status == 'cancelled':
                        counts['cancelled'] += 1
                    elif status in ['paused', 'retry_pending', 'rewound']:
                        counts['paused'] += 1
                    else:
                        counts['other'] += 1
                        logger.warning(f"Unknown task status '{status}' for task {task_id} in workflow {workflow_id}")

            # Bug #1: Use helper for workflow key
            workflow_key = default_sharding.get_workflow_key("state", workflow_id)

            # Bug #17: Always update timestamp
            await self.redis.hset(
                workflow_key.encode(),
                mapping={
                    b'pending_tasks': str(counts['pending']).encode(),
                    b'running_tasks': str(counts['running']).encode(),
                    b'completed_tasks': str(counts['completed']).encode(),
                    b'failed_tasks': str(counts['failed']).encode(),
                    b'waiting_tasks': str(counts['waiting']).encode(),
                    b'scheduled_tasks': str(counts['scheduled']).encode(),
                    b'blocked_tasks': str(counts['blocked']).encode(),
                    b'skipped_tasks': str(counts['skipped']).encode(),
                    b'updated_at': datetime.utcnow().isoformat().encode()
                }
            )

            logger.info(
                f"Recalculated task counts for workflow {workflow_id}: {counts}"
            )

        except Exception as e:
            logger.error(f"Failed to recalculate task counts for {workflow_id}: {e}")

    async def get_workflow_task_ids(self, workflow_id: str, shard: int) -> List[str]:
        """Get all task IDs for a workflow from workflow data"""
        # Bug #15: Read task IDs from workflow data, not from a non-existent set
        try:
            # Get workflow data which contains the original task definitions
            data_key = default_sharding.get_workflow_key("data", workflow_id)
            workflow_data_json = await self.redis.get(data_key.encode())

            if not workflow_data_json:
                logger.warning(f"No workflow data found for {workflow_id}")
                return []

            workflow_data = json.loads(workflow_data_json.decode())
            tasks = workflow_data.get('tasks', [])

            # Extract task IDs
            task_ids = []
            for task in tasks:
                task_id = task.get('id')
                if task_id:
                    task_ids.append(task_id)

            return task_ids

        except Exception as e:
            logger.error(f"Failed to get task IDs for workflow {workflow_id}: {e}")
            return []

    async def get_task(self, task_id: str, workflow_id: str, shard: int) -> Optional[Dict]:
        """Get task state from Redis"""
        # Bug #13: Use helper for task key
        task_key = default_sharding.get_task_key(task_id, workflow_id)

        try:
            task_data = await self.redis.hgetall(task_key.encode())
            return task_data if task_data else None
        except Exception as e:
            logger.error(f"Failed to get task {task_id}: {e}")
            return None

    async def mark_workflow_failed(self, workflow_id: str, shard: int, reason: str):
        """Mark workflow as failed atomically"""
        # Bug #1: Use helper for workflow key
        workflow_key = default_sharding.get_workflow_key("state", workflow_id)

        # Bug #11 & #14: Use Lua script for atomicity and index cleanup
        lua_script = """
        -- Update workflow state
        redis.call('hset', KEYS[1],
            'status', ARGV[1],
            'error', ARGV[2],
            'failed_at', ARGV[3],
            'updated_at', ARGV[3])

        -- Remove from all possible status indices
        for i=2,#KEYS-1 do
            redis.call('zrem', KEYS[i], ARGV[4])
        end

        -- Add to failed index
        redis.call('zadd', KEYS[2], ARGV[5], ARGV[4])

        return 1
        """

        failed_key = f"{{shard:{shard}}}:workflows:by_status:failed"
        running_key = f"{{shard:{shard}}}:workflows:by_status:running"
        waiting_key = f"{{shard:{shard}}}:workflows:by_status:waiting"
        scheduled_key = f"{{shard:{shard}}}:workflows:by_status:scheduled"
        completed_key = f"{{shard:{shard}}}:workflows:by_status:completed"

        try:
            now = datetime.utcnow()
            await self.redis.eval(
                lua_script.encode(),
                6,  # number of keys
                workflow_key.encode(),
                failed_key.encode(),
                running_key.encode(),
                waiting_key.encode(),
                scheduled_key.encode(),
                completed_key.encode(),
                WorkflowStatus.FAILED.value.encode(),
                reason.encode(),
                now.isoformat().encode(),
                workflow_id.encode(),
                str(now.timestamp()).encode()
            )

            # Bug #8: Fix stream key to use helper
            # Emit workflow:failed event after atomic update succeeds
            await self.redis.xadd(
                default_sharding.get_stream_key("workflow:failed", workflow_id).encode(),
                {
                    b'workflow_id': workflow_id.encode(),
                    b'error': reason.encode(),
                    b'reconciliation': b'true',
                    b'timestamp': now.isoformat().encode()
                }
            )

            logger.info(f"Marked workflow {workflow_id} as failed: {reason}")

        except Exception as e:
            logger.error(f"Failed to mark workflow {workflow_id} as failed: {e}")

    async def mark_workflow_completed(self, workflow_id: str, shard: int):
        """Mark workflow as completed atomically"""
        # Bug #1: Use helper for workflow key
        workflow_key = default_sharding.get_workflow_key("state", workflow_id)

        # Bug #11 & #14: Use Lua script for atomicity and index cleanup
        lua_script = """
        -- Update workflow state
        redis.call('hset', KEYS[1],
            'status', ARGV[1],
            'completed_at', ARGV[2],
            'updated_at', ARGV[2])

        -- Remove from all possible status indices
        for i=2,#KEYS-1 do
            redis.call('zrem', KEYS[i], ARGV[3])
        end

        -- Add to completed index
        redis.call('zadd', KEYS[2], ARGV[4], ARGV[3])

        return 1
        """

        completed_key = f"{{shard:{shard}}}:workflows:by_status:completed"
        running_key = f"{{shard:{shard}}}:workflows:by_status:running"
        waiting_key = f"{{shard:{shard}}}:workflows:by_status:waiting"
        scheduled_key = f"{{shard:{shard}}}:workflows:by_status:scheduled"
        failed_key = f"{{shard:{shard}}}:workflows:by_status:failed"

        try:
            now = datetime.utcnow()
            await self.redis.eval(
                lua_script.encode(),
                6,  # number of keys
                workflow_key.encode(),
                completed_key.encode(),
                running_key.encode(),
                waiting_key.encode(),
                scheduled_key.encode(),
                failed_key.encode(),
                WorkflowStatus.COMPLETED.value.encode(),
                now.isoformat().encode(),
                workflow_id.encode(),
                str(now.timestamp()).encode()
            )

            # Bug #8: Fix stream key to use helper
            # Emit workflow:completed event after atomic update succeeds
            await self.redis.xadd(
                default_sharding.get_stream_key("workflow:completed", workflow_id).encode(),
                {
                    b'workflow_id': workflow_id.encode(),
                    b'status': b'completed',
                    b'reconciliation': b'true',
                    b'timestamp': now.isoformat().encode()
                }
            )

            logger.info(f"Marked workflow {workflow_id} as completed")

        except Exception as e:
            logger.error(f"Failed to mark workflow {workflow_id} as completed: {e}")

    async def mark_workflow_waiting(self, workflow_id: str, shard: int):
        """Mark workflow as waiting for signals/timers (Bug #6)"""
        workflow_key = default_sharding.get_workflow_key("state", workflow_id)

        # Use Lua script for atomicity and index cleanup
        lua_script = """
        -- Update workflow state
        redis.call('hset', KEYS[1],
            'status', ARGV[1],
            'updated_at', ARGV[2])

        -- Remove from all possible status indices
        for i=2,#KEYS-1 do
            redis.call('zrem', KEYS[i], ARGV[3])
        end

        -- Add to waiting index
        redis.call('zadd', KEYS[2], ARGV[4], ARGV[3])

        return 1
        """

        waiting_key = f"{{shard:{shard}}}:workflows:by_status:waiting"
        running_key = f"{{shard:{shard}}}:workflows:by_status:running"
        scheduled_key = f"{{shard:{shard}}}:workflows:by_status:scheduled"
        completed_key = f"{{shard:{shard}}}:workflows:by_status:completed"
        failed_key = f"{{shard:{shard}}}:workflows:by_status:failed"

        try:
            now = datetime.utcnow()
            await self.redis.eval(
                lua_script.encode(),
                6,  # number of keys
                workflow_key.encode(),
                waiting_key.encode(),
                running_key.encode(),
                scheduled_key.encode(),
                completed_key.encode(),
                failed_key.encode(),
                WorkflowStatus.WAITING.value.encode(),
                now.isoformat().encode(),
                workflow_id.encode(),
                str(now.timestamp()).encode()
            )

            logger.info(f"Marked workflow {workflow_id} as waiting")

        except Exception as e:
            logger.error(f"Failed to mark workflow {workflow_id} as waiting: {e}")

    async def mark_workflow_scheduled(self, workflow_id: str, shard: int):
        """Mark workflow as scheduled (has timer tasks waiting)"""
        workflow_key = default_sharding.get_workflow_key("state", workflow_id)

        # Use Lua script for atomicity and index cleanup
        lua_script = """
        -- Update workflow state
        redis.call('hset', KEYS[1],
            'status', ARGV[1],
            'updated_at', ARGV[2])

        -- Remove from all possible status indices
        for i=2,#KEYS-1 do
            redis.call('zrem', KEYS[i], ARGV[3])
        end

        -- Add to scheduled index
        redis.call('zadd', KEYS[2], ARGV[4], ARGV[3])

        return 1
        """

        scheduled_key = f"{{shard:{shard}}}:workflows:by_status:scheduled"
        running_key = f"{{shard:{shard}}}:workflows:by_status:running"
        waiting_key = f"{{shard:{shard}}}:workflows:by_status:waiting"
        completed_key = f"{{shard:{shard}}}:workflows:by_status:completed"
        failed_key = f"{{shard:{shard}}}:workflows:by_status:failed"

        try:
            now = datetime.utcnow()
            await self.redis.eval(
                lua_script.encode(),
                6,  # number of keys
                workflow_key.encode(),
                scheduled_key.encode(),
                running_key.encode(),
                waiting_key.encode(),
                completed_key.encode(),
                failed_key.encode(),
                WorkflowStatus.SCHEDULED.value.encode(),
                now.isoformat().encode(),
                workflow_id.encode(),
                str(now.timestamp()).encode()
            )

            logger.info(f"Marked workflow {workflow_id} as scheduled")

        except Exception as e:
            logger.error(f"Failed to mark workflow {workflow_id} as scheduled: {e}")

    async def get_last_workflow_activity(
        self, workflow_id: str, shard: int
    ) -> Optional[datetime]:
        """
        Get timestamp of last activity for a workflow.

        Checks updated_at timestamp on workflow state.
        """
        # Bug #1: Use helper for workflow key
        workflow_key = default_sharding.get_workflow_key("state", workflow_id)

        try:
            updated_at = await self.redis.hget(workflow_key.encode(), b'updated_at')
            if updated_at:
                updated_at_str = updated_at.decode() if isinstance(updated_at, bytes) else updated_at
                return datetime.fromisoformat(updated_at_str)
            return None
        except Exception as e:
            logger.error(f"Failed to get last activity for workflow {workflow_id}: {e}")
            return None
