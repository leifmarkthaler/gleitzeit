"""
Test the Task Queue and Queue Manager
"""
import pytest
import asyncio
from datetime import datetime
from unittest.mock import Mock, AsyncMock, MagicMock

from gleitzeit.task_queue import TaskQueue, QueueManager, DependencyResolver
from gleitzeit.core.models import Task, TaskStatus, Priority, Workflow, WorkflowStatus
from gleitzeit.persistence.base import PersistenceBackend


@pytest.fixture
def mock_persistence():
    """Create a mock persistence backend with in-memory storage"""
    persistence = Mock(spec=PersistenceBackend)
    
    # In-memory storage for tasks
    tasks = {}
    
    async def save_task(task):
        tasks[task.id] = task
        return True
    
    async def get_task(task_id):
        return tasks.get(task_id)
    
    async def list_tasks(status=None, **kwargs):
        if status:
            return [t for t in tasks.values() if t.status == status]
        return list(tasks.values())
    
    async def update_task_status(task_id, status):
        if task_id in tasks:
            tasks[task_id].status = status
            return True
        return False
    
    persistence.save_task = AsyncMock(side_effect=save_task)
    persistence.get_task = AsyncMock(side_effect=get_task)
    persistence.update_task_status = AsyncMock(side_effect=update_task_status)
    persistence.list_tasks = AsyncMock(side_effect=list_tasks)
    
    return persistence


@pytest.fixture
def mock_event_bus():
    """Create a mock event bus"""
    event_bus = Mock()
    event_bus.emit = AsyncMock()
    return event_bus


@pytest.fixture
def task_queue(mock_persistence, mock_event_bus):
    """Create a task queue with mocked dependencies"""
    return TaskQueue(
        name="test_queue",
        persistence=mock_persistence,
        event_bus=mock_event_bus
    )


@pytest.fixture
def queue_manager(mock_persistence, mock_event_bus):
    """Create a queue manager with mocked dependencies"""
    return QueueManager(
        persistence=mock_persistence,
        event_bus=mock_event_bus
    )


@pytest.fixture
def sample_task():
    """Create a sample task"""
    return Task(
        id="task1",
        name="Test Task",
        protocol="test/v1",
        method="execute",
        params={"param1": "value1"},
        priority=Priority.NORMAL,
        status=TaskStatus.PENDING,
        created_at=datetime.now()
    )


@pytest.fixture
def sample_workflow():
    """Create a sample workflow with tasks"""
    tasks = [
        Task(
            id="task1",
            name="Task 1",
            protocol="test/v1",
            method="execute",
            params={},
            priority=Priority.NORMAL,
            status=TaskStatus.PENDING,
            workflow_id="workflow1",
            created_at=datetime.now()
        ),
        Task(
            id="task2",
            name="Task 2",
            protocol="test/v1",
            method="execute",
            params={},
            priority=Priority.HIGH,
            status=TaskStatus.PENDING,
            workflow_id="workflow1",
            dependencies=["task1"],
            created_at=datetime.now()
        ),
        Task(
            id="task3",
            name="Task 3",
            protocol="test/v1",
            method="execute",
            params={},
            priority=Priority.LOW,
            status=TaskStatus.PENDING,
            workflow_id="workflow1",
            dependencies=["task1", "task2"],
            created_at=datetime.now()
        )
    ]
    
    return Workflow(
        id="workflow1",
        name="Test Workflow",
        tasks=tasks,
        status=WorkflowStatus.PENDING,
        created_at=datetime.now()
    )


class TestTaskQueue:
    """Test TaskQueue functionality"""
    
    @pytest.mark.asyncio
    async def test_enqueue_task(self, task_queue, sample_task):
        """Test enqueueing a task"""
        await task_queue.enqueue(sample_task)
        
        # Verify task is in queue
        assert not await task_queue.is_empty()
        assert await task_queue.size() == 1
    
    @pytest.mark.asyncio
    async def test_dequeue_task(self, task_queue, sample_task):
        """Test dequeueing a task"""
        await task_queue.enqueue(sample_task)
        
        dequeued = await task_queue.dequeue()
        assert dequeued == sample_task
        assert await task_queue.is_empty()
    
    @pytest.mark.asyncio
    async def test_priority_ordering(self, task_queue):
        """Test that tasks are dequeued by priority"""
        # Create tasks with different priorities
        low_task = Task(
            id="low",
            name="Low Priority",
            protocol="test/v1",
            method="execute",
            params={},
            priority=Priority.LOW,
            status=TaskStatus.PENDING,
            created_at=datetime.now()
        )
        
        high_task = Task(
            id="high",
            name="High Priority",
            protocol="test/v1",
            method="execute",
            params={},
            priority=Priority.HIGH,
            status=TaskStatus.PENDING,
            created_at=datetime.now()
        )
        
        normal_task = Task(
            id="normal",
            name="Normal Priority",
            protocol="test/v1",
            method="execute",
            params={},
            priority=Priority.NORMAL,
            status=TaskStatus.PENDING,
            created_at=datetime.now()
        )
        
        # Enqueue in random order
        await task_queue.enqueue(low_task)
        await task_queue.enqueue(high_task)
        await task_queue.enqueue(normal_task)
        
        # Should dequeue in priority order
        assert (await task_queue.dequeue()).id == "high"
        assert (await task_queue.dequeue()).id == "normal"
        assert (await task_queue.dequeue()).id == "low"
    
    @pytest.mark.asyncio
    async def test_dequeue_empty_queue(self, task_queue):
        """Test dequeueing from empty queue"""
        result = await task_queue.dequeue()
        assert result is None
    
    @pytest.mark.asyncio
    async def test_peek_task(self, task_queue, sample_task):
        """Test peeking at next task without removing it"""
        await task_queue.enqueue(sample_task)
        
        peeked = await task_queue.peek()
        assert peeked == sample_task
        assert not await task_queue.is_empty()  # Task still in queue
    
    @pytest.mark.asyncio
    async def test_remove_specific_task(self, task_queue, sample_task):
        """Test removing a specific task from queue"""
        await task_queue.enqueue(sample_task)
        
        removed = await task_queue.remove(sample_task.id)
        assert removed
        assert await task_queue.is_empty()
    
    @pytest.mark.asyncio
    async def test_clear_queue(self, task_queue, sample_task):
        """Test clearing all tasks from queue"""
        await task_queue.enqueue(sample_task)
        await task_queue.enqueue(sample_task)
        
        await task_queue.clear()
        assert await task_queue.is_empty()


class TestQueueManager:
    """Test QueueManager functionality"""
    
    @pytest.mark.asyncio
    async def test_submit_task(self, queue_manager, sample_task):
        """Test submitting a task to the queue manager"""
        await queue_manager.submit_task(sample_task)
        
        # Verify task was saved and queued
        queue_manager.persistence.save_task.assert_called_once_with(sample_task)
        assert sample_task.id in queue_manager.pending_tasks
    
    @pytest.mark.asyncio
    async def test_get_next_task(self, queue_manager, sample_task):
        """Test getting the next task to execute"""
        await queue_manager.submit_task(sample_task)
        
        next_task = await queue_manager.get_next_task()
        assert next_task == sample_task
        assert next_task.status == TaskStatus.EXECUTING
    
    @pytest.mark.asyncio
    async def test_complete_task(self, queue_manager, sample_task):
        """Test marking a task as complete"""
        await queue_manager.submit_task(sample_task)
        await queue_manager.get_next_task()  # Move to executing
        
        await queue_manager.complete_task(sample_task.id)
        
        assert sample_task.id not in queue_manager.pending_tasks
        assert sample_task.id not in queue_manager.executing_tasks
        assert sample_task.id in queue_manager.completed_tasks
    
    @pytest.mark.asyncio
    async def test_fail_task(self, queue_manager, sample_task):
        """Test marking a task as failed"""
        await queue_manager.submit_task(sample_task)
        await queue_manager.get_next_task()  # Move to executing
        
        await queue_manager.fail_task(sample_task.id, "Test error")
        
        assert sample_task.id not in queue_manager.executing_tasks
        assert sample_task.id in queue_manager.failed_tasks
    
    @pytest.mark.asyncio
    async def test_retry_task(self, queue_manager, sample_task):
        """Test retrying a failed task"""
        await queue_manager.submit_task(sample_task)
        await queue_manager.get_next_task()
        await queue_manager.fail_task(sample_task.id, "Test error")
        
        # Retry the task
        await queue_manager.retry_task(sample_task.id)
        
        assert sample_task.id in queue_manager.pending_tasks
        assert sample_task.id not in queue_manager.failed_tasks
    
    @pytest.mark.asyncio
    async def test_get_queue_statistics(self, queue_manager, sample_task):
        """Test getting queue statistics"""
        await queue_manager.submit_task(sample_task)
        
        stats = await queue_manager.get_statistics()
        
        assert stats["pending"] == 1
        assert stats["executing"] == 0
        assert stats["completed"] == 0
        assert stats["failed"] == 0


class TestDependencyResolver:
    """Test DependencyResolver functionality"""
    
    def test_add_workflow(self, sample_workflow):
        """Test adding a workflow to the resolver"""
        resolver = DependencyResolver()
        resolver.add_workflow(sample_workflow)
        
        # Verify workflow and tasks are tracked
        assert "workflow1" in resolver.workflows
        assert "task1" in resolver.task_dependencies
        assert "task2" in resolver.task_dependencies
        assert "task3" in resolver.task_dependencies
    
    def test_get_execution_order(self, sample_workflow):
        """Test getting execution order with dependencies"""
        resolver = DependencyResolver()
        resolver.add_workflow(sample_workflow)
        
        order = resolver.get_execution_order("workflow1")
        
        # Should return tasks in dependency order
        assert len(order) == 3  # Three levels of execution
        assert "task1" in order[0]  # No dependencies
        assert "task2" in order[1]  # Depends on task1
        assert "task3" in order[2]  # Depends on task1 and task2
    
    def test_is_task_ready(self, sample_workflow):
        """Test checking if a task is ready to execute"""
        resolver = DependencyResolver()
        resolver.add_workflow(sample_workflow)
        
        # Task1 has no dependencies, should be ready
        assert resolver.is_task_ready("task1")
        
        # Task2 depends on task1, not ready yet
        assert not resolver.is_task_ready("task2")
        
        # Mark task1 as complete
        resolver.mark_task_completed("task1")
        
        # Now task2 should be ready
        assert resolver.is_task_ready("task2")
    
    def test_get_ready_tasks(self, sample_workflow):
        """Test getting all tasks ready to execute"""
        resolver = DependencyResolver()
        resolver.add_workflow(sample_workflow)
        
        ready = resolver.get_ready_tasks("workflow1")
        assert ready == ["task1"]  # Only task1 has no dependencies
        
        resolver.mark_task_completed("task1")
        ready = resolver.get_ready_tasks("workflow1")
        assert ready == ["task2"]  # Now task2 is ready
        
        resolver.mark_task_completed("task2")
        ready = resolver.get_ready_tasks("workflow1")
        assert ready == ["task3"]  # Finally task3 is ready
    
    def test_circular_dependency_detection(self):
        """Test detection of circular dependencies"""
        # Create workflow with circular dependency
        tasks = [
            Task(
                id="task1",
                name="Task 1",
                protocol="test/v1",
                method="execute",
                params={},
                dependencies=["task2"],  # Depends on task2
                workflow_id="circular",
                created_at=datetime.now()
            ),
            Task(
                id="task2",
                name="Task 2",
                protocol="test/v1",
                method="execute",
                params={},
                dependencies=["task1"],  # Depends on task1 (circular!)
                workflow_id="circular",
                created_at=datetime.now()
            )
        ]
        
        workflow = Workflow(
            id="circular",
            name="Circular Workflow",
            tasks=tasks,
            status=WorkflowStatus.PENDING,
            created_at=datetime.now()
        )
        
        resolver = DependencyResolver()
        
        # Should raise error for circular dependency
        from gleitzeit.core.errors import DependencyError
        with pytest.raises(DependencyError, match="Circular dependency"):
            resolver.add_workflow(workflow)
    
    def test_mark_task_failed(self, sample_workflow):
        """Test marking a task as failed affects dependents"""
        resolver = DependencyResolver()
        resolver.add_workflow(sample_workflow)
        
        # Mark task1 as failed
        resolver.mark_task_failed("task1")
        
        # Task2 and task3 should never be ready (dependency failed)
        assert not resolver.is_task_ready("task2")
        assert not resolver.is_task_ready("task3")
        
        # Should be marked as blocked
        assert resolver.is_task_blocked("task2")
        assert resolver.is_task_blocked("task3")


class TestQueuePriority:
    """Test priority queue behavior"""
    
    @pytest.mark.asyncio
    async def test_urgent_priority(self, task_queue):
        """Test that urgent priority preempts all others"""
        tasks = []
        for priority in [Priority.LOW, Priority.NORMAL, Priority.HIGH]:
            task = Task(
                id=f"task_{priority.value}",
                name=f"Task {priority.value}",
                protocol="test/v1",
                method="execute",
                params={},
                priority=priority,
                status=TaskStatus.PENDING,
                created_at=datetime.now()
            )
            tasks.append(task)
            await task_queue.enqueue(task)
        
        # Add urgent task last
        urgent_task = Task(
            id="urgent",
            name="Urgent Task",
            protocol="test/v1",
            method="execute",
            params={},
            priority=Priority.URGENT,
            status=TaskStatus.PENDING,
            created_at=datetime.now()
        )
        await task_queue.enqueue(urgent_task)
        
        # Urgent should come first
        dequeued = await task_queue.dequeue()
        assert dequeued.id == "urgent"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])