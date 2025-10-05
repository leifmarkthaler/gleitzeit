"""
Integration tests for error logging.

Tests the error logging functionality in StatelessLogService including:
- Error log storage and retrieval
- Global and workflow-specific error indexing
- Error querying with filters
- Metadata and stack trace handling
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

    # Clean up any existing test error logs
    test_workflow = "test_workflow_error_123"
    shard = default_sharding.get_shard(test_workflow)

    # Delete test error keys
    await redis_conn.delete(f"{{shard:{shard}}}:log:workflow:{test_workflow}:errors")
    await redis_conn.delete(f"{{shard:0}}:log:global:error")

    yield redis_conn

    # Cleanup
    await redis_conn.aclose()


@pytest.mark.asyncio
async def test_log_error_basic(redis):
    """Test basic error logging"""
    workflow_id = "test_workflow_error_123"
    task_id = "test_task_456"

    log_id = await StatelessLogService.log_error(
        redis=redis,
        message="Test error occurred",
        workflow_id=workflow_id,
        task_id=task_id,
        component="TestComponent",
        error_type="ValueError",
        stack_trace="Traceback (most recent call last):\n  File test.py, line 1",
        metadata={"context": "test"}
    )

    assert log_id is not None

    # Query the error
    errors = await StatelessLogService.query_errors(
        redis=redis,
        workflow_id=workflow_id,
        limit=10
    )

    assert len(errors) > 0
    error = errors[0]
    assert error['message'] == "Test error occurred"
    assert error['workflow_id'] == workflow_id
    assert error['task_id'] == task_id
    assert error['component'] == "TestComponent"
    assert error['error_type'] == "ValueError"
    assert "Traceback" in error['stack_trace']
    assert error['metadata']['context'] == "test"


@pytest.mark.asyncio
async def test_log_error_without_workflow(redis):
    """Test error logging without workflow_id (system errors)"""
    log_id = await StatelessLogService.log_error(
        redis=redis,
        message="System error occurred",
        component="SystemComponent",
        error_type="ConnectionError",
        metadata={"system": "redis"}
    )

    assert log_id is not None

    # Query global errors
    errors = await StatelessLogService.query_errors(
        redis=redis,
        limit=10
    )

    assert len(errors) > 0
    # Find our error (there might be others from previous tests)
    system_error = next((e for e in errors if e['message'] == "System error occurred"), None)
    assert system_error is not None
    assert system_error['workflow_id'] == ""
    assert system_error['error_type'] == "ConnectionError"


@pytest.mark.asyncio
async def test_query_errors_with_time_range(redis):
    """Test querying errors with time range filter"""
    workflow_id = "test_workflow_error_123"

    # Log an error and capture its timestamp
    log_id = await StatelessLogService.log_error(
        redis=redis,
        message="Time range error test",
        workflow_id=workflow_id,
        component="TestComponent",
        error_type="TimeoutError"
    )

    # Extract timestamp from log_id
    log_timestamp = int(log_id.split('-')[0])

    # Query with time range
    start_time = log_timestamp - 5000  # 5 seconds before
    end_time = log_timestamp + 5000    # 5 seconds after

    errors = await StatelessLogService.query_errors(
        redis=redis,
        workflow_id=workflow_id,
        start_time=start_time,
        end_time=end_time
    )

    assert len(errors) > 0
    error = errors[0]
    assert start_time <= error['timestamp'] <= end_time
    assert error['message'] == "Time range error test"


@pytest.mark.asyncio
async def test_query_errors_pagination(redis):
    """Test error query pagination"""
    workflow_id = "test_workflow_error_123"

    # Log 10 errors
    for i in range(10):
        await StatelessLogService.log_error(
            redis=redis,
            message=f"Pagination error {i}",
            workflow_id=workflow_id,
            component="TestComponent",
            error_type="TestError"
        )

    # Query first page (limit 5)
    page1 = await StatelessLogService.query_errors(
        redis=redis,
        workflow_id=workflow_id,
        limit=5,
        offset=0
    )

    # Query second page
    page2 = await StatelessLogService.query_errors(
        redis=redis,
        workflow_id=workflow_id,
        limit=5,
        offset=5
    )

    assert len(page1) == 5
    assert len(page2) >= 5

    # Ensure pages don't overlap
    page1_ids = {e['log_id'] for e in page1}
    page2_ids = {e['log_id'] for e in page2}
    assert len(page1_ids & page2_ids) == 0


@pytest.mark.asyncio
async def test_get_error_count(redis):
    """Test getting error count"""
    workflow_id = "test_workflow_error_123"

    # Get initial count
    initial_count = await StatelessLogService.get_error_count(
        redis=redis,
        workflow_id=workflow_id
    )

    # Log 3 more errors
    for i in range(3):
        await StatelessLogService.log_error(
            redis=redis,
            message=f"Count test error {i}",
            workflow_id=workflow_id,
            component="TestComponent"
        )

    # Get new count
    new_count = await StatelessLogService.get_error_count(
        redis=redis,
        workflow_id=workflow_id
    )

    assert new_count >= initial_count + 3


@pytest.mark.asyncio
async def test_error_with_complete_stack_trace(redis):
    """Test error logging with complete stack trace"""
    workflow_id = "test_workflow_error_123"

    try:
        # Generate a real exception with stack trace
        def inner_function():
            raise ValueError("Test exception with stack trace")

        def outer_function():
            inner_function()

        outer_function()
    except ValueError as e:
        import traceback
        stack_trace = traceback.format_exc()

        log_id = await StatelessLogService.log_error(
            redis=redis,
            message=str(e),
            workflow_id=workflow_id,
            component="TestComponent",
            error_type=type(e).__name__,
            stack_trace=stack_trace,
            metadata={"test": "stack_trace"}
        )

        # Query and verify
        errors = await StatelessLogService.query_errors(
            redis=redis,
            workflow_id=workflow_id,
            limit=1
        )

        assert len(errors) > 0
        error = errors[0]
        assert "Test exception with stack trace" in error['message']
        assert "inner_function" in error['stack_trace']
        assert "outer_function" in error['stack_trace']
        assert error['error_type'] == "ValueError"


@pytest.mark.asyncio
async def test_error_default_values(redis):
    """Test error logging with minimal parameters"""
    # Log error with only message
    log_id = await StatelessLogService.log_error(
        redis=redis,
        message="Minimal error"
    )

    assert log_id is not None

    # Query global errors
    errors = await StatelessLogService.query_errors(
        redis=redis,
        limit=10
    )

    # Find our error
    minimal_error = next((e for e in errors if e['message'] == "Minimal error"), None)
    assert minimal_error is not None
    assert minimal_error['component'] == "system"  # default
    assert minimal_error['error_type'] == "UnknownError"  # default
    assert minimal_error['workflow_id'] == ""
    assert minimal_error['task_id'] == ""


@pytest.mark.asyncio
async def test_error_with_complex_metadata(redis):
    """Test error logging with complex metadata"""
    workflow_id = "test_workflow_error_123"

    complex_metadata = {
        "request": {
            "url": "http://example.com/api",
            "method": "POST",
            "headers": {"Authorization": "Bearer ***"}
        },
        "response": {
            "status": 500,
            "body": {"error": "Internal server error"}
        },
        "retry_count": 3,
        "duration_ms": 1234,
        "tags": ["production", "critical"]
    }

    log_id = await StatelessLogService.log_error(
        redis=redis,
        message="API call failed",
        workflow_id=workflow_id,
        component="ApiClient",
        error_type="ApiError",
        metadata=complex_metadata
    )

    # Query and verify metadata is preserved
    errors = await StatelessLogService.query_errors(
        redis=redis,
        workflow_id=workflow_id,
        limit=1
    )

    assert len(errors) > 0
    error = errors[0]
    assert error['metadata']['request']['url'] == "http://example.com/api"
    assert error['metadata']['response']['status'] == 500
    assert error['metadata']['retry_count'] == 3
    assert "production" in error['metadata']['tags']


@pytest.mark.asyncio
async def test_global_vs_workflow_errors(redis):
    """Test that global and workflow-specific error queries work independently"""
    workflow_id = "test_workflow_error_123"

    # Log workflow error
    await StatelessLogService.log_error(
        redis=redis,
        message="Workflow error",
        workflow_id=workflow_id,
        component="WorkflowComponent"
    )

    # Log system error (no workflow)
    await StatelessLogService.log_error(
        redis=redis,
        message="System error",
        component="SystemComponent"
    )

    # Query workflow errors
    workflow_errors = await StatelessLogService.query_errors(
        redis=redis,
        workflow_id=workflow_id
    )

    # Query global errors
    global_errors = await StatelessLogService.query_errors(
        redis=redis
    )

    # Workflow errors should only contain workflow-specific errors
    assert len(workflow_errors) > 0
    assert all(e['workflow_id'] == workflow_id for e in workflow_errors)

    # Global errors should contain both
    assert len(global_errors) >= len(workflow_errors)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
