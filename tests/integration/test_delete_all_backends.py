#!/usr/bin/env python3
"""
Test delete methods with Redis and SQL backends
"""

import asyncio
from gleitzeit.client import GleitzeitClient
import os

async def test_backend(backend_type: str):
    """Test delete methods with a specific backend"""
    
    print(f"\n{'='*60}")
    print(f"Testing with {backend_type.upper()} backend")
    print('='*60)
    
    # Set the backend type
    os.environ['GLEITZEIT_PERSISTENCE_TYPE'] = backend_type
    
    async with GleitzeitClient(mode="native") as client:
        # Run an example workflow
        workflow_file = "examples/simple_python_workflow.yaml"
        
        print(f"\n1. Running workflow...")
        result = await client.run_workflow(workflow_file)
        workflow_id = result['workflow_id']
        print(f"   Workflow ID: {workflow_id}")
        print(f"   Status: {result['status']}")
        
        # Wait a moment for persistence
        await asyncio.sleep(0.5)
        
        # List workflows
        print("\n2. Listing workflows before deletion...")
        workflows = await client.list_workflows()
        print(f"   Total workflows: {workflows['total']}")
        
        # List tasks for this workflow
        print(f"\n3. Listing tasks for workflow...")
        tasks = await client.list_tasks(workflow_id=workflow_id)
        print(f"   Total tasks: {tasks['total']}")
        task_ids = []
        if tasks['tasks']:
            for task in tasks['tasks']:
                print(f"   - {task.id}: {task.name} ({task.status})")
                task_ids.append(task.id)
        
        # Test delete_task on first task if there are multiple
        if len(task_ids) > 1:
            task_to_delete = task_ids[0]
            print(f"\n4. Deleting task: {task_to_delete}")
            deleted = await client.delete_task(task_to_delete)
            print(f"   Task deleted: {deleted}")
            
            # Verify task deletion
            tasks_after = await client.list_tasks(workflow_id=workflow_id)
            print(f"   Remaining tasks: {tasks_after['total']}")
        
        # Test delete_workflow
        print(f"\n5. Deleting workflow: {workflow_id}")
        deleted = await client.delete_workflow(workflow_id)
        print(f"   Workflow deleted: {deleted}")
        
        # Verify workflow deletion
        print("\n6. Verifying deletion...")
        workflows_after = await client.list_workflows()
        print(f"   Total workflows after deletion: {workflows_after['total']}")
        
        tasks_after = await client.list_tasks(workflow_id=workflow_id)
        print(f"   Tasks for deleted workflow: {tasks_after['total']}")
        
        # Try to get the deleted workflow
        deleted_workflow = await client.get_workflow(workflow_id)
        print(f"   Deleted workflow retrieval: {'None' if deleted_workflow is None else 'Still exists!'}")
        
        # Test cleanup_old_data
        print("\n7. Testing cleanup_old_data...")
        deleted_count = await client.cleanup_old_data(days=0)  # Delete everything
        print(f"   Cleaned up {deleted_count} old items")
        
        print(f"\n✅ {backend_type.upper()} backend test completed!")

async def test_persistence_check():
    """Check what's persisted in each backend"""
    print("\n" + "="*60)
    print("Checking persistence across backends")
    print("="*60)
    
    for backend in ['redis', 'sql']:
        os.environ['GLEITZEIT_PERSISTENCE_TYPE'] = backend
        
        async with GleitzeitClient(mode="native") as client:
            print(f"\n{backend.upper()} Backend Status:")
            
            # Check existing data
            workflows = await client.list_workflows()
            tasks = await client.list_tasks()
            
            print(f"  Existing workflows: {workflows['total']}")
            print(f"  Existing tasks: {tasks['total']}")
            
            # Show a few samples
            if tasks['total'] > 0 and tasks['tasks']:
                print("  Sample tasks:")
                for task in tasks['tasks'][:3]:
                    print(f"    - {task.id} ({task.status})")

async def main():
    """Run all tests"""
    
    # First check what's already in each backend
    await test_persistence_check()
    
    # Test Redis backend
    await test_backend('redis')
    
    # Test SQL backend  
    await test_backend('sql')
    
    # Final check
    await test_persistence_check()
    
    print("\n" + "="*60)
    print("All backend tests completed!")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(main())