"""
Test streaming and WebSocket functionality in Gleitzeit Client
"""
import pytest
from unittest.mock import AsyncMock, Mock, MagicMock
from datetime import datetime
import asyncio
from gleitzeit.client import GleitzeitClient, ClientMode


@pytest.fixture
async def streaming_client():
    """Create a test client with streaming support"""
    client = GleitzeitClient(mode=ClientMode.API, api_host="localhost", api_port=8000)
    
    # Mock the adapter
    mock_adapter = AsyncMock()
    client._adapter = mock_adapter
    client._initialized = True
    
    return client


class TestWebSocketStreaming:
    """Test WebSocket streaming operations"""
    
    @pytest.mark.asyncio
    async def test_stream_task_logs(self, streaming_client):
        """Test streaming task logs via WebSocket"""
        task_id = "task-123"
        mock_logs = [
            {"timestamp": "2025-01-01T10:00:00", "message": "Task started"},
            {"timestamp": "2025-01-01T10:00:01", "message": "Processing"},
            {"timestamp": "2025-01-01T10:00:02", "message": "Task completed"}
        ]
        
        async def mock_stream(task_id):
            for log in mock_logs:
                yield log
        
        streaming_client._adapter.stream_task_logs = mock_stream
        
        collected_logs = []
        async for log in streaming_client.stream_task_logs(task_id):
            collected_logs.append(log)
        
        assert collected_logs == mock_logs
    
    @pytest.mark.asyncio
    async def test_stream_task_logs_with_callback(self, streaming_client):
        """Test streaming task logs with callback"""
        task_id = "task-123"
        callback_logs = []
        
        def callback(log):
            callback_logs.append(log)
        
        mock_logs = [
            {"timestamp": "2025-01-01T10:00:00", "message": "Log 1"},
            {"timestamp": "2025-01-01T10:00:01", "message": "Log 2"}
        ]
        
        async def mock_stream(task_id):
            for log in mock_logs:
                yield log
        
        streaming_client._adapter.stream_task_logs = mock_stream
        
        collected_logs = []
        async for log in streaming_client.stream_task_logs(task_id, callback=callback):
            collected_logs.append(log)
        
        assert collected_logs == mock_logs
        assert callback_logs == mock_logs
    
    @pytest.mark.asyncio
    async def test_stream_workflow_logs(self, streaming_client):
        """Test streaming workflow logs via WebSocket"""
        workflow_id = "workflow-456"
        mock_logs = [
            {"timestamp": "2025-01-01T10:00:00", "message": "Workflow started"},
            {"timestamp": "2025-01-01T10:05:00", "message": "Task 1 completed"},
            {"timestamp": "2025-01-01T10:10:00", "message": "Workflow completed"}
        ]
        
        async def mock_stream(workflow_id):
            for log in mock_logs:
                yield log
        
        streaming_client._adapter.stream_workflow_logs = mock_stream
        
        collected_logs = []
        async for log in streaming_client.stream_workflow_logs(workflow_id):
            collected_logs.append(log)
        
        assert collected_logs == mock_logs
    
    @pytest.mark.asyncio
    async def test_stream_all_logs(self, streaming_client):
        """Test streaming all system logs"""
        mock_logs = [
            {"timestamp": "2025-01-01T10:00:00", "level": "INFO", "message": "System log 1"},
            {"timestamp": "2025-01-01T10:00:01", "level": "ERROR", "message": "System log 2"}
        ]
        
        async def mock_stream(level=None):
            for log in mock_logs:
                yield log
        
        streaming_client._adapter.stream_all_logs = mock_stream
        
        collected_logs = []
        async for log in streaming_client.stream_all_logs(level="INFO"):
            collected_logs.append(log)
        
        assert collected_logs == mock_logs
    
    @pytest.mark.asyncio
    async def test_stream_not_supported(self, streaming_client):
        """Test error when adapter doesn't support streaming"""
        # Remove the streaming method
        if hasattr(streaming_client._adapter, 'stream_task_logs'):
            delattr(streaming_client._adapter, 'stream_task_logs')
        
        with pytest.raises(NotImplementedError, match="does not support WebSocket streaming"):
            async for _ in streaming_client.stream_task_logs("task-123"):
                pass


class TestEventStreaming:
    """Test event streaming operations"""
    
    @pytest.mark.asyncio
    async def test_stream_events(self, streaming_client):
        """Test streaming system events"""
        mock_events = [
            {"type": "task_started", "task_id": "task-1", "timestamp": "2025-01-01T10:00:00"},
            {"type": "task_completed", "task_id": "task-1", "timestamp": "2025-01-01T10:05:00"}
        ]
        
        async def mock_stream(filter=None):
            for event in mock_events:
                yield event
        
        streaming_client._adapter.stream_events = mock_stream
        
        collected_events = []
        async for event in streaming_client.stream_events(filter="task_*"):
            collected_events.append(event)
        
        assert collected_events == mock_events
    
    @pytest.mark.asyncio
    async def test_stream_events_fallback_polling(self, streaming_client):
        """Test event streaming falls back to polling when WebSocket not available"""
        # Remove stream_events to trigger fallback
        if hasattr(streaming_client._adapter, 'stream_events'):
            delattr(streaming_client._adapter, 'stream_events')
        
        mock_response = {
            "events": [
                {"type": "event1", "timestamp": "2025-01-01T10:00:00"},
                {"type": "event2", "timestamp": "2025-01-01T10:00:01"}
            ]
        }
        
        call_count = 0
        async def mock_get_event_stream(filter, follow):
            nonlocal call_count
            call_count += 1
            if call_count > 2:  # Stop after 2 calls
                return {"events": []}
            return mock_response
        
        streaming_client._adapter.get_event_stream = mock_get_event_stream
        
        collected_events = []
        async for event in streaming_client.stream_events():
            collected_events.append(event)
            if len(collected_events) >= 4:  # 2 events x 2 calls
                break
        
        assert len(collected_events) == 4
    
    @pytest.mark.asyncio
    async def test_stream_workflow_events(self, streaming_client):
        """Test streaming workflow-specific events"""
        workflow_id = "workflow-456"
        mock_events = [
            {"type": "task_started", "workflow_id": workflow_id, "task_id": "task-1"},
            {"type": "task_completed", "workflow_id": workflow_id, "task_id": "task-1"}
        ]
        
        async def mock_stream(workflow_id):
            for event in mock_events:
                yield event
        
        streaming_client._adapter.stream_workflow_events = mock_stream
        
        collected_events = []
        async for event in streaming_client.stream_workflow_events(workflow_id):
            collected_events.append(event)
        
        assert collected_events == mock_events


class TestFileOperations:
    """Test file upload and processing operations"""
    
    @pytest.mark.asyncio
    async def test_upload_workflow_file(self, streaming_client):
        """Test uploading workflow file"""
        import tempfile
        import yaml
        
        workflow_def = {
            "name": "Test Workflow",
            "tasks": [
                {"name": "Task 1", "protocol": "python/v1", "method": "execute"}
            ]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(workflow_def, f)
            file_path = f.name
        
        expected_result = {
            "workflow_id": "workflow-123",
            "status": "uploaded",
            "submitted": True
        }
        
        streaming_client._adapter.upload_workflow_file.return_value = expected_result
        
        result = await streaming_client.upload_workflow_file(file_path, auto_submit=True)
        
        assert result == expected_result
        streaming_client._adapter.upload_workflow_file.assert_called_once()
        
        # Clean up
        import os
        os.unlink(file_path)
    
    @pytest.mark.asyncio
    async def test_upload_workflow_file_not_found(self, streaming_client):
        """Test error when workflow file not found"""
        with pytest.raises(FileNotFoundError, match="Workflow file not found"):
            await streaming_client.upload_workflow_file("/nonexistent/file.yaml")
    
    @pytest.mark.asyncio
    async def test_bulk_process_directory(self, streaming_client):
        """Test bulk processing entire directory"""
        expected_result = {
            "processed": 10,
            "failed": 0,
            "results": {"file1.txt": "processed", "file2.txt": "processed"}
        }
        
        streaming_client._adapter.bulk_process_directory.return_value = expected_result
        
        result = await streaming_client.bulk_process_directory(
            "/path/to/dir",
            pattern="*.txt",
            method="analyze",
            recursive=True
        )
        
        assert result == expected_result
        streaming_client._adapter.bulk_process_directory.assert_called_once_with(
            "/path/to/dir",
            "*.txt",
            "analyze",
            True
        )


class TestAuthenticationOperations:
    """Test authentication lifecycle operations"""
    
    @pytest.mark.asyncio
    async def test_refresh_auth_token(self, streaming_client):
        """Test refreshing authentication token"""
        expected_result = {
            "token": "new_token_123",
            "expires_at": "2025-01-02T10:00:00"
        }
        
        streaming_client._adapter.refresh_auth_token.return_value = expected_result
        
        result = await streaming_client.refresh_auth_token()
        
        assert result == expected_result
        streaming_client._adapter.refresh_auth_token.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_change_password(self, streaming_client):
        """Test changing user password"""
        expected_result = {
            "changed": True,
            "message": "Password successfully changed"
        }
        
        streaming_client._adapter.change_password.return_value = expected_result
        
        result = await streaming_client.change_password("old_pass", "new_pass")
        
        assert result == expected_result
        streaming_client._adapter.change_password.assert_called_once_with("old_pass", "new_pass")


class TestAdvancedLogOperations:
    """Test advanced log operations"""
    
    @pytest.mark.asyncio
    async def test_search_logs(self, streaming_client):
        """Test advanced log search"""
        expected_logs = [
            {"timestamp": "2025-01-01T10:00:00", "message": "Error in task"},
            {"timestamp": "2025-01-01T10:05:00", "message": "Error in workflow"}
        ]
        
        streaming_client._adapter.search_logs.return_value = expected_logs
        
        result = await streaming_client.search_logs(
            "error",
            advanced_filters={"level": "ERROR", "source": "worker"},
            limit=50
        )
        
        assert result == expected_logs
        streaming_client._adapter.search_logs.assert_called_once_with(
            "error",
            {"level": "ERROR", "source": "worker"},
            50
        )
    
    @pytest.mark.asyncio
    async def test_set_log_retention(self, streaming_client):
        """Test setting log retention policy"""
        expected_result = {
            "days": 30,
            "level": "INFO",
            "updated": True
        }
        
        streaming_client._adapter.set_log_retention.return_value = expected_result
        
        result = await streaming_client.set_log_retention(30, log_level="INFO")
        
        assert result == expected_result
        streaming_client._adapter.set_log_retention.assert_called_once_with(30, "INFO")


class TestSystemOperations:
    """Test system maintenance operations"""
    
    @pytest.mark.asyncio
    async def test_cleanup_system(self, streaming_client):
        """Test system cleanup"""
        expected_result = {
            "logs_deleted": 10000,
            "results_deleted": 500,
            "space_freed": "2.5GB"
        }
        
        streaming_client._adapter.cleanup_system.return_value = expected_result
        
        result = await streaming_client.cleanup_system(
            older_than_days=30,
            include_logs=True,
            include_results=True
        )
        
        assert result == expected_result
        streaming_client._adapter.cleanup_system.assert_called_once_with(30, True, True)
    
    @pytest.mark.asyncio
    async def test_get_api_info(self, streaming_client):
        """Test getting API information"""
        expected_info = {
            "version": "1.0.0",
            "name": "Gleitzeit API",
            "endpoints": 89,
            "status": "healthy"
        }
        
        streaming_client._adapter.get_api_info.return_value = expected_info
        
        result = await streaming_client.get_api_info()
        
        assert result == expected_info
        streaming_client._adapter.get_api_info.assert_called_once()


class TestMonitoringOperations:
    """Test combined monitoring operations"""
    
    @pytest.mark.skip(reason="Complex async streaming test - needs proper implementation")
    @pytest.mark.asyncio
    async def test_monitor_task(self, streaming_client):
        """Test monitoring task with combined logs and events"""
        task_id = "task-123"
        
        async def mock_log_stream():
            yield {"type": "log", "message": "Task started"}
            yield {"type": "log", "message": "Processing"}
        
        async def mock_event_stream():
            yield {"type": "event", "name": "task_started"}
            yield {"type": "event", "name": "task_progress"}
        
        streaming_client.stream_task_logs = AsyncMock(return_value=mock_log_stream())
        streaming_client.stream_events = AsyncMock(return_value=mock_event_stream())
        
        collected = []
        async for item in streaming_client.monitor_task(task_id, include_logs=True, include_events=True):
            collected.append(item)
            if len(collected) >= 4:  # Collect at least 4 items
                break
        
        # Should have collected items from both streams
        assert len(collected) >= 2  # At least some items collected
    
    @pytest.mark.asyncio
    async def test_not_initialized_error(self):
        """Test error when client not initialized"""
        client = GleitzeitClient(mode="api")
        # Don't initialize
        
        with pytest.raises(RuntimeError, match="Client not initialized"):
            async for _ in client.stream_task_logs("task-123"):
                pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])