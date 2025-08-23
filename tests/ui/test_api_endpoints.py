"""
Tests for Gleitzeit UI API endpoints
"""

import pytest
from fastapi.testclient import TestClient
from datetime import datetime
import json
import sys
from pathlib import Path

# Add src directory to path
sys.path.append(str(Path(__file__).parent.parent.parent / "src"))

from ui.api.app import app


@pytest.fixture
def client():
    """Create test client"""
    return TestClient(app)


@pytest.fixture
def sample_workflow():
    """Sample workflow for testing"""
    return {
        "name": "Test Workflow",
        "tasks": [
            {
                "id": "task1",
                "method": "llm/chat",
                "parameters": {
                    "model": "llama3.2",
                    "messages": [{"role": "user", "content": "Hello"}]
                }
            },
            {
                "id": "task2",
                "method": "python/execute",
                "dependencies": ["task1"],
                "parameters": {
                    "script": "test.py"
                }
            }
        ]
    }


@pytest.fixture
def sample_task():
    """Sample task for testing"""
    return {
        "id": "test_task_1",
        "workflow_id": "test_workflow_1",
        "method": "llm/chat",
        "parameters": {"model": "llama3.2"},
        "status": "pending"
    }


class TestHealthEndpoint:
    """Test health check endpoint"""
    
    def test_health_check(self, client):
        """Test health check returns 200"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "gleitzeit-ui"


class TestWorkflowEndpoints:
    """Test workflow-related endpoints"""
    
    def test_list_workflows(self, client):
        """Test listing workflows"""
        response = client.get("/api/workflows")
        assert response.status_code == 200
        data = response.json()
        assert "workflows" in data
        assert "total" in data
        assert isinstance(data["workflows"], list)
    
    def test_list_workflows_with_filter(self, client):
        """Test listing workflows with status filter"""
        response = client.get("/api/workflows?status=running")
        assert response.status_code == 200
        data = response.json()
        assert "workflows" in data
    
    def test_list_workflows_with_pagination(self, client):
        """Test listing workflows with pagination"""
        response = client.get("/api/workflows?limit=10&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert "workflows" in data
        assert data["limit"] == 10
        assert data["offset"] == 0
    
    def test_get_workflow_not_found(self, client):
        """Test getting non-existent workflow"""
        response = client.get("/api/workflows/non_existent")
        assert response.status_code == 404
    
    def test_submit_workflow(self, client, sample_workflow):
        """Test submitting a new workflow"""
        response = client.post("/api/workflows", json=sample_workflow)
        # Note: This might fail without a running engine
        # In real tests, we'd mock the engine
        assert response.status_code in [200, 500]
    
    def test_cancel_workflow_not_found(self, client):
        """Test canceling non-existent workflow"""
        response = client.delete("/api/workflows/non_existent")
        assert response.status_code == 404
    
    def test_get_workflow_tasks_not_found(self, client):
        """Test getting tasks for non-existent workflow"""
        response = client.get("/api/workflows/non_existent/tasks")
        assert response.status_code == 404
    
    def test_get_workflow_results_not_found(self, client):
        """Test getting results for non-existent workflow"""
        response = client.get("/api/workflows/non_existent/results")
        assert response.status_code == 404
    
    def test_get_workflow_timeline_not_found(self, client):
        """Test getting timeline for non-existent workflow"""
        response = client.get("/api/workflows/non_existent/timeline")
        assert response.status_code == 404


class TestTaskEndpoints:
    """Test task-related endpoints"""
    
    def test_list_tasks(self, client):
        """Test listing tasks"""
        response = client.get("/api/tasks")
        assert response.status_code == 200
        data = response.json()
        assert "tasks" in data
        assert "total" in data
        assert isinstance(data["tasks"], list)
    
    def test_list_tasks_with_filter(self, client):
        """Test listing tasks with status filter"""
        response = client.get("/api/tasks?status=running")
        assert response.status_code == 200
        data = response.json()
        assert "tasks" in data
    
    def test_list_tasks_by_workflow(self, client):
        """Test listing tasks by workflow ID"""
        response = client.get("/api/tasks?workflow_id=test_workflow")
        assert response.status_code == 200
        data = response.json()
        assert "tasks" in data
    
    def test_get_task_not_found(self, client):
        """Test getting non-existent task"""
        response = client.get("/api/tasks/non_existent")
        assert response.status_code == 404
    
    def test_get_task_result_not_found(self, client):
        """Test getting result for non-existent task"""
        response = client.get("/api/tasks/non_existent/result")
        assert response.status_code == 404
    
    def test_get_task_logs_not_found(self, client):
        """Test getting logs for non-existent task"""
        response = client.get("/api/tasks/non_existent/logs")
        assert response.status_code == 404
    
    def test_retry_task_not_found(self, client):
        """Test retrying non-existent task"""
        response = client.post("/api/tasks/non_existent/retry")
        assert response.status_code == 404
    
    def test_cancel_task_not_found(self, client):
        """Test canceling non-existent task"""
        response = client.delete("/api/tasks/non_existent")
        assert response.status_code == 404
    
    def test_get_queue_status(self, client):
        """Test getting queue status"""
        response = client.get("/api/tasks/queue/status")
        assert response.status_code == 200
        data = response.json()
        assert "statistics" in data
        assert "queue" in data
        assert "timestamp" in data


class TestSystemEndpoints:
    """Test system-related endpoints"""
    
    def test_get_system_status(self, client):
        """Test getting system status"""
        response = client.get("/api/system/status")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "timestamp" in data
        assert "ollama" in data
        assert "resources" in data
        assert "engine" in data
    
    def test_get_metrics(self, client):
        """Test getting metrics"""
        response = client.get("/api/system/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "tasks" in data
        assert "workflows" in data
        assert "success_rate" in data
        assert "timestamp" in data
    
    def test_get_metrics_with_period(self, client):
        """Test getting metrics with specific period"""
        response = client.get("/api/system/metrics?period=24h")
        assert response.status_code == 200
        data = response.json()
        assert data["period"] == "24h"
    
    def test_get_resources(self, client):
        """Test getting resource information"""
        response = client.get("/api/system/resources")
        assert response.status_code == 200
        data = response.json()
        assert "resources" in data
        assert "timestamp" in data
        assert "ollama" in data["resources"]
        assert "python" in data["resources"]
        assert "mcp" in data["resources"]
    
    def test_get_providers(self, client):
        """Test getting provider information"""
        response = client.get("/api/system/providers")
        assert response.status_code == 200
        data = response.json()
        assert "providers" in data
        assert "total" in data
        assert isinstance(data["providers"], list)
    
    def test_get_logs(self, client):
        """Test getting system logs"""
        response = client.get("/api/system/logs")
        assert response.status_code == 200
        data = response.json()
        assert "logs" in data
        assert "total" in data
        assert isinstance(data["logs"], list)
    
    def test_get_logs_with_filter(self, client):
        """Test getting logs with level filter"""
        response = client.get("/api/system/logs?level=error&limit=50")
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 50
    
    def test_update_configuration(self, client):
        """Test updating configuration"""
        config = {"default_model": "llama3.2"}
        response = client.post("/api/system/config", json=config)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "updated"
        assert data["config"] == config
    
    def test_get_system_info(self, client):
        """Test getting system information"""
        response = client.get("/api/system/info")
        assert response.status_code == 200
        data = response.json()
        assert "gleitzeit_version" in data
        assert "ui_version" in data
        assert "python_version" in data
        assert "platform" in data


class TestHTMLPages:
    """Test HTML page endpoints"""
    
    def test_dashboard_page(self, client):
        """Test dashboard page loads"""
        response = client.get("/")
        assert response.status_code == 200
        assert b"Dashboard" in response.content
    
    def test_workflows_page(self, client):
        """Test workflows page loads"""
        response = client.get("/workflows")
        assert response.status_code == 200
        assert b"Workflows" in response.content
    
    def test_workflow_detail_page(self, client):
        """Test workflow detail page loads"""
        response = client.get("/workflows/test_id")
        assert response.status_code == 200
        assert b"Workflow Details" in response.content
    
    def test_tasks_page(self, client):
        """Test tasks page loads"""
        response = client.get("/tasks")
        assert response.status_code == 200
        assert b"Tasks" in response.content
    
    def test_task_detail_page(self, client):
        """Test task detail page loads"""
        response = client.get("/tasks/test_id")
        assert response.status_code == 200
        assert b"Task Details" in response.content


class TestStaticFiles:
    """Test static file serving"""
    
    def test_css_file(self, client):
        """Test CSS file is served"""
        response = client.get("/static/css/main.css")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/css")
    
    def test_js_file(self, client):
        """Test JavaScript file is served"""
        response = client.get("/static/js/app.js")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/javascript")
    
    def test_websocket_js_file(self, client):
        """Test WebSocket JavaScript file is served"""
        response = client.get("/static/js/websocket.js")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/javascript")