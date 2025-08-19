"""
Tests for resource management in client_v2
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch

from gleitzeit.client_v2 import GleitzeitClient
from gleitzeit.resources import (
    ResourceInstance,
    ResourceType,
    ResourceStatus,
    ResourceRequirements,
    ResourceMetrics
)


@pytest.fixture
async def client_with_resources():
    """Client with resource management enabled"""
    client = GleitzeitClient(
        mode="native",
        native_config={'enable_resource_management': True}
    )
    await client.initialize()
    yield client
    await client.shutdown()


class TestResourcePoolManagement:
    """Test resource pool creation and management"""
    
    @pytest.mark.asyncio
    async def test_create_ollama_pool(self, client_with_resources):
        """Test creating an Ollama resource pool"""
        success = await client_with_resources.create_resource_pool(
            pool_id="ollama-pool",
            resource_type="ollama",
            min_instances=1,
            max_instances=5,
            endpoints=["http://localhost:11434"]
        )
        
        assert success is True
        
        # Check pool was created
        metrics = await client_with_resources.get_resource_metrics()
        assert metrics["allocator"]["pools"] == 1
    
    @pytest.mark.asyncio
    async def test_create_docker_pool(self, client_with_resources):
        """Test creating a Docker resource pool"""
        success = await client_with_resources.create_resource_pool(
            pool_id="docker-pool",
            resource_type="docker",
            min_instances=0,
            max_instances=10
        )
        
        assert success is True
    
    @pytest.mark.asyncio
    async def test_create_pool_without_resource_manager(self):
        """Test pool creation fails gracefully without resource manager"""
        client = GleitzeitClient(mode="native")
        await client.initialize()
        
        try:
            success = await client.create_resource_pool(
                pool_id="test-pool",
                resource_type="ollama"
            )
            assert success is False
        finally:
            await client.shutdown()


class TestResourceRegistration:
    """Test resource instance registration"""
    
    @pytest.mark.asyncio
    async def test_register_ollama_instance(self, client_with_resources):
        """Test registering an Ollama instance"""
        # Create pool first
        await client_with_resources.create_resource_pool(
            pool_id="ollama-pool",
            resource_type="ollama"
        )
        
        # Register instance
        success = await client_with_resources.register_resource(
            pool_id="ollama-pool",
            instance_id="ollama-1",
            endpoint="http://localhost:11434",
            resource_type="ollama",
            capabilities=["llama3.2", "codellama"],
            max_concurrent=3
        )
        
        assert success is True
    
    @pytest.mark.asyncio
    async def test_register_to_nonexistent_pool(self, client_with_resources):
        """Test registration fails for non-existent pool"""
        success = await client_with_resources.register_resource(
            pool_id="nonexistent",
            instance_id="instance-1",
            endpoint="http://localhost:8080"
        )
        
        assert success is False


class TestResourceAllocation:
    """Test resource allocation and release"""
    
    @pytest.mark.asyncio
    async def test_allocate_and_release_resource(self, client_with_resources):
        """Test allocating and releasing a resource"""
        # Setup pool with instance
        await client_with_resources.create_resource_pool(
            pool_id="ollama-pool",
            resource_type="ollama"
        )
        
        await client_with_resources.register_resource(
            pool_id="ollama-pool",
            instance_id="ollama-1",
            endpoint="http://localhost:11434",
            capabilities=["llama3.2"]
        )
        
        # Allocate resource
        resource = await client_with_resources.allocate_resource(
            task_id="test-task-1",
            resource_type="ollama",
            capabilities=["llama3.2"],
            strategy="least_loaded"
        )
        
        assert resource is not None
        assert resource["id"] == "ollama-1"
        assert resource["status"] == "available"
        
        # Release resource
        released = await client_with_resources.release_resource("test-task-1")
        assert released is True
    
    @pytest.mark.asyncio
    async def test_allocate_with_requirements(self, client_with_resources):
        """Test allocation with specific requirements"""
        # Create pool with multiple instances
        await client_with_resources.create_resource_pool(
            pool_id="ollama-pool",
            resource_type="ollama"
        )
        
        # Register instances with different capabilities
        await client_with_resources.register_resource(
            pool_id="ollama-pool",
            instance_id="ollama-1",
            endpoint="http://localhost:11434",
            capabilities=["llama3.2", "llava"]
        )
        
        await client_with_resources.register_resource(
            pool_id="ollama-pool",
            instance_id="ollama-2",
            endpoint="http://localhost:11435",
            capabilities=["codellama", "mistral"]
        )
        
        # Allocate requiring specific capability
        resource = await client_with_resources.allocate_resource(
            task_id="test-task",
            resource_type="ollama",
            capabilities=["codellama"]
        )
        
        assert resource is not None
        assert resource["id"] == "ollama-2"
        assert "codellama" in resource["capabilities"]
    
    @pytest.mark.asyncio
    async def test_allocation_failure(self, client_with_resources):
        """Test allocation fails when no resources available"""
        # Create empty pool
        await client_with_resources.create_resource_pool(
            pool_id="empty-pool",
            resource_type="ollama"
        )
        
        # Try to allocate
        resource = await client_with_resources.allocate_resource(
            task_id="test-task",
            resource_type="ollama"
        )
        
        assert resource is None


class TestResourceMetrics:
    """Test resource metrics and monitoring"""
    
    @pytest.mark.asyncio
    async def test_get_resource_metrics(self, client_with_resources):
        """Test getting resource metrics"""
        # Create pool with instances
        await client_with_resources.create_resource_pool(
            pool_id="test-pool",
            resource_type="ollama",
            endpoints=["http://localhost:11434"]
        )
        
        metrics = await client_with_resources.get_resource_metrics()
        
        assert metrics is not None
        assert "allocator" in metrics
        assert metrics["allocator"]["pools"] == 1
        assert metrics["allocator"]["total_instances"] == 1
    
    @pytest.mark.asyncio
    async def test_metrics_without_resource_manager(self):
        """Test metrics returns disabled status without resource manager"""
        client = GleitzeitClient(mode="native")
        await client.initialize()
        
        try:
            metrics = await client.get_resource_metrics()
            assert metrics == {"enabled": False}
        finally:
            await client.shutdown()


class TestAutoScaling:
    """Test auto-scaling functionality"""
    
    @pytest.mark.asyncio
    async def test_enable_auto_scaling(self, client_with_resources):
        """Test enabling auto-scaling"""
        # Create pool
        await client_with_resources.create_resource_pool(
            pool_id="scalable-pool",
            resource_type="ollama",
            min_instances=1,
            max_instances=5
        )
        
        # Enable auto-scaling
        await client_with_resources.enable_auto_scaling(
            scale_up_threshold=0.8,
            scale_down_threshold=0.2
        )
        
        # Auto-scaling should be enabled (check through metrics)
        metrics = await client_with_resources.get_resource_metrics()
        assert metrics is not None


class TestResourceIntegration:
    """Test integration with task execution"""
    
    @pytest.mark.asyncio
    async def test_task_with_resource_requirements(self, client_with_resources):
        """Test task execution with resource requirements"""
        # Create pool and register Ollama instance
        await client_with_resources.create_resource_pool(
            pool_id="ollama-pool",
            resource_type="ollama"
        )
        
        await client_with_resources.register_resource(
            pool_id="ollama-pool",
            instance_id="ollama-1",
            endpoint="http://localhost:11434",
            capabilities=["llama3.2"]
        )
        
        # Submit task with resource requirements
        task = await client_with_resources.submit_task(
            name="Test LLM Task",
            protocol="llm/v1",
            method="chat",
            params={
                "model": "llama3.2",
                "messages": [{"role": "user", "content": "Hello"}]
            }
        )
        
        # Task should have resource_requirements field
        assert hasattr(task, 'resource_requirements')
    
    @pytest.mark.asyncio
    async def test_multiple_concurrent_allocations(self, client_with_resources):
        """Test multiple concurrent resource allocations"""
        # Create pool with multiple instances
        await client_with_resources.create_resource_pool(
            pool_id="multi-pool",
            resource_type="ollama"
        )
        
        # Register multiple instances
        for i in range(3):
            await client_with_resources.register_resource(
                pool_id="multi-pool",
                instance_id=f"ollama-{i}",
                endpoint=f"http://localhost:{11434 + i}",
                max_concurrent=2
            )
        
        # Allocate resources concurrently
        tasks = []
        for i in range(5):
            task = client_with_resources.allocate_resource(
                task_id=f"task-{i}",
                resource_type="ollama"
            )
            tasks.append(task)
        
        results = await asyncio.gather(*tasks)
        
        # Should get 5 successful allocations across 3 instances
        allocated = [r for r in results if r is not None]
        assert len(allocated) == 5
        
        # Release all
        for i in range(5):
            await client_with_resources.release_resource(f"task-{i}")


class TestResourceCleanup:
    """Test resource cleanup on shutdown"""
    
    @pytest.mark.asyncio
    async def test_resource_manager_cleanup(self):
        """Test resource manager is properly cleaned up"""
        client = GleitzeitClient(
            mode="native",
            native_config={'enable_resource_management': True}
        )
        
        await client.initialize()
        
        # Create some pools
        await client.create_resource_pool(
            pool_id="test-pool",
            resource_type="ollama"
        )
        
        # Shutdown should clean up
        await client.shutdown()
        
        # Resource manager should be stopped
        assert client._resource_manager is not None
        assert not client._resource_manager.running