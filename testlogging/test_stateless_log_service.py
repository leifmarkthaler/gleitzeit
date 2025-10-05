"""
Unit tests for StatelessLogService (both error and non-error logging).

Tests the core logging service that writes to Redis and provides
queryable structured logs across all log levels.
"""

import pytest
import pytest_asyncio
import asyncio
import time
from datetime import datetime
from gleitzeit.core.stateless_log_service import StatelessLogService
from gleitzeit.core.sharding import default_sharding
import redis.asyncio as aioredis


@pytest_asyncio.fixture
async def redis():
    """Create Redis connection for tests"""
    # Create a simple Redis connection for testing
    redis_conn = await aioredis.from_url(
        "redis://localhost:6379",
        decode_responses=False
    )

    # Clean up any existing test logs
    test_workflow = "test_workflow_123"
    shard = default_sharding.get_shard(test_workflow)

    # Delete test log keys
    for level in ["debug", "info", "warning", "error"]:
        await redis_conn.delete(f"{{shard:{shard}}}:log:workflow:{test_workflow}:{level}")
        await redis_conn.delete(f"{{shard:0}}:log:global:{level}")
        await redis_conn.delete(f"{{shard:0}}:log:component:TestComponent:{level}")

    yield redis_conn

    # Cleanup
    await redis_conn.aclose()


@pytest.mark.asyncio
async def test_log_info(redis):
    """Test INFO level logging"""
    workflow_id = "test_workflow_123"
    task_id = "test_task_456"

    log_id = await StatelessLogService.log_info(
        redis=redis,
        message="Test INFO message",
        workflow_id=workflow_id,
        task_id=task_id,
        component="TestComponent",
        operation="test_operation",
        metadata={"key": "value"}
    )

    assert log_id is not None

    # Query the log
    logs = await StatelessLogService.query_logs(
        redis=redis,
        level="INFO",
        workflow_id=workflow_id,
        limit=10
    )

    assert len(logs) > 0
    assert logs[0]['message'] == "Test INFO message"
    assert logs[0]['workflow_id'] == workflow_id
    assert logs[0]['task_id'] == task_id
    assert logs[0]['component'] == "TestComponent"
    assert logs[0]['operation'] == "test_operation"
    assert logs[0]['metadata']['key'] == "value"


@pytest.mark.asyncio
async def test_log_debug_with_sampling(redis):
    """Test DEBUG level logging with sampling"""
    workflow_id = "test_workflow_123"

    # Log 100 DEBUG messages with 100% sampling
    logged_count = 0
    for i in range(100):
        log_id = await StatelessLogService.log_debug(
            redis=redis,
            message=f"Debug message {i}",
            workflow_id=workflow_id,
            component="TestComponent",
            operation="debug_test",
            sample_rate=1.0  # 100% sampling
        )
        if log_id:
            logged_count += 1

    assert logged_count == 100

    # Test with 0% sampling (should log nothing)
    log_id = await StatelessLogService.log_debug(
        redis=redis,
        message="This should not be logged",
        workflow_id=workflow_id,
        component="TestComponent",
        sample_rate=0.0
    )
    assert log_id is None


@pytest.mark.asyncio
async def test_log_warning(redis):
    """Test WARNING level logging"""
    workflow_id = "test_workflow_123"
    task_id = "test_task_456"

    log_id = await StatelessLogService.log_warning(
        redis=redis,
        message="Test WARNING message",
        workflow_id=workflow_id,
        task_id=task_id,
        component="TestComponent",
        warning_type="slow_execution",
        metadata={"duration": 45.2}
    )

    assert log_id is not None

    # Query warnings
    logs = await StatelessLogService.query_logs(
        redis=redis,
        level="WARNING",
        workflow_id=workflow_id
    )

    assert len(logs) > 0
    warning = logs[0]
    assert warning['message'] == "Test WARNING message"
    assert warning['warning_type'] == "slow_execution"
    assert warning['metadata']['duration'] == 45.2


@pytest.mark.asyncio
async def test_log_error(redis):
    """Test ERROR level logging"""
    workflow_id = "test_workflow_123"
    task_id = "test_task_456"

    log_id = await StatelessLogService.log_error(
        redis=redis,
        message="Test ERROR message",
        workflow_id=workflow_id,
        task_id=task_id,
        component="TestComponent",
        error_type="ValueError",
        stack_trace="Traceback (most recent call last):\n  File...",
        metadata={"error_code": "E001"}
    )

    assert log_id is not None

    # Query errors
    errors = await StatelessLogService.query_errors(
        redis=redis,
        workflow_id=workflow_id
    )

    assert len(errors) > 0
    error = errors[0]
    assert error['message'] == "Test ERROR message"
    assert error['error_type'] == "ValueError"
    assert error['metadata']['error_code'] == "E001"


@pytest.mark.asyncio
async def test_query_logs_by_component(redis):
    """Test querying logs by component"""
    workflow_id = "test_workflow_123"

    # Log messages from different components
    await StatelessLogService.log_info(
        redis=redis,
        message="ComponentA message",
        workflow_id=workflow_id,
        component="ComponentA",
        operation="test"
    )

    await StatelessLogService.log_info(
        redis=redis,
        message="ComponentB message",
        workflow_id=workflow_id,
        component="ComponentB",
        operation="test"
    )

    # Query by component
    logs = await StatelessLogService.query_logs(
        redis=redis,
        level="INFO",
        component="ComponentA"
    )

    assert len(logs) > 0
    assert all(log['component'] == "ComponentA" for log in logs)


@pytest.mark.asyncio
async def test_query_logs_with_time_range(redis):
    """Test querying logs with time range filter"""
    workflow_id = "test_workflow_123"

    # Log a message and capture its actual timestamp
    log_id = await StatelessLogService.log_info(
        redis=redis,
        message="Time range test",
        workflow_id=workflow_id,
        component="TestComponent"
    )

    # Extract timestamp from log_id (format: timestamp-uuid)
    log_timestamp = int(log_id.split('-')[0])

    # Query with time range around the log timestamp
    start_time = log_timestamp - 5000  # 5 seconds before
    end_time = log_timestamp + 5000    # 5 seconds after

    # Query with time range
    logs = await StatelessLogService.query_logs(
        redis=redis,
        level="INFO",
        workflow_id=workflow_id,
        start_time=start_time,
        end_time=end_time
    )

    assert len(logs) > 0
    log = logs[0]
    assert start_time <= log['timestamp'] <= end_time
    assert log['message'] == "Time range test"


@pytest.mark.asyncio
async def test_get_log_count(redis):
    """Test getting log counts"""
    workflow_id = "test_workflow_123"

    # Log multiple messages
    for i in range(5):
        await StatelessLogService.log_info(
            redis=redis,
            message=f"Count test {i}",
            workflow_id=workflow_id,
            component="TestComponent"
        )

    # Get count
    count = await StatelessLogService.get_log_count(
        redis=redis,
        level="INFO",
        workflow_id=workflow_id
    )

    assert count >= 5


@pytest.mark.asyncio
async def test_query_logs_pagination(redis):
    """Test log query pagination"""
    workflow_id = "test_workflow_123"

    # Log 20 messages
    for i in range(20):
        await StatelessLogService.log_info(
            redis=redis,
            message=f"Pagination test {i}",
            workflow_id=workflow_id,
            component="TestComponent"
        )

    # Query first page (limit 10)
    page1 = await StatelessLogService.query_logs(
        redis=redis,
        level="INFO",
        workflow_id=workflow_id,
        limit=10,
        offset=0
    )

    # Query second page
    page2 = await StatelessLogService.query_logs(
        redis=redis,
        level="INFO",
        workflow_id=workflow_id,
        limit=10,
        offset=10
    )

    assert len(page1) == 10
    assert len(page2) >= 10
    # Ensure pages don't overlap
    page1_ids = {log['log_id'] for log in page1}
    page2_ids = {log['log_id'] for log in page2}
    assert len(page1_ids & page2_ids) == 0


@pytest.mark.asyncio
async def test_global_indexing(redis):
    """Test that logs are indexed globally on shard 0"""
    workflow_id = "test_workflow_123"

    await StatelessLogService.log_info(
        redis=redis,
        message="Global index test",
        workflow_id=workflow_id,
        component="TestComponent"
    )

    # Check global index exists
    global_index = f"{{shard:0}}:log:global:info"
    exists = await redis.exists(global_index)
    assert exists == 1


@pytest.mark.asyncio
async def test_component_indexing(redis):
    """Test that logs are indexed by component"""
    workflow_id = "test_workflow_123"

    await StatelessLogService.log_info(
        redis=redis,
        message="Component index test",
        workflow_id=workflow_id,
        component="TestComponent"
    )

    # Check component index exists
    component_index = f"{{shard:0}}:log:component:TestComponent:info"
    exists = await redis.exists(component_index)
    assert exists == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
