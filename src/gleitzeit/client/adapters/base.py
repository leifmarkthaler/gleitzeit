"""
Base adapter interface for Gleitzeit client modes.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from gleitzeit.core.models import Task, Workflow, WorkflowExecution, TaskResult


class BaseAdapter(ABC):
    """Abstract base class for client mode adapters."""
    
    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the adapter."""
        pass
    
    @abstractmethod
    async def shutdown(self) -> None:
        """Shutdown the adapter and cleanup resources."""
        pass
    
    # Workflow operations
    @abstractmethod
    async def submit_workflow(self, workflow: Workflow) -> Dict[str, Any]:
        """Submit a workflow for execution."""
        pass
    
    @abstractmethod
    async def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Get workflow by ID."""
        pass
    
    @abstractmethod
    async def list_workflows(self, status: Optional[str] = None, 
                           limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """List workflows with optional filters."""
        pass
    
    @abstractmethod
    async def cancel_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Cancel a workflow."""
        pass
    
    @abstractmethod
    async def pause_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Pause a workflow."""
        pass
    
    @abstractmethod
    async def resume_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Resume a paused workflow."""
        pass
    
    @abstractmethod
    async def delete_workflow(self, workflow_id: str) -> bool:
        """Delete a workflow."""
        pass
    
    @abstractmethod
    async def get_workflow_tasks(self, workflow_id: str) -> List[Task]:
        """Get all tasks for a workflow."""
        pass
    
    @abstractmethod
    async def get_workflow_results(self, workflow_id: str) -> List[Dict[str, Any]]:
        """Get all task results for a workflow."""
        pass
    
    # Task operations
    # Note: submit_task removed - all tasks must be submitted as workflows
    
    @abstractmethod
    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID."""
        pass
    
    @abstractmethod
    async def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        """Get task result."""
        pass
    
    @abstractmethod
    async def list_tasks(self, status: Optional[str] = None,
                        workflow_id: Optional[str] = None,
                        limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """List tasks with optional filters."""
        pass
    
    @abstractmethod
    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a task."""
        pass
    
    @abstractmethod
    async def delete_task(self, task_id: str) -> bool:
        """Delete a task."""
        pass
    
    @abstractmethod
    async def wait_for_task(self, task_id: str, timeout: float = 300.0,
                           poll_interval: float = 1.0) -> Optional[TaskResult]:
        """Wait for task completion."""
        pass
    
    # Queue operations
    @abstractmethod
    async def get_queues(self) -> Dict[str, Any]:
        """Get all queues."""
        pass
    
    @abstractmethod
    async def get_queue_details(self, queue_name: str) -> Dict[str, Any]:
        """Get details for a specific queue."""
        pass
    
    @abstractmethod
    async def pause_queue(self, queue_name: str) -> Dict[str, Any]:
        """Pause a queue."""
        pass
    
    @abstractmethod
    async def resume_queue(self, queue_name: str) -> Dict[str, Any]:
        """Resume a queue."""
        pass
    
    @abstractmethod
    async def clear_queue(self, queue_name: str) -> Dict[str, Any]:
        """Clear all items from a queue."""
        pass
    
    # Batch operations
    @abstractmethod
    async def batch_process(self, directory: str, pattern: str = "*",
                           method: str = "llm/chat", prompt: str = None,
                           model: str = "llama3.2:latest",
                           max_concurrent: int = 5,
                           name: Optional[str] = None) -> Dict[str, Any]:
        """Process files in batch."""
        pass
    
    @abstractmethod
    async def process_directory(self, directory: str, file_extensions: List[str],
                               workflow_yaml: str, max_concurrent: int = 5,
                               recursive: bool = True) -> Dict[str, Any]:
        """Process directory with workflow template."""
        pass
    
    # Chat operations
    @abstractmethod
    async def chat(self, message: str, model: str = "llama3.2:latest",
                  temperature: float = 0.7,
                  session_id: Optional[str] = None) -> Dict[str, Any]:
        """Chat with LLM."""
        pass
    
    # System operations
    @abstractmethod
    async def get_system_status(self) -> Dict[str, Any]:
        """Get system status."""
        pass
    
    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check."""
        pass
    
    @abstractmethod
    async def get_providers(self) -> List[Dict[str, Any]]:
        """Get available providers."""
        pass
    
    @abstractmethod
    async def get_protocols(self) -> List[Dict[str, Any]]:
        """Get available protocols."""
        pass
    
    # Auth operations (optional - not all adapters may support)
    async def login(self, username: str, password: str) -> Dict[str, Any]:
        """Login user. Default implementation returns not supported."""
        return {"error": "Authentication not supported in this mode"}
    
    async def logout(self) -> Dict[str, Any]:
        """Logout user. Default implementation returns not supported."""
        return {"error": "Authentication not supported in this mode"}
    
    async def get_current_user(self) -> Dict[str, Any]:
        """Get current user. Default implementation returns not supported."""
        return {"error": "Authentication not supported in this mode"}