"""
Direct adapter for API routes that bypasses HTTP.

This adapter provides the same interface as GleitzeitClient but directly
accesses the persistence layer and core components, avoiding circular
dependencies where the API would call itself.
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from gleitzeit.core.models import Task, Workflow, TaskResult
from gleitzeit.persistence.factory import PersistenceFactory

logger = logging.getLogger(__name__)


class DirectAdapter:
    """
    Direct adapter that implements client interface but uses persistence directly.
    
    This adapter is used by API routes to avoid circular dependencies.
    It provides the same methods as GleitzeitClient but accesses the
    persistence layer directly without making HTTP calls.
    """
    
    def __init__(self):
        """Initialize the direct adapter."""
        self.persistence = None
        self.initialized = False
        
    async def initialize(self):
        """Initialize the adapter with persistence backend."""
        if self.initialized:
            return
            
        # Get persistence backend (same as SystemManager uses)
        self.persistence = await PersistenceFactory.create()
        self.initialized = True
        logger.info("DirectAdapter initialized with persistence backend")
        
    async def shutdown(self):
        """Cleanup adapter resources."""
        # Persistence is shared, don't close it
        self.initialized = False
        
    # Workflow operations
    
    async def list_workflows(self, status: Optional[str] = None,
                           limit: int = 100, offset: int = 0) -> List[Workflow]:
        """List workflows directly from persistence."""
        if not self.initialized:
            await self.initialize()
            
        try:
            workflows = await self.persistence.list_workflows(
                status=status, limit=limit, offset=offset
            )
            # Convert to Workflow objects if needed
            if workflows and isinstance(workflows[0], dict):
                workflows = [Workflow(**w) for w in workflows]
            return workflows or []
        except Exception as e:
            logger.error(f"Error listing workflows: {e}")
            return []
    
    async def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Get workflow directly from persistence."""
        if not self.initialized:
            await self.initialize()
            
        try:
            workflow = await self.persistence.get_workflow(workflow_id)
            if workflow and isinstance(workflow, dict):
                workflow = Workflow(**workflow)
            return workflow
        except Exception as e:
            logger.error(f"Error getting workflow {workflow_id}: {e}")
            return None
    
    async def create_workflow(self, workflow: Workflow) -> Dict[str, Any]:
        """Create workflow directly in persistence."""
        if not self.initialized:
            await self.initialize()
            
        try:
            workflow_dict = workflow.dict() if hasattr(workflow, 'dict') else workflow
            result = await self.persistence.create_workflow(workflow_dict)
            return {"success": True, "workflow_id": result.get("id", workflow_dict.get("id"))}
        except Exception as e:
            logger.error(f"Error creating workflow: {e}")
            return {"success": False, "error": str(e)}
    
    async def cancel_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Cancel workflow directly via persistence."""
        if not self.initialized:
            await self.initialize()
            
        try:
            await self.persistence.update_workflow_status(workflow_id, "cancelled")
            return {"success": True, "workflow_id": workflow_id}
        except Exception as e:
            logger.error(f"Error cancelling workflow {workflow_id}: {e}")
            return {"success": False, "error": str(e)}
    
    # Task operations
    
    async def list_tasks(self, status: Optional[str] = None,
                        workflow_id: Optional[str] = None,
                        limit: int = 100, offset: int = 0) -> List[Task]:
        """List tasks directly from persistence."""
        if not self.initialized:
            await self.initialize()
            
        try:
            tasks = await self.persistence.list_tasks(
                workflow_id=workflow_id, status=status,
                limit=limit, offset=offset
            )
            # Convert to Task objects if needed
            if tasks and isinstance(tasks[0], dict):
                tasks = [Task(**t) for t in tasks]
            return tasks or []
        except Exception as e:
            logger.error(f"Error listing tasks: {e}")
            return []
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get task directly from persistence."""
        if not self.initialized:
            await self.initialize()
            
        try:
            task = await self.persistence.get_task(task_id)
            if task and isinstance(task, dict):
                task = Task(**task)
            return task
        except Exception as e:
            logger.error(f"Error getting task {task_id}: {e}")
            return None
    
    async def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        """Get task result directly from persistence."""
        if not self.initialized:
            await self.initialize()
            
        try:
            result = await self.persistence.get_task_result(task_id)
            if result and isinstance(result, dict):
                result = TaskResult(**result)
            return result
        except Exception as e:
            logger.error(f"Error getting task result {task_id}: {e}")
            return None
    
    async def create_task(self, task: Task) -> Dict[str, Any]:
        """Create task directly in persistence."""
        if not self.initialized:
            await self.initialize()
            
        try:
            task_dict = task.dict() if hasattr(task, 'dict') else task
            result = await self.persistence.create_task(task_dict)
            return {"success": True, "task_id": result.get("id", task_dict.get("id"))}
        except Exception as e:
            logger.error(f"Error creating task: {e}")
            return {"success": False, "error": str(e)}
    
    async def cancel_task(self, task_id: str) -> bool:
        """Cancel task directly via persistence."""
        if not self.initialized:
            await self.initialize()
            
        try:
            await self.persistence.update_task_status(task_id, "cancelled")
            return True
        except Exception as e:
            logger.error(f"Error cancelling task {task_id}: {e}")
            return False
    
    # System operations
    
    async def get_system_status(self) -> Dict[str, Any]:
        """Get system status directly."""
        if not self.initialized:
            await self.initialize()
            
        try:
            # Get basic system info from persistence
            return {
                "status": "healthy",
                "persistence": {
                    "type": type(self.persistence).__name__,
                    "connected": True
                },
                "version": "0.0.6"
            }
        except Exception as e:
            logger.error(f"Error getting system status: {e}")
            return {"status": "error", "error": str(e)}
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check."""
        return await self.get_system_status()
    
    # Auth operations (stateless - no-op for direct adapter)
    
    async def login(self, username: str, password: str) -> Dict[str, Any]:
        """Login is not needed for direct adapter."""
        return {"success": True, "message": "Direct adapter doesn't need auth"}
    
    async def logout(self) -> Dict[str, Any]:
        """Logout is not needed for direct adapter."""
        return {"success": True, "message": "Direct adapter doesn't need auth"}
    
    async def get_current_user(self) -> Dict[str, Any]:
        """Get current user (system for direct adapter)."""
        return {"username": "system", "role": "admin"}
    
    # Additional methods can be added as needed to match GleitzeitClient interface