"""
ReplayManager - Core replay functionality for Gleitzeit workflows.
"""

from enum import Enum
from typing import Dict, List, Optional, Any, Set
from datetime import datetime
import logging
import os

logger = logging.getLogger(__name__)


class ReplayMode(Enum):
    """Replay execution modes"""
    RE_EXECUTE = "re_execute"       # Run workflow again
    RESTORE = "restore"              # Load previous state
    TEMPLATE = "template"            # Use as template with modifications
    CONTINUE = "continue"            # Continue from failure point
    DEBUG = "debug"                  # Step-through execution


class ReplayOptions:
    """Configuration for replay operation"""
    def __init__(
        self,
        mode: ReplayMode = ReplayMode.RE_EXECUTE,
        preserve_ids: bool = False,
        skip_completed: bool = False,
        modifications: Optional[Dict[str, Any]] = None,
        target_time: Optional[datetime] = None,
        debug_breakpoints: Optional[List[str]] = None
    ):
        self.mode = mode
        self.preserve_ids = preserve_ids
        self.skip_completed = skip_completed
        self.modifications = modifications or {}
        self.target_time = target_time
        self.debug_breakpoints = debug_breakpoints or []


class ReplayManager:
    """Manages workflow replay operations"""
    
    def __init__(self, persistence, event_store=None):
        """
        Initialize ReplayManager.
        
        Args:
            persistence: Persistence backend for workflows/tasks
            event_store: Optional event store for event-based replay
        """
        self.persistence = persistence
        self.event_store = event_store
        logger.info("ReplayManager initialized")
    
    def _check_auth_enabled(self) -> bool:
        """Check if authentication is enabled - always enabled with basic user as minimum"""
        return True
    
    def _check_ownership_required(self) -> bool:
        """Check if ownership filtering is enabled"""
        return os.getenv("GLEITZEIT_AUTH_OWNERSHIP_FILTER", "true").lower() == "true"
    
    async def _check_workflow_access(self, workflow_id: str, user_context: Optional[Dict] = None, 
                                   operation: str = "read") -> bool:
        """
        Check if user has access to workflow for given operation.
        
        Args:
            workflow_id: Workflow ID to check
            user_context: User context with id, roles, permissions
            operation: Operation type (read, write, replay)
            
        Returns:
            True if access allowed, False otherwise
            
        Raises:
            PermissionError: If access denied with details
        """
        # If no user context, create basic user context (for backward compatibility)
        if not user_context:
            user_context = {
                "id": "basic_user",
                "email": "basic@gleitzeit.local",
                "permissions": [
                    "workflows:read", "workflows:write", "workflows:replay",
                    "tasks:read", "tasks:write",
                    "logs:read", "logs:write", 
                    "events:read", "events:write",
                    "system:read", "system:debug"
                ],
                "is_superuser": False
            }
        
        # Get workflow to check ownership
        try:
            workflow = await self.persistence.get_workflow(workflow_id)
            if not workflow:
                raise PermissionError(f"Workflow {workflow_id} not found")
        except Exception as e:
            logger.error(f"Failed to get workflow {workflow_id}: {e}")
            raise PermissionError(f"Cannot access workflow {workflow_id}")
        
        # Check if user is superuser
        if user_context.get("is_superuser"):
            return True
        
        # Check ownership if enabled
        if self._check_ownership_required():
            # Check workflow metadata first, then root level
            workflow_dict = workflow.to_dict() if hasattr(workflow, 'to_dict') else workflow.__dict__
            metadata = workflow_dict.get("metadata", {})
            owner_id = metadata.get("owner_id") or workflow_dict.get("owner_id")
            
            user_id = str(user_context.get("id", ""))
            
            # If no owner_id is set, allow basic_user to access (for backward compatibility)
            # This ensures workflows created before owner tracking work with basic user
            if not owner_id and user_id == "basic_user":
                logger.debug(f"Allowing basic_user access to workflow {workflow_id} with no owner")
            elif owner_id and str(owner_id) != user_id:
                logger.warning(f"User {user_id} denied {operation} access to workflow {workflow_id} - not owner")
                raise PermissionError(f"You don't have permission to {operation} this workflow")
        
        # Check permissions based on operation
        permissions = user_context.get("permissions", [])
        required_perms = {
            "read": ["workflows:read", "workflows:replay"],
            "write": ["workflows:write", "workflows:replay"], 
            "replay": ["workflows:replay"]
        }
        
        required = required_perms.get(operation, ["workflows:replay"])
        if not any(perm in permissions for perm in required):
            logger.warning(f"User {user_context.get('id')} missing permissions for {operation}: {required}")
            raise PermissionError(f"Missing permission for {operation} operation")
        
        return True
    
    async def replay_workflow(
        self,
        workflow_id: str,
        options: ReplayOptions = None,
        user_context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Main replay entry point.
        
        Args:
            workflow_id: ID of workflow to replay
            options: Replay configuration options
            user_context: User context for authorization
        
        Returns:
            Dict with replay_id, status, and details
        """
        options = options or ReplayOptions()
        logger.info(f"Replaying workflow {workflow_id} with mode {options.mode.value}")
        
        # Check access permissions
        await self._check_workflow_access(workflow_id, user_context, "replay")
        
        # Load workflow from persistence
        workflow = await self.persistence.get_workflow(workflow_id)
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found in persistence")
        
        # Execute based on mode
        if options.mode == ReplayMode.RE_EXECUTE:
            return await self._replay_execute(workflow, options, user_context)
        elif options.mode == ReplayMode.RESTORE:
            return await self._replay_restore(workflow, options, user_context)
        elif options.mode == ReplayMode.TEMPLATE:
            return await self._replay_template(workflow, options, user_context)
        elif options.mode == ReplayMode.CONTINUE:
            return await self._replay_continue(workflow, options, user_context)
        elif options.mode == ReplayMode.DEBUG:
            return await self._replay_debug(workflow, options, user_context)
        else:
            raise ValueError(f"Unknown replay mode: {options.mode}")
    
    def _add_owner_metadata(self, workflow, user_context: Optional[Dict]):
        """Add owner metadata to workflow if user context provided"""
        if user_context and user_context.get("id"):
            workflow.metadata = workflow.metadata or {}
            workflow.metadata["owner_id"] = user_context["id"]
            workflow.metadata["replayed_by"] = user_context.get("email", str(user_context["id"]))
            workflow.metadata["replayed_at"] = datetime.now().isoformat()
    
    async def _replay_execute(self, workflow, options: ReplayOptions, user_context: Optional[Dict] = None) -> Dict[str, Any]:
        """Re-execute the entire workflow"""
        original_id = workflow.id
        
        # Generate new ID unless preserving
        if not options.preserve_ids:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            workflow.id = f"{workflow.id}_replay_{timestamp}"
            
            # Update task IDs to avoid conflicts
            task_id_mapping = {}
            for task in workflow.tasks:
                old_id = task.id
                task.id = f"{task.id}_r{timestamp[:8]}"
                task_id_mapping[old_id] = task.id
            
            # Update dependencies with new IDs
            for task in workflow.tasks:
                if task.dependencies:
                    task.dependencies = [
                        task_id_mapping.get(dep, dep) 
                        for dep in task.dependencies
                    ]
        
        # Apply any modifications
        workflow = self._apply_modifications(workflow, options.modifications)
        
        # Add owner metadata
        self._add_owner_metadata(workflow, user_context)
        
        # Reset task states for re-execution
        for task in workflow.tasks:
            task.status = "pending"
            if hasattr(task, 'started_at'):
                task.started_at = None
            if hasattr(task, 'completed_at'):
                task.completed_at = None
            if hasattr(task, 'error_message'):
                task.error_message = None
            # Only set retry_attempts if it exists
            if hasattr(task, 'retry_attempts'):
                task.retry_attempts = 0
        
        logger.info(f"Re-executing workflow as {workflow.id}")
        
        return {
            "replay_id": workflow.id,
            "original_id": original_id,
            "mode": "re_execute",
            "status": "ready_for_submission",
            "workflow": workflow,  # Return modified workflow for submission
            "message": "Workflow prepared for re-execution. Submit using client.submit_workflow()"
        }
    
    async def _replay_restore(self, workflow, options: ReplayOptions, user_context: Optional[Dict] = None) -> Dict[str, Any]:
        """Restore workflow state at a point in time"""
        logger.info(f"Restoring state for workflow {workflow.id}")
        
        # Get all tasks and results
        tasks = await self.persistence.get_tasks_by_workflow(workflow.id)
        
        results = {}
        task_states = {}
        for task in tasks:
            task_states[task.id] = {
                "status": task.status,
                "started_at": getattr(task, 'started_at', None),
                "completed_at": getattr(task, 'completed_at', None),
                "error_message": getattr(task, 'error_message', None)
            }
            
            task_result = await self.persistence.get_task_result(task.id)
            if task_result:
                results[task.id] = {
                    "result": task_result.result,
                    "error": task_result.error,
                    "execution_time": task_result.execution_time
                }
        
        # If target_time specified, filter to that point
        if options.target_time and self.event_store:
            events = await self.event_store.get_events(
                workflow_id=workflow.id,
                until=options.target_time
            )
            # Filter states and results to target time
            task_states, results = self._filter_by_time(
                task_states, results, events, options.target_time
            )
            logger.info(f"Restored to point in time: {options.target_time}")
        
        return {
            "replay_id": workflow.id,
            "mode": "restore",
            "status": "restored",
            "workflow": workflow.to_dict() if hasattr(workflow, 'to_dict') else str(workflow),
            "task_states": task_states,
            "task_results": results,
            "restored_at": options.target_time.isoformat() if options.target_time else "latest",
            "message": "Workflow state restored successfully"
        }
    
    async def _replay_template(self, workflow, options: ReplayOptions, user_context: Optional[Dict] = None) -> Dict[str, Any]:
        """Use workflow as template with modifications"""
        original_id = workflow.id
        
        # Apply template modifications
        workflow.id = options.modifications.get(
            "workflow_id", 
            f"{workflow.id}_from_template"
        )
        workflow.name = options.modifications.get(
            "name", 
            f"{workflow.name} (From Template)"
        )
        
        if "description" in options.modifications:
            workflow.description = options.modifications["description"]
        
        # Apply task-level modifications
        if "tasks" in options.modifications:
            for task_mod in options.modifications["tasks"]:
                task = next(
                    (t for t in workflow.tasks if t.id == task_mod.get("id")),
                    None
                )
                if task:
                    for key, value in task_mod.items():
                        if key != "id" and hasattr(task, key):
                            setattr(task, key, value)
                            logger.debug(f"Modified task {task.id}: {key}={value}")
        
        # Add owner metadata
        self._add_owner_metadata(workflow, user_context)
        
        # Reset all task states
        for task in workflow.tasks:
            task.status = "pending"
            if hasattr(task, 'started_at'):
                task.started_at = None
            if hasattr(task, 'completed_at'):
                task.completed_at = None
            if hasattr(task, 'error_message'):
                task.error_message = None
            if hasattr(task, 'retry_attempts'):
                task.retry_attempts = 0
        
        logger.info(f"Created workflow {workflow.id} from template {original_id}")
        
        return {
            "replay_id": workflow.id,
            "template_from": original_id,
            "mode": "template",
            "status": "ready_for_submission",
            "workflow": workflow,
            "modifications_applied": options.modifications,
            "message": "Template workflow created. Submit using client.submit_workflow()"
        }
    
    async def _replay_continue(self, workflow, options: ReplayOptions, user_context: Optional[Dict] = None) -> Dict[str, Any]:
        """Continue workflow from failure/interruption point"""
        logger.info(f"Continuing workflow {workflow.id} from interruption")
        
        # Get current task states
        tasks = await self.persistence.get_tasks_by_workflow(workflow.id)
        
        completed_ids = set()
        failed_ids = set()
        pending_ids = set()
        
        for task in tasks:
            if task.status in ["completed", "skipped"]:
                completed_ids.add(task.id)
            elif task.status == "failed":
                failed_ids.add(task.id)
            else:
                pending_ids.add(task.id)
        
        # Prepare workflow for continuation
        original_id = workflow.id
        workflow.id = f"{workflow.id}_continue_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Add owner metadata
        self._add_owner_metadata(workflow, user_context)
        
        tasks_to_run = []
        tasks_to_skip = []
        
        for task in workflow.tasks:
            if task.id in completed_ids and options.skip_completed:
                tasks_to_skip.append(task.id)
                # Mark as already completed
                task.status = "skipped"
                task.metadata = task.metadata or {}
                task.metadata["skipped_in_replay"] = True
            else:
                tasks_to_run.append(task.id)
                # Reset status for re-execution
                task.status = "pending"
                if hasattr(task, 'retry_attempts'):
                    task.retry_attempts = 0
                if task.id in failed_ids:
                    # Clear error state for retry
                    if hasattr(task, 'error_message'):
                        task.error_message = None
                    task.metadata = task.metadata or {}
                    task.metadata["retried_in_replay"] = True
        
        logger.info(f"Continuing with {len(tasks_to_run)} tasks, skipping {len(tasks_to_skip)}")
        
        return {
            "replay_id": workflow.id,
            "original_id": original_id,
            "mode": "continue",
            "status": "ready_for_submission",
            "workflow": workflow,
            "tasks_to_run": tasks_to_run,
            "tasks_to_skip": tasks_to_skip,
            "completed_tasks": list(completed_ids),
            "failed_tasks": list(failed_ids),
            "message": f"Workflow prepared to continue. {len(tasks_to_skip)} tasks will be skipped."
        }
    
    async def _replay_debug(self, workflow, options: ReplayOptions, user_context: Optional[Dict] = None) -> Dict[str, Any]:
        """Debug replay with breakpoints and step-through"""
        logger.info(f"Setting up debug replay for workflow {workflow.id}")
        
        original_id = workflow.id
        workflow.id = f"{workflow.id}_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Add debug metadata
        workflow.metadata = workflow.metadata or {}
        workflow.metadata["debug_mode"] = True
        workflow.metadata["debug_breakpoints"] = options.debug_breakpoints
        
        # Add owner metadata
        self._add_owner_metadata(workflow, user_context)
        
        # Configure tasks for debugging
        for task in workflow.tasks:
            # Reset state
            task.status = "pending"
            if hasattr(task, 'started_at'):
                task.started_at = None
            if hasattr(task, 'completed_at'):
                task.completed_at = None
            if hasattr(task, 'error_message'):
                task.error_message = None
            if hasattr(task, 'retry_attempts'):
                task.retry_attempts = 0
            
            # Add debug metadata
            task.metadata = task.metadata or {}
            task.metadata["debug_mode"] = True
            
            if task.id in options.debug_breakpoints:
                task.metadata["breakpoint"] = True
                task.metadata["pause_before_execution"] = True
                logger.debug(f"Breakpoint set on task {task.id}")
        
        return {
            "replay_id": workflow.id,
            "original_id": original_id,
            "mode": "debug",
            "status": "ready_for_debug",
            "workflow": workflow,
            "breakpoints": options.debug_breakpoints,
            "message": f"Debug workflow prepared with {len(options.debug_breakpoints)} breakpoints"
        }
    
    def _apply_modifications(self, workflow, modifications: Dict[str, Any]):
        """Apply modifications to workflow"""
        if "name" in modifications:
            workflow.name = modifications["name"]
        
        if "description" in modifications:
            workflow.description = modifications["description"]
        
        if "metadata" in modifications:
            workflow.metadata = workflow.metadata or {}
            workflow.metadata.update(modifications["metadata"])
        
        if "tasks" in modifications:
            for task_mod in modifications["tasks"]:
                task = next(
                    (t for t in workflow.tasks if t.id == task_mod.get("id")),
                    None
                )
                if task:
                    for key, value in task_mod.items():
                        if key != "id" and hasattr(task, key):
                            setattr(task, key, value)
        
        return workflow
    
    def _filter_by_time(
        self,
        task_states: Dict,
        results: Dict,
        events: List[Dict],
        target_time: datetime
    ) -> tuple:
        """Filter states and results to specific point in time"""
        filtered_states = {}
        filtered_results = {}
        
        for event in events:
            event_time = datetime.fromisoformat(event["timestamp"])
            if event_time <= target_time:
                task_id = event.get("task_id")
                if task_id:
                    # Update state based on event
                    if "task:completed" in event.get("event_type", ""):
                        if task_id in task_states:
                            filtered_states[task_id] = task_states[task_id]
                        if task_id in results:
                            filtered_results[task_id] = results[task_id]
                    elif "task:started" in event.get("event_type", ""):
                        if task_id in task_states:
                            filtered_states[task_id] = {
                                "status": "executing",
                                "started_at": event_time,
                                "completed_at": None,
                                "error_message": None
                            }
        
        return filtered_states, filtered_results