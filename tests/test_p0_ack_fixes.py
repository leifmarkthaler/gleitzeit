"""
Tests for P0 ACK/NACK fixes - ensuring tasks don't silently fail
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from gleitzeit.workers.base import BaseWorker, WorkerConfig
from gleitzeit.workers.task_execution_worker import TaskExecutionWorker
from gleitzeit.workers.dependency_worker import DependencyWorker


class TestACKPatternFixes:
    """Test that messages are only ACK'd on success"""

    @pytest.mark.asyncio
    async def test_successful_message_is_acked(self):
        """Test that successfully processed messages are ACK'd"""

        # Create a test worker that succeeds
        class SuccessWorker(BaseWorker):
            async def on_initialize(self):
                pass

            def get_base_streams(self):
                return ["test:stream"]

            async def process_message(self, stream, message_id, data):
                # Simulate successful processing
                return True

        config = WorkerConfig(
            worker_type="test",
            worker_id="test-1",
            consumer_group="test-group"
        )

        worker = SuccessWorker(config)
        worker.redis = AsyncMock()
        worker.redis.xack = AsyncMock()

        # Process a message
        await worker._process_with_semaphore(
            "test:stream",
            "123-0",
            {b"test": b"data"}
        )

        # Should ACK the message
        worker.redis.xack.assert_called_once()
        assert worker.messages_processed == 1
        assert worker.messages_failed == 0

    @pytest.mark.asyncio
    async def test_failed_message_not_acked(self):
        """Test that failed messages are NOT ACK'd"""

        # Create a test worker that fails
        class FailWorker(BaseWorker):
            async def on_initialize(self):
                pass

            def get_base_streams(self):
                return ["test:stream"]

            async def process_message(self, stream, message_id, data):
                # Simulate failed processing
                return False

        config = WorkerConfig(
            worker_type="test",
            worker_id="test-1",
            consumer_group="test-group"
        )

        worker = FailWorker(config)
        worker.redis = AsyncMock()
        worker.redis.xack = AsyncMock()
        worker.redis.xadd = AsyncMock()  # For DLQ

        # Process a message
        await worker._process_with_semaphore(
            "test:stream",
            "123-0",
            {b"test": b"data"}
        )

        # Should NOT ACK the message
        worker.redis.xack.assert_not_called()
        assert worker.messages_processed == 0
        assert worker.messages_failed == 1

        # Should emit to DLQ
        worker.redis.xadd.assert_called_once()
        dlq_call = worker.redis.xadd.call_args
        assert b"dead_letter:tasks" == dlq_call[0][0]

    @pytest.mark.asyncio
    async def test_exception_in_processing_not_acked(self):
        """Test that messages that throw exceptions are NOT ACK'd"""

        # Create a test worker that throws exception
        class ExceptionWorker(BaseWorker):
            async def on_initialize(self):
                pass

            def get_base_streams(self):
                return ["test:stream"]

            async def process_message(self, stream, message_id, data):
                # Simulate exception
                raise ValueError("Processing failed!")

        config = WorkerConfig(
            worker_type="test",
            worker_id="test-1",
            consumer_group="test-group"
        )

        worker = ExceptionWorker(config)
        worker.redis = AsyncMock()
        worker.redis.xack = AsyncMock()
        worker.redis.xadd = AsyncMock()  # For DLQ

        # Process a message
        await worker._process_with_semaphore(
            "test:stream",
            "123-0",
            {b"test": b"data"}
        )

        # Should NOT ACK the message
        worker.redis.xack.assert_not_called()
        assert worker.messages_processed == 0
        assert worker.messages_failed == 1

        # Should emit to DLQ
        worker.redis.xadd.assert_called_once()


class TestTaskExecutionWorkerACK:
    """Test TaskExecutionWorker ACK behavior"""

    @pytest.mark.asyncio
    async def test_no_handler_returns_true_for_ack(self):
        """Test that tasks with no handler are ACK'd (to avoid infinite retry)"""

        config = WorkerConfig(
            worker_type="task_execution",
            worker_id="exec-1",
            consumer_group="execution-group"
        )

        worker = TaskExecutionWorker(config)
        worker.redis = AsyncMock()
        worker.handlers = {}  # No handlers

        # Mock event store
        worker.event_store = AsyncMock()

        # Mock Redis operations
        worker.redis.hgetall = AsyncMock(return_value={})  # Empty task data
        worker.redis.hset = AsyncMock()
        worker.redis.xadd = AsyncMock()

        # Create a task with proper Task fields
        task_data = {
            "id": "task-1",
            "workflow_id": "wf-1",
            "name": "custom_task",
            "type": "custom",
            "protocol": "unsupported/v1",
            "method": "execute",
            "config": {}
        }

        # Process should return True (ACK to prevent infinite retry)
        result = await worker.process_message(
            "{shard:0}:task:ready",
            "123-0",
            {
                "task_id": "task-1",
                "workflow_id": "wf-1",
                "task": json.dumps(task_data)
            }
        )

        assert result is True  # Should ACK to prevent infinite retry

        # Should mark task as failed
        worker.redis.hset.assert_called()
        call_args = worker.redis.hset.call_args_list
        # Find the call that sets status to failed
        status_set = False
        for call in call_args:
            if "mapping" in call[1] and b"status" in call[1]["mapping"]:
                assert call[1]["mapping"][b"status"] == b"failed"
                status_set = True
        assert status_set, "Task should be marked as failed"

    @pytest.mark.asyncio
    async def test_handler_exception_returns_false(self):
        """Test that handler exceptions cause retry (return False)"""

        config = WorkerConfig(
            worker_type="task_execution",
            worker_id="exec-1",
            consumer_group="execution-group"
        )

        worker = TaskExecutionWorker(config)
        worker.redis = AsyncMock()

        # Mock event store
        worker.event_store = AsyncMock()

        # Mock Redis operations
        worker.redis.hgetall = AsyncMock(return_value={})  # Empty task data
        worker.redis.hset = AsyncMock()
        worker.redis.xadd = AsyncMock()

        # Create a failing handler
        failing_handler = AsyncMock()
        failing_handler.can_handle.return_value = True
        failing_handler.execute.side_effect = Exception("Handler failed!")

        worker.handlers = {"test/v1": failing_handler}

        # Create a task with proper Task fields
        task_data = {
            "id": "task-1",
            "workflow_id": "wf-1",
            "name": "test_task",
            "type": "test",
            "protocol": "test/v1",
            "method": "execute",
            "config": {}
        }

        # Process should return False (don't ACK, retry)
        result = await worker.process_message(
            "{shard:0}:task:ready",
            "123-0",
            {
                "task_id": "task-1",
                "workflow_id": "wf-1",
                "task": json.dumps(task_data)
            }
        )

        assert result is False  # Should NOT ACK, leave for retry


class TestDependencyWorkerACK:
    """Test DependencyWorker ACK behavior"""

    @pytest.mark.asyncio
    async def test_dependency_check_exception_returns_false(self):
        """Test that exceptions in dependency checking cause retry"""

        config = WorkerConfig(
            worker_type="dependency",
            worker_id="dep-1",
            consumer_group="dependency-group"
        )

        worker = DependencyWorker(config)
        worker.redis = AsyncMock()

        # Make workflow fetch fail
        worker.redis.hget.side_effect = Exception("Redis error!")

        # Process should return False (retry)
        result = await worker.process_message(
            "{shard:0}:workflow:submitted",
            "123-0",
            {
                "workflow_id": "wf-1",
                "workflow": json.dumps({"tasks": []})
            }
        )

        assert result is False  # Should NOT ACK, leave for retry


class TestDeadLetterQueue:
    """Test DLQ emission for failed messages"""

    @pytest.mark.asyncio
    async def test_dlq_emission_on_failure(self):
        """Test that failed messages are sent to DLQ"""

        # Create a failing worker
        class FailWorker(BaseWorker):
            async def on_initialize(self):
                pass

            def get_base_streams(self):
                return ["test:stream"]

            async def process_message(self, stream, message_id, data):
                return False  # Fail

        config = WorkerConfig(
            worker_type="test",
            worker_id="test-1",
            consumer_group="test-group"
        )

        worker = FailWorker(config)
        worker.redis = AsyncMock()
        worker.redis.xadd = AsyncMock()

        # Process a message with workflow/task IDs
        await worker._process_with_semaphore(
            "{shard:0}:task:ready",
            "123-0",
            {
                b"workflow_id": b"wf-1",
                b"task_id": b"task-1",
                b"data": b"test"
            }
        )

        # Should emit to DLQ
        worker.redis.xadd.assert_called_once()
        dlq_call = worker.redis.xadd.call_args

        # Verify DLQ stream
        assert dlq_call[0][0] == b"dead_letter:tasks"

        # Verify DLQ data
        dlq_data = dlq_call[0][1]
        assert dlq_data[b"workflow_id"] == b"wf-1"
        assert dlq_data[b"task_id"] == b"task-1"
        assert dlq_data[b"original_stream"] == b"{shard:0}:task:ready"
        assert dlq_data[b"message_id"] == b"123-0"
        assert b"error" in dlq_data
        assert b"failed_at" in dlq_data
        assert dlq_data[b"worker_id"] == b"test-1"

    @pytest.mark.asyncio
    async def test_dlq_emission_on_exception(self):
        """Test that exceptions also emit to DLQ"""

        # Create an exception-throwing worker
        class ExceptionWorker(BaseWorker):
            async def on_initialize(self):
                pass

            def get_base_streams(self):
                return ["test:stream"]

            async def process_message(self, stream, message_id, data):
                raise RuntimeError("Boom!")

        config = WorkerConfig(
            worker_type="test",
            worker_id="test-1",
            consumer_group="test-group"
        )

        worker = ExceptionWorker(config)
        worker.redis = AsyncMock()
        worker.redis.xadd = AsyncMock()

        # Process a message
        await worker._process_with_semaphore(
            "test:stream",
            "123-0",
            {b"data": b"test"}
        )

        # Should emit to DLQ
        worker.redis.xadd.assert_called_once()
        dlq_call = worker.redis.xadd.call_args

        # Verify DLQ stream
        assert dlq_call[0][0] == b"dead_letter:tasks"

        # Verify error is captured
        dlq_data = dlq_call[0][1]
        assert b"Boom!" in dlq_data[b"error"]


class TestStatelessDesign:
    """Verify stateless design - no persistent failure tracking"""

    @pytest.mark.asyncio
    async def test_no_state_tracking_between_failures(self):
        """Test that failures don't accumulate state"""

        # Create a worker that fails
        class FailWorker(BaseWorker):
            async def on_initialize(self):
                pass

            def get_base_streams(self):
                return ["test:stream"]

            async def process_message(self, stream, message_id, data):
                return False

        config = WorkerConfig(
            worker_type="test",
            worker_id="test-1",
            consumer_group="test-group"
        )

        worker = FailWorker(config)
        worker.redis = AsyncMock()
        worker.redis.xadd = AsyncMock()

        # Process same message multiple times
        for i in range(3):
            await worker._process_with_semaphore(
                "test:stream",
                "123-0",
                {b"data": b"test"}
            )

        # Each failure should be independent - no state tracking
        assert worker.messages_failed == 3  # Simple counter, not state

        # Each should emit to DLQ independently
        assert worker.redis.xadd.call_count == 3

        # No persistent state tracking (no failure counts, etc)
        assert not hasattr(worker, '_failure_counts')
        assert not hasattr(worker, '_failed_messages')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])