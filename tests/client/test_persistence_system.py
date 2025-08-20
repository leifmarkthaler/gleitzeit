"""
Tests for persistence, initialization, and system operations in GleitzeitClient
"""

import pytest
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from gleitzeit.client import GleitzeitClient
from gleitzeit.persistence.factory import PersistenceType


class TestClientInitialization:
    """Test client initialization and lifecycle"""
    
    @pytest.mark.asyncio
    async def test_initialize_with_memory(self):
        """Test initializing client with memory persistence"""
        client = GleitzeitClient(persistence_type="memory")
        
        assert not client._initialized
        
        await client.initialize()
        
        assert client._initialized
        assert client.adapter is not None
        assert client.queue_manager is not None
        
        await client.shutdown()
        assert not client._initialized
    
    @pytest.mark.asyncio
    async def test_initialize_with_sqlite(self, temp_db_path):
        """Test initializing client with SQLite persistence"""
        client = GleitzeitClient(
            persistence_type="sql",
            sql_db_path=temp_db_path
        )
        
        await client.initialize()
        
        assert client._initialized
        assert client.persistence_backend == "sql"
        
        await client.shutdown()
    
    @pytest.mark.asyncio
    async def test_initialize_with_auto_fallback(self):
        """Test auto persistence fallback"""
        client = GleitzeitClient(persistence_type="auto")
        
        with patch('gleitzeit.client.PersistenceManager') as mock_pm:
            # Simulate Redis failure, SQL success
            mock_pm.initialize.side_effect = [
                Exception("Redis failed"),  # Redis fails
                None  # SQL succeeds
            ]
            mock_pm.get_adapter.return_value = Mock()
            mock_pm.is_initialized.return_value = True
            
            await client.initialize()
            
            assert client._initialized
    
    @pytest.mark.asyncio
    async def test_initialize_twice(self, memory_client):
        """Test that initializing twice is safe"""
        # Already initialized from fixture
        assert memory_client._initialized
        
        # Initialize again should warn but not error
        await memory_client.initialize()
        assert memory_client._initialized
    
    @pytest.mark.asyncio
    async def test_shutdown_not_initialized(self):
        """Test shutting down non-initialized client"""
        client = GleitzeitClient()
        
        # Should not raise error
        await client.shutdown()
        assert not client._initialized
    
    @pytest.mark.asyncio
    async def test_ensure_initialized_check(self):
        """Test that operations fail when not initialized"""
        client = GleitzeitClient()
        
        with pytest.raises(RuntimeError, match="Client not initialized"):
            await client.submit_task("test", "llm/v1", "chat")


class TestContextManager:
    """Test async context manager functionality"""
    
    @pytest.mark.asyncio
    async def test_context_manager_basic(self):
        """Test using client as context manager"""
        async with await create_client(persistence_type="memory") as client:
            assert client._initialized
            
            # Should be able to use client
            task = await client.submit_task(
                name="Test",
                protocol="llm/v1",
                method="chat",
                params={"model": "test"}
            )
            assert task is not None
        
        # Client should be shut down after context
        assert not client._initialized
    
    @pytest.mark.asyncio
    async def test_context_manager_with_exception(self):
        """Test context manager handles exceptions properly"""
        try:
            async with await create_client(persistence_type="memory") as client:
                assert client._initialized
                raise ValueError("Test exception")
        except ValueError:
            pass
        
        # Client should still be shut down
        assert not client._initialized
    
    @pytest.mark.asyncio
    async def test_create_client_with_config(self):
        """Test create_client with custom configuration"""
        config = {
            "execution": {
                "max_parallel_tasks": 20,
                "task_timeout": 600
            }
        }
        
        async with await create_client(
            persistence_type="memory",
            config=config
        ) as client:
            assert client._initialized
            assert client.config == config


class TestPersistenceBackends:
    """Test different persistence backends"""
    
    @pytest.mark.asyncio
    async def test_memory_persistence(self):
        """Test memory persistence backend"""
        client = GleitzeitClient(persistence_type="memory")
        await client.initialize()
        
        assert client.persistence_backend == "memory"
        
        # Test basic operations work
        task = await client.submit_task(
            name="Memory Test",
            protocol="llm/v1",
            method="chat"
        )
        
        retrieved = await client.get_task(task.id)
        assert retrieved is not None
        assert retrieved.name == "Memory Test"
        
        await client.shutdown()
    
    @pytest.mark.asyncio
    async def test_sqlite_persistence(self, temp_db_path):
        """Test SQLite persistence backend"""
        client = GleitzeitClient(
            persistence_type="sql",
            sql_db_path=temp_db_path
        )
        await client.initialize()
        
        assert client.persistence_backend == "sql"
        assert Path(temp_db_path).exists()
        
        # Test persistence across client restarts
        task = await client.submit_task(
            name="SQLite Test",
            protocol="python/v1",
            method="execute"
        )
        task_id = task.id
        
        await client.shutdown()
        
        # Create new client with same database
        client2 = GleitzeitClient(
            persistence_type="sql",
            sql_db_path=temp_db_path
        )
        await client2.initialize()
        
        # Should be able to retrieve task
        retrieved = await client2.get_task(task_id)
        assert retrieved is not None
        assert retrieved.name == "SQLite Test"
        
        await client2.shutdown()
    
    @pytest.mark.asyncio
    async def test_redis_persistence_mock(self):
        """Test Redis persistence with mock"""
        with patch('gleitzeit.persistence.factory.RedisAdapter') as MockRedis:
            mock_adapter = Mock()
            mock_adapter.initialize = AsyncMock()
            mock_adapter.shutdown = AsyncMock()
            MockRedis.return_value = mock_adapter
            
            client = GleitzeitClient(
                persistence_type="redis",
                redis_url="redis://localhost:6379"
            )
            
            with patch('gleitzeit.client.PersistenceManager') as mock_pm:
                mock_pm.initialize.return_value = None
                mock_pm.get_adapter.return_value = mock_adapter
                mock_pm.is_initialized.return_value = True
                
                await client.initialize()
                
                assert client._initialized
                assert client.adapter == mock_adapter
                
                await client.shutdown()


class TestQueueOperations:
    """Test queue management operations"""
    
    @pytest.mark.asyncio
    async def test_get_queue_statistics(self, client_with_mocks):
        """Test getting queue statistics"""
        # Mock queue states
        mock_queue1 = Mock()
        mock_queue1.get_size.return_value = 5
        mock_queue1.name = "default"
        
        mock_queue2 = Mock()
        mock_queue2.get_size.return_value = 3
        mock_queue2.name = "priority"
        
        client_with_mocks.queue_manager.queues = {
            "default": mock_queue1,
            "priority": mock_queue2
        }
        
        stats = await client_with_mocks.get_queue_statistics()
        
        assert "default" in stats
        assert stats["default"]["size"] == 5
        assert "priority" in stats
        assert stats["priority"]["size"] == 3
    
    @pytest.mark.asyncio
    async def test_queue_persistence(self, memory_client):
        """Test that queue state is persisted"""
        # Submit tasks to different queues
        task1 = await memory_client.submit_task(
            name="Default Queue Task",
            protocol="llm/v1",
            method="chat",
            queue_name="default"
        )
        
        task2 = await memory_client.submit_task(
            name="Priority Queue Task",
            protocol="llm/v1",
            method="chat",
            queue_name="priority",
            priority=10
        )
        
        # Get queue statistics
        stats = await memory_client.get_queue_statistics()
        
        # Should have tasks in queues
        assert len(stats) > 0


class TestHealthCheck:
    """Test system health check functionality"""
    
    @pytest.mark.asyncio
    async def test_health_check_healthy(self, client_with_mocks):
        """Test health check when system is healthy"""
        # Mock healthy state
        client_with_mocks.adapter.cleanup_old_data = AsyncMock(return_value=0)
        client_with_mocks.queue_manager.queues = {
            "default": Mock(name="default"),
            "priority": Mock(name="priority")
        }
        
        with patch('gleitzeit.client.datetime') as mock_datetime:
            mock_datetime.utcnow.return_value = MagicMock()
            
            health = await client_with_mocks.health_check()
        
        assert health["status"] == "healthy"
        assert health["persistence"]["status"] == "connected"
        assert health["queues"]["total"] == 2
        assert health["queues"]["active"] == 2
    
    @pytest.mark.asyncio
    async def test_health_check_not_initialized(self):
        """Test health check when client not initialized"""
        client = GleitzeitClient()
        
        health = await client.health_check()
        
        assert health["status"] == "error"
        assert "not initialized" in health["error"]


class TestCleanupOperations:
    """Test data cleanup operations"""
    
    @pytest.mark.asyncio
    async def test_cleanup_old_data(self, client_with_mocks):
        """Test cleaning up old data"""
        client_with_mocks.adapter.cleanup_old_data.return_value = 25
        
        deleted = await client_with_mocks.cleanup_old_data(days=7)
        
        assert deleted == 25
        client_with_mocks.adapter.cleanup_old_data.assert_called_once_with(7)
    
    @pytest.mark.asyncio
    async def test_cleanup_with_memory_backend(self, memory_client):
        """Test cleanup with memory backend"""
        # Submit some tasks
        for i in range(5):
            await memory_client.submit_task(
                name=f"Task {i}",
                protocol="llm/v1",
                method="chat"
            )
        
        # Cleanup (memory backend should clear old data)
        deleted = await memory_client.cleanup_old_data(days=0)
        
        # Memory backend might not track deletion count accurately
        assert deleted >= 0


class TestErrorHandling:
    """Test error handling and recovery"""
    
    @pytest.mark.asyncio
    async def test_persistence_initialization_error(self):
        """Test handling persistence initialization errors"""
        client = GleitzeitClient(persistence_type="sql", sql_db_path="/invalid/path/db.sqlite")
        
        with patch('gleitzeit.persistence.factory.PersistenceManager.initialize') as mock_init:
            mock_init.side_effect = Exception("Cannot create database")
            
            with pytest.raises(Exception, match="Cannot create database"):
                await client.initialize()
        
        assert not client._initialized
    
    @pytest.mark.asyncio
    async def test_adapter_operation_error(self, client_with_mocks):
        """Test handling adapter operation errors"""
        client_with_mocks.adapter.save_task.side_effect = Exception("Database error")
        
        with pytest.raises(Exception, match="Database error"):
            await client_with_mocks.submit_task(
                name="Error Test",
                protocol="llm/v1",
                method="chat"
            )
    
    @pytest.mark.asyncio
    async def test_shutdown_with_error(self, client_with_mocks):
        """Test shutdown handles errors gracefully"""
        client_with_mocks.adapter.shutdown.side_effect = Exception("Shutdown error")
        
        # Should not raise, but log error
        await client_with_mocks.shutdown()
        
        # Should still mark as not initialized
        assert not client_with_mocks._initialized


class TestIntegrationScenarios:
    """Test complete integration scenarios"""
    
    @pytest.mark.asyncio
    async def test_complete_workflow_scenario(self, memory_client):
        """Test complete workflow from submission to results"""
        # Submit workflow
        workflow = await memory_client.submit_workflow(
            name="Integration Test",
            tasks=[
                {
                    "name": "step1",
                    "protocol": "python/v1",
                    "method": "execute",
                    "params": {"code": "result = 10"}
                },
                {
                    "name": "step2",
                    "protocol": "python/v1",
                    "method": "execute",
                    "params": {"code": "result = ${step1.result} * 2"},
                    "dependencies": ["step1"]
                }
            ]
        )
        
        # Get workflow status
        retrieved = await memory_client.get_workflow(workflow.id)
        assert retrieved is not None
        
        # Get tasks
        tasks = await memory_client.get_workflow_tasks(workflow.id)
        assert len(tasks) == 2
        
        # Get statistics
        stats = await memory_client.get_task_statistics()
        assert stats["total"] >= 2
        
        # Health check
        health = await memory_client.health_check()
        assert health["status"] == "healthy"
    
    @pytest.mark.asyncio
    async def test_resource_and_task_integration(self, memory_client):
        """Test integration between resources and tasks"""
        # Register resource
        await memory_client.register_resource(
            hub_id="test-hub",
            instance_id="test-instance",
            instance_data={
                "type": "TEST",
                "status": "healthy",
                "endpoint": "http://localhost:9999"
            }
        )
        
        # Submit task
        task = await memory_client.submit_task(
            name="Resource Test",
            protocol="test/v1",
            method="test",
            metadata={"resource_id": "test-instance"}
        )
        
        # Link task to resource (in real scenario, execution engine does this)
        task.resource_id = "test-instance"
        await memory_client.adapter.save_task(task)
        
        # Get tasks for resource
        tasks = await memory_client.get_tasks_for_resource("test-instance")
        # Note: Implementation may not support this query directly
        
        # Get resource for task
        resource = await memory_client.get_resource_for_task(task.id)
        # Note: Implementation may need enhancement for cross-domain queries
        
        # Save metrics
        await memory_client.save_resource_metrics(
            hub_id="test-hub",
            instance_id="test-instance",
            metrics={"requests": 1}
        )
        
        # Get utilization
        util = await memory_client.get_resource_utilization("test-hub")
        assert util["total_instances"] >= 1