#!/usr/bin/env python
"""
Diagnose and fix stuck tasks in Gleitzeit.

This script identifies tasks stuck in EXECUTING state and provides options to:
1. Diagnose why they're stuck
2. Fix them by marking as failed or retrying
3. Understand why reconciliation isn't working
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.persistence.unified_redis import UnifiedRedisAdapter
from gleitzeit.core.models import TaskStatus
from gleitzeit.system.reconciliation_service import ReconciliationService, ReconciliationMode
from gleitzeit.events.pubsub_event_bus import PubSubEventBus


async def main():
    """Main diagnostic function."""
    print("=== Gleitzeit Stuck Task Diagnostic ===\n")
    
    # Initialize persistence
    persistence = UnifiedRedisAdapter(redis_url="redis://localhost:6379/0")
    await persistence.initialize()
    
    # Check for stuck tasks
    print("1. Checking for tasks in EXECUTING state...")
    executing_tasks = await persistence.get_tasks_by_status(TaskStatus.EXECUTING.value)
    
    if not executing_tasks:
        print("   No tasks currently in EXECUTING state.")
    else:
        print(f"   Found {len(executing_tasks)} task(s) in EXECUTING state:\n")
        
        for task in executing_tasks:
            print(f"   Task ID: {task.id}")
            print(f"   Name: {task.name}")
            print(f"   Workflow: {task.workflow_id}")
            print(f"   Started at: {task.started_at}")
            
            if task.started_at:
                elapsed = datetime.utcnow() - task.started_at
                print(f"   Running for: {elapsed}")
                
                # Check if it's stuck (> 5 minutes is suspicious)
                if elapsed > timedelta(minutes=5):
                    print(f"   ⚠️  STUCK: Task has been running for {elapsed}")
            else:
                print("   ⚠️  No start time recorded!")
            
            print(f"   Timeout: {task.timeout or 'Not set'}")
            print(f"   Attempts: {task.attempt_count}")
            print()
    
    # Check reconciliation service
    print("\n2. Checking ReconciliationService configuration...")
    
    # Check if reconciliation would catch these
    reconciliation_timeout = 3600  # Default from system_manager.py
    print(f"   ReconciliationService timeout: {reconciliation_timeout} seconds (1 hour)")
    print(f"   Mode: STARTUP (runs once) or PERIODIC (every 5 minutes)")
    
    stuck_count = 0
    for task in executing_tasks:
        if task.started_at:
            elapsed = datetime.utcnow() - task.started_at
            if elapsed.total_seconds() > reconciliation_timeout:
                stuck_count += 1
                print(f"   ⚠️  Task {task.id} should have been caught by reconciliation!")
    
    if stuck_count > 0:
        print(f"\n   🔴 {stuck_count} task(s) should have been cleaned up by reconciliation!")
        print("   Possible issues:")
        print("   - ReconciliationService not running")
        print("   - Service started after tasks got stuck")
        print("   - update_task method not working properly")
    
    # Run manual reconciliation
    if executing_tasks:
        print("\n3. Running manual reconciliation automatically...")
        print("\n   Running reconciliation...")
        
        # Initialize event bus
        event_bus = PubSubEventBus(persistence)
        await event_bus.initialize()
        
        # Create and run reconciliation service
        reconciliation = ReconciliationService(
            persistence=persistence,
            event_bus=event_bus,
            task_timeout=300,  # 5 minutes for testing
            mode=ReconciliationMode.MANUAL
        )
        
        stats = await reconciliation._reconcile_stuck_tasks()
        print(f"\n   Reconciliation results:")
        for key, value in stats.items():
            if value > 0:
                print(f"   - {key}: {value}")
        
        # Check if tasks are still stuck
        still_executing = await persistence.get_tasks_by_status(TaskStatus.EXECUTING.value)
        if still_executing:
            print(f"\n   ⚠️  {len(still_executing)} task(s) still in EXECUTING state")
            print("   This might indicate:")
            print("   - Tasks genuinely still running")
            print("   - Issue with persistence.update_task()")
            print("   - Tasks being re-marked as executing")
        else:
            print("\n   ✅ All stuck tasks have been reconciled!")
    
    # Check workflow status
    print("\n4. Checking associated workflows...")
    workflow_ids = set(task.workflow_id for task in executing_tasks if task.workflow_id)
    
    for workflow_id in workflow_ids:
        workflow = await persistence.get_workflow(workflow_id)
        if workflow:
            print(f"   Workflow {workflow_id}:")
            print(f"   - Status: {workflow.status}")
            print(f"   - Total tasks: {len(workflow.tasks)}")
            
            # Count task statuses
            task_statuses = {}
            for task in workflow.tasks:
                status = task.status if hasattr(task, 'status') else task.get('status', 'unknown')
                task_statuses[status] = task_statuses.get(status, 0) + 1
            
            for status, count in task_statuses.items():
                print(f"   - {status}: {count}")
    
    # Cleanup
    await persistence.shutdown()
    print("\n=== Diagnostic Complete ===")


if __name__ == "__main__":
    asyncio.run(main())