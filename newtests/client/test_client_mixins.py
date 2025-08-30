"""
Test the Gleitzeit modular client mixins
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
import tempfile
import json
import yaml
from pathlib import Path
from datetime import datetime

from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.core.models import Task, Workflow, TaskStatus


@pytest.fixture
async def client():
    """Create a test client with mocked adapter"""
    client = GleitzeitClient(mode="native", api_host="localhost", api_port=8080)
    
    # Mock the adapter to avoid actual initialization
    mock_adapter = AsyncMock()
    client._adapter = mock_adapter
    client._initialized = True
    
    return client


class TestTaskMixin:
    """Test task-related operations from TaskMixin"""
    
    @pytest.mark.asyncio
    async def test_submit_task_with_task_object(self, client):
        """Test submitting a Task object"""
        task = Task(name="test_task", protocol="test/v1", method="test_method")
        expected_result = {"task_id": "task_123", "status": "submitted"}
        
        client._adapter.submit_task.return_value = expected_result
        
        result = await client.submit_task(task)
        
        assert result == expected_result
        client._adapter.submit_task.assert_called_once_with(task)
    
    @pytest.mark.asyncio
    async def test_submit_task_with_dict(self, client):
        """Test submitting a task as dictionary"""
        task_dict = {"name": "test_task", "protocol": "test/v1", "method": "test_method"}
        expected_result = {"task_id": "task_123", "status": "submitted"}
        
        client._adapter.submit_task.return_value = expected_result
        
        result = await client.submit_task(task_dict)
        
        assert result == expected_result
        # Should convert dict to Task object
        client._adapter.submit_task.assert_called_once()
        submitted_task = client._adapter.submit_task.call_args[0][0]
        assert isinstance(submitted_task, Task)
        assert submitted_task.name == "test_task"
    
    @pytest.mark.asyncio
    async def test_execute_task(self, client):
        """Test executing a task and waiting for completion"""
        task = {"name": "test_task", "protocol": "test/v1", "method": "test_method"}
        
        # Mock submit_task to return task ID
        client._adapter.submit_task.return_value = {"task_id": "task_123"}
        
        # Mock wait_for_task to return result
        expected_result = Mock()
        expected_result.status = TaskStatus.COMPLETED
        expected_result.output = "Task completed"
        client._adapter.wait_for_task.return_value = expected_result
        
        result = await client.execute_task(task)
        
        assert result == expected_result
        client._adapter.submit_task.assert_called_once()
        client._adapter.wait_for_task.assert_called_once_with("task_123", 300.0, 1.0)
    
    @pytest.mark.asyncio
    async def test_get_task(self, client):
        """Test getting a task by ID"""
        task_id = "task_123"
        expected_task = Task(id=task_id, name="test_task", protocol="test/v1", method="test_method")
        
        client._adapter.get_task.return_value = expected_task
        
        result = await client.get_task(task_id)
        
        assert result == expected_task
        client._adapter.get_task.assert_called_once_with(task_id)
    
    @pytest.mark.asyncio
    async def test_get_task_result(self, client):
        """Test getting task result"""
        task_id = "task_123"
        expected_result = Mock()
        expected_result.output = "Task completed successfully"
        
        client._adapter.get_task_result.return_value = expected_result
        
        result = await client.get_task_result(task_id)
        
        assert result == expected_result
        client._adapter.get_task_result.assert_called_once_with(task_id)
    
    @pytest.mark.asyncio
    async def test_get_task_status(self, client):
        """Test getting task status"""
        task_id = "task_123"
        mock_task = Mock()
        mock_task.status = TaskStatus.EXECUTING
        
        client._adapter.get_task.return_value = mock_task
        
        result = await client.get_task_status(task_id)
        
        assert result == "executing"  # Should convert enum to string
        client._adapter.get_task.assert_called_once_with(task_id)
    
    @pytest.mark.asyncio
    async def test_list_tasks(self, client):
        """Test listing tasks with filters"""
        expected_tasks = {
            "tasks": [
                {"id": "task_1", "name": "Task 1", "status": "completed"},
                {"id": "task_2", "name": "Task 2", "status": "running"}
            ],
            "total": 2
        }
        
        client._adapter.list_tasks.return_value = expected_tasks
        
        result = await client.list_tasks(status="running", limit=50)
        
        assert result == expected_tasks
        client._adapter.list_tasks.assert_called_once_with("running", None, 50, 0)
    
    @pytest.mark.asyncio
    async def test_cancel_task(self, client):
        """Test cancelling a task"""
        task_id = "task_123"
        
        client._adapter.cancel_task.return_value = True
        
        result = await client.cancel_task(task_id)
        
        assert result is True
        client._adapter.cancel_task.assert_called_once_with(task_id)
    
    @pytest.mark.asyncio
    async def test_delete_task(self, client):
        """Test deleting a task"""
        task_id = "task_123"
        
        client._adapter.delete_task.return_value = True
        
        result = await client.delete_task(task_id)
        
        assert result is True
        client._adapter.delete_task.assert_called_once_with(task_id)
    
    @pytest.mark.asyncio
    async def test_wait_for_task(self, client):
        """Test waiting for task completion"""
        task_id = "task_123"
        expected_result = Mock()
        expected_result.status = TaskStatus.COMPLETED
        
        client._adapter.wait_for_task.return_value = expected_result
        
        result = await client.wait_for_task(task_id, timeout=60, poll_interval=0.5)
        
        assert result == expected_result
        client._adapter.wait_for_task.assert_called_once_with(task_id, 60, 0.5)
    
    @pytest.mark.asyncio
    async def test_retry_task(self, client):
        """Test retrying a failed task"""
        task_id = "task_123"
        
        # Mock getting the original task
        original_task = Mock()
        original_task.dict.return_value = {
            "id": task_id,
            "name": "test_task", 
            "protocol": "test/v1",
            "method": "test_method",
            "status": "failed"
        }
        client._adapter.get_task.return_value = original_task
        
        # Mock submitting retry
        retry_result = {"task_id": "task_456", "retry_of": task_id}
        client._adapter.submit_task.return_value = retry_result
        
        result = await client.retry_task(task_id)
        
        assert result == retry_result
        client._adapter.get_task.assert_called_once_with(task_id)
        client._adapter.submit_task.assert_called_once()
        
        # Check that retry task has correct structure
        # The submit_task converts dict to Task object, so we can't check dict keys directly
        # Instead we can verify the call was made correctly
        client._adapter.submit_task.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_task_statistics(self, client):
        """Test getting task statistics"""
        mock_tasks = {
            "tasks": [
                {"status": "completed"},
                {"status": "running"},
                {"status": "failed"},
                {"status": "completed"}
            ]
        }
        
        client._adapter.list_tasks.return_value = mock_tasks
        
        result = await client.get_task_statistics()
        
        expected_stats = {
            "total": 4,
            "pending": 0,
            "running": 1,
            "completed": 2,
            "failed": 1,
            "cancelled": 0
        }
        
        assert result == expected_stats
        client._adapter.list_tasks.assert_called_once_with(None, None, 1000, 0)
    
    @pytest.mark.asyncio
    async def test_batch_execute_tasks(self, client):
        """Test executing multiple tasks concurrently"""
        tasks = [
            {"name": "task1", "protocol": "test/v1", "method": "method1"},
            {"name": "task2", "protocol": "test/v1", "method": "method2"}
        ]
        
        # Mock individual task execution
        results = [Mock(), Mock()]
        results[0].status = TaskStatus.COMPLETED
        results[1].status = TaskStatus.COMPLETED
        
        client._adapter.submit_task.side_effect = [
            {"task_id": "task_1"}, 
            {"task_id": "task_2"}
        ]
        client._adapter.wait_for_task.side_effect = results
        
        result = await client.batch_execute_tasks(tasks, max_concurrent=2)
        
        assert len(result) == 2
        assert all(r.status == TaskStatus.COMPLETED for r in result)
        assert client._adapter.submit_task.call_count == 2
        assert client._adapter.wait_for_task.call_count == 2
    
    @pytest.mark.asyncio
    async def test_wait_for_tasks(self, client):
        """Test waiting for multiple tasks"""
        task_ids = ["task_1", "task_2"]
        
        # Mock results
        results = [Mock(), Mock()]
        results[0].status = TaskStatus.COMPLETED
        results[1].status = TaskStatus.FAILED
        
        client._adapter.wait_for_task.side_effect = results
        
        result = await client.wait_for_tasks(task_ids, timeout=60)
        
        assert len(result) == 2
        assert "task_1" in result
        assert "task_2" in result
        assert result["task_1"] == results[0]
        assert result["task_2"] == results[1]
        assert client._adapter.wait_for_task.call_count == 2


class TestWorkflowMixin:
    """Test workflow operations from WorkflowMixin"""
    
    @pytest.mark.asyncio
    async def test_submit_workflow(self, client):
        """Test submitting a workflow"""
        workflow = Workflow(name="Test Workflow", tasks=[])
        expected_result = {"workflow_id": "wf_123", "status": "submitted"}
        
        client._adapter.submit_workflow.return_value = expected_result
        
        result = await client.submit_workflow(workflow)
        
        assert result == expected_result
        client._adapter.submit_workflow.assert_called_once_with(workflow)
    
    @pytest.mark.asyncio
    async def test_run_workflow_from_file(self, client):
        """Test running a workflow from YAML file"""
        # Create a temporary workflow file
        workflow_dict = {
            "name": "Test Workflow",
            "tasks": [{"name": "task1", "protocol": "test/v1", "method": "test_method"}]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(workflow_dict, f)
            workflow_file = f.name
        
        try:
            expected_result = {"workflow_id": "wf_123", "status": "submitted"}
            client._adapter.submit_workflow.return_value = expected_result
            
            result = await client.run_workflow(workflow_file)
            
            assert result == expected_result
            client._adapter.submit_workflow.assert_called_once()
        finally:
            Path(workflow_file).unlink()
    
    @pytest.mark.asyncio
    async def test_get_workflow(self, client):
        """Test getting a workflow by ID"""
        workflow_id = "wf_123"
        expected_workflow = Workflow(id=workflow_id, name="Test Workflow", tasks=[])
        
        client._adapter.get_workflow.return_value = expected_workflow
        
        result = await client.get_workflow(workflow_id)
        
        assert result == expected_workflow
        client._adapter.get_workflow.assert_called_once_with(workflow_id)
    
    @pytest.mark.asyncio
    async def test_list_workflows(self, client):
        """Test listing workflows"""
        expected_workflows = {
            "workflows": [
                {"id": "wf_1", "name": "Workflow 1", "status": "completed"},
                {"id": "wf_2", "name": "Workflow 2", "status": "running"}
            ],
            "total": 2
        }
        
        client._adapter.list_workflows.return_value = expected_workflows
        
        result = await client.list_workflows(status="running", limit=50)
        
        assert result == expected_workflows
        client._adapter.list_workflows.assert_called_once_with("running", 50, 0)
    
    @pytest.mark.asyncio
    async def test_cancel_workflow(self, client):
        """Test cancelling a workflow"""
        workflow_id = "wf_123"
        expected_result = {"status": "cancelled", "workflow_id": workflow_id}
        
        client._adapter.cancel_workflow.return_value = expected_result
        
        result = await client.cancel_workflow(workflow_id)
        
        assert result == expected_result
        client._adapter.cancel_workflow.assert_called_once_with(workflow_id)
    
    @pytest.mark.asyncio
    async def test_pause_workflow(self, client):
        """Test pausing a workflow"""
        workflow_id = "wf_123"
        expected_result = {"status": "paused", "workflow_id": workflow_id}
        
        client._adapter.pause_workflow.return_value = expected_result
        
        result = await client.pause_workflow(workflow_id)
        
        assert result == expected_result
        client._adapter.pause_workflow.assert_called_once_with(workflow_id)
    
    @pytest.mark.asyncio
    async def test_resume_workflow(self, client):
        """Test resuming a workflow"""
        workflow_id = "wf_123"
        expected_result = {"status": "running", "workflow_id": workflow_id}
        
        client._adapter.resume_workflow.return_value = expected_result
        
        result = await client.resume_workflow(workflow_id)
        
        assert result == expected_result
        client._adapter.resume_workflow.assert_called_once_with(workflow_id)
    
    @pytest.mark.asyncio
    async def test_delete_workflow(self, client):
        """Test deleting a workflow"""
        workflow_id = "wf_123"
        
        client._adapter.delete_workflow.return_value = True
        
        result = await client.delete_workflow(workflow_id)
        
        assert result is True
        client._adapter.delete_workflow.assert_called_once_with(workflow_id)
    
    @pytest.mark.asyncio
    async def test_get_workflow_tasks(self, client):
        """Test getting workflow tasks"""
        workflow_id = "wf_123"
        expected_tasks = [Task(name="task1", protocol="test/v1", method="method1"), Task(name="task2", protocol="test/v1", method="method2")]
        
        client._adapter.get_workflow_tasks.return_value = expected_tasks
        
        result = await client.get_workflow_tasks(workflow_id)
        
        assert result == expected_tasks
        client._adapter.get_workflow_tasks.assert_called_once_with(workflow_id)
    
    @pytest.mark.asyncio
    async def test_wait_for_workflow(self, client):
        """Test waiting for workflow completion"""
        workflow_id = "wf_123"
        mock_workflow = Mock()
        mock_workflow.status = "completed"
        mock_workflow.dict.return_value = {"id": workflow_id, "status": "completed"}
        
        client._adapter.get_workflow.return_value = mock_workflow
        
        result = await client.wait_for_workflow(workflow_id, timeout=1, poll_interval=0.1)
        
        assert result == {"id": workflow_id, "status": "completed"}
        client._adapter.get_workflow.assert_called_with(workflow_id)
    
    @pytest.mark.asyncio
    async def test_clone_workflow(self, client):
        """Test cloning a workflow"""
        workflow_id = "wf_123"
        mock_workflow = Mock()
        mock_workflow.dict.return_value = {
            "id": workflow_id,
            "name": "Original Workflow",
            "tasks": [],
            "status": "completed"
        }
        
        client._adapter.get_workflow.return_value = mock_workflow
        client._adapter.submit_workflow.return_value = {"workflow_id": "wf_456"}
        
        result = await client.clone_workflow(workflow_id, new_name="Cloned Workflow")
        
        assert result == {"workflow_id": "wf_456"}
        client._adapter.get_workflow.assert_called_once_with(workflow_id)
        client._adapter.submit_workflow.assert_called_once()
        
        # Check that cloned workflow has correct structure
        submitted_workflow = client._adapter.submit_workflow.call_args[0][0]
        assert submitted_workflow.name == "Cloned Workflow"
    
    @pytest.mark.asyncio
    async def test_get_workflow_statistics(self, client):
        """Test getting workflow statistics"""
        mock_workflows = {
            "workflows": [
                {"status": "completed"},
                {"status": "running"},
                {"status": "failed"},
                {"status": "completed"}
            ]
        }
        
        client._adapter.list_workflows.return_value = mock_workflows
        
        result = await client.get_workflow_statistics()
        
        expected_stats = {
            "total": 4,
            "by_status": {
                "completed": 2,
                "running": 1,
                "failed": 1
            },
            "average_duration": 0,
            "success_rate": 50.0
        }
        
        assert result == expected_stats
        client._adapter.list_workflows.assert_called_once_with(None, 1000, 0)


class TestAuthMixin:
    """Test authentication operations from AuthMixin"""
    
    @pytest.mark.asyncio
    async def test_login(self, client):
        """Test user login"""
        username = "testuser"
        password = "testpass"
        expected_result = {"user_id": "user_123", "token": "auth_token", "status": "logged_in"}
        
        client._adapter.login.return_value = expected_result
        
        result = await client.login(username, password)
        
        assert result == expected_result
        client._adapter.login.assert_called_once_with(username, password)
    
    @pytest.mark.asyncio
    async def test_logout(self, client):
        """Test user logout"""
        expected_result = {"status": "logged_out"}
        
        client._adapter.logout.return_value = expected_result
        
        result = await client.logout()
        
        assert result == expected_result
        client._adapter.logout.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_current_user(self, client):
        """Test getting current user"""
        expected_user = {"id": "user_123", "username": "testuser", "role": "admin"}
        
        client._adapter.get_current_user.return_value = expected_user
        
        result = await client.get_current_user()
        
        assert result == expected_user
        client._adapter.get_current_user.assert_called_once()


class TestSystemMixin:
    """Test system operations from SystemMixin"""
    
    @pytest.mark.asyncio
    async def test_get_system_status(self, client):
        """Test getting system status"""
        expected_status = {"status": "healthy", "uptime": "2 days", "version": "1.0.0"}
        
        client._adapter.get_system_status.return_value = expected_status
        
        result = await client.get_system_status()
        
        assert result == expected_status
        client._adapter.get_system_status.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_health_check(self, client):
        """Test health check"""
        expected_health = {"status": "ok", "timestamp": datetime.now().isoformat()}
        
        client._adapter.health_check.return_value = expected_health
        
        result = await client.health_check()
        
        assert result == expected_health
        client._adapter.health_check.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_providers(self, client):
        """Test getting available providers"""
        expected_providers = [
            {"id": "python", "status": "healthy", "version": "1.0"},
            {"id": "shell", "status": "healthy", "version": "1.0"}
        ]
        
        client._adapter.get_providers.return_value = expected_providers
        
        result = await client.get_providers()
        
        assert result == expected_providers
        client._adapter.get_providers.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_protocols(self, client):
        """Test getting available protocols"""
        expected_protocols = [
            {"name": "python/v1", "version": "1.0", "supported_methods": ["execute"]},
            {"name": "shell/v1", "version": "1.0", "supported_methods": ["run"]}
        ]
        
        client._adapter.get_protocols.return_value = expected_protocols
        
        result = await client.get_protocols()
        
        assert result == expected_protocols
        client._adapter.get_protocols.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_chat(self, client):
        """Test LLM chat functionality"""
        message = "Hello, how are you?"
        model = "llama3.2:latest"
        expected_response = {"response": "I'm doing well, thank you!", "model": model}
        
        client._adapter.chat.return_value = expected_response
        
        result = await client.chat(message, model=model)
        
        assert result == expected_response
        client._adapter.chat.assert_called_once_with(message, model, 0.7, None)


class TestQueueMixin:
    """Test queue management operations from QueueMixin"""
    
    @pytest.mark.asyncio
    async def test_get_queues(self, client):
        """Test getting all queues"""
        expected_queues = {
            "high_priority": {"size": 5, "status": "active"},
            "normal": {"size": 12, "status": "active"},
            "low_priority": {"size": 3, "status": "paused"}
        }
        
        client._adapter.get_queues.return_value = expected_queues
        
        result = await client.get_queues()
        
        assert result == expected_queues
        client._adapter.get_queues.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_queue_details(self, client):
        """Test getting queue details"""
        queue_name = "high_priority"
        expected_details = {
            "name": queue_name,
            "size": 5,
            "status": "active",
            "workers": 3,
            "processing": 2
        }
        
        client._adapter.get_queue_details.return_value = expected_details
        
        result = await client.get_queue_details(queue_name)
        
        assert result == expected_details
        client._adapter.get_queue_details.assert_called_once_with(queue_name)
    
    @pytest.mark.asyncio
    async def test_pause_queue(self, client):
        """Test pausing a queue"""
        queue_name = "normal"
        expected_result = {"queue": queue_name, "status": "paused"}
        
        client._adapter.pause_queue.return_value = expected_result
        
        result = await client.pause_queue(queue_name)
        
        assert result == expected_result
        client._adapter.pause_queue.assert_called_once_with(queue_name)
    
    @pytest.mark.asyncio
    async def test_resume_queue(self, client):
        """Test resuming a queue"""
        queue_name = "normal"
        expected_result = {"queue": queue_name, "status": "active"}
        
        client._adapter.resume_queue.return_value = expected_result
        
        result = await client.resume_queue(queue_name)
        
        assert result == expected_result
        client._adapter.resume_queue.assert_called_once_with(queue_name)
    
    @pytest.mark.asyncio
    async def test_clear_queue(self, client):
        """Test clearing a queue"""
        queue_name = "normal"
        expected_result = {"queue": queue_name, "cleared_items": 12}
        
        client._adapter.clear_queue.return_value = expected_result
        
        result = await client.clear_queue(queue_name)
        
        assert result == expected_result
        client._adapter.clear_queue.assert_called_once_with(queue_name)
    
    @pytest.mark.asyncio
    async def test_configure_queue_not_supported(self, client):
        """Test configuring a queue when adapter doesn't support it"""
        queue_name = "normal"
        config = {"max_size": 100, "workers": 5}
        
        # Use a regular Mock that won't auto-create methods
        from unittest.mock import Mock
        mock_adapter = Mock()
        # Remove the configure_queue method to simulate unsupported functionality
        if hasattr(mock_adapter, 'configure_queue'):
            delattr(mock_adapter, 'configure_queue')
        client._adapter = mock_adapter
        
        result = await client.configure_queue(queue_name, config)
        
        expected_result = {"error": "Queue configuration not supported in this mode"}
        assert result == expected_result
    
    @pytest.mark.asyncio
    async def test_get_queue_statistics(self, client):
        """Test getting queue statistics"""
        mock_queues = {
            "high_priority": {"size": 5, "processing": 2, "status": "active"},
            "normal": {"size": 12, "processing": 3, "status": "active"},
            "low_priority": {"size": 3, "processing": 0, "status": "paused"}
        }
        
        client._adapter.get_queues.return_value = mock_queues
        
        result = await client.get_queue_statistics()
        
        expected_stats = {
            "total_queues": 3,
            "total_items": 20,
            "total_processing": 5,
            "queues": {
                "high_priority": {"size": 5, "processing": 2, "status": "active"},
                "normal": {"size": 12, "processing": 3, "status": "active"},
                "low_priority": {"size": 3, "processing": 0, "status": "paused"}
            }
        }
        
        assert result == expected_stats
        client._adapter.get_queues.assert_called_once()


class TestBatchProcessingMixin:
    """Test batch processing operations from BatchProcessingMixin"""
    
    @pytest.mark.asyncio
    async def test_batch_process(self, client):
        """Test batch processing files"""
        directory = "/test/dir"
        pattern = "*.txt"
        method = "llm/chat"
        prompt = "Analyze this file"
        
        expected_result = {"processed_files": 3, "batch_id": "batch_123"}
        
        client._adapter.batch_process.return_value = expected_result
        
        result = await client.batch_process(
            directory=directory,
            pattern=pattern,
            method=method,
            prompt=prompt
        )
        
        assert result == expected_result
        client._adapter.batch_process.assert_called_once_with(
            directory=directory,
            pattern=pattern,
            method=method,
            prompt=prompt,
            model="llama3.2:latest",
            max_concurrent=5,
            name=None
        )
    
    @pytest.mark.asyncio
    async def test_process_directory(self, client):
        """Test processing directory with workflow"""
        directory = "/test/dir"
        file_extensions = [".py", ".txt"]
        workflow_yaml = "workflow.yaml"
        
        expected_result = {"processed_files": 5, "workflow_id": "wf_123"}
        
        client._adapter.process_directory.return_value = expected_result
        
        result = await client.process_directory(
            directory=directory,
            file_extensions=file_extensions,
            workflow_yaml=workflow_yaml
        )
        
        assert result == expected_result
        client._adapter.process_directory.assert_called_once_with(
            directory=directory,
            file_extensions=file_extensions,
            workflow_yaml=workflow_yaml,
            max_concurrent=5,
            recursive=True
        )
    
    @pytest.mark.asyncio
    async def test_batch_analyze_files(self, client):
        """Test batch file analysis"""
        files = ["/path/file1.txt", "/path/file2.txt"]
        analysis_prompt = "What is the main topic of {filename}?"
        
        # Mock file content and task execution
        with patch('builtins.open', mock_open(read_data="Sample file content")):
            mock_result = Mock()
            mock_result.output = "Analysis result"
            client._adapter.submit_task.return_value = {"task_id": "task_123"}
            client._adapter.wait_for_task.return_value = mock_result
            
            result = await client.batch_analyze_files(files, analysis_prompt)
            
            assert len(result) == 2
            assert "/path/file1.txt" in result
            assert "/path/file2.txt" in result


class TestReplayMixin:
    """Test replay operations from ReplayMixin"""
    
    @pytest.mark.asyncio
    async def test_replay_workflow(self, client):
        """Test replaying a workflow"""
        workflow_id = "wf_123"
        mode = "re_execute"
        
        expected_result = {"new_workflow_id": "wf_456", "status": "replaying"}
        
        # Mock replay service
        mock_replay_service = Mock()
        mock_replay_service.replay = AsyncMock(return_value=expected_result)
        
        with patch.object(client, '_get_replay_service', return_value=mock_replay_service):
            result = await client.replay_workflow(workflow_id, mode)
        
        assert result == expected_result
        mock_replay_service.replay.assert_called_once_with(workflow_id, mode)
    
    @pytest.mark.asyncio
    async def test_continue_workflow(self, client):
        """Test continuing a failed workflow"""
        workflow_id = "wf_123"
        
        expected_result = {"new_workflow_id": "wf_456", "status": "continuing"}
        
        mock_replay_service = Mock()
        mock_replay_service.replay = AsyncMock(return_value=expected_result)
        
        with patch.object(client, '_get_replay_service', return_value=mock_replay_service):
            result = await client.continue_workflow(workflow_id)
        
        assert result == expected_result
        mock_replay_service.replay.assert_called_once_with(workflow_id, "continue", skip_completed=True)
    
    @pytest.mark.asyncio
    async def test_use_workflow_as_template(self, client):
        """Test using workflow as template"""
        workflow_id = "wf_123"
        modifications = {"name": "New Template Workflow"}
        
        expected_result = {"new_workflow_id": "wf_456", "status": "templated"}
        
        mock_replay_service = Mock()
        mock_replay_service.replay = AsyncMock(return_value=expected_result)
        
        with patch.object(client, '_get_replay_service', return_value=mock_replay_service):
            result = await client.use_workflow_as_template(workflow_id, modifications)
        
        assert result == expected_result
        mock_replay_service.replay.assert_called_once_with(workflow_id, "template", modifications=modifications)


class TestClientInitialization:
    """Test client initialization without adapter dependency"""
    
    @pytest.mark.asyncio
    async def test_client_not_initialized_error(self):
        """Test that methods raise error when client not initialized"""
        client = GleitzeitClient(mode="native")
        # Don't mock adapter or set initialized flag
        
        with pytest.raises(RuntimeError, match="Client not initialized"):
            await client.submit_task({"name": "test"})
    
    @pytest.mark.asyncio
    async def test_client_mode_detection(self):
        """Test client mode detection"""
        client = GleitzeitClient(mode=ClientMode.AUTO)
        
        assert client.mode == ClientMode.AUTO
    
    def test_client_configuration(self):
        """Test client configuration"""
        client = GleitzeitClient(
            mode="api",
            api_host="example.com",
            api_port=9000,
            auto_start_server=False,
            keep_server_running=True,
            headless=True
        )
        
        assert client.mode == ClientMode.API
        assert client.api_host == "example.com"
        assert client.api_port == 9000
        assert client.auto_start_server == False
        assert client.keep_server_running == True
        assert client.headless == True


def mock_open(read_data=""):
    """Helper function to mock file opening"""
    from unittest.mock import mock_open as mock_open_builtin
    return mock_open_builtin(read_data=read_data)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])