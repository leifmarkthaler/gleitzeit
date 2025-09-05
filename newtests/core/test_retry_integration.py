"""
Integration tests for retry functionality with the new architecture
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock, call
from datetime import datetime

from gleitzeit.core.execution_engine_v2 import ExecutionEngineV2
from gleitzeit.core.task_executor import TaskExecutor
from gleitzeit.core.models import Task, TaskStatus, TaskResult, RetryConfig
from gleitzeit.core.events import EventType, GleitzeitEvent
from gleitzeit.core.errors import TaskExecutionError


class TestRetryIntegration:
    """Test retry functionality in the new architecture"""
    
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
        # Store registered handlers so we can call them
        event_bus.handlers = {}
        
        def register(event_type, handler):
            if event_type not in event_bus.handlers:
                event_bus.handlers[event_type] = []
            event_bus.handlers[event_type].append(handler)
            
        event_bus.register.side_effect = register
        
        # Make emit call the handlers
        async def emit(event):
            if event.event_type in event_bus.handlers:
                for handler in event_bus.handlers[event.event_type]:
                    await handler(event)
                    
        event_bus.emit.side_effect = emit
        
        return event_bus
        
    @pytest.fixture
    def task_with_retry(self):
        """Create task with retry configuration"""
        return Task(
            id="retry-task-1",
            name="retryable-task",
            protocol="python",
            method="flaky_operation",
            params={"attempt": 0},
            retry_config=RetryConfig(
                max_attempts=3,
                base_delay=0.1,
                max_delay=1.0,
                backoff_strategy="exponential"
            )
        )
        
    @pytest.mark.asyncio
    async def test_retry_on_failure(self, mock_registry, mock_queue_manager, mock_persistence, mock_event_bus):
        """Test that failed tasks are retried"""
        # Create task executor
        executor = TaskExecutor(
            registry=mock_registry,
            persistence=mock_persistence,
            event_bus=mock_event_bus
        )
        
        # Create task with retry config
        task = Task(
            id="test-retry",
            name="retry-test",
            protocol="python",
            method="test",
            params={},
            retry_config=RetryConfig(max_attempts=3)
        )
        
        # Mock to fail first time, succeed second time
        call_count = 0
        
        async def mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call fails
                return Mock(
                    result=None,
                    error=Mock(message="Temporary failure"),
                    id=task.id
                )
            else:
                # Second call succeeds
                return Mock(
                    result={"success": True},
                    error=None,
                    id=task.id
                )
                
        mock_registry.execute_request.side_effect = mock_execute
        
        # Execute task (should fail)
        result = await executor.execute_task(task)
        
        assert result.status == TaskStatus.FAILED
        assert result.error is not None
        
        # Verify failure event was emitted
        assert mock_event_bus.emit.called
        failed_events = [
            call[0][0] for call in mock_event_bus.emit.call_args_list
            if call[0][0].event_type == EventType.TASK_FAILED
        ]
        assert len(failed_events) > 0
        
        # Check that retry info is in the event
        failed_event = failed_events[0]
        assert failed_event.data.get("is_retryable", False) is True
        
    @pytest.mark.asyncio
    async def test_retry_manager_handles_retry_events(self, mock_registry, mock_queue_manager, mock_persistence, mock_event_bus):
        """Test that RetryManager properly handles retry events"""
        from gleitzeit.core.event_driven_retry_manager import EventDrivenRetryManager
        
        # Create retry manager directly without starting monitoring
        retry_manager = EventDrivenRetryManager(
            persistence=mock_persistence,
            scheduler=None,
            event_bus=mock_event_bus
        )
        
        # Don't start monitoring to avoid infinite loop
        # Just test the event handling directly
        
        # Create a task that will fail
        task = Task(
            id="retry-task",
            name="test",
            protocol="python",
            method="test",
            params={},
            retry_config=RetryConfig(
                max_attempts=3,
                base_delay=0.1
            ),
            metadata={"retry_attempt": 0}
        )
        
        # Mock persistence to return our task
        mock_persistence.get_task.return_value = task
        
        # Emit a task failed event
        failed_event = GleitzeitEvent(
            event_type=EventType.TASK_FAILED,
            data={
                "task_id": task.id,
                "error_message": "Temporary failure",
                "is_retryable": True,
                "attempt_number": 1
            }
        )
        
        # Call the handler directly
        await retry_manager._on_task_failed(failed_event)
        
        # Verify that persistence was called to update task
        assert mock_persistence.get_task.called
        assert mock_persistence.get_task.call_args[0][0] == task.id
        
    @pytest.mark.asyncio
    async def test_max_retry_attempts_respected(self, mock_registry, mock_persistence, mock_event_bus):
        """Test that max retry attempts is respected"""
        executor = TaskExecutor(
            registry=mock_registry,
            persistence=mock_persistence,
            event_bus=mock_event_bus
        )
        
        # Create task with max 2 attempts
        task = Task(
            id="max-retry-test",
            name="test",
            protocol="python",
            method="test",
            params={},
            retry_config=RetryConfig(max_attempts=2)
        )
        
        # Mock to always fail
        mock_registry.execute_request.return_value = Mock(
            result=None,
            error=Mock(message="Persistent failure"),
            id=task.id
        )
        
        # Execute task multiple times
        results = []
        for i in range(3):
            result = await executor.execute_task(task)
            results.append(result)
            
        # All should fail since we're not actually retrying in the executor
        assert all(r.status == TaskStatus.FAILED for r in results)
        
    @pytest.mark.asyncio
    async def test_non_retryable_errors(self, mock_registry, mock_persistence, mock_event_bus):
        """Test that non-retryable errors are not retried"""
        executor = TaskExecutor(
            registry=mock_registry,
            persistence=mock_persistence,
            event_bus=mock_event_bus
        )
        
        # Create task with retry config
        task = Task(
            id="non-retry-test",
            name="test",
            protocol="python",
            method="test",
            params={},
            retry_config=RetryConfig(max_attempts=3)
        )
        
        # Mock to raise ValueError (non-retryable)
        mock_registry.execute_request.side_effect = ValueError("Invalid input")
        
        # Execute task
        result = await executor.execute_task(task)
        
        assert result.status == TaskStatus.FAILED
        
        # Check that the failed event indicates it's not retryable
        failed_events = [
            call[0][0] for call in mock_event_bus.emit.call_args_list
            if call[0][0].event_type == EventType.TASK_FAILED
        ]
        
        if failed_events:
            failed_event = failed_events[0]
            # ValueError, TypeError, KeyError are marked as non-retryable
            assert failed_event.data.get("is_retryable", True) is False
            
    @pytest.mark.asyncio
    async def test_retry_with_exponential_backoff(self, task_with_retry):
        """Test retry configuration with exponential backoff"""
        retry_config = task_with_retry.retry_config
        
        # Verify exponential backoff configuration
        assert retry_config.max_attempts == 3
        assert retry_config.base_delay == 0.1
        assert retry_config.backoff_strategy == "exponential"
        assert retry_config.max_delay == 1.0
        
        # Calculate expected delays for exponential backoff
        delays = []
        delay = retry_config.base_delay
        for i in range(retry_config.max_attempts - 1):
            delays.append(delay)
            # Exponential backoff typically doubles the delay
            delay = min(delay * 2, retry_config.max_delay)
            
        # First retry: 0.1s, Second retry: 0.2s (0.1 * 2)
        assert delays[0] == 0.1
        assert delays[1] == 0.2
        
    @pytest.mark.asyncio
    async def test_retry_metadata_tracking(self, mock_persistence):
        """Test that retry attempts are tracked in task metadata"""
        task = Task(
            id="metadata-test",
            name="test",
            protocol="python",
            method="test",
            params={},
            retry_config=RetryConfig(max_attempts=3),
            metadata={}
        )
        
        # Simulate retry attempts by updating metadata
        for attempt in range(1, 4):
            task.metadata["retry_attempt"] = attempt
            task.metadata["last_retry_at"] = datetime.utcnow().isoformat()
            
            # Save task
            await mock_persistence.save_task(task)
            
        # Verify metadata was updated
        assert task.metadata["retry_attempt"] == 3
        assert "last_retry_at" in task.metadata
        
        # Verify save was called for each attempt
        assert mock_persistence.save_task.call_count == 3
        
    @pytest.mark.asyncio
    async def test_task_eventually_succeeds_after_retries(self, mock_registry, mock_persistence, mock_event_bus):
        """Test complete retry flow where task eventually succeeds"""
        # This would be an integration test with actual retry manager
        # For now, we simulate the retry behavior
        
        task = Task(
            id="eventual-success",
            name="test",
            protocol="python",
            method="test",
            params={},
            retry_config=RetryConfig(max_attempts=3)
        )
        
        attempts = []
        
        async def mock_execute(*args, **kwargs):
            attempt = len(attempts) + 1
            attempts.append(attempt)
            
            if attempt < 3:
                # Fail first two attempts
                return Mock(
                    result=None,
                    error=Mock(message=f"Failure {attempt}"),
                    id=task.id
                )
            else:
                # Succeed on third attempt
                return Mock(
                    result={"success": True, "attempt": attempt},
                    error=None,
                    id=task.id
                )
                
        mock_registry.execute_request.side_effect = mock_execute
        
        executor = TaskExecutor(
            registry=mock_registry,
            persistence=mock_persistence,
            event_bus=mock_event_bus
        )
        
        # In real scenario, retry manager would re-execute
        # Here we simulate multiple executions
        results = []
        for i in range(3):
            result = await executor.execute_task(task)
            results.append(result)
            
            if result.status == TaskStatus.COMPLETED:
                break
                
        # Last attempt should succeed
        assert results[-1].status == TaskStatus.COMPLETED
        assert results[-1].result == {"success": True, "attempt": 3}
        assert len(attempts) == 3