"""
Tests for pending message recovery - ensuring workers process their pending messages
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from gleitzeit.workers.base import BaseWorker, WorkerConfig


class TestPendingMessageRecovery:
    """Test that workers recover pending messages on restart"""

    @pytest.mark.asyncio
    async def test_reads_pending_messages_with_0_cursor(self):
        """Test that workers use '0' cursor to read pending messages first"""

        # Create a test worker
        class TestWorker(BaseWorker):
            async def on_initialize(self):
                pass

            def get_base_streams(self):
                return ["test:stream"]

            async def process_message(self, stream, message_id, data):
                return True

        config = WorkerConfig(
            worker_type="test",
            worker_id="test-1",
            consumer_group="test-group",
            assigned_shards=[0, 1]  # Test with multiple shards
        )

        worker = TestWorker(config)

        # Check the stream patterns
        patterns = worker.get_stream_patterns()

        # Should have patterns for both shards with "0" cursor
        assert patterns[b"{shard:0}:test:stream"] == b"0"
        assert patterns[b"{shard:1}:test:stream"] == b"0"

        # Should NOT use ">" cursor
        for stream, cursor in patterns.items():
            assert cursor == b"0", f"Stream {stream} should use '0' cursor, not '{cursor.decode()}'"

    @pytest.mark.asyncio
    async def test_pending_messages_processed_before_new(self):
        """Test that pending messages are processed before new messages"""

        class TestWorker(BaseWorker):
            async def on_initialize(self):
                pass

            def get_base_streams(self):
                return ["task:ready"]

            async def process_message(self, stream, message_id, data):
                # Track which messages were processed
                if not hasattr(self, 'processed_messages'):
                    self.processed_messages = []
                self.processed_messages.append(message_id)
                return True

        config = WorkerConfig(
            worker_type="test",
            worker_id="test-1",
            consumer_group="test-group",
            assigned_shards=[0]
        )

        worker = TestWorker(config)
        worker.redis = AsyncMock()
        worker._running = True

        # Simulate Redis returning a pending message first (from previous failure)
        # In Redis Streams with "0" cursor, pending messages come before new ones
        pending_msg = (b"{shard:0}:task:ready", [(b"100-0", {b"data": b"pending"})])
        new_msg = (b"{shard:0}:task:ready", [(b"200-0", {b"data": b"new"})])

        # First call returns pending, second call returns new
        worker.redis.xreadgroup = AsyncMock()
        worker.redis.xreadgroup.side_effect = [
            [pending_msg],  # First batch: pending message
            [new_msg],       # Second batch: new message
            [],              # Then nothing
            asyncio.CancelledError()  # Stop the loop
        ]

        # Mock other Redis operations
        worker.redis.xgroup_create = AsyncMock()
        worker.redis.xack = AsyncMock()
        worker.redis.xadd = AsyncMock()
        worker.redis.hset = AsyncMock()
        worker.redis.expire = AsyncMock()
        worker.redis.delete = AsyncMock()

        # Process messages
        try:
            await worker.run()
        except asyncio.CancelledError:
            pass

        # Verify xreadgroup was called with "0" cursor
        calls = worker.redis.xreadgroup.call_args_list
        for call in calls[:-1]:  # Exclude the cancelled call
            streams_arg = call[0][2]  # Third argument is streams dict
            for stream, cursor in streams_arg.items():
                assert cursor == b"0", f"Should use '0' cursor, not '{cursor.decode()}'"

        # Verify messages were processed in order (pending first)
        assert hasattr(worker, 'processed_messages')
        assert worker.processed_messages[0] == "100-0"  # Pending processed first
        assert worker.processed_messages[1] == "200-0"  # New processed second

    @pytest.mark.asyncio
    async def test_failed_message_retried_on_restart(self):
        """Test that a message that failed (no ACK) is retried when worker restarts"""

        # Track processing attempts
        process_attempts = []

        class RetryWorker(BaseWorker):
            async def on_initialize(self):
                pass

            def get_base_streams(self):
                return ["task:ready"]

            async def process_message(self, stream, message_id, data):
                process_attempts.append(message_id)

                # First attempt fails, second succeeds
                if len(process_attempts) == 1:
                    return False  # Don't ACK - simulates failure
                else:
                    return True   # ACK - simulates success on retry

        config = WorkerConfig(
            worker_type="test",
            worker_id="worker-1",
            consumer_group="test-group",
            assigned_shards=[0]
        )

        # First run - message fails
        worker1 = RetryWorker(config)
        worker1.redis = AsyncMock()
        worker1.redis.xack = AsyncMock()
        worker1.redis.xadd = AsyncMock()  # For DLQ

        await worker1._process_with_semaphore(
            "{shard:0}:task:ready",
            "123-0",
            {b"task_id": b"task-1"}
        )

        # Should NOT have ACK'd
        worker1.redis.xack.assert_not_called()
        assert process_attempts == ["123-0"]

        # Simulate worker restart - same worker_id reads again
        # With "0" cursor, it will get the pending message
        worker2 = RetryWorker(config)
        worker2.redis = AsyncMock()
        worker2.redis.xack = AsyncMock()
        worker2.redis.xadd = AsyncMock()

        # Process same message again (simulating it being pending)
        await worker2._process_with_semaphore(
            "{shard:0}:task:ready",
            "123-0",
            {b"task_id": b"task-1"}
        )

        # Should have ACK'd this time
        worker2.redis.xack.assert_called_once()
        assert process_attempts == ["123-0", "123-0"]  # Processed twice

    @pytest.mark.asyncio
    async def test_multiple_workers_dont_get_same_pending(self):
        """Test that different workers don't get each other's pending messages"""

        class TestWorker(BaseWorker):
            async def on_initialize(self):
                pass

            def get_base_streams(self):
                return ["task:ready"]

            async def process_message(self, stream, message_id, data):
                return True

        # Create two different workers in same consumer group
        config1 = WorkerConfig(
            worker_type="test",
            worker_id="worker-1",  # Different ID
            consumer_group="test-group",  # Same group
            assigned_shards=[0]
        )

        config2 = WorkerConfig(
            worker_type="test",
            worker_id="worker-2",  # Different ID
            consumer_group="test-group",  # Same group
            assigned_shards=[0]
        )

        worker1 = TestWorker(config1)
        worker2 = TestWorker(config2)

        # Both should read with "0" cursor
        patterns1 = worker1.get_stream_patterns()
        patterns2 = worker2.get_stream_patterns()

        assert patterns1[b"{shard:0}:task:ready"] == b"0"
        assert patterns2[b"{shard:0}:task:ready"] == b"0"

        # When they call xreadgroup with their worker_id:
        # - worker-1 with "0" gets worker-1's pending messages
        # - worker-2 with "0" gets worker-2's pending messages
        # This is handled by Redis, not our code


if __name__ == "__main__":
    pytest.main([__file__, "-v"])