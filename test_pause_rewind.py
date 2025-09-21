#!/usr/bin/env python
"""
Test script for pause-rewind functionality in Gleitzeit.

This script demonstrates:
1. Simple pause and resume
2. Pause with rewind to specific task
3. Pause with rewind to step number
"""

import asyncio
import time
import json
from gleitzeit import GleitzeitClient
from gleitzeit.core.models import Workflow, Task, TaskStatus, WorkflowStatus


async def create_test_workflow():
    """Create a workflow with multiple tasks for testing."""
    workflow = Workflow(
        name="Pause-Rewind Test Workflow",
        description="Testing pause and rewind functionality",
        tasks=[
            Task(
                id="task_1",
                name="First Task",
                protocol="python/v1",
                method="time.sleep",
                params={"seconds": 2}
            ),
            Task(
                id="task_2", 
                name="Second Task",
                protocol="python/v1",
                method="time.sleep",
                params={"seconds": 2},
                dependencies=["task_1"]
            ),
            Task(
                id="task_3",
                name="Third Task",
                protocol="python/v1",
                method="time.sleep",
                params={"seconds": 2},
                dependencies=["task_2"]
            ),
            Task(
                id="task_4",
                name="Fourth Task",
                protocol="python/v1",
                method="time.sleep",
                params={"seconds": 2},
                dependencies=["task_3"]
            ),
            Task(
                id="task_5",
                name="Fifth Task",
                protocol="python/v1",
                method="time.sleep",
                params={"seconds": 2},
                dependencies=["task_4"]
            )
        ]
    )
    return workflow


async def test_simple_pause_resume():
    """Test basic pause and resume without rewind."""
    print("\n=== Test 1: Simple Pause/Resume ===")
    
    client = GleitzeitClient()
    await client.initialize()
    
    # Submit workflow
    workflow = await create_test_workflow()
    result = await client.submit_workflow(workflow)
    workflow_id = result.get("workflow_id")
    print(f"Submitted workflow: {workflow_id}")
    
    # Wait for workflow to start executing
    await asyncio.sleep(3)
    
    # Check status
    wf = await client.get_workflow(workflow_id)
    print(f"Workflow status before pause: {wf.status if wf else 'Unknown'}")
    
    # Pause workflow
    pause_result = await client.pause_workflow(workflow_id, reason="Testing pause")
    print(f"Pause result: {pause_result}")
    
    # Check pause status
    pause_status = await client.get_pause_status(workflow_id)
    print(f"Pause status: {json.dumps(pause_status, indent=2)}")
    
    # Wait a bit
    await asyncio.sleep(2)
    
    # Resume workflow
    resume_result = await client.resume_workflow(workflow_id)
    print(f"Resume result: {resume_result}")
    
    # Wait for completion
    await asyncio.sleep(10)
    
    # Check final status
    wf = await client.get_workflow(workflow_id)
    print(f"Final workflow status: {wf.status if wf else 'Unknown'}")
    
    await client.shutdown()


async def test_pause_with_rewind_to_task():
    """Test pause with rewind to a specific task."""
    print("\n=== Test 2: Pause with Rewind to Task ===")
    
    client = GleitzeitClient()
    await client.initialize()
    
    # Submit workflow
    workflow = await create_test_workflow()
    result = await client.submit_workflow(workflow)
    workflow_id = result.get("workflow_id")
    print(f"Submitted workflow: {workflow_id}")
    
    # Wait for some tasks to complete
    await asyncio.sleep(5)
    
    # Check task statuses
    tasks = await client.get_workflow_tasks(workflow_id)
    for task in tasks:
        print(f"Task {task.id}: {task.status}")
    
    # Pause with rewind to task_2
    pause_result = await client.pause_workflow(
        workflow_id,
        rewind_to_task="task_2",
        reason="Testing rewind to task_2"
    )
    print(f"Pause with rewind result: {pause_result}")
    
    # Check pause status
    pause_status = await client.get_pause_status(workflow_id)
    print(f"Pause status with rewind: {json.dumps(pause_status, indent=2)}")
    
    # Check task statuses after rewind
    tasks = await client.get_workflow_tasks(workflow_id)
    print("\nTask statuses after rewind:")
    for task in tasks:
        print(f"Task {task.id}: {task.status}")
    
    # Resume workflow
    resume_result = await client.resume_workflow(workflow_id)
    print(f"Resume result: {resume_result}")
    
    # Wait for completion
    await asyncio.sleep(10)
    
    # Check final status
    wf = await client.get_workflow(workflow_id)
    print(f"Final workflow status: {wf.status if wf else 'Unknown'}")
    
    # Check final task statuses
    tasks = await client.get_workflow_tasks(workflow_id)
    print("\nFinal task statuses:")
    for task in tasks:
        print(f"Task {task.id}: {task.status}")
    
    await client.shutdown()


async def test_pause_with_rewind_to_step():
    """Test pause with rewind to a specific step number."""
    print("\n=== Test 3: Pause with Rewind to Step ===")
    
    client = GleitzeitClient()
    await client.initialize()
    
    # Submit workflow
    workflow = await create_test_workflow()
    result = await client.submit_workflow(workflow)
    workflow_id = result.get("workflow_id")
    print(f"Submitted workflow: {workflow_id}")
    
    # Wait for some tasks to complete
    await asyncio.sleep(6)
    
    # Check task statuses
    tasks = await client.get_workflow_tasks(workflow_id)
    for i, task in enumerate(tasks, 1):
        print(f"Step {i} - Task {task.id}: {task.status}")
    
    # Pause with rewind to step 3
    pause_result = await client.pause_workflow(
        workflow_id,
        rewind_to_step=3,
        reason="Testing rewind to step 3"
    )
    print(f"Pause with rewind to step 3 result: {pause_result}")
    
    # Check pause status
    pause_status = await client.get_pause_status(workflow_id)
    print(f"Pause status: {json.dumps(pause_status, indent=2)}")
    
    # Check task statuses after rewind
    tasks = await client.get_workflow_tasks(workflow_id)
    print("\nTask statuses after rewind to step 3:")
    for i, task in enumerate(tasks, 1):
        print(f"Step {i} - Task {task.id}: {task.status}")
    
    # Resume workflow
    resume_result = await client.resume_workflow(workflow_id)
    print(f"Resume result: {resume_result}")
    
    # Wait for completion
    await asyncio.sleep(10)
    
    # Check final status
    wf = await client.get_workflow(workflow_id)
    print(f"Final workflow status: {wf.status if wf else 'Unknown'}")
    
    await client.shutdown()


async def main():
    """Run all pause-rewind tests."""
    print("=" * 60)
    print("PAUSE-REWIND FUNCTIONALITY TESTS")
    print("=" * 60)
    
    try:
        # Test 1: Simple pause/resume
        await test_simple_pause_resume()
        
        # Test 2: Pause with rewind to task
        await test_pause_with_rewind_to_task()
        
        # Test 3: Pause with rewind to step
        await test_pause_with_rewind_to_step()
        
        print("\n" + "=" * 60)
        print("ALL TESTS COMPLETED")
        print("=" * 60)
        
    except Exception as e:
        print(f"\nError during tests: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())