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
from gleitzeit.core.events import EventType, GleitzeitEvent
from gleitzeit.core.errors import SystemError, ErrorCode, AuthorizationError, AuthenticationError

if TYPE_CHECKING:
    from gleitzeit.core.workflow_manager import WorkflowManager

logger = logging.getLogger(__name__)


class NativeAdapter:
    """
    Native adapter that directly accesses persistence and core components.
    
    This adapter is used when the client needs direct access without HTTP,
    particularly for the API server to avoid circular dependencies.
    """
    
    def __init__(self, user_context: Optional[Dict[str, Any]] = None, system_manager=None):
        """Initialize the native adapter.

        Args:
            user_context: Current user context for authorization.
                         Should include id, role, permissions, etc.
                         If None, authorization checks are skipped (backward compat).
            system_manager: Optional SystemManager instance to use directly.
        """
        self.persistence = None
        self.workflow_manager = None
        self.system_manager = system_manager  # Can be provided directly
        self.event_bus = None  # Event bus for task submission events
        self.initialized = False
        self.user_context = user_context  # User context for authorization
        self.session_id = None  # Session ID from AuthManager

        # Stream integration
        self._is_stream_enabled = False
        self._stream_manager = None
        
    async def initialize(self):
        """Initialize the adapter with StreamSystemManager."""
        if self.initialized:
            return

        # If SystemManager not provided, get or create ModularStreamSystemManager
        if not self.system_manager:
            from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager
            from gleitzeit.system.models import SystemConfig, DeploymentMode

            # Create system config
            config = SystemConfig()
            config.deployment_mode = DeploymentMode.PRODUCTION

            # Always use modular stream-based system manager
            self.system_manager = await ModularStreamSystemManager.create(
                config=config,
                create_if_missing=True,  # Create if none exists
                start_system=False  # Don't auto-start to avoid blocking
            )

            # Start system if created new
            if self.system_manager and not self.system_manager._running:
                await self.system_manager.start_system()

            if not self.system_manager:
                raise SystemError(
                    message="Could not get or create ModularStreamSystemManager",
                    code=ErrorCode.SYSTEM_NOT_INITIALIZED
                )

        # Enable stream integration
        self._is_stream_enabled = True
        self._stream_manager = self.system_manager

        # Get persistence from StreamSystemManager (already initialized)
        self.persistence = self.system_manager.persistence

        # Get workflow_manager from StreamSystemManager
        self.workflow_manager = self.system_manager.workflow_manager

        # Get event_bus from StreamSystemManager for task submission events
        self.event_bus = self.system_manager.event_bus

        self.initialized = True
        logger.info("NativeAdapter initialized with StreamSystemManager")
    
    def set_user_context(self, user_context: Dict[str, Any]) -> None:
        """Set or update the user context for authorization."""
        self.user_context = user_context
    
    def set_session_id(self, session_id: str) -> None:
        """Set the session ID for authentication through AuthManager."""
        self.session_id = session_id
    
    async def _get_or_create_session(self) -> str:
        """Get or create session for authenticated operations."""
        if self.session_id:
            return self.session_id
        elif self.system_manager and self.system_manager.auth_manager:
            try:
                session_id, _ = await self.system_manager.auth_manager.get_or_create_basic_session()
                self.session_id = session_id
                return session_id
            except Exception:
                raise AuthorizationError("No session available for log access")
        else:
            return "basic-user-default"
    
    async def _check_workflow_access(self, workflow: Workflow, action: str) -> bool:
        """Check if current user has access to a workflow.
        
        Returns True if authorized, False otherwise.
        """
        if not self.user_context:
            # No user context = skip authorization (backward compat)
            logger.warning("No user context for authorization - skipping checks")
            return True
        
        # Admin/superuser always has access
        if self.user_context.get("is_superuser") or self.user_context.get("role") == "admin":
            return True
        
        # Check ownership
        workflow_user_id = getattr(workflow, 'user_id', None)
        user_id = self.user_context.get('id')
        
        # Owner has access
        if workflow_user_id and workflow_user_id == user_id:
            return True
        
        # Public workflows allow read access
        is_public = getattr(workflow, 'is_public', False)
        if is_public and action in ["read", "access"]:
            return True
        
        return False
        
    # REMOVED set_system_manager - violates stateless architecture
    # Each NativeAdapter discovers SystemManager through persistence
        
    async def shutdown(self):
        """Cleanup adapter resources."""
        # Persistence is shared, don't close it
        self.initialized = False
        self._is_stream_enabled = False
        self._stream_manager = None
        logger.info("NativeAdapter shutdown")

    def is_stream_enabled(self) -> bool:
        """Check if stream integration is enabled."""
        return self._is_stream_enabled

    async def get_stream_health(self) -> Dict[str, Any]:
        """Get stream system health if available."""
        if not self._is_stream_enabled or not self._stream_manager:
            return {"error": "Stream integration not available"}

        try:
            return await self._stream_manager.get_system_health()
        except Exception as e:
            logger.error(f"Error getting stream health: {e}")
            return {"error": str(e)}

    async def get_stream_statistics(self) -> Dict[str, Any]:
        """Get stream processing statistics if available."""
        if not self._is_stream_enabled or not self._stream_manager:
            return {"error": "Stream integration not available"}

        try:
            return await self._stream_manager.get_stream_statistics()
        except Exception as e:
            logger.error(f"Error getting stream statistics: {e}")
            return {"error": str(e)}
        
    # Workflow operations
    
    async def list_workflows(self, status: Optional[str] = None,
                           limit: int = 100, offset: int = 0) -> List[Workflow]:
        """List workflows through SystemManager."""
        if not self.initialized:
            await self.initialize()
            
        try:
            # UNIFIED PATHWAY: Always go through SystemManager's persistence
            if not self.system_manager:
                raise SystemError(
                    message="SystemManager is required for workflow listing",
                    code=ErrorCode.SYSTEM_NOT_INITIALIZED
                )
            
            # List through persistence directly (SystemManager controls access)
            workflows = await self.system_manager.persistence.list_workflows(
                status=status, limit=limit, offset=offset
            )
            
            # Handle dict response
            if isinstance(workflows, dict):
                workflows = workflows.get("workflows", [])
                
            # Convert to Workflow objects if needed
            if workflows and len(workflows) > 0 and isinstance(workflows[0], dict):
                workflows = [Workflow(**w) for w in workflows]
            return workflows or []
        except Exception as e:
            logger.error(f"Error listing workflows: {e}")
            return []
    
    async def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Get workflow through SystemManager with authorization check."""
        if not self.initialized:
            await self.initialize()
            
        try:
            # UNIFIED PATHWAY: Always go through SystemManager
            if not self.system_manager:
                raise SystemError(
                    message="SystemManager is required for workflow access",
                    code=ErrorCode.SYSTEM_NOT_INITIALIZED
                )
            
            # Get session ID - same logic as submit_workflow
            session_id = None
            if self.session_id:
                # Use cached session
                session_id = self.session_id
            elif self.system_manager.auth_manager:
                # Try to get or create basic session
                try:
                    session_id, _ = await self.system_manager.auth_manager.get_or_create_basic_session()
                    self.session_id = session_id  # Cache for future use
                except Exception:
                    raise AuthenticationError("No session available for workflow access")
            else:
                session_id = "basic-user-default"
            
            # Get through SystemManager's authenticated method
            # This ensures proper authorization checks
            workflow = await self.system_manager.get_workflow_authenticated(workflow_id, session_id)
            return workflow
            
        except AuthorizationError:
            # Re-raise authorization errors
            raise
        except Exception as e:
            logger.error(f"Error getting workflow {workflow_id}: {e}")
            return None
    
    async def submit_workflow(self, workflow: Workflow) -> Dict[str, Any]:
        """Submit workflow through SystemManager with authentication."""
        if not self.initialized:
            await self.initialize()
            
        try:
            # UNIFIED PATHWAY: Always go through SystemManager
            if not self.system_manager:
                raise SystemError(
                    message="SystemManager is required for workflow submission",
                    code=ErrorCode.SYSTEM_NOT_INITIALIZED
                )
            
            # Get session ID - either cached or create basic session
            session_id = None
            if self.session_id:
                # Use cached session
                session_id = self.session_id
            elif self.system_manager.auth_manager:
                # Try to get or create basic session
                try:
                    session_id, _ = await self.system_manager.auth_manager.get_or_create_basic_session()
                    self.session_id = session_id  # Cache for future use
                except Exception:
                    # If basic session not available, authentication required
                    raise AuthenticationError("No session available for workflow submission")
            else:
                # No auth manager - use default
                session_id = "basic-user-default"
            
            # Submit through SystemManager's authenticated method
            # This ensures proper user_id is set on the workflow
            workflow_id_for_log = workflow.id if hasattr(workflow, 'id') else workflow.get('id', 'unknown') if isinstance(workflow, dict) else 'unknown'
            logger.info(f"Submitting workflow {workflow_id_for_log} via SystemManager.submit_workflow_authenticated")
            workflow_id = await self.system_manager.submit_workflow_authenticated(workflow, session_id)
            
            return {"success": True, "workflow_id": workflow_id}
            
        except Exception as e:
            logger.error(f"Error submitting workflow: {e}")
            return {"success": False, "error": str(e)}
    
    async def cancel_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Cancel workflow with authorization check."""
        if not self.initialized:
            await self.initialize()
            
        try:
            # First get the workflow properly (with auth check)
            workflow = await self.get_workflow(workflow_id)
            if not workflow:
                return {"success": False, "error": "Workflow not found"}
            
            # Check authorization for cancel action
            if self.user_context and not await self._check_workflow_access(workflow, "cancel"):
                raise AuthorizationError(
                    resource=f"workflow/{workflow_id}",
                    action="cancel",
                    reason="You don't have permission to cancel this workflow"
                )
            
            # Now proceed with the original logic
            workflow = await self.persistence.get_workflow(workflow_id)
            if workflow:
                # Cancel all tasks in the workflow that aren't already terminal
                cancelled_tasks = 0
                for task in workflow.tasks:
                    if task.status not in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                        task.status = TaskStatus.CANCELLED
                        await self.persistence.save_task(task)
                        cancelled_tasks += 1
                
                # Cancel the workflow itself
                workflow.status = WorkflowStatus.CANCELLED
                await self.persistence.save_workflow(workflow)
                
                return {
                    "success": True, 
                    "workflow_id": workflow_id,
                    "cancelled_tasks": cancelled_tasks
                }
            return {"success": True, "workflow_id": workflow_id}
        except Exception as e:
            logger.error(f"Error cancelling workflow {workflow_id}: {e}")
            return {"success": False, "error": str(e)}
    
    async def pause_workflow(
        self, 
        workflow_id: str,
        rewind_to_task: Optional[str] = None,
        rewind_to_step: Optional[int] = None,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """Pause workflow with optional rewind directly via persistence."""
        if not self.initialized:
            await self.initialize()
            
        try:
            # Check authorization first
            workflow = await self.persistence.get_workflow(workflow_id)
            if not workflow:
                return {"success": False, "error": "Workflow not found"}
            
            if self.user_context and not await self._check_workflow_access(workflow, "pause"):
                raise AuthorizationError(
                    resource=f"workflow/{workflow_id}",
                    action="pause",
                    reason="You don't have permission to pause this workflow"
                )
            
            # Get user ID for tracking
            user_id = self.user_context.get("id") if self.user_context else None
            
            # Use the new pause methods from ScalableRedisAdapter
            if hasattr(self.persistence, 'pause_workflow_with_rewind'):
                # Determine if we need rewind
                rewind_to = rewind_to_task or rewind_to_step
                
                if rewind_to:
                    result = await self.persistence.pause_workflow_with_rewind(
                        workflow_id=workflow_id,
                        user_id=user_id,
                        rewind_to=rewind_to,
                        reason=reason
                    )
                else:
                    result = await self.persistence.pause_workflow(
                        workflow_id=workflow_id,
                        user_id=user_id
                    )
                return result
            else:
                # Fallback to simple status change for backward compatibility
                workflow.status = WorkflowStatus.PAUSED if hasattr(WorkflowStatus, 'PAUSED') else WorkflowStatus.CANCELLED
                await self.persistence.save_workflow(workflow)
                return {"success": True, "workflow_id": workflow_id, "status": "paused"}
                
        except AuthorizationError:
            raise
        except Exception as e:
            logger.error(f"Error pausing workflow {workflow_id}: {e}")
            return {"success": False, "error": str(e)}
    
    async def resume_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Resume workflow directly via persistence."""
        if not self.initialized:
            await self.initialize()
            
        try:
            # Check authorization first
            workflow = await self.persistence.get_workflow(workflow_id)
            if not workflow:
                return {"success": False, "error": "Workflow not found"}
            
            if self.user_context and not await self._check_workflow_access(workflow, "resume"):
                raise AuthorizationError(
                    resource=f"workflow/{workflow_id}",
                    action="resume",
                    reason="You don't have permission to resume this workflow"
                )
            
            # Use the new resume method from ScalableRedisAdapter
            if hasattr(self.persistence, 'resume_workflow'):
                result = await self.persistence.resume_workflow(workflow_id)
                return result
            else:
                # Fallback to simple status change for backward compatibility
                workflow.status = WorkflowStatus.RUNNING
                await self.persistence.save_workflow(workflow)
                return {"success": True, "workflow_id": workflow_id, "status": "resumed"}
                
        except AuthorizationError:
            raise
        except Exception as e:
            logger.error(f"Error resuming workflow {workflow_id}: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_pause_status(self, workflow_id: str) -> Dict[str, Any]:
        """Get pause status and metadata for a workflow."""
        if not self.initialized:
            await self.initialize()
            
        try:
            # Check authorization first
            workflow = await self.persistence.get_workflow(workflow_id)
            if not workflow:
                return {"paused": False, "error": "Workflow not found"}
            
            if self.user_context and not await self._check_workflow_access(workflow, "read"):
                raise AuthorizationError(
                    resource=f"workflow/{workflow_id}",
                    action="read",
                    reason="You don't have permission to view this workflow"
                )
            
            # Get pause metadata from persistence
            if hasattr(self.persistence, '_key') and hasattr(self.persistence, '_execute'):
                pause_key = self.persistence._key(f"workflow:pause:{workflow_id}")
                pause_data = await self.persistence._execute("hgetall", pause_key)
                
                if not pause_data:
                    return {"paused": False}
                
                # Decode pause data
                if isinstance(pause_data, dict):
                    if any(isinstance(k, bytes) for k in pause_data.keys()):
                        pause_data = {
                            k.decode() if isinstance(k, bytes) else k: 
                            v.decode() if isinstance(v, bytes) else v
                            for k, v in pause_data.items()
                        }
                
                # Parse JSON fields
                import json
                for field in ["cancelled_tasks", "queued_tasks", "reset_tasks", "preserved_results"]:
                    if field in pause_data:
                        try:
                            pause_data[field] = json.loads(pause_data[field])
                        except:
                            pass
                
                pause_data["paused"] = True
                return pause_data
            else:
                # Simple check based on status
                return {"paused": workflow.status == WorkflowStatus.PAUSED if hasattr(WorkflowStatus, 'PAUSED') else False}
                
        except AuthorizationError:
            raise
        except Exception as e:
            logger.error(f"Error getting pause status for {workflow_id}: {e}")
            return {"paused": False, "error": str(e)}
    
    async def delete_workflow(self, workflow_id: str) -> bool:
        """Delete workflow with authorization check."""
        if not self.initialized:
            await self.initialize()
            
        try:
            # First get the workflow to check authorization
            workflow = await self.get_workflow(workflow_id)
            if not workflow:
                return False
            
            # Check authorization
            if self.user_context and not await self._check_workflow_access(workflow, "delete"):
                raise AuthorizationError(
                    resource=f"workflow/{workflow_id}",
                    action="delete",
                    reason="You don't have permission to delete this workflow"
                )
            
            await self.persistence.delete_workflow(workflow_id)
            return True
        except AuthorizationError:
            raise
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
    
    async def get_workflow_results(self, workflow_id: str) -> List[Dict[str, Any]]:
        """Get all task results for a workflow.
        
        Uses the system manager's execution engine for unified access.
        """
        if not self.initialized:
            await self.initialize()
            
        try:
            # Ensure SystemManager and execution engine are available
            if not self.system_manager:
                raise SystemError(
                    message="SystemManager not configured - cannot retrieve workflow results",
                    code=ErrorCode.SYSTEM_NOT_INITIALIZED
                )
            
            if not hasattr(self.system_manager, 'execution_engine') or not self.system_manager.execution_engine:
                raise SystemError(
                    message="ExecutionEngine not available in SystemManager",
                    code=ErrorCode.SYSTEM_NOT_INITIALIZED
                )
            
            # Use execution engine for unified result retrieval
            execution_engine = self.system_manager.execution_engine
            results = await execution_engine.get_workflow_results(workflow_id)
            
            # Convert TaskResult objects to dicts for API compatibility
            return [r.dict() if hasattr(r, 'dict') else r for r in results]
            
        except Exception as e:
            logger.error(f"Error getting workflow results: {e}")
            raise  # Re-raise to ensure proper error handling
    
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
    
    # Task submission removed - all tasks must be submitted as workflows
    # This ensures proper validation through the workflow loader
    async def submit_task_as_workflow(self, task: Task) -> Dict[str, Any]:
        """
        Helper to submit a single task as a workflow.
        DEPRECATED: Use submit_workflow directly.
        """
        # Convert task to dict if needed
        if hasattr(task, 'dict'):
            task_dict = task.dict()
        elif isinstance(task, dict):
            task_dict = task
        else:
            task_dict = task.__dict__
        
        # Create a single-task workflow
        workflow_dict = {
            "name": f"Single task: {task_dict.get('name', 'unnamed')}",
            "tasks": [task_dict]
        }
        
        # Convert to Workflow object
        from gleitzeit.core.models import Workflow
        workflow = Workflow(**workflow_dict)
        
        # Submit as workflow
        return await self.submit_workflow(workflow)
    
    async def cancel_task(self, task_id: str) -> bool:
        """Cancel task and cascade to workflow and remaining tasks."""
        if not self.initialized:
            await self.initialize()
            
        try:
            # Get the task to find its workflow
            task = await self.persistence.get_task(task_id)
            if not task:
                logger.error(f"Task {task_id} not found")
                return False
            
            # Cancel the specific task
            await self.persistence.update_task_status(task_id, TaskStatus.CANCELLED)
            
            # If task belongs to a workflow, cancel the entire workflow
            if task.workflow_id:
                result = await self.cancel_workflow(task.workflow_id)
                # Check if workflow cancellation was successful
                if not result.get("success", False):
                    logger.error(f"Failed to cancel workflow {task.workflow_id} for task {task_id}")
                    return False
            
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
    
    # Auth operations - Direct access via SystemManager's AuthManager
    
    async def login(self, username: str, password: str) -> Dict[str, Any]:
        """Login through SystemManager's AuthManager."""
        if not self.system_manager or not self.system_manager.auth_manager:
            return {"success": True, "message": "Native adapter - auth not configured"}
        
        try:
            result = await self.system_manager.auth_manager.login(username, password)
            return result
        except Exception as e:
            logger.error(f"Login error: {e}")
            return {"success": False, "error": str(e)}
    
    async def logout(self) -> Dict[str, Any]:
        """Logout through SystemManager's AuthManager."""
        if not self.system_manager or not self.system_manager.auth_manager:
            return {"success": True, "message": "Native adapter - auth not configured"}
        
        # Native adapter doesn't have session context, so this is a no-op
        return {"success": True, "message": "Logged out"}
    
    async def get_current_user(self) -> Dict[str, Any]:
        """Get current user from session or auto-login as basic user."""
        if not self.system_manager or not self.system_manager.auth_manager:
            return {"username": "system", "role": "admin", "adapter": "native"}
        
        # Try to get or create basic session for immediate use
        try:
            session_id, user = await self.system_manager.auth_manager.get_or_create_basic_session()
            return user
        except Exception as e:
            # If no session available, return system user
            logger.debug(f"Could not get session: {e}")
            return {"username": "system", "role": "admin", "adapter": "native"}
    
    # Extended auth operations
    
    async def create_user(self, username: str, email: str, password: str, 
                          role: str = "user", metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Create a new user through SystemManager's AuthManager."""
        if not self.system_manager or not self.system_manager.auth_manager:
            raise SystemError(
                message="AuthManager not configured",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED
            )
        
        try:
            user = await self.system_manager.auth_manager.create_user(
                username=username,
                email=email,
                password=password,
                role=role,
                metadata=metadata or {}
            )
            return user
        except Exception as e:
            logger.error(f"Create user error: {e}")
            raise
    
    async def list_users(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """List users through SystemManager's AuthManager."""
        if not self.system_manager or not self.system_manager.auth_manager:
            return []
        
        try:
            users = await self.system_manager.auth_manager.list_users(limit=limit, offset=offset)
            return users
        except Exception as e:
            logger.error(f"List users error: {e}")
            return []
    
    async def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID through SystemManager's AuthManager."""
        if not self.system_manager or not self.system_manager.auth_manager:
            return None
        
        try:
            user = await self.system_manager.auth_manager.get_user(user_id)
            return user
        except Exception as e:
            logger.error(f"Get user error: {e}")
            return None
    
    async def update_user(self, user_id: str, **kwargs) -> Dict[str, Any]:
        """Update user through SystemManager's AuthManager."""
        if not self.system_manager or not self.system_manager.auth_manager:
            raise SystemError(
                message="AuthManager not configured",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED
            )
        
        try:
            user = await self.system_manager.auth_manager.update_user(user_id, **kwargs)
            return user
        except Exception as e:
            logger.error(f"Update user error: {e}")
            raise
    
    async def delete_user(self, user_id: str) -> bool:
        """Delete user through SystemManager's AuthManager."""
        if not self.system_manager or not self.system_manager.auth_manager:
            return False
        
        try:
            success = await self.system_manager.auth_manager.delete_user(user_id)
            return success
        except Exception as e:
            logger.error(f"Delete user error: {e}")
            return False
    
    async def activate_user(self, user_id: str) -> Dict[str, Any]:
        """Activate user through SystemManager's AuthManager."""
        if not self.system_manager or not self.system_manager.auth_manager:
            raise SystemError(
                message="AuthManager not configured",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED
            )
        
        try:
            user = await self.system_manager.auth_manager.activate_user(user_id)
            return user
        except Exception as e:
            logger.error(f"Activate user error: {e}")
            raise
    
    async def deactivate_user(self, user_id: str) -> Dict[str, Any]:
        """Deactivate user through SystemManager's AuthManager."""
        if not self.system_manager or not self.system_manager.auth_manager:
            raise SystemError(
                message="AuthManager not configured",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED
            )
        
        try:
            user = await self.system_manager.auth_manager.deactivate_user(user_id)
            return user
        except Exception as e:
            logger.error(f"Deactivate user error: {e}")
            raise
    
    async def search_users(self, query: str, field: str = "username") -> List[Dict[str, Any]]:
        """Search users through SystemManager's AuthManager."""
        if not self.system_manager or not self.system_manager.auth_manager:
            return []
        
        try:
            users = await self.system_manager.auth_manager.search_users(query, field)
            return users
        except Exception as e:
            logger.error(f"Search users error: {e}")
            return []
    
    async def change_password(self, user_id: str, old_password: str, new_password: str) -> bool:
        """Change password through SystemManager's AuthManager."""
        if not self.system_manager or not self.system_manager.auth_manager:
            return False
        
        try:
            success = await self.system_manager.auth_manager.change_password(
                user_id, old_password, new_password
            )
            return success
        except Exception as e:
            logger.error(f"Change password error: {e}")
            return False
    
    async def request_password_reset(self, email: str) -> Dict[str, Any]:
        """Request password reset through SystemManager's AuthManager."""
        if not self.system_manager or not self.system_manager.auth_manager:
            raise SystemError(
                message="AuthManager not configured",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED
            )
        
        try:
            result = await self.system_manager.auth_manager.request_password_reset(email)
            return result
        except Exception as e:
            logger.error(f"Request password reset error: {e}")
            raise
    
    async def reset_password(self, token: str, new_password: str) -> bool:
        """Reset password through SystemManager's AuthManager."""
        if not self.system_manager or not self.system_manager.auth_manager:
            return False
        
        try:
            success = await self.system_manager.auth_manager.reset_password(token, new_password)
            return success
        except Exception as e:
            logger.error(f"Reset password error: {e}")
            return False
    
    async def get_sessions(self, user_id: str) -> List[Dict[str, Any]]:
        """Get active sessions through SystemManager's AuthManager."""
        if not self.system_manager or not self.system_manager.auth_manager:
            return []
        
        try:
            sessions = await self.system_manager.auth_manager.get_active_sessions(user_id)
            return sessions
        except Exception as e:
            logger.error(f"Get sessions error: {e}")
            return []
    
    async def revoke_session(self, user_id: str, session_id: str) -> bool:
        """Revoke session through SystemManager's AuthManager."""
        if not self.system_manager or not self.system_manager.auth_manager:
            return False
        
        try:
            success = await self.system_manager.auth_manager.revoke_session(user_id, session_id)
            return success
        except Exception as e:
            logger.error(f"Revoke session error: {e}")
            return False
    
    async def revoke_all_sessions(self, user_id: str) -> int:
        """Revoke all sessions through SystemManager's AuthManager."""
        if not self.system_manager or not self.system_manager.auth_manager:
            return 0
        
        try:
            count = await self.system_manager.auth_manager.revoke_all_user_sessions(user_id)
            return count
        except Exception as e:
            logger.error(f"Revoke all sessions error: {e}")
            return 0
    
    async def get_devices(self, user_id: str) -> List[Dict[str, Any]]:
        """Get user devices through SystemManager's AuthManager."""
        if not self.system_manager or not self.system_manager.auth_manager:
            return []
        
        try:
            devices = await self.system_manager.auth_manager.get_user_devices(user_id)
            return devices
        except Exception as e:
            logger.error(f"Get devices error: {e}")
            return []
    
    async def trust_device(self, user_id: str, fingerprint: str, trust_days: int = 30) -> Dict[str, Any]:
        """Trust device through SystemManager's AuthManager."""
        if not self.system_manager or not self.system_manager.auth_manager:
            raise SystemError(
                message="AuthManager not configured",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED
            )
        
        try:
            result = await self.system_manager.auth_manager.trust_device(
                user_id, fingerprint, trust_days
            )
            return result
        except Exception as e:
            logger.error(f"Trust device error: {e}")
            raise
    
    async def get_auth_history(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get auth history through SystemManager's AuthManager."""
        if not self.system_manager or not self.system_manager.auth_manager:
            return []
        
        try:
            history = await self.system_manager.auth_manager.get_auth_history(user_id, limit)
            return history
        except Exception as e:
            logger.error(f"Get auth history error: {e}")
            return []
    
    async def send_verification_email(self, user_id: str) -> Dict[str, Any]:
        """Send verification email through SystemManager's AuthManager."""
        if not self.system_manager or not self.system_manager.auth_manager:
            raise SystemError(
                message="AuthManager not configured",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED
            )
        
        try:
            result = await self.system_manager.auth_manager.send_verification_email(user_id)
            return result
        except Exception as e:
            logger.error(f"Send verification error: {e}")
            raise
    
    async def verify_email(self, token: str) -> bool:
        """Verify email through SystemManager's AuthManager."""
        if not self.system_manager or not self.system_manager.auth_manager:
            return False
        
        try:
            success = await self.system_manager.auth_manager.verify_email(token)
            return success
        except Exception as e:
            logger.error(f"Verify email error: {e}")
            return False
    
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
            # Get session for authorization
            session_id = await self._get_or_create_session()
            
            # First get the task to verify ownership/access
            task = await self.persistence.get_task(task_id)
            if not task:
                raise AuthorizationError(f"Task {task_id} not found")
            
            # Verify user has access to the task's workflow
            workflow = await self.system_manager.get_workflow_authenticated(task.workflow_id, session_id)
            if not workflow:
                raise AuthorizationError(f"Access denied to workflow {task.workflow_id}")
            
            # Use LogCollector from SystemManager if available
            if self.system_manager and hasattr(self.system_manager, 'log_collector') and self.system_manager.log_collector:
                try:
                    logs = await self.system_manager.log_collector.get_logs(
                        task_id=task_id,
                        limit=limit
                    )
                    return logs
                except Exception as e:
                    logger.debug(f"Could not get logs from LogCollector: {e}")
                    
        except AuthorizationError:
            # Re-raise authorization errors
            raise
        except Exception as e:
            logger.error(f"Error getting task logs: {e}")
            raise AuthorizationError("Failed to access task logs")
        
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
            # Get session for authorization
            session_id = await self._get_or_create_session()
            
            # For global logs, require admin privileges or return user's workflow logs only
            if self.user_context and self.user_context.get("role") != "admin" and not self.user_context.get("is_superuser"):
                # Non-admin users can only see logs from their own workflows
                # Get user's workflows first
                user_workflows = await self.list_workflows()
                if not user_workflows:
                    return []
                
                # Collect logs from all user's workflows
                all_logs = []
                for workflow in user_workflows[:10]:  # Limit to prevent abuse
                    try:
                        workflow_logs = await self.system_manager.log_collector.get_logs(
                            workflow_id=workflow.get('id'),
                            limit=min(limit // len(user_workflows), 50),
                            since=start_time
                        )
                        all_logs.extend(workflow_logs)
                    except Exception:
                        continue
                
                logs = sorted(all_logs, key=lambda x: x.get('timestamp', ''), reverse=True)[:limit]
            else:
                # Admin users can see global logs
                if self.system_manager and hasattr(self.system_manager, 'log_collector') and self.system_manager.log_collector:
                    try:
                        logs = await self.system_manager.log_collector.get_logs(
                            limit=limit,
                            since=start_time
                        )
                    except Exception as e:
                        logger.debug(f"Could not get logs from LogCollector: {e}")
                        logs = []
                else:
                    logs = []
            
            # Client-side filtering for level and source
            if level:
                logs = [log for log in logs if log.get('level') == level]
            if source:
                logs = [log for log in logs if log.get('source') == source]
                
            # Apply offset if needed
            if offset:
                logs = logs[offset:]
                
            return logs
            
        except AuthorizationError:
            # Re-raise authorization errors
            raise
        except Exception as e:
            logger.error(f"Error getting logs: {e}")
            return []
        
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
            # Get session for authorization
            session_id = await self._get_or_create_session()
            
            # For log search, apply same authorization as get_logs
            if self.user_context and self.user_context.get("role") != "admin" and not self.user_context.get("is_superuser"):
                # Non-admin users can only search logs from their own workflows
                user_workflows = await self.list_workflows()
                if not user_workflows:
                    return []
                
                all_logs = []
                for workflow in user_workflows[:5]:  # Limit for search
                    try:
                        workflow_logs = await self.system_manager.log_collector.get_logs(
                            workflow_id=workflow.get('id'),
                            limit=min(limit // len(user_workflows), 20)
                        )
                        all_logs.extend(workflow_logs)
                    except Exception:
                        continue
                
                logs = all_logs
            else:
                # Admin users can search all logs
                if self.system_manager and hasattr(self.system_manager, 'log_collector') and self.system_manager.log_collector:
                    try:
                        logs = await self.system_manager.log_collector.get_logs(
                            limit=limit
                        )
                    except Exception as e:
                        logger.debug(f"Could not query logs from LogCollector: {e}")
                        logs = []
                else:
                    logs = []
            
            # Client-side filtering by query string
            if query:
                query_lower = query.lower()
                logs = [log for log in logs if query_lower in log.get('message', '').lower()]
                
            # Apply offset if needed
            if offset:
                logs = logs[offset:]
                
            return logs
            
        except AuthorizationError:
            # Re-raise authorization errors
            raise
        except Exception as e:
            logger.error(f"Error querying logs: {e}")
            return []
        
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
            # Use LogCollector from SystemManager if available
            if self.system_manager and hasattr(self.system_manager, 'log_collector') and self.system_manager.log_collector:
                logs = await self.system_manager.log_collector.get_logs(
                    workflow_id=workflow_id,
                    limit=1000  # Large limit for workflow logs
                )
                    
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