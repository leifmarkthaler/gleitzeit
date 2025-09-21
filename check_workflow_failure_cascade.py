#!/usr/bin/env python
"""
Check workflow failure cascade logic.

This script checks if pending tasks are properly marked as failed
when their parent workflow fails.
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.persistence.unified_redis import UnifiedRedisAdapter
from gleitzeit.core.models import TaskStatus, WorkflowStatus


async def main():
    print("=== Workflow Failure Cascade Analysis ===\n")
    
    persistence = UnifiedRedisAdapter(redis_url="redis://localhost:6379/0")
    await persistence.initialize()
    
    # Get all tasks by status
    pending_tasks = await persistence.get_tasks_by_status(TaskStatus.PENDING.value)
    failed_tasks = await persistence.get_tasks_by_status(TaskStatus.FAILED.value)
    completed_tasks = await persistence.get_tasks_by_status(TaskStatus.COMPLETED.value)
    
    print(f"Current task counts:")
    print(f"  Pending: {len(pending_tasks)}")
    print(f"  Failed: {len(failed_tasks)}")
    print(f"  Completed: {len(completed_tasks)}")
    
    # Check each pending task's workflow status
    print(f"\nAnalyzing {len(pending_tasks)} pending tasks:")
    
    orphaned_tasks = []
    
    for task in pending_tasks:
        print(f"\n  Task: {task.id} ({task.name})")
        print(f"    Workflow: {task.workflow_id}")
        print(f"    Created: {task.created_at}")
        
        # Get workflow
        workflow = await persistence.get_workflow(task.workflow_id)
        if workflow:
            print(f"    Workflow Status: {workflow.status}")
            print(f"    Workflow Created: {workflow.created_at}")
            
            # Check if workflow failed or completed but task still pending
            if workflow.status in [WorkflowStatus.FAILED.value, WorkflowStatus.COMPLETED.value]:
                print(f"    ⚠️  ISSUE: Task is pending but workflow is {workflow.status}")
                orphaned_tasks.append({
                    'task': task,
                    'workflow': workflow,
                    'issue': f'Task pending but workflow {workflow.status}'
                })
            
            # Get all tasks in this workflow
            workflow_tasks = await persistence.get_tasks_by_workflow(task.workflow_id)
            task_statuses = {}
            for t in workflow_tasks:
                status = t.status
                task_statuses[status] = task_statuses.get(status, 0) + 1
            
            print(f"    Workflow task statuses: {task_statuses}")
            
            # Check if any task failed
            failed_count = task_statuses.get(TaskStatus.FAILED.value, 0)
            if failed_count > 0:
                print(f"    ⚠️  {failed_count} task(s) in workflow failed, but task still pending")
        else:
            print(f"    ❌ Workflow not found!")
            orphaned_tasks.append({
                'task': task,
                'workflow': None,
                'issue': 'Workflow not found'
            })
    
    # Summary
    print(f"\n=== Summary ===")
    if orphaned_tasks:
        print(f"❌ Found {len(orphaned_tasks)} orphaned/inconsistent tasks:")
        
        for item in orphaned_tasks:
            print(f"  - Task {item['task'].id}: {item['issue']}")
        
        print(f"\nThese tasks should be marked as failed due to workflow state.")
        
        # Fix them
        response = input("\nWould you like to fix these tasks? (y/n): ")
        if response.lower() == 'y':
            print("Fixing orphaned tasks...")
            
            for item in orphaned_tasks:
                task = item['task']
                print(f"  Marking task {task.id} as failed...")
                
                # Update task status
                task.status = TaskStatus.FAILED.value
                task.error_message = f"Workflow {task.workflow_id} failed or completed without this task"
                task.completed_at = datetime.utcnow()
                
                await persistence.save_task(task)
                
                # Create task result
                from gleitzeit.core.models import TaskResult
                task_result = TaskResult(
                    task_id=task.id,
                    workflow_id=task.workflow_id,
                    status=TaskStatus.FAILED,
                    error=task.error_message,
                    started_at=task.created_at,
                    completed_at=task.completed_at
                )
                
                await persistence.save_task_result(task_result)
            
            print(f"✅ Fixed {len(orphaned_tasks)} orphaned tasks")
    else:
        print("✅ No orphaned tasks found - cascade logic working correctly")
    
    await persistence.shutdown()


if __name__ == "__main__":
    asyncio.run(main())