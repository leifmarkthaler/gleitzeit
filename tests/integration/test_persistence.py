#!/usr/bin/env python3
"""
Test script to verify persistence layer functionality
"""

import asyncio
from datetime import datetime
from gleitzeit.persistence.unified_persistence import UnifiedInMemoryAdapter
from gleitzeit.core.models import Task, Workflow, Priority

async def test_persistence():
    """Test basic persistence operations"""
    print("=== Testing Gleitzeit Persistence Layer ===\n")
    
    # Initialize persistence
    persistence = UnifiedInMemoryAdapter()
    await persistence.initialize()
    print("✓ Persistence initialized")
    
    # Create a test workflow
    workflow = Workflow(
        id="test-workflow-1",
        name="Test Workflow",
        tasks=[],
        created_at=datetime.now()
    )
    
    # Save workflow
    await persistence.save_workflow(workflow)
    print("✓ Workflow saved")
    
    # Create test tasks
    task1 = Task(
        id="task-1",
        name="Task 1",
        protocol="python/v1",
        method="python/execute",
        params={"code": "print('hello')"},
        workflow_id="test-workflow-1",
        status="pending",
        priority=Priority.NORMAL
    )
    
    task2 = Task(
        id="task-2", 
        name="Task 2",
        protocol="llm/v1",
        method="llm/chat",
        params={"model": "llama3.2", "messages": []},
        workflow_id="test-workflow-1",
        status="completed",
        priority=Priority.HIGH
    )
    
    # Save tasks
    await persistence.save_task(task1)
    await persistence.save_task(task2)
    print("✓ Tasks saved")
    
    # Test retrieval
    retrieved_workflow = await persistence.get_workflow("test-workflow-1")
    print(f"✓ Retrieved workflow: {retrieved_workflow.name if retrieved_workflow else 'None'}")
    
    retrieved_task = await persistence.get_task("task-1")
    print(f"✓ Retrieved task: {retrieved_task.name if retrieved_task else 'None'}")
    
    # Test get tasks by workflow
    workflow_tasks = await persistence.get_tasks_by_workflow("test-workflow-1")
    print(f"✓ Tasks for workflow: {len(workflow_tasks)} tasks")
    
    # Test get tasks by status
    pending_tasks = await persistence.get_tasks_by_status("pending")
    print(f"✓ Pending tasks: {len(pending_tasks)} tasks")
    
    print("\n=== Testing List Methods ===\n")
    
    # Test list_workflows method
    try:
        workflows_result = await persistence.list_workflows(limit=10, offset=0)
        print(f"✓ list_workflows() returned: {workflows_result}")
        print(f"  - Total workflows: {workflows_result['total']}")
        print(f"  - Workflows in result: {len(workflows_result['workflows'])}")
        if workflows_result['workflows']:
            for wf in workflows_result['workflows']:
                print(f"    - {wf.id}: {wf.name}")
    except Exception as e:
        print(f"✗ list_workflows() failed: {e}")
    
    # Test list_tasks method
    try:
        tasks_result = await persistence.list_tasks(workflow_id="test-workflow-1", limit=10, offset=0)
        print(f"\n✓ list_tasks() returned: {tasks_result}")
        print(f"  - Total tasks: {tasks_result['total']}")
        print(f"  - Tasks in result: {len(tasks_result['tasks'])}")
        if tasks_result['tasks']:
            for task in tasks_result['tasks']:
                print(f"    - {task.id}: {task.name} ({task.status})")
    except Exception as e:
        print(f"✗ list_tasks() failed: {e}")
    
    # Test list_tasks with status filter
    try:
        completed_tasks = await persistence.list_tasks(status="completed", limit=10, offset=0)
        print(f"\n✓ list_tasks(status='completed') returned: {completed_tasks['total']} tasks")
    except Exception as e:
        print(f"✗ list_tasks(status='completed') failed: {e}")
    
    # Cleanup
    await persistence.shutdown()
    print("\n✓ Persistence shut down")
    
    print("\n=== All Tests Complete ===")

if __name__ == "__main__":
    asyncio.run(test_persistence())