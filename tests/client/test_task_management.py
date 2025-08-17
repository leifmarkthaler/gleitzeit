"""
Tests for task management functionality in GleitzeitClient
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch

from gleitzeit.client import GleitzeitClient
from gleitzeit.core.models import Task, TaskResult


class TestTaskSubmission:
    """Test task submission functionality"""
    
    @pytest.mark.asyncio
    async def test_submit_task_basic(self, client_with_mocks):
        """Test basic task submission"""
        # Setup
        expected_task = Task(
            id="task-001",
            name="Test Task",
            protocol="llm/v1",
            method="chat",
            params={"model": "llama3.2"},
            status="queued"
        )
        client_with_mocks.adapter.save_task.return_value = True
        
        # Execute
        with patch('gleitzeit.core.models.Task') as MockTask:
            MockTask.return_value = expected_task
            task = await client_with_mocks.submit_task(
                name="Test Task",
                protocol="llm/v1",
                method="chat",
                params={"model": "llama3.2"}
            )
        
        # Verify
        assert task.name == "Test Task"
        assert task.protocol == "llm/v1"
        assert task.method == "chat"
        client_with_mocks.adapter.save_task.assert_called_once()
        client_with_mocks.queue_manager.enqueue_task.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_submit_task_with_metadata(self, client_with_mocks):
        """Test task submission with metadata"""
        task = await client_with_mocks.submit_task(
            name="Task with Metadata",
            protocol="python/v1",
            method="execute",
            params={"code": "print('hello')"},
            metadata={"author": "test", "version": "1.0"},
            priority=5
        )
        
        client_with_mocks.adapter.save_task.assert_called_once()
        saved_task = client_with_mocks.adapter.save_task.call_args[0][0]
        assert saved_task.metadata == {"author": "test", "version": "1.0"}
        assert saved_task.priority == 5
    
    @pytest.mark.asyncio
    async def test_submit_task_to_custom_queue(self, client_with_mocks):
        """Test submitting task to custom queue"""
        await client_with_mocks.submit_task(
            name="Priority Task",
            protocol="llm/v1",
            method="chat",
            params={},
            queue_name="high_priority"
        )
        
        client_with_mocks.queue_manager.enqueue_task.assert_called_once()
        call_args = client_with_mocks.queue_manager.enqueue_task.call_args
        assert call_args[0][1] == "high_priority"  # Second argument is queue_name
    
    @pytest.mark.asyncio
    async def test_submit_task_not_initialized(self):
        """Test task submission when client not initialized"""
        client = GleitzeitClient()
        
        with pytest.raises(RuntimeError, match="Client not initialized"):
            await client.submit_task(
                name="Test",
                protocol="llm/v1",
                method="chat"
            )


class TestTaskRetrieval:
    """Test task retrieval and status checking"""
    
    @pytest.mark.asyncio
    async def test_get_task(self, client_with_mocks, sample_task):
        """Test getting task by ID"""
        client_with_mocks.adapter.get_task.return_value = sample_task
        
        task = await client_with_mocks.get_task("task-123")
        
        assert task is not None
        assert task.id == "task-123"
        assert task.name == "Test Task"
        client_with_mocks.adapter.get_task.assert_called_once_with("task-123")
    
    @pytest.mark.asyncio
    async def test_get_task_not_found(self, client_with_mocks):
        """Test getting non-existent task"""
        client_with_mocks.adapter.get_task.return_value = None
        
        task = await client_with_mocks.get_task("nonexistent")
        
        assert task is None
    
    @pytest.mark.asyncio
    async def test_get_task_status(self, client_with_mocks, sample_task):
        """Test getting task status"""
        sample_task.status = "running"
        client_with_mocks.adapter.get_task.return_value = sample_task
        
        status = await client_with_mocks.get_task_status("task-123")
        
        assert status == "running"
    
    @pytest.mark.asyncio
    async def test_get_task_result(self, client_with_mocks, sample_task_result):
        """Test getting task result"""
        client_with_mocks.adapter.get_task_result.return_value = sample_task_result
        
        result = await client_with_mocks.get_task_result("task-123")
        
        assert result is not None
        assert result.task_id == "task-123"
        assert result.status == "completed"
        assert result.output == "Task completed successfully"


class TestTaskWaiting:
    """Test waiting for task completion"""
    
    @pytest.mark.asyncio
    async def test_wait_for_task_immediate_completion(self, client_with_mocks, sample_task, sample_task_result):
        """Test waiting for already completed task"""
        sample_task.status = "completed"
        client_with_mocks.adapter.get_task.return_value = sample_task
        client_with_mocks.adapter.get_task_result.return_value = sample_task_result
        
        result = await client_with_mocks.wait_for_task("task-123")
        
        assert result is not None
        assert result.status == "completed"
    
    @pytest.mark.asyncio
    async def test_wait_for_task_delayed_completion(self, client_with_mocks, sample_task, sample_task_result):
        """Test waiting for task that completes after polling"""
        # Task starts as running, then completes
        statuses = ["running", "running", "completed"]
        status_iter = iter(statuses)
        
        def get_task_side_effect(task_id):
            sample_task.status = next(status_iter)
            return sample_task
        
        client_with_mocks.adapter.get_task.side_effect = get_task_side_effect
        client_with_mocks.adapter.get_task_result.return_value = sample_task_result
        
        result = await client_with_mocks.wait_for_task("task-123", poll_interval=0.01)
        
        assert result is not None
        assert result.status == "completed"
        assert client_with_mocks.adapter.get_task.call_count == 3
    
    @pytest.mark.asyncio
    async def test_wait_for_task_timeout(self, client_with_mocks, sample_task):
        """Test waiting for task with timeout"""
        sample_task.status = "running"
        client_with_mocks.adapter.get_task.return_value = sample_task
        
        result = await client_with_mocks.wait_for_task(
            "task-123",
            timeout=0.1,
            poll_interval=0.05
        )
        
        assert result is None  # Timed out
    
    @pytest.mark.asyncio
    async def test_wait_for_task_failed(self, client_with_mocks, sample_task, sample_task_result):
        """Test waiting for task that fails"""
        sample_task.status = "failed"
        sample_task_result.status = "failed"
        sample_task_result.error = "Task execution failed"
        
        client_with_mocks.adapter.get_task.return_value = sample_task
        client_with_mocks.adapter.get_task_result.return_value = sample_task_result
        
        result = await client_with_mocks.wait_for_task("task-123")
        
        assert result is not None
        assert result.status == "failed"
        assert result.error == "Task execution failed"
    
    @pytest.mark.asyncio
    async def test_wait_for_nonexistent_task(self, client_with_mocks):
        """Test waiting for task that doesn't exist"""
        client_with_mocks.adapter.get_task.return_value = None
        
        result = await client_with_mocks.wait_for_task("nonexistent")
        
        assert result is None


class TestTaskCancellation:
    """Test task cancellation"""
    
    @pytest.mark.asyncio
    async def test_cancel_queued_task(self, client_with_mocks, sample_task):
        """Test cancelling a queued task"""
        sample_task.status = "queued"
        client_with_mocks.adapter.get_task.return_value = sample_task
        
        # Mock queue removal
        mock_queue = Mock()
        mock_queue.remove_task = AsyncMock(return_value=True)
        client_with_mocks.queue_manager.queues = {"default": mock_queue}
        
        cancelled = await client_with_mocks.cancel_task("task-123")
        
        assert cancelled is True
        mock_queue.remove_task.assert_called_once_with("task-123")
        client_with_mocks.adapter.save_task.assert_called_once()
        
        # Check task status was updated
        updated_task = client_with_mocks.adapter.save_task.call_args[0][0]
        assert updated_task.status == "cancelled"
    
    @pytest.mark.asyncio
    async def test_cancel_running_task(self, client_with_mocks, sample_task):
        """Test that running tasks cannot be cancelled"""
        sample_task.status = "running"
        client_with_mocks.adapter.get_task.return_value = sample_task
        
        cancelled = await client_with_mocks.cancel_task("task-123")
        
        assert cancelled is False
        client_with_mocks.adapter.save_task.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_cancel_nonexistent_task(self, client_with_mocks):
        """Test cancelling task that doesn't exist"""
        client_with_mocks.adapter.get_task.return_value = None
        
        cancelled = await client_with_mocks.cancel_task("nonexistent")
        
        assert cancelled is False
    
    @pytest.mark.asyncio
    async def test_cancel_task_not_in_queue(self, client_with_mocks, sample_task):
        """Test cancelling task that's not in any queue"""
        sample_task.status = "queued"
        client_with_mocks.adapter.get_task.return_value = sample_task
        
        # Mock empty queues
        mock_queue = Mock()
        mock_queue.remove_task = AsyncMock(return_value=False)
        client_with_mocks.queue_manager.queues = {"default": mock_queue}
        
        cancelled = await client_with_mocks.cancel_task("task-123")
        
        assert cancelled is False


class TestTaskStatistics:
    """Test task statistics functionality"""
    
    @pytest.mark.asyncio
    async def test_get_task_statistics(self, client_with_mocks):
        """Test getting task statistics"""
        mock_tasks = [
            Mock(status="queued"),
            Mock(status="queued"),
            Mock(status="running"),
            Mock(status="completed"),
            Mock(status="completed"),
            Mock(status="completed"),
            Mock(status="failed")
        ]
        client_with_mocks.adapter.list_tasks.return_value = mock_tasks
        
        stats = await client_with_mocks.get_task_statistics()
        
        assert stats["total"] == 7
        assert stats["queued"] == 2
        assert stats["running"] == 1
        assert stats["completed"] == 3
        assert stats["failed"] == 1


class TestMemoryPersistenceIntegration:
    """Integration tests with memory persistence"""
    
    @pytest.mark.asyncio
    async def test_task_lifecycle_memory(self, memory_client):
        """Test complete task lifecycle with memory persistence"""
        # Submit task
        task = await memory_client.submit_task(
            name="Integration Test",
            protocol="python/v1",
            method="execute",
            params={"code": "result = 42"}
        )
        
        assert task.id is not None
        assert task.status == "queued"
        
        # Get task
        retrieved = await memory_client.get_task(task.id)
        assert retrieved is not None
        assert retrieved.id == task.id
        
        # Get status
        status = await memory_client.get_task_status(task.id)
        assert status == "queued"
        
        # Note: In real scenario, a worker would process the task
        # For testing, we'll manually update the status
        task.status = "completed"
        await memory_client.adapter.save_task(task)
        
        # Create and save result
        result = TaskResult(
            task_id=task.id,
            status="completed",
            output="42"
        )
        await memory_client.adapter.save_task_result(result)
        
        # Get result
        task_result = await memory_client.get_task_result(task.id)
        assert task_result is not None
        assert task_result.output == "42"
    
    @pytest.mark.asyncio
    async def test_multiple_tasks_memory(self, memory_client):
        """Test handling multiple tasks with memory persistence"""
        tasks = []
        
        # Submit multiple tasks
        for i in range(5):
            task = await memory_client.submit_task(
                name=f"Task {i}",
                protocol="llm/v1",
                method="chat",
                params={"model": "llama3.2"},
                priority=i
            )
            tasks.append(task)
        
        # Verify all tasks were created
        for task in tasks:
            retrieved = await memory_client.get_task(task.id)
            assert retrieved is not None
            assert retrieved.priority == tasks.index(task)
        
        # Get statistics
        stats = await memory_client.get_task_statistics()
        assert stats["total"] >= 5
        assert stats["queued"] >= 5