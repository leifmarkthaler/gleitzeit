"""
Dependency resolution worker for Gleitzeit 0.0.7

Resolves task dependencies within workflow shards for maximum locality.
"""

import asyncio
import json
import logging
import re
from typing import Dict, Any, List, Set, Optional
from datetime import datetime

from .base import BaseWorker, WorkerConfig
from ..core.sharding import default_sharding
from ..core.cache import LRUCache
from ..core.events import EventType
from ..core.event_store import EventStore, EventLevel

logger = logging.getLogger(__name__)


class DependencyWorker(BaseWorker):
    """
    Worker that resolves task dependencies after completions.

    Features:
    - Processes task:completed events
    - Resolves dependencies within same shard
    - Emits ready tasks to same shard
    - Maintains dependency graphs in Redis
    """

    def __init__(self, config: WorkerConfig):
        super().__init__(config)
        # Use LRU cache for dependency caching
        cache_size = config.__dict__.get('dependency_cache_size', 500)
        cache_ttl = config.__dict__.get('dependency_cache_ttl', 1800)  # 30 minutes default
        self.dependency_cache = LRUCache(max_size=cache_size, default_ttl=cache_ttl)

    async def on_initialize(self):
        """Initialize dependency resolution resources"""
        # Initialize event store
        self.event_store = EventStore(self.redis, config={
            'max_events_per_workflow': 10000,
            'event_ttl_seconds': 86400 * 30  # 30 days
        })

        logger.info("DependencyWorker initialized")
        logger.info(f"Dependency cache configured: size={self.dependency_cache.max_size}, ttl={self.dependency_cache.default_ttl}s")

    def get_base_streams(self) -> List[str]:
        """Return streams this worker consumes from"""
        return ["task:completed", "task:failed", "workflow:submitted", "task:cancelled", "workflow:cancelled"]

    async def process_message(self, stream: str, message_id: str, data: Dict) -> bool:
        """Process dependency-related events

        Returns:
            True if message was processed successfully
            False if message should be retried
        """
        workflow_id = data.get('workflow_id')

        if not workflow_id:
            logger.error(f"Missing workflow_id in message {message_id}")
            return True  # Malformed message, ACK to remove

        try:
            if "task:completed" in stream:
                await self.handle_task_completion(workflow_id, data)
            elif "task:failed" in stream:
                await self.handle_task_failure(workflow_id, data)
            elif "workflow:submitted" in stream:
                await self.handle_workflow_submission(workflow_id, data)
            elif "task:cancelled" in stream:
                await self.handle_task_cancellation(workflow_id, data)
            elif "workflow:cancelled" in stream:
                await self.handle_workflow_cancellation(workflow_id, data)

            return True  # Successfully processed

        except Exception as e:
            logger.error(f"Failed to process dependency message: {e}", exc_info=True)
            # Log to Redis for queryability
            await self.log_worker_error(
                "process_message",
                e,
                workflow_id=workflow_id,
                stream=stream,
                message_id=message_id
            )
            return False  # Retry on exception

    async def handle_workflow_submission(self, workflow_id: str, data: Dict):
        """Process newly submitted workflow"""
        logger.info(f"Processing workflow submission: {workflow_id}")

        # Log INFO: Workflow submission received
        await self.log_worker_info(
            "workflow_submission_received",
            f"Processing workflow submission {workflow_id}",
            workflow_id=workflow_id
        )

        # Emit workflow started event
        await self.event_store.store_event(
            event_type=EventType.WORKFLOW_STARTED,
            workflow_id=workflow_id,
            level=EventLevel.CRITICAL,
            data={
                'worker_id': self.config.worker_id,
                'timestamp': datetime.utcnow().isoformat()
            }
        )

        workflow_data = data.get('workflow')
        if isinstance(workflow_data, str):
            workflow_data = json.loads(workflow_data)

        # Store workflow definition separately (due to size)
        await self.redis.hset(
            default_sharding.get_workflow_key("data", workflow_id).encode(),
            mapping={
                b"workflow": json.dumps(workflow_data).encode()
            }
        )

        # Build dependency graph
        dependency_graph = self.build_dependency_graph(workflow_data)

        # Store dependency graph in Redis
        graph_key = default_sharding.get_workflow_key("dependency:graph", workflow_id)
        for task_id, deps in dependency_graph.items():
            await self.redis.hset(
                graph_key.encode(),
                task_id.encode(),
                json.dumps(deps).encode()
            )

        # Find and emit initial tasks (no dependencies)
        initial_tasks = self.find_initial_tasks(dependency_graph, workflow_data)
        shard = default_sharding.get_shard(workflow_id)

        for task_data in initial_tasks:
            # Emit task ready event
            await self.event_store.store_event(
                event_type=EventType.TASK_READY,
                workflow_id=workflow_id,
                task_id=task_data['id'],
                level=EventLevel.IMPORTANT,
                data={
                    'is_initial': True,
                    'dependencies': task_data.get('dependencies', [])
                }
            )

            # All tasks go to task:ready stream (including timer tasks)
            # Timer provider will handle the sleeping status
            await self.redis.xadd(
                default_sharding.get_stream_key("task:ready", workflow_id).encode(),
                {
                    b"workflow_id": workflow_id.encode(),
                    b"task_id": task_data['id'].encode(),
                    b"task": json.dumps(task_data).encode(),
                    b"timestamp": datetime.utcnow().isoformat().encode()
                }
            )
            logger.info(f"Emitted initial task {task_data['id']} to shard {shard}")

        # Log INFO: Initial tasks emitted
        await self.log_worker_info(
            "initial_tasks_emitted",
            f"Emitted {len(initial_tasks)} initial tasks for workflow {workflow_id}",
            workflow_id=workflow_id,
            initial_task_count=len(initial_tasks),
            total_task_count=len(workflow_data.get('tasks', []))
        )

        # Store consolidated workflow state (replaces both workflow:state and workflow:status)
        pending_count = len(workflow_data.get('tasks', [])) - len(initial_tasks)
        now = datetime.utcnow().isoformat()

        # Get workflow metadata
        workflow_name = workflow_data.get('name', 'unnamed')
        workflow_description = workflow_data.get('description', '')
        workflow_version = workflow_data.get('version', '1.0.0')

        # Determine initial workflow status based on initial tasks
        # Count task types in initial tasks
        scheduled_count = sum(1 for task in initial_tasks if task.get('protocol', '').startswith('timer/'))
        signal_count = sum(1 for task in initial_tasks if task.get('protocol', '').startswith('signal/'))
        active_count = len(initial_tasks) - scheduled_count - signal_count

        # Determine initial status intelligently
        if active_count > 0:
            # Has actively running tasks
            initial_status = b"running"
            running_count = active_count
            waiting_count = signal_count
        elif signal_count > 0:
            # Only signal tasks (waiting for signals)
            initial_status = b"waiting"
            running_count = 0
            waiting_count = signal_count
        elif scheduled_count > 0:
            # Only scheduled tasks (waiting for timers)
            initial_status = b"scheduled"
            running_count = 0
            waiting_count = 0
        else:
            # No initial tasks (all tasks have dependencies)
            initial_status = b"running"
            running_count = 0
            waiting_count = 0

        await self.redis.hset(
            default_sharding.get_workflow_key("state", workflow_id).encode(),
            mapping={
                # Core workflow info
                b"workflow_id": workflow_id.encode(),
                b"name": workflow_name.encode(),
                b"description": workflow_description.encode(),
                b"version": workflow_version.encode(),

                # Status fields
                b"status": initial_status,
                b"submitted_at": now.encode(),
                b"started_at": now.encode(),

                # Task metrics
                b"total_tasks": str(len(workflow_data.get('tasks', []))).encode(),
                b"completed_tasks": b"0",
                b"failed_tasks": b"0",
                b"skipped_tasks": b"0",
                b"blocked_tasks": b"0",
                b"waiting_tasks": str(waiting_count).encode(),
                b"scheduled_tasks": str(scheduled_count).encode(),
                b"pending_tasks": str(pending_count).encode(),
                b"running_tasks": str(running_count).encode(),

                # Worker tracking
                b"worker_id": self.config.worker_id.encode()
            }
        )

        # Add workflow to appropriate status index for reconciliation worker
        shard = default_sharding.get_shard(workflow_id)
        status_str = initial_status.decode()
        status_index_key = f"{{shard:{shard}}}:workflows:by_status:{status_str}"
        await self.redis.zadd(
            status_index_key.encode(),
            {workflow_id.encode(): datetime.utcnow().timestamp()}
        )

    async def handle_task_completion(self, workflow_id: str, data: Dict):
        """Handle task completion and resolve dependencies"""
        task_id = data.get('task_id')
        logger.info(f"Processing task completion: {task_id} from workflow {workflow_id}")

        # Log DEBUG: Task completion received
        await self.log_worker_debug(
            "task_completion_received",
            f"Processing task completion {task_id}",
            workflow_id=workflow_id,
            task_id=task_id
        )

        # Check if task is already completed to prevent duplicate processing
        completed_key = default_sharding.get_workflow_key("tasks:completed", workflow_id)
        was_added = await self.redis.sadd(completed_key.encode(), task_id.encode())

        if not was_added:
            # Task already processed, skip to avoid double-counting
            logger.debug(f"Task {task_id} already completed, skipping duplicate processing")
            return

        # Update completed tasks count in consolidated state
        await self.redis.hincrby(
            default_sharding.get_workflow_key("state", workflow_id).encode(),
            b"completed_tasks",
            1
        )

        # Decrement running tasks
        await self.redis.hincrby(
            default_sharding.get_workflow_key("state", workflow_id).encode(),
            b"running_tasks",
            -1
        )

        # Get dependency graph (all on same shard!)
        graph_key = default_sharding.get_workflow_key("dependency:graph", workflow_id)
        raw_graph = await self.redis.hgetall(graph_key.encode())

        if not raw_graph:
            logger.warning(f"No dependency graph found for workflow {workflow_id}")
            return

        # Parse dependency graph
        dependency_graph = {}
        for tid, deps in raw_graph.items():
            dependency_graph[tid.decode()] = json.loads(deps.decode())

        # Find newly ready tasks
        ready_tasks = await self.find_ready_tasks(
            workflow_id,
            task_id,
            dependency_graph
        )

        # Emit ready tasks to same shard
        if ready_tasks:
            shard = default_sharding.get_shard(workflow_id)

            # Log INFO: Dependencies resolved
            await self.log_worker_info(
                "dependencies_resolved",
                f"Resolved {len(ready_tasks)} newly ready tasks after {task_id} completion",
                workflow_id=workflow_id,
                task_id=task_id,
                ready_task_count=len(ready_tasks)
            )

            for ready_task_id in ready_tasks:
                # Get task data
                workflow_data = await self.redis.hget(
                    default_sharding.get_workflow_key("data", workflow_id).encode(),
                    b"workflow"
                )

                if workflow_data:
                    workflow = json.loads(workflow_data)
                    task_data = self.find_task_by_id(workflow, ready_task_id)

                    if task_data:
                        # Resolve parameters before emitting
                        resolved_task = await self.resolve_task_parameters(
                            task_data.copy(),
                            workflow_id
                        )

                        # Emit task ready event
                        await self.event_store.store_event(
                            event_type=EventType.TASK_READY,
                            workflow_id=workflow_id,
                            task_id=ready_task_id,
                            level=EventLevel.IMPORTANT,
                            data={
                                'is_initial': False,
                                'triggered_by': task_id,  # Fixed: was using undefined completed_task_id
                                'dependencies': task_data.get('dependencies', [])
                            }
                        )

                        # All tasks go to task:ready stream (including timer tasks)
                        # Timer provider will handle the sleeping status
                        await self.redis.xadd(
                            default_sharding.get_stream_key("task:ready", workflow_id).encode(),
                            {
                                b"workflow_id": workflow_id.encode(),
                                b"task_id": ready_task_id.encode(),
                                b"task": json.dumps(resolved_task).encode(),
                                b"timestamp": datetime.utcnow().isoformat().encode()
                            }
                        )
                        logger.info(f"Emitted ready task {ready_task_id} to shard {shard}")

        # Check if workflow is complete
        await self.check_workflow_completion(workflow_id)

        # Check if workflow status should be updated based on remaining tasks
        await self.check_workflow_status_transition(workflow_id)

    async def handle_task_failure(self, workflow_id: str, data: Dict):
        """Handle task failure and update consolidated state"""
        task_id = data.get('task_id')
        logger.info(f"Processing task failure: {task_id} from workflow {workflow_id}")

        # Update failed tasks count in consolidated state
        await self.redis.hincrby(
            default_sharding.get_workflow_key("state", workflow_id).encode(),
            b"failed_tasks",
            1
        )

        # Decrement running tasks
        await self.redis.hincrby(
            default_sharding.get_workflow_key("state", workflow_id).encode(),
            b"running_tasks",
            -1
        )

        # Mark task as failed in the failed set
        await self.redis.sadd(
            default_sharding.get_workflow_key("tasks:failed", workflow_id).encode(),
            task_id.encode()
        )

        # HARD FAIL POLICY: Immediately fail the workflow on first task failure
        # Get current workflow status
        workflow_state = await self.redis.hgetall(
            default_sharding.get_workflow_key("state", workflow_id).encode()
        )
        current_status = workflow_state.get(b"status", b"unknown").decode()

        # Only fail workflow if it's still active (not already failed/completed/cancelled)
        # Active states: running, waiting, scheduled, paused, pending
        if current_status not in ["completed", "failed", "cancelled"]:
            logger.warning(f"Task {task_id} failed - applying HARD FAIL policy for workflow {workflow_id}")

            # Mark all pending and running tasks as blocked
            total_tasks = int(workflow_state.get(b"total_tasks", b"0").decode())
            pending_tasks = int(workflow_state.get(b"pending_tasks", b"0").decode())
            running_tasks = int(workflow_state.get(b"running_tasks", b"0").decode())
            completed_tasks = int(workflow_state.get(b"completed_tasks", b"0").decode())
            failed_tasks = int(workflow_state.get(b"failed_tasks", b"0").decode())

            # All non-completed/non-failed tasks become blocked
            blocked_count = total_tasks - completed_tasks - failed_tasks

            # Update workflow status to failed immediately
            await self.redis.hset(
                default_sharding.get_workflow_key("state", workflow_id).encode(),
                mapping={
                    b"status": b"failed",
                    b"completed_at": datetime.utcnow().isoformat().encode(),
                    b"blocked_tasks": str(blocked_count).encode(),
                    b"pending_tasks": b"0",
                    b"running_tasks": b"0"
                }
            )

            # Emit workflow failed event
            await self.event_store.store_event(
                event_type=EventType.WORKFLOW_FAILED,
                workflow_id=workflow_id,
                level=EventLevel.CRITICAL,
                data={
                    'status': 'failed',
                    'failed_task_id': task_id,
                    'total_tasks': total_tasks,
                    'completed_tasks': completed_tasks,
                    'failed_tasks': failed_tasks,
                    'blocked_tasks': blocked_count,
                    'reason': 'hard_fail_policy',
                    'worker_id': self.config.worker_id
                }
            )

            logger.info(f"Workflow {workflow_id} marked as FAILED due to task {task_id} failure (hard fail policy)")
        else:
            # Workflow already completed/failed, just check for final status
            await self.check_workflow_completion(workflow_id)

    async def find_ready_tasks(
        self,
        workflow_id: str,
        completed_task_id: str,
        dependency_graph: Dict[str, List[str]]
    ) -> List[str]:
        """Find tasks that are now ready after a completion"""
        ready_tasks = []
        completed_set = await self.redis.smembers(
            default_sharding.get_workflow_key("tasks:completed", workflow_id).encode()
        )
        completed_tasks = {t.decode() for t in completed_set}

        # Also get failed tasks to check if dependencies have failed
        failed_set = await self.redis.smembers(
            default_sharding.get_workflow_key("tasks:failed", workflow_id).encode()
        )
        failed_tasks = {t.decode() for t in failed_set}

        # Check each task's dependencies
        for task_id, dependencies in dependency_graph.items():
            if task_id in completed_tasks:
                continue  # Already completed

            # Check if this task depends on the completed task
            if completed_task_id in dependencies:
                # Check if any dependency has failed
                failed_deps = [dep for dep in dependencies if dep in failed_tasks]
                if failed_deps:
                    # Mark task as blocked due to failed dependency
                    logger.info(f"Task {task_id} blocked due to failed dependencies: {failed_deps}")

                    # Log WARNING: Task blocked due to failed dependency
                    await self.log_worker_warning(
                        "task_blocked_failed_dependency",
                        f"Task {task_id} blocked due to failed dependencies: {', '.join(failed_deps)}",
                        workflow_id=workflow_id,
                        task_id=task_id,
                        failed_dependencies=failed_deps
                    )
                    await self.redis.sadd(
                        default_sharding.get_workflow_key("tasks:blocked", workflow_id).encode(),
                        task_id.encode()
                    )
                    await self.redis.hset(
                        default_sharding.get_task_key(task_id, workflow_id).encode(),
                        mapping={
                            b"status": b"blocked",
                            b"blocked_by": ','.join(failed_deps).encode(),
                            b"blocked_reason": f"Dependencies failed: {', '.join(failed_deps)}".encode()
                        }
                    )
                    # Update blocked count in consolidated state
                    await self.redis.hincrby(
                        default_sharding.get_workflow_key("state", workflow_id).encode(),
                        b"blocked_tasks",
                        1
                    )
                    # Decrement pending tasks
                    await self.redis.hincrby(
                        default_sharding.get_workflow_key("state", workflow_id).encode(),
                        b"pending_tasks",
                        -1
                    )
                    continue

                # Check if all dependencies are satisfied
                if all(dep in completed_tasks for dep in dependencies):
                    # Check validation dependencies
                    should_skip = await self._check_validation_dependencies(
                        workflow_id, task_id, dependencies
                    )

                    if should_skip:
                        # Mark task as skipped due to validation failure
                        await self.redis.hset(
                            default_sharding.get_task_key(task_id, workflow_id).encode(),
                            mapping={
                                b"status": b"skipped",
                                b"skipped_reason": b"validation_failed",
                                b"skipped_at": datetime.utcnow().isoformat().encode()
                            }
                        )
                        # Update skipped count in consolidated state
                        await self.redis.hincrby(
                            default_sharding.get_workflow_key("state", workflow_id).encode(),
                            b"skipped_tasks",
                            1
                        )
                        # Decrement pending tasks
                        await self.redis.hincrby(
                            default_sharding.get_workflow_key("state", workflow_id).encode(),
                            b"pending_tasks",
                            -1
                        )
                        logger.info(f"Task {task_id} skipped due to validation failure")
                        continue

                    # Check if not already running
                    is_running = await self.redis.sismember(
                        default_sharding.get_workflow_key("tasks:running", workflow_id).encode(),
                        task_id.encode()
                    )

                    if not is_running:
                        ready_tasks.append(task_id)
                        # Mark as running
                        await self.redis.sadd(
                            default_sharding.get_workflow_key("tasks:running", workflow_id).encode(),
                            task_id.encode()
                        )

                        # Get workflow data to check task protocol
                        workflow_data = await self.redis.hget(
                            default_sharding.get_workflow_key("data", workflow_id).encode(),
                            b"workflow"
                        )

                        # Determine which counter to update based on task protocol
                        counter_field = b"running_tasks"
                        if workflow_data:
                            workflow = json.loads(workflow_data)
                            task_def = self.find_task_by_id(workflow, task_id)
                            if task_def:
                                protocol = task_def.get('protocol', '')
                                if protocol.startswith('timer/'):
                                    counter_field = b"scheduled_tasks"
                                elif protocol.startswith('signal/'):
                                    counter_field = b"waiting_tasks"

                        # Update appropriate task count in consolidated state
                        await self.redis.hincrby(
                            default_sharding.get_workflow_key("state", workflow_id).encode(),
                            counter_field,
                            1
                        )
                        # Decrement pending tasks
                        await self.redis.hincrby(
                            default_sharding.get_workflow_key("state", workflow_id).encode(),
                            b"pending_tasks",
                            -1
                        )

        return ready_tasks

    async def compute_workflow_status(self, workflow_id: str) -> tuple[str, Dict[str, int]]:
        """
        Compute workflow status from actual task states in Redis (stateless).

        Returns:
            Tuple of (workflow_status, task_counts) where task_counts has keys:
            completed, failed, scheduled, waiting, pending, cancelled, paused
        """
        # Initialize counters
        counts = {
            "completed": 0,
            "failed": 0,
            "scheduled": 0,
            "waiting": 0,
            "pending": 0,
            "cancelled": 0,
            "paused": 0
        }

        # Get workflow data to access tasks
        shard = default_sharding.get_shard(workflow_id)
        workflow_key = f"{{shard:{shard}}}:workflow:{workflow_id}"
        workflow_data = await self.redis.hgetall(workflow_key.encode())

        if not workflow_data:
            logger.warning(f"Workflow {workflow_id} not found")
            return "pending", counts

        # Parse workflow tasks
        workflow_json = workflow_data.get(b"data")
        if not workflow_json:
            logger.warning(f"Workflow {workflow_id} has no data field")
            return "pending", counts

        workflow = json.loads(workflow_json.decode())
        tasks = workflow.get("workflow", {}).get("tasks", [])

        if not tasks:
            return "pending", counts

        # Check each task's actual status from Redis
        for task in tasks:
            task_id = task.get("id")
            if not task_id:
                continue

            # Query task status from Redis
            task_status_key = f"{{shard:{shard}}}:task:status:{task_id}"
            task_status_data = await self.redis.hgetall(task_status_key.encode())

            if task_status_data:
                # Task has explicit status in Redis
                status = task_status_data.get(b"status", b"pending").decode()

                if status == "completed":
                    counts["completed"] += 1
                elif status == "failed":
                    counts["failed"] += 1
                elif status == "scheduled":
                    counts["scheduled"] += 1
                elif status == "waiting":
                    counts["waiting"] += 1
                elif status == "cancelled":
                    counts["cancelled"] += 1
                elif status == "paused":
                    counts["paused"] += 1
                else:
                    counts["pending"] += 1
            else:
                # Task has no status yet - infer from protocol
                protocol = task.get("protocol", "python/v1")

                if protocol.startswith("timer/"):
                    counts["scheduled"] += 1
                elif protocol.startswith("signal/"):
                    counts["waiting"] += 1
                else:
                    # Regular tasks that haven't started yet
                    counts["pending"] += 1

        # Determine workflow status based on actual task states
        total_tasks = sum(counts.values())

        # Hard fail policy: any failed task fails the whole workflow
        if counts["failed"] > 0:
            return "failed", counts

        # All tasks cancelled
        if counts["cancelled"] == total_tasks:
            return "cancelled", counts

        # All tasks completed
        if counts["completed"] == total_tasks:
            return "completed", counts

        # Determine status based on what's remaining
        active_tasks = counts["pending"]

        if active_tasks > 0:
            # Has tasks ready to run or that could become ready
            return "running", counts
        elif counts["waiting"] > 0 and counts["scheduled"] == 0:
            # Only waiting for signals
            return "waiting", counts
        elif counts["scheduled"] > 0 and counts["waiting"] == 0:
            # Only waiting for timers
            return "scheduled", counts
        elif counts["scheduled"] > 0 or counts["waiting"] > 0:
            # Has both scheduled and waiting tasks - prioritize waiting
            return "waiting", counts
        elif counts["paused"] > 0:
            return "paused", counts
        else:
            # Shouldn't reach here
            logger.warning(f"Workflow {workflow_id} in unexpected state: {counts}")
            return "pending", counts

    async def check_workflow_status_transition(self, workflow_id: str):
        """Check if workflow status should transition based on actual task states (stateless)"""
        try:
            # Get current workflow state
            state_key = default_sharding.get_workflow_key("state", workflow_id)
            workflow_state = await self.redis.hgetall(state_key.encode())

            if not workflow_state:
                return

            current_status = workflow_state.get(b"status", b"running").decode()

            # Only check transitions for active workflows
            if current_status not in ["running", "waiting", "scheduled", "pending"]:
                return

            # Compute workflow status from actual task states
            new_status, task_counts = await self.compute_workflow_status(workflow_id)

            # Update status if it changed
            if new_status != current_status:
                shard = default_sharding.get_shard(workflow_id)
                logger.info(
                    f"Transitioning workflow {workflow_id} from {current_status} to {new_status} "
                    f"(task counts: {task_counts})"
                )

                # Update workflow status
                await self.redis.hset(
                    state_key.encode(),
                    b"status",
                    new_status.encode()
                )

                # Update status indices
                old_index = f"{{shard:{shard}}}:workflows:by_status:{current_status}"
                new_index = f"{{shard:{shard}}}:workflows:by_status:{new_status}"

                # Remove from old index and add to new index
                await self.redis.zrem(old_index.encode(), workflow_id.encode())
                await self.redis.zadd(
                    new_index.encode(),
                    {workflow_id.encode(): datetime.utcnow().timestamp()}
                )

        except Exception as e:
            logger.error(f"Failed to check workflow status transition for {workflow_id}: {e}")

    async def check_workflow_completion(self, workflow_id: str):
        """Check if workflow is complete, including skipped and blocked tasks"""
        # Read from consolidated state
        status = await self.redis.hgetall(default_sharding.get_workflow_key("state", workflow_id).encode())

        if status:
            total = int(status.get(b"total_tasks", b"0").decode())
            completed = int(status.get(b"completed_tasks", b"0").decode())

            # Count skipped and blocked tasks
            skipped_set = await self.redis.smembers(
                default_sharding.get_workflow_key("tasks:skipped", workflow_id).encode()
            )
            blocked_set = await self.redis.smembers(
                default_sharding.get_workflow_key("tasks:blocked", workflow_id).encode()
            )
            failed_set = await self.redis.smembers(
                default_sharding.get_workflow_key("tasks:failed", workflow_id).encode()
            )

            skipped_count = len(skipped_set)
            blocked_count = len(blocked_set)
            failed_count = len(failed_set)

            # Workflow is complete when all tasks are either completed, skipped, blocked, or failed
            accounted_tasks = completed + skipped_count + blocked_count + failed_count

            if accounted_tasks >= total and total > 0:
                # Determine overall workflow status
                if failed_count > 0:
                    workflow_status = b"failed"
                    logger.info(f"Workflow {workflow_id} failed with {failed_count} failed tasks")
                elif blocked_count > 0:
                    # Blocked tasks prevent workflow completion - similar to failed
                    workflow_status = b"failed"
                    logger.info(f"Workflow {workflow_id} failed with {blocked_count} blocked tasks")
                elif skipped_count > 0:
                    workflow_status = b"completed_with_skips"
                    logger.info(f"Workflow {workflow_id} completed with {skipped_count} skipped tasks")
                else:
                    workflow_status = b"completed"
                    logger.info(f"Workflow {workflow_id} completed successfully!")

                # Find the maximum completed_at timestamp from all tasks to use as workflow completion time
                # This ensures the workflow completed_at is never before any task completed_at
                workflow_completed_at = None
                try:
                    # Get all task IDs for this workflow
                    shard = default_sharding.get_shard(workflow_id)
                    graph_key = f"{{shard:{shard}}}:workflow:dependency:graph:{workflow_id}"
                    graph_data = await self.redis.hgetall(graph_key.encode())

                    task_ids = [k.decode() for k in graph_data.keys()] if graph_data else []

                    # Get completed_at for each task
                    max_timestamp = None
                    for task_id in task_ids:
                        task_key = default_sharding.get_task_key(task_id, workflow_id)
                        task_completed_at = await self.redis.hget(task_key.encode(), b"completed_at")
                        if task_completed_at:
                            task_timestamp_str = task_completed_at.decode()
                            try:
                                task_timestamp = datetime.fromisoformat(task_timestamp_str)
                                if max_timestamp is None or task_timestamp > max_timestamp:
                                    max_timestamp = task_timestamp
                            except:
                                pass

                    # Use the maximum task completion time, or current time if no tasks have completed_at
                    if max_timestamp:
                        workflow_completed_at = max_timestamp.isoformat()
                    else:
                        workflow_completed_at = datetime.utcnow().isoformat()

                except Exception as e:
                    logger.warning(f"Failed to determine workflow completion time from tasks: {e}")
                    workflow_completed_at = datetime.utcnow().isoformat()

                # Emit workflow completion event
                event_type = EventType.WORKFLOW_FAILED if workflow_status == b"failed" else EventType.WORKFLOW_COMPLETED
                await self.event_store.store_event(
                    event_type=event_type,
                    workflow_id=workflow_id,
                    level=EventLevel.CRITICAL,
                    data={
                        'status': workflow_status.decode(),
                        'total_tasks': total,
                        'completed_tasks': completed,
                        'skipped_tasks': skipped_count,
                        'blocked_tasks': blocked_count,
                        'failed_tasks': failed_count,
                        'worker_id': self.config.worker_id
                    }
                )

                # Update workflow status in consolidated state
                await self.redis.hset(
                    default_sharding.get_workflow_key("state", workflow_id).encode(),
                    mapping={
                        b"status": workflow_status,
                        b"completed_at": workflow_completed_at.encode(),
                        b"completed_tasks": str(completed).encode(),
                        b"skipped_tasks": str(skipped_count).encode(),
                        b"blocked_tasks": str(blocked_count).encode(),
                        b"failed_tasks": str(failed_count).encode(),
                        b"running_tasks": b"0",  # All tasks done
                        b"pending_tasks": b"0"   # All tasks done
                    }
                )

                # Emit workflow completion event
                shard = default_sharding.get_shard(workflow_id)
                await self.redis.xadd(
                    default_sharding.get_stream_key("workflow:completed", workflow_id).encode(),
                    {
                        b"workflow_id": workflow_id.encode(),
                        b"timestamp": datetime.utcnow().isoformat().encode()
                    }
                )

    def build_dependency_graph(self, workflow: Dict) -> Dict[str, List[str]]:
        """Build dependency graph from workflow definition"""
        graph = {}
        tasks = workflow.get('tasks', [])

        for task in tasks:
            task_id = task.get('id', task.get('name'))
            dependencies = task.get('dependencies', [])
            graph[task_id] = dependencies

        return graph

    def find_initial_tasks(self, dependency_graph: Dict, workflow: Dict) -> List[Dict]:
        """Find tasks with no dependencies"""
        initial_tasks = []
        tasks = workflow.get('tasks', [])

        for task in tasks:
            task_id = task.get('id', task.get('name'))
            if not dependency_graph.get(task_id, []):
                initial_tasks.append(task)

        return initial_tasks

    def find_task_by_id(self, workflow: Dict, task_id: str) -> Optional[Dict]:
        """Find task data by ID"""
        for task in workflow.get('tasks', []):
            if task.get('id', task.get('name')) == task_id:
                return task
        return None

    async def resolve_task_parameters(self, task: Dict, workflow_id: str) -> Dict:
        """
        Resolve parameter references in task parameters.

        Supports ${task_id.field} syntax to reference results from other tasks.
        Also automatically injects dependency results as 'inputs' for convenience.

        Args:
            task: Task dictionary with params to resolve
            workflow_id: ID of the workflow

        Returns:
            Task with resolved parameters
        """
        params = task.get('params', {})
        resolved_params = await self._substitute_parameters(params, workflow_id)
        task['params'] = resolved_params

        # Also resolve in args if present
        if 'args' in params:
            resolved_args = []
            for arg in params.get('args', []):
                resolved_arg = await self._substitute_parameters(arg, workflow_id)
                # If the resolved arg is a dict/list, JSON encode it for command line
                if isinstance(resolved_arg, (dict, list)):
                    resolved_arg = json.dumps(resolved_arg)
                resolved_args.append(resolved_arg)
            task['params']['args'] = resolved_args

        # Automatically inject dependency results as inputs for convenience
        dependencies = task.get('dependencies', [])
        if dependencies:
            inputs = task['params'].get('inputs', {})

            # Fetch results from each dependency
            for dep_id in dependencies:
                task_status = await self.redis.hgetall(
                    default_sharding.get_task_key(dep_id, workflow_id).encode()
                )

                if task_status and b'result' in task_status:
                    # Parse the result
                    try:
                        result_data = json.loads(task_status[b'result'].decode())
                        # Add to inputs using the task ID as key
                        inputs[dep_id] = result_data
                        logger.debug(f"Injected {dep_id} result into inputs for task {task.get('id')}")
                    except json.JSONDecodeError:
                        # If result is not JSON, add as string
                        inputs[dep_id] = task_status[b'result'].decode()

            # Update task params with inputs
            if inputs:
                task['params']['inputs'] = inputs

        return task

    async def _substitute_parameters(self, obj: Any, workflow_id: str) -> Any:
        """
        Recursively substitute parameter references in an object.

        Args:
            obj: Object to process (str, dict, list, or other)
            workflow_id: ID of the workflow

        Returns:
            Object with all parameter references resolved
        """
        if isinstance(obj, str):
            return await self._substitute_string_parameters(obj, workflow_id)
        elif isinstance(obj, dict):
            result = {}
            for k, v in obj.items():
                result[k] = await self._substitute_parameters(v, workflow_id)
            return result
        elif isinstance(obj, list):
            result = []
            for item in obj:
                result.append(await self._substitute_parameters(item, workflow_id))
            return result
        else:
            return obj

    async def _substitute_string_parameters(self, text: str, workflow_id: str) -> Any:
        """
        Substitute parameter references in a string.

        Args:
            text: String that may contain ${...} references
            workflow_id: ID of the workflow

        Returns:
            Resolved value (may be string or actual referenced object)
        """
        # Pattern for ${task-id.field} references
        pattern = r'\$\{([^}]+)\}'
        matches = re.findall(pattern, text)

        if not matches:
            return text

        for match in matches:
            ref_value = await self._resolve_reference(match, workflow_id)

            if ref_value is not None:
                # If entire string is just the reference, return actual value
                if text == f"${{{match}}}":
                    logger.info(f"Parameter substitution: ${{{match}}} -> {ref_value}")
                    return ref_value
                # Otherwise, do string replacement
                else:
                    replacement = json.dumps(ref_value) if not isinstance(ref_value, str) else ref_value
                    logger.info(f"Parameter substitution in string: ${{{match}}} -> {replacement}")
                    text = text.replace(f"${{{match}}}", replacement)

        return text

    async def _resolve_reference(self, reference: str, workflow_id: str) -> Any:
        """
        Resolve a single parameter reference.

        Args:
            reference: Reference string (e.g., "task1.result")
            workflow_id: ID of the workflow

        Returns:
            Resolved value or None if not found
        """
        parts = reference.split('.')
        ref_task_id = parts[0]
        field_path = parts[1:] if len(parts) > 1 else ['result']

        # Get task result from Redis
        task_status = await self.redis.hgetall(default_sharding.get_task_key(ref_task_id, workflow_id).encode())

        if not task_status or b'result' not in task_status:
            logger.warning(f"Referenced task {ref_task_id} not found or has no result")
            return None

        # Parse the result
        result_data = json.loads(task_status[b'result'].decode())

        # Navigate through field path
        current = result_data
        for field in field_path:
            if isinstance(current, dict) and field in current:
                current = current[field]
            else:
                logger.warning(f"Field {field} not found in {ref_task_id} result")
                return None

        return current

    async def _check_validation_dependencies(
        self,
        workflow_id: str,
        task_id: str,
        dependencies: List[str]
    ) -> bool:
        """
        Check if any validation dependencies failed.
        Convention: Tasks depending on validation/v1 tasks are skipped if validation fails.

        Args:
            workflow_id: Workflow ID
            task_id: Task to check
            dependencies: List of dependency task IDs

        Returns:
            True if task should be skipped due to validation failure
        """
        # Get workflow data to check task protocols
        workflow_data = await self.redis.hget(
            default_sharding.get_workflow_key("data", workflow_id).encode(),
            b"workflow"
        )

        if not workflow_data:
            return False

        workflow = json.loads(workflow_data)

        # Check each dependency
        for dep_id in dependencies:
            # Find the dependency task in workflow
            dep_task = self.find_task_by_id(workflow, dep_id)

            if not dep_task:
                continue

            # Check if this is a validation task (convention-based behavior)
            if dep_task.get('protocol') == 'validation/v1':
                # Get the validation task result
                task_result = await self.redis.hget(
                    default_sharding.get_task_key(dep_id, workflow_id).encode(),
                    b'result'
                )

                if task_result:
                    result_data = json.loads(task_result.decode())

                    # Check validation result
                    if not result_data.get('valid', False):
                        # Check on_failure behavior from validation result
                        on_failure = result_data.get('on_failure', 'skip')

                        if on_failure == 'skip':
                            logger.info(f"Validation {dep_id} returned valid=false, skipping {task_id}")

                            # Emit task skipped event
                            await self.event_store.store_event(
                                event_type=EventType.TASK_SKIPPED,
                                workflow_id=workflow_id,
                                task_id=task_id,
                                level=EventLevel.IMPORTANT,
                                data={
                                    'reason': f"Validation {dep_id} returned false",
                                    'validation_task': dep_id,
                                    'on_failure': on_failure
                                }
                            )

                            # Mark as skipped in status
                            await self.redis.hset(
                                default_sharding.get_task_key(task_id, workflow_id).encode(),
                                mapping={
                                    b"status": b"skipped",
                                    b"skipped_reason": f"Validation {dep_id} failed".encode(),
                                    b"skipped_at": datetime.utcnow().isoformat().encode()
                                }
                            )
                            # Also update workflow tracking
                            await self.redis.sadd(
                                default_sharding.get_workflow_key("tasks:skipped", workflow_id).encode(),
                                task_id.encode()
                            )
                            return True

                        elif on_failure == 'fail':
                            logger.info(f"Validation {dep_id} returned valid=false, failing {task_id}")
                            # Mark task as failed
                            await self.redis.hset(
                                default_sharding.get_task_key(task_id, workflow_id).encode(),
                                mapping={
                                    b"status": b"failed",
                                    b"error": f"Validation dependency {dep_id} failed".encode(),
                                    b"failed_at": datetime.utcnow().isoformat().encode()
                                }
                            )
                            # Also update workflow tracking
                            await self.redis.sadd(
                                default_sharding.get_workflow_key("tasks:failed", workflow_id).encode(),
                                task_id.encode()
                            )
                            # Emit failure event
                            await self.redis.xadd(
                                default_sharding.get_stream_key("task:failed", workflow_id).encode(),
                                {
                                    b"workflow_id": workflow_id.encode(),
                                    b"task_id": task_id.encode(),
                                    b"error": f"Validation dependency {dep_id} failed".encode(),
                                    b"timestamp": datetime.utcnow().isoformat().encode()
                                }
                            )
                            return True

                        elif on_failure == 'block':
                            logger.info(f"Validation {dep_id} returned valid=false, blocking {task_id}")

                            # Emit task blocked event (using CANCELLED as closest match)
                            await self.event_store.store_event(
                                event_type=EventType.TASK_CANCELLED,  # No TASK_BLOCKED yet
                                workflow_id=workflow_id,
                                task_id=task_id,
                                level=EventLevel.IMPORTANT,
                                data={
                                    'reason': f"Blocked by validation {dep_id}",
                                    'validation_task': dep_id,
                                    'on_failure': on_failure,
                                    'status': 'blocked'
                                }
                            )

                            # Mark task as blocked
                            await self.redis.hset(
                                default_sharding.get_task_key(task_id, workflow_id).encode(),
                                mapping={
                                    b"status": b"blocked",
                                    b"blocked_reason": f"Validation {dep_id} failed".encode(),
                                    b"blocked_at": datetime.utcnow().isoformat().encode()
                                }
                            )
                            # Also update workflow tracking
                            await self.redis.sadd(
                                default_sharding.get_workflow_key("tasks:blocked", workflow_id).encode(),
                                task_id.encode()
                            )
                            # Emit blocked event (similar to failed)
                            await self.redis.xadd(
                                default_sharding.get_stream_key("task:blocked", workflow_id).encode(),
                                {
                                    b"workflow_id": workflow_id.encode(),
                                    b"task_id": task_id.encode(),
                                    b"reason": f"Validation {dep_id} failed".encode(),
                                    b"timestamp": datetime.utcnow().isoformat().encode()
                                }
                            )
                            return True

                        # Check for gate control directives
                        control = result_data.get('control', {})
                        if control:
                            skip_tasks = control.get('skip_tasks', [])
                            # Find current task to get its name
                            current_task = self.find_task_by_id(workflow, task_id)
                            task_name = current_task.get('name') if current_task else task_id
                            if task_name in skip_tasks:
                                logger.info(f"Task {task_name} in skip list from validation gate {dep_id}")
                                await self.redis.hset(
                                    default_sharding.get_task_key(task_id, workflow_id).encode(),
                                    mapping={
                                        b"status": b"blocked",
                                        b"blocked_reason": f"Blocked by validation gate {dep_id}".encode(),
                                        b"blocked_at": datetime.utcnow().isoformat().encode()
                                    }
                                )
                                return True

        return False

    async def handle_task_cancellation(self, workflow_id: str, data: Dict):
        """Handle task cancellation - with hard fail policy, cancel dependent tasks and workflow"""
        task_id = data.get('task_id')
        if not task_id:
            logger.error(f"Missing task_id in cancellation message")
            return

        logger.info(f"Processing task cancellation with hard fail policy: {task_id} in workflow {workflow_id}")

        # Mark task as cancelled in Redis (if not already)
        task_key = default_sharding.get_task_key(task_id, workflow_id)
        current_status = await self.redis.hget(task_key.encode(), b"status")

        if current_status and current_status.decode() in ["completed", "failed", "cancelled", "blocked"]:
            logger.info(f"Task {task_id} already in terminal state: {current_status.decode()}")
            return

        # Update task status to cancelled
        await self.redis.hset(
            task_key.encode(),
            mapping={
                b"status": b"cancelled",
                b"cancelled_at": datetime.utcnow().isoformat().encode(),
                b"cancelled_reason": data.get('reason', b'user_requested')
            }
        )

        # Add to cancelled tasks set
        await self.redis.sadd(
            default_sharding.get_workflow_key("tasks:cancelled", workflow_id).encode(),
            task_id.encode()
        )

        # Get dependency graph to find dependent tasks
        graph_key = default_sharding.get_workflow_key("dependency:graph", workflow_id)
        dependency_graph = {}

        graph_data = await self.redis.hgetall(graph_key.encode())
        for tid, deps in graph_data.items():
            dependency_graph[tid.decode()] = json.loads(deps.decode())

        # Find tasks that depend on the cancelled task
        dependent_tasks = []
        for tid, deps in dependency_graph.items():
            if task_id in deps:
                dependent_tasks.append(tid)

        # HARD FAIL POLICY: Cancel all dependent tasks (not just block them)
        for dep_task_id in dependent_tasks:
            dep_task_key = default_sharding.get_task_key(dep_task_id, workflow_id)
            dep_status = await self.redis.hget(dep_task_key.encode(), b"status")

            # Only cancel if not already in terminal state
            if not dep_status or dep_status.decode() not in ["completed", "failed", "cancelled", "blocked"]:
                logger.info(f"Cancelling dependent task {dep_task_id} due to cancelled dependency {task_id} (hard fail policy)")

                # Emit cancellation event for the dependent task (will cascade)
                await self.redis.xadd(
                    default_sharding.get_stream_key("task:cancelled", workflow_id).encode(),
                    {
                        b"task_id": dep_task_id.encode(),
                        b"workflow_id": workflow_id.encode(),
                        b"reason": f"dependency_{task_id}_cancelled".encode(),
                        b"timestamp": datetime.utcnow().isoformat().encode()
                    }
                )

        # HARD FAIL POLICY: Cancel the entire workflow when any task is cancelled
        logger.info(f"Cancelling entire workflow {workflow_id} due to task {task_id} cancellation (hard fail policy)")

        # Emit workflow cancellation event
        await self.redis.xadd(
            default_sharding.get_stream_key("workflow:cancelled", workflow_id).encode(),
            {
                b"workflow_id": workflow_id.encode(),
                b"reason": f"task_{task_id}_cancelled_hard_fail".encode(),
                b"timestamp": datetime.utcnow().isoformat().encode()
            }
        )

    async def handle_workflow_cancellation(self, workflow_id: str, data: Dict):
        """Handle workflow cancellation - cancel all non-terminal tasks"""
        logger.info(f"Processing workflow cancellation: {workflow_id}")

        # Get all tasks in the workflow
        tasks_key = default_sharding.get_workflow_key("tasks", workflow_id)
        task_ids = await self.redis.smembers(tasks_key.encode())

        if not task_ids:
            # Get tasks from workflow data if not in tasks set
            workflow_data = await self.redis.hget(
                default_sharding.get_workflow_key("data", workflow_id).encode(),
                b"workflow"
            )
            if workflow_data:
                workflow = json.loads(workflow_data.decode())
                task_ids = [task['id'].encode() for task in workflow.get('tasks', [])]

        cancelled_count = 0
        for task_id_bytes in task_ids:
            task_id = task_id_bytes.decode() if isinstance(task_id_bytes, bytes) else task_id_bytes
            task_key = default_sharding.get_task_key(task_id, workflow_id)

            # Check current status
            current_status = await self.redis.hget(task_key.encode(), b"status")

            # Only cancel non-terminal tasks
            if not current_status or current_status.decode() not in ["completed", "failed", "cancelled", "blocked"]:
                # Emit task cancellation event for each task
                await self.redis.xadd(
                    default_sharding.get_stream_key("task:cancelled", workflow_id).encode(),
                    {
                        b"task_id": task_id.encode(),
                        b"workflow_id": workflow_id.encode(),
                        b"reason": b"workflow_cancelled",
                        b"timestamp": datetime.utcnow().isoformat().encode()
                    }
                )
                cancelled_count += 1

        logger.info(f"Emitted cancellation for {cancelled_count} tasks in workflow {workflow_id}")

        # Update workflow status
        await self.redis.hset(
            default_sharding.get_workflow_key("status", workflow_id).encode(),
            mapping={
                b"status": b"cancelled",
                b"cancelled_at": datetime.utcnow().isoformat().encode(),
                b"cancelled_reason": data.get('reason', b'user_requested')
            }
        )

        # Store cancellation event
        await self.event_store.store_event(
            event_type=EventType.WORKFLOW_CANCELLED,
            workflow_id=workflow_id,
            level=EventLevel.CRITICAL,
            data={
                'reason': data.get('reason', 'user_requested'),
                'tasks_cancelled': cancelled_count
            }
        )
