"""
Test the Execution Engine
"""
import pytest
import asyncio
from datetime import datetime
from unittest.mock import Mock, AsyncMock, MagicMock, patch

from gleitzeit.core.execution_engine_v2 import ExecutionEngineV2 as ExecutionEngine, ExecutionMode
from gleitzeit.core.models import Task, TaskStatus, Priority, Workflow, WorkflowStatus, TaskResult
from gleitzeit.core.errors import TaskError, ErrorCode
from gleitzeit.core.jsonrpc import JSONRPCRequest, JSONRPCResponse
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.task_queue import QueueManager, DependencyResolver


@pytest.fixture
def mock_registry():
    """Create a mock registry"""
    registry = Mock(spec=ProtocolProviderRegistry)
    registry.execute_request = AsyncMock()
    return registry


@pytest.fixture
def mock_queue_manager():
    """Create a mock queue manager"""
    manager = Mock(spec=QueueManager)
    manager.submit_task = AsyncMock()
    manager.get_next_task = AsyncMock()
    manager.complete_task = AsyncMock()
    manager.fail_task = AsyncMock()
    return manager


@pytest.fixture
def mock_dependency_resolver():
    """Create a mock dependency resolver"""
    resolver = Mock(spec=DependencyResolver)
    resolver.add_workflow = Mock()
    resolver.validate_workflow_dependencies = Mock(return_value=[])  # No validation errors
    resolver.get_execution_order = Mock(return_value=[["task1"], ["task2"]])
    resolver.is_task_ready = Mock(return_value=True)
    resolver.mark_task_completed = Mock()
    resolver.mark_task_failed = Mock()
    return resolver


@pytest.fixture
def mock_persistence():
    """Create a mock persistence backend"""
    persistence = Mock()
    persistence.save_workflow = AsyncMock(return_value=True)
    persistence.save_task = AsyncMock(return_value=True)
    persistence.save_task_result = AsyncMock(return_value=True)
    persistence.get_task = AsyncMock()
    persistence.get_workflow = AsyncMock()
    persistence.update_task_status = AsyncMock(return_value=True)
    return persistence


@pytest.fixture
def mock_event_bus():
    """Create a mock event bus"""
    event_bus = Mock()
    event_bus.emit = AsyncMock()
    event_bus.subscribe = Mock()
    return event_bus


@pytest.fixture
def execution_engine(mock_registry, mock_queue_manager, mock_dependency_resolver, mock_persistence, mock_event_bus):
    """Create an execution engine with mocked dependencies"""
    return ExecutionEngine(
        registry=mock_registry,
        queue_manager=mock_queue_manager,
        dependency_resolver=mock_dependency_resolver,
        persistence=mock_persistence,
        event_bus=mock_event_bus,
        max_concurrent_tasks=2
    )


@pytest.fixture
def sample_task():
    """Create a sample task"""
    return Task(
        id="task1",
        name="Test Task",
        protocol="python/v1",
        method="execute",
        params={"file": "test.py"},
        priority=Priority.NORMAL,
        status=TaskStatus.PENDING,
        created_at=datetime.now()
    )


@pytest.fixture
def sample_workflow():
    """Create a sample workflow"""
    tasks = [
        Task(
            id="task1",
            name="Task 1",
            protocol="python/v1",
            method="execute",
            params={"file": "script1.py"},
            workflow_id="workflow1",
            created_at=datetime.now()
        ),
        Task(
            id="task2",
            name="Task 2",
            protocol="python/v1",
            method="execute",
            params={"file": "script2.py", "input": "${task1.result}"},
            dependencies=["task1"],
            workflow_id="workflow1",
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


class TestExecutionEngineBasics:
    """Test basic execution engine functionality"""
    
    @pytest.mark.asyncio
    async def test_submit_workflow(self, execution_engine, sample_workflow, mock_persistence, mock_event_bus):
        """Test submitting a workflow"""
        await execution_engine.submit_workflow(sample_workflow)
        
        # Verify workflow was saved
        mock_persistence.save_workflow.assert_called_once_with(sample_workflow)
        
        # In event-driven mode, tasks are processed via events, not saved directly
        # Verify events were emitted instead
        assert mock_event_bus.emit.call_count >= 1  # At least workflow submitted event
    
    @pytest.mark.asyncio
    async def test_submit_single_task(self, execution_engine, sample_task, mock_persistence, mock_event_bus):
        """Test submitting a single task"""
        await execution_engine.submit_task(sample_task)
        
        # In event-driven mode, task submission creates a workflow and emits events
        # Verify workflow was created for single task
        assert mock_persistence.save_workflow.called
        # Verify event was emitted
        assert mock_event_bus.emit.called
    
    def test_execution_engine_has_components(self, execution_engine):
        """Test execution engine has required components"""
        assert execution_engine.registry is not None
        assert execution_engine.queue_manager is not None
        assert execution_engine.dependency_resolver is not None
    
    def test_max_concurrent_tasks(self, execution_engine):
        """Test concurrent task limit"""
        assert execution_engine.max_concurrent_tasks == 2


class TestTaskExecution:
    """Test task execution functionality"""
    
    @pytest.mark.asyncio
    async def test_execute_task_success(self, execution_engine, sample_task, mock_registry):
        """Test successful task execution"""
        # Mock successful response
        mock_registry.execute_request.return_value = JSONRPCResponse(
            result={"output": "success"},
            error=None,
            id=sample_task.id
        )
        
        result = await execution_engine._execute_task(sample_task)
        
        assert result.status == TaskStatus.COMPLETED
        assert result.result == {"output": "success"}
        assert result.error is None
    
    @pytest.mark.asyncio
    async def test_execute_task_failure(self, execution_engine, sample_task, mock_registry):
        """Test task execution failure"""
        # Mock error response
        mock_registry.execute_request.side_effect = TaskError(
            message="Execution failed",
            code=ErrorCode.TASK_EXECUTION_FAILED
        )
        
        result = await execution_engine._execute_task(sample_task)
        
        assert result.status == TaskStatus.FAILED
        assert result.error is not None
        assert "Execution failed" in result.error
    
    @pytest.mark.asyncio
    async def test_execute_task_timeout(self, execution_engine, sample_task, mock_registry):
        """Test task execution timeout"""
        # Mock timeout
        mock_registry.execute_request.side_effect = asyncio.TimeoutError()
        
        result = await execution_engine._execute_task(sample_task)
        
        assert result.status == TaskStatus.FAILED
        assert "timeout" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_task_parameter_substitution(self, execution_engine, mock_persistence):
        """Test parameter substitution in tasks"""
        # Create task with parameter reference
        task = Task(
            id="task2",
            name="Task with substitution",
            protocol="python/v1",
            method="execute",
            params={"input": "${task1.result.value}"},
            dependencies=["task1"],
            workflow_id="workflow1",
            created_at=datetime.now()
        )
        
        # Mock previous task result
        previous_result = TaskResult(
            task_id="task1",
            workflow_id="workflow1",
            status=TaskStatus.COMPLETED,
            result={"value": "substituted_value"}
        )
        mock_persistence.get_task_result = AsyncMock(return_value=previous_result)
        
        # Execute parameter resolution
        resolved = await execution_engine._resolve_task_parameters(task)
        
        assert resolved["input"] == "substituted_value"


class TestWorkflowExecution:
    """Test workflow execution functionality"""
    
    @pytest.mark.asyncio
    async def test_workflow_completion(self, execution_engine, sample_workflow, mock_persistence):
        """Test marking workflow as complete"""
        # Mock all tasks completed
        mock_persistence.get_workflow.return_value = sample_workflow
        
        for task in sample_workflow.tasks:
            task.status = TaskStatus.COMPLETED
        
        await execution_engine._check_workflow_completion(sample_workflow.id)
        
        # Workflow should be marked complete
        assert sample_workflow.status == WorkflowStatus.COMPLETED
        mock_persistence.save_workflow.assert_called()
    
    @pytest.mark.asyncio
    async def test_workflow_failure(self, execution_engine, sample_workflow, mock_persistence):
        """Test workflow failure when task fails"""
        mock_persistence.get_workflow.return_value = sample_workflow
        
        # Mark one task as failed
        sample_workflow.tasks[0].status = TaskStatus.FAILED
        sample_workflow.tasks[1].status = TaskStatus.CANCELLED
        
        await execution_engine._check_workflow_completion(sample_workflow.id)
        
        # Workflow should be marked failed
        assert sample_workflow.status == WorkflowStatus.FAILED


class TestProviderRouting:
    """Test routing tasks to providers"""
    
    @pytest.mark.asyncio
    async def test_route_to_registry(self, execution_engine, sample_task, mock_registry):
        """Test routing task through registry"""
        mock_registry.execute_request.return_value = JSONRPCResponse(
            result={"data": "test"},
            error=None,
            id=sample_task.id
        )
        
        result = await execution_engine._route_task_to_provider(
            sample_task,
            sample_task.params
        )
        
        # Verify registry was called
        mock_registry.execute_request.assert_called_once()
        call_args = mock_registry.execute_request.call_args
        assert call_args[0][0] == "python/v1"  # protocol_id
        assert call_args[0][1].method == "execute"  # method
    
    @pytest.mark.asyncio
    async def test_no_provider_available(self, execution_engine, sample_task, mock_registry):
        """Test handling when no provider is available"""
        mock_registry.execute_request.return_value = JSONRPCResponse(
            result=None,
            error={"code": -32000, "message": "No providers available"},
            id=sample_task.id
        )
        
        with pytest.raises(TaskError) as exc_info:
            await execution_engine._route_task_to_provider(
                sample_task,
                sample_task.params
            )
        
        assert "Provider error" in str(exc_info.value)


class TestConcurrencyControl:
    """Test concurrent task execution control"""
    
    @pytest.mark.asyncio
    async def test_max_concurrent_limit(self, execution_engine, mock_queue_manager):
        """Test that concurrent task limit is enforced"""
        # Create multiple tasks
        tasks = []
        for i in range(5):
            task = Task(
                id=f"task{i}",
                name=f"Task {i}",
                protocol="python/v1",
                method="execute",
                params={},
                created_at=datetime.now()
            )
            tasks.append(task)
        
        # Mock queue to return tasks
        mock_queue_manager.get_next_task.side_effect = tasks + [None]
        
        # Track active tasks
        active_count = 0
        max_active = 0
        
        async def mock_execute(task):
            nonlocal active_count, max_active
            active_count += 1
            max_active = max(max_active, active_count)
            await asyncio.sleep(0.01)  # Simulate work
            active_count -= 1
            return TaskResult(
                task_id=task.id,
                status=TaskStatus.COMPLETED,
                result={}
            )
        
        execution_engine._execute_task = mock_execute
        
        # Process tasks
        await execution_engine._process_queue()
        
        # Should never exceed max_concurrent_tasks (2)
        assert max_active <= execution_engine.max_concurrent_tasks


class TestEventIntegration:
    """Test event bus integration"""
    
    @pytest.mark.asyncio
    async def test_task_completed_event(self, execution_engine, sample_task, mock_event_bus, mock_registry):
        """Test that task completion emits event"""
        mock_registry.execute_request.return_value = JSONRPCResponse(
            result={"success": True},
            error=None,
            id=sample_task.id
        )
        
        await execution_engine._execute_task(sample_task)
        
        # Verify event was emitted
        mock_event_bus.emit.assert_called()
        emitted_event = mock_event_bus.emit.call_args[0][0]
        assert emitted_event.event_type.value == "task:completed"
    
    @pytest.mark.asyncio
    async def test_task_failed_event(self, execution_engine, sample_task, mock_event_bus, mock_registry):
        """Test that task failure emits event"""
        mock_registry.execute_request.side_effect = Exception("Test failure")
        
        await execution_engine._execute_task(sample_task)
        
        # Verify failure event was emitted
        mock_event_bus.emit.assert_called()
        emitted_event = mock_event_bus.emit.call_args[0][0]
        assert emitted_event.event_type.value == "task:failed"
    
    @pytest.mark.asyncio
    async def test_workflow_completed_event(self, execution_engine, sample_workflow, mock_event_bus, mock_persistence):
        """Test that workflow completion emits event"""
        mock_persistence.get_workflow.return_value = sample_workflow
        
        for task in sample_workflow.tasks:
            task.status = TaskStatus.COMPLETED
        
        await execution_engine._check_workflow_completion(sample_workflow.id)
        
        # Verify workflow completed event
        mock_event_bus.emit.assert_called()
        emitted_event = mock_event_bus.emit.call_args[0][0]
        assert emitted_event.event_type.value == "workflow:completed"


class TestRetryLogic:
    """Test task retry functionality"""
    
    @pytest.mark.asyncio
    async def test_retry_on_transient_error(self, execution_engine, sample_task, mock_registry):
        """Test retry on transient errors"""
        sample_task.retry_config = {
            "max_attempts": 3,
            "delay": 0.01
        }
        
        # First two attempts fail, third succeeds
        mock_registry.execute_request.side_effect = [
            TaskError("Transient error", ErrorCode.PROVIDER_ERROR),
            TaskError("Transient error", ErrorCode.PROVIDER_ERROR),
            JSONRPCResponse(result={"success": True}, error=None, id=sample_task.id)
        ]
        
        # Execute with retry manager
        result = await execution_engine._execute_task(sample_task)
        
        # Should eventually succeed
        assert result.status == TaskStatus.COMPLETED
        assert mock_registry.execute_request.call_count == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])