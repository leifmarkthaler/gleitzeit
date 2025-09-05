"""
Tests for ProviderPullAdapter
"""

import pytest
import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock

from gleitzeit.orchestration.provider_pull import ProviderPullAdapter, ProviderPoolManager
from gleitzeit.events.base import EventBus
from gleitzeit.core.events import GleitzeitEvent, EventType
from gleitzeit.persistence.unified_redis import UnifiedRedisBackend


class MockProvider:
    """Mock provider for testing"""
    
    def __init__(self, protocol_name="python", fail_on_execute=False):
        self.protocol_name = protocol_name
        self.protocol = protocol_name  # Some providers use this
        self.fail_on_execute = fail_on_execute
        self.executed_tasks = []
        self.execution_delay = 0.05  # Small delay to simulate work
        
    async def execute(self, method: str, params: dict):
        """Mock execution"""
        if self.fail_on_execute:
            raise Exception(f"Mock failure for method {method}")
            
        self.executed_tasks.append({
            "method": method,
            "params": params,
            "timestamp": datetime.utcnow()
        })
        
        # Simulate some work
        await asyncio.sleep(self.execution_delay)
        
        # Return mock result
        return {
            "status": "success",
            "method": method,
            "result": f"Executed {method}"
        }


class MockSyncProvider:
    """Mock synchronous provider for testing"""
    
    def __init__(self, protocol_name="sync_python"):
        self.protocol_name = protocol_name
        self.executed_tasks = []
        
    def execute(self, method: str, params: dict):
        """Synchronous mock execution"""
        self.executed_tasks.append({
            "method": method,
            "params": params
        })
        return {"status": "success", "method": method}


@pytest.fixture
async def redis_backend():
    """Create test Redis backend"""
    backend = UnifiedRedisBackend()
    await backend.initialize()
    
    # Clear any existing test data
    await backend.redis.flushdb()
    
    yield backend
    
    # Cleanup
    await backend.redis.flushdb()
    await backend.cleanup()


@pytest.fixture
def event_bus():
    """Create test event bus"""
    return EventBus()


@pytest.fixture
def mock_provider():
    """Create mock provider"""
    return MockProvider(protocol_name="test_protocol")


@pytest.fixture
async def adapter(mock_provider, event_bus, redis_backend):
    """Create test adapter"""
    adapter = ProviderPullAdapter(
        provider=mock_provider,
        event_bus=event_bus,
        redis_client=redis_backend.redis,
        poll_interval=0.05
    )
    yield adapter


class TestProviderPullAdapter:
    """Test ProviderPullAdapter functionality"""
    
    @pytest.mark.asyncio
    async def test_adapter_initialization(self, mock_provider, event_bus, redis_backend):
        """Test adapter initialization"""
        adapter = ProviderPullAdapter(
            provider=mock_provider,
            event_bus=event_bus,
            redis_client=redis_backend.redis,
            poll_interval=0.1,
            batch_size=5
        )
        
        assert adapter.provider == mock_provider
        assert adapter.protocol == "test_protocol"
        assert adapter.queue_key == "provider:queue:test_protocol"
        assert adapter.processing_key == "provider:processing:test_protocol"
        assert adapter.poll_interval == 0.1
        assert adapter.batch_size == 5
        assert not adapter.running
    
    @pytest.mark.asyncio
    async def test_pull_task_from_queue(self, adapter, redis_backend):
        """Test pulling task from Redis queue"""
        # Add task to queue
        task_data = {
            "task_id": "test-task-1",
            "workflow_id": "test-workflow",
            "method": "test_method",
            "params": {"key": "value"}
        }
        
        await redis_backend.redis.lpush(
            adapter.queue_key,
            json.dumps(task_data)
        )
        
        # Pull task
        pulled_task = await adapter._pull_task()
        
        assert pulled_task is not None
        assert pulled_task["task_id"] == "test-task-1"
        assert pulled_task["method"] == "test_method"
        assert pulled_task["params"]["key"] == "value"
        
        # Check task moved to processing queue
        processing_count = await redis_backend.redis.llen(adapter.processing_key)
        assert processing_count == 1
    
    @pytest.mark.asyncio
    async def test_pull_empty_queue(self, adapter):
        """Test pulling from empty queue returns None"""
        pulled_task = await adapter._pull_task()
        assert pulled_task is None
    
    @pytest.mark.asyncio
    async def test_execute_task_async_provider(self, adapter, mock_provider, event_bus):
        """Test executing task with async provider"""
        # Track events
        events_received = []
        
        async def capture_event(event):
            events_received.append(event)
        
        event_bus.register(EventType.TASK_STARTED, capture_event)
        event_bus.register(EventType.TASK_COMPLETED, capture_event)
        
        # Execute task
        task_data = {
            "task_id": "test-task-2",
            "workflow_id": "test-workflow",
            "method": "async_method",
            "params": {"message": "Hello"}
        }
        
        await adapter._execute_task(task_data)
        
        # Check provider executed task
        assert len(mock_provider.executed_tasks) == 1
        assert mock_provider.executed_tasks[0]["method"] == "async_method"
        assert mock_provider.executed_tasks[0]["params"]["message"] == "Hello"
        
        # Check events emitted
        assert len(events_received) == 2
        assert events_received[0].event_type == EventType.TASK_STARTED
        assert events_received[1].event_type == EventType.TASK_COMPLETED
        assert events_received[1].data["task_id"] == "test-task-2"
        assert "result" in events_received[1].data
        
        # Check statistics updated
        assert adapter.tasks_processed == 1
        assert adapter.tasks_failed == 0
    
    @pytest.mark.asyncio
    async def test_execute_task_sync_provider(self, event_bus, redis_backend):
        """Test executing task with synchronous provider"""
        # Create sync provider and adapter
        sync_provider = MockSyncProvider()
        adapter = ProviderPullAdapter(
            provider=sync_provider,
            event_bus=event_bus,
            redis_client=redis_backend.redis
        )
        
        # Execute task
        task_data = {
            "task_id": "sync-task",
            "workflow_id": "test-workflow",
            "method": "sync_method",
            "params": {"value": 42}
        }
        
        await adapter._execute_task(task_data)
        
        # Check provider executed task
        assert len(sync_provider.executed_tasks) == 1
        assert sync_provider.executed_tasks[0]["method"] == "sync_method"
        assert adapter.tasks_processed == 1
    
    @pytest.mark.asyncio
    async def test_task_execution_failure(self, event_bus, redis_backend):
        """Test handling task execution failure"""
        # Create provider that fails
        failing_provider = MockProvider(fail_on_execute=True)
        adapter = ProviderPullAdapter(
            provider=failing_provider,
            event_bus=event_bus,
            redis_client=redis_backend.redis
        )
        
        # Track failure events
        failure_events = []
        
        async def capture_failure(event):
            failure_events.append(event)
        
        event_bus.register(EventType.TASK_FAILED, capture_failure)
        
        # Execute task that will fail
        task_data = {
            "task_id": "failing-task",
            "workflow_id": "test-workflow",
            "method": "failing_method",
            "params": {}
        }
        
        await adapter._execute_task(task_data)
        
        # Check failure event emitted
        assert len(failure_events) == 1
        assert failure_events[0].data["task_id"] == "failing-task"
        assert "Mock failure" in failure_events[0].data["error"]
        
        # Check statistics
        assert adapter.tasks_processed == 0
        assert adapter.tasks_failed == 1
    
    @pytest.mark.asyncio
    async def test_remove_from_processing_queue(self, adapter, redis_backend):
        """Test removing task from processing queue after completion"""
        # Add task to processing queue
        task_data = {
            "task_id": "process-task",
            "method": "test"
        }
        
        await redis_backend.redis.lpush(
            adapter.processing_key,
            json.dumps(task_data)
        )
        
        # Remove task
        await adapter._remove_from_processing(task_data)
        
        # Check queue is empty
        processing_count = await redis_backend.redis.llen(adapter.processing_key)
        assert processing_count == 0
    
    @pytest.mark.asyncio
    async def test_recover_processing_tasks(self, adapter, redis_backend):
        """Test recovering tasks from processing queue after crash"""
        # Simulate crashed tasks in processing queue
        task1 = {"task_id": "crashed-1", "method": "m1"}
        task2 = {"task_id": "crashed-2", "method": "m2"}
        
        await redis_backend.redis.lpush(
            adapter.processing_key,
            json.dumps(task1),
            json.dumps(task2)
        )
        
        # Recover tasks
        await adapter.recover_processing_tasks()
        
        # Check tasks moved back to main queue
        queue_length = await redis_backend.redis.llen(adapter.queue_key)
        assert queue_length == 2
        
        # Check processing queue cleared
        processing_length = await redis_backend.redis.llen(adapter.processing_key)
        assert processing_length == 0
        
        # Verify tasks can be pulled again
        recovered_task = await adapter._pull_task()
        assert recovered_task["task_id"] in ["crashed-1", "crashed-2"]
    
    @pytest.mark.asyncio
    async def test_adapter_start_stop(self, adapter, redis_backend):
        """Test starting and stopping adapter"""
        # Add task to queue
        task_data = {
            "task_id": "start-stop-task",
            "workflow_id": "test",
            "method": "test",
            "params": {}
        }
        
        await redis_backend.redis.lpush(
            adapter.queue_key,
            json.dumps(task_data)
        )
        
        # Start adapter
        start_task = asyncio.create_task(adapter.start())
        
        # Let it process
        await asyncio.sleep(0.2)
        
        # Stop adapter
        await adapter.stop()
        
        # Cancel the start task
        start_task.cancel()
        try:
            await start_task
        except asyncio.CancelledError:
            pass
        
        # Check task was processed
        assert adapter.tasks_processed == 1
        assert not adapter.running
    
    @pytest.mark.asyncio
    async def test_get_adapter_stats(self, adapter):
        """Test getting adapter statistics"""
        # Set some stats
        adapter.tasks_processed = 10
        adapter.tasks_failed = 2
        adapter.started_at = datetime.utcnow()
        
        # Get stats
        stats = adapter.get_stats()
        
        assert stats["protocol"] == "test_protocol"
        assert stats["tasks_processed"] == 10
        assert stats["tasks_failed"] == 2
        assert stats["success_rate"] == 10 / 12  # 10 successful out of 12 total
        assert stats["queue_key"] == adapter.queue_key
        assert "uptime_seconds" in stats


class TestProviderPoolManager:
    """Test ProviderPoolManager functionality"""
    
    @pytest.mark.asyncio
    async def test_add_single_provider(self, event_bus, redis_backend):
        """Test adding a single provider to pool"""
        manager = ProviderPoolManager(event_bus, redis_backend.redis)
        provider = MockProvider(protocol_name="pooled")
        
        await manager.add_provider(provider, instances=1)
        
        assert "pooled" in manager.adapters
        assert len(manager.adapters["pooled"]) == 1
        assert isinstance(manager.adapters["pooled"][0], ProviderPullAdapter)
    
    @pytest.mark.asyncio
    async def test_add_multiple_provider_instances(self, event_bus, redis_backend):
        """Test adding multiple instances of same provider"""
        manager = ProviderPoolManager(event_bus, redis_backend.redis)
        provider = MockProvider(protocol_name="multi")
        
        await manager.add_provider(provider, instances=3)
        
        assert "multi" in manager.adapters
        assert len(manager.adapters["multi"]) == 3
        
        # All should be ProviderPullAdapter instances
        for adapter in manager.adapters["multi"]:
            assert isinstance(adapter, ProviderPullAdapter)
            assert adapter.protocol == "multi"
    
    @pytest.mark.asyncio
    async def test_start_stop_pool(self, event_bus, redis_backend):
        """Test starting and stopping provider pool"""
        manager = ProviderPoolManager(event_bus, redis_backend.redis)
        
        # Add providers
        provider1 = MockProvider(protocol_name="p1")
        provider2 = MockProvider(protocol_name="p2")
        
        await manager.add_provider(provider1, instances=2)
        await manager.add_provider(provider2, instances=1)
        
        # Start manager (briefly)
        start_task = asyncio.create_task(manager.start())
        
        # Let it run briefly
        await asyncio.sleep(0.1)
        
        # Stop manager
        await manager.stop()
        
        # Cancel start task
        start_task.cancel()
        try:
            await start_task
        except asyncio.CancelledError:
            pass
        
        assert not manager.running
    
    @pytest.mark.asyncio
    async def test_pool_stats(self, event_bus, redis_backend):
        """Test getting pool statistics"""
        manager = ProviderPoolManager(event_bus, redis_backend.redis)
        
        # Add providers
        provider1 = MockProvider(protocol_name="stats1")
        provider2 = MockProvider(protocol_name="stats2")
        
        await manager.add_provider(provider1, instances=2)
        await manager.add_provider(provider2, instances=1)
        
        # Get stats
        stats = manager.get_stats()
        
        assert "stats1" in stats
        assert stats["stats1"]["instances"] == 2
        assert len(stats["stats1"]["adapters"]) == 2
        
        assert "stats2" in stats
        assert stats["stats2"]["instances"] == 1
        assert len(stats["stats2"]["adapters"]) == 1


class TestIntegration:
    """Integration tests for provider pull system"""
    
    @pytest.mark.asyncio
    async def test_multiple_tasks_processing(self, event_bus, redis_backend):
        """Test processing multiple tasks in sequence"""
        provider = MockProvider(protocol_name="multi_test")
        adapter = ProviderPullAdapter(
            provider=provider,
            event_bus=event_bus,
            redis_client=redis_backend.redis,
            poll_interval=0.01
        )
        
        # Add multiple tasks to queue
        tasks = []
        for i in range(5):
            task = {
                "task_id": f"task-{i}",
                "workflow_id": "workflow",
                "method": f"method_{i}",
                "params": {"index": i}
            }
            tasks.append(task)
            await redis_backend.redis.lpush(
                adapter.queue_key,
                json.dumps(task)
            )
        
        # Start adapter
        start_task = asyncio.create_task(adapter.start())
        
        # Wait for processing
        await asyncio.sleep(0.5)
        
        # Stop adapter
        await adapter.stop()
        start_task.cancel()
        try:
            await start_task
        except asyncio.CancelledError:
            pass
        
        # Check all tasks processed
        assert adapter.tasks_processed == 5
        assert len(provider.executed_tasks) == 5
        
        # Check queue is empty
        queue_length = await redis_backend.redis.llen(adapter.queue_key)
        assert queue_length == 0
    
    @pytest.mark.asyncio
    async def test_concurrent_adapters(self, event_bus, redis_backend):
        """Test multiple adapters pulling from same queue"""
        provider1 = MockProvider(protocol_name="concurrent")
        provider2 = MockProvider(protocol_name="concurrent")
        
        adapter1 = ProviderPullAdapter(
            provider=provider1,
            event_bus=event_bus,
            redis_client=redis_backend.redis,
            poll_interval=0.01
        )
        
        adapter2 = ProviderPullAdapter(
            provider=provider2,
            event_bus=event_bus,
            redis_client=redis_backend.redis,
            poll_interval=0.01
        )
        
        # Add tasks to queue
        for i in range(10):
            task = {
                "task_id": f"concurrent-{i}",
                "workflow_id": "workflow",
                "method": f"method_{i}",
                "params": {}
            }
            await redis_backend.redis.lpush(
                "provider:queue:concurrent",
                json.dumps(task)
            )
        
        # Start both adapters
        task1 = asyncio.create_task(adapter1.start())
        task2 = asyncio.create_task(adapter2.start())
        
        # Wait for processing
        await asyncio.sleep(0.5)
        
        # Stop adapters
        await adapter1.stop()
        await adapter2.stop()
        
        task1.cancel()
        task2.cancel()
        try:
            await asyncio.gather(task1, task2)
        except asyncio.CancelledError:
            pass
        
        # Check all tasks were processed (distributed between adapters)
        total_processed = adapter1.tasks_processed + adapter2.tasks_processed
        total_executed = len(provider1.executed_tasks) + len(provider2.executed_tasks)
        
        assert total_processed == 10
        assert total_executed == 10
        
        # Both adapters should have processed some tasks
        assert adapter1.tasks_processed > 0
        assert adapter2.tasks_processed > 0