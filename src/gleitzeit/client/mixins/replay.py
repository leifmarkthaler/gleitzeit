"""
ReplayMixin - Adds replay capabilities to GleitzeitClient.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
import logging

from gleitzeit.core.errors import SystemError

logger = logging.getLogger(__name__)


class ReplayMixin:
    """Adds replay capabilities to GleitzeitClient"""
    
    def _get_replay_service(self):
        """Get or create replay service instance"""
        if not hasattr(self, '_replay_service'):
            from gleitzeit.replay.service import ReplayService
            self._replay_service = ReplayService(self)
        return self._replay_service
    
    async def replay_workflow(
        self,
        workflow_id: str,
        mode: str = "re_execute",
        **options
    ) -> Dict[str, Any]:
        """
        Replay a workflow.
        
        Args:
            workflow_id: ID of workflow to replay
            mode: Replay mode (re_execute, restore, template, continue, debug)
            **options: Additional options for replay
        
        Returns:
            Replay result with new workflow ID and status
        
        Examples:
            # Re-execute workflow
            result = await client.replay_workflow("wf_123")
            
            # Use as template with modifications
            result = await client.replay_workflow(
                "daily_etl",
                mode="template",
                modifications={
                    "name": "Daily ETL - Modified",
                    "tasks": [{"id": "fetch", "params": {"date": "2025-08-30"}}]
                }
            )
            
            # Restore state at specific time
            result = await client.replay_workflow(
                "wf_456",
                mode="restore", 
                target_time=datetime(2025, 8, 29, 10, 30)
            )
        """
        if not self._initialized:
            raise SystemError("Client not initialized")
        
        try:
            service = self._get_replay_service()
            return await service.replay(workflow_id, mode, **options)
        except Exception as e:
            logger.error(f"Replay failed for workflow {workflow_id}: {e}")
            raise
    
    async def continue_workflow(
        self,
        workflow_id: str,
        skip_completed: bool = True
    ) -> Dict[str, Any]:
        """
        Continue a failed or interrupted workflow.
        
        Args:
            workflow_id: ID of workflow to continue
            skip_completed: Skip already completed tasks
        
        Returns:
            Continuation result
        
        Example:
            result = await client.continue_workflow("failed_wf_123")
        """
        return await self.replay_workflow(
            workflow_id,
            mode="continue",
            skip_completed=skip_completed
        )
    
    async def debug_workflow(
        self,
        workflow_id: str,
        breakpoints: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Debug replay a workflow with breakpoints.
        
        Args:
            workflow_id: ID of workflow to debug
            breakpoints: List of task IDs to pause at
        
        Returns:
            Debug replay result
        
        Example:
            result = await client.debug_workflow(
                "wf_789",
                breakpoints=["task2", "task5"]
            )
        """
        return await self.replay_workflow(
            workflow_id,
            mode="debug",
            debug_breakpoints=breakpoints or []
        )
    
    async def use_workflow_as_template(
        self,
        workflow_id: str,
        modifications: Dict[str, Any],
        new_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Use existing workflow as template.
        
        Args:
            workflow_id: ID of workflow to use as template
            modifications: Modifications to apply
            new_name: New name for the workflow
        
        Returns:
            Template replay result
        
        Example:
            result = await client.use_workflow_as_template(
                "daily_etl",
                modifications={
                    "name": "Weekly ETL",
                    "tasks": [
                        {"id": "fetch", "params": {"frequency": "weekly"}}
                    ]
                }
            )
        """
        if new_name:
            modifications["name"] = new_name
        
        return await self.replay_workflow(
            workflow_id,
            mode="template",
            modifications=modifications
        )
    
    async def restore_workflow_state(
        self,
        workflow_id: str,
        target_time: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Restore workflow state (without re-execution).
        
        Args:
            workflow_id: ID of workflow to restore
            target_time: Point in time to restore to (default: latest)
        
        Returns:
            Restored state information
        
        Example:
            # Restore latest state
            state = await client.restore_workflow_state("wf_123")
            
            # Restore state at specific time
            state = await client.restore_workflow_state(
                "wf_123",
                target_time=datetime(2025, 8, 29, 10, 30)
            )
        """
        return await self.replay_workflow(
            workflow_id,
            mode="restore",
            target_time=target_time
        )
    
    async def list_replayable_workflows(
        self,
        status: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        List workflows available for replay.
        
        Args:
            status: Filter by workflow status
            since: Filter workflows created after this time
            limit: Maximum number of results
        
        Returns:
            List of replayable workflow summaries
        
        Example:
            # List all replayable workflows
            workflows = await client.list_replayable_workflows()
            
            # List failed workflows only
            failed = await client.list_replayable_workflows(status="failed")
            
            # List recent workflows
            recent = await client.list_replayable_workflows(
                since=datetime.now() - timedelta(days=7)
            )
        """
        if not self._initialized:
            raise SystemError("Client not initialized")
        
        service = self._get_replay_service()
        return await service.list_replayable_workflows(status, since, limit)
    
    async def get_replay_history(
        self,
        workflow_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get replay history for a workflow.
        
        Args:
            workflow_id: Original workflow ID
        
        Returns:
            List of replay records
        
        Example:
            history = await client.get_replay_history("original_wf_123")
        """
        if not self._initialized:
            raise SystemError("Client not initialized")
        
        service = self._get_replay_service()
        return await service.get_replay_history(workflow_id)