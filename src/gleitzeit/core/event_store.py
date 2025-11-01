"""
Event Store for Gleitzeit Replayability

Captures and stores workflow execution events for replay and auditing.
"""

import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum

from .events import EventType
from .sharding import default_sharding

logger = logging.getLogger(__name__)


class EventLevel(str, Enum):
    """Event importance levels for filtering"""
    CRITICAL = "critical"  # State changes (task completion, failure)
    IMPORTANT = "important"  # Task starts, dependency resolution
    INFO = "info"  # General informational events (timer created, signal registered)
    DETAIL = "detail"  # Parameter resolution, validation checks
    DEBUG = "debug"  # Internal state, timing


@dataclass
class WorkflowEvent:
    """
    Structured event for workflow execution
    """
    event_id: str
    event_type: EventType
    workflow_id: str
    task_id: Optional[str]
    timestamp: str
    level: EventLevel
    data: Dict[str, Any]

    # Replay metadata
    replay_id: Optional[str] = None
    is_replay: bool = False
    original_event_id: Optional[str] = None  # If replaying an event

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return {
            'event_id': self.event_id,
            'event_type': self.event_type.value if isinstance(self.event_type, Enum) else self.event_type,
            'workflow_id': self.workflow_id,
            'task_id': self.task_id,
            'timestamp': self.timestamp,
            'level': self.level.value if isinstance(self.level, Enum) else self.level,
            'data': self.data,
            'replay_id': self.replay_id,
            'is_replay': self.is_replay,
            'original_event_id': self.original_event_id
        }

    def to_redis_message(self) -> Dict[bytes, bytes]:
        """Convert to Redis stream message format"""
        return {
            b'event_id': self.event_id.encode(),
            b'event_type': self.event_type.value.encode() if isinstance(self.event_type, Enum) else self.event_type.encode(),
            b'task_id': (self.task_id or '').encode(),
            b'timestamp': self.timestamp.encode(),
            b'level': self.level.value.encode() if isinstance(self.level, Enum) else self.level.encode(),
            b'data': json.dumps(self.data).encode(),
            b'replay_id': (self.replay_id or '').encode(),
            b'is_replay': str(self.is_replay).encode()
        }


class EventStore:
    """
    Manages event storage and retrieval for workflow replay
    """

    def __init__(self, redis_client, config: Optional[Dict[str, Any]] = None):
        self.redis = redis_client
        self.config = config or {}

        # Configuration
        self.max_events_per_workflow = self.config.get('max_events_per_workflow', 10000)
        self.event_ttl_seconds = self.config.get('event_ttl_seconds', 86400 * 30)  # 30 days
        self.batch_size = self.config.get('batch_size', 100)

    async def store_event(
        self,
        event_type: EventType,
        workflow_id: str,
        task_id: Optional[str] = None,
        level: EventLevel = EventLevel.IMPORTANT,
        data: Optional[Dict[str, Any]] = None,
        replay_id: Optional[str] = None
    ) -> str:
        """
        Store a workflow event

        Args:
            event_type: Type of event
            workflow_id: Workflow identifier
            task_id: Task identifier (if task-specific)
            level: Event importance level
            data: Event data/context
            replay_id: Replay session ID (if replaying)

        Returns:
            Event ID
        """
        import uuid

        # Generate event
        event = WorkflowEvent(
            event_id=f"evt_{uuid.uuid4().hex[:12]}",
            event_type=event_type,
            workflow_id=workflow_id,
            task_id=task_id,
            timestamp=datetime.utcnow().isoformat(),
            level=level,
            data=data or {},
            replay_id=replay_id,
            is_replay=bool(replay_id)
        )

        # Get stream key for this workflow
        stream_key = self._get_event_stream_key(workflow_id)

        # Store in Redis stream with automatic trimming
        await self.redis.xadd(
            stream_key.encode(),
            event.to_redis_message(),
            maxlen=self.max_events_per_workflow,
            approximate=True  # Allow approximate trimming for performance
        )

        # Publish to pub/sub channel for WebSocket broadcasting
        try:
            await self.redis.publish(
                'gleitzeit:events',
                json.dumps({
                    'type': 'workflow_event',
                    'workflow_id': workflow_id,
                    'task_id': task_id,
                    'event_type': event_type.value if hasattr(event_type, 'value') else str(event_type),
                    'timestamp': event.timestamp,
                    'level': level.value if hasattr(level, 'value') else str(level),
                    'data': data or {}
                })
            )
            logger.debug(f"Published event {event.event_id} to pub/sub channel")
        except Exception as e:
            logger.error(f"Failed to publish event to pub/sub: {e}")

        logger.debug(f"Stored event {event.event_id} for workflow {workflow_id}")
        return event.event_id

    async def get_timeline(
        self,
        workflow_id: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        event_types: Optional[List[EventType]] = None,
        min_level: EventLevel = EventLevel.IMPORTANT
    ) -> List[WorkflowEvent]:
        """
        Retrieve workflow execution timeline

        Args:
            workflow_id: Workflow to get timeline for
            start_time: Start of time range (Redis stream ID or '-')
            end_time: End of time range (Redis stream ID or '+')
            event_types: Filter to specific event types
            min_level: Minimum event level to include

        Returns:
            List of events in chronological order
        """
        stream_key = self._get_event_stream_key(workflow_id)

        # Read events from stream
        events_raw = await self.redis.xrange(
            stream_key.encode(),
            min=start_time.encode() if start_time else b'-',
            max=end_time.encode() if end_time else b'+',
            count=self.max_events_per_workflow
        )

        # Parse and filter events
        events = []
        level_hierarchy = {
            EventLevel.DEBUG: 0,
            EventLevel.DETAIL: 1,
            EventLevel.INFO: 2,
            EventLevel.IMPORTANT: 3,
            EventLevel.CRITICAL: 4
        }
        min_level_value = level_hierarchy.get(min_level, 0)

        for event_id, event_data in events_raw:
            # Decode event data
            event_dict = {
                'event_id': event_data.get(b'event_id', b'').decode(),
                'event_type': event_data.get(b'event_type', b'').decode(),
                'workflow_id': workflow_id,
                'task_id': event_data.get(b'task_id', b'').decode() or None,
                'timestamp': event_data.get(b'timestamp', b'').decode(),
                'level': event_data.get(b'level', b'important').decode(),
                'data': json.loads(event_data.get(b'data', b'{}')),
                'replay_id': event_data.get(b'replay_id', b'').decode() or None,
                'is_replay': event_data.get(b'is_replay', b'false').decode() == 'true'
            }

            # Apply filters
            event_level = EventLevel(event_dict['level'])
            if level_hierarchy.get(event_level, 0) < min_level_value:
                continue

            if event_types and event_dict['event_type'] not in [et.value for et in event_types]:
                continue

            # Convert to WorkflowEvent
            events.append(WorkflowEvent(
                event_id=event_dict['event_id'],
                event_type=EventType(event_dict['event_type']),
                workflow_id=event_dict['workflow_id'],
                task_id=event_dict['task_id'],
                timestamp=event_dict['timestamp'],
                level=event_level,
                data=event_dict['data'],
                replay_id=event_dict['replay_id'],
                is_replay=event_dict['is_replay']
            ))

        return events

    async def get_task_execution_order(self, workflow_id: str) -> List[str]:
        """
        Get the order in which tasks were executed

        Returns:
            List of task IDs in execution order
        """
        timeline = await self.get_timeline(
            workflow_id,
            event_types=[EventType.TASK_STARTED]
        )

        return [event.task_id for event in timeline if event.task_id]

    async def clear_events(self, workflow_id: str):
        """
        Clear all events for a workflow (for testing/cleanup)
        """
        stream_key = self._get_event_stream_key(workflow_id)
        await self.redis.delete(stream_key.encode())
        logger.info(f"Cleared events for workflow {workflow_id}")

    def _get_event_stream_key(self, workflow_id: str) -> str:
        """Get Redis key for workflow event stream"""
        shard = default_sharding.get_shard(workflow_id)
        return f"{{shard:{shard}}}:events:{workflow_id}"

    async def get_task_timeline(self, workflow_id: str, task_id: str) -> List[WorkflowEvent]:
        """
        Get timeline of events for a specific task within a workflow

        Args:
            workflow_id: The workflow identifier
            task_id: The specific task identifier

        Returns:
            List of events related to this task, sorted by timestamp
        """
        # Get all events for the workflow
        timeline = await self.get_timeline(workflow_id)

        # Filter for this specific task
        task_events = [
            event for event in timeline
            if event.task_id == task_id or (
                # Include workflow-level events that affect this task
                event.data and (
                    task_id in event.data.get('tasks_to_replay', []) or
                    task_id in event.data.get('failed_tasks', []) or
                    task_id in event.data.get('completed_tasks', []) or
                    task_id in event.data.get('skipped_tasks', []) or
                    task_id in event.data.get('blocked_tasks', [])
                )
            )
        ]

        return task_events

    async def get_task_execution_details(self, workflow_id: str, task_id: str) -> Dict[str, Any]:
        """
        Get detailed execution information for a specific task

        Args:
            workflow_id: The workflow identifier
            task_id: The specific task identifier

        Returns:
            Dictionary with task execution details including timing, status, and data
        """
        events = await self.get_task_timeline(workflow_id, task_id)

        details = {
            'task_id': task_id,
            'workflow_id': workflow_id,
            'status': 'unknown',
            'start_time': None,
            'end_time': None,
            'duration_ms': None,
            'execution_id': None,
            'protocol': None,
            'handler_id': None,
            'worker_id': None,
            'result': None,
            'error': None,
            'skip_reason': None,
            'validation_task': None,
            'retry_count': 0,
            'is_validation': False,
            'events': []
        }

        # Process events chronologically
        for event in events:
            event_info = {
                'timestamp': event.timestamp,
                'type': event.event_type.value if hasattr(event.event_type, 'value') else str(event.event_type),
                'data': event.data
            }
            details['events'].append(event_info)

            # Extract execution details based on event type
            if event.event_type == EventType.TASK_STARTED:
                details['status'] = 'started'
                details['start_time'] = event.timestamp
                details['execution_id'] = event.data.get('execution_id')
                details['protocol'] = event.data.get('protocol')
                details['handler_id'] = event.data.get('handler_id')
                details['is_validation'] = event.data.get('protocol') == 'validation/v1'

            elif event.event_type == EventType.TASK_COMPLETED:
                details['status'] = 'completed'
                details['end_time'] = event.timestamp
                details['result'] = event.data.get('result')
                details['worker_id'] = event.data.get('worker_id')

            elif event.event_type == EventType.TASK_FAILED:
                details['status'] = 'failed'
                details['end_time'] = event.timestamp
                details['error'] = event.data.get('error')
                details['worker_id'] = event.data.get('worker_id')

            elif event.event_type == EventType.TASK_SKIPPED:
                details['status'] = 'skipped'
                details['skip_reason'] = event.data.get('reason')
                details['validation_task'] = event.data.get('validation_task')

            elif event.event_type == EventType.TASK_CANCELLED:
                details['status'] = 'blocked'
                details['skip_reason'] = event.data.get('reason')
                details['validation_task'] = event.data.get('validation_task')

            elif event.event_type == EventType.WORKFLOW_RESUMED:
                if task_id in event.data.get('tasks_to_replay', []):
                    details['retry_count'] += 1

        # Calculate duration if we have both start and end times
        if details['start_time'] and details['end_time']:
            try:
                start = datetime.fromisoformat(details['start_time'])
                end = datetime.fromisoformat(details['end_time'])
                duration = (end - start).total_seconds() * 1000  # Convert to milliseconds
                details['duration_ms'] = round(duration, 2)
            except:
                pass  # If parsing fails, leave duration as None

        return details

    async def get_execution_summary(self, workflow_id: str) -> Dict[str, Any]:
        """
        Get execution summary from events

        Returns:
            Summary with task counts, timing, etc.
        """
        timeline = await self.get_timeline(workflow_id)

        if not timeline:
            return {}

        # Analyze timeline
        summary = {
            'workflow_id': workflow_id,
            'start_time': timeline[0].timestamp if timeline else None,
            'end_time': timeline[-1].timestamp if timeline else None,
            'total_events': len(timeline),
            'tasks_started': 0,
            'tasks_completed': 0,
            'tasks_failed': 0,
            'tasks_skipped': 0,
            'validation_tasks': 0,
            'replay_events': 0
        }

        for event in timeline:
            if event.event_type == EventType.TASK_STARTED:
                summary['tasks_started'] += 1
            elif event.event_type == EventType.TASK_COMPLETED:
                summary['tasks_completed'] += 1
            elif event.event_type == EventType.TASK_FAILED:
                summary['tasks_failed'] += 1
            elif event.event_type == 'task:skipped':  # Add this event type if needed
                summary['tasks_skipped'] += 1

            if event.task_id and 'validate' in event.task_id:
                summary['validation_tasks'] += 1

            if event.is_replay:
                summary['replay_events'] += 1

        return summary