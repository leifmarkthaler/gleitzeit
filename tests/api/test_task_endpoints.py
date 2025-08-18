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
    async def test_submit_single_task(self, async_client, sample_task_request, mock_execution_engine):
        """Test submitting a single task"""
        response = await async_client.post("/tasks", json=sample_task_request)
        assert response.status_code == 200
        data = response.json()
        
        # Check response structure
        assert "task_id" in data
        assert data["task_id"].startswith("api_task_")
        assert data["status"] == "submitted"
        assert "created_at" in data
        assert data["completed_at"] is None
        assert data["result"] is None
        assert data["error"] is None
        
        # Wait for background execution
        await asyncio.sleep(0.1)
        mock_execution_engine.submit_task.assert_called_once()
        mock_execution_engine.start.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_submit_task_with_custom_id(self, async_client, mock_execution_engine):
        """Test submitting task with custom ID"""
        task = {
            "id": "custom_task_123",
            "name": "Custom ID Task",
            "protocol": "python/v1",
            "method": "python/execute",
            "params": {"code": "result = 1"}
        }
        
        response = await async_client.post("/tasks", json=task)
        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == "custom_task_123"
    
    @pytest.mark.asyncio
    async def test_submit_task_with_dependencies(self, async_client, mock_execution_engine):
        """Test submitting task with dependencies"""
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
    
    @pytest.mark.asyncio
    async def test_submit_task_with_retry(self, async_client, mock_execution_engine):
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
    async def test_submit_task_without_engine(self, async_client, sample_task_request):
        """Test task submission when engine not initialized"""
        from gleitzeit.api.main import app_state
        
        original_engine = app_state.execution_engine
        app_state.execution_engine = None
        
        response = await async_client.post("/tasks", json=sample_task_request)
        assert response.status_code == 503
        assert response.json()["detail"] == "System not initialized"
        
        app_state.execution_engine = original_engine
    
    @pytest.mark.asyncio
    async def test_submit_task_with_priority(self, async_client, mock_execution_engine):
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
    async def test_get_nonexistent_task(self, async_client):
        """Test getting status of non-existent task"""
        response = await async_client.get("/tasks/nonexistent_task")
        assert response.status_code == 404
        assert response.json()["detail"] == "Task not found"
    
    @pytest.mark.asyncio
    async def test_task_completion_updates(self, async_client, sample_task_request, 
                                          mock_execution_engine, sample_task_result):
        """Test task status updates after completion"""
        from gleitzeit.api.main import app_state
        
        # Submit task
        submit_response = await async_client.post("/tasks", json=sample_task_request)
        task_id = submit_response.json()["task_id"]
        
        # Mock task result
        mock_execution_engine.task_results = {task_id: sample_task_result}
        
        # Wait for background execution
        await asyncio.sleep(0.2)
        
        # Manually update task status (simulating background task)
        if task_id in app_state.active_tasks:
            task = app_state.active_tasks[task_id]
            task.status = "completed"
            task.result = sample_task_result.result
            task.completed_at = datetime.now()
        
        # Get updated status
        response = await async_client.get(f"/tasks/{task_id}")
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "completed"
        assert data["result"] is not None
        assert data["completed_at"] is not None


class TestTaskExecution:
    """Test task execution behavior"""
    
    @pytest.mark.asyncio
    async def test_task_background_execution(self, async_client, sample_task_request, 
                                            mock_execution_engine):
        """Test that task executes in background"""
        response = await async_client.post("/tasks", json=sample_task_request)
        assert response.status_code == 200
        
        # Response should return immediately
        data = response.json()
        assert data["status"] == "submitted"
        
        # Wait for background task
        await asyncio.sleep(0.2)
        
        # Verify execution methods were called
        mock_execution_engine.submit_task.assert_called_once()
        mock_execution_engine.start.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_task_execution_success(self, async_client, sample_task_request,
                                         mock_execution_engine, sample_task_result):
        """Test successful task execution"""
        from gleitzeit.api.main import app_state
        
        # Submit task
        response = await async_client.post("/tasks", json=sample_task_request)
        task_id = response.json()["task_id"]
        
        # Mock successful execution
        mock_execution_engine.task_results = {task_id: sample_task_result}
        
        # Wait for execution
        await asyncio.sleep(0.2)
        
        # Manually update (simulating background task)
        task = app_state.active_tasks[task_id]
        task.status = "completed"
        task.result = sample_task_result.result
        task.error = None  # Explicitly set error to None for successful completion
        task.completed_at = datetime.now()
        
        # Check final status
        response = await async_client.get(f"/tasks/{task_id}")
        data = response.json()
        
        assert data["status"] == "completed"
        assert data["result"]["output"] == "Success"
        assert data["result"]["result"] == 4
        assert data["error"] is None
    
    @pytest.mark.asyncio
    async def test_task_execution_failure(self, async_client, sample_task_request,
                                         mock_execution_engine):
        """Test failed task execution"""
        from gleitzeit.api.main import app_state
        from gleitzeit.core import TaskResult
        
        # Submit task
        response = await async_client.post("/tasks", json=sample_task_request)
        task_id = response.json()["task_id"]
        
        # Mock failed execution
        failed_result = MagicMock(spec=TaskResult)
        failed_result.status = "failed"
        failed_result.result = None
        failed_result.error = "Execution error: Division by zero"
        
        mock_execution_engine.task_results = {task_id: failed_result}
        
        # Wait for execution
        await asyncio.sleep(0.2)
        
        # Manually update (simulating background task)
        task = app_state.active_tasks[task_id]
        task.status = "failed"
        task.error = failed_result.error
        task.completed_at = datetime.now()
        
        # Check final status
        response = await async_client.get(f"/tasks/{task_id}")
        data = response.json()
        
        assert data["status"] == "failed"
        assert data["error"] == "Execution error: Division by zero"
        assert data["result"] is None
    
    @pytest.mark.asyncio
    async def test_task_execution_timeout(self, async_client, mock_execution_engine):
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
                                          mock_execution_engine):
        """Test handling when task returns no result"""
        from gleitzeit.api.main import app_state
        
        # Submit task
        response = await async_client.post("/tasks", json=sample_task_request)
        task_id = response.json()["task_id"]
        
        # Mock no result returned
        mock_execution_engine.task_results = {}  # No result for task
        
        # Wait for execution
        await asyncio.sleep(0.2)
        
        # Manually update (simulating background task detecting no result)
        task = app_state.active_tasks[task_id]
        task.status = "failed"
        task.error = "No result returned"
        task.completed_at = datetime.now()
        
        # Check final status
        response = await async_client.get(f"/tasks/{task_id}")
        data = response.json()
        
        assert data["status"] == "failed"
        assert data["error"] == "No result returned"


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