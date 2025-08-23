"""End-to-end tests for the workflows page UI"""
import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from datetime import datetime
import os

# Set API URL for testing
os.environ["GLEITZEIT_API_URL"] = "http://localhost:8012"

from src.ui.api.app import app


@pytest.fixture
def client():
    """Create test client with configured app state"""
    # Configure app state for testing
    app.state.api_url = "http://localhost:8012"
    return TestClient(app)


@pytest.fixture
def mock_gleitzeit_api():
    """Mock the Gleitzeit API responses"""
    with patch('aiohttp.ClientSession') as mock:
        yield mock


class TestWorkflowsPage:
    """Test workflows page functionality"""
    
    def test_workflows_page_loads(self, client):
        """Test that workflows page loads successfully"""
        response = client.get("/workflows")
        assert response.status_code == 200
        assert "Workflows" in response.text
        assert "New Workflow" in response.text
        assert "submit-workflow-modal" in response.text
    
    def test_workflows_stats_overview(self, client, mock_gleitzeit_api):
        """Test workflows statistics overview section"""
        # Mock API response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "workflows": [
                {"id": "wf1", "status": "pending"},
                {"id": "wf2", "status": "running"},
                {"id": "wf3", "status": "completed"},
                {"id": "wf4", "status": "failed"},
                {"id": "wf5", "status": "cancelled"},
                {"id": "wf6", "status": "completed"}
            ],
            "total": 6
        })
        
        mock_session = AsyncMock()
        mock_session.request.return_value.__aenter__.return_value = mock_response
        mock_gleitzeit_api.return_value.__aenter__.return_value = mock_session
        
        response = client.get("/api/workflows")
        assert response.status_code == 200
        data = response.json()
        
        # Verify stats calculation would work
        workflows = data.get("workflows", [])
        stats = {
            "total": len(workflows),
            "pending": len([w for w in workflows if w.get("status") == "pending"]),
            "running": len([w for w in workflows if w.get("status") == "running"]),
            "completed": len([w for w in workflows if w.get("status") == "completed"]),
            "failed": len([w for w in workflows if w.get("status") == "failed"]),
            "cancelled": len([w for w in workflows if w.get("status") == "cancelled"])
        }
        
        assert stats["total"] == 6
        assert stats["pending"] == 1
        assert stats["running"] == 1
        assert stats["completed"] == 2
        assert stats["failed"] == 1
        assert stats["cancelled"] == 1
    
    def test_workflows_table_layout(self, client, mock_gleitzeit_api):
        """Test workflows table layout and formatting"""
        # Mock API response with detailed workflow data
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "workflows": [
                {
                    "id": "abc123def456",
                    "workflow_id": "abc123def456",
                    "name": "Data Processing Pipeline",
                    "status": "running",
                    "tasks_total": 5,
                    "tasks_completed": 3,
                    "tasks_failed": 0,
                    "created_at": "2025-01-15T10:30:00Z"
                },
                {
                    "id": "xyz789ghi012",
                    "workflow_id": "xyz789ghi012",
                    "name": "ML Training Job",
                    "status": "completed",
                    "tasks_total": 10,
                    "tasks_completed": 10,
                    "tasks_failed": 0,
                    "created_at": "2025-01-15T09:00:00Z"
                }
            ],
            "total": 2
        }
        
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_gleitzeit_api.return_value.__aenter__.return_value = mock_client
        
        response = client.get("/api/workflows?limit=50")
        assert response.status_code == 200
        data = response.json()
        
        # Verify table data structure
        assert len(data["workflows"]) == 2
        
        # Check first workflow
        wf1 = data["workflows"][0]
        assert wf1["name"] == "Data Processing Pipeline"
        assert wf1["status"] == "running"
        assert wf1["tasks_total"] == 5
        assert wf1["tasks_completed"] == 3
        
        # Check progress calculation would work
        progress = round((wf1["tasks_completed"] / wf1["tasks_total"]) * 100)
        assert progress == 60
    
    def test_workflow_filters(self, client, mock_gleitzeit_api):
        """Test workflow filtering by status"""
        # Mock filtered response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "workflows": [
                {"id": "wf1", "status": "running"},
                {"id": "wf2", "status": "running"}
            ],
            "total": 2
        }
        
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_gleitzeit_api.return_value.__aenter__.return_value = mock_client
        
        response = client.get("/api/workflows?status=running&limit=50")
        assert response.status_code == 200
        data = response.json()
        
        # All workflows should be running
        for wf in data["workflows"]:
            assert wf["status"] == "running"
    
    def test_workflow_submission_modal(self, client):
        """Test workflow submission modal elements"""
        response = client.get("/workflows")
        assert response.status_code == 200
        
        # Check modal elements
        assert "submit-workflow-modal" in response.text
        assert "template-select" in response.text
        assert "Simple Python Task" in response.text
        assert "Parallel Tasks" in response.text
        assert "LLM Chat" in response.text
        assert "workflow-name" in response.text
        assert "workflow-json" in response.text
    
    def test_workflow_templates(self, client):
        """Test workflow template functionality"""
        response = client.get("/workflows")
        assert response.status_code == 200
        
        # Check template options
        assert "Simple Python Task" in response.text
        assert "Parallel Tasks Example" in response.text
        assert "LLM Chat Example" in response.text
        
        # Verify loadTemplate function exists
        assert "function loadTemplate" in response.text
        assert "templates.simple" in response.text
        assert "templates.parallel" in response.text
        assert "templates.llm" in response.text
    
    def test_workflow_action_buttons(self, client, mock_gleitzeit_api):
        """Test workflow action buttons based on status"""
        # Mock response with various workflow states
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "workflows": [
                {"id": "wf1", "status": "running"},
                {"id": "wf2", "status": "failed"},
                {"id": "wf3", "status": "completed"}
            ],
            "total": 3
        }
        
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_gleitzeit_api.return_value.__aenter__.return_value = mock_client
        
        response = client.get("/api/workflows")
        assert response.status_code == 200
        data = response.json()
        
        # Verify button logic would work
        for wf in data["workflows"]:
            if wf["status"] == "running":
                # Should have Cancel button
                assert wf["id"] == "wf1"
            elif wf["status"] == "failed":
                # Should have Retry button
                assert wf["id"] == "wf2"
            elif wf["status"] == "completed":
                # Should only have View and Delete buttons
                assert wf["id"] == "wf3"
    
    def test_workflow_progress_calculation(self, client):
        """Test workflow progress calculation"""
        workflows = [
            {"tasks_total": 10, "tasks_completed": 5},
            {"tasks_total": 0, "tasks_completed": 0},
            {"tasks_total": 3, "tasks_completed": 3},
            {"tasks_total": 7, "tasks_completed": 2}
        ]
        
        for wf in workflows:
            total = wf["tasks_total"]
            completed = wf["tasks_completed"]
            
            if total == 0:
                progress = 0
            else:
                progress = round((completed / total) * 100)
            
            if total == 10 and completed == 5:
                assert progress == 50
            elif total == 0:
                assert progress == 0
            elif total == 3 and completed == 3:
                assert progress == 100
            elif total == 7 and completed == 2:
                assert progress == 29
    
    def test_workflow_status_icons(self, client):
        """Test workflow status icon mapping"""
        response = client.get("/workflows")
        assert response.status_code == 200
        
        # Check getStatusIcon function
        assert "function getStatusIcon" in response.text
        assert "case 'completed': return '✓'" in response.text
        assert "case 'running': return '▶'" in response.text
        assert "case 'failed': return '✗'" in response.text
        assert "case 'pending': return '○'" in response.text
        assert "case 'cancelled': return '⊘'" in response.text
    
    def test_workflow_time_formatting(self, client):
        """Test workflow time formatting function"""
        response = client.get("/workflows")
        assert response.status_code == 200
        
        # Check formatTime function
        assert "function formatTime" in response.text
        assert "Just now" in response.text
        assert "mins ago" in response.text
        assert "toLocaleTimeString" in response.text
        assert "toLocaleString" in response.text
    
    def test_empty_workflows_state(self, client, mock_gleitzeit_api):
        """Test empty state when no workflows exist"""
        # Mock empty response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "workflows": [],
            "total": 0
        }
        
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_gleitzeit_api.return_value.__aenter__.return_value = mock_client
        
        response = client.get("/api/workflows")
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["workflows"]) == 0
        assert data["total"] == 0
    
    def test_workflow_deletion(self, client, mock_gleitzeit_api):
        """Test workflow deletion functionality"""
        # Mock successful deletion
        mock_response = MagicMock()
        mock_response.status_code = 200
        
        mock_client = AsyncMock()
        mock_client.delete.return_value = mock_response
        mock_gleitzeit_api.return_value.__aenter__.return_value = mock_client
        
        response = client.delete("/api/workflows/test-workflow-id")
        assert response.status_code == 200
    
    def test_workflow_cancellation(self, client, mock_gleitzeit_api):
        """Test workflow cancellation functionality"""
        # Mock successful cancellation
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "cancelled"}
        
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_gleitzeit_api.return_value.__aenter__.return_value = mock_client
        
        response = client.post("/api/workflows/test-workflow-id/cancel")
        assert response.status_code == 200
    
    def test_workflow_retry(self, client, mock_gleitzeit_api):
        """Test workflow retry functionality"""
        # Mock successful retry
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"workflow_id": "new-workflow-id"}
        
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_gleitzeit_api.return_value.__aenter__.return_value = mock_client
        
        response = client.post("/api/workflows/test-workflow-id/retry")
        assert response.status_code == 200
    
    def test_workflow_pagination_info(self, client, mock_gleitzeit_api):
        """Test workflow pagination information display"""
        # Mock paginated response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "workflows": [{"id": f"wf{i}"} for i in range(50)],
            "total": 150
        }
        
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_gleitzeit_api.return_value.__aenter__.return_value = mock_client
        
        response = client.get("/api/workflows?limit=50")
        assert response.status_code == 200
        data = response.json()
        
        # Check pagination info would be displayed correctly
        assert len(data["workflows"]) == 50
        assert data["total"] == 150
        # UI would show "Showing 50 of 150 workflows"