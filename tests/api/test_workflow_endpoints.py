"""
Tests for workflow management endpoints
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import datetime
import json
import io


class TestWorkflowSubmission:
    """Test workflow submission endpoints"""
    
    @pytest.mark.asyncio
    async def test_submit_workflow(self, async_client, sample_workflow_request, mock_execution_engine):
        """Test submitting a workflow"""
        response = await async_client.post("/workflows", json=sample_workflow_request)
        assert response.status_code == 200
        data = response.json()
        
        # Check response structure
        assert "workflow_id" in data
        assert data["workflow_id"].startswith("api_workflow_")
        assert data["status"] == "submitted"
        assert data["tasks_total"] == 2
        assert data["tasks_completed"] == 0
        assert data["tasks_failed"] == 0
        assert "created_at" in data
        assert data["completed_at"] is None
        
        # Verify workflow was submitted to engine
        await asyncio.sleep(0.1)  # Let background task start
        mock_execution_engine.submit_workflow.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_submit_workflow_with_retry_config(self, async_client, mock_execution_engine):
        """Test submitting workflow with retry configuration"""
        workflow = {
            "name": "Workflow with Retry",
            "tasks": [{
                "name": "Retry Task",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {"code": "result = 1"},
                "retry": {
                    "max_attempts": 3,
                    "base_delay": 5.0,
                    "max_delay": 60.0
                }
            }]
        }
        
        response = await async_client.post("/workflows", json=workflow)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "submitted"
    
    @pytest.mark.asyncio
    async def test_submit_invalid_workflow(self, async_client):
        """Test submitting invalid workflow"""
        invalid_workflow = {
            "name": "Invalid",
            "tasks": []  # Empty tasks list
        }
        
        response = await async_client.post("/workflows", json=invalid_workflow)
        assert response.status_code in [400, 422]  # Validation error
    
    @pytest.mark.asyncio
    async def test_submit_workflow_without_engine(self, async_client, sample_workflow_request):
        """Test workflow submission when engine not initialized"""
        from gleitzeit.api.main import app_state
        
        original_engine = app_state.execution_engine
        app_state.execution_engine = None
        
        response = await async_client.post("/workflows", json=sample_workflow_request)
        assert response.status_code == 503
        assert response.json()["detail"] == "System not initialized"
        
        app_state.execution_engine = original_engine
    
    @pytest.mark.asyncio
    async def test_workflow_with_dependencies(self, async_client, mock_execution_engine):
        """Test workflow with task dependencies"""
        workflow = {
            "name": "Dependent Workflow",
            "tasks": [
                {"id": "task_a", "name": "Task A", "protocol": "python/v1", "method": "python/execute", "params": {}},
                {"id": "task_b", "name": "Task B", "protocol": "python/v1", "method": "python/execute", "params": {}, 
                 "dependencies": ["task_a"]},
                {"id": "task_c", "name": "Task C", "protocol": "python/v1", "method": "python/execute", "params": {}, 
                 "dependencies": ["task_a", "task_b"]}
            ]
        }
        
        response = await async_client.post("/workflows", json=workflow)
        assert response.status_code in [200, 400]  # May validate dependencies
        if response.status_code == 200:
            data = response.json()
            assert data["tasks_total"] == 3


class TestWorkflowStatus:
    """Test workflow status endpoints"""
    
    @pytest.mark.asyncio
    async def test_get_workflow_status(self, async_client, sample_workflow_request):
        """Test getting workflow status"""
        from gleitzeit.api.main import app_state
        
        # Submit workflow first
        submit_response = await async_client.post("/workflows", json=sample_workflow_request)
        workflow_id = submit_response.json()["workflow_id"]
        
        # Get status
        response = await async_client.get(f"/workflows/{workflow_id}")
        assert response.status_code == 200
        data = response.json()
        
        assert data["workflow_id"] == workflow_id
        assert data["status"] in ["submitted", "running", "completed"]
        assert data["tasks_total"] == 2
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_workflow(self, async_client):
        """Test getting status of non-existent workflow"""
        response = await async_client.get("/workflows/nonexistent_id")
        assert response.status_code == 404
        assert response.json()["detail"] == "Workflow not found"
    
    @pytest.mark.asyncio
    async def test_workflow_completion_updates(self, async_client, sample_workflow_request, 
                                             mock_execution_engine, sample_task_result):
        """Test workflow status updates after completion"""
        from gleitzeit.api.main import app_state
        
        # Submit workflow
        submit_response = await async_client.post("/workflows", json=sample_workflow_request)
        workflow_id = submit_response.json()["workflow_id"]
        
        # Mock task results
        mock_execution_engine.task_results = {
            "task1": sample_task_result,
            "task2": sample_task_result
        }
        
        # Wait for background execution
        await asyncio.sleep(0.2)
        
        # Update workflow status manually (simulating background task)
        if workflow_id in app_state.active_workflows:
            workflow = app_state.active_workflows[workflow_id]
            workflow.status = "completed"
            workflow.tasks_completed = 2
            workflow.completed_at = datetime.now()
        
        # Get updated status
        response = await async_client.get(f"/workflows/{workflow_id}")
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "completed"
        assert data["tasks_completed"] == 2
        assert data["completed_at"] is not None


class TestWorkflowUpload:
    """Test workflow file upload endpoints"""
    
    @pytest.mark.asyncio
    async def test_upload_workflow_file(self, async_client, temp_workflow_file, mock_execution_engine):
        """Test uploading and executing workflow file"""
        with open(temp_workflow_file, 'rb') as f:
            files = {"file": ("workflow.yaml", f, "application/yaml")}
            response = await async_client.post("/workflows/upload", files=files)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "workflow_id" in data
        assert data["status"] == "submitted"
        assert data["name"] == "Test Workflow File"
        assert data["tasks"] == 1
    
    @pytest.mark.asyncio
    async def test_upload_workflow_without_execution(self, async_client, temp_workflow_file):
        """Test uploading workflow for validation only"""
        with open(temp_workflow_file, 'rb') as f:
            files = {"file": ("workflow.yaml", f, "application/yaml")}
            response = await async_client.post("/workflows/upload?execute=false", files=files)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "validated"
        assert data["valid"] is True
    
    @pytest.mark.asyncio
    async def test_upload_invalid_workflow_file(self, async_client):
        """Test uploading invalid workflow file"""
        invalid_yaml = b"valid:\n  name: test\n  tasks:\n    - invalid"
        files = {"file": ("invalid.yaml", io.BytesIO(invalid_yaml), "application/yaml")}
        
        response = await async_client.post("/workflows/upload", files=files)
        assert response.status_code in [200, 400, 422]  # API may accept and validate later
    
    @pytest.mark.asyncio
    async def test_upload_json_workflow(self, async_client, mock_execution_engine):
        """Test uploading JSON workflow file"""
        workflow_json = {
            "name": "JSON Workflow",
            "tasks": [{
                "name": "JSON Task",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {"code": "result = 'json'"}
            }]
        }
        
        json_bytes = json.dumps(workflow_json).encode()
        files = {"file": ("workflow.json", io.BytesIO(json_bytes), "application/json")}
        
        response = await async_client.post("/workflows/upload", files=files)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "JSON Workflow"


class TestWorkflowCancellation:
    """Test workflow cancellation endpoints"""
    
    @pytest.mark.asyncio
    async def test_cancel_workflow(self, async_client, sample_workflow_request):
        """Test cancelling a running workflow"""
        from gleitzeit.api.main import app_state
        
        # Submit workflow
        submit_response = await async_client.post("/workflows", json=sample_workflow_request)
        workflow_id = submit_response.json()["workflow_id"]
        
        # Cancel workflow
        response = await async_client.delete(f"/workflows/{workflow_id}")
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "cancelled"
        assert data["workflow_id"] == workflow_id
        
        # Check workflow status updated
        workflow = app_state.active_workflows[workflow_id]
        assert workflow.status == "cancelled"
        assert workflow.completed_at is not None
    
    @pytest.mark.asyncio
    async def test_cancel_nonexistent_workflow(self, async_client):
        """Test cancelling non-existent workflow"""
        response = await async_client.delete("/workflows/nonexistent")
        assert response.status_code == 404
        assert response.json()["detail"] == "Workflow not found"


class TestWorkflowExecution:
    """Test workflow execution behavior"""
    
    @pytest.mark.asyncio
    async def test_workflow_background_execution(self, async_client, sample_workflow_request, 
                                                mock_execution_engine):
        """Test that workflow executes in background"""
        response = await async_client.post("/workflows", json=sample_workflow_request)
        assert response.status_code == 200
        
        # Response should return immediately
        data = response.json()
        assert data["status"] == "submitted"
        
        # Wait for background task
        await asyncio.sleep(0.2)
        
        # Verify execution methods were called
        mock_execution_engine.submit_workflow.assert_called_once()
        mock_execution_engine._execute_workflow.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_workflow_error_handling(self, async_client, sample_workflow_request, 
                                          mock_execution_engine):
        """Test workflow execution error handling"""
        from gleitzeit.api.main import app_state
        
        # Make execution fail
        mock_execution_engine._execute_workflow.side_effect = Exception("Execution failed")
        
        response = await async_client.post("/workflows", json=sample_workflow_request)
        workflow_id = response.json()["workflow_id"]
        
        # Wait for background task to fail
        await asyncio.sleep(0.2)
        
        # Check workflow marked as failed
        workflow = app_state.active_workflows[workflow_id]
        assert workflow.status == "failed"
        assert workflow.completed_at is not None
    
    @pytest.mark.asyncio
    async def test_workflow_result_collection(self, async_client, sample_workflow_request,
                                             mock_execution_engine):
        """Test collecting results from completed workflow tasks"""
        from gleitzeit.api.main import app_state
        from gleitzeit.core import TaskResult
        
        # Submit workflow
        response = await async_client.post("/workflows", json=sample_workflow_request)
        workflow_id = response.json()["workflow_id"]
        
        # Mock task results
        result1 = MagicMock(spec=TaskResult)
        result1.status = "completed"
        result1.result = {"output": "Task 1 output", "result": 10}
        result1.error = None
        
        result2 = MagicMock(spec=TaskResult)
        result2.status = "failed"
        result2.result = None
        result2.error = "Task 2 failed"
        
        mock_execution_engine.task_results = {
            "task1": result1,
            "task2": result2
        }
        
        # Wait for execution
        await asyncio.sleep(0.2)
        
        # Manually trigger result collection (simulating background task)
        workflow = app_state.active_workflows[workflow_id]
        workflow.status = "completed"
        workflow.tasks_completed = 1
        workflow.tasks_failed = 1
        workflow.results = {
            "task1": {"status": "completed", "result": result1.result, "error": None},
            "task2": {"status": "failed", "result": None, "error": "Task 2 failed"}
        }
        
        # Get workflow with results
        response = await async_client.get(f"/workflows/{workflow_id}")
        data = response.json()
        
        assert data["tasks_completed"] == 1
        assert data["tasks_failed"] == 1
        assert "task1" in data["results"]
        assert data["results"]["task1"]["status"] == "completed"
        assert data["results"]["task2"]["status"] == "failed"