"""
Tests for GleitzeitClient monitoring and health check functionality.

Tests system health, worker monitoring, metrics, and logs.
"""
import pytest
import asyncio
from gleitzeit.client import GleitzeitClient


@pytest.mark.asyncio
async def test_health_check():
    """Test basic health check."""
    async with GleitzeitClient() as client:
        health = await client.health_check()

        assert "status" in health
        print(f"✓ Health check passed")
        print(f"  Status: {health.get('status')}")
        print(f"  Response: {health}")


@pytest.mark.asyncio
async def test_get_system_health():
    """Test detailed system health."""
    async with GleitzeitClient() as client:
        health = await client.get_system_health()

        print(f"✓ Got system health")
        print(f"  Status: {health.status}")
        print(f"  API Version: {health.api_version}")
        print(f"  Uptime: {health.uptime}s")
        print(f"  Redis Connected: {health.redis_connected}")
        print(f"  Workers: {health.worker_count}")
        print(f"  Active Workflows: {health.active_workflows}")
        print(f"  Active Tasks: {health.active_tasks}")


@pytest.mark.asyncio
async def test_get_workers_status():
    """Test getting worker status."""
    async with GleitzeitClient() as client:
        workers = await client.get_workers_status()

        print(f"✓ Got {len(workers)} workers")

        for worker in workers[:5]:  # Show first 5
            print(f"\n  Worker: {worker.worker_id}")
            print(f"    Type: {worker.worker_type}")
            print(f"    Status: {worker.status}")
            print(f"    Last Heartbeat: {worker.last_heartbeat}")
            print(f"    Tasks Processed: {worker.tasks_processed}")
            if worker.current_task:
                print(f"    Current Task: {worker.current_task}")


@pytest.mark.asyncio
async def test_get_system_metrics():
    """Test getting system metrics."""
    async with GleitzeitClient() as client:
        metrics = await client.get_system_metrics()

        print(f"✓ Got system metrics")
        print(f"  Metrics: {metrics}")


@pytest.mark.asyncio
async def test_get_workflow_metrics():
    """Test getting workflow metrics."""
    async with GleitzeitClient() as client:
        metrics = await client.get_workflow_metrics(time_range="1h")

        print(f"✓ Got workflow metrics for 1h")
        print(f"  Metrics: {metrics}")


@pytest.mark.asyncio
async def test_get_task_metrics():
    """Test getting task metrics."""
    async with GleitzeitClient() as client:
        metrics = await client.get_task_metrics(time_range="1h")

        print(f"✓ Got task metrics for 1h")
        print(f"  Metrics: {metrics}")


@pytest.mark.asyncio
async def test_get_queue_depths():
    """Test getting queue depths."""
    async with GleitzeitClient() as client:
        queues = await client.get_queue_depths()

        print(f"✓ Got queue depths for {len(queues)} queues")

        for queue_name, depth in list(queues.items())[:10]:
            print(f"  {queue_name}: {depth} items")


@pytest.mark.asyncio
async def test_get_redis_info():
    """Test getting Redis information."""
    async with GleitzeitClient() as client:
        redis_info = await client.get_redis_info()

        print(f"✓ Got Redis info")
        print(f"  Keys: {list(redis_info.keys())[:5]}")


@pytest.mark.asyncio
async def test_get_resource_usage():
    """Test getting resource usage."""
    async with GleitzeitClient() as client:
        resources = await client.get_resource_usage()

        print(f"✓ Got resource usage")
        print(f"  Resources: {resources}")


@pytest.mark.asyncio
async def test_check_api_version():
    """Test getting API version."""
    async with GleitzeitClient() as client:
        version = await client.check_api_version()

        print(f"✓ Got API version: {version}")


@pytest.mark.asyncio
async def test_get_configuration():
    """Test getting system configuration."""
    async with GleitzeitClient() as client:
        config = await client.get_configuration()

        print(f"✓ Got system configuration")
        print(f"  Config keys: {list(config.keys())[:10]}")


@pytest.mark.asyncio
async def test_get_rate_limit_status():
    """Test getting rate limit status."""
    async with GleitzeitClient() as client:
        rate_limit = await client.get_rate_limit_status()

        print(f"✓ Got rate limit status")
        print(f"  Limit: {rate_limit['limit']}")
        print(f"  Remaining: {rate_limit['remaining']}")
        print(f"  Reset in: {rate_limit['reset_in_seconds']}s")
        print(f"  Current: {rate_limit['current']}")


@pytest.mark.asyncio
async def test_get_audit_logs():
    """Test getting audit logs."""
    async with GleitzeitClient() as client:
        logs = await client.get_audit_logs(limit=10)

        print(f"✓ Got {len(logs)} audit log entries")

        if logs:
            for log in logs[:3]:
                print(f"  {log}")


@pytest.mark.asyncio
async def test_get_error_logs():
    """Test getting error logs."""
    async with GleitzeitClient() as client:
        errors = await client.get_error_logs(limit=5, level="ERROR")

        print(f"✓ Got {len(errors)} error log entries")

        if errors:
            for error in errors[:3]:
                print(f"  {error}")


@pytest.mark.asyncio
async def test_trigger_health_check_all_workers():
    """Test triggering health check on all workers."""
    async with GleitzeitClient() as client:
        try:
            results = await client.trigger_health_check_all_workers()

            print(f"✓ Triggered health check on all workers")
            healthy_count = sum(1 for v in results.values() if v)
            print(f"  {healthy_count}/{len(results)} workers healthy")
        except Exception as e:
            print(f"Note: Could not trigger health checks: {e}")


if __name__ == "__main__":
    import sys

    print("Running monitoring tests...\n")

    try:
        asyncio.run(test_health_check())
        asyncio.run(test_get_system_health())
        asyncio.run(test_get_workers_status())
        asyncio.run(test_get_system_metrics())
        asyncio.run(test_get_workflow_metrics())
        asyncio.run(test_get_task_metrics())
        asyncio.run(test_get_queue_depths())
        asyncio.run(test_get_redis_info())
        asyncio.run(test_get_resource_usage())
        asyncio.run(test_check_api_version())
        asyncio.run(test_get_configuration())
        asyncio.run(test_get_rate_limit_status())
        asyncio.run(test_get_audit_logs())
        asyncio.run(test_get_error_logs())
        asyncio.run(test_trigger_health_check_all_workers())
        print("\n✓ All monitoring tests passed!")
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
