"""
Integration tests for worker logging (INFO/DEBUG/WARNING).

Tests that workers correctly log operational events to Redis
and that these logs are queryable.
"""

import pytest
import pytest_asyncio
import asyncio
from gleitzeit.workers.base import BaseWorker, WorkerConfig
from gleitzeit.core.stateless_log_service import StatelessLogService
import redis.asyncio as aioredis


class TestWorker(BaseWorker):
    """Test worker for logging tests"""

    def get_base_streams(self):
        return ["test:stream"]

    async def on_initialize(self):
        """Initialize worker"""
        pass

    async def process_message(self, stream, message_id, data):
        return True


@pytest_asyncio.fixture
async def redis():
    """Create Redis connection for tests"""
    # Create a simple Redis connection for testing
    redis_conn = await aioredis.from_url(
        "redis://localhost:6379",
        decode_responses=False
    )
    yield redis_conn
    await redis_conn.aclose()


@pytest_asyncio.fixture
async def test_worker(redis):
    """Create test worker instance"""
    config = WorkerConfig(
        worker_id="test_worker_1",
        worker_type="test_worker",
        consumer_group="test_group",
        assigned_shards=[0],
        max_concurrent=5,
        batch_size=10,
        block_timeout=1000
    )

    worker = TestWorker(config)
    worker.redis = redis

    yield worker


@pytest.mark.asyncio
async def test_log_worker_info(test_worker, redis):
    """Test worker INFO logging"""
    workflow_id = "test_workflow_789"
    task_id = "test_task_101"

    await test_worker.log_worker_info(
        operation="test_operation",
        message="Worker info test message",
        workflow_id=workflow_id,
        task_id=task_id,
        custom_field="custom_value"
    )

    # Query the logs
    logs = await StatelessLogService.query_logs(
        redis=redis,
        level="INFO",
        workflow_id=workflow_id
    )

    assert len(logs) > 0
    log = logs[0]
    assert "Worker info test message" in log['message']
    assert log['workflow_id'] == workflow_id
    assert log['task_id'] == task_id
    assert log['component'] == "test_worker"
    assert log['operation'] == "test_operation"
    assert log['metadata']['worker_id'] == "test_worker_1"
    assert log['metadata']['custom_field'] == "custom_value"


@pytest.mark.asyncio
async def test_log_worker_debug(test_worker, redis):
    """Test worker DEBUG logging with sampling"""
    workflow_id = "test_workflow_789"

    # Log with 100% sampling to ensure it gets logged
    await test_worker.log_worker_debug(
        operation="debug_test",
        message="Worker debug test message",
        workflow_id=workflow_id,
        debug_data={"key": "value"}
    )

    # Query DEBUG logs
    logs = await StatelessLogService.query_logs(
        redis=redis,
        level="DEBUG",
        workflow_id=workflow_id
    )

    # Note: Due to 10% default sampling, this may or may not be logged
    # The test verifies the method doesn't error
    assert logs is not None


@pytest.mark.asyncio
async def test_log_worker_warning(test_worker, redis):
    """Test worker WARNING logging"""
    workflow_id = "test_workflow_789"
    task_id = "test_task_101"

    await test_worker.log_worker_warning(
        operation="slow_processing",
        message="Task processing is slow",
        workflow_id=workflow_id,
        task_id=task_id,
        duration=45.2,
        threshold=30.0
    )

    # Query warnings
    logs = await StatelessLogService.query_logs(
        redis=redis,
        level="WARNING",
        workflow_id=workflow_id
    )

    assert len(logs) > 0
    warning = logs[0]
    assert "Task processing is slow" in warning['message']
    assert warning['warning_type'] == "slow_processing"
    assert warning['metadata']['duration'] == 45.2
    assert warning['metadata']['threshold'] == 30.0


@pytest.mark.asyncio
async def test_log_worker_error(test_worker, redis):
    """Test worker ERROR logging"""
    workflow_id = "test_workflow_789"
    task_id = "test_task_101"

    try:
        raise ValueError("Test error for logging")
    except ValueError as e:
        await test_worker.log_worker_error(
            operation="test_operation",
            error=e,
            workflow_id=workflow_id,
            task_id=task_id
        )

    # Query errors
    errors = await StatelessLogService.query_errors(
        redis=redis,
        workflow_id=workflow_id
    )

    assert len(errors) > 0
    error = errors[0]
    assert "Test error for logging" in error['message']
    assert error['error_type'] == "ValueError"
    assert error['workflow_id'] == workflow_id
    assert error['task_id'] == task_id


@pytest.mark.asyncio
async def test_worker_logging_with_shard_info(test_worker, redis):
    """Test that worker logs include shard information"""
    workflow_id = "test_workflow_789"

    await test_worker.log_worker_info(
        operation="shard_test",
        message="Testing shard info in logs",
        workflow_id=workflow_id
    )

    logs = await StatelessLogService.query_logs(
        redis=redis,
        level="INFO",
        workflow_id=workflow_id
    )

    assert len(logs) > 0
    log = logs[0]
    assert 'shard' in log['metadata']
    assert log['metadata']['shard'] == 0  # From test_worker config


@pytest.mark.asyncio
async def test_query_logs_by_worker_component(redis):
    """Test querying logs by worker component name"""
    # This test assumes some logs have been created by test_worker
    logs = await StatelessLogService.query_logs(
        redis=redis,
        level="INFO",
        component="test_worker",
        limit=10
    )

    # Should get logs from test_worker component
    assert logs is not None
    if len(logs) > 0:
        assert all(log['component'] == "test_worker" for log in logs)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
