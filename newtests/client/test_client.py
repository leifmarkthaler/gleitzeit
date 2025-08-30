"""
Test the Gleitzeit Client - Real Methods Only
"""
import pytest
import asyncio
from unittest.mock import AsyncMock
from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.core.models import Task, Workflow, TaskStatus


@pytest.fixture
async def api_client():
    """Create a client in API mode with mocked adapter"""
    client = GleitzeitClient(mode=ClientMode.API, api_host="localhost", api_port=8000)
    
    # Mock the adapter to avoid actual HTTP calls
    mock_adapter = AsyncMock()
    client._adapter = mock_adapter
    client._initialized = True
    
    return client


@pytest.fixture
def sample_task():
    """Create a sample task"""
    return Task(
        name="Test Task",
        protocol="python/v1", 
        method="execute",
        params={"script": "test.py"}
    )


@pytest.fixture
def sample_workflow():
    """Create a sample workflow"""
    return Workflow(
        name="Test Workflow",
        tasks=[
            Task(
                name="First Task",
                protocol="python/v1",
                method="execute", 
                params={"script": "first.py"}
            )
        ]
    )


class TestTaskOperations:
    """Test real task operations"""
    
    @pytest.mark.asyncio
    async def test_submit_task(self, api_client, sample_task):
        """Test submitting a task"""
        expected_result = {"task_id": "task-123", "status": "submitted"}
        api_client._adapter.submit_task.return_value = expected_result
        
        result = await api_client.submit_task(sample_task)
        
        assert result == expected_result
        api_client._adapter.submit_task.assert_called_once_with(sample_task)
    
    @pytest.mark.asyncio
    async def test_get_task(self, api_client):
        """Test getting a task"""
        task_id = "task-123"
        expected_task = Task(name="Test Task", protocol="python/v1", method="execute")
        
        api_client._adapter.get_task.return_value = expected_task
        
        result = await api_client.get_task(task_id)
        
        assert result == expected_task
        api_client._adapter.get_task.assert_called_once_with(task_id)
    
    @pytest.mark.asyncio
    async def test_get_task_status(self, api_client):
        """Test getting task status"""
        task_id = "task-123"
        mock_task = AsyncMock()
        mock_task.status = TaskStatus.EXECUTING
        
        api_client._adapter.get_task.return_value = mock_task
        
        result = await api_client.get_task_status(task_id)
        
        assert result == "executing"
        api_client._adapter.get_task.assert_called_once_with(task_id)
    
    @pytest.mark.asyncio
    async def test_list_tasks(self, api_client):
        """Test listing tasks"""
        expected_tasks = {
            "tasks": [
                {"id": "task-1", "name": "Task 1", "status": "completed"},
                {"id": "task-2", "name": "Task 2", "status": "executing"}
            ],
            "total": 2
        }
        
        api_client._adapter.list_tasks.return_value = expected_tasks
        
        result = await api_client.list_tasks(status="executing", limit=50)
        
        assert result == expected_tasks
        api_client._adapter.list_tasks.assert_called_once_with("executing", None, 50, 0)
    
    @pytest.mark.asyncio
    async def test_cancel_task(self, api_client):
        """Test cancelling a task"""
        task_id = "task-123"
        
        api_client._adapter.cancel_task.return_value = True
        
        result = await api_client.cancel_task(task_id)
        
        assert result is True
        api_client._adapter.cancel_task.assert_called_once_with(task_id)


class TestWorkflowOperations:
    """Test real workflow operations"""
    
    @pytest.mark.asyncio
    async def test_submit_workflow(self, api_client, sample_workflow):
        """Test submitting a workflow"""
        expected_result = {"workflow_id": "workflow-123", "status": "submitted"}
        
        api_client._adapter.submit_workflow.return_value = expected_result
        
        result = await api_client.submit_workflow(sample_workflow)
        
        assert result == expected_result
        api_client._adapter.submit_workflow.assert_called_once_with(sample_workflow)
    
    @pytest.mark.asyncio
    async def test_cancel_workflow(self, api_client):
        """Test cancelling a workflow"""
        workflow_id = "workflow-123"
        expected_result = {"workflow_id": workflow_id, "status": "cancelled"}
        
        api_client._adapter.cancel_workflow.return_value = expected_result
        
        result = await api_client.cancel_workflow(workflow_id)
        
        assert result == expected_result
        api_client._adapter.cancel_workflow.assert_called_once_with(workflow_id)


class TestClientInitialization:
    """Test client initialization and configuration"""
    
    def test_client_mode_configuration(self):
        """Test client mode configuration"""
        client = GleitzeitClient(
            mode="api",
            api_host="example.com", 
            api_port=9000,
            auto_start_server=False
        )
        
        assert client.mode == ClientMode.API
        assert client.api_host == "example.com"
        assert client.api_port == 9000
        assert client.auto_start_server == False
    
    def test_client_mode_enum(self):
        """Test client mode using enum"""
        client = GleitzeitClient(mode=ClientMode.NATIVE)
        
        assert client.mode == ClientMode.NATIVE
    
    @pytest.mark.asyncio
    async def test_client_not_initialized_error(self):
        """Test error when client not initialized"""
        client = GleitzeitClient(mode="native")
        # Don't set _adapter or _initialized
        
        with pytest.raises(RuntimeError, match="Client not initialized"):
            await client.submit_task({"name": "test", "protocol": "test/v1", "method": "test"})
    
    def test_client_properties(self):
        """Test client property access"""
        client = GleitzeitClient(mode="api", api_host="test.com", api_port=8080)
        
        assert client.get_mode() == "api"
        assert client.is_initialized() == False
        
        # Mock initialization
        client._initialized = True
        assert client.is_initialized() == True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])