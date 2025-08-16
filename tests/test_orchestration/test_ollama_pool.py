"""
Tests for Ollama Pool Manager
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
import aiohttp

from gleitzeit.orchestration.ollama_pool import (
    OllamaPoolManager, 
    LoadBalancingStrategy,
    InstanceState,
    OllamaInstance
)


class TestOllamaPoolManager:
    """Test multi-instance Ollama orchestration"""
    
    @pytest.fixture
    def instances_config(self):
        """Sample instances configuration"""
        return [
            {
                "id": "local",
                "url": "http://localhost:11434",
                "models": ["llama3.2", "codellama"],
                "max_concurrent": 5,
                "tags": ["local", "cpu"]
            },
            {
                "id": "gpu-1",
                "url": "http://gpu1:11434",
                "models": ["llama3.2:70b", "mixtral"],
                "max_concurrent": 2,
                "tags": ["remote", "gpu", "high-memory"]
            },
            {
                "id": "gpu-2",
                "url": "http://gpu2:11434",
                "models": ["llava", "bakllava"],
                "max_concurrent": 1,
                "tags": ["remote", "gpu", "vision"]
            }
        ]
        
    @pytest.fixture
    async def pool_manager(self, instances_config):
        """Create pool manager instance"""
        manager = OllamaPoolManager(
            instances=instances_config,
            health_check_interval=5
        )
        # Mock the HTTP session
        manager.session = AsyncMock(spec=aiohttp.ClientSession)
        return manager
        
    @pytest.mark.asyncio
    async def test_initialization(self, pool_manager, instances_config):
        """Test pool manager initialization"""
        assert len(pool_manager.instances) == 3
        assert "local" in pool_manager.instances
        assert "gpu-1" in pool_manager.instances
        assert "gpu-2" in pool_manager.instances
        
        # Check instance configuration
        local_instance = pool_manager.instances["local"]
        assert local_instance.url == "http://localhost:11434"
        assert "llama3.2" in local_instance.models
        assert local_instance.max_concurrent == 5
        
    @pytest.mark.asyncio
    async def test_load_balancing_least_loaded(self, pool_manager):
        """Test least loaded balancing strategy"""
        # Set all instances as healthy
        for instance in pool_manager.instances.values():
            instance.state = InstanceState.HEALTHY
            
        # Simulate different load levels
        pool_manager.instances["local"].metrics.active_requests = 3
        pool_manager.instances["gpu-1"].metrics.active_requests = 1
        pool_manager.instances["gpu-2"].metrics.active_requests = 2
        
        # Get instance with least load
        available = list(pool_manager.instances.values())
        selected = await pool_manager._select_instance(
            available,
            LoadBalancingStrategy.LEAST_LOADED
        )
        
        assert selected.id == "gpu-1"
        
    @pytest.mark.asyncio
    async def test_load_balancing_model_affinity(self, pool_manager):
        """Test model affinity routing"""
        # Set all instances as healthy
        for instance in pool_manager.instances.values():
            instance.state = InstanceState.HEALTHY
            
        # Simulate model loaded on gpu-1
        pool_manager.instances["gpu-1"].models_loaded = {"mixtral"}
        
        # Get instance for mixtral model
        available = list(pool_manager.instances.values())
        selected = await pool_manager._select_instance(
            available,
            LoadBalancingStrategy.MODEL_AFFINITY,
            model="mixtral"
        )
        
        assert selected.id == "gpu-1"
        
    @pytest.mark.asyncio
    async def test_circuit_breaker(self, pool_manager):
        """Test circuit breaker functionality"""
        instance_id = "local"
        
        # Record multiple failures
        for _ in range(5):
            await pool_manager.record_failure(
                "http://localhost:11434",
                Exception("Connection failed")
            )
            
        # Check circuit is open
        assert pool_manager.circuit_breaker.is_open(instance_id)
        
        # Instance should not be available
        available = pool_manager._get_available_instances()
        assert not any(i.id == instance_id for i in available)
        
    @pytest.mark.asyncio
    async def test_health_check(self, pool_manager):
        """Test health check functionality"""
        instance_id = "local"
        
        # Mock successful health check
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "models": [
                {"name": "llama3.2"},
                {"name": "codellama"}
            ]
        })
        
        pool_manager.session.get = AsyncMock(return_value=mock_response)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        
        # Run health check
        result = await pool_manager.health_check(instance_id)
        
        assert result is True
        assert pool_manager.instances[instance_id].state == InstanceState.HEALTHY
        assert "llama3.2" in pool_manager.instances[instance_id].models_loaded
        
    @pytest.mark.asyncio
    async def test_failover(self, pool_manager):
        """Test automatic failover on instance failure"""
        # Set instances as healthy
        pool_manager.instances["local"].state = InstanceState.HEALTHY
        pool_manager.instances["gpu-1"].state = InstanceState.UNHEALTHY
        pool_manager.instances["gpu-2"].state = InstanceState.HEALTHY
        
        # Try to get instance - should skip unhealthy one
        url = await pool_manager.get_instance(
            strategy="round_robin",
            require_healthy=True
        )
        
        assert url in ["http://localhost:11434", "http://gpu2:11434"]
        assert url != "http://gpu1:11434"
        
    @pytest.mark.asyncio
    async def test_tag_filtering(self, pool_manager):
        """Test instance filtering by tags"""
        # Set all instances as healthy
        for instance in pool_manager.instances.values():
            instance.state = InstanceState.HEALTHY
            
        # Get GPU instances only
        available = pool_manager._get_available_instances(tags=["gpu"])
        
        assert len(available) == 2
        assert all("gpu" in i.tags for i in available)
        assert not any(i.id == "local" for i in available)
        
    @pytest.mark.asyncio
    async def test_concurrent_limit(self, pool_manager):
        """Test concurrent request limiting"""
        instance = pool_manager.instances["gpu-2"]
        instance.state = InstanceState.HEALTHY
        instance.max_concurrent = 1
        instance.metrics.active_requests = 1
        
        # Instance should not be available when at limit
        available = pool_manager._get_available_instances()
        assert not any(i.id == "gpu-2" for i in available)
        
    @pytest.mark.asyncio
    async def test_metrics_tracking(self, pool_manager):
        """Test metrics tracking"""
        url = "http://localhost:11434"
        
        # Record success
        await pool_manager.record_success(url, 0.5)
        
        instance = pool_manager.instances["local"]
        assert instance.metrics.success_count == 1
        assert instance.metrics.avg_response_time == 0.5
        
        # Record failure
        await pool_manager.record_failure(url, Exception("Test error"))
        
        assert instance.metrics.error_count == 1
        assert instance.metrics.error_rate == 0.5  # 1 error, 1 success
        
    @pytest.mark.asyncio
    async def test_pool_status(self, pool_manager):
        """Test pool status reporting"""
        # Set instance states
        pool_manager.instances["local"].state = InstanceState.HEALTHY
        pool_manager.instances["gpu-1"].state = InstanceState.DEGRADED
        pool_manager.instances["gpu-2"].state = InstanceState.UNHEALTHY
        
        # Set some metrics
        pool_manager.instances["local"].metrics.active_requests = 2
        pool_manager.instances["local"].metrics.total_requests = 10
        
        status = await pool_manager.get_pool_status()
        
        assert status["total_instances"] == 3
        assert status["healthy_instances"] == 1
        assert status["degraded_instances"] == 1
        assert status["unhealthy_instances"] == 1
        assert "local" in status["instances"]
        assert status["instances"]["local"]["active_requests"] == 2