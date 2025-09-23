"""
Replay Worker for Gleitzeit

Orchestrates workflow replay by leveraging existing stateless workers.
Maintains the stateless architecture by re-computing parameters on demand.
"""

import json
import logging
import asyncio
from typing import Dict, Any, Optional, List, Set
from datetime import datetime
from enum import Enum

from .base import BaseWorker, WorkerConfig
from ..core.sharding import default_sharding
from ..core.models import TaskStatus
from ..core.events import EventType
from ..core.event_store import EventStore, EventLevel, WorkflowEvent

logger = logging.getLogger(__name__)


class ReplayMode(str, Enum):
    """Replay execution modes"""
    FULL = "full"  # Re-execute entire workflow
    FROM_TASK = "from_task"  # Start from specific task
    FAILED_ONLY = "failed_only"  # Only replay failed tasks
    DETERMINISTIC = "deterministic"  # Keep validation results for same path
    RE_EVALUATE = "re_evaluate"  # Re-evaluate validation conditions
    DEBUG = "debug"  # Step-through execution with breakpoints


class ReplayWorker(BaseWorker):
    """
    Orchestrates workflow replay using existing stateless workers.

    Key principle: Replay is re-computation, not data playback.
    DependencyWorker will re-resolve parameters from source data.
    """

    def __init__(self, config: Optional[WorkerConfig] = None):
        super().__init__(config)
        self.event_store = None
        self.replay_sessions = {}  # Track active replay sessions

    def get_base_streams(self) -> List[str]:
        """Base streams this worker type consumes"""
        return ["replay:request"]

    def get_consumer_streams(self) -> List[str]:
        """Replay worker listens to replay requests"""
        return ["replay:request"]

    async def process_message(self, stream: str, message_id: bytes, data: Dict[bytes, bytes]):
        """Process a stream message - required by BaseWorker"""
        # Decode the message data
        decoded_data = {k.decode(): v.decode() if isinstance(v, bytes) else v
                       for k, v in data.items()}
        await self.process_stream_message(stream, message_id, decoded_data)

    async def on_initialize(self):
        """Initialize replay worker resources"""
        self.event_store = EventStore(self.redis, config={
            'max_events_per_workflow': 10000,
            'event_ttl_seconds': 86400 * 30  # 30 days
        })
        logger.info("ReplayWorker initialized with event store")

    async def process_stream_message(self, stream: str, message_id: bytes, data: Dict):
        """Process replay request"""
        if "replay:request" in stream:
            await self.handle_replay_request(data)

    async def handle_replay_request(self, data: Dict):
        """Handle a replay request"""
        workflow_id = data.get('workflow_id')
        replay_mode = ReplayMode(data.get('mode', 'full'))
        start_from = data.get('start_from')
        use_cached_results = data.get('use_cached_results', True)
        replay_validations = data.get('replay_validations', False)

        logger.info(f"Starting replay for workflow {workflow_id} in mode {replay_mode}")

        # Generate replay ID
        import uuid
        replay_id = f"replay_{uuid.uuid4().hex[:12]}"

        # Store replay session
        self.replay_sessions[replay_id] = {
            'workflow_id': workflow_id,
            'mode': replay_mode,
            'started_at': datetime.utcnow().isoformat(),
            'status': 'running'
        }

        try:
            await self.replay_workflow(
                workflow_id=workflow_id,
                replay_mode=replay_mode,
                start_from=start_from,
                use_cached_results=use_cached_results,
                replay_validations=replay_validations,
                replay_id=replay_id
            )

            # Mark replay as completed
            self.replay_sessions[replay_id]['status'] = 'completed'
            self.replay_sessions[replay_id]['completed_at'] = datetime.utcnow().isoformat()

            logger.info(f"Replay {replay_id} completed successfully")

        except Exception as e:
            logger.error(f"Replay {replay_id} failed: {e}", exc_info=True)
            self.replay_sessions[replay_id]['status'] = 'failed'
            self.replay_sessions[replay_id]['error'] = str(e)

    async def replay_workflow(
        self,
        workflow_id: str,
        replay_mode: ReplayMode = ReplayMode.FULL,
        start_from: Optional[str] = None,
        use_cached_results: bool = True,
        replay_validations: bool = False,
        replay_id: Optional[str] = None
    ):
        """
        Replay a workflow execution.

        The replay process:
        1. Load workflow definition (original params)
        2. Load execution timeline (if following original order)
        3. Clear/reset task status as needed
           - If replay_validations=False, keep validation task results
           - This preserves the original execution path
        4. Let DependencyWorker re-compute parameters
        5. DependencyWorker checks validation dependencies
           - If validation result exists (not cleared), use it
           - Apply skip/fail/block behavior to dependent tasks
        6. Execute tasks (or use cached results)
        """
        logger.info(f"Replaying workflow {workflow_id} with mode {replay_mode}")

        # Load workflow definition
        workflow_data = await self.redis.hget(
            default_sharding.get_workflow_key("data", workflow_id).encode(),
            b"workflow"
        )
        if not workflow_data:
            raise ValueError(f"Workflow {workflow_id} not found")

        workflow = json.loads(workflow_data)

        # Load execution timeline
        timeline = await self.event_store.get_timeline(
            workflow_id,
            event_types=[EventType.TASK_STARTED, EventType.TASK_COMPLETED, EventType.TASK_FAILED],
            min_level=EventLevel.CRITICAL
        )

        # Determine which tasks to replay based on mode
        tasks_to_clear = await self._determine_tasks_to_clear(
            workflow_id, workflow, timeline, replay_mode, start_from, replay_validations
        )

        # Clear task results as needed
        await self._clear_task_results(workflow_id, tasks_to_clear)

        # Store replay metadata
        await self.redis.hset(
            default_sharding.get_workflow_key("replay", workflow_id).encode(),
            mapping={
                b"replay_id": replay_id.encode() if replay_id else b"",
                b"mode": replay_mode.value.encode(),
                b"started_at": datetime.utcnow().isoformat().encode(),
                b"tasks_cleared": json.dumps(list(tasks_to_clear)).encode()
            }
        )

        # Emit replay started event
        await self.event_store.store_event(
            event_type=EventType.WORKFLOW_RESUMED,  # Reuse existing event type
            workflow_id=workflow_id,
            level=EventLevel.CRITICAL,
            data={
                'replay_id': replay_id,
                'mode': replay_mode.value,
                'tasks_to_replay': len(tasks_to_clear)
            },
            replay_id=replay_id
        )

        # Based on mode, handle replay differently
        if replay_mode == ReplayMode.DEBUG:
            # Debug mode - allow stepping through
            await self._debug_replay(workflow_id, workflow, timeline, tasks_to_clear, replay_id)
        else:
            # Normal replay - re-submit to workflow system
            await self._standard_replay(workflow_id, workflow, tasks_to_clear, use_cached_results, replay_id)

    async def _determine_tasks_to_clear(
        self,
        workflow_id: str,
        workflow: Dict,
        timeline: List[WorkflowEvent],
        mode: ReplayMode,
        start_from: Optional[str],
        replay_validations: bool
    ) -> Set[str]:
        """Determine which task results to clear based on replay mode"""
        all_task_ids = {task['id'] for task in workflow.get('tasks', [])}
        tasks_to_clear = set()

        if mode == ReplayMode.FULL:
            # Clear all non-validation tasks (unless replay_validations=True)
            for task in workflow.get('tasks', []):
                task_id = task['id']
                is_validation = task.get('protocol') == 'validation/v1'

                if replay_validations or not is_validation:
                    tasks_to_clear.add(task_id)

        elif mode == ReplayMode.FROM_TASK:
            # Clear from specific task onward
            if not start_from:
                raise ValueError("start_from required for FROM_TASK mode")

            # Find task in timeline
            found_start = False
            for event in timeline:
                if event.task_id == start_from:
                    found_start = True
                if found_start and event.task_id:
                    task = self._find_task_by_id(workflow, event.task_id)
                    if task:
                        is_validation = task.get('protocol') == 'validation/v1'
                        if replay_validations or not is_validation:
                            tasks_to_clear.add(event.task_id)

        elif mode == ReplayMode.FAILED_ONLY:
            # Clear only failed tasks
            failed_tasks = await self._get_failed_tasks(workflow_id)
            tasks_to_clear = failed_tasks

        elif mode == ReplayMode.DETERMINISTIC:
            # Keep all validation results, clear everything else
            for task in workflow.get('tasks', []):
                if task.get('protocol') != 'validation/v1':
                    tasks_to_clear.add(task['id'])

        elif mode == ReplayMode.RE_EVALUATE:
            # Clear everything including validations
            tasks_to_clear = all_task_ids

        return tasks_to_clear

    async def _clear_task_results(self, workflow_id: str, task_ids: Set[str]):
        """Clear task results for replay"""
        for task_id in task_ids:
            task_key = default_sharding.get_task_key(task_id, workflow_id).encode()

            # Keep some metadata but clear result
            task_data = await self.redis.hgetall(task_key)
            if task_data:
                await self.redis.hdel(
                    task_key,
                    b"result",
                    b"status",
                    b"completed_at",
                    b"execution_id"
                )
                logger.debug(f"Cleared result for task {task_id}")

        # Update workflow status
        await self.redis.srem(
            default_sharding.get_workflow_key("tasks:completed", workflow_id).encode(),
            *[task_id.encode() for task_id in task_ids]
        )

    async def _standard_replay(
        self,
        workflow_id: str,
        workflow: Dict,
        tasks_cleared: Set[str],
        use_cached_results: bool,
        replay_id: str
    ):
        """Standard replay - resubmit to workflow system"""

        # Mark workflow as replaying
        await self.redis.hset(
            default_sharding.get_workflow_key("status", workflow_id).encode(),
            b"is_replay", b"true"
        )

        # The workflow is already loaded, just need to trigger re-evaluation
        # DependencyWorker will naturally re-evaluate dependencies

        # If all tasks were cleared, re-submit workflow
        if len(tasks_cleared) == len(workflow.get('tasks', [])):
            # Full replay - submit to workflow loader
            await self.redis.xadd(
                default_sharding.get_stream_key("workflow:submitted", workflow_id).encode(),
                {
                    b"workflow_id": workflow_id.encode(),
                    b"workflow": json.dumps(workflow).encode(),
                    b"replay_id": replay_id.encode(),
                    b"timestamp": datetime.utcnow().isoformat().encode()
                }
            )
            logger.info(f"Re-submitted workflow {workflow_id} for full replay")
        else:
            # Partial replay - trigger dependency check for cleared tasks
            for task_id in tasks_cleared:
                # Find task dependencies
                task = self._find_task_by_id(workflow, task_id)
                if task and not task.get('dependencies'):
                    # No dependencies - can run immediately
                    await self.redis.xadd(
                        default_sharding.get_stream_key("task:ready", workflow_id).encode(),
                        {
                            b"workflow_id": workflow_id.encode(),
                            b"task_id": task_id.encode(),
                            b"task": json.dumps(task).encode(),
                            b"replay_id": replay_id.encode(),
                            b"timestamp": datetime.utcnow().isoformat().encode()
                        }
                    )

            # Trigger dependency worker to re-evaluate
            await self._trigger_dependency_check(workflow_id, tasks_cleared)

    async def _debug_replay(
        self,
        workflow_id: str,
        workflow: Dict,
        timeline: List[WorkflowEvent],
        tasks_to_replay: Set[str],
        replay_id: str
    ):
        """Debug replay with stepping capability"""
        logger.info(f"Starting debug replay for workflow {workflow_id}")

        # This would integrate with a debugger interface
        # For now, just log the replay plan
        logger.info(f"Debug replay plan:")
        logger.info(f"  Tasks to replay: {tasks_to_replay}")
        logger.info(f"  Timeline events: {len(timeline)}")

        # Could implement breakpoints, step-through, etc.
        # For now, fall back to standard replay
        await self._standard_replay(workflow_id, workflow, tasks_to_replay, False, replay_id)

    async def _trigger_dependency_check(self, workflow_id: str, task_ids: Set[str]):
        """Trigger dependency worker to re-evaluate tasks"""
        # Emit a synthetic completion event to trigger dependency check
        for task_id in task_ids:
            # Check if task has dependencies that are complete
            # This will cause DependencyWorker to re-evaluate
            pass  # DependencyWorker will naturally handle this

    def _find_task_by_id(self, workflow: Dict, task_id: str) -> Optional[Dict]:
        """Find task definition by ID"""
        for task in workflow.get('tasks', []):
            if task.get('id') == task_id:
                return task
        return None

    async def _get_failed_tasks(self, workflow_id: str) -> Set[str]:
        """Get list of failed tasks from workflow"""
        failed_key = default_sharding.get_workflow_key("tasks:failed", workflow_id).encode()
        failed_tasks = await self.redis.smembers(failed_key)
        return {task_id.decode() for task_id in failed_tasks}

    async def get_replay_status(self, replay_id: str) -> Optional[Dict]:
        """Get status of a replay session"""
        return self.replay_sessions.get(replay_id)

    async def list_replays(self, workflow_id: Optional[str] = None) -> List[Dict]:
        """List replay sessions, optionally filtered by workflow"""
        replays = []
        for replay_id, session in self.replay_sessions.items():
            if not workflow_id or session['workflow_id'] == workflow_id:
                replays.append({
                    'replay_id': replay_id,
                    **session
                })
        return replays