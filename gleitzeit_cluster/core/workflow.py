"""
Workflow definitions and orchestration for Gleitzeit Cluster
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field
import uuid

from .task import Task, TaskStatus


class WorkflowStatus(Enum):
    """Workflow execution status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class WorkflowErrorStrategy(Enum):
    """Error handling strategies for workflows"""
    STOP_ON_FIRST_ERROR = "stop"
    CONTINUE_ON_ERROR = "continue"
    RETRY_FAILED_TASKS = "retry"
    SKIP_FAILED_TASKS = "skip"


class WorkflowResult(BaseModel):
    """Workflow execution result"""
    workflow_id: str
    status: WorkflowStatus
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    execution_time_seconds: Optional[float] = None
    results: Dict[str, Any] = Field(default_factory=dict)
    errors: Dict[str, str] = Field(default_factory=dict)


class Workflow(BaseModel):
    """Workflow definition and execution state"""
    
    # Identity
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: Optional[str] = None
    version: str = "1.0"
    
    # Configuration
    error_strategy: WorkflowErrorStrategy = WorkflowErrorStrategy.CONTINUE_ON_ERROR
    max_parallel_tasks: int = 10
    timeout_seconds: int = 3600  # 1 hour default
    
    # Tasks
    tasks: Dict[str, Task] = Field(default_factory=dict)
    task_order: List[str] = Field(default_factory=list)
    
    # Execution state
    status: WorkflowStatus = WorkflowStatus.PENDING
    current_tasks: Set[str] = Field(default_factory=set)  # Currently executing
    completed_tasks: Set[str] = Field(default_factory=set)
    failed_tasks: Set[str] = Field(default_factory=set)
    
    # Results
    results: Dict[str, Any] = Field(default_factory=dict)
    errors: Dict[str, str] = Field(default_factory=dict)
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Metadata
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    def add_task(self, task: Task) -> None:
        """Add a task to the workflow"""
        task.workflow_id = self.id
        self.tasks[task.id] = task
        if task.id not in self.task_order:
            self.task_order.append(task.id)
    
    def add_text_task(
        self, 
        name: str, 
        prompt: str, 
        model: str = "llama3",
        dependencies: Optional[List[str]] = None,
        **kwargs
    ) -> Task:
        """Convenience method to add a text task"""
        from .task import TaskType, TaskParameters
        
        task = Task(
            name=name,
            task_type=TaskType.TEXT,
            parameters=TaskParameters(
                prompt=prompt,
                model_name=model,
                **kwargs
            ),
            dependencies=dependencies or []
        )
        self.add_task(task)
        return task
    
    def add_vision_task(
        self,
        name: str,
        prompt: str,
        image_path: str,
        model: str = "llava",
        dependencies: Optional[List[str]] = None,
        **kwargs
    ) -> Task:
        """Convenience method to add a vision task"""
        from .task import TaskType, TaskParameters
        
        task = Task(
            name=name,
            task_type=TaskType.VISION,
            parameters=TaskParameters(
                prompt=prompt,
                image_path=image_path,
                model_name=model,
                **kwargs
            ),
            dependencies=dependencies or []
        )
        self.add_task(task)
        return task
    
    def add_python_task(
        self,
        name: str,
        function_name: str,
        args: Optional[List[Any]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        dependencies: Optional[List[str]] = None,
        **task_kwargs
    ) -> Task:
        """Convenience method to add a Python task"""
        from .task import TaskType, TaskParameters
        
        task = Task(
            name=name,
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name=function_name,
                args=args or [],
                kwargs=kwargs or {},
                **task_kwargs
            ),
            dependencies=dependencies or []
        )
        self.add_task(task)
        return task
    
    def get_ready_tasks(self) -> List[Task]:
        """Get tasks that are ready to execute"""
        ready_tasks = []
        
        for task_id in self.task_order:
            task = self.tasks[task_id]
            
            # Skip if already processed
            if task_id in self.completed_tasks or task_id in self.failed_tasks:
                continue
                
            # Skip if currently running
            if task_id in self.current_tasks:
                continue
                
            # Check if dependencies are satisfied
            if task.is_ready_to_execute(self.completed_tasks):
                ready_tasks.append(task)
        
        return ready_tasks
    
    def can_start_more_tasks(self) -> bool:
        """Check if we can start more parallel tasks"""
        return len(self.current_tasks) < self.max_parallel_tasks
    
    def mark_task_started(self, task_id: str) -> None:
        """Mark task as started"""
        if task_id in self.tasks:
            self.current_tasks.add(task_id)
            self.tasks[task_id].update_status(TaskStatus.PROCESSING)
    
    def mark_task_completed(self, task_id: str, result: Any) -> None:
        """Mark task as completed"""
        if task_id in self.tasks:
            self.current_tasks.discard(task_id)
            self.completed_tasks.add(task_id)
            self.tasks[task_id].update_status(TaskStatus.COMPLETED)
            self.tasks[task_id].result = result
            self.results[task_id] = result
    
    def mark_task_failed(self, task_id: str, error: str) -> None:
        """Mark task as failed"""
        if task_id in self.tasks:
            self.current_tasks.discard(task_id)
            task = self.tasks[task_id]
            
            # Try retry if possible
            if task.can_retry():
                task.retry_count += 1
                task.update_status(TaskStatus.RETRYING, error)
                # Task becomes ready for retry
            else:
                self.failed_tasks.add(task_id)
                task.update_status(TaskStatus.FAILED, error)
                self.errors[task_id] = error
                
                # Handle error strategy
                if self.error_strategy == WorkflowErrorStrategy.STOP_ON_FIRST_ERROR:
                    self.status = WorkflowStatus.FAILED
    
    def is_complete(self) -> bool:
        """Check if workflow is complete"""
        total_tasks = len(self.tasks)
        processed_tasks = len(self.completed_tasks) + len(self.failed_tasks)
        return processed_tasks >= total_tasks
    
    def is_failed(self) -> bool:
        """Check if workflow has failed"""
        return (
            self.status == WorkflowStatus.FAILED or
            (self.error_strategy == WorkflowErrorStrategy.STOP_ON_FIRST_ERROR and 
             len(self.failed_tasks) > 0)
        )
    
    def get_progress(self) -> Dict[str, Any]:
        """Get workflow progress information"""
        total_tasks = len(self.tasks)
        completed = len(self.completed_tasks)
        failed = len(self.failed_tasks)
        running = len(self.current_tasks)
        pending = total_tasks - completed - failed - running
        
        return {
            "workflow_id": self.id,
            "status": self.status.value,
            "total_tasks": total_tasks,
            "completed_tasks": completed,
            "failed_tasks": failed,
            "running_tasks": running,
            "pending_tasks": pending,
            "progress_percent": (completed / total_tasks * 100) if total_tasks > 0 else 0,
            "execution_time": (
                (datetime.utcnow() - self.started_at).total_seconds()
                if self.started_at else 0
            )
        }
    
    def to_result(self) -> WorkflowResult:
        """Convert to workflow result"""
        execution_time = None
        if self.started_at and self.completed_at:
            execution_time = (self.completed_at - self.started_at).total_seconds()
        elif self.started_at:
            execution_time = (datetime.utcnow() - self.started_at).total_seconds()
            
        return WorkflowResult(
            workflow_id=self.id,
            status=self.status,
            total_tasks=len(self.tasks),
            completed_tasks=len(self.completed_tasks),
            failed_tasks=len(self.failed_tasks),
            execution_time_seconds=execution_time,
            results=self.results,
            errors=self.errors
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        data = self.model_dump(mode="json")
        # Convert sets to lists for JSON serialization
        data["current_tasks"] = list(self.current_tasks)
        data["completed_tasks"] = list(self.completed_tasks)
        data["failed_tasks"] = list(self.failed_tasks)
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Workflow":
        """Create workflow from dictionary"""
        # Convert lists back to sets
        if "current_tasks" in data:
            data["current_tasks"] = set(data["current_tasks"])
        if "completed_tasks" in data:
            data["completed_tasks"] = set(data["completed_tasks"])
        if "failed_tasks" in data:
            data["failed_tasks"] = set(data["failed_tasks"])
            
        # Convert task dictionaries back to Task objects
        if "tasks" in data:
            tasks = {}
            for task_id, task_data in data["tasks"].items():
                tasks[task_id] = Task.from_dict(task_data)
            data["tasks"] = tasks
            
        return cls.model_validate(data)
    
    def __str__(self) -> str:
        return f"Workflow(id={self.id[:8]}, name={self.name}, status={self.status.value})"