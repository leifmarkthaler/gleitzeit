#!/usr/bin/env python
"""
Analyze why pending tasks aren't being processed and suggest requeue mechanism.
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.persistence.unified_redis import UnifiedRedisAdapter
from gleitzeit.core.models import TaskStatus


async def main():
    print("=== Pending Task Analysis ===\n")
    
    persistence = UnifiedRedisAdapter(redis_url="redis://localhost:6379/0")
    await persistence.initialize()
    
    # Get all task statuses
    pending = await persistence.get_tasks_by_status(TaskStatus.PENDING.value)
    queued = await persistence.get_tasks_by_status("queued")
    
    print(f"Current state:")
    print(f"  PENDING tasks: {len(pending)}")
    print(f"  QUEUED tasks: {len(queued)}")
    
    # Check if pending tasks should be queued
    print(f"\nPending task analysis:")
    
    should_be_queued = []
    for task in pending:
        print(f"\n  Task {task.id}:")
        print(f"    Name: {task.name}")
        print(f"    Created: {task.created_at}")
        print(f"    Dependencies: {task.dependencies}")
        
        # Calculate age
        if task.created_at:
            age = datetime.utcnow() - task.created_at
            age_minutes = age.total_seconds() / 60
            print(f"    Age: {age_minutes:.1f} minutes")
            
            # Should be requeued if old and has no dependencies
            if age_minutes > 5 and not task.dependencies:
                print(f"    ⚠️  Should be requeued - no dependencies, old task")
                should_be_queued.append(task)
            elif task.dependencies:
                print(f"    ✅ Has dependencies - may be waiting")
            else:
                print(f"    ✅ Recent task - may be processing")
    
    print(f"\n=== Issues Identified ===")
    
    if should_be_queued:
        print(f"❌ {len(should_be_queued)} task(s) should be requeued:")
        for task in should_be_queued:
            print(f"  - {task.id} ({task.name})")
        
        print(f"\n=== Missing Requeue Mechanism ===")
        print("The ReconciliationService should include pending task requeue logic:")
        print("1. Find PENDING tasks older than X minutes with no dependencies")
        print("2. Emit TASK_READY events to trigger processing") 
        print("3. Or transition them to QUEUED status")
        
        # Offer to fix
        fix_now = input("\nWould you like me to create a fix for this? (y/n): ").strip().lower()
        if fix_now == 'y':
            print("\nCreating pending task requeue functionality...")
            
            from gleitzeit.events.pubsub_event_bus import PubSubEventBus
            from gleitzeit.core.events import EventType, GleitzeitEvent
            
            event_bus = PubSubEventBus(persistence)
            await event_bus.initialize()
            
            for task in should_be_queued:
                print(f"  Requeuing task {task.id}...")
                
                # Emit TASK_READY event
                await event_bus.emit(GleitzeitEvent(
                    event_type=EventType.TASK_READY,
                    data={"task_id": task.id, "workflow_id": task.workflow_id}
                ))
                
                # Also emit WORKFLOW_SUBMITTED for the workflow
                await event_bus.emit(GleitzeitEvent(
                    event_type=EventType.WORKFLOW_SUBMITTED,
                    data={"workflow_id": task.workflow_id}
                ))
            
            print(f"✅ Emitted requeue events for {len(should_be_queued)} tasks")
            
            # Wait and check
            print("Waiting 10 seconds to see if tasks get processed...")
            await asyncio.sleep(10)
            
            new_pending = await persistence.get_tasks_by_status(TaskStatus.PENDING.value)
            new_executing = await persistence.get_tasks_by_status(TaskStatus.EXECUTING.value)
            
            print(f"\nResults after requeue:")
            print(f"  PENDING: {len(pending)} → {len(new_pending)}")
            print(f"  EXECUTING: 0 → {len(new_executing)}")
            
            if len(new_executing) > 0:
                print("✅ Tasks were picked up!")
            elif len(new_pending) < len(pending):
                print("✅ Some progress made!")
            else:
                print("❌ No change - system may not be processing events")
        
    else:
        print("✅ No stuck pending tasks found")
    
    # Create permanent fix recommendation
    print(f"\n=== Permanent Fix Needed ===")
    print("ReconciliationService should include this method:")
    print("""
async def _reconcile_pending_tasks(self) -> Dict[str, int]:
    '''Reconcile stuck pending tasks.'''
    stats = {'tasks_requeued': 0}
    
    try:
        pending_tasks = await self.persistence.get_tasks_by_status('pending')
        cutoff_time = datetime.utcnow() - timedelta(minutes=5)
        
        for task in pending_tasks:
            # Requeue old tasks with no dependencies
            if (task.created_at < cutoff_time and 
                not task.dependencies):
                
                await self.event_bus.emit(GleitzeitEvent(
                    event_type=EventType.TASK_READY,
                    data={'task_id': task.id, 'workflow_id': task.workflow_id}
                ))
                stats['tasks_requeued'] += 1
    
    except Exception as e:
        logger.error(f'Error reconciling pending tasks: {e}')
    
    return stats
    """)
    
    await persistence.shutdown()


if __name__ == "__main__":
    asyncio.run(main())