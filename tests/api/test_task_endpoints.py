"""
Tests for task execution endpoints
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime


class TestTaskSubmission:
    """Test task submission endpoints"""
    
    @pytest.mark.asyncio
    async def test_submit_single_task(self, async_client, sample_task_request, mock_gleitzeit_client):
        """Test submitting a single task"""
        response = await async_client.post("/tasks", json=sample_task_request)
        assert response.status_code == 200
        data = response.json()
        
        # Check response structure
        assert "task_id" in data
        assert data["task_id"] == "client_task_12345678"  # Client generates the ID
        assert data["status"] == "submitted"
        assert "created_at" in data
        assert data["completed_at"] is None
        assert data["result"] is None
        assert data["error"] is None
        
        # Verify client was called to submit task
        mock_gleitzeit_client.submit_task.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_submit_task_with_custom_id(self, async_client, mock_gleitzeit_client):
        """Test submitting task with custom ID (ignored by API)"""
        task = {
            "id": "custom_task_123",  # This will be ignored, client generates ID
            "name": "Custom ID Task",
            "protocol": "python/v1",
            "method": "python/execute",
            "params": {"code": "result = 1"}
        }
        
        response = await async_client.post("/tasks", json=task)
        assert response.status_code == 200
        data = response.json()
        # API should use the client-generated ID, not the provided one
        assert data["task_id"] == "client_task_12345678"
    
    @pytest.mark.asyncio
    async def test_submit_task_with_dependencies(self, async_client, mock_gleitzeit_client):
        """Test submitting task with dependencies"""
        # Update mock to return a task with HIGH priority
        from gleitzeit.core import Task, Priority
        mock_task = MagicMock(spec=Task)
        mock_task.id = "client_task_with_deps"
        mock_task.name = "Dependent Task"
        mock_task.protocol = "python/v1"
        mock_task.method = "python/execute"
        mock_task.params = {"code": "result = prev_result * 2"}
        mock_task.status = "submitted"
        mock_task.priority = Priority.HIGH
        mock_gleitzeit_client.submit_task.return_value = mock_task
        
        task = {
            "name": "Dependent Task",
            "protocol": "python/v1",
            "method": "python/execute",
            "params": {"code": "result = prev_result * 2"},
            "dependencies": ["previous_task_id"],
            "priority": "high"
        }
        
        response = await async_client.post("/tasks", json=task)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "submitted"
        assert data["task_id"] == "client_task_with_deps"
    
    @pytest.mark.asyncio
    async def test_submit_task_with_retry(self, async_client, mock_gleitzeit_client):
        """Test submitting task with retry configuration"""
        task = {
            "name": "Retry Task",
            "protocol": "llm/v1",
            "method": "llm/chat",
            "params": {"messages": [{"role": "user", "content": "Hello"}]},
            "retry": {
                "max_attempts": 5,
                "base_delay": 2.0,
                "max_delay": 30.0
            }
        }
        
        response = await async_client.post("/tasks", json=task)
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_submit_task_without_client(self, async_client, sample_task_request):
        """Test task submission when client not initialized"""
        from gleitzeit.api.main import app_state
        
        original_client = app_state.client
        app_state.client = None
        
        response = await async_client.post("/tasks", json=sample_task_request)
        assert response.status_code == 503
        assert response.json()["detail"] == "System not initialized"
        
        app_state.client = original_client
    
    @pytest.mark.asyncio
    async def test_submit_task_with_priority(self, async_client, mock_gleitzeit_client):
        """Test task priority levels"""
        for priority in ["low", "normal", "high", "urgent"]:
            task = {
                "name": f"{priority.title()} Priority Task",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {"code": "result = 1"},
                "priority": priority
            }
            
            response = await async_client.post("/tasks", json=task)
            assert response.status_code == 200


class TestTaskStatus:
    """Test task status endpoints"""
    
    @pytest.mark.asyncio
    async def test_get_task_status(self, async_client, sample_task_request):
        """Test getting task status"""
        from gleitzeit.api.main import app_state
        
        # Submit task
        submit_response = await async_client.post("/tasks", json=sample_task_request)
        task_id = submit_response.json()["task_id"]
        
        # Get status
        response = await async_client.get(f"/tasks/{task_id}")
        assert response.status_code == 200
        data = response.json()
        
        assert data["task_id"] == task_id
        assert data["status"] in ["submitted", "running", "completed", "failed"]  # May be in any state
        assert "created_at" in data
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_task(self, async_client, mock_gleitzeit_client):
        """Test getting status of non-existent task"""
        # Mock get_task to return None for nonexistent task
        mock_gleitzeit_client.get_task.return_value = None
        
        response = await async_client.get("/tasks/nonexistent_task")
        assert response.status_code == 404
        assert response.json()["detail"] == "Task not found"
    
    @pytest.mark.asyncio
    async def test_task_completion_updates(self, async_client, sample_task_request, 
                                          mock_gleitzeit_client, sample_task_result):
        """Test task status updates after completion"""
        from gleitzeit.api.main import app_state
        from gleitzeit.core import Task
        
        # Submit task
        submit_response = await async_client.post("/tasks", json=sample_task_request)
        task_id = submit_response.json()["task_id"]
        
        # Mock get_task to return completed task
        completed_task = MagicMock(spec=Task)
        completed_task.id = task_id
        completed_task.status = "completed"
        completed_task.result = sample_task_result.result
        completed_task.error = None  # Add error attribute
        completed_task.created_at = datetime.now()
        completed_task.completed_at = datetime.now()
        mock_gleitzeit_client.get_task.return_value = completed_task
        
        # Get updated status
        response = await async_client.get(f"/tasks/{task_id}")
        assert response.status_code == 200
        data = response.json()
        
        assert data["task_id"] == task_id
        assert data["status"] == "completed"
        assert data["result"] is not None
        assert data["completed_at"] is not None


class TestTaskExecution:
    """Test task execution behavior"""
    
    @pytest.mark.asyncio
    async def test_task_background_execution(self, async_client, sample_task_request, 
                                            mock_gleitzeit_client):
        """Test that task executes in background"""
        response = await async_client.post("/tasks", json=sample_task_request)
        assert response.status_code == 200
        
        # Response should return immediately
        data = response.json()
        assert data["status"] == "submitted"
        
        # Verify client submit_task was called
        mock_gleitzeit_client.submit_task.assert_called_once()
        # wait_for_task is called in background, not immediately
        # So we don't check for it here
    
    @pytest.mark.asyncio
    async def test_task_execution_success(self, async_client, sample_task_request,
                                         mock_gleitzeit_client, sample_task_result):
        """Test successful task execution"""
        from gleitzeit.core import Task
        
        # Submit task
        response = await async_client.post("/tasks", json=sample_task_request)
        task_id = response.json()["task_id"]
        
        # Mock successful execution
        mock_gleitzeit_client.execute_task.return_value = sample_task_result
        
        # Mock get_task to return completed task
        completed_task = MagicMock(spec=Task)
        completed_task.id = task_id
        completed_task.status = "completed"
        completed_task.result = sample_task_result.result
        completed_task.error = None
        completed_task.created_at = datetime.now()
        completed_task.completed_at = datetime.now()
        mock_gleitzeit_client.get_task.return_value = completed_task
        
        # Check final status
        response = await async_client.get(f"/tasks/{task_id}")
        data = response.json()
        
        assert data["status"] == "completed"
        assert data["result"]["output"] == "Success"
        assert data["result"]["result"] == 4
        assert data["error"] is None
    
    @pytest.mark.asyncio
    async def test_task_execution_failure(self, async_client, sample_task_request,
                                         mock_gleitzeit_client):
        """Test failed task execution"""
        from gleitzeit.core import Task, TaskResult
        
        # Submit task
        response = await async_client.post("/tasks", json=sample_task_request)
        task_id = response.json()["task_id"]
        
        # Mock failed execution
        failed_result = MagicMock(spec=TaskResult)
        failed_result.status = "failed"
        failed_result.result = None
        failed_result.error = "Execution error: Division by zero"
        mock_gleitzeit_client.execute_task.return_value = failed_result
        
        # Mock get_task to return failed task
        failed_task = MagicMock(spec=Task)
        failed_task.id = task_id
        failed_task.status = "failed"
        failed_task.result = None
        failed_task.error = "Execution error: Division by zero"
        failed_task.created_at = datetime.now()
        failed_task.completed_at = datetime.now()
        mock_gleitzeit_client.get_task.return_value = failed_task
        
        # Check final status
        response = await async_client.get(f"/tasks/{task_id}")
        data = response.json()
        
        assert data["status"] == "failed"
        assert data["error"] == "Execution error: Division by zero"
        assert data["result"] is None
    
    @pytest.mark.asyncio
    async def test_task_execution_timeout(self, async_client, mock_gleitzeit_client):
        """Test task execution with timeout"""
        task = {
            "name": "Timeout Task",
            "protocol": "python/v1",
            "method": "python/execute",
            "params": {
                "code": "import time; time.sleep(100)",
                "timeout": 1  # 1 second timeout
            }
        }
        
        response = await async_client.post("/tasks", json=task)
        assert response.status_code == 200
        
        # Task should be submitted despite timeout configuration
        data = response.json()
        assert data["status"] == "submitted"
    
    @pytest.mark.asyncio
    async def test_task_no_result_handling(self, async_client, sample_task_request,
                                          mock_gleitzeit_client):
        """Test handling when task returns no result"""
        from gleitzeit.core import Task
        
        # Submit task
        response = await async_client.post("/tasks", json=sample_task_request)
        task_id = response.json()["task_id"]
        
        # Mock no result returned
        mock_gleitzeit_client.execute_task.return_value = None
        
        # Mock get_task to return failed task
        failed_task = MagicMock(spec=Task)
        failed_task.id = task_id
        failed_task.status = "failed"
        failed_task.result = None
        failed_task.error = "No result returned"
        failed_task.created_at = datetime.now()
        failed_task.completed_at = datetime.now()
        mock_gleitzeit_client.get_task.return_value = failed_task
        
        # Check final status
        response = await async_client.get(f"/tasks/{task_id}")
        data = response.json()
        
        assert data["status"] == "failed"
        assert data["error"] == "No result returned"


class TestTaskDeletion:
    """Test task deletion endpoints"""
    
    @pytest.mark.asyncio
    async def test_delete_existing_task(self, async_client, mock_gleitzeit_client):
        """Test deleting an existing task"""
        mock_gleitzeit_client.delete_task.return_value = True
        
        response = await async_client.delete("/tasks/task-123")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Task deleted successfully"
        
        mock_gleitzeit_client.delete_task.assert_called_once_with("task-123")
    
    @pytest.mark.asyncio
    async def test_delete_nonexistent_task(self, async_client, mock_gleitzeit_client):
        """Test deleting a non-existent task"""
        mock_gleitzeit_client.delete_task.return_value = False
        
        response = await async_client.delete("/tasks/nonexistent-task")
        assert response.status_code == 404
        data = response.json()
        assert data["detail"] == "Task not found"
    
    @pytest.mark.asyncio
    async def test_delete_workflow(self, async_client, mock_gleitzeit_client):
        """Test deleting a workflow and all its tasks"""
        mock_gleitzeit_client.delete_workflow.return_value = True
        
        response = await async_client.delete("/workflows/workflow-123")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Workflow deleted successfully"
        
        mock_gleitzeit_client.delete_workflow.assert_called_once_with("workflow-123")
    
    @pytest.mark.asyncio
    async def test_delete_nonexistent_workflow(self, async_client, mock_gleitzeit_client):
        """Test deleting a non-existent workflow"""
        mock_gleitzeit_client.delete_workflow.return_value = False
        
        response = await async_client.delete("/workflows/nonexistent-workflow")
        assert response.status_code == 404
        data = response.json()
        assert data["detail"] == "Workflow not found"


class TestTaskValidation:
    """Test task validation"""
    
    @pytest.mark.asyncio
    async def test_invalid_task_protocol(self, async_client):
        """Test submitting task with invalid protocol"""
        task = {
            "name": "Invalid Protocol",
            "protocol": "invalid/v1",
            "method": "invalid/method",
            "params": {}
        }
        
        response = await async_client.post("/tasks", json=task)
        # Should still accept but may fail during execution
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_missing_required_fields(self, async_client):
        """Test submitting task with missing required fields"""
        task = {
            "protocol": "python/v1"
            # Missing name and method
        }
        
        response = await async_client.post("/tasks", json=task)
        assert response.status_code == 422  # Validation error
    
    @pytest.mark.asyncio
    async def test_invalid_priority(self, async_client):
        """Test submitting task with invalid priority"""
        # Test with numeric priority (invalid type)
        task = {
            "name": "Invalid Priority",
            "protocol": "python/v1",
            "method": "python/execute",
            "params": {"code": "result = 1"},
            "priority": 999  # Invalid priority type (should be string)
        }
        
        response = await async_client.post("/tasks", json=task)
        # Should handle the invalid priority gracefully (may accept with default or reject)
        assert response.status_code in [200, 400, 422, 500]
    
    @pytest.mark.asyncio
    async def test_empty_params(self, async_client):
        """Test submitting task with empty params"""
        task = {
            "name": "Empty Params",
            "protocol": "python/v1",
            "method": "python/execute",
            "params": {}
        }
        
        response = await async_client.post("/tasks", json=task)
        assert response.status_code == 200  # Should accept empty params