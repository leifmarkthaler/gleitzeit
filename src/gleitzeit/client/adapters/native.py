"""
Native adapter for direct access to Gleitzeit components.

This adapter provides direct access to persistence and core components
without HTTP overhead. Used by the API to avoid circular dependencies.
"""

import logging
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from datetime import datetime

from gleitzeit.core.models import Task, Workflow, TaskResult, TaskStatus, WorkflowStatus
from gleitzeit.persistence.factory import PersistenceFactory
from gleitzeit.core.events import EventType

if TYPE_CHECKING:
    from gleitzeit.core.workflow_manager import WorkflowManager

logger = logging.getLogger(__name__)


class NativeAdapter:
    """
    Native adapter that directly accesses persistence and core components.
    
    This adapter is used when the client needs direct access without HTTP,
    particularly for the API server to avoid circular dependencies.
    """
    
    def __init__(self):
        """Initialize the native adapter."""
        self.persistence = None
        self.workflow_manager = None
        self.system_manager = None
        self.initialized = False
        
    async def initialize(self):
        """Initialize the adapter with persistence backend and workflow manager."""
        if self.initialized:
            return
            
        # Get persistence backend (shared with SystemManager)
        self.persistence = await PersistenceFactory.create()
        
        # Get SystemManager instance to access workflow manager
        from gleitzeit.system.system_manager import SystemManager
        
        # Check if SystemManager is already initialized (e.g., by API)
        # If not, we only use persistence directly (backward compatibility)
        # The API should provide the system_manager via set_system_manager
        
        self.initialized = True
        logger.info("NativeAdapter initialized with direct persistence access")
        
    def set_system_manager(self, system_manager):
        """Set the system manager to access workflow manager.
        
        Args:
            system_manager: SystemManager instance with workflow_manager
        """
        self.system_manager = system_manager
        if system_manager and hasattr(system_manager, 'workflow_manager'):
            self.workflow_manager = system_manager.workflow_manager
            logger.info("NativeAdapter configured with WorkflowManager from SystemManager")
        
    async def shutdown(self):
        """Cleanup adapter resources."""
        # Persistence is shared, don't close it
        self.initialized = False
        logger.info("NativeAdapter shutdown")
        
    # Workflow operations
    
    async def list_workflows(self, status: Optional[str] = None,
                           limit: int = 100, offset: int = 0) -> List[Workflow]:
        """List workflows directly from persistence."""
        if not self.initialized:
            await self.initialize()
            
        try:
            result = await self.persistence.list_workflows(
                status=status, limit=limit, offset=offset
            )
            # Handle dict response from persistence layer
            if isinstance(result, dict):
                workflows = result.get("workflows", [])
            else:
                workflows = result
                
            # Convert to Workflow objects if needed
            if workflows and len(workflows) > 0 and isinstance(workflows[0], dict):
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
    
    async def submit_workflow(self, workflow: Workflow) -> Dict[str, Any]:
        """Submit workflow for execution."""
        if not self.initialized:
            await self.initialize()
            
        try:
            workflow_dict = workflow.dict() if hasattr(workflow, 'dict') else workflow
            
            # Store in persistence first
            await self.persistence.save_workflow(workflow)
            
            # If we have a workflow manager, use it to execute
            if self.workflow_manager:
                logger.info(f"Executing workflow {workflow.id} via WorkflowManager")
                result = await self.workflow_manager.execute_workflow(workflow)
                return {"success": True, "workflow_id": workflow.id, "execution": result}
            else:
                # Backward compatibility: just store in persistence
                # The execution engine should pick it up via events
                logger.warning(f"No WorkflowManager available, workflow {workflow.id} stored but not executed")
                return {"success": True, "workflow_id": workflow_dict.get("id")}
        except Exception as e:
            logger.error(f"Error submitting workflow: {e}")
            return {"success": False, "error": str(e)}
    
    async def cancel_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Cancel workflow directly via persistence."""
        if not self.initialized:
            await self.initialize()
            
        try:
            workflow = await self.persistence.get_workflow(workflow_id)
            if workflow:
                workflow.status = WorkflowStatus.CANCELLED
                await self.persistence.save_workflow(workflow)
            return {"success": True, "workflow_id": workflow_id}
        except Exception as e:
            logger.error(f"Error cancelling workflow {workflow_id}: {e}")
            return {"success": False, "error": str(e)}
    
    async def pause_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Pause workflow directly via persistence."""
        if not self.initialized:
            await self.initialize()
            
        try:
            workflow = await self.persistence.get_workflow(workflow_id)
            if workflow:
                workflow.status = WorkflowStatus.PAUSED
                await self.persistence.save_workflow(workflow)
            return {"success": True, "workflow_id": workflow_id}
        except Exception as e:
            logger.error(f"Error pausing workflow {workflow_id}: {e}")
            return {"success": False, "error": str(e)}
    
    async def resume_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Resume workflow directly via persistence."""
        if not self.initialized:
            await self.initialize()
            
        try:
            workflow = await self.persistence.get_workflow(workflow_id)
            if workflow:
                workflow.status = WorkflowStatus.RUNNING
                await self.persistence.save_workflow(workflow)
            return {"success": True, "workflow_id": workflow_id}
        except Exception as e:
            logger.error(f"Error resuming workflow {workflow_id}: {e}")
            return {"success": False, "error": str(e)}
    
    async def delete_workflow(self, workflow_id: str) -> bool:
        """Delete workflow directly from persistence."""
        if not self.initialized:
            await self.initialize()
            
        try:
            await self.persistence.delete_workflow(workflow_id)
            return True
        except Exception as e:
            logger.error(f"Error deleting workflow {workflow_id}: {e}")
            return False
    
    async def get_workflow_tasks(self, workflow_id: str) -> List[Task]:
        """Get workflow tasks directly from persistence."""
        if not self.initialized:
            await self.initialize()
            
        try:
            tasks = await self.persistence.list_tasks(workflow_id=workflow_id)
            if tasks and isinstance(tasks[0], dict):
                tasks = [Task(**t) for t in tasks]
            return tasks or []
        except Exception as e:
            logger.error(f"Error getting workflow tasks: {e}")
            return []
    
    # Task operations
    
    async def list_tasks(self, status: Optional[str] = None,
                        workflow_id: Optional[str] = None,
                        limit: int = 100, offset: int = 0) -> List[Task]:
        """List tasks directly from persistence."""
        if not self.initialized:
            await self.initialize()
            
        try:
            result = await self.persistence.list_tasks(
                workflow_id=workflow_id, status=status,
                limit=limit, offset=offset
            )
            # Handle dict response from persistence layer
            if isinstance(result, dict):
                tasks = result.get("tasks", [])
            else:
                tasks = result
                
            if tasks and len(tasks) > 0 and isinstance(tasks[0], dict):
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
    
    async def submit_task(self, task: Task) -> Dict[str, Any]:
        """Submit task directly to persistence."""
        if not self.initialized:
            await self.initialize()
            
        try:
            task_dict = task.dict() if hasattr(task, 'dict') else task
            await self.persistence.create_task(task_dict)
            return {"success": True, "task_id": task_dict.get("id")}
        except Exception as e:
            logger.error(f"Error submitting task: {e}")
            return {"success": False, "error": str(e)}
    
    async def cancel_task(self, task_id: str) -> bool:
        """Cancel task directly via persistence."""
        if not self.initialized:
            await self.initialize()
            
        try:
            await self.persistence.update_task_status(task_id, TaskStatus.CANCELLED)
            return True
        except Exception as e:
            logger.error(f"Error cancelling task {task_id}: {e}")
            return False
    
    async def delete_task(self, task_id: str) -> bool:
        """Delete task directly from persistence."""
        if not self.initialized:
            await self.initialize()
            
        try:
            await self.persistence.delete_task(task_id)
            return True
        except Exception as e:
            logger.error(f"Error deleting task {task_id}: {e}")
            return False
    
    async def wait_for_task(self, task_id: str, timeout: float = 300.0,
                           poll_interval: float = 1.0) -> Optional[TaskResult]:
        """
        Wait for task completion.
        
        In native mode, this polls the persistence layer directly.
        """
        import asyncio
        import time
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            task = await self.get_task(task_id)
            if task and task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                return await self.get_task_result(task_id)
                
            await asyncio.sleep(poll_interval)
            
        return None
    
    # Queue operations
    
    async def get_queues(self) -> Dict[str, Any]:
        """Get queue information."""
        # Simplified for now
        return {"queues": []}
    
    async def get_queue_details(self, queue_name: str) -> Dict[str, Any]:
        """Get queue details."""
        return {"queue": queue_name, "size": 0}
    
    # System operations
    
    async def get_system_status(self) -> Dict[str, Any]:
        """Get system status directly."""
        if not self.initialized:
            await self.initialize()
            
        return {
            "status": "healthy",
            "mode": "native",
            "persistence": {
                "type": type(self.persistence).__name__,
                "connected": True
            }
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check."""
        return await self.get_system_status()
    
    # Auth operations (no-op for native adapter in stateless architecture)
    
    async def login(self, username: str, password: str) -> Dict[str, Any]:
        """Login is handled at API layer, not in native adapter."""
        return {"success": True, "message": "Native adapter - auth handled at API layer"}
    
    async def logout(self) -> Dict[str, Any]:
        """Logout is handled at API layer, not in native adapter."""
        return {"success": True, "message": "Native adapter - auth handled at API layer"}
    
    async def get_current_user(self) -> Dict[str, Any]:
        """Get current user (system for native adapter)."""
        return {"username": "system", "role": "admin", "adapter": "native"}
    
    # WorkflowManager access
    
    async def get_workflow_manager(self) -> Optional["WorkflowManager"]:
        """
        Get WorkflowManager instance from SystemManager or create one.
        
        This method attempts to:
        1. Get WorkflowManager from distributed component registry
        2. Create a stateless instance if not found
        
        Returns:
            WorkflowManager instance or None if unavailable
        """
        try:
            # Try to get from component registry first
            from gleitzeit.system.distributed_registry import DistributedComponentRegistry
            from gleitzeit.core.workflow_manager_factory import WorkflowManagerFactory
            
            # Try to get existing instance from registry
            try:
                registry = DistributedComponentRegistry(self.persistence)
                components = await registry.list_components(component_type="WorkflowManager")
                if components:
                    # Get the component metadata
                    component = components[0]
                    logger.info(f"Found WorkflowManager in registry: {component.component_id}")
                    # For now, we'll create a new instance since we can't serialize the actual object
                    # In a real implementation, we'd need a way to get the actual instance
            except Exception as e:
                logger.debug(f"Could not get WorkflowManager from registry: {e}")
            
            # Create stateless instance if not found
            logger.info("Creating new WorkflowManager instance")
            workflow_manager = await WorkflowManagerFactory.create(
                persistence=self.persistence,
                event_bus=None,  # Event bus would be created if needed
                execution_engine=None,  # Will be created by factory
                dependency_resolver=None
            )
            return workflow_manager
            
        except Exception as e:
            logger.error(f"Error getting WorkflowManager: {e}")
            return None
    
    async def get_task_logs(self, 
                          task_id: str,
                          level: Optional[str] = None,
                          limit: int = 100,
                          offset: int = 0) -> List[Dict[str, Any]]:
        """
        Get logs for a specific task from the centralized logging system.
        
        Args:
            task_id: Task ID to get logs for
            level: Optional log level filter
            limit: Maximum number of logs to return
            offset: Offset for pagination
            
        Returns:
            List of log entries for the task
        """
        if not self.initialized:
            await self.initialize()
            
        try:
            # Try to get logs from Redis log adapter first
            if hasattr(self.persistence, 'redis') and self.persistence.redis:
                from gleitzeit.persistence.log_redis_adapter import LogRedisAdapter
                log_adapter = LogRedisAdapter(self.persistence.redis)
                
                # Get logs for this specific task
                logs = await log_adapter.get_logs(
                    task_id=task_id,
                    level=level,
                    limit=limit,
                    offset=offset
                )
                
                # Convert LogEntry objects to dictionaries if needed
                if logs and hasattr(logs[0], 'to_dict'):
                    logs = [log.to_dict() for log in logs]
                    
                return logs
                
        except Exception as e:
            logger.debug(f"Could not get logs from Redis adapter: {e}")
        
        # Fallback: If no centralized logs available yet, return minimal info
        # This is temporary until full logging integration is complete
        try:
            task = await self.persistence.get_task(task_id)
            if task:
                return [{
                    "timestamp": datetime.now().isoformat(),
                    "level": "INFO",
                    "message": f"Real-time logs not yet available for task {task_id}. Enable LogCollector for full logging.",
                    "task_id": task_id,
                    "source": "native_adapter",
                    "metadata": {
                        "task_name": task.name if hasattr(task, 'name') else None,
                        "task_status": task.status if hasattr(task, 'status') else None,
                        "migration_notice": "Logs will be available once LogCollector is properly initialized"
                    }
                }]
            else:
                return [{
                    "timestamp": datetime.now().isoformat(),
                    "level": "WARNING",
                    "message": f"Task {task_id} not found",
                    "task_id": task_id,
                    "source": "native_adapter"
                }]
                
        except Exception as e:
            logger.error(f"Error getting task info: {e}")
            return [{
                "timestamp": datetime.now().isoformat(),
                "level": "ERROR",
                "message": f"Error retrieving logs for task {task_id}: {str(e)}",
                "task_id": task_id,
                "source": "native_adapter"
            }]
    
    async def get_logs(self, 
                      level: Optional[str] = None,
                      source: Optional[str] = None,
                      start_time: Optional[datetime] = None,
                      end_time: Optional[datetime] = None,
                      limit: int = 100,
                      offset: int = 0) -> List[Dict[str, Any]]:
        """Get logs with optional filtering from centralized system."""
        if not self.initialized:
            await self.initialize()
            
        try:
            # Try to get logs from Redis log adapter
            if hasattr(self.persistence, 'redis') and self.persistence.redis:
                from gleitzeit.persistence.log_redis_adapter import LogRedisAdapter
                log_adapter = LogRedisAdapter(self.persistence.redis)
                
                # Get logs with filters
                logs = await log_adapter.get_logs(
                    level=level,
                    source=source,
                    start_time=start_time,
                    end_time=end_time,
                    limit=limit,
                    offset=offset
                )
                
                # Convert LogEntry objects to dictionaries if needed
                if logs and hasattr(logs[0], 'to_dict'):
                    logs = [log.to_dict() for log in logs]
                    
                return logs
                
        except Exception as e:
            logger.debug(f"Could not get logs from Redis adapter: {e}")
        
        # Fallback message
        return [{
            "timestamp": datetime.now().isoformat(),
            "level": "INFO",
            "message": "Centralized logging not yet available. Enable LogCollector for full logging.",
            "source": "native_adapter"
        }]
    
    async def get_log_levels(self) -> List[str]:
        """Get available log levels."""
        return ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
    
    async def query_logs(self, 
                        query: str,
                        limit: int = 100,
                        offset: int = 0) -> List[Dict[str, Any]]:
        """Query logs using a search string."""
        if not self.initialized:
            await self.initialize()
            
        try:
            # Try to query logs from Redis log adapter
            if hasattr(self.persistence, 'redis') and self.persistence.redis:
                from gleitzeit.persistence.log_redis_adapter import LogRedisAdapter
                log_adapter = LogRedisAdapter(self.persistence.redis)
                
                # Search logs - this would need to be implemented in LogRedisAdapter
                # For now, return empty as query functionality may not be fully implemented
                return []
                
        except Exception as e:
            logger.debug(f"Could not query logs from Redis adapter: {e}")
        
        return []
    
    async def tail_logs(self,
                       lines: int = 100,
                       follow: bool = False,
                       source: Optional[str] = None) -> List[Dict[str, Any]]:
        """Tail logs (get most recent logs)."""
        # For tail functionality, get recent logs
        return await self.get_logs(
            source=source,
            limit=lines,
            offset=0
        )
    
    async def download_logs(self,
                          format: str = "json",
                          start_time: Optional[datetime] = None,
                          end_time: Optional[datetime] = None) -> bytes:
        """Download logs in specified format."""
        logs = await self.get_logs(
            start_time=start_time,
            end_time=end_time,
            limit=10000  # Large limit for download
        )
        
        if format == "json":
            import json
            return json.dumps(logs, indent=2).encode('utf-8')
        elif format == "csv":
            # Simple CSV conversion
            if not logs:
                return b"timestamp,level,message,source\n"
            
            csv_lines = ["timestamp,level,message,source"]
            for log in logs:
                line = f"{log.get('timestamp','')},{log.get('level','')},{log.get('message','').replace(',',';')},{log.get('source','')}"
                csv_lines.append(line)
            return "\n".join(csv_lines).encode('utf-8')
        else:
            # Plain text format
            lines = []
            for log in logs:
                line = f"[{log.get('timestamp','')}] {log.get('level','')} {log.get('source','')}: {log.get('message','')}"
                lines.append(line)
            return "\n".join(lines).encode('utf-8')
    
    async def clear_logs(self,
                        before: Optional[datetime] = None,
                        level: Optional[str] = None) -> Dict[str, Any]:
        """Clear logs with optional filtering."""
        # This would need to be implemented in the persistence layer
        return {"success": False, "message": "Log clearing not yet implemented in native adapter"}
    
    async def get_log_size(self) -> Dict[str, Any]:
        """Get log storage size information."""
        # This would need to be implemented in the persistence layer
        return {"bytes": 0, "human_readable": "0 B", "message": "Log size calculation not yet implemented"}
    
    async def get_workflow_logs(self, workflow_id: str) -> List[Dict[str, Any]]:
        """Get logs for a specific workflow."""
        if not self.initialized:
            await self.initialize()
            
        try:
            # Get logs filtered by workflow_id
            if hasattr(self.persistence, 'redis') and self.persistence.redis:
                from gleitzeit.persistence.log_redis_adapter import LogRedisAdapter
                log_adapter = LogRedisAdapter(self.persistence.redis)
                
                # Get logs for this specific workflow
                logs = await log_adapter.get_logs(
                    workflow_id=workflow_id,
                    limit=1000  # Large limit for workflow logs
                )
                
                # Convert LogEntry objects to dictionaries if needed
                if logs and hasattr(logs[0], 'to_dict'):
                    logs = [log.to_dict() for log in logs]
                    
                return logs
                
        except Exception as e:
            logger.debug(f"Could not get workflow logs from Redis adapter: {e}")
        
        # Fallback: minimal info
        return [{
            "timestamp": datetime.now().isoformat(),
            "level": "INFO",
            "message": f"Real-time logs not yet available for workflow {workflow_id}. Enable LogCollector for full logging.",
            "workflow_id": workflow_id,
            "source": "native_adapter"
        }]