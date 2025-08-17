"""
Shared fixtures for client tests
"""

import pytest
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from typing import Dict, Any, Optional

from gleitzeit.client import GleitzeitClient
from gleitzeit.core.models import Task, Workflow, TaskResult, WorkflowExecution
from gleitzeit.hub.base import ResourceInstance, ResourceMetrics, ResourceStatus
from gleitzeit.persistence.unified_persistence import UnifiedPersistenceAdapter


@pytest.fixture
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_db_path():
    """Create temporary database path"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        path = Path(tmp.name)
    yield str(path)
    if path.exists():
        path.unlink()


@pytest.fixture
async def mock_persistence():
    """Create mock persistence adapter"""
    mock = Mock(spec=UnifiedPersistenceAdapter)
    
    # Task operations
    mock.save_task = AsyncMock(return_value=True)
    mock.get_task = AsyncMock(return_value=None)
    mock.get_task_result = AsyncMock(return_value=None)
    mock.update_task_status = AsyncMock(return_value=True)
    mock.list_tasks = AsyncMock(return_value=[])
    
    # Workflow operations
    mock.save_workflow = AsyncMock(return_value=True)
    mock.get_workflow = AsyncMock(return_value=None)
    mock.save_workflow_execution = AsyncMock(return_value=True)
    mock.get_workflow_execution = AsyncMock(return_value=None)
    
    # Resource operations
    mock.save_resource_instance = AsyncMock(return_value=True)
    mock.get_resource_instance = AsyncMock(return_value=None)
    mock.list_resource_instances = AsyncMock(return_value=[])
    mock.save_resource_metrics = AsyncMock(return_value=True)
    mock.get_resource_metrics = AsyncMock(return_value=None)
    
    # Queue operations
    mock.save_queue_state = AsyncMock(return_value=True)
    mock.get_queue_state = AsyncMock(return_value=None)
    
    # Lifecycle
    mock.initialize = AsyncMock()
    mock.shutdown = AsyncMock()
    mock.cleanup_old_data = AsyncMock(return_value=10)
    
    return mock


@pytest.fixture
async def mock_queue_manager():
    """Create mock queue manager"""
    from gleitzeit.task_queue import QueueManager
    
    mock = Mock(spec=QueueManager)
    mock.enqueue_task = AsyncMock(return_value=True)
    mock.dequeue_task = AsyncMock(return_value=None)
    mock.remove_task = AsyncMock(return_value=True)
    mock.get_queue_size = Mock(return_value=0)
    mock.queues = {}
    
    return mock


@pytest.fixture
async def client_with_mocks(mock_persistence, mock_queue_manager):
    """Create client with mocked dependencies"""
    client = GleitzeitClient(persistence_type="memory")
    
    # Inject mocks
    with patch('gleitzeit.client.PersistenceManager') as mock_pm:
        mock_pm.get_adapter.return_value = mock_persistence
        mock_pm.is_initialized.return_value = True
        
        client.adapter = mock_persistence
        client.queue_manager = mock_queue_manager
        client._initialized = True
        
        yield client


@pytest.fixture
async def memory_client():
    """Create client with memory persistence"""
    client = GleitzeitClient(persistence_type="memory")
    await client.initialize()
    yield client
    await client.shutdown()


@pytest.fixture
async def sqlite_client(temp_db_path):
    """Create client with SQLite persistence"""
    client = GleitzeitClient(
        persistence_type="sql",
        sql_db_path=temp_db_path
    )
    await client.initialize()
    yield client
    await client.shutdown()


@pytest.fixture
def sample_task():
    """Create sample task"""
    return Task(
        id="task-123",
        name="Test Task",
        protocol="llm/v1",
        method="chat",
        params={
            "model": "llama3.2",
            "messages": [{"role": "user", "content": "Hello"}]
        },
        status="queued"
    )


@pytest.fixture
def sample_workflow():
    """Create sample workflow"""
    return Workflow(
        id="wf-123",
        name="Test Workflow",
        tasks=[
            Task(
                id="task-1",
                name="First Task",
                protocol="llm/v1",
                method="chat",
                params={"model": "llama3.2"}
            ),
            Task(
                id="task-2",
                name="Second Task",
                protocol="python/v1",
                method="execute",
                params={"code": "print('hello')"},
                dependencies=["task-1"]
            )
        ]
    )


@pytest.fixture
def sample_task_result():
    """Create sample task result"""
    return TaskResult(
        task_id="task-123",
        status="completed",
        output="Task completed successfully",
        error=None,
        metadata={"duration": 1.5}
    )


@pytest.fixture
def sample_resource():
    """Create sample resource instance"""
    return {
        "id": "ollama-1",
        "hub_id": "ollama-hub",
        "type": "OLLAMA",
        "status": "healthy",
        "endpoint": "http://localhost:11434",
        "metadata": {
            "models": ["llama3.2", "codellama"],
            "version": "0.1.0"
        }
    }


@pytest.fixture
def sample_metrics():
    """Create sample resource metrics"""
    return ResourceMetrics(
        hub_id="ollama-hub",
        instance_id="ollama-1",
        cpu_usage=45.5,
        memory_usage=2048,
        disk_usage=10240,
        network_in=1000,
        network_out=2000,
        custom_metrics={
            "requests_per_second": 10,
            "average_latency_ms": 150
        }
    )


class MockAsyncContextManager:
    """Helper for testing async context managers"""
    
    def __init__(self, return_value=None):
        self.return_value = return_value
        self.entered = False
        self.exited = False
    
    async def __aenter__(self):
        self.entered = True
        return self.return_value
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.exited = True
        return False


@pytest.fixture
def mock_create_client():
    """Mock the create_client function"""
    async def _create_client(**kwargs):
        client = GleitzeitClient(**kwargs)
        client._initialized = True
        return client
    
    return _create_client