#!/usr/bin/env python
"""
Debug why a task remains pending.

This checks:
1. Task details and dependencies
2. Workflow status and progression
3. Event bus and orchestrator status
4. Provider availability
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.persistence.unified_redis import UnifiedRedisAdapter
from gleitzeit.core.models import TaskStatus
from gleitzeit.providers.pooling_adapter import PoolingAdapter
from gleitzeit.providers.provider_pool_manager import ProviderPoolManager


async def main():
    print("=== Debugging Pending Task ===\n")
    
    persistence = UnifiedRedisAdapter(redis_url="redis://localhost:6379/0")
    await persistence.initialize()
    
    # Get the pending task
    pending_tasks = await persistence.get_tasks_by_status(TaskStatus.PENDING.value)
    
    if not pending_tasks:
        print("No pending tasks found.")
        await persistence.shutdown()
        return
    
    task = pending_tasks[0]  # task-e4b68b90
    
    print(f"Task Details:")
    print(f"  ID: {task.id}")
    print(f"  Name: {task.name}")
    print(f"  Protocol: {task.protocol}")
    print(f"  Method: {task.method}")
    print(f"  Workflow: {task.workflow_id}")
    print(f"  Created: {task.created_at}")
    print(f"  Dependencies: {task.dependencies}")
    print(f"  Status: {task.status}")
    
    # Check workflow
    workflow = await persistence.get_workflow(task.workflow_id)
    if workflow:
        print(f"\nWorkflow Details:")
        print(f"  ID: {workflow.id}")
        print(f"  Name: {workflow.name}")
        print(f"  Status: {workflow.status}")
        print(f"  Created: {workflow.created_at}")
        print(f"  Total tasks: {len(workflow.tasks)}")
        
        # Check all tasks in workflow
        workflow_tasks = await persistence.get_tasks_by_workflow(task.workflow_id)
        print(f"  Tasks in workflow:")
        for t in workflow_tasks:
            print(f"    - {t.id} ({t.name}): {t.status}")
    
    # Check if task should be ready to execute
    print(f"\nTask Analysis:")
    
    # Check dependencies
    if task.dependencies:
        print(f"  Has {len(task.dependencies)} dependencies - checking if they're completed...")
        all_deps_completed = True
        for dep_id in task.dependencies:
            dep_task = await persistence.get_task(dep_id)
            if dep_task:
                print(f"    - {dep_id}: {dep_task.status}")
                if dep_task.status not in [TaskStatus.COMPLETED.value, TaskStatus.FAILED.value]:
                    all_deps_completed = False
            else:
                print(f"    - {dep_id}: NOT FOUND")
                all_deps_completed = False
        
        if all_deps_completed:
            print("  ✅ All dependencies satisfied")
        else:
            print("  ❌ Dependencies not satisfied - task correctly pending")
    else:
        print("  ✅ No dependencies - task should be ready to execute")
    
    # Check provider availability
    print(f"\nProvider Availability:")
    try:
        # Create a temporary pool manager to check availability
        pool_manager = ProviderPoolManager(persistence)
        await pool_manager.initialize()
        
        # Check if protocol is available
        available, reason = await pool_manager.validate_provider_availability(task.protocol)
        if available:
            print(f"  ✅ Protocol {task.protocol} is available")
        else:
            print(f"  ❌ Protocol {task.protocol} not available: {reason}")
    except Exception as e:
        print(f"  ❌ Error checking provider availability: {e}")
    
    # Check system components
    print(f"\nSystem Status:")
    
    # Check if TaskOrchestrator is running by looking for running tasks
    executing_tasks = await persistence.get_tasks_by_status(TaskStatus.EXECUTING.value)
    print(f"  Currently executing tasks: {len(executing_tasks)}")
    
    # Check recent task activity
    completed_tasks = await persistence.get_tasks_by_status(TaskStatus.COMPLETED.value)
    if completed_tasks:
        recent_completed = [t for t in completed_tasks if t.completed_at and 
                          (datetime.utcnow() - t.completed_at).total_seconds() < 300]  # Last 5 minutes
        print(f"  Tasks completed in last 5 minutes: {len(recent_completed)}")
        if recent_completed:
            print("  ✅ System appears to be processing tasks")
        else:
            print("  ⚠️  No recent task completions - system may be stuck")
    
    # Check event bus activity (if we can)
    print(f"\nRecommendations:")
    
    if not task.dependencies:
        if workflow and workflow.status == "pending":
            print("  1. Task has no dependencies and workflow is pending")
            print("  2. Task should be picked up by orchestrator")
            print("  3. Check if TaskOrchestrator is running and processing WORKFLOW_SUBMITTED events")
            print("  4. May need to manually trigger workflow progression")
        else:
            print("  1. Check TaskOrchestrator status")
            print("  2. Check event bus connectivity")
            print("  3. Verify provider registration")
    
    await persistence.shutdown()


if __name__ == "__main__":
    asyncio.run(main())