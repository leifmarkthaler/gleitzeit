#!/usr/bin/env python3
"""
Test script for new delete methods in GleitzeitClient
"""

import asyncio
from gleitzeit.client import GleitzeitClient
import yaml
import tempfile
import os

async def test_delete_methods():
    """Test the new delete methods"""
    
    # Test with memory backend (for quick testing)
    os.environ['GLEITZEIT_PERSISTENCE_TYPE'] = 'memory'
    
    async with GleitzeitClient(mode="native") as client:
        print("Testing delete methods with memory backend...")
        
        # Create a test workflow
        workflow_yaml = """
name: Test Delete Workflow
tasks:
  - id: task1
    name: Task 1
    protocol: python/v1
    method: python/execute
    params:
      code: |
        print("Task 1 executed")
        
  - id: task2
    name: Task 2
    protocol: python/v1
    method: python/execute
    params:
      code: |
        print("Task 2 executed")
    depends_on: [task1]
"""
        
        # Save workflow to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(workflow_yaml)
            workflow_file = f.name
        
        try:
            # Run the workflow
            print("\n1. Running workflow...")
            result = await client.run_workflow(workflow_file)
            workflow_id = result['workflow_id']
            print(f"   Workflow ID: {workflow_id}")
            
            # List workflows
            print("\n2. Listing workflows before deletion...")
            workflows = await client.list_workflows()
            print(f"   Total workflows: {workflows['total']}")
            
            # List tasks
            print("\n3. Listing tasks before deletion...")
            tasks = await client.list_tasks(workflow_id=workflow_id)
            print(f"   Tasks for workflow: {tasks['total']}")
            for task in tasks['tasks']:
                print(f"   - {task.id}: {task.name} ({task.status})")
            
            # Test delete_task
            if tasks['total'] > 0:
                task_id = tasks['tasks'][0].id
                print(f"\n4. Deleting task: {task_id}")
                deleted = await client.delete_task(task_id)
                print(f"   Task deleted: {deleted}")
                
                # Check remaining tasks
                tasks_after = await client.list_tasks(workflow_id=workflow_id)
                print(f"   Remaining tasks: {tasks_after['total']}")
            
            # Test delete_workflow
            print(f"\n5. Deleting workflow: {workflow_id}")
            deleted = await client.delete_workflow(workflow_id)
            print(f"   Workflow deleted: {deleted}")
            
            # Verify deletion
            print("\n6. Verifying deletion...")
            workflows_after = await client.list_workflows()
            print(f"   Total workflows after deletion: {workflows_after['total']}")
            
            tasks_after = await client.list_tasks(workflow_id=workflow_id)
            print(f"   Tasks for deleted workflow: {tasks_after['total']}")
            
            # Test with non-existent IDs
            print("\n7. Testing with non-existent IDs...")
            deleted = await client.delete_task("non_existent_task")
            print(f"   Delete non-existent task: {deleted}")
            
            deleted = await client.delete_workflow("non_existent_workflow")
            print(f"   Delete non-existent workflow: {deleted}")
            
            print("\n✅ All delete method tests completed!")
            
        finally:
            # Clean up temp file
            os.unlink(workflow_file)

async def test_cleanup_old_data():
    """Test the cleanup_old_data method"""
    
    async with GleitzeitClient(mode="native") as client:
        print("\n\nTesting cleanup_old_data method...")
        
        # Clean up data older than 0 days (everything)
        deleted_count = await client.cleanup_old_data(days=0)
        print(f"   Deleted {deleted_count} old items")
        
        print("✅ Cleanup test completed!")

async def main():
    """Run all tests"""
    await test_delete_methods()
    await test_cleanup_old_data()

if __name__ == "__main__":
    asyncio.run(main())