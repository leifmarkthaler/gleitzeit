"""
Centralized Event Definitions for Gleitzeit V4

Provides a consistent event hierarchy and event types for the entire system,
including Socket.IO event coordination and structured event payloads.
"""

from enum import Enum, auto
from typing import Optional, Dict, Any, Union, List
from dataclasses import dataclass, asdict
from datetime import datetime
from pydantic import BaseModel, Field

from gleitzeit.core.models import TaskStatus, WorkflowStatus


class EventType(str, Enum):
    """
    Standardized event types for Gleitzeit V4
    
    Event naming convention: {component}:{action}
    - engine: Execution engine lifecycle
    - task: Individual task events  
    - workflow: Workflow orchestration events
    - provider: Provider management events
    - queue: Queue and scheduling events
    - health: Health monitoring events
    """
    
    # Engine Lifecycle Events
    ENGINE_STARTED = "engine:started"
    ENGINE_STOPPED = "engine:stopped"
    ENGINE_PAUSED = "engine:paused"
    ENGINE_RESUMED = "engine:resumed"
    
    # Task Execution Events
    TASK_SUBMITTED = "task:submitted"
    TASK_QUEUED = "task:queued" 
    TASK_STARTED = "task:started"
    TASK_COMPLETED = "task:completed"
    TASK_FAILED = "task:failed"
    TASK_CANCELLED = "task:cancelled"
    TASK_RETRY_SCHEDULED = "task:retry_scheduled"
    TASK_RETRY_EXECUTED = "task:retry_executed"
    TASK_TIMEOUT = "task:timeout"
    TASK_READY = "task:ready"  # Task ready for execution (dependencies satisfied)
    TASK_READY_FOR_RETRY = "task:ready_for_retry"  # Task ready to be retried
    RETRY_SCHEDULED = "retry:scheduled"  # Retry has been scheduled
    
    # Workflow Events
    WORKFLOW_SUBMITTED = "workflow:submitted"
    WORKFLOW_VALIDATED = "workflow:validated"
    WORKFLOW_STARTED = "workflow:started"
    WORKFLOW_COMPLETED = "workflow:completed"
    WORKFLOW_FAILED = "workflow:failed"
    WORKFLOW_CANCELLED = "workflow:cancelled"
    WORKFLOW_PAUSED = "workflow:paused"
    WORKFLOW_RESUMED = "workflow:resumed"
    WORKFLOW_PROGRESS = "workflow:progress"
    WORKFLOW_STUCK = "workflow:stuck"
    WORKFLOW_WAITING_FOR_SIGNAL = "workflow:waiting_for_signal"
    
    # Reconciliation Events
    RECONCILIATION_LEADER_ELECTED = "reconciliation:leader_elected"
    RECONCILIATION_LEADER_STEPPED_DOWN = "reconciliation:leader_stepped_down"
    RECONCILIATION_STARTED = "reconciliation:started"
    RECONCILIATION_COMPLETED = "reconciliation:completed"
    RECONCILIATION_FAILED = "reconciliation:failed"
    
    # Provider Events
    PROVIDER_REGISTERED = "provider:registered"
    PROVIDER_UNREGISTERED = "provider:unregistered"
    PROVIDER_STARTED = "provider:started"
    PROVIDER_STOPPED = "provider:stopped"
    PROVIDER_HEALTH_CHECK = "provider:health_check"
    PROVIDER_ERROR = "provider:error"
    PROVIDER_OVERLOADED = "provider:overloaded"
    PROVIDER_CLEANUP_REQUESTED = "provider:cleanup_requested"
    PROVIDER_SESSION_CLEANUP = "provider:session_cleanup"
    
    # Session Events
    SESSION_CREATED = "session:created"
    SESSION_REVOKED = "session:revoked"
    SESSION_EXPIRED = "session:expired"
    SESSION_REFRESHED = "session:refreshed"
    
    # Pool Events
    POOL_SCALED = "pool:scaled"
    POOL_SCALED_UP = "pool:scaled_up"
    POOL_SCALED_DOWN = "pool:scaled_down"
    POOL_METRICS = "pool:metrics"
    
    # Worker Events
    WORKER_STARTED = "worker:started"
    WORKER_STOPPED = "worker:stopped"
    WORKER_IDLE = "worker:idle"
    WORKER_BUSY = "worker:busy"
    WORKER_FAILED = "worker:failed"
    WORKER_HEARTBEAT = "worker:heartbeat"
    
    # Task Pool Events
    TASK_AVAILABLE = "task:available"
    TASK_CLAIMED = "task:claimed"
    
    # Circuit Breaker Events
    CIRCUIT_OPENED = "circuit:opened"
    CIRCUIT_CLOSED = "circuit:closed"
    CIRCUIT_HALF_OPEN = "circuit:half_open"
    
    # Backpressure Events
    BACKPRESSURE_HIGH = "backpressure:high"
    BACKPRESSURE_NORMAL = "backpressure:normal"
    BACKPRESSURE_CRITICAL = "backpressure:critical"
    
    # Log Events
    LOG_MESSAGE = "log:message"
    LOG_STREAM_START = "log:stream:start"
    LOG_STREAM_END = "log:stream:end"
    LOG_BATCH = "log:batch"
    
    # Pool Management Events
    POOL_SCALE_REQUESTED = "pool:scale_requested"
    
    # Queue Events
    QUEUE_TASK_ENQUEUED = "queue:task_enqueued"
    QUEUE_TASK_DEQUEUED = "queue:task_dequeued"
    QUEUE_FULL = "queue:full"
    QUEUE_EMPTY = "queue:empty"
    QUEUE_PRIORITY_CHANGED = "queue:priority_changed"
    
    # Health & Monitoring Events
    HEALTH_CHECK_STARTED = "health:check_started"
    HEALTH_CHECK_COMPLETED = "health:check_completed" 
    HEALTH_CHECK_FAILED = "health:check_failed"
    METRICS_COLLECTED = "metrics:collected"
    ALERT_TRIGGERED = "alert:triggered"
    
    # System Events
    SYSTEM_SHUTDOWN = "system:shutdown"
    SYSTEM_STARTED = "system:started"
    CLEANUP_STARTED = "cleanup:started"
    CLEANUP_COMPLETED = "cleanup:completed"
    
    # Service Registry Events
    SERVICE_REGISTERED = "service:registered"
    SERVICE_DEREGISTERED = "service:deregistered"
    SERVICE_HEALTH_CHANGED = "service:health_changed"
    COMPONENT_FAILURE = "component:failure"
    
    # Configuration Events
    CONFIG_CHANGED = "config:changed"
    
    # Resource Coordination Events
    RESOURCE_ALLOCATED = "resource:allocated"
    RESOURCE_RELEASED = "resource:released"
    
    # Client Events (for event-driven client)
    CLIENT_CONNECTION_ESTABLISHED = "client:connection:established"
    CLIENT_CONNECTION_LOST = "client:connection:lost"
    CLIENT_CONNECTION_ERROR = "client:connection:error"
    CLIENT_RECONNECTION_ATTEMPT = "client:reconnection:attempt"
    CLIENT_RECONNECTION_SUCCESS = "client:reconnection:success"
    CLIENT_RECONNECTION_FAILED = "client:reconnection:failed"
    CLIENT_SUBSCRIBED = "client:subscribed"
    CLIENT_UNSUBSCRIBED = "client:unsubscribed"
    CLIENT_INITIALIZED = "client:initialized"
    CLIENT_READY = "client:ready"
    CLIENT_SHUTTING_DOWN = "client:shutting_down"
    CLIENT_SHUTDOWN = "client:shutdown"
    CLIENT_ERROR = "client:error"
    
    # Test Events (for testing purposes only)
    TEST_EVENT = "test:event"
    TEST_PRIORITY = "test:priority"


class EventSeverity(str, Enum):
    """Event severity levels for filtering and alerting"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class BaseEventData:
    """Base class for all event data"""
    timestamp: Optional[datetime] = None
    
    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        result = asdict(self)
        # Convert datetime to ISO format
        if self.timestamp:
            result['timestamp'] = self.timestamp.isoformat()
        return result
    
    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


@dataclass
class EngineEventData(BaseEventData):
    """Engine lifecycle event data"""
    mode: Optional[str] = None
    max_concurrent_tasks: Optional[int] = None
    stats: Optional[Dict[str, Any]] = None


@dataclass 
class TaskEventData:
    """Task execution event data"""
    task_id: str
    timestamp: Optional[datetime] = None
    task_name: Optional[str] = None
    workflow_id: Optional[str] = None
    protocol: Optional[str] = None
    method: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[str] = None
    attempt_count: Optional[int] = None
    duration: Optional[float] = None
    error_message: Optional[str] = None
    provider_id: Optional[str] = None
    result_size: Optional[int] = None
    
    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        result = asdict(self)
        if self.timestamp:
            result['timestamp'] = self.timestamp.isoformat()
        return result


@dataclass
class WorkflowEventData:
    """Workflow orchestration event data"""
    workflow_id: str
    timestamp: Optional[datetime] = None
    workflow_name: Optional[str] = None
    total_tasks: Optional[int] = None
    completed_tasks: Optional[int] = None
    failed_tasks: Optional[int] = None
    status: Optional[WorkflowStatus] = None
    execution_levels: Optional[int] = None
    duration: Optional[float] = None
    error_message: Optional[str] = None
    
    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        result = asdict(self)
        if self.timestamp:
            result['timestamp'] = self.timestamp.isoformat()
        if self.status:
            # Convert WorkflowStatus enum to string value
            result['status'] = self.status.value if hasattr(self.status, 'value') else str(self.status)
        return result


@dataclass
class ProviderEventData:
    """Provider management event data"""
    provider_id: str
    timestamp: Optional[datetime] = None
    protocol_id: Optional[str] = None
    provider_name: Optional[str] = None
    health_status: Optional[str] = None
    request_count: Optional[int] = None
    error_count: Optional[int] = None
    success_rate: Optional[float] = None
    response_time: Optional[float] = None
    
    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        result = asdict(self)
        if self.timestamp:
            result['timestamp'] = self.timestamp.isoformat()
        return result


@dataclass
class QueueEventData:
    """Queue management event data"""
    timestamp: Optional[datetime] = None
    queue_name: str = "default"
    task_id: Optional[str] = None
    queue_size: Optional[int] = None
    priority: Optional[str] = None
    wait_time: Optional[float] = None
    
    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        result = asdict(self)
        if self.timestamp:
            result['timestamp'] = self.timestamp.isoformat()
        return result


@dataclass
class HealthEventData:
    """Health monitoring event data"""
    component: str
    status: str  # healthy, degraded, unhealthy
    timestamp: Optional[datetime] = None
    details: Optional[Dict[str, Any]] = None
    response_time: Optional[float] = None
    error_message: Optional[str] = None
    
    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        result = asdict(self)
        if self.timestamp:
            result['timestamp'] = self.timestamp.isoformat()
        return result


class GleitzeitEvent(BaseModel):
    """
    Structured event object for Gleitzeit V4
    
    All events in the system use this consistent structure for
    better observability, debugging, and integration.
    """
    
    event_type: EventType = Field(..., description="Type of event")
    severity: EventSeverity = Field(EventSeverity.INFO, description="Event severity level")
    data: Dict[str, Any] = Field(default_factory=dict, description="Event-specific data")
    source: Optional[str] = Field(None, description="Component that emitted the event")
    correlation_id: Optional[str] = Field(None, description="ID for tracking related events")
    tags: Dict[str, str] = Field(default_factory=dict, description="Additional metadata tags")
    timestamp: Optional[datetime] = Field(default=None, description="When the event occurred")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "event_type": self.event_type.value,
            "severity": self.severity.value,
            "data": self.data,
            "source": self.source,
            "correlation_id": self.correlation_id,
            "tags": self.tags,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None
        }
    
    def to_socket_io(self) -> tuple[str, Dict[str, Any]]:
        """Convert to Socket.IO event format (event_name, data)"""
        return self.event_type.value, self.to_dict()
    
    @classmethod
    def create_task_event(
        cls,
        event_type: EventType,
        task_data: TaskEventData,
        severity: EventSeverity = EventSeverity.INFO,
        source: Optional[str] = None,
        correlation_id: Optional[str] = None
    ) -> "GleitzeitEvent":
        """Create a task-related event"""
        return cls(
            event_type=event_type,
            severity=severity,
            data=task_data.to_dict(),
            source=source,
            correlation_id=correlation_id or task_data.workflow_id,
            tags={"component": "task", "task_id": task_data.task_id}
        )
    
    @classmethod
    def create_workflow_event(
        cls,
        event_type: EventType,
        workflow_data: WorkflowEventData,
        severity: EventSeverity = EventSeverity.INFO,
        source: Optional[str] = None
    ) -> "GleitzeitEvent":
        """Create a workflow-related event"""
        return cls(
            event_type=event_type,
            severity=severity,
            data=workflow_data.to_dict(),
            source=source,
            correlation_id=workflow_data.workflow_id,
            tags={"component": "workflow", "workflow_id": workflow_data.workflow_id}
        )
    
    @classmethod
    def create_provider_event(
        cls,
        event_type: EventType,
        provider_data: ProviderEventData,
        severity: EventSeverity = EventSeverity.INFO,
        source: Optional[str] = None
    ) -> "GleitzeitEvent":
        """Create a provider-related event"""
        return cls(
            event_type=event_type,
            severity=severity,
            data=provider_data.to_dict(),
            source=source,
            tags={"component": "provider", "provider_id": provider_data.provider_id}
        )


# Utility functions for event creation
def create_task_started_event(
    task_id: str,
    task_name: str,
    protocol: str,
    method: str,
    workflow_id: Optional[str] = None,
    source: str = "execution_engine"
) -> GleitzeitEvent:
    """Create a task started event"""
    task_data = TaskEventData(
        task_id=task_id,
        task_name=task_name,
        protocol=protocol,
        method=method,
        workflow_id=workflow_id,
        status=TaskStatus.EXECUTING
    )
    return GleitzeitEvent.create_task_event(
        EventType.TASK_STARTED,
        task_data,
        source=source,
        correlation_id=workflow_id
    )


def create_task_completed_event(
    task_id: str,
    workflow_id: Optional[str] = None,
    duration: Optional[float] = None,
    result_size: Optional[int] = None,
    source: str = "execution_engine"
) -> GleitzeitEvent:
    """Create a task completed event"""
    task_data = TaskEventData(
        task_id=task_id,
        workflow_id=workflow_id,
        status=TaskStatus.COMPLETED,
        duration=duration,
        result_size=result_size
    )
    return GleitzeitEvent.create_task_event(
        EventType.TASK_COMPLETED,
        task_data,
        source=source,
        correlation_id=workflow_id
    )


def create_task_failed_event(
    task_id: str,
    error_message: str,
    workflow_id: Optional[str] = None,
    source: str = "execution_engine",
    error_type: Optional[str] = None,
    is_retryable: Optional[bool] = None,
    is_permanent: Optional[bool] = None,
    attempt_number: Optional[int] = None
) -> GleitzeitEvent:
    """Create a task failed event"""
    task_data = TaskEventData(
        task_id=task_id,
        workflow_id=workflow_id,
        status=TaskStatus.FAILED,
        error_message=error_message
    )
    
    # Add additional metadata if provided
    tags = {}
    if error_type:
        tags["error_type"] = error_type
    if is_retryable is not None:
        tags["is_retryable"] = str(is_retryable)
    
    event = GleitzeitEvent.create_task_event(
        EventType.TASK_FAILED,
        task_data,
        severity=EventSeverity.ERROR,
        source=source,
        correlation_id=workflow_id
    )
    
    # Add custom tags
    if tags:
        event.tags.update(tags)
    
    # Add additional data fields
    if error_type:
        event.data["error_type"] = error_type
    if is_retryable is not None:
        event.data["is_retryable"] = is_retryable
    if is_permanent is not None:
        event.data["is_permanent"] = is_permanent
    if attempt_number is not None:
        event.data["attempt_number"] = attempt_number
    
    return event


def create_workflow_started_event(
    workflow_id: str,
    workflow_name: str,
    total_tasks: int,
    execution_levels: int = 1,
    source: str = "execution_engine"
) -> GleitzeitEvent:
    """Create a workflow started event"""
    workflow_data = WorkflowEventData(
        workflow_id=workflow_id,
        workflow_name=workflow_name,
        total_tasks=total_tasks,
        execution_levels=execution_levels,
        status=WorkflowStatus.RUNNING
    )
    return GleitzeitEvent.create_workflow_event(
        EventType.WORKFLOW_STARTED,
        workflow_data,
        source=source
    )


def create_workflow_completed_event(
    workflow_id: str,
    workflow_name: str = None,
    total_tasks: int = 0,
    completed_tasks: int = 0,
    failed_tasks: int = 0,
    duration: float = 0.0,
    source: str = "execution_engine"
) -> GleitzeitEvent:
    """Create a workflow completed event"""
    return GleitzeitEvent(
        event_type=EventType.WORKFLOW_COMPLETED,
        severity=EventSeverity.INFO,
        data={
            'workflow_id': workflow_id,
            'workflow_name': workflow_name,
            'total_tasks': total_tasks,
            'completed_tasks': completed_tasks,
            'failed_tasks': failed_tasks,
            'duration': duration,
            'status': WorkflowStatus.COMPLETED.value
        },
        source=source
    )


# Event filtering and routing utilities
def get_events_by_severity(events: List[GleitzeitEvent], min_severity: EventSeverity) -> List[GleitzeitEvent]:
    """Filter events by minimum severity level"""
    severity_order = {
        EventSeverity.DEBUG: 0,
        EventSeverity.INFO: 1,
        EventSeverity.WARNING: 2,
        EventSeverity.ERROR: 3,
        EventSeverity.CRITICAL: 4
    }
    min_level = severity_order[min_severity]
    return [e for e in events if severity_order[e.severity] >= min_level]


def get_events_by_component(events: List[GleitzeitEvent], component: str) -> List[GleitzeitEvent]:
    """Filter events by component"""
    return [e for e in events if e.tags.get("component") == component]


def get_events_by_correlation_id(events: List[GleitzeitEvent], correlation_id: str) -> List[GleitzeitEvent]:
    """Get all events related to a workflow or operation"""
    return [e for e in events if e.correlation_id == correlation_id]


def create_custom_event(
    event_type: EventType,
    data: Dict[str, Any],
    source: str,
    severity: EventSeverity = EventSeverity.INFO,
    tags: Optional[Dict[str, str]] = None
) -> GleitzeitEvent:
    """Create a custom event with the specified type and data"""
    return GleitzeitEvent(
        event_type=event_type,
        severity=severity,
        data=data,
        source=source,
        tags=tags or {}
    )


def create_workflow_submitted_event(
    workflow_id: str,
    workflow_name: str,
    total_tasks: int,
    source: str = "unknown"
) -> GleitzeitEvent:
    """Create a workflow submitted event"""
    return GleitzeitEvent(
        event_type=EventType.WORKFLOW_SUBMITTED,
        severity=EventSeverity.INFO,
        data={
            'workflow_id': workflow_id,
            'workflow_name': workflow_name,
            'total_tasks': total_tasks
        },
        source=source
    )


def create_workflow_failed_event(
    workflow_id: str,
    workflow_name: str,
    total_tasks: int,
    completed_tasks: int,
    failed_tasks: int,
    duration: float,
    error_message: str,
    source: str = "unknown"
) -> GleitzeitEvent:
    """Create a workflow failed event"""
    return GleitzeitEvent(
        event_type=EventType.WORKFLOW_FAILED,
        severity=EventSeverity.ERROR,
        data={
            'workflow_id': workflow_id,
            'workflow_name': workflow_name,
            'total_tasks': total_tasks,
            'completed_tasks': completed_tasks,
            'failed_tasks': failed_tasks,
            'duration': duration,
            'error_message': error_message
        },
        source=source
    )