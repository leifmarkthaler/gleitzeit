"""
Test Workflow Execution with Unified Persistence

Tests real workflow execution patterns with all persistence adapters to ensure
workflows work correctly with the unified persistence architecture.
"""

import pytest
import asyncio
import tempfile
import os
from datetime import datetime
from typing import List, Optional

# Import all adapters
from gleitzeit.persistence.unified_persistence import (
    UnifiedPersistenceAdapter,
    UnifiedInMemoryAdapter
)
from gleitzeit.persistence.unified_sqlalchemy import UnifiedSQLAlchemyAdapter
from gleitzeit.persistence.unified_redis import UnifiedRedisAdapter

# Import models
from gleitzeit.core.models import (
    Workflow, WorkflowExecution, TaskStatus, TaskResult
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
async def memory_adapter():
    """Create an in-memory adapter for testing"""
    adapter = UnifiedInMemoryAdapter()
    await adapter.initialize()
    yield adapter
    await adapter.shutdown()


@pytest.fixture
async def sql_adapter():
    """Create a SQLite adapter for testing"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name
    
    adapter = UnifiedSQLAlchemyAdapter(db_path=db_path)
    await adapter.initialize()
    yield adapter
    await adapter.shutdown()
    
    # Cleanup
    try:
        os.unlink(db_path)
    except:
        pass


@pytest.fixture
async def redis_adapter():
    """Create a Redis adapter for testing (requires Redis running)"""
    try:
        adapter = UnifiedRedisAdapter(
            redis_url="redis://localhost:6379/15",  # Use database 15 for tests
            key_prefix="test_workflow"
        )
        await adapter.initialize()
        
        # Clear test data
        await adapter._execute("FLUSHDB")
        
        yield adapter
        
        # Cleanup
        await adapter._execute("FLUSHDB")
        await adapter.shutdown()
    except Exception as e:
        pytest.skip(f"Redis not available: {e}")


@pytest.fixture(params=["memory", "sql", "redis"])
async def adapter(request):
    """Parametrized fixture that provides all adapter types"""
    if request.param == "memory":
        adapter = UnifiedInMemoryAdapter()
    elif request.param == "sql":
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name
        adapter = UnifiedSQLAlchemyAdapter(db_path=db_path)
    elif request.param == "redis":
        try:
            adapter = UnifiedRedisAdapter(
                redis_url="redis://localhost:6379/15",
                key_prefix="test_workflow"
            )
            await adapter.initialize()
            await adapter._execute("FLUSHDB")
            await adapter.shutdown()
            
            # Recreate for actual test
            adapter = UnifiedRedisAdapter(
                redis_url="redis://localhost:6379/15",
                key_prefix="test_workflow"
            )
        except Exception as e:
            pytest.skip(f"Redis not available: {e}")
    
    await adapter.initialize()
    yield adapter
    await adapter.shutdown()
    
    # Cleanup for SQL
    if request.param == "sql":
        try:
            os.unlink(db_path)
        except:
            pass


# ============================================================================
# Workflow Execution Tests
# ============================================================================

class TestWorkflowExecution:
    """Test complete workflow execution with persistence"""
    
    async def test_simple_workflow_execution(self, adapter):
        """Test execution of a simple linear workflow"""
        # Create a workflow - tasks will be auto-created as Task objects
        workflow = Workflow(
            id="wf_simple_001",
            name="Simple Processing Pipeline",
            description="Test simple workflow execution",
            tasks=[
                {
                    "name": "step_1",
                    "protocol": "python",
                    "method": "process",
                    "params": {"input": "data"}
                },
                {
                    "name": "step_2",
                    "protocol": "python",
                    "method": "transform",
                    "params": {"format": "json"}
                },
                {
                    "name": "step_3",
                    "protocol": "python",
                    "method": "save",
                    "params": {"output": "result.json"}
                }
            ]
        )
        
        # Set up dependencies (task 2 depends on 1, task 3 depends on 2)
        workflow.tasks[1].dependencies = [workflow.tasks[0].id]
        workflow.tasks[2].dependencies = [workflow.tasks[1].id]
        
        # Save workflow
        await adapter.save_workflow(workflow)
        
        # Create workflow execution
        execution = WorkflowExecution(
            execution_id=f"exec_{workflow.id}_001",
            workflow_id=workflow.id,
            status="running",
            started_at=datetime.utcnow(),
            completed_tasks=0,
            failed_tasks=0,
            total_tasks=len(workflow.tasks)
        )
        await adapter.save_workflow_execution(execution)
        
        # Save tasks to persistence
        for task in workflow.tasks:
            task.workflow_id = workflow.id
            await adapter.save_task(task)
        
        # Verify tasks were saved
        saved_tasks = await adapter.get_tasks_by_workflow(workflow.id)
        assert len(saved_tasks) == 3
        
        # Execute tasks in order
        for task in workflow.tasks:
            # Check dependencies
            can_execute = True
            if task.dependencies:
                for dep_id in task.dependencies:
                    dep_task = await adapter.get_task(dep_id)
                    if dep_task and dep_task.status != TaskStatus.COMPLETED:
                        can_execute = False
                        break
            
            assert can_execute, f"Task {task.name} should be executable"
            
            # Execute task
            task.status = TaskStatus.EXECUTING
            task.started_at = datetime.utcnow()
            await adapter.save_task(task)
            
            # Complete task
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.utcnow()
            await adapter.save_task(task)
            
            # Save task result
            result = TaskResult(
                task_id=task.id,
                status="completed",
                result={"output": f"Result from {task.name}"},
                duration_seconds=0.1
            )
            await adapter.save_task_result(result)
            
            # Update execution
            execution.completed_tasks += 1
            await adapter.save_workflow_execution(execution)
        
        # Complete execution
        execution.status = "completed"
        execution.completed_at = datetime.utcnow()
        await adapter.save_workflow_execution(execution)
        
        # Verify final state
        final_tasks = await adapter.get_tasks_by_workflow(workflow.id)
        assert all(t.status == TaskStatus.COMPLETED for t in final_tasks)
        
        final_execution = await adapter.get_workflow_execution(execution.execution_id)
        assert final_execution.status == "completed"
        assert final_execution.completed_tasks == 3
        assert final_execution.failed_tasks == 0
        
        # Cleanup
        for task in workflow.tasks:
            await adapter.delete_task(task.id)
    
    async def test_workflow_with_parallel_tasks(self, adapter):
        """Test workflow with parallel task execution"""
        # Create workflow with parallel branches
        workflow = Workflow(
            id="wf_parallel_001",
            name="Parallel Processing Workflow",
            description="Test parallel task execution",
            tasks=[
                {
                    "name": "setup",
                    "protocol": "python",
                    "method": "initialize",
                    "params": {}
                },
                {
                    "name": "process_a",
                    "protocol": "python",
                    "method": "process_a",
                    "params": {"branch": "A"}
                },
                {
                    "name": "process_b",
                    "protocol": "python",
                    "method": "process_b",
                    "params": {"branch": "B"}
                },
                {
                    "name": "merge",
                    "protocol": "python",
                    "method": "merge_results",
                    "params": {}
                }
            ]
        )
        
        # Set up dependencies: both process_a and process_b depend on setup
        # merge depends on both process_a and process_b
        workflow.tasks[1].dependencies = [workflow.tasks[0].id]  # process_a -> setup
        workflow.tasks[2].dependencies = [workflow.tasks[0].id]  # process_b -> setup
        workflow.tasks[3].dependencies = [workflow.tasks[1].id, workflow.tasks[2].id]  # merge -> both
        
        # Save workflow and tasks
        await adapter.save_workflow(workflow)
        for task in workflow.tasks:
            task.workflow_id = workflow.id
            await adapter.save_task(task)
        
        # Create execution
        execution = WorkflowExecution(
            execution_id=f"exec_{workflow.id}_001",
            workflow_id=workflow.id,
            status="running",
            started_at=datetime.utcnow(),
            completed_tasks=0,
            failed_tasks=0,
            total_tasks=len(workflow.tasks)
        )
        await adapter.save_workflow_execution(execution)
        
        # Execute setup task
        setup_task = workflow.tasks[0]
        setup_task.status = TaskStatus.COMPLETED
        setup_task.completed_at = datetime.utcnow()
        await adapter.save_task(setup_task)
        execution.completed_tasks += 1
        await adapter.save_workflow_execution(execution)
        
        # Execute parallel tasks (can run simultaneously)
        parallel_tasks = [workflow.tasks[1], workflow.tasks[2]]
        for task in parallel_tasks:
            # Verify dependencies are met
            for dep_id in task.dependencies:
                dep_task = await adapter.get_task(dep_id)
                assert dep_task.status == TaskStatus.COMPLETED
            
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.utcnow()
            await adapter.save_task(task)
            execution.completed_tasks += 1
            await adapter.save_workflow_execution(execution)
        
        # Execute merge task
        merge_task = workflow.tasks[3]
        for dep_id in merge_task.dependencies:
            dep_task = await adapter.get_task(dep_id)
            assert dep_task.status == TaskStatus.COMPLETED
        
        merge_task.status = TaskStatus.COMPLETED
        merge_task.completed_at = datetime.utcnow()
        await adapter.save_task(merge_task)
        execution.completed_tasks += 1
        
        # Complete execution
        execution.status = "completed"
        execution.completed_at = datetime.utcnow()
        await adapter.save_workflow_execution(execution)
        
        # Verify all tasks completed
        final_execution = await adapter.get_workflow_execution(execution.execution_id)
        assert final_execution.completed_tasks == 4
        assert final_execution.status == "completed"
        
        # Cleanup
        for task in workflow.tasks:
            await adapter.delete_task(task.id)
    
    async def test_workflow_with_failure_handling(self, adapter):
        """Test workflow execution with task failure"""
        # Create workflow
        workflow = Workflow(
            id="wf_failure_001",
            name="Failure Test Workflow",
            description="Test failure handling",
            tasks=[
                {
                    "name": "task_1",
                    "protocol": "python",
                    "method": "execute",
                    "params": {}
                },
                {
                    "name": "task_2_fails",
                    "protocol": "python",
                    "method": "fail",
                    "params": {}
                },
                {
                    "name": "task_3",
                    "protocol": "python",
                    "method": "cleanup",
                    "params": {}
                }
            ]
        )
        
        # Set dependencies
        workflow.tasks[1].dependencies = [workflow.tasks[0].id]
        workflow.tasks[2].dependencies = [workflow.tasks[1].id]
        
        # Save workflow and tasks
        await adapter.save_workflow(workflow)
        for task in workflow.tasks:
            task.workflow_id = workflow.id
            await adapter.save_task(task)
        
        # Create execution
        execution = WorkflowExecution(
            execution_id=f"exec_{workflow.id}_001",
            workflow_id=workflow.id,
            status="running",
            started_at=datetime.utcnow(),
            completed_tasks=0,
            failed_tasks=0,
            total_tasks=len(workflow.tasks)
        )
        await adapter.save_workflow_execution(execution)
        
        # Execute first task successfully
        task_1 = workflow.tasks[0]
        task_1.status = TaskStatus.COMPLETED
        task_1.completed_at = datetime.utcnow()
        await adapter.save_task(task_1)
        execution.completed_tasks += 1
        await adapter.save_workflow_execution(execution)
        
        # Second task fails
        task_2 = workflow.tasks[1]
        task_2.status = TaskStatus.FAILED
        task_2.error_message = "Simulated failure"
        task_2.completed_at = datetime.utcnow()
        await adapter.save_task(task_2)
        
        # Save failure result
        failure_result = TaskResult(
            task_id=task_2.id,
            status="failed",
            result={},
            error_message="Task failed: Simulated failure",
            duration_seconds=0.1
        )
        await adapter.save_task_result(failure_result)
        
        execution.failed_tasks += 1
        await adapter.save_workflow_execution(execution)
        
        # Third task cannot execute due to dependency failure
        task_3 = workflow.tasks[2]
        dep_task = await adapter.get_task(task_2.id)
        assert dep_task.status == TaskStatus.FAILED
        
        # Mark workflow as failed
        execution.status = "failed"
        execution.completed_at = datetime.utcnow()
        await adapter.save_workflow_execution(execution)
        
        # Verify final state
        final_execution = await adapter.get_workflow_execution(execution.execution_id)
        assert final_execution.status == "failed"
        assert final_execution.completed_tasks == 1
        assert final_execution.failed_tasks == 1
        
        # Verify task statuses
        tasks = await adapter.get_tasks_by_workflow(workflow.id)
        statuses = {t.id: t.status for t in tasks}
        assert statuses[task_1.id] == TaskStatus.COMPLETED
        assert statuses[task_2.id] == TaskStatus.FAILED
        assert statuses[task_3.id] == TaskStatus.QUEUED  # Never executed
        
        # Cleanup
        for task in workflow.tasks:
            await adapter.delete_task(task.id)
    
    async def test_workflow_queries(self, adapter):
        """Test querying workflows and their tasks"""
        # Create multiple workflows
        workflows = []
        for i in range(3):
            wf = Workflow(
                id=f"wf_query_{i}",
                name=f"Query Test Workflow {i}",
                tasks=[
                    {
                        "name": f"task_{j}",
                        "protocol": "python",
                        "method": "execute",
                        "params": {"index": j}
                    }
                    for j in range(2)
                ]
            )
            workflows.append(wf)
            await adapter.save_workflow(wf)
            
            # Save tasks
            for task in wf.tasks:
                task.workflow_id = wf.id
                task.status = TaskStatus.COMPLETED if i == 0 else TaskStatus.QUEUED
                await adapter.save_task(task)
        
        # Query completed tasks
        completed = await adapter.get_tasks_by_status(TaskStatus.COMPLETED)
        assert len(completed) == 2  # First workflow's tasks
        
        # Query by workflow
        wf0_tasks = await adapter.get_tasks_by_workflow(workflows[0].id)
        assert len(wf0_tasks) == 2
        assert all(t.status == TaskStatus.COMPLETED for t in wf0_tasks)
        
        wf1_tasks = await adapter.get_tasks_by_workflow(workflows[1].id)
        assert len(wf1_tasks) == 2
        assert all(t.status == TaskStatus.QUEUED for t in wf1_tasks)
        
        # Get task counts
        counts = await adapter.get_task_count_by_status()
        assert counts.get(TaskStatus.COMPLETED, 0) == 2
        assert counts.get(TaskStatus.QUEUED, 0) == 4
        
        # Cleanup
        for wf in workflows:
            for task in wf.tasks:
                await adapter.delete_task(task.id)