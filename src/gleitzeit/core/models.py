"""
Core data models for Gleitzeit V4

Enhanced models that support protocol-based task execution
with JSON-RPC 2.0 integration.
"""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Union
from uuid import uuid4
from pydantic import BaseModel, Field, field_validator, ConfigDict, field_serializer
import json
import re
from gleitzeit.core.errors import TaskValidationError


class TaskStatus(str, Enum):
    """Task execution status"""
    PENDING = "pending"
    QUEUED = "queued"
    VALIDATED = "validated" 
    ROUTED = "routed"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRY_PENDING = "retry_pending"


class WorkflowStatus(str, Enum):
    """Workflow execution status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Priority(str, Enum):
    """Task priority levels"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class RetryConfig(BaseModel):
    """Configuration for task retry behavior"""
    max_attempts: int = Field(default=3, ge=1, le=10)
    backoff_strategy: str = Field(default="exponential", pattern="^(linear|exponential|fixed)$")
    base_delay: float = Field(default=1.0, ge=0.1, le=60.0)
    max_delay: float = Field(default=300.0, ge=1.0, le=3600.0)
    jitter: bool = Field(default=True, description="Add random jitter to delays")


class Task(BaseModel):
    """
    V4 Task model with protocol-based execution
    
    Key changes from V3:
    - Uses 'protocol' instead of provider type
    - Uses 'method' for JSON-RPC method name
    - Uses 'params' for JSON-RPC parameters
    """
    
    # Identity
    id: str = Field(default_factory=lambda: str(uuid4()))
    workflow_id: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    
    # Protocol specification
    protocol: str = Field(..., pattern=r"^[a-z][a-z0-9_-]*(/[a-z0-9_-]+|/v\d+)?$", 
                         description="Protocol identifier (e.g., 'llm/v1', 'mcp/v1', 'python/v1')")
    method: str = Field(..., description="JSON-RPC method name")
    params: Dict[str, Any] = Field(default_factory=dict,
                                  description="JSON-RPC parameters")
    
    # Execution control
    priority: Priority = Priority.NORMAL
    dependencies: List[str] = Field(default_factory=list,
                                   description="List of task IDs this task depends on")
    timeout: Optional[int] = Field(None, ge=1, le=3600,
                                  description="Execution timeout in seconds")
    retry_config: Optional[RetryConfig] = None
    
    # Resource requirements
    resource_requirements: Optional[Dict[str, Any]] = Field(
        None,
        description="Resource requirements for task execution (e.g., GPU, memory, specific models)"
    )
    
    # Status tracking
    status: TaskStatus = TaskStatus.PENDING
    attempt_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Execution details
    assigned_provider: Optional[str] = None
    execution_node: Optional[str] = None
    error_message: Optional[str] = None
    
    # Metadata
    tags: Dict[str, str] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    model_config = ConfigDict(
        use_enum_values=True
    )
    
    @field_serializer('created_at', 'started_at', 'completed_at')
    def serialize_datetime(self, dt: Optional[datetime]) -> Optional[str]:
        return dt.isoformat() if dt else None
    
    @field_validator('method')
    @classmethod
    def validate_method_name(cls, v: str) -> str:
        """
        Validate method name with support for different protocol conventions:
        - Standard JSON-RPC: alphanumeric with underscores and slashes
        - MCP (Model Context Protocol): supports dotted notation like 'tool.echo'
        - URI-style: supports colons for resource URIs like 'resource.file://path'
        """
        if not v:
            raise TaskValidationError(
                "task",
                ["Method name cannot be empty"]
            )
        
        # Must start with a letter
        if not v[0].isalpha():
            raise TaskValidationError(
                "task",
                ["Method name must start with a letter"]
            )
        
        # Check for valid characters: letters, numbers, dots, underscores, slashes, colons, hyphens
        import re
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_./:/-]*$', v):
            raise TaskValidationError(
                "task",
                [f"Method name '{v}' contains invalid characters. Allowed: letters, numbers, dots, underscores, slashes, colons, hyphens"]
            )
        
        # Additional checks for common patterns
        if '..' in v:
            raise TaskValidationError(
                "task",
                ["Method name cannot contain consecutive dots"]
            )
        
        if v.endswith('.'):
            raise TaskValidationError(
                "task",
                ["Method name cannot end with a dot"]
            )
            
        return v
    
    @field_validator('dependencies')
    @classmethod
    def validate_dependencies(cls, v: List[str]) -> List[str]:
        """Ensure dependencies don't include self-references"""
        return list(set(v))  # Remove duplicates
    
    @field_validator('params')
    @classmethod
    def validate_params(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure params are JSON serializable"""
        try:
            json.dumps(v)
            return v
        except (TypeError, ValueError) as e:
            raise TaskValidationError(
                "task",
                [f"Parameters must be JSON serializable: {e}"]
            )
    
    def mark_started(self, provider_id: str, node_id: Optional[str] = None) -> None:
        """Mark task as started"""
        self.status = TaskStatus.EXECUTING
        self.started_at = datetime.utcnow()
        self.assigned_provider = provider_id
        self.execution_node = node_id
    
    def mark_completed(self) -> None:
        """Mark task as completed"""
        self.status = TaskStatus.COMPLETED
        self.completed_at = datetime.utcnow()
    
    def mark_failed(self, error_message: str) -> None:
        """Mark task as failed"""
        self.status = TaskStatus.FAILED
        self.completed_at = datetime.utcnow()
        self.error_message = error_message
    
    def can_retry(self) -> bool:
        """Check if task can be retried"""
        if not self.retry_config:
            return False
        return self.attempt_count < self.retry_config.max_attempts
    
    def increment_attempt(self) -> None:
        """Increment attempt counter"""
        self.attempt_count += 1
        if self.can_retry():
            self.status = TaskStatus.RETRY_PENDING
        else:
            self.status = TaskStatus.FAILED
    
    def get_execution_duration(self) -> Optional[float]:
        """Get task execution duration in seconds"""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
    
    def to_jsonrpc_request(self, request_id: Optional[str] = None) -> Dict[str, Any]:
        """Convert task to JSON-RPC 2.0 request"""
        return {
            "jsonrpc": "2.0",
            "id": request_id or self.id,
            "method": self.method,
            "params": self.params
        }


class Workflow(BaseModel):
    """
    V4 Workflow model with enhanced dependency management
    """
    
    # Identity
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    
    # Workflow structure
    tasks: List[Task] = Field(default_factory=list)
    
    # Execution control
    priority: Priority = Priority.NORMAL
    max_parallel_tasks: Optional[int] = Field(None, ge=1, le=100,
                                             description="Maximum concurrent tasks")
    timeout: Optional[int] = Field(None, ge=1, le=86400,
                                  description="Workflow timeout in seconds")
    
    # Status tracking
    status: WorkflowStatus = WorkflowStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Results tracking
    task_results: Dict[str, Any] = Field(default_factory=dict,
                                        description="Task ID -> Result mapping")
    completed_tasks: List[str] = Field(default_factory=list,
                                      description="List of completed task IDs")
    failed_tasks: List[str] = Field(default_factory=list,
                                   description="List of failed task IDs")
    
    # Metadata
    tags: Dict[str, str] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    model_config = ConfigDict(
        use_enum_values=True
    )
    
    @field_serializer('created_at', 'started_at', 'completed_at')
    def serialize_datetime(self, dt: Optional[datetime]) -> Optional[str]:
        return dt.isoformat() if dt else None
    
    def add_task(self, task: Task) -> None:
        """Add a task to the workflow"""
        task.workflow_id = self.id
        self.tasks.append(task)
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID"""
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None
    
    def get_ready_tasks(self) -> List[Task]:
        """Get tasks that are ready to execute (dependencies satisfied)"""
        ready = []
        
        for task in self.tasks:
            if task.status in [TaskStatus.PENDING, TaskStatus.QUEUED]:
                # Check if all dependencies are completed
                dependencies_satisfied = all(
                    dep_id in self.completed_tasks 
                    for dep_id in task.dependencies
                )
                
                if dependencies_satisfied:
                    ready.append(task)
        
        return ready
    
    def get_running_tasks(self) -> List[Task]:
        """Get currently executing tasks"""
        return [task for task in self.tasks if task.status == TaskStatus.EXECUTING]
    
    def mark_task_completed(self, task_id: str, result: Any) -> None:
        """Mark a task as completed and store its result"""
        task = self.get_task(task_id)
        if task:
            task.mark_completed()
            self.task_results[task_id] = result
            
            if task_id not in self.completed_tasks:
                self.completed_tasks.append(task_id)
            
            # Remove from failed tasks if it was there
            if task_id in self.failed_tasks:
                self.failed_tasks.remove(task_id)
    
    def mark_task_failed(self, task_id: str, error_message: str) -> None:
        """Mark a task as failed"""
        task = self.get_task(task_id)
        if task:
            task.mark_failed(error_message)
            
            if task_id not in self.failed_tasks:
                self.failed_tasks.append(task_id)
    
    def is_complete(self) -> bool:
        """Check if workflow is complete"""
        total_tasks = len(self.tasks)
        finished_tasks = len(self.completed_tasks) + len(self.failed_tasks)
        return finished_tasks >= total_tasks
    
    def is_successful(self) -> bool:
        """Check if workflow completed successfully"""
        return (self.is_complete() and 
                len(self.failed_tasks) == 0 and
                len(self.completed_tasks) == len(self.tasks))
    
    def get_completion_percentage(self) -> float:
        """Get workflow completion percentage"""
        if not self.tasks:
            return 100.0
        
        finished_tasks = len(self.completed_tasks) + len(self.failed_tasks)
        return (finished_tasks / len(self.tasks)) * 100.0
    
    def get_execution_summary(self) -> Dict[str, Any]:
        """Get execution summary statistics"""
        duration = None
        if self.started_at and self.completed_at:
            duration = (self.completed_at - self.started_at).total_seconds()
        
        return {
            "workflow_id": self.id,
            "name": self.name,
            "status": self.status,
            "total_tasks": len(self.tasks),
            "completed_tasks": len(self.completed_tasks),
            "failed_tasks": len(self.failed_tasks),
            "completion_percentage": self.get_completion_percentage(),
            "duration_seconds": duration,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None
        }
    
    def validate_dependencies(self) -> List[str]:
        """Validate task dependencies and return any errors"""
        errors = []
        task_ids = {task.id for task in self.tasks}
        
        for task in self.tasks:
            for dep_id in task.dependencies:
                if dep_id not in task_ids:
                    errors.append(f"Task {task.id} depends on non-existent task {dep_id}")
                elif dep_id == task.id:
                    errors.append(f"Task {task.id} cannot depend on itself")
        
        # Check for circular dependencies (simplified check)
        # In production, implement proper topological sort
        
        return errors


class TaskResult(BaseModel):
    """Result of task execution"""
    task_id: str = Field(..., description="Task identifier")
    workflow_id: Optional[str] = Field(None, description="Workflow identifier")
    status: TaskStatus = Field(..., description="Execution status")
    result: Optional[Any] = Field(None, description="Task result data")
    error: Optional[str] = Field(None, description="Error message if failed")
    started_at: Optional[datetime] = Field(None, description="When execution started")
    completed_at: Optional[datetime] = Field(None, description="When execution completed")
    duration_seconds: Optional[float] = Field(None, description="Execution duration in seconds")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    model_config = ConfigDict(
        use_enum_values=True
    )
    
    @field_serializer('started_at', 'completed_at')
    def serialize_datetime(self, dt: Optional[datetime]) -> Optional[str]:
        return dt.isoformat() if dt else None
    
    def __post_init__(self) -> None:
        """Calculate duration if both timestamps are available"""
        if self.started_at and self.completed_at and not self.duration_seconds:
            self.duration_seconds = (self.completed_at - self.started_at).total_seconds()


class WorkflowExecution(BaseModel):
    """
    Represents a workflow execution instance
    
    Tracks the execution state of a workflow with progress information.
    """
    
    # Identity
    execution_id: str = Field(..., min_length=1, max_length=100)
    workflow_id: str = Field(..., min_length=1, max_length=100)
    
    # Status tracking
    status: WorkflowStatus = WorkflowStatus.PENDING
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    
    # Progress tracking
    completed_tasks: int = Field(default=0, ge=0)
    failed_tasks: int = Field(default=0, ge=0) 
    total_tasks: int = Field(default=0, ge=0)
    
    model_config = ConfigDict(
        use_enum_values=True
    )
    
    @field_serializer('started_at', 'completed_at')
    def serialize_datetime(self, dt: Optional[datetime]) -> Optional[str]:
        return dt.isoformat() if dt else None