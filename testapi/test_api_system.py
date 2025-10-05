"""
Direct API tests for system monitoring endpoints.

Tests the actual HTTP endpoints without using the client library.
"""
import pytest
import httpx
import asyncio

BASE_URL = "http://localhost:8000"


async def create_test_session():
    """Helper to create a test session"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/auth/session/create",
            json={"username": "system_test_user", "password": ""}
        )
        return response.json()["session_id"]


@pytest.mark.asyncio
async def test_system_status():
    """Test GET /system/status"""
    session_id = await create_test_session()

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/system/status",
            headers={"X-Session-ID": session_id}
        )

        assert response.status_code == 200
        data = response.json()
        assert "orchestrator" in data
        assert "workers" in data
        assert "queues" in data
        print(f"✓ System status:")
        print(f"  Workers: {len(data['workers'])}")
        print(f"  Queues: {len(data['queues'])}")


@pytest.mark.asyncio
async def test_system_metrics():
    """Test GET /system/metrics"""
    session_id = await create_test_session()

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/system/metrics",
            headers={"X-Session-ID": session_id}
        )

        assert response.status_code == 200
        data = response.json()
        assert "workflows" in data
        assert "tasks" in data

        workflows = data["workflows"]
        tasks = data["tasks"]

        print(f"✓ System metrics:")
        print(f"  Workflows: {workflows['total']} total, {workflows['running']} running")
        print(f"  Tasks: {tasks['total']} total, {tasks['running']} running")


@pytest.mark.asyncio
async def test_list_workers():
    """Test GET /system/workers"""
    session_id = await create_test_session()

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/system/workers",
            headers={"X-Session-ID": session_id}
        )

        assert response.status_code == 200
        data = response.json()
        assert "count" in data
        assert "workers" in data

        print(f"✓ Workers: {data['count']} registered")
        for worker in data["workers"][:3]:
            print(f"  - {worker.get('worker_id', 'unknown')}: {worker.get('worker_type', 'unknown')}")


@pytest.mark.asyncio
async def test_workflow_metrics():
    """Test GET /system/metrics/workflows"""
    session_id = await create_test_session()

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/system/metrics/workflows",
            params={"time_range": "1h"},
            headers={"X-Session-ID": session_id}
        )

        assert response.status_code == 200
        data = response.json()
        assert "time_range" in data
        assert "total_workflows" in data
        assert "by_status" in data

        print(f"✓ Workflow metrics (1h):")
        print(f"  Total: {data['total_workflows']}")
        print(f"  By status: {data['by_status']}")


@pytest.mark.asyncio
async def test_task_metrics():
    """Test GET /system/metrics/tasks"""
    session_id = await create_test_session()

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/system/metrics/tasks",
            params={"time_range": "1h"},
            headers={"X-Session-ID": session_id}
        )

        assert response.status_code == 200
        data = response.json()
        assert "time_range" in data
        assert "total_tasks" in data
        assert "by_status" in data
        assert "by_protocol" in data

        print(f"✓ Task metrics (1h):")
        print(f"  Total: {data['total_tasks']}")
        print(f"  By status: {data['by_status']}")
        print(f"  By protocol: {data['by_protocol']}")


@pytest.mark.asyncio
async def test_redis_info():
    """Test GET /system/redis/info"""
    session_id = await create_test_session()

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/system/redis/info",
            headers={"X-Session-ID": session_id}
        )

        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert "uptime_seconds" in data
        assert "connected_clients" in data

        print(f"✓ Redis info:")
        print(f"  Version: {data['version']}")
        print(f"  Uptime: {data['uptime_seconds']}s")
        print(f"  Clients: {data['connected_clients']}")


@pytest.mark.asyncio
async def test_queue_depths():
    """Test GET /system/queues"""
    session_id = await create_test_session()

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/system/queues",
            headers={"X-Session-ID": session_id}
        )

        assert response.status_code == 200
        data = response.json()
        assert "queues" in data
        assert "total_queues" in data
        assert "total_messages" in data

        print(f"✓ Queue depths:")
        print(f"  Total queues: {data['total_queues']}")
        print(f"  Total messages: {data['total_messages']}")

        # Show first few queues
        for queue, depth in list(data['queues'].items())[:5]:
            print(f"  {queue}: {depth}")


@pytest.mark.asyncio
async def test_get_configuration():
    """Test GET /system/config"""
    session_id = await create_test_session()

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/system/config",
            headers={"X-Session-ID": session_id}
        )

        assert response.status_code == 200
        data = response.json()
        # Should have sanitized config (no secrets)
        print(f"✓ System config (sanitized):")
        print(f"  Keys: {list(data.keys())}")


@pytest.mark.asyncio
async def test_resource_usage():
    """Test GET /system/resources"""
    session_id = await create_test_session()

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/system/resources",
            headers={"X-Session-ID": session_id}
        )

        assert response.status_code == 200
        data = response.json()
        assert "cpu" in data
        assert "memory" in data
        assert "disk" in data

        print(f"✓ Resource usage:")
        print(f"  CPU: {data['cpu']['percent']}%")
        print(f"  Memory: {data['memory']['percent']}%")
        print(f"  Disk: {data['disk']['percent']}%")


@pytest.mark.asyncio
async def test_worker_health_check():
    """Test POST /system/workers/health-check"""
    session_id = await create_test_session()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/system/workers/health-check",
            headers={"X-Session-ID": session_id}
        )

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "healthy" in data
        assert "unhealthy" in data
        assert "total" in data

        print(f"✓ Worker health check:")
        print(f"  Healthy: {data['healthy']}/{data['total']}")


@pytest.mark.asyncio
async def test_get_active_sessions():
    """Test GET /system/sessions"""
    session_id = await create_test_session()

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/system/sessions",
            headers={"X-Session-ID": session_id}
        )

        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data
        assert "total" in data
        assert "active" in data

        print(f"✓ Active sessions: {data['active']}/{data['total']}")


if __name__ == "__main__":
    print("Running system API tests...\n")

    asyncio.run(test_system_status())
    asyncio.run(test_system_metrics())
    asyncio.run(test_list_workers())
    asyncio.run(test_workflow_metrics())
    asyncio.run(test_task_metrics())
    asyncio.run(test_redis_info())
    asyncio.run(test_queue_depths())
    asyncio.run(test_get_configuration())
    asyncio.run(test_resource_usage())
    asyncio.run(test_worker_health_check())
    asyncio.run(test_get_active_sessions())

    print("\n✓ All system API tests passed!")
