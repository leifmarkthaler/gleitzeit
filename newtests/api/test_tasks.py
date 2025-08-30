"""
Tests for task API endpoints.
"""

import pytest
from fastapi import status


class TestTaskEndpoints:
    """Test task API endpoints."""
    
    def test_submit_task(self, client, sample_task, mock_client):
        """Test task submission."""
        response = client.post(
            "/tasks/",
            json={"task": sample_task}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["task_id"] == "task_123"
        assert data["status"] == "submitted"
        
        # Verify client method was called
        mock_client.submit_task.assert_called_once()
        
    def test_get_task(self, client, mock_client):
        """Test get task by ID."""
        response = client.get("/tasks/task_123")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == "task_123"
        assert data["name"] == "test_task"
        
        mock_client.get_task.assert_called_once_with("task_123")
        
    def test_list_tasks_with_filters(self, client, mock_client):
        """Test list tasks with all filters."""
        response = client.get(
            "/tasks/",
            params={
                "workflow_id": "wf_123",
                "status": "running",
                "limit": 50,
                "offset": 10
            }
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "tasks" in data
        assert len(data["tasks"]) == 1
        
        mock_client.list_tasks.assert_called_once_with("wf_123", "running", 50, 10)
        
    def test_list_tasks_default_params(self, client, mock_client):
        """Test list tasks with default parameters."""
        response = client.get("/tasks/")
        
        assert response.status_code == status.HTTP_200_OK
        mock_client.list_tasks.assert_called_once_with(None, None, 100, 0)
        
    def test_list_tasks_partial_filters(self, client, mock_client):
        """Test list tasks with partial filters."""
        response = client.get(
            "/tasks/",
            params={"workflow_id": "wf_123", "limit": 25}
        )
        
        assert response.status_code == status.HTTP_200_OK
        mock_client.list_tasks.assert_called_once_with("wf_123", None, 25, 0)
        
    def test_cancel_task(self, client, mock_client):
        """Test cancel task."""
        response = client.post("/tasks/task_123/cancel")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["task_id"] == "task_123"
        assert data["status"] == "cancelled"
        
        mock_client.cancel_task.assert_called_once_with("task_123")
        
    def test_pause_task(self, client, mock_client):
        """Test pause task."""
        response = client.post("/tasks/task_123/pause")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "paused"
        
        mock_client.pause_task.assert_called_once_with("task_123")
        
    def test_resume_task(self, client, mock_client):
        """Test resume task."""
        response = client.post("/tasks/task_123/resume")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "running"
        
        mock_client.resume_task.assert_called_once_with("task_123")
        
    def test_update_task(self, client, mock_client):
        """Test update task properties."""
        updates = {"priority": "high", "timeout": 300}
        response = client.put(
            "/tasks/task_123",
            json={"updates": updates}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["updated"] is True
        
        mock_client.update_task.assert_called_once_with("task_123", updates)
        
    def test_wait_for_task(self, client, mock_client):
        """Test wait for task completion."""
        response = client.post(
            "/tasks/task_123/wait",
            params={"timeout": 120.0, "poll_interval": 1.0}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "completed"
        
        mock_client.wait_for_task.assert_called_once_with("task_123", 120.0, 1.0)
        
    def test_wait_for_task_default_params(self, client, mock_client):
        """Test wait for task with default parameters."""
        response = client.post("/tasks/task_123/wait")
        
        assert response.status_code == status.HTTP_200_OK
        mock_client.wait_for_task.assert_called_once_with("task_123", 300.0, 2.0)


class TestTaskErrorHandling:
    """Test error handling in task endpoints."""
    
    def test_submit_task_client_error(self, client, sample_task, mock_client):
        """Test task submission with client error."""
        mock_client.submit_task.side_effect = RuntimeError("Database connection failed")
        
        response = client.post(
            "/tasks/",
            json={"task": sample_task}
        )
        
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Database connection failed" in response.json()["detail"]
        
    def test_get_task_not_found(self, client, mock_client):
        """Test get task when not found."""
        mock_client.get_task.return_value = None
        
        response = client.get("/tasks/nonexistent")
        
        assert response.status_code == status.HTTP_200_OK
        assert response.json() is None
        
        mock_client.get_task.assert_called_once_with("nonexistent")
        
    def test_update_task_validation_error(self, client, mock_client):
        """Test update task with validation error."""
        mock_client.update_task.side_effect = ValueError("Invalid update data")
        
        response = client.put(
            "/tasks/task_123",
            json={"updates": {"invalid_field": "value"}}
        )
        
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        
    def test_cancel_task_not_found(self, client, mock_client):
        """Test cancel task when task doesn't exist."""
        mock_client.cancel_task.side_effect = ValueError("Task not found")
        
        response = client.post("/tasks/nonexistent/cancel")
        
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR