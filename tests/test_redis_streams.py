"""Tests for Redis Streams implementation."""

import asyncio
import pytest
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import redis.asyncio as redis
from redis.exceptions import ResponseError

from gleitzeit.streams.task_stream import TaskStreamManager
from gleitzeit.streams.workflow_stream import WorkflowStreamManager
from gleitzeit.streams.worker import StreamTaskWorker
from gleitzeit.streams.dlq_handler import DeadLetterQueueHandler
from gleitzeit.streams.retry_manager import StreamRetryManager
from gleitzeit.streams.feature_flags import FeatureFlags
from gleitzeit.streams.stream_orchestrator import StreamOrchestrator, StreamMode
from gleitzeit.core.models import Task, TaskStatus, Workflow, WorkflowStatus


@pytest.fixture
async def redis_client():
    """Mock Redis client."""
    client = AsyncMock(spec=redis.Redis)
    return client


@pytest.fixture
async def task_stream(redis_client):
    """Create TaskStreamManager instance."""
    stream = TaskStreamManager(redis_client)
    return stream


@pytest.fixture
async def workflow_stream(redis_client):
    """Create WorkflowStreamManager instance."""
    stream = WorkflowStreamManager(redis_client)
    return stream


@pytest.fixture
async def dlq_handler(redis_client):
    """Create DeadLetterQueueHandler instance."""
    handler = DeadLetterQueueHandler(redis_client)
    return handler


@pytest.fixture
async def retry_manager(redis_client):
    """Create StreamRetryManager instance."""
    manager = StreamRetryManager(redis_client)
    return manager


@pytest.fixture
async def feature_flags(redis_client):
    """Create FeatureFlags instance."""
    flags = FeatureFlags(redis_client)
    return flags


class TestTaskStreamManager:
    """Test TaskStreamManager functionality."""
    
    async def test_initialize(self, task_stream, redis_client):
        """Test stream initialization."""
        redis_client.xgroup_create.side_effect = ResponseError("BUSYGROUP")
        
        await task_stream.initialize()
        
        # Should attempt to create consumer groups
        assert redis_client.xgroup_create.call_count == 3  # normal, high, low
    
    async def test_enqueue_task(self, task_stream, redis_client):
        """Test task enqueuing."""
        redis_client.xadd.return_value = "1234-0"
        
        message_id = await task_stream.enqueue_task(
            task_id="task-123",
            workflow_id="workflow-456",
            priority="high"
        )
        
        assert message_id == "1234-0"
        redis_client.xadd.assert_called_once()
        
        # Check correct stream key for high priority
        call_args = redis_client.xadd.call_args
        assert "high" in call_args[0][0]
    
    async def test_read_tasks(self, task_stream, redis_client):
        """Test reading tasks from stream."""
        redis_client.xreadgroup.return_value = [
            (b"stream", [
                (b"1234-0", {
                    b"task_id": b"task-123",
                    b"workflow_id": b"workflow-456",
                    b"priority": b"normal",
                    b"timestamp": b"2024-01-01T00:00:00",
                    b"metadata": b"{}"
                })
            ])
        ]
        
        tasks = await task_stream.read_tasks("consumer-1", count=5)
        
        assert len(tasks) == 1
        assert tasks[0]["task_id"] == "task-123"
        assert tasks[0]["workflow_id"] == "workflow-456"
    
    async def test_acknowledge_task(self, task_stream, redis_client):
        """Test task acknowledgment."""
        await task_stream.acknowledge_task("1234-0")
        
        redis_client.xack.assert_called_once()
    
    async def test_reclaim_stale_tasks(self, task_stream, redis_client):
        """Test reclaiming stale tasks."""
        redis_client.xautoclaim.return_value = (
            b"0",
            [
                (b"1234-0", {
                    b"task_id": b"task-123",
                    b"workflow_id": b"workflow-456",
                    b"priority": b"normal",
                    b"timestamp": b"2024-01-01T00:00:00",
                    b"metadata": b"{}"
                })
            ]
        )
        
        reclaimed = await task_stream.reclaim_stale_tasks("consumer-1")
        
        assert len(reclaimed) == 1
        assert reclaimed[0]["task_id"] == "task-123"


class TestWorkflowStreamManager:
    """Test WorkflowStreamManager functionality."""
    
    async def test_submit_workflow(self, workflow_stream, redis_client):
        """Test workflow submission."""
        redis_client.xadd.return_value = "1234-0"
        
        message_id = await workflow_stream.submit_workflow("workflow-123")
        
        assert message_id == "1234-0"
        redis_client.xadd.assert_called_once()
        
        # Check event type
        call_args = redis_client.xadd.call_args
        assert call_args[0][1]["action"] == "START"
    
    async def test_trigger_dependency_check(self, workflow_stream, redis_client):
        """Test dependency check trigger."""
        redis_client.xadd.return_value = "1234-1"
        
        message_id = await workflow_stream.trigger_dependency_check(
            "workflow-123",
            "task-456"
        )
        
        assert message_id == "1234-1"
        redis_client.xadd.assert_called_once()
        
        # Check action type
        call_args = redis_client.xadd.call_args
        assert call_args[0][1]["action"] == "CHECK_DEPS"
    
    async def test_mark_workflow_complete(self, workflow_stream, redis_client):
        """Test marking workflow as complete."""
        redis_client.xadd.return_value = "1234-2"
        redis_client.publish.return_value = 1
        
        message_id = await workflow_stream.mark_workflow_complete("workflow-123")
        
        assert message_id == "1234-2"
        
        # Should publish notification
        redis_client.publish.assert_called_once()
    
    async def test_claim_workflow_events(self, workflow_stream, redis_client):
        """Test claiming workflow events."""
        redis_client.xreadgroup.return_value = [
            (b"stream", [
                (b"1234-0", {
                    b"workflow_id": b"workflow-123",
                    b"action": b"START",
                    b"submitted_at": b"2024-01-01T00:00:00"
                })
            ])
        ]
        
        events = await workflow_stream.claim_workflow_events("manager-1")
        
        assert len(events) == 1
        assert events[0]["workflow_id"] == "workflow-123"
        assert events[0]["action"] == "START"


class TestStreamTaskWorker:
    """Test StreamTaskWorker functionality."""
    
    @pytest.fixture
    async def worker(self, redis_client):
        """Create worker instance."""
        worker = StreamTaskWorker(
            redis_client,
            worker_id="test-worker",
            max_concurrent_tasks=2,
            batch_size=5
        )
        return worker
    
    async def test_initialize(self, worker, redis_client):
        """Test worker initialization."""
        with patch('gleitzeit.streams.worker.get_persistence') as mock_get_persistence:
            mock_persistence = AsyncMock()
            mock_get_persistence.return_value = mock_persistence
            
            await worker.initialize()
            
            # Should register worker
            redis_client.hset.assert_called()
            assert "test-worker" in str(redis_client.hset.call_args)
    
    async def test_process_task(self, worker, redis_client):
        """Test task processing."""
        task_data = {
            "id": "msg-123",
            "task_id": "task-456",
            "workflow_id": "workflow-789",
            "priority": "normal"
        }
        
        # Mock persistence
        mock_task = MagicMock()
        mock_task.id = "task-456"
        mock_task.workflow_id = "workflow-789"
        mock_task.status = TaskStatus.PENDING
        
        with patch.object(worker, 'persistence') as mock_persistence:
            mock_persistence.get_task.return_value = mock_task
            mock_persistence.update_task.return_value = None
            
            # Mock lock acquisition
            redis_client.set.return_value = True
            
            await worker._process_task(task_data)
            
            # Should update task status
            assert mock_task.status == TaskStatus.SUCCEEDED
            mock_persistence.update_task.assert_called()
    
    async def test_acquire_task_lock(self, worker, redis_client):
        """Test idempotency lock acquisition."""
        redis_client.set.return_value = True
        
        acquired = await worker._acquire_task_lock("task-123")
        
        assert acquired is True
        redis_client.set.assert_called_once()
        
        # Check NX flag was used
        call_kwargs = redis_client.set.call_args[1]
        assert call_kwargs["nx"] is True


class TestDeadLetterQueueHandler:
    """Test DLQ handler functionality."""
    
    async def test_add_to_dlq(self, dlq_handler, redis_client):
        """Test adding task to DLQ."""
        redis_client.xadd.return_value = "dlq-123"
        redis_client.hincrby.return_value = 1
        redis_client.hset.return_value = 1
        
        with patch.object(dlq_handler, 'persistence') as mock_persistence:
            mock_task = MagicMock()
            mock_persistence.get_task.return_value = mock_task
            
            message_id = await dlq_handler.add_to_dlq(
                task_id="task-123",
                workflow_id="workflow-456",
                error="Max retries exceeded",
                retry_count=3
            )
            
            assert message_id == "dlq-123"
            redis_client.xadd.assert_called_once()
    
    async def test_get_dlq_entries(self, dlq_handler, redis_client):
        """Test retrieving DLQ entries."""
        redis_client.xrange.return_value = [
            (b"dlq-123", {
                b"task_id": b"task-123",
                b"workflow_id": b"workflow-456",
                b"error": b"Failed permanently",
                b"retry_count": b"3",
                b"failed_at": b"2024-01-01T00:00:00",
                b"metadata": b"{}"
            })
        ]
        
        entries = await dlq_handler.get_dlq_entries(count=10)
        
        assert len(entries) == 1
        assert entries[0]["task_id"] == "task-123"
        assert entries[0]["retry_count"] == 3
    
    async def test_reprocess_dlq_entry(self, dlq_handler, redis_client):
        """Test reprocessing a DLQ entry."""
        redis_client.xrange.return_value = [
            (b"dlq-123", {
                b"task_id": b"task-123",
                b"workflow_id": b"workflow-456",
                b"error": b"Failed",
                b"retry_count": b"3",
                b"failed_at": b"2024-01-01T00:00:00",
                b"metadata": b"{}"
            })
        ]
        
        with patch.object(dlq_handler, 'persistence') as mock_persistence:
            mock_task = MagicMock()
            mock_task.id = "task-123"
            mock_task.workflow_id = "workflow-456"
            mock_persistence.get_task.return_value = mock_task
            
            success = await dlq_handler.reprocess_dlq_entry("dlq-123")
            
            assert success is True
            redis_client.xdel.assert_called_once()


class TestStreamRetryManager:
    """Test retry manager functionality."""
    
    async def test_schedule_retry(self, retry_manager, redis_client):
        """Test scheduling a retry."""
        redis_client.zadd.return_value = 1
        
        scheduled = await retry_manager.schedule_retry(
            task_id="task-123",
            workflow_id="workflow-456",
            retry_count=1,
            error="Temporary failure"
        )
        
        assert scheduled is True
        redis_client.zadd.assert_called_once()
        
        # Check exponential backoff was applied
        call_args = redis_client.zadd.call_args
        retry_data = list(call_args[0][1].keys())[0]
        parsed_data = json.loads(retry_data)
        assert parsed_data["retry_count"] == 1
    
    async def test_max_retries_exceeded(self, retry_manager, redis_client):
        """Test handling max retries exceeded."""
        retry_manager.max_retries = 3
        
        with patch.object(retry_manager.dlq_handler, 'add_to_dlq') as mock_add_dlq:
            scheduled = await retry_manager.schedule_retry(
                task_id="task-123",
                workflow_id="workflow-456",
                retry_count=3,  # Already at max
                error="Permanent failure"
            )
            
            assert scheduled is False
            mock_add_dlq.assert_called_once()
    
    async def test_get_pending_retries(self, retry_manager, redis_client):
        """Test getting pending retries."""
        retry_data = json.dumps({
            "task_id": "task-123",
            "workflow_id": "workflow-456",
            "retry_count": 2,
            "error": "Failed",
            "scheduled_at": "2024-01-01T00:00:00",
            "metadata": {}
        })
        
        redis_client.zrange.return_value = [
            (retry_data.encode(), 1234567890.0)
        ]
        
        pending = await retry_manager.get_pending_retries()
        
        assert len(pending) == 1
        assert pending[0]["task_id"] == "task-123"
        assert pending[0]["retry_count"] == 2


class TestFeatureFlags:
    """Test feature flag management."""
    
    async def test_initialize_defaults(self, feature_flags, redis_client):
        """Test initializing with default flags."""
        redis_client.hgetall.return_value = {}
        
        await feature_flags.initialize()
        
        redis_client.hset.assert_called_once()
        
        # Check defaults were set
        call_args = redis_client.hset.call_args
        flags_set = call_args[1]["mapping"]
        assert "stream_mode" in flags_set
        assert "stream_percentage" in flags_set
    
    async def test_get_flag(self, feature_flags, redis_client):
        """Test getting a flag value."""
        redis_client.hget.return_value = b"50"
        
        value = await feature_flags.get_flag("stream_percentage")
        
        assert value == 50
    
    async def test_set_flag(self, feature_flags, redis_client):
        """Test setting a flag value."""
        await feature_flags.set_flag("stream_percentage", 75)
        
        redis_client.hset.assert_called()
        
        # Check audit trail was updated
        redis_client.lpush.assert_called()
    
    async def test_enable_streams_gradually(self, feature_flags, redis_client):
        """Test gradual stream enablement."""
        # Start disabled
        redis_client.hget.side_effect = [
            b"0",  # stream_percentage
            StreamMode.DISABLED.value.encode()  # stream_mode
        ]
        
        await feature_flags.enable_streams_gradually(50, increment=10)
        
        # Should move to shadow mode first
        redis_client.hset.assert_called()
        call_args = redis_client.hset.call_args_list[-2]  # Second to last call
        assert call_args[0][2] == StreamMode.SHADOW.value
    
    async def test_rollback_streams(self, feature_flags, redis_client):
        """Test stream rollback."""
        redis_client.hget.side_effect = [
            StreamMode.ENABLED.value.encode(),  # stream_mode
            b"100"  # stream_percentage
        ]
        
        await feature_flags.rollback_streams()
        
        # Should move back to partial mode
        redis_client.hset.assert_called()
        call_args = redis_client.hset.call_args_list[-2]
        assert call_args[0][2] == StreamMode.PARTIAL.value


class TestStreamOrchestrator:
    """Test StreamOrchestrator integration."""
    
    @pytest.fixture
    async def orchestrator(self, redis_client):
        """Create orchestrator instance."""
        mock_queue = AsyncMock()
        mock_deps = AsyncMock()
        mock_executor = AsyncMock()
        mock_persistence = AsyncMock()
        mock_event_bus = AsyncMock()
        
        orch = StreamOrchestrator(
            redis_client=redis_client,
            queue_manager=mock_queue,
            dependency_manager=mock_deps,
            task_executor=mock_executor,
            persistence=mock_persistence,
            event_bus=mock_event_bus,
            stream_mode=StreamMode.PARTIAL,
            stream_percentage=50
        )
        
        return orch
    
    async def test_submit_task_via_streams(self, orchestrator, redis_client):
        """Test task submission via streams."""
        task = Task(
            id="task-123",
            workflow_id="workflow-456",
            function="test_func",
            dependencies=[]
        )
        
        # Hash should route to streams (< 50%)
        with patch.object(orchestrator, '_should_use_streams', return_value=True):
            redis_client.xadd.return_value = "msg-123"
            
            message_id = await orchestrator.submit_task(task)
            
            assert message_id == "msg-123"
            assert orchestrator.metrics["tasks_via_streams"] == 1
    
    async def test_submit_task_via_pubsub(self, orchestrator):
        """Test task submission via pub/sub."""
        task = Task(
            id="task-789",
            workflow_id="workflow-456",
            function="test_func",
            dependencies=[]
        )
        
        # Hash should route to pub/sub (>= 50%)
        with patch.object(orchestrator, '_should_use_streams', return_value=False):
            task_id = await orchestrator.submit_task(task)
            
            assert task_id == "task-789"
            assert orchestrator.metrics["tasks_via_pubsub"] == 1
    
    async def test_shadow_mode(self, orchestrator):
        """Test shadow mode operation."""
        orchestrator.stream_mode = StreamMode.SHADOW
        
        task = Task(
            id="task-shadow",
            workflow_id="workflow-456",
            function="test_func",
            dependencies=[]
        )
        
        await orchestrator.submit_task(task)
        
        # Should submit to both paths
        orchestrator.queue_manager.enqueue_task.assert_called_once()
        # Note: Stream submission would also happen in shadow mode