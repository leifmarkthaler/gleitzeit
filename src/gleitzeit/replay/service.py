"""
ReplayService - High-level replay service for client integration.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
import logging
import asyncio

from .manager import ReplayManager, ReplayMode, ReplayOptions

logger = logging.getLogger(__name__)


class ReplayService:
    """High-level replay service for client integration"""
    
    def __init__(self, client):
        """
        Initialize replay service.
        
        Args:
            client: GleitzeitClient instance
        """
        self.client = client
        
        # Get persistence and event store from adapter
        persistence = None
        event_store = None
        
        if hasattr(client, '_adapter'):
            if hasattr(client._adapter, 'persistence'):
                persistence = client._adapter.persistence
            if hasattr(client._adapter, 'event_store'):
                event_store = client._adapter.event_store
        
        if not persistence:
            raise RuntimeError("Replay service requires persistence backend")
        
        self.replay_manager = ReplayManager(
            persistence=persistence,
            event_store=event_store
        )
        logger.info("ReplayService initialized")
    
    async def _get_user_context(self) -> Dict:
        """Get user context from client if available, fallback to basic user"""
        try:
            if hasattr(self.client, '_adapter') and hasattr(self.client._adapter, 'get_current_user'):
                get_user_func = self.client._adapter.get_current_user
                if asyncio.iscoroutinefunction(get_user_func):
                    user_context = await get_user_func()
                else:
                    user_context = get_user_func()
                
                # If we got a valid user context, return it
                if user_context and user_context.get("id"):
                    return user_context
        except:
            pass
        
        # Always fallback to basic user (for seamless pip install experience)
        return {
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
    
    async def replay(
        self,
        workflow_id: str,
        mode: str = "re_execute",
        user_context: Optional[Dict] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Simple replay interface.
        
        Args:
            workflow_id: ID of workflow to replay
            mode: Replay mode as string
            user_context: Optional user context (auto-detected if not provided)
            **kwargs: Additional options for replay
        
        Returns:
            Replay result dictionary
        """
        try:
            replay_mode = ReplayMode(mode)
        except ValueError:
            raise ValueError(f"Invalid replay mode: {mode}. "
                           f"Valid modes: {[m.value for m in ReplayMode]}")
        
        # Get user context if not provided
        if user_context is None:
            user_context = await self._get_user_context()
        
        options = ReplayOptions(mode=replay_mode, **{k: v for k, v in kwargs.items() if k != 'user_context'})
        result = await self.replay_manager.replay_workflow(workflow_id, options, user_context)
        
        # If mode returns a workflow for submission, submit it
        if "workflow" in result and result.get("status") in [
            "ready_for_submission", "ready_for_debug"
        ]:
            workflow = result["workflow"]
            submission_result = await self.client.submit_workflow(workflow)
            result["submission_result"] = submission_result
            result["status"] = "submitted"
            logger.info(f"Automatically submitted replay workflow {workflow.id}")
        
        return result
    
    async def list_replayable_workflows(
        self,
        status: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
        user_context: Optional[Dict] = None
    ) -> List[Dict[str, Any]]:
        """
        List workflows available for replay.
        
        Args:
            status: Filter by workflow status
            since: Filter by creation time
            limit: Maximum number of results
            user_context: Optional user context (auto-detected if not provided)
        
        Returns:
            List of replayable workflow summaries
        """
        if not hasattr(self.client._adapter, 'persistence'):
            return []
        
        # Get user context if not provided
        if user_context is None:
            user_context = await self._get_user_context()
        
        persistence = self.client._adapter.persistence
        
        # Get workflows from persistence
        workflows_data = await persistence.list_workflows(
            status=status,
            limit=limit
        )
        
        workflows = workflows_data.get("workflows", [])
        
        replayable = []
        for wf_summary in workflows:
            # Skip if created before 'since' time
            if since and "created_at" in wf_summary:
                try:
                    created_at = datetime.fromisoformat(wf_summary["created_at"])
                    if created_at < since:
                        continue
                except:
                    pass
            
            # Check if user can access this workflow
            try:
                await self.replay_manager._check_workflow_access(wf_summary["id"], user_context, "read")
            except PermissionError:
                # User doesn't have access to this workflow
                continue
            except Exception as e:
                logger.warning(f"Error checking access to workflow {wf_summary['id']}: {e}")
                continue
            
            # Get full workflow to check replayability
            try:
                full_wf = await persistence.get_workflow(wf_summary["id"])
                if full_wf and full_wf.tasks:
                    replayable.append({
                        "id": wf_summary["id"],
                        "name": wf_summary.get("name", "Unknown"),
                        "status": wf_summary.get("status", "unknown"),
                        "task_count": len(full_wf.tasks),
                        "created_at": wf_summary.get("created_at"),
                        "description": getattr(full_wf, 'description', None),
                        "replayable": True,
                        "replay_modes": ["re_execute", "template", "restore"]
                    })
                    
                    # Add continue mode if workflow failed or interrupted
                    if wf_summary.get("status") in ["failed", "running", "interrupted"]:
                        replayable[-1]["replay_modes"].append("continue")
            except Exception as e:
                logger.warning(f"Could not check workflow {wf_summary['id']}: {e}")
        
        return replayable
    
    async def get_replay_history(
        self,
        original_workflow_id: str,
        user_context: Optional[Dict] = None
    ) -> List[Dict[str, Any]]:
        """
        Get history of replays for a workflow.
        
        Args:
            original_workflow_id: Original workflow ID
            user_context: Optional user context (auto-detected if not provided)
        
        Returns:
            List of replay records
        """
        # Get user context if not provided
        if user_context is None:
            user_context = await self._get_user_context()
        
        # Check access to original workflow first
        try:
            await self.replay_manager._check_workflow_access(original_workflow_id, user_context, "read")
        except PermissionError:
            logger.warning(f"User denied access to replay history for workflow {original_workflow_id}")
            return []
        
        # Look for workflows with replay patterns in their IDs
        all_workflows = await self.client._adapter.persistence.list_workflows(limit=1000)
        
        replay_history = []
        for wf in all_workflows.get("workflows", []):
            wf_id = wf.get("id", "")
            # Check if this is a replay of the original
            if (original_workflow_id in wf_id and 
                any(pattern in wf_id for pattern in ["_replay_", "_continue_", "_debug_", "_from_template"])):
                
                # Check access to this replay workflow
                try:
                    await self.replay_manager._check_workflow_access(wf_id, user_context, "read")
                except PermissionError:
                    # User doesn't have access to this replay
                    continue
                except Exception:
                    # Skip if we can't check access
                    continue
                
                # Determine replay type
                if "_replay_" in wf_id:
                    replay_type = "re_execute"
                elif "_continue_" in wf_id:
                    replay_type = "continue"
                elif "_debug_" in wf_id:
                    replay_type = "debug"
                elif "_from_template" in wf_id:
                    replay_type = "template"
                else:
                    replay_type = "unknown"
                
                replay_history.append({
                    "replay_id": wf_id,
                    "original_id": original_workflow_id,
                    "replay_type": replay_type,
                    "status": wf.get("status"),
                    "created_at": wf.get("created_at"),
                    "task_count": wf.get("tasks_total", 0)
                })
        
        # Sort by creation time
        replay_history.sort(
            key=lambda x: x.get("created_at", ""),
            reverse=True
        )
        
        return replay_history