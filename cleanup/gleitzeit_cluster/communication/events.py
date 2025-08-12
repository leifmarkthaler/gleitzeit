"""
Event definitions for cluster communication
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class EventType(Enum):
    """Types of cluster events"""
    
    # Task events
    TASK_CREATED = "task_created"
    TASK_QUEUED = "task_queued"
    TASK_ASSIGNED = "task_assigned"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_CANCELLED = "task_cancelled"
    
    # Workflow events
    WORKFLOW_SUBMITTED = "workflow_submitted"
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_PROGRESS = "workflow_progress"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_CANCELLED = "workflow_cancelled"
    
    # Node events
    NODE_REGISTERED = "node_registered"
    NODE_HEARTBEAT = "node_heartbeat"
    NODE_RESOURCE_UPDATE = "node_resource_update"
    NODE_HEALTH_UPDATE = "node_health_update"
    NODE_OFFLINE = "node_offline"
    NODE_OVERLOADED = "node_overloaded"
    
    # Cluster events
    CLUSTER_SCALING = "cluster_scaling"
    CLUSTER_ALERT = "cluster_alert"
    CLUSTER_CONFIG_UPDATE = "cluster_config_update"
    
    # Scheduler events
    SCHEDULING_DECISION = "scheduling_decision"
    LOAD_BALANCING = "load_balancing"
    RESOURCE_ALLOCATION = "resource_allocation"


class EventNamespace(Enum):
    """Socket.IO namespaces for event organization"""
    CLUSTER = "/cluster"
    SCHEDULING = "/scheduling" 
    MONITORING = "/monitoring"
    WORKFLOWS = "/workflows"
    ADMIN = "/admin"


class ClusterEvent(BaseModel):
    """Base cluster event"""
    
    event_type: EventType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source: str  # Component that generated the event
    namespace: EventNamespace = EventNamespace.CLUSTER
    
    # Event data
    data: Dict[str, Any] = Field(default_factory=dict)
    
    # Optional fields
    correlation_id: Optional[str] = None  # For tracing related events
    workflow_id: Optional[str] = None
    task_id: Optional[str] = None
    node_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for transmission"""
        return self.model_dump(mode="json")
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ClusterEvent":
        """Create event from dictionary"""
        return cls.model_validate(data)


# Event factory functions for common events

def create_task_event(
    event_type: EventType,
    task_id: str,
    workflow_id: Optional[str] = None,
    source: str = "unknown",
    data: Optional[Dict[str, Any]] = None
) -> ClusterEvent:
    """Create a task-related event"""
    return ClusterEvent(
        event_type=event_type,
        source=source,
        namespace=EventNamespace.MONITORING,
        task_id=task_id,
        workflow_id=workflow_id,
        data=data or {}
    )


def create_workflow_event(
    event_type: EventType,
    workflow_id: str,
    source: str = "scheduler",
    data: Optional[Dict[str, Any]] = None
) -> ClusterEvent:
    """Create a workflow-related event"""
    return ClusterEvent(
        event_type=event_type,
        source=source,
        namespace=EventNamespace.WORKFLOWS,
        workflow_id=workflow_id,
        data=data or {}
    )


def create_node_event(
    event_type: EventType,
    node_id: str,
    source: str = "machine_manager",
    data: Optional[Dict[str, Any]] = None
) -> ClusterEvent:
    """Create a node-related event"""
    return ClusterEvent(
        event_type=event_type,
        source=source,
        namespace=EventNamespace.CLUSTER,
        node_id=node_id,
        data=data or {}
    )


def create_scheduling_event(
    event_type: EventType,
    source: str = "scheduler",
    task_id: Optional[str] = None,
    node_id: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None
) -> ClusterEvent:
    """Create a scheduling-related event"""
    return ClusterEvent(
        event_type=event_type,
        source=source,
        namespace=EventNamespace.SCHEDULING,
        task_id=task_id,
        node_id=node_id,
        data=data or {}
    )