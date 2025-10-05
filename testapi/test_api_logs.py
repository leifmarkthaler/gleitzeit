"""
API Tests for Logging and Error Endpoints

Tests the REST API endpoints for querying logs and errors:
- GET /system/logs/errors - Query error logs
- GET /system/logs - Query logs by level
- GET /system/logs/workflow/{workflow_id} - Get workflow-specific logs
- GET /system/logs/component/{component} - Get component-specific logs
- GET /system/logs/stats - Get log statistics
"""

import pytest
import pytest_asyncio
import asyncio
import httpx
from gleitzeit.core.stateless_log_service import StatelessLogService
from gleitzeit.core.redis_cluster import get_redis_cluster
import time


BASE_URL = "http://localhost:8000/system"


@pytest_asyncio.fixture
async def redis():
    """Get Redis connection for test setup"""
    cluster = await get_redis_cluster()
    yield cluster.client
    # Close connection after test
    await cluster.client.aclose()


@pytest_asyncio.fixture
async def setup_test_logs(redis):
    """Create test logs for API testing"""
    workflow_id = "test_api_workflow_123"

    # Create various logs for testing
    await StatelessLogService.log_info(
        redis=redis,
        message="API test INFO log",
        workflow_id=workflow_id,
        component="TestComponent",
        operation="test_operation",
        metadata={"test": "info"}
    )

    await StatelessLogService.log_debug(
        redis=redis,
        message="API test DEBUG log",
        workflow_id=workflow_id,
        component="TestComponent",
        operation="test_debug",
        sample_rate=1.0  # 100% to ensure it's logged
    )

    await StatelessLogService.log_warning(
        redis=redis,
        message="API test WARNING log",
        workflow_id=workflow_id,
        component="TestComponent",
        warning_type="test_warning"
    )

    await StatelessLogService.log_error(
        redis=redis,
        message="API test ERROR log",
        workflow_id=workflow_id,
        component="TestComponent",
        error_type="TestError",
        stack_trace="Test stack trace"
    )

    # Create component-specific logs
    await StatelessLogService.log_info(
        redis=redis,
        message="Component A log",
        workflow_id=workflow_id,
        component="ComponentA"
    )

    await StatelessLogService.log_info(
        redis=redis,
        message="Component B log",
        workflow_id=workflow_id,
        component="ComponentB"
    )

    yield workflow_id

    # Cleanup handled by TTL


@pytest.mark.asyncio
async def test_get_error_logs(setup_test_logs):
    """Test GET /logs/errors endpoint"""
    workflow_id = setup_test_logs

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/logs/errors",
            params={"workflow_id": workflow_id, "limit": 10}
        )

    assert response.status_code == 200
    data = response.json()

    assert "errors" in data
    assert "total" in data
    assert isinstance(data["errors"], list)
    assert data["total"] >= 1

    # Verify error structure
    if len(data["errors"]) > 0:
        error = data["errors"][0]
        assert "log_id" in error
        assert "timestamp" in error
        assert "message" in error
        assert "error_type" in error


@pytest.mark.asyncio
async def test_get_error_logs_with_pagination(setup_test_logs):
    """Test error log pagination"""
    workflow_id = setup_test_logs

    async with httpx.AsyncClient() as client:
        # Get first page with limit 1
        response1 = await client.get(
            f"{BASE_URL}/logs/errors",
            params={"workflow_id": workflow_id, "limit": 1, "offset": 0}
        )

        # Get second page
        response2 = await client.get(
            f"{BASE_URL}/logs/errors",
            params={"workflow_id": workflow_id, "limit": 1, "offset": 1}
        )

    assert response1.status_code == 200
    assert response2.status_code == 200

    data1 = response1.json()
    data2 = response2.json()

    # Should have at least 1 error from setup
    assert len(data1["errors"]) >= 1

    # If there are multiple errors, ensure no overlap
    if len(data2["errors"]) > 0:
        ids1 = {e["log_id"] for e in data1["errors"]}
        ids2 = {e["log_id"] for e in data2["errors"]}
        assert len(ids1 & ids2) == 0


@pytest.mark.asyncio
async def test_get_logs_by_level(setup_test_logs):
    """Test GET /logs endpoint with level filter"""
    workflow_id = setup_test_logs

    async with httpx.AsyncClient() as client:
        # Test INFO level
        response = await client.get(
            f"{BASE_URL}/logs",
            params={"level": "INFO", "workflow_id": workflow_id}
        )

    assert response.status_code == 200
    data = response.json()

    assert "logs" in data
    assert "level" in data
    assert data["level"] == "INFO"
    assert "total" in data
    assert isinstance(data["logs"], list)


@pytest.mark.asyncio
async def test_get_logs_invalid_level():
    """Test /logs endpoint with invalid level"""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/logs",
            params={"level": "INVALID"}
        )

    assert response.status_code == 400
    assert "Invalid log level" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_logs_with_component_filter(setup_test_logs):
    """Test /logs endpoint with component filter"""
    workflow_id = setup_test_logs

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/logs",
            params={"level": "INFO", "component": "ComponentA"}
        )

    assert response.status_code == 200
    data = response.json()

    assert "logs" in data
    # All returned logs should be from ComponentA
    for log in data["logs"]:
        if log["workflow_id"] == workflow_id:
            assert log["component"] == "ComponentA"


@pytest.mark.asyncio
async def test_get_workflow_logs(setup_test_logs):
    """Test GET /logs/workflow/{workflow_id} endpoint"""
    workflow_id = setup_test_logs

    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/logs/workflow/{workflow_id}")

    assert response.status_code == 200
    data = response.json()

    assert "workflow_id" in data
    assert data["workflow_id"] == workflow_id
    assert "logs" in data
    assert "count" in data
    assert "total" in data

    # Should have logs from multiple levels
    assert data["total"] >= 4  # INFO, DEBUG, WARNING, ERROR


@pytest.mark.asyncio
async def test_get_workflow_logs_with_level_filter(setup_test_logs):
    """Test workflow logs with level filter"""
    workflow_id = setup_test_logs

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/logs/workflow/{workflow_id}",
            params={"level": "WARNING"}
        )

    assert response.status_code == 200
    data = response.json()

    assert "logs" in data
    # All logs should be WARNING level
    for log in data["logs"]:
        assert log["level"] == "WARNING"


@pytest.mark.asyncio
async def test_get_component_logs(setup_test_logs):
    """Test GET /logs/component/{component} endpoint"""
    workflow_id = setup_test_logs

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/logs/component/TestComponent",
            params={"level": "INFO"}
        )

    assert response.status_code == 200
    data = response.json()

    assert "component" in data
    assert data["component"] == "TestComponent"
    assert "logs" in data
    assert "total" in data

    # All logs should be from TestComponent
    for log in data["logs"]:
        assert log["component"] == "TestComponent"


@pytest.mark.asyncio
async def test_get_log_statistics(setup_test_logs):
    """Test GET /logs/stats endpoint"""
    workflow_id = setup_test_logs

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/logs/stats",
            params={"workflow_id": workflow_id}
        )

    assert response.status_code == 200
    data = response.json()

    assert "stats" in data
    assert "total" in data
    assert "filters" in data

    # Should have counts for each level
    stats = data["stats"]
    assert "debug" in stats
    assert "info" in stats
    assert "warning" in stats
    assert "error" in stats

    # At least one of each from setup
    assert stats["info"] >= 1
    assert stats["warning"] >= 1
    assert stats["error"] >= 1


@pytest.mark.asyncio
async def test_get_log_statistics_with_component_filter(setup_test_logs):
    """Test log statistics with component filter"""
    workflow_id = setup_test_logs

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/logs/stats",
            params={"workflow_id": workflow_id, "component": "ComponentA"}
        )

    assert response.status_code == 200
    data = response.json()

    assert "stats" in data
    assert data["filters"]["component"] == "ComponentA"


@pytest.mark.asyncio
async def test_get_logs_with_time_range(setup_test_logs):
    """Test querying logs with time range"""
    workflow_id = setup_test_logs

    # Get current time with a wide range to catch test logs
    start_time = int(time.time() * 1000) - 60000  # 60 seconds ago
    end_time = int(time.time() * 1000) + 10000    # 10 seconds from now

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/logs",
            params={
                "level": "INFO",
                "workflow_id": workflow_id,
                "start_time": start_time,
                "end_time": end_time
            }
        )

    assert response.status_code == 200
    data = response.json()

    assert "logs" in data
    assert "filters" in data
    assert data["filters"]["start_time"] == start_time
    assert data["filters"]["end_time"] == end_time


@pytest.mark.asyncio
async def test_error_logs_without_workflow():
    """Test querying global error logs (no workflow filter)"""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/logs/errors",
            params={"limit": 10}
        )

    assert response.status_code == 200
    data = response.json()

    assert "errors" in data
    assert "total" in data
    # Should work even without workflow_id filter


@pytest.mark.asyncio
async def test_get_logs_pagination_parameters(setup_test_logs):
    """Test that pagination parameters are returned correctly"""
    workflow_id = setup_test_logs

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/logs",
            params={"level": "INFO", "workflow_id": workflow_id, "limit": 5, "offset": 2}
        )

    assert response.status_code == 200
    data = response.json()

    assert data["limit"] == 5
    assert data["offset"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
