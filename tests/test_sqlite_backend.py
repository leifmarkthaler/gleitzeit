#!/usr/bin/env python3
"""
Test SQLite Persistence Backend
"""

import asyncio
import sys
import os
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from gleitzeit.persistence.sqlite_backend import SQLiteBackend
from gleitzeit.core.models import Task, Workflow, TaskResult, TaskStatus, WorkflowStatus

async def test_backend_initialization():
    """Test SQLite backend initialization"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        backend = SQLiteBackend(db_path)
        
        await backend.initialize()
        
        # Check database file was created
        assert os.path.exists(db_path)
        
        await backend.shutdown()
        print("✅ Backend initialization test passed")

async def test_task_persistence():
    """Test task save and retrieve"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        backend = SQLiteBackend(db_path)
        await backend.initialize()
        
        # Create and save task
        task = Task(
            id="test-task-1",
            name="Test Task",
            protocol="python/v1",
            method="python/execute",
            params={"code": "result = 42"}
        )
        
        await backend.save_task(task)
        
        # Retrieve task
        retrieved = await backend.get_task("test-task-1")
        assert retrieved is not None
        assert retrieved.id == "test-task-1"
        assert retrieved.name == "Test Task"
        assert retrieved.params["code"] == "result = 42"
        
        await backend.shutdown()
        print("✅ Task persistence test passed")

async def test_workflow_persistence():
    """Test workflow save and retrieve"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        backend = SQLiteBackend(db_path)
        await backend.initialize()
        
        # Create workflow
        workflow = Workflow(
            id="test-workflow-1",
            name="Test Workflow",
            description="Test workflow for SQLite backend",
            tasks=[
                Task(id="t1", name="Task 1", protocol="p", method="m", params={}),
                Task(id="t2", name="Task 2", protocol="p", method="m", params={})
            ]
        )
        
        await backend.save_workflow(workflow)
        
        # Retrieve workflow
        retrieved = await backend.get_workflow("test-workflow-1")
        assert retrieved is not None
        assert retrieved.name == "Test Workflow"
        assert len(retrieved.tasks) == 2
        
        await backend.shutdown()
        print("✅ Workflow persistence test passed")

async def test_task_status_update():
    """Test task status updates"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        backend = SQLiteBackend(db_path)
        await backend.initialize()
        
        # Create task
        task = Task(
            id="status-task",
            name="Status Task",
            protocol="python/v1",
            method="python/execute",
            params={}
        )
        task.status = TaskStatus.QUEUED
        
        await backend.save_task(task)
        
        # Update status
        task.status = TaskStatus.EXECUTING
        await backend.save_task(task)
        
        # Retrieve and check
        retrieved = await backend.get_task("status-task")
        assert retrieved.status == TaskStatus.EXECUTING
        
        # Update to completed
        task.status = TaskStatus.COMPLETED
        await backend.save_task(task)
        
        retrieved = await backend.get_task("status-task")
        assert retrieved.status == TaskStatus.COMPLETED
        
        await backend.shutdown()
        print("✅ Task status update test passed")

async def test_get_tasks_by_status():
    """Test retrieving tasks by status"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        backend = SQLiteBackend(db_path)
        await backend.initialize()
        
        # Create tasks with different statuses
        tasks = [
            Task(id="queued1", name="Queued 1", protocol="p", method="m", params={}, status=TaskStatus.QUEUED),
            Task(id="queued2", name="Queued 2", protocol="p", method="m", params={}, status=TaskStatus.QUEUED),
            Task(id="executing1", name="Executing 1", protocol="p", method="m", params={}, status=TaskStatus.EXECUTING),
            Task(id="completed1", name="Completed 1", protocol="p", method="m", params={}, status=TaskStatus.COMPLETED),
        ]
        
        for task in tasks:
            await backend.save_task(task)
        
        # Get queued tasks
        queued_tasks = await backend.get_tasks_by_status(TaskStatus.QUEUED)
        assert len(queued_tasks) == 2
        
        # Get executing tasks
        executing_tasks = await backend.get_tasks_by_status(TaskStatus.EXECUTING)
        assert len(executing_tasks) == 1
        
        # Get completed tasks
        completed_tasks = await backend.get_tasks_by_status(TaskStatus.COMPLETED)
        assert len(completed_tasks) == 1
        
        await backend.shutdown()
        print("✅ Get tasks by status test passed")

async def test_task_result_persistence():
    """Test task result save and retrieve"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        backend = SQLiteBackend(db_path)
        await backend.initialize()
        
        # Create and save task
        task = Task(id="result-task", name="Result Task", protocol="p", method="m", params={})
        await backend.save_task(task)
        
        # Save task result
        result = TaskResult(
            task_id="result-task",
            status=TaskStatus.COMPLETED,
            result={"value": 42, "message": "Success"},
            error=None
        )
        
        await backend.save_task_result(result)
        
        # Retrieve result
        retrieved = await backend.get_task_result("result-task")
        assert retrieved is not None
        assert retrieved.status == TaskStatus.COMPLETED
        assert retrieved.result["value"] == 42
        assert retrieved.result["message"] == "Success"
        
        await backend.shutdown()
        print("✅ Task result persistence test passed")

async def test_delete_task():
    """Test task deletion"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        backend = SQLiteBackend(db_path)
        await backend.initialize()
        
        # Create and save task
        task = Task(id="delete-task", name="Delete Task", protocol="p", method="m", params={})
        await backend.save_task(task)
        
        # Verify it exists
        retrieved = await backend.get_task("delete-task")
        assert retrieved is not None
        
        # Delete task
        deleted = await backend.delete_task("delete-task")
        assert deleted
        
        # Verify it's gone
        retrieved = await backend.get_task("delete-task")
        assert retrieved is None
        
        await backend.shutdown()
        print("✅ Task deletion test passed")

async def main():
    """Run all tests"""
    print("🧪 Testing SQLite Persistence Backend")
    print("=" * 50)
    
    try:
        await test_backend_initialization()
        await test_task_persistence()
        await test_workflow_persistence()
        await test_task_status_update()
        await test_get_tasks_by_status()
        await test_task_result_persistence()
        await test_delete_task()
        
        print("\n✅ All SQLite backend tests PASSED")
        return 0
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))