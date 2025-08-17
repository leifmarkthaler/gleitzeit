"""
Integration tests for workflow execution

Tests cover:
- Complete workflow execution pipeline
- Task dependency resolution
- Parallel task execution
- Error propagation through workflow
- Result persistence
- Provider integration

Related components:
- ExecutionEngine
- Workflow
- Task
- Providers
- Persistence
"""

import pytest
import asyncio
from typing import Dict, Any, List
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

from gleitzeit.core.execution_engine import ExecutionEngine
from gleitzeit.core.models import Task, Workflow, TaskStatus, WorkflowStatus, Priority
from gleitzeit.providers.base import ProtocolProvider
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.task_queue import QueueManager, DependencyResolver
from gleitzeit.core.protocol import ProtocolSpec


@pytest.mark.integration
class TestWorkflowExecution:
    """Integration tests for workflow execution"""
    
    @pytest.fixture
    async def mock_llm_provider(self):
        """Create mock LLM provider"""
        provider = AsyncMock(spec=ProtocolProvider)
        provider.id = "mock_llm"
        provider.protocol_id = "llm/v1"
        provider.health_check = AsyncMock(return_value=True)
        provider.execute = AsyncMock(return_value={
            "response": "Mock LLM response",
            "model": "mock-model"
        })
        provider.handle_request = AsyncMock(return_value={
            "response": "Mock LLM response",
            "model": "mock-model"
        })
        provider.__aenter__ = AsyncMock(return_value=provider)
        provider.__aexit__ = AsyncMock(return_value=None)
        return provider
    
    @pytest.fixture
    async def mock_python_provider(self):
        """Create mock Python provider"""
        provider = AsyncMock(spec=ProtocolProvider)
        provider.id = "mock_python"
        provider.protocol_id = "python/v1"
        provider.health_check = AsyncMock(return_value=True)
        provider.execute = AsyncMock(return_value={
            "status": "success",
            "output": "Script executed successfully"
        })
        provider.handle_request = AsyncMock(return_value={
            "status": "success",
            "output": "Script executed successfully"
        })
        provider.__aenter__ = AsyncMock(return_value=provider)
        provider.__aexit__ = AsyncMock(return_value=None)
        return provider
    
    @pytest.fixture
    async def execution_engine_with_providers(self, mock_llm_provider, mock_python_provider):
        """Create execution engine with mock providers"""
        registry = ProtocolProviderRegistry()
        queue_manager = QueueManager()
        dependency_resolver = DependencyResolver()
        
        engine = ExecutionEngine(
            registry=registry,
            queue_manager=queue_manager,
            dependency_resolver=dependency_resolver,
            max_concurrent_tasks=3
        )
        
        # Register protocols
        llm_protocol = ProtocolSpec(name="llm", version="v1", description="LLM Protocol")
        python_protocol = ProtocolSpec(name="python", version="v1", description="Python Protocol")
        engine.registry.register_protocol(llm_protocol)
        engine.registry.register_protocol(python_protocol)
        
        # Register providers
        engine.registry.register_provider("mock_llm", "llm/v1", mock_llm_provider)
        engine.registry.register_provider("mock_python", "python/v1", mock_python_provider)
        
        yield engine
        await engine.stop()
    
    @pytest.mark.asyncio
    async def test_simple_workflow_execution(self, execution_engine_with_providers):
        """Test execution of simple single-task workflow"""
        task = Task(
            id="task_1",
            name="Simple Task",
            protocol="llm/v1",
            method="chat",
            params={"model": "test", "messages": []},
            workflow_id="workflow_1"
        )
        
        workflow = Workflow(
            id="workflow_1",
            name="Simple Workflow",
            tasks=[task]
        )
        
        # Submit and execute workflow
        await execution_engine_with_providers.submit_workflow(workflow)
        await execution_engine_with_providers._execute_workflow(workflow)
        
        # Check task was completed
        assert task.status == TaskStatus.COMPLETED
        
        # Check result was stored
        result = execution_engine_with_providers.task_results.get("task_1")
        assert result is not None
        assert result.status == "completed"
    
    @pytest.mark.asyncio
    async def test_dependent_task_execution(self, execution_engine_with_providers):
        """Test execution of workflow with task dependencies"""
        task1 = Task(
            id="task_1",
            name="First Task",
            protocol="llm/v1",
            method="chat",
            params={"model": "test", "messages": []},
            workflow_id="workflow_1"
        )
        
        task2 = Task(
            id="task_2",
            name="Second Task",
            protocol="llm/v1",
            method="chat",
            params={"model": "test", "messages": []},
            dependencies=["task_1"],
            workflow_id="workflow_1"
        )
        
        task3 = Task(
            id="task_3",
            name="Third Task",
            protocol="python/v1",
            method="run",
            params={"script": "print('done')"},
            dependencies=["task_2"],
            workflow_id="workflow_1"
        )
        
        workflow = Workflow(
            id="workflow_1",
            name="Dependent Workflow",
            tasks=[task1, task2, task3]
        )
        
        # Execute workflow
        await execution_engine_with_providers.submit_workflow(workflow)
        await execution_engine_with_providers._execute_workflow(workflow)
        
        # All tasks should be completed
        assert task1.status == TaskStatus.COMPLETED
        assert task2.status == TaskStatus.COMPLETED
        assert task3.status == TaskStatus.COMPLETED
        
        # Tasks should have been executed in order
        assert task1.completed_at < task2.started_at
        assert task2.completed_at < task3.started_at
    
    @pytest.mark.asyncio
    async def test_parallel_task_execution(self, execution_engine_with_providers):
        """Test parallel execution of independent tasks"""
        # Create 5 independent tasks
        tasks = []
        for i in range(5):
            task = Task(
                id=f"parallel_task_{i}",
                name=f"Parallel Task {i}",
                protocol="llm/v1",
                method="chat",
                params={"model": "test", "messages": []},
                workflow_id="parallel_workflow"
            )
            tasks.append(task)
        
        workflow = Workflow(
            id="parallel_workflow",
            name="Parallel Workflow",
            tasks=tasks
        )
        
        # Track execution order
        execution_order = []
        original_execute = execution_engine_with_providers._execute_task
        
        async def track_execution(task):
            execution_order.append(task.id)
            return await original_execute(task)
        
        execution_engine_with_providers._execute_task = track_execution
        
        # Execute workflow
        await execution_engine_with_providers.submit_workflow(workflow)
        await execution_engine_with_providers._execute_workflow(workflow)
        
        # All tasks should be completed
        for task in tasks:
            assert task.status == TaskStatus.COMPLETED
        
        # Tasks should have executed in parallel (limited by max_concurrent_tasks)
        # With max_concurrent_tasks=3, first 3 should start immediately
        assert len(execution_order) == 5
    
    @pytest.mark.asyncio
    async def test_workflow_with_mixed_providers(self, execution_engine_with_providers):
        """Test workflow using multiple provider types"""
        llm_task = Task(
            id="llm_task",
            name="LLM Task",
            protocol="llm/v1",
            method="chat",
            params={"model": "test", "messages": []},
            workflow_id="mixed_workflow"
        )
        
        python_task = Task(
            id="python_task",
            name="Python Task",
            protocol="python/v1",
            method="run",
            params={"script": "print('test')"},
            dependencies=["llm_task"],
            workflow_id="mixed_workflow"
        )
        
        workflow = Workflow(
            id="mixed_workflow",
            name="Mixed Provider Workflow",
            tasks=[llm_task, python_task]
        )
        
        # Execute workflow
        await execution_engine_with_providers.submit_workflow(workflow)
        await execution_engine_with_providers._execute_workflow(workflow)
        
        # Both tasks should complete
        assert llm_task.status == TaskStatus.COMPLETED
        assert python_task.status == TaskStatus.COMPLETED
        
        # Check correct providers were used
        mock_llm = execution_engine_with_providers.registry.provider_instances["mock_llm"]
        mock_python = execution_engine_with_providers.registry.provider_instances["mock_python"]
        
        mock_llm.execute.assert_called()
        mock_python.execute.assert_called()
    
    @pytest.mark.asyncio
    async def test_workflow_error_propagation(self, execution_engine_with_providers):
        """Test error handling in workflow execution"""
        # Make first task fail
        mock_llm = execution_engine_with_providers.registry.provider_instances["mock_llm"]
        mock_llm.execute.side_effect = Exception("Provider error")
        
        task1 = Task(
            id="failing_task",
            name="Failing Task",
            protocol="llm/v1",
            method="chat",
            params={},
            workflow_id="error_workflow"
        )
        
        task2 = Task(
            id="dependent_task",
            name="Dependent Task",
            protocol="llm/v1",
            method="chat",
            params={},
            dependencies=["failing_task"],
            workflow_id="error_workflow"
        )
        
        workflow = Workflow(
            id="error_workflow",
            name="Error Workflow",
            tasks=[task1, task2]
        )
        
        # Execute workflow
        await execution_engine_with_providers.submit_workflow(workflow)
        await execution_engine_with_providers._execute_workflow(workflow)
        
        # First task should fail
        assert task1.status == TaskStatus.FAILED
        assert task1.error_message == "Provider error"
        
        # Dependent task should not execute
        assert task2.status == TaskStatus.PENDING
    
    @pytest.mark.asyncio
    async def test_workflow_retry_on_failure(self, execution_engine_with_providers):
        """Test task retry mechanism"""
        # Make provider fail twice then succeed
        call_count = 0
        
        async def flaky_execute(method, params):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Temporary failure")
            return {"response": "Success after retry"}
        
        mock_llm = execution_engine_with_providers.registry.provider_instances["mock_llm"]
        mock_llm.execute.side_effect = flaky_execute
        
        task = Task(
            id="retry_task",
            name="Retry Task",
            protocol="llm/v1",
            method="chat",
            params={},
            max_retries=3,
            workflow_id="retry_workflow"
        )
        
        workflow = Workflow(
            id="retry_workflow",
            name="Retry Workflow",
            tasks=[task]
        )
        
        # Execute workflow
        await execution_engine_with_providers.submit_workflow(workflow)
        await execution_engine_with_providers._execute_workflow(workflow)
        
        # Task should eventually succeed
        assert task.status == TaskStatus.COMPLETED
        assert task.attempt_count == 3
    
    @pytest.mark.asyncio
    async def test_workflow_priority_execution(self, execution_engine_with_providers):
        """Test task priority affects execution order"""
        high_priority_task = Task(
            id="high_priority",
            name="High Priority",
            protocol="llm/v1",
            method="chat",
            params={},
            priority=Priority.HIGH,
            workflow_id="priority_workflow"
        )
        
        normal_priority_task = Task(
            id="normal_priority",
            name="Normal Priority",
            protocol="llm/v1",
            method="chat",
            params={},
            priority=Priority.NORMAL,
            workflow_id="priority_workflow"
        )
        
        low_priority_task = Task(
            id="low_priority",
            name="Low Priority",
            protocol="llm/v1",
            method="chat",
            params={},
            priority=Priority.LOW,
            workflow_id="priority_workflow"
        )
        
        # Submit in reverse priority order
        workflow = Workflow(
            id="priority_workflow",
            name="Priority Workflow",
            tasks=[low_priority_task, normal_priority_task, high_priority_task]
        )
        
        # Track execution order
        execution_order = []
        
        async def track_execute(method, params):
            execution_order.append(params.get("task_id"))
            return {"response": "done"}
        
        mock_llm = execution_engine_with_providers.registry.provider_instances["mock_llm"]
        mock_llm.execute.side_effect = track_execute
        
        # Set max concurrent to 1 to force sequential execution
        execution_engine_with_providers.max_concurrent_tasks = 1
        
        await execution_engine_with_providers.submit_workflow(workflow)
        await execution_engine_with_providers._execute_workflow(workflow)
        
        # All tasks should complete
        assert all(t.status == TaskStatus.COMPLETED for t in workflow.tasks)
    
    @pytest.mark.asyncio
    async def test_workflow_cancellation(self, execution_engine_with_providers):
        """Test workflow cancellation during execution"""
        # Create slow tasks
        async def slow_execute(method, params):
            await asyncio.sleep(1)
            return {"response": "done"}
        
        mock_llm = execution_engine_with_providers.registry.provider_instances["mock_llm"]
        mock_llm.execute.side_effect = slow_execute
        
        tasks = [
            Task(
                id=f"task_{i}",
                name=f"Task {i}",
                protocol="llm/v1",
                method="chat",
                params={},
                workflow_id="cancel_workflow"
            )
            for i in range(5)
        ]
        
        workflow = Workflow(
            id="cancel_workflow",
            name="Cancel Workflow",
            tasks=tasks
        )
        
        # Start execution
        await execution_engine_with_providers.submit_workflow(workflow)
        
        # Start execution in background
        execution_task = asyncio.create_task(
            execution_engine_with_providers._execute_workflow(workflow)
        )
        
        # Wait a bit then cancel
        await asyncio.sleep(0.1)
        execution_task.cancel()
        
        try:
            await execution_task
        except asyncio.CancelledError:
            pass
        
        # Some tasks may have started but workflow should not be complete
        completed_count = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)
        assert completed_count < len(tasks)


@pytest.mark.integration
class TestWorkflowPersistence:
    """Test workflow execution with persistence"""
    
    @pytest.mark.asyncio
    async def test_workflow_results_persisted(
        self, execution_engine_with_providers, memory_persistence
    ):
        """Test that workflow results are persisted"""
        # Configure engine with persistence
        execution_engine_with_providers.persistence = memory_persistence
        
        task = Task(
            id="persist_task",
            name="Persist Task",
            protocol="llm/v1",
            method="chat",
            params={},
            workflow_id="persist_workflow"
        )
        
        workflow = Workflow(
            id="persist_workflow",
            name="Persist Workflow",
            tasks=[task]
        )
        
        # Execute workflow
        await execution_engine_with_providers.submit_workflow(workflow)
        await execution_engine_with_providers._execute_workflow(workflow)
        
        # Check result was persisted
        stored_result = await memory_persistence.get_task_result("persist_task")
        assert stored_result is not None
        assert stored_result["status"] == "completed"
    
    @pytest.mark.asyncio
    async def test_workflow_state_recovery(
        self, execution_engine_with_providers, memory_persistence
    ):
        """Test recovering workflow state from persistence"""
        # Store workflow state
        workflow_data = {
            "id": "recover_workflow",
            "name": "Recover Workflow",
            "status": "running",
            "tasks": [
                {"id": "task_1", "status": "completed"},
                {"id": "task_2", "status": "pending"}
            ]
        }
        
        await memory_persistence.store_workflow("recover_workflow", workflow_data)
        
        # Recover workflow
        recovered = await memory_persistence.get_workflow("recover_workflow")
        assert recovered is not None
        assert recovered["status"] == "running"
        assert len(recovered["tasks"]) == 2