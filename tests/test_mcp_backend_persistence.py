#!/usr/bin/env python3
"""
Test MCP Provider Backend Persistence
Verifies that MCP task results are properly saved and retrievable from the backend
"""

import asyncio
import sys
import os
import tempfile
import json
from pathlib import Path
import logging

# Set up logging to see what's happening
logging.basicConfig(level=logging.INFO)

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from gleitzeit.persistence.sqlite_backend import SQLiteBackend
from gleitzeit.core.models import Task, Workflow, TaskResult, TaskStatus, WorkflowStatus, Priority
from gleitzeit.providers.simple_mcp_provider import SimpleMCPProvider
from gleitzeit.protocols.mcp_protocol import mcp_protocol as MCP_PROTOCOL_V1
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.core.execution_engine import ExecutionEngine, ExecutionMode
from gleitzeit.task_queue.task_queue import QueueManager
from gleitzeit.task_queue.dependency_resolver import DependencyResolver


async def test_mcp_save_and_retrieve():
    """Test that MCP task results are saved and can be retrieved from backend"""
    
    print("\n" + "="*60)
    print("Test: MCP Task Result Persistence")
    print("="*60)
    
    # Create temporary database
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_mcp.db")
        
        # Initialize backend
        backend = SQLiteBackend(db_path)
        await backend.initialize()
        print("✅ Backend initialized")
        
        # Create and save an MCP task
        task = Task(
            id="mcp-echo-test",
            name="MCP Echo Test",
            protocol="mcp/v1",
            method="mcp/tool.echo",
            params={"message": "Hello from MCP test!"},
            priority=Priority.NORMAL,
            status=TaskStatus.QUEUED
        )
        
        # Save task to backend
        await backend.save_task(task)
        print("✅ MCP task saved to backend")
        
        # Retrieve task from backend
        retrieved_task = await backend.get_task("mcp-echo-test")
        assert retrieved_task is not None, "Task not found in backend"
        assert retrieved_task.method == "mcp/tool.echo", f"Method mismatch: {retrieved_task.method}"
        assert retrieved_task.params["message"] == "Hello from MCP test!", "Params not preserved"
        print("✅ MCP task retrieved from backend")
        
        # Create and save task result
        task_result = TaskResult(
            task_id="mcp-echo-test",
            status=TaskStatus.COMPLETED,
            result={
                "response": "Hello from MCP test!",
                "echoed": True,
                "length": 19
            },
            error=None,
            duration_seconds=0.001
        )
        
        await backend.save_task_result(task_result)
        print("✅ MCP task result saved to backend")
        
        # Retrieve task result from backend
        retrieved_result = await backend.get_task_result("mcp-echo-test")
        assert retrieved_result is not None, "Task result not found in backend"
        assert retrieved_result.status == TaskStatus.COMPLETED, f"Status mismatch: {retrieved_result.status}"
        assert retrieved_result.result["response"] == "Hello from MCP test!", "Result response not preserved"
        assert retrieved_result.result["echoed"] == True, "Result echoed flag not preserved"
        assert retrieved_result.result["length"] == 19, "Result length not preserved"
        print("✅ MCP task result retrieved from backend")
        print(f"   Retrieved result: {json.dumps(retrieved_result.result, indent=2)}")
        
        await backend.shutdown()
        
    print("\n✅ Test passed: MCP results persist and retrieve correctly")
    return True


async def test_mcp_workflow_execution_with_persistence():
    """Test full MCP workflow execution with backend persistence"""
    
    print("\n" + "="*60)
    print("Test: MCP Workflow Execution with Persistence")
    print("="*60)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_mcp_workflow.db")
        
        # Initialize components
        backend = SQLiteBackend(db_path)
        await backend.initialize()
        
        registry = ProtocolProviderRegistry()
        queue_manager = QueueManager()
        dependency_resolver = DependencyResolver()
        
        # Register MCP protocol
        registry.register_protocol(MCP_PROTOCOL_V1)
        
        # Create and register MCP provider
        mcp_provider = SimpleMCPProvider("test-mcp-provider")
        await mcp_provider.initialize()
        registry.register_provider("test-mcp-provider", "mcp/v1", mcp_provider)
        print("✅ MCP provider registered")
        
        # Create execution engine
        engine = ExecutionEngine(
            registry=registry,
            queue_manager=queue_manager,
            dependency_resolver=dependency_resolver,
            persistence=backend,
            max_concurrent_tasks=5
        )
        
        # Create a workflow with MCP tasks
        workflow = Workflow(
            id="test-mcp-workflow",
            name="Test MCP Workflow",
            description="Testing MCP backend persistence",
            tasks=[
                Task(
                    id="task1-echo",
                    name="Echo Task",
                    protocol="mcp/v1",
                    method="mcp/tool.echo",
                    params={"message": "Test message"},
                    priority=Priority.NORMAL
                ),
                Task(
                    id="task2-add",
                    name="Add Task",
                    protocol="mcp/v1",
                    method="mcp/tool.add",
                    params={"a": 10, "b": 20},
                    priority=Priority.NORMAL
                ),
                Task(
                    id="task3-multiply",
                    name="Multiply Task",
                    protocol="mcp/v1",
                    method="mcp/tool.multiply",
                    params={"a": 5, "b": 6},
                    priority=Priority.NORMAL,
                    dependencies=["task2-add"]  # Depends on add task
                )
            ]
        )
        
        # Save workflow to backend
        await backend.save_workflow(workflow)
        print("✅ Workflow saved to backend")
        
        # Submit workflow
        await engine.submit_workflow(workflow)
        print("✅ Workflow submitted")
        
        # Execute the workflow directly (like the CLI does)
        try:
            await engine._execute_workflow(workflow)
            print("✅ Workflow execution completed")
        except Exception as e:
            print(f"⚠️  Workflow execution error: {e}")
            # Continue anyway to check what was saved
        
        # Retrieve workflow from backend
        retrieved_workflow = await backend.get_workflow("test-mcp-workflow")
        assert retrieved_workflow is not None, "Workflow not found in backend"
        assert len(retrieved_workflow.tasks) == 3, f"Task count mismatch: {len(retrieved_workflow.tasks)}"
        print("✅ Workflow retrieved from backend")
        
        # Check each task and its result
        print("\n📊 Task Results from Backend:")
        for task in workflow.tasks:
            # Get task from backend
            retrieved_task = await backend.get_task(task.id)
            assert retrieved_task is not None, f"Task {task.id} not found"
            
            # Get task result from backend
            task_result = await backend.get_task_result(task.id)
            assert task_result is not None, f"Result for task {task.id} not found"
            assert task_result.status == TaskStatus.COMPLETED, f"Task {task.id} not completed"
            
            print(f"\n  Task: {task.name} ({task.id})")
            print(f"  Method: {task.method}")
            print(f"  Status: {task_result.status}")
            print(f"  Result from backend: {json.dumps(task_result.result, indent=4)}")
            
            # Verify specific results
            if task.id == "task1-echo":
                assert task_result.result["response"] == "Test message", "Echo result incorrect"
            elif task.id == "task2-add":
                assert task_result.result["result"] == 30, "Add result incorrect (10+20 should be 30)"
            elif task.id == "task3-multiply":
                assert task_result.result["result"] == 30, "Multiply result incorrect (5*6 should be 30)"
        
        # Check task count by status
        status_counts = await backend.get_task_count_by_status()
        print(f"\n📈 Task Status Summary:")
        for status, count in status_counts.items():
            print(f"  {status}: {count}")
        
        assert status_counts.get("completed", 0) >= 3, "Not all tasks completed"
        
        # Verify results are actually in the database
        import sqlite3
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM task_results WHERE task_id LIKE 'task%'")
        result_count = cursor.fetchone()[0]
        assert result_count == 3, f"Expected 3 results in database, found {result_count}"
        
        # Get actual result data from database
        cursor.execute("""
            SELECT t.name, r.result 
            FROM task_results r 
            JOIN tasks t ON r.task_id = t.id 
            WHERE t.id LIKE 'task%'
            ORDER BY t.id
        """)
        db_results = cursor.fetchall()
        
        print(f"\n📀 Raw Database Results:")
        for task_name, result_json in db_results:
            result_data = json.loads(result_json)
            print(f"  {task_name}: {result_data}")
        
        conn.close()
        
        await backend.shutdown()
        await registry.stop()
        
    print("\n✅ Test passed: MCP workflow results persist and retrieve correctly")
    return True


async def main():
    """Run all MCP backend persistence tests"""
    
    print("\n" + "="*60)
    print("MCP BACKEND PERSISTENCE TEST SUITE")
    print("="*60)
    
    tests = [
        ("Save and Retrieve MCP Task", test_mcp_save_and_retrieve),
        ("MCP Workflow Execution with Persistence", test_mcp_workflow_execution_with_persistence)
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            print(f"\n🧪 Running: {test_name}")
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ Test failed: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    failed = len(results) - passed
    
    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{test_name}: {status}")
    
    print(f"\nTotal: {passed} passed, {failed} failed out of {len(results)} tests")
    
    if failed == 0:
        print("\n🎉 All MCP backend persistence tests passed!")
        return 0
    else:
        print(f"\n❌ {failed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)