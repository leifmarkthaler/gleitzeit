"""Integration tests for the workflows page UI with real API"""
import pytest
import asyncio
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


class TestWorkflowsPageIntegration:
    """Integration tests for workflows page functionality"""
    
    def test_workflows_page_loads(self, client):
        """Test that workflows page loads successfully"""
        response = client.get("/workflows")
        assert response.status_code == 200
        assert "Workflows" in response.text
        assert "New Workflow" in response.text
        assert "submit-workflow-modal" in response.text
    
    def test_workflows_api_endpoint(self, client):
        """Test workflows API endpoint returns data"""
        response = client.get("/api/workflows")
        assert response.status_code == 200
        data = response.json()
        
        # Should have workflows array and total
        assert "workflows" in data
        assert "total" in data
        assert isinstance(data["workflows"], list)
        assert isinstance(data["total"], int)
    
    def test_workflows_filtering(self, client):
        """Test workflows filtering by status"""
        # Test each status filter
        for status in ["pending", "running", "completed", "failed", "cancelled"]:
            response = client.get(f"/api/workflows?status={status}")
            assert response.status_code == 200
            data = response.json()
            
            # Verify structure
            assert "workflows" in data
            assert isinstance(data["workflows"], list)
            
            # All returned workflows should match the filter (if any exist)
            for wf in data["workflows"]:
                assert wf.get("status") == status
    
    def test_workflows_limit(self, client):
        """Test workflows limit parameter"""
        response = client.get("/api/workflows?limit=5")
        assert response.status_code == 200
        data = response.json()
        
        # Should not return more than limit
        assert len(data["workflows"]) <= 5
    
    def test_workflow_submission_modal_elements(self, client):
        """Test workflow submission modal has all required elements"""
        response = client.get("/workflows")
        assert response.status_code == 200
        
        # Check modal elements
        assert "submit-workflow-modal" in response.text
        assert "template-select" in response.text
        assert "workflow-name" in response.text
        assert "workflow-json" in response.text
        
        # Check templates
        assert "Simple Python Task" in response.text
        assert "Parallel Tasks" in response.text
        assert "LLM Chat" in response.text
    
    def test_workflow_javascript_functions(self, client):
        """Test that required JavaScript functions are present"""
        response = client.get("/workflows")
        assert response.status_code == 200
        
        # Check required functions
        assert "function getStatusIcon" in response.text
        assert "function calculateProgress" in response.text
        assert "function formatTime" in response.text
        assert "function refreshWorkflows" in response.text
        assert "function showSubmitWorkflowModal" in response.text
        assert "function closeSubmitWorkflowModal" in response.text
        assert "function loadTemplate" in response.text
        assert "function submitWorkflow" in response.text
    
    def test_workflow_htmx_attributes(self, client):
        """Test HTMX attributes for dynamic updates"""
        response = client.get("/workflows")
        assert response.status_code == 200
        
        # Check HTMX attributes
        assert 'hx-get="/api/workflows"' in response.text
        assert 'hx-trigger="load' in response.text
        assert 'hx-target=' in response.text
        assert 'hx-swap=' in response.text
    
    def test_workflow_status_icons_mapping(self, client):
        """Test status icon mapping in JavaScript"""
        response = client.get("/workflows")
        assert response.status_code == 200
        
        # Check icon mappings
        assert "case 'completed': return '✓'" in response.text
        assert "case 'running': return '▶'" in response.text
        assert "case 'failed': return '✗'" in response.text
        assert "case 'pending': return '○'" in response.text
        assert "case 'cancelled': return '⊘'" in response.text
    
    def test_workflow_table_structure(self, client):
        """Test workflow table has correct structure"""
        response = client.get("/workflows")
        assert response.status_code == 200
        
        # Check table headers in JavaScript
        assert "Status" in response.text
        assert "Workflow ID" in response.text
        assert "Name" in response.text
        assert "Tasks" in response.text
        assert "Progress" in response.text
        assert "Created" in response.text
        assert "Actions" in response.text
    
    def test_workflow_stats_overview_section(self, client):
        """Test workflow statistics overview section"""
        response = client.get("/workflows")
        assert response.status_code == 200
        
        # Check stats section elements
        assert "workflows-overview" in response.text
        assert "Workflow Statistics" in response.text
        assert "Total Workflows" in response.text
        assert "Pending" in response.text
        assert "Running" in response.text
        assert "Completed" in response.text
        assert "Failed" in response.text
        assert "Cancelled" in response.text
    
    def test_workflow_action_buttons_html(self, client):
        """Test workflow action button HTML generation"""
        response = client.get("/workflows")
        assert response.status_code == 200
        
        # Check action button templates in JavaScript
        assert "btn btn-primary\">View</a>" in response.text
        assert 'hx-post="/api/workflows/${workflowId}/cancel"' in response.text
        assert 'hx-post="/api/workflows/${workflowId}/retry"' in response.text
        assert 'hx-delete="/api/workflows/${workflowId}"' in response.text
    
    def test_workflow_empty_state(self, client):
        """Test empty state HTML"""
        response = client.get("/workflows")
        assert response.status_code == 200
        
        # Check empty state template
        assert "No Workflows Found" in response.text
        assert "Submit a workflow to get started!" in response.text
    
    def test_workflow_template_definitions(self, client):
        """Test workflow template definitions"""
        response = client.get("/workflows")
        assert response.status_code == 200
        
        # Check template definitions
        assert '"Simple Python Task"' in response.text
        assert '"python/execute"' in response.text
        assert '"Parallel Tasks Example"' in response.text
        assert '"dependencies"' in response.text
        assert '"LLM Chat Example"' in response.text
        assert '"llm/chat"' in response.text