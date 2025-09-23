"""
Event Monitor for System-Wide Event Timeline

Provides event-centric views across all workflows, enabling system monitoring,
debugging, and analysis of specific event types.
"""

import json
import logging
from typing import Dict, Any, Optional, List, Set
from datetime import datetime, timedelta
from dataclasses import dataclass
from collections import defaultdict

from .events import EventType
from .event_store import EventStore, EventLevel, WorkflowEvent
from .sharding import default_sharding

logger = logging.getLogger(__name__)


@dataclass
class EventMetrics:
    """Metrics for a specific event type"""
    event_type: EventType
    count: int = 0
    workflows_affected: Set[str] = None
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    avg_per_minute: float = 0.0

    def __post_init__(self):
        if self.workflows_affected is None:
            self.workflows_affected = set()


class EventMonitor:
    """
    System-wide event monitoring and analysis.

    Provides event-centric views across all workflows.
    """

    def __init__(self, redis_client, config: Optional[Dict[str, Any]] = None):
        self.redis = redis_client
        self.config = config or {}
        self.event_store = EventStore(redis_client, config)

    async def get_event_centric_timeline(
        self,
        event_types: List[EventType],
        limit: int = 100,
        time_window: Optional[timedelta] = None
    ) -> List[WorkflowEvent]:
        """
        Get timeline of specific event types across ALL workflows.

        Args:
            event_types: Types of events to retrieve
            limit: Maximum events to return
            time_window: Optional time window (e.g., last hour)

        Returns:
            List of events sorted by timestamp, newest first
        """
        all_events = []

        # Get list of all workflows (from a central index)
        workflow_ids = await self._get_active_workflows(time_window)

        # Collect events from each workflow
        for workflow_id in workflow_ids:
            try:
                events = await self.event_store.get_timeline(
                    workflow_id=workflow_id,
                    event_types=event_types,
                    min_level=EventLevel.CRITICAL
                )

                # Filter by time window if specified
                if time_window:
                    cutoff = datetime.utcnow() - time_window
                    events = [
                        e for e in events
                        if datetime.fromisoformat(e.timestamp) > cutoff
                    ]

                all_events.extend(events)

            except Exception as e:
                logger.warning(f"Failed to get events for workflow {workflow_id}: {e}")

        # Sort by timestamp (newest first) and limit
        all_events.sort(key=lambda e: e.timestamp, reverse=True)
        return all_events[:limit]

    async def get_failure_timeline(
        self,
        limit: int = 50,
        time_window: Optional[timedelta] = None
    ) -> List[WorkflowEvent]:
        """
        Get timeline of all failure events across the system.

        Returns:
            List of failure events (TASK_FAILED, WORKFLOW_FAILED)
        """
        return await self.get_event_centric_timeline(
            event_types=[EventType.TASK_FAILED, EventType.WORKFLOW_FAILED],
            limit=limit,
            time_window=time_window
        )

    async def get_validation_timeline(
        self,
        limit: int = 50,
        time_window: Optional[timedelta] = None
    ) -> List[WorkflowEvent]:
        """
        Get timeline of validation decisions (skips, blocks).

        Returns:
            List of validation-related events
        """
        return await self.get_event_centric_timeline(
            event_types=[EventType.TASK_SKIPPED, EventType.TASK_CANCELLED],
            limit=limit,
            time_window=time_window
        )

    async def get_system_metrics(
        self,
        time_window: timedelta = timedelta(hours=1)
    ) -> Dict[str, Any]:
        """
        Get system-wide metrics for all event types.

        Returns:
            Dictionary with metrics per event type
        """
        metrics = defaultdict(lambda: EventMetrics(EventType.TASK_STARTED))
        workflow_ids = await self._get_active_workflows(time_window)

        for workflow_id in workflow_ids:
            try:
                events = await self.event_store.get_timeline(
                    workflow_id=workflow_id,
                    min_level=EventLevel.CRITICAL
                )

                # Filter by time window
                cutoff = datetime.utcnow() - time_window
                events = [
                    e for e in events
                    if datetime.fromisoformat(e.timestamp) > cutoff
                ]

                # Aggregate metrics
                for event in events:
                    event_type = event.event_type
                    if event_type not in metrics:
                        metrics[event_type] = EventMetrics(event_type)

                    m = metrics[event_type]
                    m.count += 1
                    m.workflows_affected.add(workflow_id)

                    if not m.first_seen or event.timestamp < m.first_seen:
                        m.first_seen = event.timestamp
                    if not m.last_seen or event.timestamp > m.last_seen:
                        m.last_seen = event.timestamp

            except Exception as e:
                logger.warning(f"Failed to get metrics for workflow {workflow_id}: {e}")

        # Calculate rates
        window_minutes = time_window.total_seconds() / 60
        for event_type, metric in metrics.items():
            metric.avg_per_minute = metric.count / window_minutes if window_minutes > 0 else 0

        return {
            'time_window': str(time_window),
            'total_workflows': len(workflow_ids),
            'metrics_by_event': {
                k.value if hasattr(k, 'value') else str(k): {
                    'count': v.count,
                    'workflows_affected': len(v.workflows_affected),
                    'first_seen': v.first_seen,
                    'last_seen': v.last_seen,
                    'avg_per_minute': round(v.avg_per_minute, 2)
                }
                for k, v in metrics.items()
            }
        }

    async def monitor_event_rate(
        self,
        event_type: EventType,
        threshold: int = 100,
        window: timedelta = timedelta(minutes=1)
    ) -> bool:
        """
        Monitor if an event type exceeds a rate threshold.

        Args:
            event_type: Event type to monitor
            threshold: Maximum events allowed in window
            window: Time window for rate calculation

        Returns:
            True if rate exceeds threshold
        """
        events = await self.get_event_centric_timeline(
            event_types=[event_type],
            time_window=window
        )

        return len(events) > threshold

    async def get_workflow_health_summary(
        self,
        time_window: timedelta = timedelta(hours=1)
    ) -> Dict[str, Any]:
        """
        Get health summary of all workflows in time window.

        Returns:
            Summary with success rate, failure patterns, etc.
        """
        workflow_ids = await self._get_active_workflows(time_window)

        healthy = 0
        failed = 0
        completed = 0
        in_progress = 0
        with_skips = 0

        for workflow_id in workflow_ids:
            try:
                summary = await self.event_store.get_execution_summary(workflow_id)

                if summary.get('tasks_failed', 0) > 0:
                    failed += 1
                elif summary.get('tasks_completed', 0) == summary.get('total_tasks', 1):
                    if summary.get('tasks_skipped', 0) > 0:
                        with_skips += 1
                    else:
                        healthy += 1
                    completed += 1
                else:
                    in_progress += 1

            except Exception as e:
                logger.warning(f"Failed to get health for workflow {workflow_id}: {e}")

        return {
            'time_window': str(time_window),
            'total_workflows': len(workflow_ids),
            'healthy': healthy,
            'failed': failed,
            'completed': completed,
            'in_progress': in_progress,
            'completed_with_skips': with_skips,
            'success_rate': (healthy / completed * 100) if completed > 0 else 0,
            'failure_rate': (failed / len(workflow_ids) * 100) if workflow_ids else 0
        }

    async def find_correlated_failures(
        self,
        time_window: timedelta = timedelta(minutes=30)
    ) -> Dict[str, List[str]]:
        """
        Find patterns in failures across workflows.

        Returns:
            Dictionary of failure patterns and affected workflows
        """
        failures = await self.get_failure_timeline(limit=1000, time_window=time_window)

        # Group failures by task name/type
        failure_patterns = defaultdict(list)

        for event in failures:
            if event.task_id:
                # Extract task name (remove workflow-specific suffixes)
                task_name = event.task_id.split('_')[0] if '_' in event.task_id else event.task_id
                failure_patterns[task_name].append({
                    'workflow': event.workflow_id,
                    'timestamp': event.timestamp,
                    'error': event.data.get('error', 'Unknown')
                })

        # Find patterns with multiple occurrences
        correlated = {
            task: failures
            for task, failures in failure_patterns.items()
            if len(failures) > 1
        }

        return correlated

    async def get_event_stream(
        self,
        event_types: Optional[List[EventType]] = None,
        follow: bool = False
    ):
        """
        Stream events in real-time as they occur.

        Args:
            event_types: Filter to specific event types
            follow: If True, continuously stream new events

        Yields:
            WorkflowEvent objects as they occur
        """
        # This would use Redis XREAD with block=0 for real-time streaming
        # Implementation depends on your streaming requirements
        pass

    async def _get_active_workflows(
        self,
        time_window: Optional[timedelta] = None
    ) -> List[str]:
        """
        Get list of active workflow IDs.

        This could be optimized with a central index.
        """
        workflow_ids = []

        # For each shard, get workflows
        # This is a simplified version - in production you'd want an index
        num_shards = getattr(default_sharding, 'num_shards', self.config.get('num_shards', 16))
        for shard in range(num_shards):
            pattern = f"{{shard:{shard}}}:workflow:data:*"

            # Get workflow keys from this shard
            cursor = 0
            while True:
                cursor, keys = await self.redis.scan(
                    cursor,
                    match=pattern.encode(),
                    count=100
                )

                for key in keys:
                    # Extract workflow ID from key
                    key_str = key.decode()
                    if ':workflow:data:' in key_str:
                        workflow_id = key_str.split(':workflow:data:')[1]
                        workflow_ids.append(workflow_id)

                if cursor == 0:
                    break

        return workflow_ids

    async def get_hot_paths(
        self,
        time_window: timedelta = timedelta(hours=1),
        min_executions: int = 5
    ) -> Dict[str, int]:
        """
        Identify most frequently executed task paths.

        Returns:
            Dictionary of task sequences and their execution counts
        """
        workflow_ids = await self._get_active_workflows(time_window)
        path_counts = defaultdict(int)

        for workflow_id in workflow_ids:
            try:
                # Get execution order
                order = await self.event_store.get_task_execution_order(workflow_id)
                if len(order) >= 2:
                    # Create path signature
                    path = " -> ".join(order)
                    path_counts[path] += 1

            except Exception as e:
                logger.warning(f"Failed to get path for workflow {workflow_id}: {e}")

        # Filter by minimum executions
        return {
            path: count
            for path, count in path_counts.items()
            if count >= min_executions
        }
