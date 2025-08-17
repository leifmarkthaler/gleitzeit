"""
Tests for resource management functionality in GleitzeitClient
"""

import pytest
from unittest.mock import Mock, AsyncMock

from gleitzeit.client import GleitzeitClient
from gleitzeit.hub.base import ResourceMetrics, ResourceStatus


class TestResourceRegistration:
    """Test resource registration and management"""
    
    @pytest.mark.asyncio
    async def test_register_resource(self, client_with_mocks):
        """Test registering a new resource"""
        resource_data = {
            "type": "OLLAMA",
            "status": "healthy",
            "endpoint": "http://localhost:11434",
            "metadata": {"models": ["llama3.2"]}
        }
        
        result = await client_with_mocks.register_resource(
            hub_id="ollama-hub",
            instance_id="ollama-1",
            instance_data=resource_data
        )
        
        assert result is True
        client_with_mocks.adapter.save_resource_instance.assert_called_once_with(
            "ollama-hub", "ollama-1", resource_data
        )
    
    @pytest.mark.asyncio
    async def test_register_resource_failure(self, client_with_mocks):
        """Test resource registration failure"""
        client_with_mocks.adapter.save_resource_instance.return_value = False
        
        result = await client_with_mocks.register_resource(
            hub_id="ollama-hub",
            instance_id="ollama-1",
            instance_data={}
        )
        
        assert result is False


class TestResourceRetrieval:
    """Test resource retrieval functionality"""
    
    @pytest.mark.asyncio
    async def test_get_resource(self, client_with_mocks, sample_resource):
        """Test getting a resource by ID"""
        client_with_mocks.adapter.get_resource_instance.return_value = sample_resource
        
        resource = await client_with_mocks.get_resource("ollama-1")
        
        assert resource is not None
        assert resource["id"] == "ollama-1"
        assert resource["type"] == "OLLAMA"
        assert resource["endpoint"] == "http://localhost:11434"
    
    @pytest.mark.asyncio
    async def test_get_resource_not_found(self, client_with_mocks):
        """Test getting non-existent resource"""
        client_with_mocks.adapter.get_resource_instance.return_value = None
        
        resource = await client_with_mocks.get_resource("nonexistent")
        
        assert resource is None
    
    @pytest.mark.asyncio
    async def test_list_resources(self, client_with_mocks):
        """Test listing resources for a hub"""
        resources = [
            {
                "id": "ollama-1",
                "type": "OLLAMA",
                "status": "healthy",
                "endpoint": "http://localhost:11434"
            },
            {
                "id": "ollama-2",
                "type": "OLLAMA",
                "status": "healthy",
                "endpoint": "http://localhost:11435"
            }
        ]
        client_with_mocks.adapter.list_resource_instances.return_value = resources
        
        result = await client_with_mocks.list_resources("ollama-hub")
        
        assert len(result) == 2
        assert result[0]["id"] == "ollama-1"
        assert result[1]["id"] == "ollama-2"
    
    @pytest.mark.asyncio
    async def test_list_resources_empty(self, client_with_mocks):
        """Test listing resources when none exist"""
        client_with_mocks.adapter.list_resource_instances.return_value = []
        
        result = await client_with_mocks.list_resources("empty-hub")
        
        assert result == []


class TestResourceMetrics:
    """Test resource metrics functionality"""
    
    @pytest.mark.asyncio
    async def test_save_resource_metrics(self, client_with_mocks):
        """Test saving resource metrics"""
        metrics = {
            "cpu_usage": 45.5,
            "memory_usage": 2048,
            "requests_per_second": 10
        }
        
        result = await client_with_mocks.save_resource_metrics(
            hub_id="ollama-hub",
            instance_id="ollama-1",
            metrics=metrics
        )
        
        assert result is True
        client_with_mocks.adapter.save_resource_metrics.assert_called_once_with(
            "ollama-hub", "ollama-1", metrics
        )
    
    @pytest.mark.asyncio
    async def test_get_resource_metrics(self, client_with_mocks, sample_metrics):
        """Test getting resource metrics"""
        client_with_mocks.adapter.get_resource_metrics.return_value = sample_metrics
        
        metrics = await client_with_mocks.get_resource_metrics(
            hub_id="ollama-hub",
            instance_id="ollama-1"
        )
        
        assert metrics is not None
        assert metrics.cpu_usage == 45.5
        assert metrics.memory_usage == 2048
        assert metrics.custom_metrics["requests_per_second"] == 10
    
    @pytest.mark.asyncio
    async def test_get_hub_metrics(self, client_with_mocks):
        """Test getting aggregated hub metrics"""
        # Mock multiple resource metrics
        metrics1 = ResourceMetrics(
            hub_id="ollama-hub",
            instance_id="ollama-1",
            cpu_usage=40.0,
            memory_usage=2000
        )
        metrics2 = ResourceMetrics(
            hub_id="ollama-hub",
            instance_id="ollama-2",
            cpu_usage=60.0,
            memory_usage=3000
        )
        
        # Return different metrics for different instance IDs
        def get_metrics_side_effect(hub_id, instance_id=None):
            if instance_id == "ollama-1":
                return metrics1
            elif instance_id == "ollama-2":
                return metrics2
            else:
                # Aggregated metrics for hub
                return ResourceMetrics(
                    hub_id=hub_id,
                    instance_id=None,
                    cpu_usage=50.0,  # Average
                    memory_usage=5000  # Total
                )
        
        client_with_mocks.adapter.get_resource_metrics.side_effect = get_metrics_side_effect
        
        metrics = await client_with_mocks.get_resource_metrics("ollama-hub")
        
        assert metrics is not None
        assert metrics.cpu_usage == 50.0
        assert metrics.memory_usage == 5000


class TestResourceUtilization:
    """Test resource utilization tracking"""
    
    @pytest.mark.asyncio
    async def test_get_resource_utilization(self, client_with_mocks):
        """Test getting resource utilization for a hub"""
        # Mock resources
        resources = [
            {"id": "r1", "status": "healthy"},
            {"id": "r2", "status": "healthy"},
            {"id": "r3", "status": "unhealthy"},
            {"id": "r4", "status": "healthy"},
            {"id": "r5", "status": "stopped"}
        ]
        client_with_mocks.adapter.list_resource_instances.return_value = resources
        
        # Mock metrics showing utilization
        metrics = ResourceMetrics(
            hub_id="ollama-hub",
            cpu_usage=75.0,
            memory_usage=8192
        )
        client_with_mocks.adapter.get_resource_metrics.return_value = metrics
        
        utilization = await client_with_mocks.get_resource_utilization("ollama-hub")
        
        assert utilization["total_instances"] == 5
        assert utilization["healthy_instances"] == 3
        assert utilization["unhealthy_instances"] == 1
        assert utilization["utilization_percent"] == 60.0  # 3/5 healthy
    
    @pytest.mark.asyncio
    async def test_get_resource_utilization_empty(self, client_with_mocks):
        """Test utilization for hub with no resources"""
        client_with_mocks.adapter.list_resource_instances.return_value = []
        
        utilization = await client_with_mocks.get_resource_utilization("empty-hub")
        
        assert utilization["total_instances"] == 0
        assert utilization["healthy_instances"] == 0
        assert utilization["unhealthy_instances"] == 0
        assert utilization["utilization_percent"] == 0.0


class TestCrossDomainOperations:
    """Test operations linking tasks and resources"""
    
    @pytest.mark.asyncio
    async def test_get_tasks_for_resource(self, client_with_mocks):
        """Test getting tasks executed by a resource"""
        tasks = [
            Mock(id="task-1", name="Task 1", resource_id="ollama-1"),
            Mock(id="task-2", name="Task 2", resource_id="ollama-1"),
            Mock(id="task-3", name="Task 3", resource_id="ollama-2")
        ]
        
        # Filter tasks for the requested resource
        client_with_mocks.adapter.list_tasks.return_value = [
            t for t in tasks if getattr(t, 'resource_id', None) == "ollama-1"
        ]
        
        result = await client_with_mocks.get_tasks_for_resource("ollama-1")
        
        assert len(result) == 2
        assert all(t.resource_id == "ollama-1" for t in result)
    
    @pytest.mark.asyncio
    async def test_get_resource_for_task(self, client_with_mocks):
        """Test getting the resource that executed a task"""
        # Mock task with resource reference
        task = Mock(id="task-123", resource_id="ollama-1")
        client_with_mocks.adapter.get_task.return_value = task
        
        # Mock resource
        resource = {
            "id": "ollama-1",
            "type": "OLLAMA",
            "endpoint": "http://localhost:11434"
        }
        client_with_mocks.adapter.get_resource_instance.return_value = resource
        
        result = await client_with_mocks.get_resource_for_task("task-123")
        
        assert result is not None
        assert result["id"] == "ollama-1"
        assert result["type"] == "OLLAMA"
    
    @pytest.mark.asyncio
    async def test_get_resource_for_task_not_found(self, client_with_mocks):
        """Test getting resource for task with no resource"""
        task = Mock(id="task-123", resource_id=None)
        client_with_mocks.adapter.get_task.return_value = task
        
        result = await client_with_mocks.get_resource_for_task("task-123")
        
        assert result is None


class TestResourceMemoryIntegration:
    """Integration tests with memory persistence"""
    
    @pytest.mark.asyncio
    async def test_resource_lifecycle_memory(self, memory_client):
        """Test complete resource lifecycle with memory persistence"""
        # Register resource
        resource_data = {
            "type": "OLLAMA",
            "status": "healthy",
            "endpoint": "http://localhost:11434",
            "metadata": {
                "models": ["llama3.2", "codellama"],
                "version": "0.1.0"
            }
        }
        
        registered = await memory_client.register_resource(
            hub_id="ollama-hub",
            instance_id="ollama-test",
            instance_data=resource_data
        )
        assert registered is True
        
        # Get resource
        resource = await memory_client.get_resource("ollama-test")
        assert resource is not None
        assert resource["type"] == "OLLAMA"
        
        # List resources
        resources = await memory_client.list_resources("ollama-hub")
        assert len(resources) >= 1
        assert any(r["id"] == "ollama-test" for r in resources if "id" in r)
        
        # Save metrics
        metrics_saved = await memory_client.save_resource_metrics(
            hub_id="ollama-hub",
            instance_id="ollama-test",
            metrics={
                "cpu_usage": 50.0,
                "memory_usage": 4096,
                "active_models": 2
            }
        )
        assert metrics_saved is True
        
        # Get metrics
        metrics = await memory_client.get_resource_metrics(
            hub_id="ollama-hub",
            instance_id="ollama-test"
        )
        assert metrics is not None
        assert metrics.cpu_usage == 50.0
        assert metrics.memory_usage == 4096
    
    @pytest.mark.asyncio
    async def test_multiple_resources_memory(self, memory_client):
        """Test managing multiple resources"""
        # Register multiple resources across different hubs
        resources = [
            ("ollama-hub", "ollama-1", {"type": "OLLAMA", "status": "healthy"}),
            ("ollama-hub", "ollama-2", {"type": "OLLAMA", "status": "healthy"}),
            ("docker-hub", "docker-1", {"type": "DOCKER", "status": "healthy"}),
            ("docker-hub", "docker-2", {"type": "DOCKER", "status": "stopped"}),
        ]
        
        for hub_id, instance_id, data in resources:
            registered = await memory_client.register_resource(
                hub_id=hub_id,
                instance_id=instance_id,
                instance_data=data
            )
            assert registered is True
        
        # List Ollama resources
        ollama_resources = await memory_client.list_resources("ollama-hub")
        assert len(ollama_resources) >= 2
        
        # List Docker resources
        docker_resources = await memory_client.list_resources("docker-hub")
        assert len(docker_resources) >= 2
        
        # Get utilization for each hub
        ollama_util = await memory_client.get_resource_utilization("ollama-hub")
        assert ollama_util["total_instances"] >= 2
        assert ollama_util["healthy_instances"] >= 2
        
        docker_util = await memory_client.get_resource_utilization("docker-hub")
        assert docker_util["total_instances"] >= 2
        assert docker_util["healthy_instances"] >= 1  # One is stopped