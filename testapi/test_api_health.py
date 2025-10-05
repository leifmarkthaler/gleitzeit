"""
Direct API tests for health endpoints.

Tests the actual HTTP endpoints without using the client library.
"""
import pytest
import httpx
import asyncio

BASE_URL = "http://localhost:8000"


@pytest.mark.asyncio
async def test_root_endpoint():
    """Test GET /"""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/")

        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert "status" in data
        assert data["name"] == "Gleitzeit API"
        assert data["version"] == "0.0.7-secure"
        print(f"✓ Root endpoint: {data['name']} v{data['version']}")


@pytest.mark.asyncio
async def test_health_check():
    """Test GET /health/"""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/health/")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "components" in data
        assert "api" in data["components"]
        assert "redis" in data["components"]
        print(f"✓ Health check: {data['status']}")
        print(f"  API: {data['components']['api']}")
        print(f"  Redis: {data['components']['redis']}")


@pytest.mark.asyncio
async def test_readiness_check():
    """Test GET /health/ready"""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/health/ready")

        assert response.status_code in [200, 503]
        data = response.json()
        assert "ready" in data
        print(f"✓ Readiness check: {data['ready']}")


@pytest.mark.asyncio
async def test_liveness_check():
    """Test GET /health/live"""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/health/live")

        assert response.status_code == 200
        data = response.json()
        assert "alive" in data
        assert data["alive"] is True
        print(f"✓ Liveness check: alive")


@pytest.mark.asyncio
async def test_detailed_health():
    """Test GET /health/detailed"""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/health/detailed")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "redis_connected" in data
        assert "worker_count" in data
        assert "active_workflows" in data
        assert "redis_info" in data

        print(f"✓ Detailed health:")
        print(f"  Status: {data['status']}")
        print(f"  Version: {data['version']}")
        print(f"  Redis: {'connected' if data['redis_connected'] else 'disconnected'}")
        print(f"  Workers: {data['worker_count']}")
        print(f"  Active workflows: {data['active_workflows']}")


@pytest.mark.asyncio
async def test_cluster_health():
    """Test GET /health/cluster"""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/health/cluster")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "redis_connected" in data
        assert "cluster_info" in data
        assert "services" in data

        cluster_info = data["cluster_info"]
        print(f"✓ Cluster health: {data['status']}")
        print(f"  Total services: {cluster_info['total_services']}")
        print(f"  Healthy services: {cluster_info['healthy_services']}")
        print(f"  API instances: {cluster_info['api_instances']}")
        print(f"  UI instances: {cluster_info['ui_instances']}")
        print(f"  Worker types: {cluster_info['worker_types']}")


if __name__ == "__main__":
    print("Running health API tests...\n")

    asyncio.run(test_root_endpoint())
    asyncio.run(test_health_check())
    asyncio.run(test_readiness_check())
    asyncio.run(test_liveness_check())
    asyncio.run(test_detailed_health())
    asyncio.run(test_cluster_health())

    print("\n✓ All health API tests passed!")
