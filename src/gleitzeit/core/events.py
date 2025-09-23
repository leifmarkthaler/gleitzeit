"""
Event definitions for Gleitzeit 0.0.7

Provides event types and structures for the worker-based architecture.
"""

from enum import Enum
from typing import Optional, Dict, Any, Union
from dataclasses import dataclass, asdict
from datetime import datetime

from .models import TaskStatus, WorkflowStatus


class EventType(str, Enum):
    """
    Standardized event types for Gleitzeit 0.0.7

    Event naming convention: {component}:{action}
    """

    # Worker Lifecycle Events
    WORKER_STARTED = "worker:started"
    WORKER_STOPPED = "worker:stopped"
    WORKER_HEARTBEAT = "worker:heartbeat"
    WORKER_FAILED = "worker:failed"
    WORKER_LEADER_ELECTED = "worker:leader_elected"
    WORKER_LEADER_LOST = "worker:leader_lost"

    # Task Execution Events
    TASK_SUBMITTED = "task:submitted"
    TASK_QUEUED = "task:queued"
    TASK_READY = "task:ready"  # Task ready for execution
    TASK_STARTED = "task:started"
    TASK_COMPLETED = "task:completed"
    TASK_FAILED = "task:failed"
    TASK_CANCELLED = "task:cancelled"
    TASK_RETRY_SCHEDULED = "task:retry_scheduled"
    TASK_SLEEPING = "task:sleeping"  # Task is sleeping (timer)
    TASK_WAITING = "task:waiting"  # Task is waiting (signal)
    TASK_SKIPPED = "task:skipped"  # Task skipped due to validation failure
    TASK_BLOCKED = "task:blocked"  # Task blocked due to dependency failure

    # Workflow Events
    WORKFLOW_SUBMITTED = "workflow:submitted"
    WORKFLOW_VALIDATED = "workflow:validated"
    WORKFLOW_STARTED = "workflow:started"
    WORKFLOW_COMPLETED = "workflow:completed"
    WORKFLOW_FAILED = "workflow:failed"
    WORKFLOW_CANCELLED = "workflow:cancelled"
    WORKFLOW_PAUSED = "workflow:paused"
    WORKFLOW_RESUMED = "workflow:resumed"
    WORKFLOW_WAITING_FOR_SIGNAL = "workflow:waiting_for_signal"
    WORKFLOW_TIMER_SCHEDULED = "workflow:timer_scheduled"

    # Timer Events
    TIMER_CREATED = "timer:created"
    TIMER_EXPIRED = "timer:expired"
    TIMER_CANCELLED = "timer:cancelled"
    TIMER_FIRED = "timer:fired"

    # Signal Events
    SIGNAL_SENT = "signal:sent"
    SIGNAL_RECEIVED = "signal:received"
    SIGNAL_TIMEOUT = "signal:timeout"
    SIGNAL_WAITING = "signal:waiting"

    # Provider Events
    PROVIDER_REGISTERED = "provider:registered"
    PROVIDER_UNREGISTERED = "provider:unregistered"
    PROVIDER_ERROR = "provider:error"
    PROVIDER_INITIALIZED = "provider:initialized"

    # Shard Events
    SHARD_ASSIGNED = "shard:assigned"
    SHARD_RELEASED = "shard:released"
    SHARD_REBALANCED = "shard:rebalanced"

    # System Events
    SYSTEM_STARTED = "system:started"
    SYSTEM_SHUTDOWN = "system:shutdown"
    SYSTEM_ERROR = "system:error"

    # Consumer Group Events
    CONSUMER_GROUP_CREATED = "consumer:group:created"
    CONSUMER_GROUP_JOINED = "consumer:group:joined"
    CONSUMER_GROUP_LEFT = "consumer:group:left"


class EventSeverity(str, Enum):
    """Event severity levels"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class BaseEvent:
    """Base class for all events"""
    event_type: EventType
    timestamp: datetime
    severity: EventSeverity = EventSeverity.INFO
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        result = asdict(self)
        # Convert datetime to ISO format
        result['timestamp'] = self.timestamp.isoformat()
        # Convert enums to strings
        result['event_type'] = self.event_type.value
        result['severity'] = self.severity.value
        return result


@dataclass
class WorkerEvent:
    """Worker lifecycle event"""
    event_type: EventType
    timestamp: datetime
    worker_id: str
    worker_type: str
    severity: EventSeverity = EventSeverity.INFO
    metadata: Optional[Dict[str, Any]] = None
    assigned_shards: Optional[list] = None
    consumer_group: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        result = asdict(self)
        result['timestamp'] = self.timestamp.isoformat()
        result['event_type'] = self.event_type.value
        result['severity'] = self.severity.value
        return result


@dataclass
class TaskEvent:
    """Task execution event"""
    event_type: EventType
    timestamp: datetime
    task_id: str
    workflow_id: Optional[str] = None
    status: Optional[TaskStatus] = None
    protocol: Optional[str] = None
    method: Optional[str] = None
    severity: EventSeverity = EventSeverity.INFO
    metadata: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    result: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['timestamp'] = self.timestamp.isoformat()
        result['event_type'] = self.event_type.value
        result['severity'] = self.severity.value
        if self.status:
            result['status'] = self.status.value
        return result


@dataclass
class WorkflowEvent:
    """Workflow orchestration event"""
    event_type: EventType
    timestamp: datetime
    workflow_id: str
    status: Optional[WorkflowStatus] = None
    total_tasks: Optional[int] = None
    completed_tasks: Optional[int] = None
    failed_tasks: Optional[int] = None
    severity: EventSeverity = EventSeverity.INFO
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['timestamp'] = self.timestamp.isoformat()
        result['event_type'] = self.event_type.value
        result['severity'] = self.severity.value
        if self.status:
            result['status'] = self.status.value
        return result


@dataclass
class TimerEvent:
    """Timer-related event"""
    event_type: EventType
    timestamp: datetime
    timer_id: str
    task_id: str
    workflow_id: str
    duration_seconds: Optional[float] = None
    scheduled_time: Optional[datetime] = None
    fired_at: Optional[datetime] = None
    severity: EventSeverity = EventSeverity.INFO
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['timestamp'] = self.timestamp.isoformat()
        result['event_type'] = self.event_type.value
        result['severity'] = self.severity.value
        if self.scheduled_time:
            result['scheduled_time'] = self.scheduled_time.isoformat()
        if self.fired_at:
            result['fired_at'] = self.fired_at.isoformat()
        return result


@dataclass
class SignalEvent:
    """Signal-related event"""
    event_type: EventType
    timestamp: datetime
    signal_name: str
    workflow_id: Optional[str] = None
    task_id: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    timeout_seconds: Optional[float] = None
    severity: EventSeverity = EventSeverity.INFO
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['timestamp'] = self.timestamp.isoformat()
        result['event_type'] = self.event_type.value
        result['severity'] = self.severity.value
        return result


@dataclass
class ProviderEvent:
    """Provider-related event"""
    event_type: EventType
    timestamp: datetime
    provider_id: str
    protocol_id: str
    action: str  # registered, unregistered, error, etc.
    error_message: Optional[str] = None
    severity: EventSeverity = EventSeverity.INFO
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['timestamp'] = self.timestamp.isoformat()
        result['event_type'] = self.event_type.value
        result['severity'] = self.severity.value
        return result


@dataclass
class ShardEvent:
    """Shard management event"""
    event_type: EventType
    timestamp: datetime
    shard_id: int
    worker_id: str
    action: str  # assigned, released, rebalanced
    total_shards: Optional[int] = None
    severity: EventSeverity = EventSeverity.INFO
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['timestamp'] = self.timestamp.isoformat()
        result['event_type'] = self.event_type.value
        result['severity'] = self.severity.value
        return result


class EventEmitter:
    """Base class for components that emit events"""

    def __init__(self):
        self._event_handlers = {}

    def on(self, event_type: EventType, handler):
        """Register an event handler"""
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []
        self._event_handlers[event_type].append(handler)

    async def emit(self, event: BaseEvent):
        """Emit an event to registered handlers"""
        handlers = self._event_handlers.get(event.event_type, [])
        for handler in handlers:
            try:
                await handler(event)
            except Exception as e:
                # Log error but don't stop other handlers
                import logging
                logging.error(f"Error in event handler: {e}")