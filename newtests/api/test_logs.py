"""
Tests for logging API endpoints.
"""

import pytest
from fastapi import status
from datetime import datetime


class TestLogEndpoints:
    """Test logging API endpoints."""
    
    def test_get_logs(self, client, mock_client):
        """Test get logs with filters."""
        response = client.get(
            "/logs/",
            params={
                "level": "INFO",
                "source": "api",
                "limit": 50,
                "offset": 0
            }
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "log_1"
        assert data[0]["level"] == "INFO"
        assert data[0]["message"] == "Test log"
        
        mock_client.get_logs.assert_called_once_with(
            level="INFO",
            source="api",
            start_time=None,
            end_time=None,
            limit=50,
            offset=0
        )
    
    def test_get_logs_default_params(self, client, mock_client):
        """Test get logs with default parameters."""
        response = client.get("/logs/")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        
        mock_client.get_logs.assert_called_once_with(
            level=None,
            source=None,
            start_time=None,
            end_time=None,
            limit=100,
            offset=0
        )
    
    def test_get_logs_with_time_range(self, client, mock_client):
        """Test get logs with time range."""
        start_time = "2023-01-01T00:00:00"
        end_time = "2023-01-02T00:00:00"
        
        response = client.get(
            "/logs/",
            params={
                "start_time": start_time,
                "end_time": end_time
            }
        )
        
        assert response.status_code == status.HTTP_200_OK
        mock_client.get_logs.assert_called_once()
    
    def test_get_log_levels(self, client, mock_client):
        """Test get available log levels."""
        response = client.get("/logs/levels")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "DEBUG" in data
        assert "INFO" in data
        assert "WARNING" in data
        assert "ERROR" in data
        assert "CRITICAL" in data
        
        mock_client.get_log_levels.assert_called_once()
    
    def test_get_log_sources(self, client, mock_client):
        """Test get available log sources."""
        response = client.get("/logs/sources")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "api" in data
        assert "worker" in data
        assert "scheduler" in data
        
        mock_client.get_log_sources.assert_called_once()
    
    def test_get_task_logs(self, client, mock_client):
        """Test get logs for specific task."""
        response = client.get(
            "/logs/task/task_123",
            params={"level": "ERROR", "limit": 25}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["task_id"] == "task_123"
        assert data[0]["message"] == "Task log"
        
        mock_client.get_task_logs.assert_called_once_with(
            task_id="task_123",
            level="ERROR",
            limit=25,
            offset=0
        )
    
    def test_get_workflow_logs(self, client, mock_client):
        """Test get logs for specific workflow."""
        response = client.get(
            "/logs/workflow/wf_123",
            params={"limit": 10, "offset": 5}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["workflow_id"] == "wf_123"
        assert data[0]["message"] == "Workflow log"
        
        mock_client.get_workflow_logs.assert_called_once_with(
            workflow_id="wf_123",
            level=None,
            limit=10,
            offset=5
        )
    
    def test_clear_logs(self, client, admin_headers, mock_client):
        """Test clear logs (admin only)."""
        response = client.delete(
            "/logs/",
            params={
                "level": "DEBUG",
                "source": "test"
            },
            headers=admin_headers
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["deleted"] == 100
        assert data["message"] == "Logs cleared"
        
        mock_client.clear_logs.assert_called_once_with(
            before=None,
            level="DEBUG",
            source="test"
        )
    
    def test_clear_logs_without_admin(self, client, user_headers, mock_client):
        """Test clear logs without admin privileges."""
        response = client.delete(
            "/logs/",
            headers=user_headers
        )
        
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Admin privileges required" in response.json()["detail"]
    
    def test_get_log_statistics(self, client, mock_client):
        """Test get log statistics."""
        response = client.get("/logs/stats")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 1000
        assert data["by_level"]["INFO"] == 500
        assert data["by_level"]["ERROR"] == 100
        
        mock_client.get_log_statistics.assert_called_once_with(
            start_time=None,
            end_time=None
        )
    
    def test_export_logs_json(self, client, mock_client):
        """Test export logs in JSON format."""
        response = client.post(
            "/logs/export",
            params={
                "format": "json",
                "level": "ERROR"
            }
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["file"] == "logs_export.json"
        assert data["size"] == 1024
        
        mock_client.export_logs.assert_called_once_with(
            format="json",
            level="ERROR",
            source=None,
            start_time=None,
            end_time=None
        )
    
    def test_export_logs_csv(self, client, mock_client):
        """Test export logs in CSV format."""
        response = client.post(
            "/logs/export",
            params={"format": "csv"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        mock_client.export_logs.assert_called_once_with(
            format="csv",
            level=None,
            source=None,
            start_time=None,
            end_time=None
        )


class TestLogPagination:
    """Test pagination in log endpoints."""
    
    def test_logs_pagination_limit(self, client, mock_client):
        """Test logs with limit parameter."""
        response = client.get(
            "/logs/",
            params={"limit": 500}
        )
        
        assert response.status_code == status.HTTP_200_OK
        mock_client.get_logs.assert_called_once_with(
            level=None,
            source=None,
            start_time=None,
            end_time=None,
            limit=500,
            offset=0
        )
    
    def test_logs_pagination_offset(self, client, mock_client):
        """Test logs with offset parameter."""
        response = client.get(
            "/logs/",
            params={"offset": 100}
        )
        
        assert response.status_code == status.HTTP_200_OK
        mock_client.get_logs.assert_called_once_with(
            level=None,
            source=None,
            start_time=None,
            end_time=None,
            limit=100,
            offset=100
        )
    
    def test_logs_pagination_limit_exceeded(self, client, mock_client):
        """Test logs with limit exceeding maximum."""
        response = client.get(
            "/logs/",
            params={"limit": 2000}  # Max is 1000
        )
        
        # FastAPI will validate and reject this
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY