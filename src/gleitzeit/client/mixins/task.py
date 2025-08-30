"""
Task operations mixin for Gleitzeit client.
"""

from typing import Any, Dict, List, Optional, Union
import asyncio
import time
from gleitzeit.core.models import Task, TaskResult, TaskStatus


class TaskMixin:
    """Mixin providing task-related operations."""
    
    async def submit_task(self, task: Union[Task, Dict[str, Any]]) -> Dict[str, Any]:
        """
        Submit a task for execution.
        
        Args:
            task: Task object or dictionary
            
        Returns:
            Task submission result
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
            
        if isinstance(task, dict):
            task = Task(**task)
            
        return await self._adapter.submit_task(task)
    
    async def execute_task(self, task: Union[Task, Dict[str, Any]]) -> TaskResult:
        """
        Execute a task and wait for completion.
        
        Args:
            task: Task to execute
            
        Returns:
            TaskResult object
        """
        result = await self.submit_task(task)
        task_id = result.get('task_id') or result.get('id')
        
        if not task_id:
            raise ValueError("No task ID in submission result")
        
        return await self.wait_for_task(task_id)
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        """
        Get task by ID.
        
        Args:
            task_id: Task ID
            
        Returns:
            Task object or None
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.get_task(task_id)
    
    async def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        """
        Get task execution result.
        
        Args:
            task_id: Task ID
            
        Returns:
            TaskResult or None
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.get_task_result(task_id)
    
    async def get_task_status(self, task_id: str) -> Optional[str]:
        """
        Get task status.
        
        Args:
            task_id: Task ID
            
        Returns:
            Status string or None
        """
        task = await self.get_task(task_id)
        if task:
            return task.status.value if hasattr(task.status, 'value') else str(task.status)
        return None
    
    async def list_tasks(self, status: Optional[str] = None,
                        workflow_id: Optional[str] = None,
                        limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """
        List tasks with optional filters.
        
        Args:
            status: Filter by status
            workflow_id: Filter by workflow ID
            limit: Maximum number of tasks
            offset: Offset for pagination
            
        Returns:
            Dictionary with tasks list
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.list_tasks(status, workflow_id, limit, offset)
    
    async def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a task.
        
        Args:
            task_id: Task ID to cancel
            
        Returns:
            True if cancelled successfully
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.cancel_task(task_id)
    
    async def delete_task(self, task_id: str) -> bool:
        """
        Delete a task.
        
        Args:
            task_id: Task ID to delete
            
        Returns:
            True if deleted successfully
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.delete_task(task_id)
    
    async def wait_for_task(self, task_id: str,
                          timeout: float = 300.0,
                          poll_interval: float = 1.0) -> Optional[TaskResult]:
        """
        Wait for task to complete.
        
        Args:
            task_id: Task ID to wait for
            timeout: Maximum wait time in seconds
            poll_interval: Poll interval in seconds
            
        Returns:
            TaskResult when complete
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.wait_for_task(task_id, timeout, poll_interval)
    
    async def retry_task(self, task_id: str) -> Dict[str, Any]:
        """
        Retry a failed task.
        
        Args:
            task_id: Task ID to retry
            
        Returns:
            Retry result
        """
        # Get the original task
        task = await self.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        
        # Create a copy for retry
        task_dict = task.dict() if hasattr(task, 'dict') else task
        task_dict['retry_of'] = task_id
        if 'id' in task_dict:
            del task_dict['id']
        if 'status' in task_dict:
            del task_dict['status']
        
        # Submit as new task
        return await self.submit_task(task_dict)
    
    async def get_task_statistics(self) -> Dict[str, int]:
        """
        Get task execution statistics.
        
        Returns:
            Statistics dictionary
        """
        all_tasks = await self.list_tasks(limit=1000)
        tasks = all_tasks.get('tasks', [])
        
        stats = {
            'total': len(tasks),
            'pending': 0,
            'running': 0,
            'completed': 0,
            'failed': 0,
            'cancelled': 0
        }
        
        for task in tasks:
            status = task.get('status', 'unknown').lower()
            if status in stats:
                stats[status] += 1
        
        return stats
    
    async def batch_execute_tasks(self, tasks: List[Union[Task, Dict]], 
                                 max_concurrent: int = 5) -> List[TaskResult]:
        """
        Execute multiple tasks concurrently.
        
        Args:
            tasks: List of tasks to execute
            max_concurrent: Maximum concurrent tasks
            
        Returns:
            List of TaskResults
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def execute_with_limit(task):
            async with semaphore:
                return await self.execute_task(task)
        
        results = await asyncio.gather(
            *[execute_with_limit(task) for task in tasks],
            return_exceptions=True
        )
        
        # Filter out exceptions and return results
        return [r for r in results if not isinstance(r, Exception)]
    
    async def wait_for_tasks(self, task_ids: List[str],
                           timeout: float = 300.0) -> Dict[str, TaskResult]:
        """
        Wait for multiple tasks to complete.
        
        Args:
            task_ids: List of task IDs
            timeout: Maximum wait time
            
        Returns:
            Dictionary mapping task_id to TaskResult
        """
        results = await asyncio.gather(
            *[self.wait_for_task(tid, timeout) for tid in task_ids],
            return_exceptions=True
        )
        
        return {
            task_id: result
            for task_id, result in zip(task_ids, results)
            if not isinstance(result, Exception)
        }
    
    async def get_queue_status(self) -> Dict[str, Any]:
        """
        Get task queue status overview.
        
        Returns:
            Queue status with counts and processing rates
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.get_queue_status()
    
    async def bulk_cancel_tasks(self, task_ids: List[str]) -> Dict[str, Any]:
        """
        Cancel multiple tasks at once.
        
        Args:
            task_ids: List of task IDs to cancel
            
        Returns:
            Results of bulk cancellation
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.bulk_cancel_tasks(task_ids)
    
    async def bulk_retry_tasks(self, task_ids: List[str]) -> Dict[str, Any]:
        """
        Retry multiple tasks at once.
        
        Args:
            task_ids: List of task IDs to retry
            
        Returns:
            Results of bulk retry with new task IDs
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.bulk_retry_tasks(task_ids)
    
    async def get_bulk_task_status(self, task_ids: List[str]) -> Dict[str, Any]:
        """
        Get status of multiple tasks at once.
        
        Args:
            task_ids: List of task IDs to check
            
        Returns:
            Dictionary mapping task IDs to their status
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.get_bulk_task_status(task_ids)