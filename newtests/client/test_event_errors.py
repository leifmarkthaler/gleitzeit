"""
Test event error management functionality in Gleitzeit Client
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


class TestEventErrorManagement:
    """Test event error management methods"""
    
    @pytest.mark.asyncio
    async def test_get_event_errors(self, client):
        """Test getting event errors with filters"""
        expected_errors = [
            {
                "id": "error-1",
                "status": "new",
                "severity": "high",
                "message": "Task execution failed",
                "timestamp": "2025-01-01T10:00:00"
            },
            {
                "id": "error-2", 
                "status": "acknowledged",
                "severity": "low",
                "message": "Retry succeeded",
                "timestamp": "2025-01-01T10:01:00"
            }
        ]
        
        client._adapter.get_event_errors.return_value = expected_errors
        
        result = await client.get_event_errors(
            status="new",
            severity="high",
            limit=50,
            offset=10
        )
        
        assert result == expected_errors
        client._adapter.get_event_errors.assert_called_once_with(
            status="new",
            severity="high",
            start_time=None,
            end_time=None,
            limit=50,
            offset=10
        )
    
    @pytest.mark.asyncio
    async def test_get_event_errors_with_time_range(self, client):
        """Test getting event errors with time range"""
        start_time = datetime(2025, 1, 1, 9, 0, 0)
        end_time = datetime(2025, 1, 1, 11, 0, 0)
        
        expected_errors = [{"id": "error-1", "timestamp": "2025-01-01T10:00:00"}]
        client._adapter.get_event_errors.return_value = expected_errors
        
        result = await client.get_event_errors(
            start_time=start_time,
            end_time=end_time
        )
        
        assert result == expected_errors
        client._adapter.get_event_errors.assert_called_once_with(
            status=None,
            severity=None,
            start_time=start_time,
            end_time=end_time,
            limit=100,
            offset=0
        )
    
    @pytest.mark.asyncio
    async def test_get_event_error(self, client):
        """Test getting specific event error"""
        error_id = "error-123"
        expected_error = {
            "id": error_id,
            "status": "new",
            "severity": "critical",
            "message": "Database connection failed",
            "stack_trace": "...",
            "context": {"task_id": "task-456"}
        }
        
        client._adapter.get_event_error.return_value = expected_error
        
        result = await client.get_event_error(error_id)
        
        assert result == expected_error
        client._adapter.get_event_error.assert_called_once_with(error_id)
    
    @pytest.mark.asyncio
    async def test_retry_event_error(self, client):
        """Test retrying a failed event"""
        error_id = "error-123"
        expected_result = {
            "error_id": error_id,
            "status": "retry_initiated",
            "new_task_id": "task-789"
        }
        
        client._adapter.retry_event_error.return_value = expected_result
        
        result = await client.retry_event_error(error_id)
        
        assert result == expected_result
        client._adapter.retry_event_error.assert_called_once_with(error_id)
    
    @pytest.mark.asyncio
    async def test_acknowledge_event_error(self, client):
        """Test acknowledging an event error"""
        error_id = "error-123"
        notes = "Investigating the issue"
        expected_result = {
            "error_id": error_id,
            "status": "acknowledged",
            "acknowledged_at": "2025-01-01T10:00:00",
            "notes": notes
        }
        
        client._adapter.acknowledge_event_error.return_value = expected_result
        
        result = await client.acknowledge_event_error(error_id, notes)
        
        assert result == expected_result
        client._adapter.acknowledge_event_error.assert_called_once_with(error_id, notes)
    
    @pytest.mark.asyncio
    async def test_acknowledge_event_error_without_notes(self, client):
        """Test acknowledging without notes"""
        error_id = "error-123"
        expected_result = {"error_id": error_id, "status": "acknowledged"}
        
        client._adapter.acknowledge_event_error.return_value = expected_result
        
        result = await client.acknowledge_event_error(error_id)
        
        assert result == expected_result
        client._adapter.acknowledge_event_error.assert_called_once_with(error_id, None)
    
    @pytest.mark.asyncio
    async def test_resolve_event_error(self, client):
        """Test resolving an event error"""
        error_id = "error-123"
        resolution = "Fixed database connection settings"
        notes = "Updated connection pool configuration"
        expected_result = {
            "error_id": error_id,
            "status": "resolved",
            "resolution": resolution,
            "resolved_at": "2025-01-01T10:00:00",
            "notes": notes
        }
        
        client._adapter.resolve_event_error.return_value = expected_result
        
        result = await client.resolve_event_error(error_id, resolution, notes)
        
        assert result == expected_result
        client._adapter.resolve_event_error.assert_called_once_with(error_id, resolution, notes)
    
    @pytest.mark.asyncio
    async def test_ignore_event_error(self, client):
        """Test ignoring an event error"""
        error_id = "error-123"
        reason = "Known intermittent issue, will be fixed in next release"
        expected_result = {
            "error_id": error_id,
            "status": "ignored",
            "reason": reason,
            "ignored_at": "2025-01-01T10:00:00"
        }
        
        client._adapter.ignore_event_error.return_value = expected_result
        
        result = await client.ignore_event_error(error_id, reason)
        
        assert result == expected_result
        client._adapter.ignore_event_error.assert_called_once_with(error_id, reason)
    
    @pytest.mark.asyncio
    async def test_delete_event_error(self, client):
        """Test deleting an event error"""
        error_id = "error-123"
        expected_result = {
            "error_id": error_id,
            "deleted": True,
            "message": "Event error deleted successfully"
        }
        
        client._adapter.delete_event_error.return_value = expected_result
        
        result = await client.delete_event_error(error_id)
        
        assert result == expected_result
        client._adapter.delete_event_error.assert_called_once_with(error_id)
    
    @pytest.mark.asyncio
    async def test_get_event_error_statistics(self, client):
        """Test getting event error statistics"""
        start_time = datetime(2025, 1, 1)
        end_time = datetime(2025, 1, 2)
        expected_stats = {
            "total_errors": 150,
            "by_status": {
                "new": 10,
                "acknowledged": 20,
                "resolved": 100,
                "ignored": 20
            },
            "by_severity": {
                "low": 50,
                "medium": 60,
                "high": 30,
                "critical": 10
            },
            "error_rate": 6.25,  # errors per hour
            "resolution_rate": 0.67  # 100/150
        }
        
        client._adapter.get_event_error_statistics.return_value = expected_stats
        
        result = await client.get_event_error_statistics(start_time, end_time)
        
        assert result == expected_stats
        client._adapter.get_event_error_statistics.assert_called_once_with(start_time, end_time)
    
    @pytest.mark.asyncio
    async def test_get_event_error_statistics_no_time_range(self, client):
        """Test getting statistics without time range"""
        expected_stats = {"total_errors": 500, "by_status": {}}
        
        client._adapter.get_event_error_statistics.return_value = expected_stats
        
        result = await client.get_event_error_statistics()
        
        assert result == expected_stats
        client._adapter.get_event_error_statistics.assert_called_once_with(None, None)
    
    @pytest.mark.asyncio
    async def test_bulk_acknowledge_errors(self, client):
        """Test bulk acknowledging errors"""
        error_ids = ["error-1", "error-2", "error-3"]
        notes = "Batch acknowledgment during maintenance"
        expected_result = {
            "acknowledged": 3,
            "failed": 0,
            "results": [
                {"error_id": "error-1", "status": "acknowledged"},
                {"error_id": "error-2", "status": "acknowledged"},
                {"error_id": "error-3", "status": "acknowledged"}
            ]
        }
        
        client._adapter.bulk_acknowledge_errors.return_value = expected_result
        
        result = await client.bulk_acknowledge_errors(error_ids, notes)
        
        assert result == expected_result
        client._adapter.bulk_acknowledge_errors.assert_called_once_with(error_ids, notes)
    
    @pytest.mark.asyncio
    async def test_bulk_retry_errors(self, client):
        """Test bulk retrying errors"""
        error_ids = ["error-1", "error-2", "error-3"]
        expected_result = {
            "retried": 2,
            "failed": 1,
            "results": [
                {"error_id": "error-1", "status": "retry_initiated", "new_task_id": "task-100"},
                {"error_id": "error-2", "status": "retry_initiated", "new_task_id": "task-101"},
                {"error_id": "error-3", "status": "retry_failed", "reason": "Task no longer exists"}
            ]
        }
        
        client._adapter.bulk_retry_errors.return_value = expected_result
        
        result = await client.bulk_retry_errors(error_ids)
        
        assert result == expected_result
        client._adapter.bulk_retry_errors.assert_called_once_with(error_ids)
    
    @pytest.mark.asyncio
    async def test_not_initialized_error(self):
        """Test error when client not initialized"""
        client = GleitzeitClient(mode="api")
        # Don't initialize
        
        with pytest.raises(RuntimeError, match="Client not initialized"):
            await client.get_event_errors()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])