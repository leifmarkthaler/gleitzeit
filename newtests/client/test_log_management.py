"""
Test log management functionality in Gleitzeit Client
"""
import pytest
from unittest.mock import AsyncMock
from datetime import datetime
from gleitzeit.client import GleitzeitClient, ClientMode


@pytest.fixture
async def client():
    """Create a test client with mocked adapter"""
    client = GleitzeitClient(mode=ClientMode.API, api_host="localhost", api_port=8000)
    
    # Mock the adapter
    mock_adapter = AsyncMock()
    client._adapter = mock_adapter
    client._initialized = True
    
    return client


class TestLogManagement:
    """Test log management methods"""
    
    @pytest.mark.asyncio
    async def test_get_logs(self, client):
        """Test getting logs with filters"""
        expected_logs = [
            {"timestamp": "2025-01-01T10:00:00", "level": "INFO", "message": "Test log 1"},
            {"timestamp": "2025-01-01T10:01:00", "level": "ERROR", "message": "Test log 2"}
        ]
        
        client._adapter.get_logs.return_value = expected_logs
        
        result = await client.get_logs(
            level="INFO",
            source="worker",
            limit=50,
            offset=10
        )
        
        assert result == expected_logs
        client._adapter.get_logs.assert_called_once_with(
            level="INFO",
            source="worker",
            start_time=None,
            end_time=None,
            limit=50,
            offset=10
        )
    
    @pytest.mark.asyncio
    async def test_get_logs_with_time_range(self, client):
        """Test getting logs with time range"""
        start_time = datetime(2025, 1, 1, 9, 0, 0)
        end_time = datetime(2025, 1, 1, 11, 0, 0)
        
        expected_logs = [{"timestamp": "2025-01-01T10:00:00", "level": "INFO", "message": "Test"}]
        client._adapter.get_logs.return_value = expected_logs
        
        result = await client.get_logs(
            start_time=start_time,
            end_time=end_time
        )
        
        assert result == expected_logs
        client._adapter.get_logs.assert_called_once_with(
            level=None,
            source=None,
            start_time=start_time,
            end_time=end_time,
            limit=100,
            offset=0
        )
    
    @pytest.mark.asyncio
    async def test_get_log_levels(self, client):
        """Test getting available log levels"""
        expected_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        client._adapter.get_log_levels.return_value = expected_levels
        
        result = await client.get_log_levels()
        
        assert result == expected_levels
        client._adapter.get_log_levels.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_query_logs(self, client):
        """Test querying logs with search string"""
        query = "error in worker"
        expected_logs = [
            {"timestamp": "2025-01-01T10:00:00", "message": "error in worker process"}
        ]
        
        client._adapter.query_logs.return_value = expected_logs
        
        result = await client.query_logs(query, limit=20, offset=5)
        
        assert result == expected_logs
        client._adapter.query_logs.assert_called_once_with(query, 20, 5)
    
    @pytest.mark.asyncio
    async def test_tail_logs(self, client):
        """Test tailing logs"""
        expected_logs = [
            {"timestamp": "2025-01-01T10:00:00", "message": "Recent log 1"},
            {"timestamp": "2025-01-01T10:00:01", "message": "Recent log 2"}
        ]
        
        client._adapter.tail_logs.return_value = expected_logs
        
        result = await client.tail_logs(lines=50, follow=True, source="api")
        
        assert result == expected_logs
        client._adapter.tail_logs.assert_called_once_with(50, True, "api")
    
    @pytest.mark.asyncio
    async def test_download_logs(self, client):
        """Test downloading logs"""
        expected_data = b"log,data,here"
        client._adapter.download_logs.return_value = expected_data
        
        result = await client.download_logs(
            format="csv",
            start_time=datetime(2025, 1, 1),
            end_time=datetime(2025, 1, 2)
        )
        
        assert result == expected_data
        client._adapter.download_logs.assert_called_once_with(
            "csv",
            datetime(2025, 1, 1),
            datetime(2025, 1, 2)
        )
    
    @pytest.mark.asyncio
    async def test_clear_logs(self, client):
        """Test clearing logs"""
        before_time = datetime(2025, 1, 1)
        expected_result = {"cleared": 1000, "status": "success"}
        
        client._adapter.clear_logs.return_value = expected_result
        
        result = await client.clear_logs(before=before_time, level="DEBUG")
        
        assert result == expected_result
        client._adapter.clear_logs.assert_called_once_with(before_time, "DEBUG")
    
    @pytest.mark.asyncio
    async def test_get_log_size(self, client):
        """Test getting log storage size"""
        expected_size = {
            "bytes": 1048576,
            "human_readable": "1.0 MB",
            "files": 5
        }
        
        client._adapter.get_log_size.return_value = expected_size
        
        result = await client.get_log_size()
        
        assert result == expected_size
        client._adapter.get_log_size.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_task_logs(self, client):
        """Test getting logs for specific task"""
        task_id = "task-123"
        expected_logs = [
            {"timestamp": "2025-01-01T10:00:00", "task_id": task_id, "message": "Task started"},
            {"timestamp": "2025-01-01T10:00:05", "task_id": task_id, "message": "Task completed"}
        ]
        
        client._adapter.get_task_logs.return_value = expected_logs
        
        result = await client.get_task_logs(task_id)
        
        assert result == expected_logs
        client._adapter.get_task_logs.assert_called_once_with(task_id)
    
    @pytest.mark.asyncio
    async def test_get_workflow_logs(self, client):
        """Test getting logs for specific workflow"""
        workflow_id = "workflow-456"
        expected_logs = [
            {"timestamp": "2025-01-01T10:00:00", "workflow_id": workflow_id, "message": "Workflow started"},
            {"timestamp": "2025-01-01T10:10:00", "workflow_id": workflow_id, "message": "Workflow completed"}
        ]
        
        client._adapter.get_workflow_logs.return_value = expected_logs
        
        result = await client.get_workflow_logs(workflow_id)
        
        assert result == expected_logs
        client._adapter.get_workflow_logs.assert_called_once_with(workflow_id)
    
    @pytest.mark.asyncio
    async def test_not_initialized_error(self):
        """Test error when client not initialized"""
        client = GleitzeitClient(mode="api")
        # Don't initialize
        
        with pytest.raises(RuntimeError, match="Client not initialized"):
            await client.get_logs()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])