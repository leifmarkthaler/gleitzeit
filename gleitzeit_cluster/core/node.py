"""
Executor node definitions for Gleitzeit Cluster
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field
import uuid

from .task import TaskType


class NodeStatus(Enum):
    """Node status"""
    STARTING = "starting"
    HEALTHY = "healthy"
    BUSY = "busy"
    OVERLOADED = "overloaded"
    UNHEALTHY = "unhealthy"
    OFFLINE = "offline"
    DRAINING = "draining"  # No new tasks, finish current ones


class NodeCapabilities(BaseModel):
    """Node capabilities and constraints"""
    supported_task_types: Set[TaskType] = Field(default_factory=set)
    available_models: List[str] = Field(default_factory=list)
    max_concurrent_tasks: int = 5
    has_gpu: bool = False
    gpu_memory_gb: Optional[float] = None
    cpu_cores: int = 1
    memory_gb: float = 4.0
    tags: Set[str] = Field(default_factory=set)


class NodeResources(BaseModel):
    """Current resource utilization"""
    cpu_usage_percent: float = 0.0
    memory_usage_percent: float = 0.0
    gpu_usage_percent: Optional[float] = None
    gpu_memory_usage_percent: Optional[float] = None
    active_tasks: int = 0
    queue_length: int = 0
    load_average: Optional[float] = None
    disk_usage_percent: Optional[float] = None
    network_io_mbps: Optional[float] = None


class NodeHealth(BaseModel):
    """Node health metrics"""
    is_healthy: bool = True
    last_heartbeat: datetime = Field(default_factory=datetime.utcnow)
    consecutive_failures: int = 0
    error_rate_percent: float = 0.0
    average_task_duration_seconds: Optional[float] = None
    tasks_completed_total: int = 0
    tasks_failed_total: int = 0
    uptime_seconds: float = 0.0


class ExecutorNode(BaseModel):
    """Executor node representation"""
    
    # Identity
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    host: str = "localhost"
    port: int = 8080
    
    # Configuration
    capabilities: NodeCapabilities = Field(default_factory=NodeCapabilities)
    
    # State
    status: NodeStatus = NodeStatus.STARTING
    resources: NodeResources = Field(default_factory=NodeResources)
    health: NodeHealth = Field(default_factory=NodeHealth)
    
    # Task tracking
    assigned_tasks: Set[str] = Field(default_factory=set)
    completed_tasks_count: int = 0
    failed_tasks_count: int = 0
    
    # Timestamps
    registered_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Metadata
    version: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    def can_execute_task(self, task_type: TaskType, required_models: List[str] = None) -> bool:
        """Check if node can execute a specific task type"""
        # Check task type support
        if task_type not in self.capabilities.supported_task_types:
            return False
            
        # Check model availability
        if required_models:
            available_models_set = set(self.capabilities.available_models)
            required_models_set = set(required_models)
            if not required_models_set.issubset(available_models_set):
                return False
        
        # Check capacity
        if self.resources.active_tasks >= self.capabilities.max_concurrent_tasks:
            return False
            
        # Check health
        if not self.health.is_healthy:
            return False
            
        return True
    
    def get_load_score(self) -> float:
        """Calculate load score for scheduling decisions (0.0 = idle, 1.0 = full)"""
        # Task load
        task_load = self.resources.active_tasks / self.capabilities.max_concurrent_tasks
        
        # CPU load
        cpu_load = self.resources.cpu_usage_percent / 100.0
        
        # Memory load  
        memory_load = self.resources.memory_usage_percent / 100.0
        
        # GPU load (if applicable)
        gpu_load = 0.0
        if self.capabilities.has_gpu and self.resources.gpu_usage_percent is not None:
            gpu_load = self.resources.gpu_usage_percent / 100.0
        
        # Weighted average (tasks are most important)
        weights = [0.4, 0.3, 0.2, 0.1]  # task, cpu, memory, gpu
        loads = [task_load, cpu_load, memory_load, gpu_load]
        
        return sum(w * l for w, l in zip(weights, loads))
    
    def update_resources(self, resources: NodeResources) -> None:
        """Update resource metrics"""
        self.resources = resources
        self.last_seen_at = datetime.utcnow()
        
        # Update status based on load
        load_score = self.get_load_score()
        if load_score < 0.5:
            self.status = NodeStatus.HEALTHY
        elif load_score < 0.8:
            self.status = NodeStatus.BUSY
        else:
            self.status = NodeStatus.OVERLOADED
    
    def update_health(self, health: NodeHealth) -> None:
        """Update health metrics"""
        self.health = health
        self.last_seen_at = datetime.utcnow()
        
        # Update overall status
        if not health.is_healthy:
            self.status = NodeStatus.UNHEALTHY
    
    def assign_task(self, task_id: str) -> None:
        """Assign a task to this node"""
        self.assigned_tasks.add(task_id)
        self.resources.active_tasks = len(self.assigned_tasks)
    
    def complete_task(self, task_id: str, success: bool = True) -> None:
        """Mark task as completed"""
        self.assigned_tasks.discard(task_id)
        self.resources.active_tasks = len(self.assigned_tasks)
        
        if success:
            self.completed_tasks_count += 1
        else:
            self.failed_tasks_count += 1
            
        # Update health metrics
        total_tasks = self.completed_tasks_count + self.failed_tasks_count
        if total_tasks > 0:
            self.health.error_rate_percent = (self.failed_tasks_count / total_tasks) * 100
    
    def is_available(self) -> bool:
        """Check if node is available for new tasks"""
        return (
            self.status in [NodeStatus.HEALTHY, NodeStatus.BUSY] and
            self.health.is_healthy and
            self.resources.active_tasks < self.capabilities.max_concurrent_tasks
        )
    
    def is_overloaded(self) -> bool:
        """Check if node is overloaded"""
        return (
            self.status == NodeStatus.OVERLOADED or
            self.get_load_score() > 0.9
        )
    
    def time_since_last_seen(self) -> float:
        """Get seconds since last seen"""
        return (datetime.utcnow() - self.last_seen_at).total_seconds()
    
    def is_stale(self, max_age_seconds: int = 90) -> bool:
        """Check if node hasn't been seen recently"""
        return self.time_since_last_seen() > max_age_seconds
    
    def get_efficiency_score(self) -> float:
        """Calculate efficiency score based on historical performance"""
        total_tasks = self.completed_tasks_count + self.failed_tasks_count
        if total_tasks == 0:
            return 1.0  # New nodes get benefit of doubt
            
        # Success rate component
        success_rate = self.completed_tasks_count / total_tasks
        
        # Performance component (lower average duration is better)
        performance_score = 1.0
        if self.health.average_task_duration_seconds:
            # Normalize to 0.0-1.0 range, assuming 60s is average
            performance_score = max(0.1, min(1.0, 60.0 / self.health.average_task_duration_seconds))
        
        # Health component
        health_score = 1.0 - (self.health.consecutive_failures * 0.1)
        health_score = max(0.0, health_score)
        
        # Combined score
        return (success_rate * 0.5 + performance_score * 0.3 + health_score * 0.2)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        data = self.model_dump(mode="json")
        # Convert sets to lists for JSON serialization
        data["assigned_tasks"] = list(self.assigned_tasks)
        data["capabilities"]["supported_task_types"] = [t.value for t in self.capabilities.supported_task_types]
        data["capabilities"]["tags"] = list(self.capabilities.tags)
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutorNode":
        """Create node from dictionary"""
        # Convert lists back to sets and enums
        if "assigned_tasks" in data:
            data["assigned_tasks"] = set(data["assigned_tasks"])
            
        if "capabilities" in data:
            caps = data["capabilities"]
            if "supported_task_types" in caps:
                caps["supported_task_types"] = {TaskType(t) for t in caps["supported_task_types"]}
            if "tags" in caps:
                caps["tags"] = set(caps["tags"])
                
        return cls.model_validate(data)
    
    def __str__(self) -> str:
        return f"ExecutorNode(id={self.id[:8]}, name={self.name}, status={self.status.value})"