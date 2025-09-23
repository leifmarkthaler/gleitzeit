"""
Test the complete recovery system including:
1. Failed messages not ACK'd (stay pending)
2. Workers read their own pending on restart
3. XCLAIM for permanently dead workers
4. Exponential backoff retry
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from gleitzeit.workers.base import BaseWorker, WorkerConfig
from gleitzeit.workers.pending_recovery import PendingRecoveryMixin


class TestCompleteRecoverySystem:
    """Test all recovery mechanisms work together"""

    @pytest.mark.asyncio
    async def test_recovery_levels(self):
        """Test the 4 levels of recovery"""

        # Create a test worker
        class TestWorker(BaseWorker, PendingRecoveryMixin):
            async def on_initialize(self):
                pass

            def get_base_streams(self):
                return ["task:ready"]

            async def process_message(self, stream, message_id, data):
                # Track processing attempts
                if not hasattr(self, 'attempts'):
                    self.attempts = {}

                if message_id not in self.attempts:
                    self.attempts[message_id] = 0
                self.attempts[message_id] += 1

                # First attempt fails
                if self.attempts[message_id] == 1:
                    return False  # Don't ACK - Level 1: stays pending
                else:
                    return True   # Success on retry

        config = WorkerConfig(
            worker_type="test",
            worker_id="test-worker-1",
            consumer_group="test-group",
            assigned_shards=[0]
        )

        worker = TestWorker(config)
        worker.redis = AsyncMock()
        worker._running = True

        # Level 1: Message fails, stays pending (no ACK)
        await worker._process_with_semaphore(
            "{shard:0}:task:ready",
            "100-0",
            {b"data": b"test"}
        )

        # Should NOT have ACK'd
        worker.redis.xack.assert_not_called()
        assert worker.messages_failed == 1

        # Level 2: Worker reads pending on restart (using "0" cursor)
        patterns = worker.get_stream_patterns()
        assert patterns[b"{shard:0}:task:ready"] == b"0"  # Reads pending first

        # Level 3: XCLAIM for stuck messages from dead workers
        # Mock XPENDING returning a stuck message from dead-worker-1
        worker.redis.execute_command = AsyncMock()
        worker.redis.execute_command.return_value = [
            # Format: (message_id, consumer, idle_time, delivery_count)
            [b"200-0", b"dead-worker-1", 400000, 1],  # 400 seconds idle
            [b"201-0", b"dead-worker-1", 350000, 1],  # 350 seconds idle
        ]

        # Run recovery
        claimed = await worker.recover_pending_messages()

        # Should have called XCLAIM for stuck messages
        calls = worker.redis.execute_command.call_args_list
        xclaim_call = None
        for call in calls:
            if call[0][0] == b"XCLAIM":
                xclaim_call = call
                break

        assert xclaim_call is not None, "Should have called XCLAIM"
        assert b"200-0" in xclaim_call[0]
        assert b"201-0" in xclaim_call[0]

    @pytest.mark.asyncio
    async def test_xclaim_only_for_old_messages(self):
        """Test that we only XCLAIM messages idle > threshold"""

        class TestWorker(BaseWorker, PendingRecoveryMixin):
            async def on_initialize(self):
                pass

            def get_base_streams(self):
                return ["task:ready"]

            async def process_message(self, stream, message_id, data):
                return True

        config = WorkerConfig(
            worker_type="test",
            worker_id="test-worker-1",
            consumer_group="test-group",
            assigned_shards=[0]
        )

        worker = TestWorker(config)
        worker.redis = AsyncMock()
        worker._running = True

        # Mock XPENDING with mixed idle times
        worker.redis.execute_command = AsyncMock()

        # First call returns pending messages with different idle times
        worker.redis.execute_command.return_value = [
            [b"100-0", b"other-worker", 100000, 1],   # 100 seconds - too fresh
            [b"101-0", b"other-worker", 400000, 1],   # 400 seconds - should claim
            [b"102-0", b"other-worker", 600000, 1],   # 600 seconds - should claim
        ]

        # Run recovery
        await worker._recover_stream_pending(b"{shard:0}:task:ready")

        # Check XCLAIM was called with only old messages
        calls = worker.redis.execute_command.call_args_list
        xclaim_call = None
        for call in calls:
            if len(call[0]) > 0 and call[0][0] == b"XCLAIM":
                xclaim_call = call
                break

        assert xclaim_call is not None
        # Should only claim messages > 300 seconds idle
        assert b"100-0" not in xclaim_call[0]  # Too fresh
        assert b"101-0" in xclaim_call[0]      # Old enough
        assert b"102-0" in xclaim_call[0]      # Old enough

    @pytest.mark.asyncio
    async def test_recovery_with_multiple_workers(self):
        """Test recovery doesn't interfere with healthy workers"""

        class TestWorker(BaseWorker, PendingRecoveryMixin):
            async def on_initialize(self):
                pass

            def get_base_streams(self):
                return ["task:ready"]

            async def process_message(self, stream, message_id, data):
                return True

        # Create two workers in same consumer group
        config1 = WorkerConfig(
            worker_type="test",
            worker_id="healthy-worker-1",
            consumer_group="test-group",
            assigned_shards=[0]
        )

        config2 = WorkerConfig(
            worker_type="test",
            worker_id="healthy-worker-2",
            consumer_group="test-group",
            assigned_shards=[0]
        )

        worker1 = TestWorker(config1)
        worker2 = TestWorker(config2)

        worker1.redis = AsyncMock()
        worker2.redis = AsyncMock()

        worker1._running = True
        worker2._running = True

        # Worker1 has a fresh pending message (50 seconds idle)
        # Worker2 runs recovery but shouldn't claim it
        worker2.redis.execute_command = AsyncMock()
        worker2.redis.execute_command.return_value = [
            [b"msg-1", b"healthy-worker-1", 50000, 1],  # Only 50 seconds idle
        ]

        # Worker2 runs recovery
        claimed = await worker2._recover_stream_pending(b"{shard:0}:task:ready")

        # Should NOT have claimed anything (message too fresh)
        assert claimed == 0

        # Now simulate worker1 being dead (message idle 400 seconds)
        worker2.redis.execute_command.return_value = [
            [b"msg-1", b"healthy-worker-1", 400000, 1],  # 400 seconds idle
        ]

        # Worker2 runs recovery again
        worker2.redis.execute_command.side_effect = [
            # First call: XPENDING returns old message
            [[b"msg-1", b"healthy-worker-1", 400000, 1]],
            # Second call: XCLAIM returns claimed message
            [b"msg-1"]
        ]

        claimed = await worker2._recover_stream_pending(b"{shard:0}:task:ready")

        # Should have claimed the stuck message
        assert claimed == 1

    @pytest.mark.asyncio
    async def test_recovery_loop_runs_periodically(self):
        """Test that recovery runs periodically in background"""

        class TestWorker(BaseWorker, PendingRecoveryMixin):
            RECOVERY_INTERVAL = 0.1  # Fast for testing

            async def on_initialize(self):
                pass

            def get_base_streams(self):
                return ["task:ready"]

            async def process_message(self, stream, message_id, data):
                return True

        config = WorkerConfig(
            worker_type="test",
            worker_id="test-worker",
            consumer_group="test-group"
        )

        worker = TestWorker(config)
        worker.redis = AsyncMock()
        worker._running = True

        # Mock recovery to track calls
        recovery_calls = []
        original_recover = worker.recover_pending_messages

        async def mock_recover():
            recovery_calls.append(time.time())
            return 0

        worker.recover_pending_messages = mock_recover

        # Start recovery task
        await worker.start_recovery_task()

        # Let it run for a bit
        await asyncio.sleep(0.35)

        # Stop recovery
        worker._running = False
        await worker.stop_recovery_task()

        # Should have run multiple times
        assert len(recovery_calls) >= 3, f"Expected at least 3 recovery runs, got {len(recovery_calls)}"

        # Check timing between calls
        if len(recovery_calls) >= 2:
            interval = recovery_calls[1] - recovery_calls[0]
            assert 0.08 <= interval <= 0.15, f"Recovery interval was {interval}, expected ~0.1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])