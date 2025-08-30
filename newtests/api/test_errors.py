"""
Tests for error management API endpoints.
"""

import pytest
from fastapi import status
from datetime import datetime


class TestErrorEndpoints:
    """Test error management API endpoints."""
    
    def test_get_event_errors(self, client, mock_client):
        """Test get event errors with filters."""
        response = client.get(
            "/errors/",
            params={
                "status": "new",
                "severity": "high",
                "limit": 50,
                "offset": 0
            }
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "err_1"
        assert data[0]["severity"] == "high"
        assert data[0]["message"] == "Test error"
        
        mock_client.get_event_errors.assert_called_once_with(
            status="new",
            severity="high",
            start_time=None,
            end_time=None,
            limit=50,
            offset=0
        )
    
    def test_get_event_errors_default_params(self, client, mock_client):
        """Test get event errors with default parameters."""
        response = client.get("/errors/")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        
        mock_client.get_event_errors.assert_called_once_with(
            status=None,
            severity=None,
            start_time=None,
            end_time=None,
            limit=100,
            offset=0
        )
    
    def test_get_event_error_by_id(self, client, mock_client):
        """Test get specific event error."""
        response = client.get("/errors/err_1")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == "err_1"
        assert data["severity"] == "high"
        assert data["message"] == "Test error"
        assert data["status"] == "new"
        
        mock_client.get_event_error.assert_called_once_with("err_1")
    
    def test_update_event_error(self, client, mock_client):
        """Test update event error."""
        response = client.put(
            "/errors/err_1",
            json={
                "status": "acknowledged",
                "resolution": "Working on fix",
                "notes": "Identified root cause"
            }
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == "err_1"
        assert data["status"] == "acknowledged"
        
        mock_client.update_event_error.assert_called_once_with(
            "err_1",
            status="acknowledged",
            resolution="Working on fix",
            notes="Identified root cause"
        )
    
    def test_update_event_error_partial(self, client, mock_client):
        """Test partial update of event error."""
        response = client.put(
            "/errors/err_1",
            json={"status": "acknowledged"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        mock_client.update_event_error.assert_called_once_with(
            "err_1",
            status="acknowledged",
            resolution=None,
            notes=None
        )
    
    def test_acknowledge_error(self, client, mock_client):
        """Test acknowledge event error."""
        response = client.post("/errors/err_1/acknowledge")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == "err_1"
        assert data["status"] == "acknowledged"
        
        mock_client.acknowledge_error.assert_called_once_with("err_1")
    
    def test_resolve_error(self, client, mock_client):
        """Test resolve event error."""
        response = client.post(
            "/errors/err_1/resolve",
            params={"resolution": "Fixed the bug in task handler"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == "err_1"
        assert data["status"] == "resolved"
        
        mock_client.resolve_error.assert_called_once_with(
            "err_1", 
            "Fixed the bug in task handler"
        )
    
    def test_ignore_error(self, client, mock_client):
        """Test ignore event error."""
        response = client.post("/errors/err_1/ignore")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == "err_1"
        assert data["status"] == "ignored"
        
        mock_client.ignore_error.assert_called_once_with("err_1")
    
    def test_retry_failed_event(self, client, mock_client):
        """Test retry failed event."""
        response = client.post("/errors/err_1/retry")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == "err_1"
        assert data["retry_status"] == "submitted"
        
        mock_client.retry_failed_event.assert_called_once_with("err_1")
    
    def test_get_task_errors(self, client, mock_client):
        """Test get errors for specific task."""
        response = client.get(
            "/errors/task/task_123",
            params={"severity": "medium", "limit": 25}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["task_id"] == "task_123"
        assert data[0]["message"] == "Task error"
        
        mock_client.get_task_errors.assert_called_once_with(
            task_id="task_123",
            severity="medium",
            limit=25,
            offset=0
        )
    
    def test_get_workflow_errors(self, client, mock_client):
        """Test get errors for specific workflow."""
        response = client.get(
            "/errors/workflow/wf_123",
            params={"limit": 10, "offset": 5}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["workflow_id"] == "wf_123"
        assert data[0]["message"] == "Workflow error"
        
        mock_client.get_workflow_errors.assert_called_once_with(
            workflow_id="wf_123",
            severity=None,
            limit=10,
            offset=5
        )
    
    def test_get_error_statistics(self, client, mock_client):
        """Test get error statistics."""
        response = client.get("/errors/stats")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 50
        assert data["by_severity"]["high"] == 10
        assert data["by_severity"]["medium"] == 20
        
        mock_client.get_error_statistics.assert_called_once_with(
            start_time=None,
            end_time=None
        )
    
    def test_clear_errors(self, client, admin_headers, mock_client):
        """Test clear errors (admin only)."""
        response = client.delete(
            "/errors/",
            params={
                "status": "resolved",
                "severity": "low"
            },
            headers=admin_headers
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["deleted"] == 25
        assert data["message"] == "Errors cleared"
        
        mock_client.clear_errors.assert_called_once_with(
            before=None,
            status="resolved",
            severity="low"
        )
    
    def test_clear_errors_without_admin(self, client, user_headers, mock_client):
        """Test clear errors without admin privileges."""
        response = client.delete(
            "/errors/",
            headers=user_headers
        )
        
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Admin privileges required" in response.json()["detail"]


class TestErrorFiltering:
    """Test filtering in error endpoints."""
    
    def test_filter_errors_by_status(self, client, mock_client):
        """Test filter errors by status."""
        response = client.get(
            "/errors/",
            params={"status": "acknowledged"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        mock_client.get_event_errors.assert_called_once_with(
            status="acknowledged",
            severity=None,
            start_time=None,
            end_time=None,
            limit=100,
            offset=0
        )
    
    def test_filter_errors_by_severity(self, client, mock_client):
        """Test filter errors by severity."""
        response = client.get(
            "/errors/",
            params={"severity": "critical"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        mock_client.get_event_errors.assert_called_once_with(
            status=None,
            severity="critical",
            start_time=None,
            end_time=None,
            limit=100,
            offset=0
        )
    
    def test_filter_errors_by_time_range(self, client, mock_client):
        """Test filter errors by time range."""
        start_time = "2023-01-01T00:00:00"
        end_time = "2023-01-02T00:00:00"
        
        response = client.get(
            "/errors/",
            params={
                "start_time": start_time,
                "end_time": end_time
            }
        )
        
        assert response.status_code == status.HTTP_200_OK
        mock_client.get_event_errors.assert_called_once()


class TestErrorPagination:
    """Test pagination in error endpoints."""
    
    def test_errors_pagination_limit(self, client, mock_client):
        """Test errors with limit parameter."""
        response = client.get(
            "/errors/",
            params={"limit": 500}
        )
        
        assert response.status_code == status.HTTP_200_OK
        mock_client.get_event_errors.assert_called_once_with(
            status=None,
            severity=None,
            start_time=None,
            end_time=None,
            limit=500,
            offset=0
        )
    
    def test_errors_pagination_offset(self, client, mock_client):
        """Test errors with offset parameter."""
        response = client.get(
            "/errors/",
            params={"offset": 100}
        )
        
        assert response.status_code == status.HTTP_200_OK
        mock_client.get_event_errors.assert_called_once_with(
            status=None,
            severity=None,
            start_time=None,
            end_time=None,
            limit=100,
            offset=100
        )