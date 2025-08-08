"""
Core task definitions for Gleitzeit Cluster
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field
import uuid


class TaskType(Enum):
    """Streamlined task types for Gleitzeit"""
    TEXT = "text"            # LLM text generation
    VISION = "vision"        # Vision/image analysis
    FUNCTION = "function"    # Secure function execution
    HTTP = "http"           # HTTP requests
    FILE = "file"           # File operations
    
    # Legacy aliases for backward compatibility
    @classmethod
    def _missing_(cls, value):
        """Handle legacy task type names"""
        legacy_map = {
            "text_prompt": cls.TEXT,
            "ollama_text": cls.TEXT,
            "vision_task": cls.VISION,
            "ollama_vision": cls.VISION,
            "python_function": cls.FUNCTION,
            "python_code": cls.FUNCTION,
            "http_request": cls.HTTP,
            "file_operation": cls.FILE
        }
        return legacy_map.get(value)


class TaskStatus(Enum):
    """Task execution status"""
    PENDING = "pending"
    QUEUED = "queued"
    ASSIGNED = "assigned" 
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


class TaskPriority(Enum):
    """Task priority levels"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TaskParameters(BaseModel):
    """Parameters for different task types"""
    
    # Common parameters
    prompt: Optional[str] = None
    model_name: Optional[str] = "llama3"
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None
    timeout_seconds: Optional[int] = 300
    
    # Vision task parameters
    image_path: Optional[str] = None
    
    # Python function parameters
    function_name: Optional[str] = None
    module_path: Optional[str] = None
    args: Optional[List[Any]] = Field(default_factory=list)
    kwargs: Optional[Dict[str, Any]] = Field(default_factory=dict)
    
    # HTTP request parameters
    url: Optional[str] = None
    method: Optional[str] = "GET"
    headers: Optional[Dict[str, str]] = Field(default_factory=dict)
    data: Optional[Any] = None
    
    # File operation parameters
    operation: Optional[str] = None  # read, write, delete, etc.
    source_path: Optional[str] = None
    target_path: Optional[str] = None
    content: Optional[str] = None


class TaskRequirements(BaseModel):
    """Resource requirements for task execution"""
    cpu_cores: Optional[float] = None
    memory_mb: Optional[int] = None
    gpu_memory_mb: Optional[int] = None
    requires_gpu: bool = False
    required_models: List[str] = Field(default_factory=list)
    node_tags: List[str] = Field(default_factory=list)


class TaskResult(BaseModel):
    """Task execution result"""
    task_id: str
    status: TaskStatus
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_time_seconds: Optional[float] = None
    executor_node_id: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class Task(BaseModel):
    """Core task representation"""
    
    # Identity
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    workflow_id: Optional[str] = None
    
    # Task definition
    task_type: TaskType
    parameters: TaskParameters = Field(default_factory=TaskParameters)
    requirements: TaskRequirements = Field(default_factory=TaskRequirements)
    
    # Execution control
    priority: TaskPriority = TaskPriority.NORMAL
    max_retries: int = 3
    retry_count: int = 0
    timeout_seconds: int = 300
    
    # Dependencies
    dependencies: List[str] = Field(default_factory=list)
    depends_on_success: bool = True  # If False, runs even if deps failed
    
    # Status and tracking
    status: TaskStatus = TaskStatus.PENDING
    assigned_node_id: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    queued_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Metadata
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        """Post-initialization validation"""
        # Auto-detect requirements based on task type
        if self.task_type == TaskType.VISION_TASK:
            self.requirements.requires_gpu = True
            if self.parameters.model_name:
                self.requirements.required_models.append(self.parameters.model_name)
        
        elif self.task_type == TaskType.TEXT_PROMPT:
            if self.parameters.model_name:
                self.requirements.required_models.append(self.parameters.model_name)
    
    def update_status(self, status: TaskStatus, error: Optional[str] = None) -> None:
        """Update task status with timestamp"""
        self.status = status
        self.updated_at = datetime.utcnow()
        
        if error:
            self.error = error
            
        if status == TaskStatus.QUEUED:
            self.queued_at = datetime.utcnow()
        elif status == TaskStatus.PROCESSING:
            self.started_at = datetime.utcnow()
        elif status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
            self.completed_at = datetime.utcnow()
    
    def is_ready_to_execute(self, completed_tasks: set[str]) -> bool:
        """Check if all dependencies are satisfied"""
        if not self.dependencies:
            return True
            
        return all(dep_id in completed_tasks for dep_id in self.dependencies)
    
    def can_retry(self) -> bool:
        """Check if task can be retried"""
        return (
            self.status in [TaskStatus.FAILED, TaskStatus.RETRYING] and
            self.retry_count < self.max_retries
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for Redis storage"""
        return self.model_dump(mode="json")
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        """Create task from dictionary"""
        return cls.model_validate(data)
    
    def __str__(self) -> str:
        return f"Task(id={self.id[:8]}, name={self.name}, status={self.status.value})"