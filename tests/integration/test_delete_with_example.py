#!/usr/bin/env python3
"""
Test delete methods with a working workflow from examples
"""

import asyncio
from gleitzeit.client import GleitzeitClient
import os

async def main():
    """Test delete methods with real workflow"""
    
    # Use memory backend for testing
    os.environ['GLEITZEIT_PERSISTENCE_TYPE'] = 'memory'
    
    async with GleitzeitClient(mode="native") as client:
        print("Testing delete methods with example workflow...")
        
        # Run an example workflow
        workflow_file = "examples/simple_python_workflow.yaml"
        
        print(f"\n1. Running workflow from {workflow_file}...")
        result = await client.run_workflow(workflow_file)
        workflow_id = result['workflow_id']
        print(f"   Workflow ID: {workflow_id}")
        print(f"   Status: {result['status']}")
        
        # List workflows
        print("\n2. Listing workflows before deletion...")
        workflows = await client.list_workflows()
        print(f"   Total workflows: {workflows['total']}")
        if workflows['total'] > 0 and 'workflows' in workflows:
            for wf in workflows['workflows'][:3]:  # Show first 3
                print(f"   - {wf.get('id', 'N/A')}: {wf.get('name', 'N/A')}")
        
        # List tasks for this workflow
        print(f"\n3. Listing tasks for workflow {workflow_id}...")
        tasks = await client.list_tasks(workflow_id=workflow_id)
        print(f"   Total tasks: {tasks['total']}")
        task_ids = []
        if tasks['tasks']:
            for task in tasks['tasks']:
                print(f"   - {task.id}: {task.name} ({task.status})")
                task_ids.append(task.id)
        
        # Test delete_task on first task
        if task_ids:
            task_to_delete = task_ids[0]
            print(f"\n4. Deleting task: {task_to_delete}")
            deleted = await client.delete_task(task_to_delete)
            print(f"   Task deleted: {deleted}")
            
            # Verify task deletion
            tasks_after = await client.list_tasks(workflow_id=workflow_id)
            print(f"   Remaining tasks for workflow: {tasks_after['total']}")
        
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
        print(f"   Deleted workflow retrieval: {deleted_workflow}")
        
        print("\n✅ Delete methods tested successfully!")

if __name__ == "__main__":
    asyncio.run(main())