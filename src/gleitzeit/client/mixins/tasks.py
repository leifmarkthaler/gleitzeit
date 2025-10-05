"""
Task operations mixin for Gleitzeit client.

Provides methods for querying and managing individual tasks within workflows.
"""

import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TaskStatus:
    """Task status information."""
    task_id: str
    workflow_id: str
    status: str
    provider: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    retry_count: int = 0


class TaskMixin:
    """
    Task operations mixin.

    Provides methods for:
    - Querying task status
    - Retrieving task results
    - Retrying failed tasks
    - Task cancellation
    """

    async def get_task(self, task_id: str, workflow_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get task details.

        Args:
            task_id: Task ID
            workflow_id: Optional workflow ID for faster lookup

        Returns:
            Task information
        """
        # Server exposes task endpoints at /tasks/{task_id}
        return await self._request("GET", f"/tasks/{task_id}")

    async def get_task_status(self, task_id: str, workflow_id: Optional[str] = None) -> TaskStatus:
        """
        Get task status.

        Args:
            task_id: Task ID
            workflow_id: Optional workflow ID

        Returns:
            TaskStatus object
        """
        task = await self.get_task(task_id, workflow_id)
        state = task.get("state", {})

        return TaskStatus(
            task_id=task.get("task_id", task_id),
            workflow_id=state.get("workflow_id") or task.get("workflow_id", workflow_id or ""),
            status=state.get("status", task.get("status", "unknown")),
            provider=state.get("provider", task.get("provider", "")),
            created_at=state.get("created_at", task.get("created_at", "")),
            started_at=state.get("started_at") or task.get("started_at"),
            completed_at=state.get("completed_at") or task.get("completed_at"),
            result=task.get("result"),
            error=state.get("error") or task.get("error"),
            retry_count=int(state.get("retry_count", task.get("retry_count", 0)) or 0)
        )

    async def get_task_result(self, task_id: str, workflow_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get task result.

        Args:
            task_id: Task ID
            workflow_id: Optional workflow ID

        Returns:
            Task result or None if not completed
        """
        task = await self.get_task(task_id, workflow_id)
        # Result can be at top level or in state object
        return task.get("result") or task.get("state", {}).get("result")

    async def retry_task(self, task_id: str, workflow_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Retry a failed task.

        Args:
            task_id: Task ID
            workflow_id: Optional workflow ID

        Returns:
            Retry result
        """
        response = await self._request("POST", f"/tasks/{task_id}/retry")
        logger.info(f"Retried task {task_id}")
        return response

    async def cancel_task(self, task_id: str, workflow_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Cancel a task.

        Args:
            task_id: Task ID
            workflow_id: Optional workflow ID

        Returns:
            Cancellation result
        """
        response = await self._request("POST", f"/tasks/{task_id}/cancel")
        logger.info(f"Cancelled task {task_id}")
        return response

    async def get_task_logs(self, task_id: str, workflow_id: Optional[str] = None) -> List[str]:
        """
        Get task execution logs.

        Args:
            task_id: Task ID
            workflow_id: Optional workflow ID

        Returns:
            List of log entries
        """
        response = await self._request("GET", f"/tasks/{task_id}/logs")
        return response.get("logs", [])

    async def get_task_dependencies(self, task_id: str, workflow_id: str) -> List[str]:
        """
        Get task dependencies.

        Args:
            task_id: Task ID
            workflow_id: Workflow ID

        Returns:
            List of dependency task IDs
        """
        endpoint = f"/workflows/{workflow_id}/tasks/{task_id}/dependencies"
        response = await self._request("GET", endpoint)
        return response.get("dependencies", [])

    async def get_task_dependents(self, task_id: str, workflow_id: str) -> List[str]:
        """
        Get tasks that depend on this task.

        Args:
            task_id: Task ID
            workflow_id: Workflow ID

        Returns:
            List of dependent task IDs
        """
        endpoint = f"/workflows/{workflow_id}/tasks/{task_id}/dependents"
        response = await self._request("GET", endpoint)
        return response.get("dependents", [])

    async def list_tasks(
        self,
        limit: int = 100,
        offset: int = 0,
        status: Optional[str] = None,
        workflow_id: Optional[str] = None,
        full_data: bool = False
    ) -> Any:
        """
        List tasks.

        Args:
            limit: Maximum number of tasks
            offset: Offset for pagination
            status: Optional status filter
            workflow_id: Optional workflow ID filter
            full_data: If True, return full task data; if False, return just IDs

        Returns:
            List of task IDs or task data objects
        """
        # Step 1: Get task IDs
        params = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if workflow_id:
            params["workflow_id"] = workflow_id

        response = await self._request(
            "GET",
            "/tasks/list",
            params=params
        )

        task_ids = response.get("task_ids", [])

        if not full_data or not task_ids:
            # Return just the IDs
            return task_ids

        # Step 2: Get full task data for those IDs
        tasks_response = await self._request(
            "POST",
            "/tasks/",
            json_data={"task_ids": task_ids}
        )

        return tasks_response.get("tasks", [])

    async def wait_for_task(
        self,
        task_id: str,
        workflow_id: Optional[str] = None,
        timeout: Optional[int] = None,
        poll_interval: int = 2
    ) -> TaskStatus:
        """
        Wait for task to complete.

        Args:
            task_id: Task ID
            workflow_id: Optional workflow ID
            timeout: Maximum wait time in seconds
            poll_interval: Polling interval in seconds

        Returns:
            Final task status

        Raises:
            TimeoutError: If timeout exceeded
        """
        import asyncio
        start_time = asyncio.get_event_loop().time()

        while True:
            status = await self.get_task_status(task_id, workflow_id)

            if status.status in ["completed", "failed", "cancelled"]:
                return status

            if timeout and (asyncio.get_event_loop().time() - start_time) > timeout:
                raise TimeoutError(f"Task {task_id} did not complete within {timeout} seconds")

            await asyncio.sleep(poll_interval)

    async def get_failed_tasks(self, workflow_id: str) -> List[TaskStatus]:
        """
        Get all failed tasks in a workflow.

        Args:
            workflow_id: Workflow ID

        Returns:
            List of failed TaskStatus objects
        """
        tasks = await self.get_workflow_tasks(workflow_id)
        failed_tasks = []

        for task in tasks:
            if task.get("status") == "failed":
                failed_tasks.append(TaskStatus(
                    task_id=task["task_id"],
                    workflow_id=workflow_id,
                    status="failed",
                    provider=task.get("provider", ""),
                    created_at=task.get("created_at", ""),
                    error=task.get("error"),
                    retry_count=task.get("retry_count", 0)
                ))

        return failed_tasks

    async def retry_failed_tasks(self, workflow_id: str) -> List[Dict[str, Any]]:
        """
        Retry all failed tasks in a workflow.

        Args:
            workflow_id: Workflow ID

        Returns:
            List of retry results
        """
        failed_tasks = await self.get_failed_tasks(workflow_id)
        results = []

        for task in failed_tasks:
            try:
                result = await self.retry_task(task.task_id, workflow_id)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to retry task {task.task_id}: {e}")
                results.append({"task_id": task.task_id, "error": str(e)})

        return results
