"""
Tests for TaskExecutor service
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock
from datetime import datetime

from gleitzeit.core.task_executor import TaskExecutor
from gleitzeit.core.models import Task, TaskStatus, TaskResult
from gleitzeit.core.jsonrpc import JSONRPCResponse, JSONRPCError
from gleitzeit.core.errors import TaskTimeoutError, TaskExecutionError


class TestTaskExecutor:
    """Test suite for TaskExecutor"""
    
    @pytest.fixture
    def mock_registry(self):
        """Create mock protocol registry"""
        registry = Mock()
        registry.execute_request = AsyncMock()
        registry.is_protocol_available = Mock(return_value=True)
        return registry
        
    @pytest.fixture
    def mock_persistence(self):
        """Create mock persistence backend"""
        persistence = Mock()
        persistence.save_task = AsyncMock()
        persistence.save_task_result = AsyncMock()
        persistence.get_task_result = AsyncMock()
        return persistence
        
    @pytest.fixture
    def mock_event_bus(self):
        """Create mock event bus"""
        event_bus = Mock()
        event_bus.emit = AsyncMock()
        return event_bus
        
    @pytest.fixture
    def executor(self, mock_registry, mock_persistence, mock_event_bus):
        """Create TaskExecutor instance"""
        return TaskExecutor(
            registry=mock_registry,
            persistence=mock_persistence,
            event_bus=mock_event_bus,
            task_timeout=5
        )
        
    @pytest.fixture
    def sample_task(self):
        """Create sample task for testing"""
        return Task(
            id="task-1",
            name="test-task",
            protocol="python",
            method="execute",
            params={"input": "test_data"}
        )
        
    @pytest.mark.asyncio
    async def test_successful_task_execution(self, executor, mock_registry, sample_task):
        """Test successful task execution"""
        # Setup mock response
        mock_registry.execute_request.return_value = JSONRPCResponse(
            result={"output": "success"},
            error=None,
            id=sample_task.id
        )
        
        # Execute task
        result = await executor.execute_task(sample_task)
        
        # Verify result
        assert result.status == TaskStatus.COMPLETED
        assert result.result == {"output": "success"}
        assert result.error is None
        assert result.task_id == sample_task.id
        
        # Verify registry was called
        mock_registry.execute_request.assert_called_once()
        
    @pytest.mark.asyncio
    async def test_task_execution_with_error(self, executor, mock_registry, sample_task):
        """Test task execution with error"""
        # Setup mock error response
        mock_registry.execute_request.return_value = JSONRPCResponse(
            result=None,
            error=JSONRPCError(code=-32000, message="Execution failed"),
            id=sample_task.id
        )
        
        # Execute task
        result = await executor.execute_task(sample_task)
        
        # Verify error result
        assert result.status == TaskStatus.FAILED
        assert result.result is None
        assert result.error is not None
        assert "Execution failed" in str(result.error)
        
    @pytest.mark.asyncio
    async def test_task_execution_timeout(self, executor, mock_registry, sample_task):
        """Test task execution timeout"""
        # Setup mock to simulate timeout
        async def slow_execution(*args, **kwargs):
            await asyncio.sleep(10)  # Longer than timeout
            
        mock_registry.execute_request.side_effect = slow_execution
        
        # Execute task (should timeout)
        result = await executor.execute_task(sample_task)
        
        # Verify timeout result
        assert result.status == TaskStatus.FAILED
        assert result.error is not None
        assert "timed out" in str(result.error).lower()
        
    @pytest.mark.asyncio
    async def test_parameter_resolution(self, executor, mock_registry, mock_persistence):
        """Test parameter resolution for dependent tasks"""
        # Create task with dependencies
        task = Task(
            id="task-2",
            name="dependent-task",
            protocol="python",
            method="process",
            params={"input": "${task-1}"},
            dependencies=["task-1"]
        )
        
        # Setup mock for parameter resolution
        mock_result = Mock()
        mock_result.result = {"data": "resolved_value"}
        mock_persistence.get_task_result.return_value = mock_result
        
        # Setup successful execution
        mock_registry.execute_request.return_value = JSONRPCResponse(
            result={"processed": "data"},
            error=None,
            id=task.id
        )
        
        # Execute task
        result = await executor.execute_task(task)
        
        # Verify success
        assert result.status == TaskStatus.COMPLETED
        assert result.result == {"processed": "data"}
        
    @pytest.mark.asyncio
    async def test_event_emission(self, executor, mock_registry, mock_event_bus, sample_task):
        """Test that events are emitted during task execution"""
        # Setup successful execution
        mock_registry.execute_request.return_value = JSONRPCResponse(
            result={"output": "success"},
            error=None,
            id=sample_task.id
        )
        
        # Execute task
        await executor.execute_task(sample_task)
        
        # Verify events were emitted
        assert mock_event_bus.emit.call_count >= 2  # At least started and completed
        
        # Check event types
        emitted_events = [call[0][0] for call in mock_event_bus.emit.call_args_list]
        event_types = [event.event_type.value for event in emitted_events]
        
        assert "task:started" in event_types
        assert "task:completed" in event_types
        
    @pytest.mark.asyncio
    async def test_persistence_updates(self, executor, mock_registry, mock_persistence, sample_task):
        """Test that task status and results are persisted"""
        # Setup successful execution
        mock_registry.execute_request.return_value = JSONRPCResponse(
            result={"output": "success"},
            error=None,
            id=sample_task.id
        )
        
        # Execute task
        result = await executor.execute_task(sample_task)
        
        # Verify persistence calls
        assert mock_persistence.save_task.called
        assert mock_persistence.save_task_result.called
        
        # Verify task status was updated
        saved_task_calls = mock_persistence.save_task.call_args_list
        final_task = saved_task_calls[-1][0][0]
        assert final_task.status == TaskStatus.COMPLETED
        
    @pytest.mark.asyncio
    async def test_task_validation(self, executor, mock_registry):
        """Test task validation"""
        # Valid task
        valid_task = Task(
            id="task-1",
            name="valid",
            protocol="python",
            method="execute",
            params={}
        )
        assert await executor.validate_task(valid_task) is True
        
        # Task without protocol - can't create with empty protocol due to validation
        # So we create with protocol and then clear it
        invalid_task1 = Task(
            id="task-2",
            name="invalid",
            protocol="test",
            method="execute",
            params={}
        )
        invalid_task1.protocol = None  # Clear protocol after creation
        with pytest.raises(ValueError, match="no protocol"):
            await executor.validate_task(invalid_task1)
            
        # Task without method
        invalid_task2 = Task(
            id="task-3",
            name="invalid",
            protocol="python",
            method="test",
            params={}
        )
        invalid_task2.method = None  # Clear method after creation
        with pytest.raises(ValueError, match="no method"):
            await executor.validate_task(invalid_task2)
            
        # Task with unsupported protocol
        mock_registry.is_protocol_available.return_value = False
        unsupported_task = Task(
            id="task-4",
            name="unsupported",
            protocol="unknown",
            method="execute",
            params={}
        )
        with pytest.raises(ValueError, match="not available"):
            await executor.validate_task(unsupported_task)
            
    @pytest.mark.asyncio
    async def test_pooling_adapter_routing(self, mock_registry, mock_persistence, mock_event_bus):
        """Test routing through pooling adapter when available"""
        # Create mock pooling adapter
        mock_pooling = Mock()
        mock_pooling.is_protocol_available = Mock(return_value=True)
        mock_pooling.execute_task = AsyncMock(return_value={"pooled": "result"})
        
        # Create executor with pooling adapter
        executor = TaskExecutor(
            registry=mock_registry,
            persistence=mock_persistence,
            event_bus=mock_event_bus,
            pooling_adapter=mock_pooling
        )
        
        # Execute task
        task = Task(
            id="task-1",
            name="pooled-task",
            protocol="python",
            method="execute",
            params={}
        )
        result = await executor.execute_task(task)
        
        # Verify pooling adapter was used
        mock_pooling.execute_task.assert_called_once_with(task)
        assert result.result == {"pooled": "result"}
        
        # Verify registry was NOT called
        mock_registry.execute_request.assert_not_called()
        
    @pytest.mark.asyncio
    async def test_exception_handling(self, executor, mock_registry, sample_task):
        """Test handling of unexpected exceptions"""
        # Setup mock to raise exception
        mock_registry.execute_request.side_effect = RuntimeError("Unexpected error")
        
        # Execute task
        result = await executor.execute_task(sample_task)
        
        # Verify error handling
        assert result.status == TaskStatus.FAILED
        assert result.error is not None
        assert "Unexpected error" in str(result.error)