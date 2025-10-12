"""
Workflow State Reconciliation Worker

Periodically scans workflows and ensures state consistency.
Fixes workflows stuck in incorrect states due to worker crashes.
"""

import asyncio
import logging
import json
import uuid
from typing import Dict, List, Optional, Set
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

from .base import BaseWorker, WorkerConfig
from ..core.models import WorkflowStatus, TaskStatus

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

        # Metrics
        self.workflows_scanned = 0
        self.inconsistencies_found = 0
        self.workflows_fixed = 0
        self.scan_errors = 0

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
                        f"Scanned {self.workflows_scanned} workflows, "
                        f"found {self.inconsistencies_found} inconsistencies, "
                        f"fixed {self.workflows_fixed} workflows in {scan_duration:.2f}s",
                        scan_duration=scan_duration,
                        workflows_scanned=self.workflows_scanned,
                        inconsistencies_found=self.inconsistencies_found,
                        workflows_fixed=self.workflows_fixed
                    )

                    # Wait for next scan interval
                    await asyncio.sleep(self.scan_interval)

                except Exception as e:
                    self.scan_errors += 1
                    await self.log_worker_error(
                        "reconciliation_cycle_failed",
                        e,
                        scan_errors=self.scan_errors
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
                async with self.acquire_shard_lock(shard) as lock:
                    await self.reconcile_shard(shard)
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

    async def reconcile_shard(self, shard: int):
        """Reconcile all running workflows on a shard"""
        offset = 0
        shard_workflows_scanned = 0

        while True:
            # Scan for running workflows
            workflow_ids = await self.scan_running_workflows(shard, offset, self.batch_size)

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

        logger.debug(f"Shard {shard} reconciliation complete: {shard_workflows_scanned} workflows scanned")

    async def _reconcile_workflow_with_semaphore(self, workflow_id: str, shard: int):
        """Reconcile workflow with concurrency control"""
        async with self._reconciliation_semaphore:
            await self.reconcile_workflow(workflow_id, shard)

    async def scan_running_workflows(
        self, shard: int, offset: int, limit: int
    ) -> List[str]:
        """
        Scan for workflows with status='running' on a shard.

        Uses sorted set for efficient scanning:
        {shard:N}:workflows:by_status:running
        """
        key = f"{{shard:{shard}}}:workflows:by_status:running"

        try:
            workflow_ids = await self.redis.zrange(
                key.encode(),
                offset,
                offset + limit - 1
            )

            return [wf_id.decode() for wf_id in workflow_ids]
        except Exception as e:
            logger.error(f"Failed to scan workflows on shard {shard}: {e}")
            return []

    async def reconcile_workflow(self, workflow_id: str, shard: int):
        """
        Reconcile a single workflow.

        Performs all consistency checks and fixes inconsistencies.
        """
        self.workflows_scanned += 1

        try:
            # Get workflow state
            workflow = await self.get_workflow(workflow_id, shard)
            if not workflow:
                logger.warning(f"Workflow {workflow_id} not found during reconciliation")
                return

            # Skip if no longer running
            status = workflow.get('status', '').decode() if isinstance(workflow.get('status'), bytes) else workflow.get('status', '')
            if status != 'running':
                return

            # Run consistency checks
            inconsistencies = await self.check_workflow_consistency(workflow_id, workflow, shard)

            if inconsistencies:
                self.inconsistencies_found += len(inconsistencies)

                await self.log_worker_warning(
                    "workflow_inconsistency_detected",
                    f"Workflow {workflow_id} has {len(inconsistencies)} inconsistencies",
                    workflow_id=workflow_id,
                    shard=shard,
                    inconsistencies=inconsistencies
                )

                # Fix inconsistencies
                await self.fix_workflow_state(workflow_id, workflow, inconsistencies, shard)

                self.workflows_fixed += 1

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
        key = f"{{shard:{shard}}}:workflow:status:{workflow_id}"

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

        # Check 1: Task count consistency
        total_accounted = completed_tasks + failed_tasks + running_tasks + pending_tasks
        if total_accounted != total_tasks:
            inconsistencies.append(
                f"task_count_mismatch: total={total_tasks} but "
                f"accounted={total_accounted} "
                f"(completed={completed_tasks}, failed={failed_tasks}, "
                f"running={running_tasks}, pending={pending_tasks})"
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

        # Check 4: Zombie workflow detection
        if running_tasks == 0 and pending_tasks == 0 and completed_tasks < total_tasks:
            # No active tasks but workflow incomplete - check last activity
            last_activity = await self.get_last_workflow_activity(workflow_id, shard)
            if last_activity:
                time_since_activity = (datetime.utcnow() - last_activity).total_seconds()
                if time_since_activity > self.zombie_threshold:
                    inconsistencies.append(
                        f"zombie_workflow: no active tasks for {time_since_activity:.0f}s "
                        f"(threshold={self.zombie_threshold}s)"
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

        # Recalculate task counts if mismatch detected
        if has_task_count_mismatch:
            await self.recalculate_task_counts(workflow_id, shard)
            # Re-fetch workflow after recalculation
            workflow = await self.get_workflow(workflow_id, shard)
            if not workflow:
                return

        # Apply state fixes
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

    async def recalculate_task_counts(self, workflow_id: str, shard: int):
        """
        Recalculate workflow task counts from actual task states.
        """
        try:
            # Get all task IDs for workflow
            task_ids = await self.get_workflow_task_ids(workflow_id, shard)

            counts = {
                'pending': 0,
                'running': 0,
                'completed': 0,
                'failed': 0,
                'waiting': 0
            }

            # Fetch actual task states
            for task_id in task_ids:
                task = await self.get_task(task_id, workflow_id, shard)
                if task:
                    status = task.get(b'status', b'pending').decode() if isinstance(task.get(b'status'), bytes) else task.get('status', 'pending')
                    if status in counts:
                        counts[status] += 1

            # Update workflow with corrected counts
            workflow_key = f"{{shard:{shard}}}:workflow:status:{workflow_id}"
            await self.redis.hset(
                workflow_key.encode(),
                mapping={
                    b'pending_tasks': str(counts['pending']).encode(),
                    b'running_tasks': str(counts['running']).encode(),
                    b'completed_tasks': str(counts['completed']).encode(),
                    b'failed_tasks': str(counts['failed']).encode(),
                    b'waiting_tasks': str(counts.get('waiting', 0)).encode(),
                    b'updated_at': datetime.utcnow().isoformat().encode()
                }
            )

            logger.info(
                f"Recalculated task counts for workflow {workflow_id}: {counts}"
            )

        except Exception as e:
            logger.error(f"Failed to recalculate task counts for {workflow_id}: {e}")

    async def get_workflow_task_ids(self, workflow_id: str, shard: int) -> List[str]:
        """Get all task IDs for a workflow"""
        tasks_key = f"{{shard:{shard}}}:workflow:tasks:{workflow_id}"

        try:
            task_ids = await self.redis.smembers(tasks_key.encode())
            return [tid.decode() for tid in task_ids]
        except Exception as e:
            logger.error(f"Failed to get task IDs for workflow {workflow_id}: {e}")
            return []

    async def get_task(self, task_id: str, workflow_id: str, shard: int) -> Optional[Dict]:
        """Get task state from Redis"""
        task_key = f"{{shard:{shard}}}:task:status:{task_id}"

        try:
            task_data = await self.redis.hgetall(task_key.encode())
            return task_data if task_data else None
        except Exception as e:
            logger.error(f"Failed to get task {task_id}: {e}")
            return None

    async def mark_workflow_failed(self, workflow_id: str, shard: int, reason: str):
        """Mark workflow as failed"""
        workflow_key = f"{{shard:{shard}}}:workflow:status:{workflow_id}"

        try:
            await self.redis.hset(
                workflow_key.encode(),
                mapping={
                    b'status': WorkflowStatus.FAILED.value.encode(),
                    b'error': reason.encode(),
                    b'failed_at': datetime.utcnow().isoformat().encode(),
                    b'updated_at': datetime.utcnow().isoformat().encode()
                }
            )

            # Move from running to failed index
            running_key = f"{{shard:{shard}}}:workflows:by_status:running"
            failed_key = f"{{shard:{shard}}}:workflows:by_status:failed"

            await self.redis.zrem(running_key.encode(), workflow_id.encode())
            await self.redis.zadd(
                failed_key.encode(),
                {workflow_id.encode(): datetime.utcnow().timestamp()}
            )

            # Emit workflow:failed event
            await self.redis.xadd(
                f"{{shard:{shard}}}:workflow:failed".encode(),
                {
                    b'workflow_id': workflow_id.encode(),
                    b'error': reason.encode(),
                    b'reconciliation': b'true',
                    b'timestamp': datetime.utcnow().isoformat().encode()
                }
            )

            logger.info(f"Marked workflow {workflow_id} as failed: {reason}")

        except Exception as e:
            logger.error(f"Failed to mark workflow {workflow_id} as failed: {e}")

    async def mark_workflow_completed(self, workflow_id: str, shard: int):
        """Mark workflow as completed"""
        workflow_key = f"{{shard:{shard}}}:workflow:status:{workflow_id}"

        try:
            await self.redis.hset(
                workflow_key.encode(),
                mapping={
                    b'status': WorkflowStatus.COMPLETED.value.encode(),
                    b'completed_at': datetime.utcnow().isoformat().encode(),
                    b'updated_at': datetime.utcnow().isoformat().encode()
                }
            )

            # Move from running to completed index
            running_key = f"{{shard:{shard}}}:workflows:by_status:running"
            completed_key = f"{{shard:{shard}}}:workflows:by_status:completed"

            await self.redis.zrem(running_key.encode(), workflow_id.encode())
            await self.redis.zadd(
                completed_key.encode(),
                {workflow_id.encode(): datetime.utcnow().timestamp()}
            )

            # Emit workflow:completed event
            await self.redis.xadd(
                f"{{shard:{shard}}}:workflow:completed".encode(),
                {
                    b'workflow_id': workflow_id.encode(),
                    b'status': b'completed',
                    b'reconciliation': b'true',
                    b'timestamp': datetime.utcnow().isoformat().encode()
                }
            )

            logger.info(f"Marked workflow {workflow_id} as completed")

        except Exception as e:
            logger.error(f"Failed to mark workflow {workflow_id} as completed: {e}")

    async def get_last_workflow_activity(
        self, workflow_id: str, shard: int
    ) -> Optional[datetime]:
        """
        Get timestamp of last activity for a workflow.

        Checks updated_at timestamp on workflow state.
        """
        workflow_key = f"{{shard:{shard}}}:workflow:status:{workflow_id}"

        try:
            updated_at = await self.redis.hget(workflow_key.encode(), b'updated_at')
            if updated_at:
                updated_at_str = updated_at.decode() if isinstance(updated_at, bytes) else updated_at
                return datetime.fromisoformat(updated_at_str)
            return None
        except Exception as e:
            logger.error(f"Failed to get last activity for workflow {workflow_id}: {e}")
            return None
