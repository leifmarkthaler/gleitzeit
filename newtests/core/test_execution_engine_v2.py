"""
Tests for ExecutionEngineV2
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from datetime import datetime

from gleitzeit.core.execution_engine_v2 import ExecutionEngineV2, ExecutionMode
from gleitzeit.core.models import Task, Workflow, TaskStatus, TaskResult, WorkflowStatus
from gleitzeit.core.events import EventType, GleitzeitEvent


class TestExecutionEngineV2:
    """Test suite for refactored ExecutionEngineV2"""
    
    @pytest.fixture
    def mock_registry(self):
        """Create mock protocol registry"""
        registry = Mock()
        registry.execute_request = AsyncMock()
        registry.is_protocol_available = Mock(return_value=True)
        return registry
        
    @pytest.fixture
    def mock_queue_manager(self):
        """Create mock queue manager"""
        queue = Mock()
        queue.enqueue_task = AsyncMock()
        queue.dequeue_task = AsyncMock()
        queue.get_statistics = Mock(return_value={"queued": 0})
        return queue
        
    @pytest.fixture
    def mock_persistence(self):
        """Create mock persistence backend"""
        persistence = Mock()
        persistence.save_task = AsyncMock()
        persistence.save_workflow = AsyncMock()
        persistence.save_task_result = AsyncMock()
        persistence.get_task = AsyncMock()
        persistence.get_workflow = AsyncMock()
        persistence.get_task_result = AsyncMock()
        return persistence
        
    @pytest.fixture
    def mock_event_bus(self):
        """Create mock event bus"""
        event_bus = Mock()
        event_bus.emit = AsyncMock()
        event_bus.register = Mock()
        return event_bus
        
    @pytest.fixture
    def engine(self, mock_registry, mock_queue_manager, mock_persistence, mock_event_bus):
        """Create ExecutionEngineV2 instance"""
        return ExecutionEngineV2(
            registry=mock_registry,
            queue_manager=mock_queue_manager,
            dependency_resolver=None,  # Will use UnifiedDependencyManager
            persistence=mock_persistence,
            event_bus=mock_event_bus,
            max_concurrent_tasks=5,
            task_timeout=10
        )
        
    @pytest.fixture
    def sample_task(self):
        """Create sample task"""
        return Task(
            id="task-1",
            name="test-task",
            protocol="python",
            method="execute",
            params={"input": "test"}
        )
        
    @pytest.fixture
    def sample_workflow(self):
        """Create sample workflow"""
        tasks = [
            Task(id="t1", name="setup", protocol="python", method="setup", params={}),
            Task(id="t2", name="process", protocol="python", method="process", 
                 params={}, dependencies=["t1"]),
            Task(id="t3", name="cleanup", protocol="python", method="cleanup",
                 params={}, dependencies=["t2"])
        ]
        return Workflow(
            id="wf-1",
            name="test-workflow",
            tasks=tasks
        )
        
    @pytest.mark.asyncio
    async def test_engine_initialization(self, engine):
        """Test engine initializes correctly"""
        assert engine is not None
        assert engine.task_executor is not None
        assert engine.task_orchestrator is not None
        assert engine.dependency_manager is not None
        assert engine.parameter_resolver is not None
        assert engine.retry_manager is not None
        assert not engine._running
        
    @pytest.mark.asyncio
    async def test_engine_start_stop(self, engine, mock_event_bus):
        """Test engine start and stop lifecycle"""
        # Start engine
        await engine.start(ExecutionMode.EVENT_DRIVEN)
        
        assert engine._running is True
        assert engine._mode == ExecutionMode.EVENT_DRIVEN
        
        # Verify start event was emitted
        mock_event_bus.emit.assert_called()
        start_event_call = mock_event_bus.emit.call_args_list[0]
        event = start_event_call[0][0]
        assert event.event_type == EventType.ENGINE_STARTED
        
        # Stop engine
        await engine.stop()
        
        assert engine._running is False
        
        # Verify stop event was emitted
        stop_event_call = mock_event_bus.emit.call_args_list[-1]
        event = stop_event_call[0][0]
        assert event.event_type == EventType.ENGINE_STOPPED
        
    @pytest.mark.asyncio
    async def test_submit_task(self, engine, sample_task, mock_queue_manager, mock_persistence, mock_event_bus):
        """Test submitting a single task"""
        await engine.submit_task(sample_task)
        
        # Verify task was saved
        mock_persistence.save_task.assert_called_once_with(sample_task)
        
        # Verify task was enqueued
        mock_queue_manager.enqueue_task.assert_called_once_with(sample_task, None)
        
        # Verify event was emitted
        mock_event_bus.emit.assert_called()
        event_call = mock_event_bus.emit.call_args_list[-1]
        event = event_call[0][0]
        assert event.event_type == EventType.TASK_SUBMITTED
        assert event.data["task_id"] == sample_task.id
        
    @pytest.mark.asyncio
    async def test_submit_workflow(self, engine, sample_workflow, mock_persistence):
        """Test submitting a workflow"""
        # Mock the task orchestrator's submit_workflow method
        engine.task_orchestrator.submit_workflow = AsyncMock()
        
        await engine.submit_workflow(sample_workflow)
        
        # Verify orchestrator was called
        engine.task_orchestrator.submit_workflow.assert_called_once_with(sample_workflow)
        
    @pytest.mark.asyncio
    async def test_execute_task_directly(self, engine, sample_task, mock_registry):
        """Test executing a task directly (bypassing queue)"""
        # Mock successful execution
        mock_registry.execute_request.return_value = Mock(
            result={"output": "success"},
            error=None,
            id=sample_task.id
        )
        
        result = await engine.execute_task(sample_task)
        
        assert result.status == TaskStatus.COMPLETED
        assert result.task_id == sample_task.id
        assert result.error is None
        
    @pytest.mark.asyncio
    async def test_get_task_result(self, engine, mock_persistence):
        """Test getting task result"""
        # Mock task result
        expected_result = TaskResult(
            task_id="task-1",
            status=TaskStatus.COMPLETED,
            result={"data": "test"},
            error=None
        )
        mock_persistence.get_task_result.return_value = expected_result
        
        result = await engine.get_task_result("task-1")
        
        assert result == expected_result
        mock_persistence.get_task_result.assert_called_once_with("task-1")
        
    @pytest.mark.asyncio
    async def test_get_workflow_results(self, engine, sample_workflow, mock_persistence):
        """Test getting all workflow results"""
        # Mock workflow and results
        mock_persistence.get_workflow.return_value = sample_workflow
        
        # Create mock results for each task
        results = []
        for task in sample_workflow.tasks:
            result = TaskResult(
                task_id=task.id,
                status=TaskStatus.COMPLETED,
                result={"task": task.name},
                error=None
            )
            results.append(result)
            
        # Mock get_task_result to return results in order
        mock_persistence.get_task_result.side_effect = results
        
        workflow_results = await engine.get_workflow_results(sample_workflow.id)
        
        assert len(workflow_results) == 3
        assert all(r.status == TaskStatus.COMPLETED for r in workflow_results)
        
    @pytest.mark.asyncio
    async def test_stats_tracking(self, engine):
        """Test statistics tracking"""
        # Simulate task events
        await engine._on_task_completed(GleitzeitEvent(
            event_type=EventType.TASK_COMPLETED,
            data={"task_id": "t1"}
        ))
        await engine._on_task_failed(GleitzeitEvent(
            event_type=EventType.TASK_FAILED,
            data={"task_id": "t2"}
        ))
        await engine._on_workflow_completed(GleitzeitEvent(
            event_type=EventType.WORKFLOW_COMPLETED,
            data={"workflow_id": "wf1"}
        ))
        
        stats = engine.get_stats()
        
        assert stats["tasks_processed"] == 2
        assert stats["tasks_succeeded"] == 1
        assert stats["tasks_failed"] == 1
        assert stats["workflows_completed"] == 1
        assert "orchestrator_stats" in stats
        assert "dependency_stats" in stats
        
    @pytest.mark.asyncio
    async def test_emit_event_compatibility(self, engine, mock_event_bus):
        """Test emit_event method for backward compatibility"""
        # Test with string event type
        await engine.emit_event("task:ready", {"task_id": "test"})
        
        mock_event_bus.emit.assert_called()
        event = mock_event_bus.emit.call_args[0][0]
        assert isinstance(event, GleitzeitEvent)
        
        # Test with GleitzeitEvent object
        test_event = GleitzeitEvent(
            event_type=EventType.TASK_STARTED,
            data={"task_id": "test2"}
        )
        await engine.emit_event(test_event)
        
        event = mock_event_bus.emit.call_args[0][0]
        assert event == test_event
        
    @pytest.mark.asyncio
    async def test_retry_manager_integration(self, engine):
        """Test retry manager is properly integrated"""
        assert engine.retry_manager is not None
        
        # Test getting retry stats
        stats = await engine.get_retry_stats()
        assert isinstance(stats, dict)
        
    @pytest.mark.asyncio
    async def test_is_running(self, engine):
        """Test is_running method"""
        assert not engine.is_running()
        
        await engine.start()
        assert engine.is_running()
        
        await engine.stop()
        assert not engine.is_running()
        
    @pytest.mark.asyncio
    async def test_no_persistence_handling(self, mock_registry, mock_queue_manager, mock_event_bus):
        """Test engine works without persistence"""
        engine = ExecutionEngineV2(
            registry=mock_registry,
            queue_manager=mock_queue_manager,
            dependency_resolver=None,
            persistence=None,  # No persistence
            event_bus=mock_event_bus
        )
        
        # Should not raise errors
        result = await engine.get_task_result("task-1")
        assert result is None
        
        results = await engine.get_workflow_results("wf-1")
        assert results == []
        
    @pytest.mark.asyncio
    async def test_no_event_bus_handling(self, mock_registry, mock_queue_manager, mock_persistence):
        """Test engine works without event bus"""
        engine = ExecutionEngineV2(
            registry=mock_registry,
            queue_manager=mock_queue_manager,
            dependency_resolver=None,
            persistence=mock_persistence,
            event_bus=None  # No event bus
        )
        
        # Should not raise errors
        await engine.emit_event("test:event", {})
        await engine.start()
        await engine.stop()
        
    @pytest.mark.asyncio
    async def test_concurrent_task_limit(self, engine):
        """Test max concurrent tasks is respected"""
        assert engine.max_concurrent_tasks == 5
        assert engine.task_orchestrator.max_concurrent_tasks == 5
        
    @pytest.mark.asyncio
    async def test_task_timeout_configuration(self, engine):
        """Test task timeout is properly configured"""
        assert engine.task_timeout == 10
        assert engine.task_executor.task_timeout == 10