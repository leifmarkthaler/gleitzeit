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
        return ["task:completed", "workflow:submitted"]

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
            elif "workflow:submitted" in stream:
                await self.handle_workflow_submission(workflow_id, data)

            return True  # Successfully processed

        except Exception as e:
            logger.error(f"Failed to process dependency message: {e}", exc_info=True)
            return False  # Retry on exception

    async def handle_workflow_submission(self, workflow_id: str, data: Dict):
        """Process newly submitted workflow"""
        logger.info(f"Processing workflow submission: {workflow_id}")

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

        # Store workflow data
        await self.redis.hset(
            default_sharding.get_workflow_key("data", workflow_id).encode(),
            mapping={
                b"workflow": json.dumps(workflow_data).encode(),
                b"submitted_at": datetime.utcnow().isoformat().encode(),
                b"status": b"running"
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

        # Track pending tasks
        pending_count = len(workflow_data.get('tasks', [])) - len(initial_tasks)
        await self.redis.hset(
            default_sharding.get_workflow_key("status", workflow_id).encode(),
            mapping={
                b"total_tasks": str(len(workflow_data.get('tasks', []))).encode(),
                b"completed_tasks": b"0",
                b"pending_tasks": str(pending_count).encode(),
                b"running_tasks": str(len(initial_tasks)).encode()
            }
        )

    async def handle_task_completion(self, workflow_id: str, data: Dict):
        """Handle task completion and resolve dependencies"""
        task_id = data.get('task_id')
        logger.info(f"Processing task completion: {task_id} from workflow {workflow_id}")

        # Update completed tasks count
        await self.redis.hincrby(
            default_sharding.get_workflow_key("status", workflow_id).encode(),
            b"completed_tasks",
            1
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

        # Mark task as completed
        completed_key = default_sharding.get_workflow_key("tasks:completed", workflow_id)
        await self.redis.sadd(completed_key.encode(), task_id.encode())

        # Find newly ready tasks
        ready_tasks = await self.find_ready_tasks(
            workflow_id,
            task_id,
            dependency_graph
        )

        # Emit ready tasks to same shard
        if ready_tasks:
            shard = default_sharding.get_shard(workflow_id)

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
                            default_sharding.get_task_key("status", workflow_id, task_id).encode(),
                            mapping={
                                b"status": b"skipped",
                                b"skipped_reason": b"validation_failed",
                                b"skipped_at": datetime.utcnow().isoformat().encode()
                            }
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

        return ready_tasks

    async def check_workflow_completion(self, workflow_id: str):
        """Check if workflow is complete, including skipped and blocked tasks"""
        status = await self.redis.hgetall(default_sharding.get_workflow_key("status", workflow_id).encode())

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

                # Update workflow status
                await self.redis.hset(
                    default_sharding.get_workflow_key("status", workflow_id).encode(),
                    mapping={
                        b"status": workflow_status,
                        b"completed_at": datetime.utcnow().isoformat().encode(),
                        b"completed_tasks": str(completed).encode(),
                        b"skipped_tasks": str(skipped_count).encode(),
                        b"blocked_tasks": str(blocked_count).encode(),
                        b"failed_tasks": str(failed_count).encode()
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

