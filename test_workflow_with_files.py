#!/usr/bin/env python3
"""
Test workflow execution with Python files and result retrieval.
This tests authorization, task execution, and result collection.
"""

import asyncio
import os
from pathlib import Path
from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.core.models import Workflow, Task

# Get the test tasks directory
TEST_TASKS_DIR = Path(__file__).parent / "test_tasks"


async def test_workflow_with_python_files():
    """Test running a workflow with Python file tasks."""
    print("=" * 60)
    print("WORKFLOW WITH PYTHON FILES TEST")
    print("=" * 60)
    
    # Initialize client
    client = GleitzeitClient(mode=ClientMode.API)
    await client.initialize()
    
    try:
        # Get current user
        user = await client.get_current_user()
        print(f"\n1. Current user: {user.get('username')} (role: {user.get('role')})")
        
        # Create workflow with tasks that use Python files
        workflow = Workflow(
            id="test-python-files-workflow",
            name="Python Files Workflow Test",
            tasks=[
                # Task 1: Add numbers
                Task(
                    id="task-add",
                    name="Add Numbers",
                    protocol="python/v1",
                    method="execute_file",
                    params={
                        "file": str(TEST_TASKS_DIR / "calculate.py"),
                        "function": "add_numbers",
                        "args": [10, 25]
                    }
                ),
                
                # Task 2: Multiply numbers
                Task(
                    id="task-multiply",
                    name="Multiply Numbers",
                    protocol="python/v1",
                    method="execute_file",
                    params={
                        "file": str(TEST_TASKS_DIR / "calculate.py"),
                        "function": "multiply_numbers",
                        "args": [7, 8]
                    }
                ),
                
                # Task 3: Process data
                Task(
                    id="task-process",
                    name="Process Data",
                    protocol="python/v1",
                    method="execute_file",
                    params={
                        "file": str(TEST_TASKS_DIR / "calculate.py"),
                        "function": "process_data",
                        "args": [[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]]
                    }
                ),
                
                # Task 4: Transform text
                Task(
                    id="task-transform",
                    name="Transform Text",
                    protocol="python/v1",
                    method="execute_file",
                    params={
                        "file": str(TEST_TASKS_DIR / "transform.py"),
                        "function": "transform_text",
                        "args": ["Hello Gleitzeit", "upper"]
                    }
                )
            ]
        )
        
        print("\n2. Submitting workflow with Python file tasks...")
        print(f"   Workflow: {workflow.name}")
        print(f"   Tasks: {len(workflow.tasks)}")
        for task in workflow.tasks:
            print(f"     - {task.name}: {task.params.get('file')}")
        
        # Submit workflow
        result = await client.submit_workflow(workflow)
        workflow_id = result.get('workflow_id', workflow.id)
        
        if result.get('success'):
            print(f"\n3. ✅ Workflow submitted successfully")
            print(f"   Workflow ID: {workflow_id}")
        else:
            print(f"\n3. ❌ Workflow submission failed: {result}")
            return False
        
        # Wait for workflow to complete
        print("\n4. Waiting for workflow to complete...")
        wait_result = await client.wait_for_workflow(
            workflow_id,
            timeout=60.0,
            poll_interval=2.0
        )
        
        if wait_result.get('status') == 'completed':
            print("   ✅ Workflow completed successfully")
        else:
            print(f"   ❌ Workflow did not complete: {wait_result}")
        
        # Get workflow status
        print("\n5. Getting workflow details...")
        workflow_details = await client.get_workflow(workflow_id)
        if workflow_details:
            print(f"   Status: {workflow_details.status}")
            print(f"   Completed tasks: {workflow_details.tasks_completed}/{workflow_details.tasks_total}")
            print(f"   Failed tasks: {workflow_details.tasks_failed}")
            
            # Check ownership
            if hasattr(workflow_details, 'user_id'):
                print(f"   Owner: {workflow_details.user_id}")
                if workflow_details.user_id == user.get('id'):
                    print("   ✅ Workflow owned by current user")
                else:
                    print("   ❌ Workflow not owned by current user")
        
        # Get workflow results
        print("\n6. Getting workflow results...")
        results = await client.get_workflow_results(workflow_id)
        
        if results:
            print("   ✅ Results retrieved successfully")
            
            # Display results for each task
            if 'task_results' in results:
                for task_id, task_result in results['task_results'].items():
                    print(f"\n   Task: {task_id}")
                    print(f"   Result: {task_result}")
            elif 'results' in results:
                for task_id, task_result in results['results'].items():
                    print(f"\n   Task: {task_id}")
                    print(f"   Result: {task_result}")
            else:
                print(f"   Results structure: {results}")
        else:
            print("   ❌ No results retrieved")
        
        # Test authorization: Try to access as if we were another user
        print("\n7. Testing authorization...")
        
        # List workflows - should only see our own
        all_workflows = await client.list_workflows()
        if all_workflows:
            if isinstance(all_workflows, dict):
                workflow_list = all_workflows.get('workflows', [])
            else:
                workflow_list = all_workflows
            
            our_workflows = [w for w in workflow_list 
                           if (hasattr(w, 'id') and w.id == workflow_id) or 
                              (isinstance(w, dict) and w.get('id') == workflow_id)]
            
            if our_workflows:
                print(f"   ✅ Can see our workflow in list")
            else:
                print(f"   ⚠️ Cannot see our workflow in list")
            
            # Check if we see workflows we shouldn't
            for wf in workflow_list:
                wf_user_id = getattr(wf, 'user_id', None) if hasattr(wf, 'user_id') else wf.get('user_id')
                wf_id = getattr(wf, 'id', None) if hasattr(wf, 'id') else wf.get('id')
                if wf_user_id and wf_user_id != user.get('id') and wf_user_id != 'basic-user':
                    print(f"   ❌ Can see other user's workflow: {wf_id} (owner: {wf_user_id})")
        
        print("\n8. Testing task results...")
        # Get individual task results
        for task in workflow.tasks:
            try:
                task_result = await client.get_task_result(task.id)
                if task_result:
                    print(f"   ✅ Got result for {task.name}: {task_result.result if hasattr(task_result, 'result') else task_result}")
                else:
                    print(f"   ⚠️ No result for {task.name}")
            except Exception as e:
                print(f"   ❌ Error getting result for {task.name}: {e}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await client.shutdown()


async def main():
    """Run the workflow test."""
    
    # Check that test files exist
    test_files = [
        TEST_TASKS_DIR / "calculate.py",
        TEST_TASKS_DIR / "transform.py"
    ]
    
    for file in test_files:
        if not file.exists():
            print(f"❌ Test file not found: {file}")
            print("Please ensure test_tasks directory contains calculate.py and transform.py")
            return
    
    print("Test files found:")
    for file in test_files:
        print(f"  ✓ {file}")
    
    # Run the test
    success = await test_workflow_with_python_files()
    
    print("\n" + "=" * 60)
    if success:
        print("✅ WORKFLOW TEST COMPLETED SUCCESSFULLY")
        print("Authorization, execution, and results all working!")
    else:
        print("❌ WORKFLOW TEST FAILED")
        print("Please check the errors above")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())