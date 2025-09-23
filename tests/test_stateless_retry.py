"""
Test stateless retry implementation.

Verifies that retry logic works correctly with all state in Redis.
"""

import pytest
import pytest_asyncio
import asyncio
import time
import json
from unittest.mock import Mock, AsyncMock, patch
import redis.asyncio as aioredis

from gleitzeit.core.stateless_retry_service import (
    StatelessRetryService,
    RetryContext,
    RetryDecision
)
from gleitzeit.workers.retry_worker import RetryWorker
from gleitzeit.core.models import TaskStatus


@pytest_asyncio.fixture
async def redis_client():
    """Create test Redis client"""
    # Use fake redis or mock for testing
    redis = AsyncMock()

    # Mock basic Redis operations
    redis.hgetall = AsyncMock(return_value={})
    redis.hset = AsyncMock()
    redis.hincrby = AsyncMock()
    redis.xadd = AsyncMock()
    redis.zadd = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.eval = AsyncMock(return_value=1)  # Budget check passes
    redis.expire = AsyncMock()
    redis.zcard = AsyncMock(return_value=0)

    return redis


class TestStatelessRetryService:
    """Test the stateless retry service"""

    @pytest.mark.asyncio
    async def test_retry_decision_retryable_error(self, redis_client):
        """Test retry decision for retryable errors"""
        service = StatelessRetryService(redis_client)

        context = RetryContext(
            task_id="task1",
            workflow_id="wf1",
            error_type="ConnectionError",
            error_msg="Connection refused",
            current_attempt=0
        )

        decision, metadata = await service.should_retry(context)

        assert decision == RetryDecision.RETRY
        assert 'delay' in metadata
        assert metadata['delay'] > 0

    @pytest.mark.asyncio
    async def test_retry_decision_non_retryable_error(self, redis_client):
        """Test retry decision for non-retryable errors"""
        service = StatelessRetryService(redis_client)

        context = RetryContext(
            task_id="task1",
            workflow_id="wf1",
            error_type="ValueError",
            error_msg="Invalid value",
            current_attempt=0
        )

        decision, metadata = await service.should_retry(context)

        assert decision == RetryDecision.SKIP
        assert metadata['reason'] == 'non_retryable_error'

    @pytest.mark.asyncio
    async def test_retry_decision_max_attempts(self, redis_client):
        """Test retry decision when max attempts reached"""
        service = StatelessRetryService(redis_client)

        context = RetryContext(
            task_id="task1",
            workflow_id="wf1",
            error_type="ConnectionError",
            error_msg="Connection refused",
            current_attempt=5  # Exceeds default max
        )

        decision, metadata = await service.should_retry(context)

        assert decision == RetryDecision.MAX_ATTEMPTS
        assert metadata['current_attempt'] == 5

    @pytest.mark.asyncio
    async def test_budget_exhaustion(self, redis_client):
        """Test retry decision when budget is exhausted"""
        # Mock budget check to fail
        redis_client.eval = AsyncMock(return_value=0)

        service = StatelessRetryService(redis_client)

        context = RetryContext(
            task_id="task1",
            workflow_id="wf1",
            error_type="ConnectionError",
            error_msg="Connection refused",
            current_attempt=0
        )

        decision, metadata = await service.should_retry(context)

        assert decision == RetryDecision.BUDGET_EXHAUSTED
        assert 'workflow_id' in metadata

    @pytest.mark.asyncio
    async def test_delay_calculation(self, redis_client):
        """Test delay calculation strategies"""
        service = StatelessRetryService(redis_client)

        context = RetryContext(
            task_id="task1",
            workflow_id="wf1",
            error_type="Error",
            error_msg="Test",
            current_attempt=2
        )

        # Test exponential
        delay = await service.calculate_delay(
            context,
            {'strategy': 'exponential', 'base_delay': 1.0, 'multiplier': 2.0}
        )
        assert delay == 4.0  # 1 * 2^2

        # Test linear
        delay = await service.calculate_delay(
            context,
            {'strategy': 'linear', 'base_delay': 1.0, 'multiplier': 2.0}
        )
        assert delay == 6.0  # 1 * (2+1) * 2

        # Test fixed
        delay = await service.calculate_delay(
            context,
            {'strategy': 'fixed', 'base_delay': 5.0}
        )
        assert delay == 5.0

    @pytest.mark.asyncio
    async def test_metrics_recording(self, redis_client):
        """Test that metrics are recorded correctly"""
        service = StatelessRetryService(redis_client)

        await service.record_retry_success("wf1", "task1")

        # Verify Redis calls
        redis_client.hincrby.assert_called()
        calls = redis_client.hincrby.call_args_list

        # Should increment success counters
        assert any(b'successful_retries' in str(call) for call in calls)

    @pytest.mark.asyncio
    async def test_configuration_hierarchy(self, redis_client):
        """Test configuration retrieval hierarchy"""
        service = StatelessRetryService(redis_client)

        # Mock task-specific config
        redis_client.hgetall = AsyncMock(side_effect=[
            {b'max_retries': b'5', b'base_delay': b'2.0'},  # Task config
            {},  # Workflow config (empty)
            {}   # Global config (empty)
        ])

        config = await service._get_retry_config("wf1", "task1")

        assert config['max_retries'] == 5
        assert config['base_delay'] == 2.0

    @pytest.mark.asyncio
    async def test_set_retry_config(self, redis_client):
        """Test setting retry configuration"""
        service = StatelessRetryService(redis_client)

        config = {
            'max_retries': 3,
            'base_delay': 1.5,
            'strategy': 'exponential_jitter'
        }

        await service.set_retry_config(config, workflow_id="wf1")

        # Verify Redis hset was called
        redis_client.hset.assert_called()
        call_args = redis_client.hset.call_args

        # Check that config was encoded properly
        assert call_args[0][0] == b'retry:config:workflow:wf1'


class TestRetryWorker:
    """Test the retry worker"""

    @pytest.mark.asyncio
    async def test_retry_worker_initialization(self, redis_client):
        """Test retry worker initializes correctly"""
        worker = RetryWorker(
            worker_id="test_retry_worker",
            config={'retry': {'max_retries': 3}}
        )

        # Mock redis for initialization
        worker.redis = redis_client
        await worker.initialize()

        assert worker.retry_service is not None
        assert worker.worker_id == "test_retry_worker"

    @pytest.mark.asyncio
    async def test_handle_task_failure_retry(self, redis_client):
        """Test handling task failure that should retry"""
        worker = RetryWorker(worker_id="test_worker")
        worker.redis = redis_client
        await worker.initialize()

        # Mock task data
        redis_client.hgetall = AsyncMock(return_value={
            b'retry_count': b'0',
            b'method': b'http/get'
        })

        # Process failure message
        data = {
            'task_id': 'task1',
            'workflow_id': 'wf1',
            'error': 'ConnectionError: Connection refused',
            'error_type': 'ConnectionError'
        }

        result = await worker._handle_task_failure(data)

        assert result is True
        # Should schedule retry via timer
        redis_client.zadd.assert_called()

    @pytest.mark.asyncio
    async def test_handle_task_failure_permanent(self, redis_client):
        """Test handling task failure that should not retry"""
        worker = RetryWorker(worker_id="test_worker")
        worker.redis = redis_client
        await worker.initialize()

        # Mock task data
        redis_client.hgetall = AsyncMock(return_value={
            b'retry_count': b'0',
            b'method': b'python/exec'
        })

        # Process failure with non-retryable error
        data = {
            'task_id': 'task1',
            'workflow_id': 'wf1',
            'error': 'ValueError: Invalid input',
            'error_type': 'ValueError'
        }

        result = await worker._handle_task_failure(data)

        assert result is True
        # Should emit to failed stream
        redis_client.xadd.assert_called()

        # Check that it's marked as final failure
        xadd_calls = redis_client.xadd.call_args_list
        assert any(b'final_failure' in str(call) for call in xadd_calls)

    @pytest.mark.asyncio
    async def test_process_message_routing(self, redis_client):
        """Test message routing in process_message"""
        worker = RetryWorker(worker_id="test_worker")
        worker.redis = redis_client
        await worker.initialize()

        # Mock event store
        worker.event_store = AsyncMock()

        # Test task:failed stream
        result = await worker.process_message(
            "task:failed:shard0",
            b"msg_id",
            {
                b'task_id': b'task1',
                b'workflow_id': b'wf1',
                b'error': b'Test error',
                b'error_type': b'TestError'
            }
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_configuration_update(self, redis_client):
        """Test handling configuration updates"""
        worker = RetryWorker(worker_id="test_worker")
        worker.redis = redis_client
        await worker.initialize()

        data = {
            'type': 'workflow',
            'workflow_id': 'wf1',
            'config': json.dumps({
                'max_retries': 5,
                'base_delay': 2.0
            })
        }

        result = await worker._handle_configuration(data)

        assert result is True
        # Should have set config in Redis
        redis_client.hset.assert_called()

    @pytest.mark.asyncio
    async def test_budget_reset(self, redis_client):
        """Test emergency budget reset"""
        worker = RetryWorker(worker_id="test_worker")
        worker.redis = redis_client
        await worker.initialize()

        data = {
            'type': 'reset_budget',
            'workflow_id': 'wf1'
        }

        result = await worker._handle_configuration(data)

        assert result is True
        # Should have reset budget
        redis_client.set.assert_called()


class TestIntegration:
    """Integration tests for stateless retry system"""

    @pytest.mark.asyncio
    async def test_end_to_end_retry_flow(self, redis_client):
        """Test complete retry flow from failure to retry scheduling"""
        # Setup
        service = StatelessRetryService(redis_client)
        worker = RetryWorker(worker_id="test_worker")
        worker.redis = redis_client
        await worker.initialize()

        # Simulate task failure
        context = RetryContext(
            task_id="task1",
            workflow_id="wf1",
            error_type="ConnectionError",
            error_msg="Connection refused",
            current_attempt=0,
            service_name="api1"
        )

        # Check retry decision
        decision, metadata = await service.should_retry(context)
        assert decision == RetryDecision.RETRY

        # Process through worker
        data = {
            'task_id': context.task_id,
            'workflow_id': context.workflow_id,
            'error': context.error_msg,
            'error_type': context.error_type
        }

        redis_client.hgetall = AsyncMock(return_value={
            b'retry_count': b'0',
            b'method': b'api1/call'
        })

        result = await worker._handle_task_failure(data)
        assert result is True

        # Verify retry was scheduled
        redis_client.zadd.assert_called()
        redis_client.hset.assert_called()

    @pytest.mark.asyncio
    async def test_stateless_across_workers(self, redis_client):
        """Test that state is shared across workers via Redis"""
        # Create two workers
        worker1 = RetryWorker(worker_id="worker1")
        worker2 = RetryWorker(worker_id="worker2")

        worker1.redis = redis_client
        worker2.redis = redis_client

        await worker1.initialize()
        await worker2.initialize()

        # Worker 1 sets configuration
        await worker1.retry_service.set_retry_config(
            {'max_retries': 5},
            workflow_id="shared_wf"
        )

        # Worker 2 should see the same configuration
        # (In real scenario, this would read from actual Redis)
        # Here we're verifying the calls were made correctly
        redis_client.hset.assert_called()

        # Both workers would read the same state from Redis
        assert worker1.retry_service.redis == worker2.retry_service.redis


if __name__ == "__main__":
    pytest.main([__file__, "-v"])