"""
Event Schemas for Gleitzeit V3

Defines the structure and validation for all system events.
Every event has a standard envelope with event-specific payload.
"""

from enum import Enum
from typing import Dict, Any, Optional, List, Union, Set
from datetime import datetime
from pydantic import BaseModel, Field
import uuid


class EventType(str, Enum):
    """All possible event types in the system"""
    
    # Workflow Events
    WORKFLOW_SUBMITTED = "workflow:submitted"
    WORKFLOW_STATE_CHANGED = "workflow:state_changed"
    WORKFLOW_COMPLETED = "workflow:completed"
    WORKFLOW_FAILED = "workflow:failed"
    WORKFLOW_CANCELLED = "workflow:cancelled"
    
    # Task Events
    TASK_CREATED = "task:created"
    TASK_READY = "task:ready"
    TASK_BLOCKED = "task:blocked"
    TASK_ASSIGNED = "task:assigned"
    TASK_STARTED = "task:started"
    TASK_STATE_CHANGED = "task:state_changed"
    TASK_COMPLETED = "task:completed"
    TASK_FAILED = "task:failed"
    TASK_CANCELLED = "task:cancelled"
    TASK_RETRY_REQUESTED = "task:retry_requested"
    
    # Provider Events
    PROVIDER_REGISTERED = "provider:registered"
    PROVIDER_AVAILABLE = "provider:available"
    PROVIDER_BUSY = "provider:busy"
    PROVIDER_OVERLOADED = "provider:overloaded"
    PROVIDER_DISCONNECTED = "provider:disconnected"
    PROVIDER_HEARTBEAT = "provider:heartbeat"
    PROVIDER_HEALTH_CHECK = "provider:health_check"
    
    # Assignment Events
    ASSIGNMENT_REQUESTED = "assignment:requested"
    ASSIGNMENT_CANDIDATE_FOUND = "assignment:candidate_found"
    ASSIGNMENT_VALIDATED = "assignment:validated"
    ASSIGNMENT_APPROVED = "assignment:approved"
    ASSIGNMENT_REJECTED = "assignment:rejected"
    ASSIGNMENT_EXECUTED = "assignment:executed"
    ASSIGNMENT_FAILED = "assignment:failed"
    
    # Parameter Events
    PARAMETERS_RESOLVE_REQUESTED = "parameters:resolve_requested"
    PARAMETERS_RESOLVED = "parameters:resolved"
    PARAMETERS_RESOLUTION_FAILED = "parameters:resolution_failed"
    
    # Dependency Events
    DEPENDENCY_SATISFIED = "dependency:satisfied"
    DEPENDENCY_FAILED = "dependency:failed"
    DEPENDENCY_CHAIN_RESOLVED = "dependency:chain_resolved"
    
    # System Events
    COMPONENT_STARTED = "component:started"
    COMPONENT_STOPPED = "component:stopped"
    COMPONENT_HEALTH = "component:health"
    
    # Audit Events
    AUDIT_WORKFLOW_CREATED = "audit:workflow_created"
    AUDIT_TASK_ASSIGNED = "audit:task_assigned"
    AUDIT_PARAMETER_SUBSTITUTED = "audit:parameter_substituted"
    AUDIT_ERROR_OCCURRED = "audit:error_occurred"


class EventSeverity(str, Enum):
    """Event severity levels"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class EventEnvelope(BaseModel):
    """Standard envelope for all events"""
    
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    sequence_number: Optional[int] = None
    source_component: str
    correlation_id: Optional[str] = None  # For tracing related events
    workflow_id: Optional[str] = None
    task_id: Optional[str] = None
    provider_id: Optional[str] = None
    severity: EventSeverity = EventSeverity.INFO
    payload: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# Workflow Event Payloads

class WorkflowSubmittedPayload(BaseModel):
    workflow_id: str
    workflow_name: str
    task_count: int
    client_id: str
    priority: str = "normal"


class WorkflowStateChangedPayload(BaseModel):
    workflow_id: str
    old_state: str
    new_state: str
    reason: Optional[str] = None


class WorkflowCompletedPayload(BaseModel):
    workflow_id: str
    duration_seconds: float
    completed_tasks: int
    failed_tasks: int
    results: Dict[str, Any]


# Task Event Payloads

class TaskCreatedPayload(BaseModel):
    task_id: str
    task_name: str
    task_type: str
    workflow_id: str
    dependencies: List[str]
    priority: str = "normal"


class TaskReadyPayload(BaseModel):
    task_id: str
    task_type: str
    provider_requirements: Dict[str, Any]
    priority: str = "normal"


class TaskAssignedPayload(BaseModel):
    task_id: str
    provider_id: str
    assignment_timestamp: datetime
    estimated_duration: Optional[int] = None


class TaskCompletedPayload(BaseModel):
    task_id: str
    provider_id: str
    duration_seconds: float
    result: Any
    execution_metadata: Dict[str, Any] = Field(default_factory=dict)


class TaskFailedPayload(BaseModel):
    task_id: str
    provider_id: Optional[str] = None
    error_code: str
    error_message: str
    retry_count: int
    is_recoverable: bool = True


# Provider Event Payloads

class ProviderRegisteredPayload(BaseModel):
    provider_id: str
    provider_name: str
    capabilities: List[str]
    capacity: int
    version: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ProviderAvailablePayload(BaseModel):
    provider_id: str
    available_capacity: int
    supported_task_types: List[str]
    current_load: float


class ProviderHeartbeatPayload(BaseModel):
    provider_id: str
    health_status: str  # healthy, degraded, unhealthy
    current_tasks: int
    capacity_utilization: float
    last_task_completed: Optional[datetime] = None
    performance_metrics: Dict[str, Any] = Field(default_factory=dict)


# Assignment Event Payloads

class AssignmentRequestedPayload(BaseModel):
    task_id: str
    task_type: str
    requirements: Dict[str, Any]
    priority: str = "normal"


class AssignmentCandidateFoundPayload(BaseModel):
    task_id: str
    provider_id: str
    compatibility_score: float
    estimated_wait_time: Optional[int] = None


class AssignmentValidatedPayload(BaseModel):
    task_id: str
    provider_id: str
    validation_result: bool
    validation_details: Dict[str, Any] = Field(default_factory=dict)


# Parameter Event Payloads

class ParametersResolveRequestedPayload(BaseModel):
    task_id: str
    original_parameters: Dict[str, Any]
    dependency_tasks: List[str]


class ParametersResolvedPayload(BaseModel):
    task_id: str
    original_parameters: Dict[str, Any]
    resolved_parameters: Dict[str, Any]
    substitutions_made: Dict[str, str]  # pattern -> value


class ParametersResolutionFailedPayload(BaseModel):
    task_id: str
    missing_dependencies: List[str]
    error_message: str


# Dependency Event Payloads

class DependencySatisfiedPayload(BaseModel):
    task_id: str
    dependency_task_id: str
    dependency_result: Any


# Audit Event Payloads

class AuditWorkflowCreatedPayload(BaseModel):
    workflow_id: str
    workflow_definition: Dict[str, Any]
    created_by: str
    creation_context: Dict[str, Any] = Field(default_factory=dict)


class AuditTaskAssignedPayload(BaseModel):
    task_id: str
    provider_id: str
    assignment_reason: str
    assignment_context: Dict[str, Any] = Field(default_factory=dict)


class AuditParameterSubstitutedPayload(BaseModel):
    task_id: str
    parameter_name: str
    original_value: str
    substituted_value: str
    source_task_id: str


# Event Factory Functions

def create_event(
    event_type: EventType,
    source_component: str,
    payload: Dict[str, Any],
    workflow_id: Optional[str] = None,
    task_id: Optional[str] = None,
    provider_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    severity: EventSeverity = EventSeverity.INFO,
    metadata: Optional[Dict[str, Any]] = None
) -> EventEnvelope:
    """Create a properly formatted event"""
    return EventEnvelope(
        event_type=event_type,
        source_component=source_component,
        payload=payload,
        workflow_id=workflow_id,
        task_id=task_id,
        provider_id=provider_id,
        correlation_id=correlation_id,
        severity=severity,
        metadata=metadata or {}
    )


def create_workflow_submitted_event(
    workflow_id: str,
    workflow_name: str,
    task_count: int,
    client_id: str,
    source_component: str,
    priority: str = "normal"
) -> EventEnvelope:
    """Create workflow submitted event"""
    payload = WorkflowSubmittedPayload(
        workflow_id=workflow_id,
        workflow_name=workflow_name,
        task_count=task_count,
        client_id=client_id,
        priority=priority
    ).dict()
    
    return create_event(
        event_type=EventType.WORKFLOW_SUBMITTED,
        source_component=source_component,
        payload=payload,
        workflow_id=workflow_id
    )


def create_task_ready_event(
    task_id: str,
    task_type: str,
    workflow_id: str,
    provider_requirements: Dict[str, Any],
    source_component: str,
    priority: str = "normal"
) -> EventEnvelope:
    """Create task ready event"""
    payload = TaskReadyPayload(
        task_id=task_id,
        task_type=task_type,
        provider_requirements=provider_requirements,
        priority=priority
    ).dict()
    
    return create_event(
        event_type=EventType.TASK_READY,
        source_component=source_component,
        payload=payload,
        workflow_id=workflow_id,
        task_id=task_id
    )


def create_provider_heartbeat_event(
    provider_id: str,
    health_status: str,
    current_tasks: int,
    capacity_utilization: float,
    source_component: str,
    performance_metrics: Optional[Dict[str, Any]] = None
) -> EventEnvelope:
    """Create provider heartbeat event"""
    payload = ProviderHeartbeatPayload(
        provider_id=provider_id,
        health_status=health_status,
        current_tasks=current_tasks,
        capacity_utilization=capacity_utilization,
        performance_metrics=performance_metrics or {}
    ).dict()
    
    return create_event(
        event_type=EventType.PROVIDER_HEARTBEAT,
        source_component=source_component,
        payload=payload,
        provider_id=provider_id
    )


class EventFilter:
    """Filter for subscribing to specific events"""
    
    def __init__(
        self,
        event_types: Optional[Set[EventType]] = None,
        workflow_ids: Optional[Set[str]] = None,
        task_ids: Optional[Set[str]] = None,
        provider_ids: Optional[Set[str]] = None,
        severities: Optional[Set[EventSeverity]] = None,
        source_components: Optional[Set[str]] = None,
        correlation_ids: Optional[Set[str]] = None
    ):
        self.event_types = event_types or set()
        self.workflow_ids = workflow_ids or set()
        self.task_ids = task_ids or set()
        self.provider_ids = provider_ids or set()
        self.severities = severities or set()
        self.source_components = source_components or set()
        self.correlation_ids = correlation_ids or set()
    
    def matches(self, event: 'EventEnvelope') -> bool:
        """Check if event matches this filter"""
        if self.event_types and event.event_type not in self.event_types:
            return False
        if self.workflow_ids and event.workflow_id not in self.workflow_ids:
            return False
        if self.task_ids and event.task_id not in self.task_ids:
            return False
        if self.provider_ids and event.provider_id not in self.provider_ids:
            return False
        if self.severities and event.severity not in self.severities:
            return False
        if self.source_components and event.source_component not in self.source_components:
            return False
        if self.correlation_ids and event.correlation_id not in self.correlation_ids:
            return False
        return True