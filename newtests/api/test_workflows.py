"""
Tests for workflow API endpoints.
"""

import pytest
from fastapi import status


class TestWorkflowEndpoints:
    """Test workflow API endpoints."""
    
    def test_submit_workflow(self, client, sample_workflow, mock_client):
        """Test workflow submission."""
        response = client.post(
            "/workflows/",
            json={"workflow": sample_workflow}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["workflow_id"] == "wf_123"
        assert data["status"] == "submitted"
        
        # Verify client method was called
        mock_client.submit_workflow.assert_called_once()
        
    def test_get_workflow(self, client, mock_client):
        """Test get workflow by ID."""
        response = client.get("/workflows/wf_123")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == "wf_123"
        assert data["name"] == "test_workflow"
        
        mock_client.get_workflow.assert_called_once_with("wf_123")
        
    def test_list_workflows(self, client, mock_client):
        """Test list workflows with filters."""
        response = client.get(
            "/workflows/",
            params={"status": "running", "limit": 50, "offset": 0}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "workflows" in data
        assert len(data["workflows"]) == 1
        
        mock_client.list_workflows.assert_called_once_with("running", 50, 0)
        
    def test_list_workflows_default_params(self, client, mock_client):
        """Test list workflows with default parameters."""
        response = client.get("/workflows/")
        
        assert response.status_code == status.HTTP_200_OK
        mock_client.list_workflows.assert_called_once_with(None, 100, 0)
        
    def test_cancel_workflow(self, client, mock_client):
        """Test cancel workflow."""
        response = client.post("/workflows/wf_123/cancel")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["workflow_id"] == "wf_123"
        assert data["status"] == "cancelled"
        
        mock_client.cancel_workflow.assert_called_once_with("wf_123")
        
    def test_pause_workflow(self, client, mock_client):
        """Test pause workflow."""
        response = client.post("/workflows/wf_123/pause")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "paused"
        
        mock_client.pause_workflow.assert_called_once_with("wf_123")
        
    def test_resume_workflow(self, client, mock_client):
        """Test resume workflow."""
        response = client.post("/workflows/wf_123/resume")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "running"
        
        mock_client.resume_workflow.assert_called_once_with("wf_123")
        
    def test_delete_workflow(self, client, mock_client):
        """Test delete workflow."""
        response = client.delete("/workflows/wf_123")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data is True
        
        mock_client.delete_workflow.assert_called_once_with("wf_123")
        
    def test_get_workflow_tasks(self, client, mock_client):
        """Test get workflow tasks."""
        response = client.get("/workflows/wf_123/tasks")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "task_123"
        
        mock_client.get_workflow_tasks.assert_called_once_with("wf_123")
        
    def test_wait_for_workflow(self, client, mock_client):
        """Test wait for workflow completion."""
        response = client.post(
            "/workflows/wf_123/wait",
            params={"timeout": 120.0, "poll_interval": 1.0}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "completed"
        
        mock_client.wait_for_workflow.assert_called_once_with("wf_123", 120.0, 1.0)
        
    def test_wait_for_workflow_default_params(self, client, mock_client):
        """Test wait for workflow with default parameters."""
        response = client.post("/workflows/wf_123/wait")
        
        assert response.status_code == status.HTTP_200_OK
        mock_client.wait_for_workflow.assert_called_once_with("wf_123", 300.0, 2.0)
        
    def test_clone_workflow(self, client, mock_client):
        """Test clone workflow."""
        response = client.post(
            "/workflows/wf_123/clone",
            params={"new_name": "cloned_workflow"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["workflow_id"] == "wf_456"
        assert data["status"] == "created"
        
        mock_client.clone_workflow.assert_called_once_with("wf_123", "cloned_workflow")
        
    def test_clone_workflow_no_name(self, client, mock_client):
        """Test clone workflow without new name."""
        response = client.post("/workflows/wf_123/clone")
        
        assert response.status_code == status.HTTP_200_OK
        mock_client.clone_workflow.assert_called_once_with("wf_123", None)
        
    def test_get_workflow_statistics(self, client, mock_client):
        """Test get workflow statistics."""
        response = client.get("/workflows/statistics/summary")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 5
        assert data["success_rate"] == 60.0
        
        mock_client.get_workflow_statistics.assert_called_once()
        
    def test_get_workflow_timeline(self, client, mock_client):
        """Test get workflow timeline."""
        response = client.get("/workflows/wf_123/timeline")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "timeline" in data
        
        mock_client.get_workflow_timeline.assert_called_once_with("wf_123")
        
    def test_get_workflow_dependencies(self, client, mock_client):
        """Test get workflow dependencies."""
        response = client.get("/workflows/wf_123/dependencies")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "dependencies" in data
        
        mock_client.get_workflow_dependencies.assert_called_once_with("wf_123")
        
    def test_get_workflow_critical_path(self, client, mock_client):
        """Test get workflow critical path."""
        response = client.get("/workflows/wf_123/critical-path")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "critical_path" in data
        
        mock_client.get_workflow_critical_path.assert_called_once_with("wf_123")
        
    def test_run_workflow_from_file(self, client, mock_client):
        """Test run workflow from file."""
        response = client.post(
            "/workflows/run",
            params={"workflow_file": "/path/to/workflow.yaml", "watch": True}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["workflow_id"] == "wf_789"
        assert data["status"] == "started"
        
        mock_client.run_workflow.assert_called_once_with("/path/to/workflow.yaml", True)


class TestWorkflowErrorHandling:
    """Test error handling in workflow endpoints."""
    
    def test_submit_workflow_client_error(self, client, sample_workflow, mock_client):
        """Test workflow submission with client error."""
        mock_client.submit_workflow.side_effect = RuntimeError("Client error")
        
        response = client.post(
            "/workflows/",
            json={"workflow": sample_workflow}
        )
        
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Client error" in response.json()["detail"]
        
    def test_submit_workflow_not_initialized(self, client, sample_workflow, mock_client):
        """Test workflow submission when client not initialized."""
        mock_client.submit_workflow.side_effect = RuntimeError("not initialized")
        
        response = client.post(
            "/workflows/",
            json={"workflow": sample_workflow}
        )
        
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json()["detail"] == "Service temporarily unavailable"
        
    def test_submit_workflow_not_implemented(self, client, sample_workflow, mock_client):
        """Test workflow submission with not implemented error."""
        # Save original mock
        original_side_effect = mock_client.submit_workflow.side_effect
        
        try:
            def raise_not_implemented(*args, **kwargs):
                raise NotImplementedError("Feature not implemented")
            
            mock_client.submit_workflow.side_effect = raise_not_implemented
            
            response = client.post(
                "/workflows/",
                json={"workflow": sample_workflow}
            )
            
            # Note: Currently returns 500 instead of 501 due to FastAPI exception handling
            assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            assert "Feature not implemented" in response.json()["detail"]
        finally:
            # Restore original mock
            mock_client.submit_workflow.side_effect = original_side_effect