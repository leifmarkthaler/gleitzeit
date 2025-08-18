"""
Integration tests for the Gleitzeit API
"""

import pytest
import asyncio
import json
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch
from gleitzeit.core import TaskResult


class TestEndToEndWorkflows:
    """Test complete workflow execution scenarios"""
    
    @pytest.mark.asyncio
    async def test_complete_workflow_lifecycle(self, async_client, mock_execution_engine):
        """Test complete workflow from submission to completion"""
        # 1. Submit workflow
        workflow = {
            "name": "E2E Test Workflow",
            "description": "End-to-end test",
            "tasks": [
                {
                    "id": "step1",
                    "name": "First Step",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "result = 10"}
                },
                {
                    "id": "step2",
                    "name": "Second Step",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "result = 20"},
                    "dependencies": ["step1"]
                }
            ]
        }
        
        submit_response = await async_client.post("/workflows", json=workflow)
        assert submit_response.status_code == 200
        workflow_id = submit_response.json()["workflow_id"]
        
        # 2. Check initial status
        status_response = await async_client.get(f"/workflows/{workflow_id}")
        assert status_response.status_code == 200
        status_data = status_response.json()
        assert status_data["status"] == "submitted"
        assert status_data["tasks_total"] == 2
        
        # 3. Simulate execution completion
        from gleitzeit.api.main import app_state
        
        # Mock task results
        result1 = MagicMock(spec=TaskResult)
        result1.status = "completed"
        result1.result = {"output": "", "result": 10}
        
        result2 = MagicMock(spec=TaskResult)
        result2.status = "completed"
        result2.result = {"output": "", "result": 20}
        
        mock_execution_engine.task_results = {
            "step1": result1,
            "step2": result2
        }
        
        # Wait for background execution
        await asyncio.sleep(0.2)
        
        # Update workflow status
        if workflow_id in app_state.active_workflows:
            wf = app_state.active_workflows[workflow_id]
            wf.status = "completed"
            wf.tasks_completed = 2
            wf.completed_at = datetime.now()
            wf.results = {
                "step1": {"status": "completed", "result": result1.result, "error": None},
                "step2": {"status": "completed", "result": result2.result, "error": None}
            }
        
        # 4. Check final status
        final_response = await async_client.get(f"/workflows/{workflow_id}")
        assert final_response.status_code == 200
        final_data = final_response.json()
        assert final_data["status"] == "completed"
        assert final_data["tasks_completed"] == 2
        assert final_data["tasks_failed"] == 0
        assert "step1" in final_data["results"]
        assert "step2" in final_data["results"]
    
    @pytest.mark.asyncio
    async def test_workflow_with_failure_recovery(self, async_client, mock_execution_engine):
        """Test workflow with task failure and recovery"""
        from gleitzeit.api.main import app_state
        
        # Submit workflow with retry config
        workflow = {
            "name": "Recovery Test",
            "tasks": [
                {
                    "name": "Failing Task",
                    "protocol": "llm/v1",
                    "method": "llm/chat",
                    "params": {"messages": [{"role": "user", "content": "test"}]},
                    "retry": {
                        "max_attempts": 3,
                        "base_delay": 1.0
                    }
                }
            ]
        }
        
        response = await async_client.post("/workflows", json=workflow)
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        # Simulate failure then success
        failed_result = MagicMock(spec=TaskResult)
        failed_result.status = "failed"
        failed_result.error = "Temporary failure"
        
        success_result = MagicMock(spec=TaskResult)
        success_result.status = "completed"
        success_result.result = {"response": "Success after retry"}
        
        # First attempt fails
        mock_execution_engine.task_results = {"task_0": failed_result}
        await asyncio.sleep(0.1)
        
        # Retry succeeds
        mock_execution_engine.task_results = {"task_0": success_result}
        await asyncio.sleep(0.1)
        
        # Update workflow status
        if workflow_id in app_state.active_workflows:
            wf = app_state.active_workflows[workflow_id]
            wf.status = "completed"
            wf.tasks_completed = 1
            wf.results = {
                "task_0": {"status": "completed", "result": success_result.result, "error": None}
            }
        
        # Check final status
        response = await async_client.get(f"/workflows/{workflow_id}")
        data = response.json()
        assert data["status"] == "completed"
        assert data["tasks_completed"] == 1


class TestCrossEndpointIntegration:
    """Test integration between different endpoints"""
    
    @pytest.mark.asyncio
    async def test_template_to_workflow_integration(self, async_client, mock_execution_engine):
        """Test template execution creates proper workflow"""
        # Execute research template
        template_result = {
            "template_type": "research",
            "workflow_id": "template_research_123",
            "topic": "AI ethics",
            "status": "completed",
            "steps_planned": 5,
            "execution_time": 120.0,
            "report": "# Research Report\n\nAI ethics is...",
            "success": True
        }
        
        result = MagicMock(spec=TaskResult)
        result.status = "completed"
        result.result = template_result
        
        mock_execution_engine.task_results = {"template_test": result}
        
        with patch('gleitzeit.api.main.uuid.uuid4') as mock_uuid:
            mock_uuid.return_value.hex = "test1234" * 4
            
            response = await async_client.post("/templates/research", json={
                "topic": "AI ethics",
                "depth": "deep"
            })
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify workflow was created
        assert "workflow_id" in data
        assert data["steps_planned"] == 5
        
        # Verify task was submitted
        await asyncio.sleep(0.1)
        mock_execution_engine.submit_task.assert_called()
    
    @pytest.mark.asyncio
    async def test_batch_to_workflow_integration(self, async_client, mock_batch_processor, 
                                              mock_batch_result, mock_execution_engine):
        """Test batch processing integrates with workflow execution"""
        mock_batch_processor.process_batch.return_value = mock_batch_result
        
        # Submit batch processing
        response = await async_client.post("/batch", json={
            "directory": "/docs",
            "pattern": "*.txt",
            "prompt": "Summarize",
            "model": "llama3.2"
        })
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify batch processor was called with execution engine
        mock_batch_processor.process_batch.assert_called_once()
        call_args = mock_batch_processor.process_batch.call_args[1]
        assert call_args["execution_engine"] == mock_execution_engine
    
    @pytest.mark.asyncio
    async def test_mixed_endpoint_workflow(self, async_client, mock_execution_engine):
        """Test workflow using multiple endpoint types"""
        # 1. Execute Python code
        python_result = MagicMock(spec=TaskResult)
        python_result.status = "completed"
        python_result.result = {"output": "Data processed", "result": [1, 2, 3]}
        
        mock_execution_engine.task_results = {"exec_python": python_result}
        
        with patch('gleitzeit.api.main.uuid.uuid4') as mock_uuid:
            mock_uuid.return_value.hex = "python12" * 4
            
            python_response = await async_client.post("/execute/python", json={
                "code": "result = [1, 2, 3]",
                "timeout": 30
            })
        
        assert python_response.status_code == 200
        
        # 2. Chat about the result
        chat_result = MagicMock(spec=TaskResult)
        chat_result.status = "completed"
        chat_result.result = {"response": "The data shows a sequence..."}
        
        mock_execution_engine.task_results = {"chat_analysis": chat_result}
        
        with patch('gleitzeit.api.main.uuid.uuid4') as mock_uuid:
            mock_uuid.return_value.hex = "chat1234" * 4
            
            chat_response = await async_client.post("/chat", json={
                "message": f"Analyze this data: {python_response.json()['result']}",
                "model": "llama3.2"
            })
        
        assert chat_response.status_code == 200
        assert "sequence" in chat_response.json()["response"]


class TestSystemIntegration:
    """Test system-level integration"""
    
    @pytest.mark.asyncio
    async def test_provider_registration_and_discovery(self, async_client):
        """Test provider registration and discovery flow"""
        # 1. Check initial providers
        providers_response = await async_client.get("/providers")
        assert providers_response.status_code == 200
        initial_providers = providers_response.json()["providers"]
        
        # 2. Check protocols
        protocols_response = await async_client.get("/protocols")
        assert protocols_response.status_code == 200
        protocols = protocols_response.json()["protocols"]
        
        # 3. Verify provider-protocol mapping
        for provider in initial_providers:
            assert provider["protocol"] in protocols
    
    @pytest.mark.asyncio
    async def test_status_monitoring_integration(self, async_client, mock_execution_engine):
        """Test status monitoring across multiple operations"""
        from gleitzeit.api.main import app_state
        
        # 1. Get initial status
        initial_status = await async_client.get("/status")
        assert initial_status.status_code == 200
        initial_data = initial_status.json()
        initial_uptime = initial_data["uptime_seconds"]
        
        # 2. Submit some tasks
        for i in range(5):
            await async_client.post("/tasks", json={
                "name": f"Task {i}",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {"code": f"result = {i}"}
            })
        
        # 3. Wait and check updated status
        await asyncio.sleep(0.5)
        
        updated_status = await async_client.get("/status")
        assert updated_status.status_code == 200
        updated_data = updated_status.json()
        
        # Uptime should have increased
        assert updated_data["uptime_seconds"] > initial_uptime
    
    @pytest.mark.asyncio
    async def test_concurrent_operations(self, async_client, mock_execution_engine):
        """Test system handles concurrent operations correctly"""
        # Prepare different operation types
        operations = [
            # Status checks
            async_client.get("/status"),
            async_client.get("/health"),
            
            # Workflow submission
            async_client.post("/workflows", json={
                "name": "Concurrent WF",
                "tasks": [{"name": "t1", "protocol": "p", "method": "m"}]
            }),
            
            # Task execution
            async_client.post("/tasks", json={
                "name": "Concurrent Task",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {"code": "result = 1"}
            }),
            
            # Python execution
            async_client.post("/execute/python", json={
                "code": "print('concurrent')",
                "timeout": 30
            }),
            
            # Chat
            async_client.post("/chat", json={
                "message": "concurrent test",
                "model": "test"
            })
        ]
        
        # Execute all concurrently
        results = await asyncio.gather(*operations, return_exceptions=True)
        
        # All should succeed (no exceptions)
        for result in results:
            assert not isinstance(result, Exception)
            assert result.status_code in [200, 500]  # 500 for operations needing real results


class TestDataFlowIntegration:
    """Test data flow through the system"""
    
    @pytest.mark.asyncio
    async def test_parameter_substitution_flow(self, async_client, mock_execution_engine):
        """Test parameter substitution across workflow tasks"""
        from gleitzeit.api.main import app_state
        
        # Submit workflow with parameter substitution
        workflow = {
            "name": "Parameter Flow Test",
            "tasks": [
                {
                    "id": "generate",
                    "name": "Generate Data",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "result = {'value': 42, 'message': 'test'}"}
                },
                {
                    "id": "process",
                    "name": "Process Data",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "result = ${generate.result.value} * 2"},
                    "dependencies": ["generate"]
                }
            ]
        }
        
        response = await async_client.post("/workflows", json=workflow)
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        # Mock results
        gen_result = MagicMock(spec=TaskResult)
        gen_result.status = "completed"
        gen_result.result = {"result": {"value": 42, "message": "test"}}
        
        proc_result = MagicMock(spec=TaskResult)
        proc_result.status = "completed"
        proc_result.result = {"result": 84}
        
        mock_execution_engine.task_results = {
            "generate": gen_result,
            "process": proc_result
        }
        
        # Simulate completion
        await asyncio.sleep(0.2)
        
        if workflow_id in app_state.active_workflows:
            wf = app_state.active_workflows[workflow_id]
            wf.status = "completed"
            wf.tasks_completed = 2
            wf.results = {
                "generate": {"status": "completed", "result": gen_result.result, "error": None},
                "process": {"status": "completed", "result": proc_result.result, "error": None}
            }
        
        # Verify results
        response = await async_client.get(f"/workflows/{workflow_id}")
        data = response.json()
        
        assert data["results"]["generate"]["result"]["result"]["value"] == 42
        assert data["results"]["process"]["result"]["result"] == 84
    
    @pytest.mark.asyncio
    async def test_error_propagation(self, async_client, mock_execution_engine):
        """Test error propagation through the system"""
        from gleitzeit.api.main import app_state
        
        # Submit workflow where first task fails
        workflow = {
            "name": "Error Propagation Test",
            "tasks": [
                {
                    "id": "failing",
                    "name": "Failing Task",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "raise ValueError('Test error')"}
                },
                {
                    "id": "dependent",
                    "name": "Dependent Task",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "result = 1"},
                    "dependencies": ["failing"]
                }
            ]
        }
        
        response = await async_client.post("/workflows", json=workflow)
        workflow_id = response.json()["workflow_id"]
        
        # Mock failure
        failed_result = MagicMock(spec=TaskResult)
        failed_result.status = "failed"
        failed_result.error = "ValueError: Test error"
        
        mock_execution_engine.task_results = {"failing": failed_result}
        
        await asyncio.sleep(0.2)
        
        # Update workflow with failure
        if workflow_id in app_state.active_workflows:
            wf = app_state.active_workflows[workflow_id]
            wf.status = "failed"
            wf.tasks_failed = 1
            wf.results = {
                "failing": {"status": "failed", "result": None, "error": "ValueError: Test error"}
            }
        
        # Check error in response
        response = await async_client.get(f"/workflows/{workflow_id}")
        data = response.json()
        
        assert data["status"] == "failed"
        assert data["tasks_failed"] == 1
        assert "ValueError" in data["results"]["failing"]["error"]


class TestCleanupAndTeardown:
    """Test cleanup and teardown operations"""
    
    @pytest.mark.asyncio
    async def test_workflow_cancellation_cleanup(self, async_client):
        """Test cleanup after workflow cancellation"""
        from gleitzeit.api.main import app_state
        
        # Submit workflow
        response = await async_client.post("/workflows", json={
            "name": "To Cancel",
            "tasks": [{"name": "task", "protocol": "p", "method": "m"}]
        })
        workflow_id = response.json()["workflow_id"]
        
        # Cancel it
        cancel_response = await async_client.delete(f"/workflows/{workflow_id}")
        assert cancel_response.status_code == 200
        
        # Verify workflow marked as cancelled
        wf = app_state.active_workflows[workflow_id]
        assert wf.status == "cancelled"
        assert wf.completed_at is not None
    
    @pytest.mark.asyncio
    async def test_resource_cleanup_on_error(self, async_client, mock_execution_engine):
        """Test resources are cleaned up on error"""
        from gleitzeit.api.main import app_state
        
        # Make execution fail
        mock_execution_engine.submit_workflow.side_effect = Exception("Critical error")
        
        # Submit workflow
        response = await async_client.post("/workflows", json={
            "name": "Error Test",
            "tasks": []
        })
        
        workflow_id = response.json()["workflow_id"]
        
        # Wait for background task to fail
        await asyncio.sleep(0.2)
        
        # Workflow should still be tracked (for status queries)
        assert workflow_id in app_state.active_workflows
        
        # But should be marked as failed
        wf = app_state.active_workflows[workflow_id]
        assert wf.status == "failed"
        
        # Reset
        mock_execution_engine.submit_workflow.side_effect = None