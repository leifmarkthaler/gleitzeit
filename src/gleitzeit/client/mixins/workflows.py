"""
Workflow operations mixin for Gleitzeit client.

Provides methods for submitting, querying, and managing workflows.
"""

import logging
import uuid
import asyncio
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class WorkflowResponse:
    """Workflow submission response."""
    workflow_id: str
    status: str
    message: str
    submitted_at: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None


@dataclass
class WorkflowStatus:
    """Workflow status information."""
    workflow_id: str
    status: str
    created_at: str
    updated_at: str
    completed_at: Optional[str] = None
    error: Optional[str] = None
    progress: Optional[Dict[str, Any]] = None


class WorkflowMixin:
    """
    Workflow operations mixin.

    Provides methods for:
    - Submitting workflows
    - Querying workflow status
    - Canceling workflows
    - Batch operations
    - Workflow validation
    """

    async def submit_workflow(
        self,
        workflow: Dict[str, Any],
        workflow_id: Optional[str] = None,
        priority: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> WorkflowResponse:
        """
        Submit a workflow for execution.

        Args:
            workflow: Workflow definition
            workflow_id: Optional workflow ID (generated if not provided)
            priority: Optional priority (higher = more important)
            metadata: Optional metadata to attach

        Returns:
            WorkflowResponse with submission details

        Raises:
            ValueError: If workflow is invalid
            AuthenticationError: If authentication fails
        """
        # Generate workflow ID if not provided
        if not workflow_id:
            workflow_id = f"workflow-{uuid.uuid4()}"

        request_data = {
            "workflow": workflow,
            "workflow_id": workflow_id
        }

        if priority is not None:
            request_data["priority"] = priority

        if metadata:
            request_data["metadata"] = metadata

        try:
            response = await self._request(
                "POST",
                "/workflows/submit",
                json_data=request_data
            )

            logger.info(f"Submitted workflow {workflow_id}: {response.get('status')}")
            return WorkflowResponse(**response)

        except Exception as e:
            logger.error(f"Failed to submit workflow {workflow_id}: {e}")
            raise

    async def submit_workflows_batch(
        self,
        workflows: List[Dict[str, Any]],
        max_concurrent: int = 5
    ) -> List[WorkflowResponse]:
        """
        Submit multiple workflows concurrently.

        Args:
            workflows: List of workflow definitions
            max_concurrent: Maximum concurrent submissions

        Returns:
            List of WorkflowResponse objects
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def submit_with_semaphore(workflow: Dict[str, Any]) -> WorkflowResponse:
            async with semaphore:
                return await self.submit_workflow(workflow)

        tasks = [submit_with_semaphore(w) for w in workflows]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        responses = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Failed to submit workflow {i}: {result}")
                # Create error response
                responses.append(WorkflowResponse(
                    workflow_id=f"error-{i}",
                    status="failed",
                    message=str(result),
                    submitted_at=""
                ))
            else:
                responses.append(result)

        return responses

    async def get_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """
        Get workflow details.

        Args:
            workflow_id: Workflow ID

        Returns:
            Workflow information
        """
        return await self._request(
            "GET",
            f"/workflows/{workflow_id}"
        )

    async def get_workflow_status(self, workflow_id: str) -> WorkflowStatus:
        """
        Get workflow status.

        Args:
            workflow_id: Workflow ID

        Returns:
            WorkflowStatus object
        """
        response = await self.get_workflow(workflow_id)

        state = response.get('state', {})
        data_section = response.get('data', {})

        status = state.get('status') or response.get('status', 'unknown')
        created_at = state.get('submitted_at') or response.get('created_at', '')
        updated_at = state.get('updated_at') or response.get('updated_at', '')
        completed_at = data_section.get('completed_at') or response.get('completed_at')
        error = data_section.get('error') or response.get('error')

        return WorkflowStatus(
            workflow_id=response.get("workflow_id", workflow_id),
            status=status,
            created_at=created_at,
            updated_at=updated_at,
            completed_at=completed_at,
            error=error,
            progress=response.get("progress")
        )

    async def get_workflow_tasks(self, workflow_id: str) -> List[Dict[str, Any]]:
        """
        Get all tasks for a workflow.

        Args:
            workflow_id: Workflow ID

        Returns:
            List of task information
        """
        response = await self._request(
            "GET",
            f"/workflows/{workflow_id}/tasks"
        )
        return response.get("tasks", [])

    async def cancel_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """
        Cancel a workflow.

        Args:
            workflow_id: Workflow ID

        Returns:
            Cancellation result
        """
        response = await self._request(
            "POST",
            f"/workflows/{workflow_id}/cancel"
        )
        logger.info(f"Cancelled workflow {workflow_id}")
        return response

    async def cancel_workflows_batch(
        self,
        workflow_ids: List[str],
        max_concurrent: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Cancel multiple workflows concurrently.

        Args:
            workflow_ids: List of workflow IDs
            max_concurrent: Maximum concurrent cancellations

        Returns:
            List of cancellation results
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def cancel_with_semaphore(workflow_id: str) -> Dict[str, Any]:
            async with semaphore:
                try:
                    return await self.cancel_workflow(workflow_id)
                except Exception as e:
                    return {"workflow_id": workflow_id, "error": str(e)}

        tasks = [cancel_with_semaphore(wid) for wid in workflow_ids]
        return await asyncio.gather(*tasks)

    async def wait_for_workflow(
        self,
        workflow_id: str,
        timeout: Optional[int] = None,
        poll_interval: int = 2
    ) -> WorkflowStatus:
        """
        Wait for workflow to complete.

        Args:
            workflow_id: Workflow ID
            timeout: Maximum wait time in seconds
            poll_interval: Polling interval in seconds

        Returns:
            Final workflow status

        Raises:
            TimeoutError: If timeout exceeded
        """
        start_time = asyncio.get_event_loop().time()

        while True:
            status = await self.get_workflow_status(workflow_id)

            if status.status in ["completed", "failed", "cancelled"]:
                return status

            if timeout and (asyncio.get_event_loop().time() - start_time) > timeout:
                raise TimeoutError(f"Workflow {workflow_id} did not complete within {timeout} seconds")

            await asyncio.sleep(poll_interval)

    async def retry_workflow(self, workflow_id: str) -> WorkflowResponse:
        """
        Retry a failed workflow.

        Args:
            workflow_id: Workflow ID

        Returns:
            New workflow response
        """
        # Get original workflow
        workflow = await self.get_workflow(workflow_id)
        workflow_definition = workflow.get('data', {}).get('workflow')

        if not workflow_definition:
            raise ValueError(
                f"Workflow {workflow_id} does not include a persisted definition to retry"
            )

        new_workflow_id = f"{workflow_id}-retry-{uuid.uuid4().hex[:8]}"
        return await self.submit_workflow(
            workflow_definition,
            workflow_id=new_workflow_id,
            metadata={"original_workflow_id": workflow_id, "is_retry": True}
        )

    async def list_workflows(
        self,
        limit: int = 100,
        offset: int = 0,
        status: Optional[str] = None,
        full_data: bool = False
    ) -> List[Any]:
        """
        List workflows.

        Args:
            limit: Maximum number of workflows
            offset: Offset for pagination
            status: Optional status filter
            full_data: If True, return full workflow data; if False, return just IDs

        Returns:
            List of workflow IDs or workflow data objects
        """
        # Step 1: Get workflow IDs
        params = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status

        response = await self._request(
            "GET",
            "/workflows/list",
            params=params
        )

        workflow_ids = response.get("workflow_ids", [])

        if not full_data or not workflow_ids:
            # Return just the IDs
            return workflow_ids

        # Step 2: Get full workflow data for those IDs
        workflows_response = await self._request(
            "POST",
            "/workflows/",
            json_data={"workflow_ids": workflow_ids}
        )

        return workflows_response.get("workflows", [])
