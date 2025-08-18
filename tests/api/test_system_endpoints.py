"""
Tests for system management endpoints
"""

import pytest
from datetime import datetime
from unittest.mock import patch


class TestSystemEndpoints:
    """Test system management endpoints"""
    
    @pytest.mark.asyncio
    async def test_root_endpoint(self, async_client):
        """Test root endpoint returns API info"""
        response = await async_client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Gleitzeit API"
        assert data["version"] == "0.0.5"
        assert data["status"] == "running"
        assert data["documentation"] == "/docs"
    
    @pytest.mark.asyncio
    async def test_health_check(self, async_client):
        """Test health check endpoint"""
        response = await async_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        # Verify timestamp is valid ISO format
        datetime.fromisoformat(data["timestamp"])
    
    @pytest.mark.asyncio
    async def test_status_endpoint(self, async_client, mock_execution_engine):
        """Test system status endpoint"""
        response = await async_client.get("/status")
        assert response.status_code == 200
        data = response.json()
        
        # Check status structure
        assert data["status"] == "running"
        assert data["version"] == "0.0.5"
        assert "providers" in data
        assert "persistence_backend" in data
        assert "task_statistics" in data
        assert "uptime_seconds" in data
        
        # Check providers
        assert "test-python-provider" in data["providers"]
        provider = data["providers"]["test-python-provider"]
        assert provider["protocol"] == "python/v1"
        assert provider["status"] == "healthy"
        assert "methods" in provider
        
        # Check task statistics
        stats = data["task_statistics"]
        assert stats["completed"] == 100
        assert stats["failed"] == 5
        assert stats["queued"] == 2
        
        # Check uptime is positive
        assert data["uptime_seconds"] >= 0
    
    @pytest.mark.asyncio
    async def test_status_without_engine(self, async_client):
        """Test status endpoint when system not initialized"""
        from gleitzeit.api.main import app_state
        
        # Temporarily remove execution engine
        original_engine = app_state.execution_engine
        app_state.execution_engine = None
        
        response = await async_client.get("/status")
        assert response.status_code == 503
        assert response.json()["detail"] == "System not initialized"
        
        # Restore engine
        app_state.execution_engine = original_engine
    
    @pytest.mark.asyncio
    async def test_list_providers(self, async_client):
        """Test list providers endpoint"""
        response = await async_client.get("/providers")
        assert response.status_code == 200
        data = response.json()
        
        assert "providers" in data
        providers = data["providers"]
        assert len(providers) == 2
        
        # Check first provider
        python_provider = next(p for p in providers if p["id"] == "test-python-provider")
        assert python_provider["protocol"] == "python/v1"
        assert python_provider["name"] == "PythonProvider"
        assert python_provider["status"] == "healthy"
        assert "python/execute" in python_provider["methods"]
    
    @pytest.mark.asyncio
    async def test_list_protocols(self, async_client):
        """Test list protocols endpoint"""
        response = await async_client.get("/protocols")
        assert response.status_code == 200
        data = response.json()
        
        assert "protocols" in data
        protocols = data["protocols"]
        assert "python/v1" in protocols
        assert "llm/v1" in protocols
        assert "mcp/v1" in protocols
        assert "template/v1" in protocols
    
    def test_sync_root_endpoint(self, sync_client):
        """Test root endpoint with sync client"""
        response = sync_client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Gleitzeit API"
    
    def test_sync_health_check(self, sync_client):
        """Test health check with sync client"""
        response = sync_client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"


class TestSystemErrorHandling:
    """Test error handling for system endpoints"""
    
    @pytest.mark.asyncio
    async def test_providers_without_registry(self, async_client):
        """Test providers endpoint when registry not available"""
        from gleitzeit.api.main import app_state
        
        original_registry = app_state.registry
        app_state.registry = None
        
        response = await async_client.get("/providers")
        assert response.status_code == 503
        assert response.json()["detail"] == "System not initialized"
        
        app_state.registry = original_registry
    
    @pytest.mark.asyncio
    async def test_protocols_without_registry(self, async_client):
        """Test protocols endpoint when registry not available"""
        from gleitzeit.api.main import app_state
        
        original_registry = app_state.registry
        app_state.registry = None
        
        response = await async_client.get("/protocols")
        assert response.status_code == 503
        assert response.json()["detail"] == "System not initialized"
        
        app_state.registry = original_registry
    
    @pytest.mark.asyncio
    async def test_status_with_persistence_error(self, async_client, mock_persistence):
        """Test status endpoint when persistence fails"""
        # Make persistence raise an error
        mock_persistence.get_task_count_by_status.side_effect = Exception("DB Error")
        
        response = await async_client.get("/status")
        assert response.status_code == 200
        data = response.json()
        
        # Should still return status but with empty statistics
        assert data["status"] == "running"
        assert data["task_statistics"] == {}


class TestSystemMetrics:
    """Test system metrics and monitoring"""
    
    @pytest.mark.asyncio
    async def test_uptime_calculation(self, async_client):
        """Test that uptime is calculated correctly"""
        from gleitzeit.api.main import app_state
        from datetime import timedelta
        
        # Set start time to past
        original_start = app_state.start_time
        app_state.start_time = datetime.now() - timedelta(hours=1)
        
        response = await async_client.get("/status")
        assert response.status_code == 200
        data = response.json()
        
        # Uptime should be approximately 1 hour (3600 seconds)
        assert 3595 <= data["uptime_seconds"] <= 3605
        
        # Restore original
        app_state.start_time = original_start
    
    @pytest.mark.asyncio
    async def test_provider_health_status(self, async_client, mock_execution_engine):
        """Test provider health status reporting"""
        # Make one provider unhealthy
        mock_execution_engine.registry.provider_instances["test-python-provider"].is_running = lambda: False
        
        response = await async_client.get("/status")
        assert response.status_code == 200
        data = response.json()
        
        provider = data["providers"]["test-python-provider"]
        assert provider["status"] == "unhealthy"
        
        # Restore
        mock_execution_engine.registry.provider_instances["test-python-provider"].is_running = lambda: True