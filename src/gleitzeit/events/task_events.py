"""Task-related events for event-driven architecture."""

from typing import Optional
from dataclasses import dataclass
from ..core.models import Task, TaskResult
from ..core.events import GleitzeitEvent, EventType, EventSeverity


@dataclass
class TaskCompletedEvent:
    """Event emitted when a task completes successfully."""
    
    task_id: str
    workflow_id: Optional[str]
    task: Task
    task_result: TaskResult
    source: str = "execution_engine"
    
    def to_gleitzeit_event(self) -> GleitzeitEvent:
        """Convert to GleitzeitEvent for emission."""
        return GleitzeitEvent(
            event_type=EventType.TASK_COMPLETED,
            severity=EventSeverity.INFO,
            data={
                "task_id": self.task_id,
                "workflow_id": self.workflow_id,
                "execution_time": self.task_result.execution_time,
                "success": self.task_result.success
            },
            source=self.source,
            correlation_id=self.workflow_id,
            tags={"component": "task", "task_id": self.task_id}
        )


@dataclass 
class TaskFailedEvent:
    """Event emitted when a task fails."""
    
    task_id: str
    workflow_id: Optional[str]
    task: Task
    error: str
    source: str = "execution_engine"
    
    def to_gleitzeit_event(self) -> GleitzeitEvent:
        """Convert to GleitzeitEvent for emission."""
        return GleitzeitEvent(
            event_type=EventType.TASK_FAILED,
            severity=EventSeverity.ERROR,
            data={
                "task_id": self.task_id,
                "workflow_id": self.workflow_id,
                "error": self.error
            },
            source=self.source,
            correlation_id=self.workflow_id,
            tags={"component": "task", "task_id": self.task_id}
        )