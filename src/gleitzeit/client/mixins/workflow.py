"""
Workflow operations mixin for Gleitzeit client.
"""

from typing import Any, Dict, List, Optional
import yaml
import json
from pathlib import Path
from gleitzeit.core.models import Workflow, Task


class WorkflowMixin:
    """Mixin providing workflow-related operations."""
    
    async def submit_workflow(self, workflow: Workflow) -> Dict[str, Any]:
        """
        Submit a workflow for execution.
        
        Args:
            workflow: Workflow object to submit
            
        Returns:
            Dictionary with workflow submission result
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.submit_workflow(workflow)
    
    async def run_workflow(self, workflow_file: str, watch: bool = False) -> Dict[str, Any]:
        """
        Run a workflow from a YAML/JSON file.
        
        Args:
            workflow_file: Path to workflow definition file
            watch: Whether to watch for completion
            
        Returns:
            Workflow execution result
        """
        # Load workflow from file
        file_path = Path(workflow_file)
        if not file_path.exists():
            raise FileNotFoundError(f"Workflow file not found: {workflow_file}")
        
        with open(file_path, 'r') as f:
            if file_path.suffix in ['.yaml', '.yml']:
                workflow_dict = yaml.safe_load(f)
            else:
                workflow_dict = json.load(f)
        
        # Create workflow object
        workflow = Workflow(**workflow_dict)
        
        # Submit workflow
        result = await self.submit_workflow(workflow)
        
        if watch and 'workflow_id' in result:
            # Wait for completion
            return await self.wait_for_workflow(result['workflow_id'])
        
        return result
    
    async def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """
        Get workflow by ID.
        
        Args:
            workflow_id: Workflow ID
            
        Returns:
            Workflow object or None if not found
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.get_workflow(workflow_id)
    
    async def list_workflows(self, status: Optional[str] = None,
                           limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """
        List workflows with optional filters.
        
        Args:
            status: Filter by status (pending, running, completed, failed)
            limit: Maximum number of workflows to return
            offset: Offset for pagination
            
        Returns:
            Dictionary with workflows list and pagination info
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.list_workflows(status, limit, offset)
    
    async def cancel_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """
        Cancel a workflow.
        
        Args:
            workflow_id: ID of workflow to cancel
            
        Returns:
            Cancellation result
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.cancel_workflow(workflow_id)
    
    async def pause_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """
        Pause a running workflow.
        
        Args:
            workflow_id: ID of workflow to pause
            
        Returns:
            Pause result
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.pause_workflow(workflow_id)
    
    async def resume_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """
        Resume a paused workflow.
        
        Args:
            workflow_id: ID of workflow to resume
            
        Returns:
            Resume result
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.resume_workflow(workflow_id)
    
    async def delete_workflow(self, workflow_id: str) -> bool:
        """
        Delete a workflow.
        
        Args:
            workflow_id: ID of workflow to delete
            
        Returns:
            True if deleted successfully
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.delete_workflow(workflow_id)
    
    async def get_workflow_tasks(self, workflow_id: str) -> List[Task]:
        """
        Get all tasks for a workflow.
        
        Args:
            workflow_id: Workflow ID
            
        Returns:
            List of Task objects
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.get_workflow_tasks(workflow_id)
    
    async def wait_for_workflow(self, workflow_id: str, 
                               timeout: float = 300.0,
                               poll_interval: float = 2.0) -> Dict[str, Any]:
        """
        Wait for workflow to complete.
        
        Args:
            workflow_id: Workflow ID to wait for
            timeout: Maximum time to wait in seconds
            poll_interval: Polling interval in seconds
            
        Returns:
            Final workflow state
        """
        import asyncio
        import time
        
        start_time = time.time()
        
        while True:
            workflow = await self.get_workflow(workflow_id)
            
            if not workflow:
                raise ValueError(f"Workflow {workflow_id} not found")
            
            if workflow.status in ['completed', 'failed', 'cancelled']:
                return workflow.dict() if hasattr(workflow, 'dict') else workflow
            
            if time.time() - start_time > timeout:
                raise TimeoutError(f"Workflow {workflow_id} did not complete within {timeout} seconds")
            
            await asyncio.sleep(poll_interval)
    
    async def clone_workflow(self, workflow_id: str, 
                           new_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Clone an existing workflow.
        
        Args:
            workflow_id: ID of workflow to clone
            new_name: Name for the cloned workflow
            
        Returns:
            Cloned workflow information
        """
        workflow = await self.get_workflow(workflow_id)
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")
        
        # Modify workflow for cloning
        workflow_dict = workflow.dict() if hasattr(workflow, 'dict') else workflow
        workflow_dict['name'] = new_name or f"{workflow_dict.get('name', 'workflow')}_clone"
        if 'id' in workflow_dict:
            del workflow_dict['id']
        if 'status' in workflow_dict:
            del workflow_dict['status']
            
        # Submit as new workflow
        new_workflow = Workflow(**workflow_dict)
        return await self.submit_workflow(new_workflow)
    
    async def get_workflow_statistics(self) -> Dict[str, Any]:
        """
        Get workflow execution statistics.
        
        Returns:
            Statistics dictionary
        """
        # Get workflows and calculate stats
        all_workflows = await self.list_workflows(limit=1000)
        workflows = all_workflows.get('workflows', [])
        
        stats = {
            'total': len(workflows),
            'by_status': {},
            'average_duration': 0,
            'success_rate': 0
        }
        
        for workflow in workflows:
            status = workflow.get('status', 'unknown')
            stats['by_status'][status] = stats['by_status'].get(status, 0) + 1
        
        if stats['total'] > 0:
            completed = stats['by_status'].get('completed', 0)
            stats['success_rate'] = (completed / stats['total']) * 100
        
        return stats