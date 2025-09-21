#!/usr/bin/env python
"""
Test the new pending task requeue mechanism.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.persistence.unified_redis import UnifiedRedisAdapter
from gleitzeit.core.models import TaskStatus
from gleitzeit.system.reconciliation_service import ReconciliationService, ReconciliationMode
from gleitzeit.events.pubsub_event_bus import PubSubEventBus


async def main():
    print("=== Testing Requeue Mechanism ===\n")
    
    persistence = UnifiedRedisAdapter(redis_url="redis://localhost:6379/0")
    await persistence.initialize()
    
    event_bus = PubSubEventBus(persistence)
    await event_bus.initialize()
    
    # Create reconciliation service with new functionality
    reconciliation = ReconciliationService(
        persistence=persistence,
        event_bus=event_bus,
        task_timeout=300,  # 5 minutes
        mode=ReconciliationMode.MANUAL
    )
    
    # Check before reconciliation
    print("1. Before reconciliation:")
    pending_before = await persistence.get_tasks_by_status(TaskStatus.PENDING.value)
    executing_before = await persistence.get_tasks_by_status(TaskStatus.EXECUTING.value)
    
    print(f"   PENDING: {len(pending_before)}")
    print(f"   EXECUTING: {len(executing_before)}")
    
    if pending_before:
        for task in pending_before:
            age = None
            if task.created_at:
                from datetime import datetime
                age = (datetime.utcnow() - task.created_at).total_seconds() / 60
            
            print(f"     - {task.id} ({task.name}): age={age:.1f}min, deps={len(task.dependencies or [])}")
    
    # Run reconciliation with new pending task logic
    print(f"\n2. Running reconciliation with requeue mechanism...")
    stats = await reconciliation.reconcile()
    
    print(f"   Reconciliation results:")
    for key, value in stats.items():
        if value > 0 or key.startswith('pending'):
            print(f"     {key}: {value}")
    
    # Check after reconciliation
    print(f"\n3. After reconciliation:")
    pending_after = await persistence.get_tasks_by_status(TaskStatus.PENDING.value)
    executing_after = await persistence.get_tasks_by_status(TaskStatus.EXECUTING.value)
    
    print(f"   PENDING: {len(pending_before)} → {len(pending_after)}")
    print(f"   EXECUTING: {len(executing_before)} → {len(executing_after)}")
    
    # Wait a bit for potential processing
    print(f"\n4. Waiting 10 seconds for task processing...")
    await asyncio.sleep(10)
    
    # Final check
    pending_final = await persistence.get_tasks_by_status(TaskStatus.PENDING.value)
    executing_final = await persistence.get_tasks_by_status(TaskStatus.EXECUTING.value)
    completed_final = await persistence.get_tasks_by_status(TaskStatus.COMPLETED.value)
    
    print(f"\n5. Final status:")
    print(f"   PENDING: {len(pending_after)} → {len(pending_final)}")
    print(f"   EXECUTING: {len(executing_after)} → {len(executing_final)}")
    print(f"   COMPLETED: → {len(completed_final)}")
    
    # Summary
    print(f"\n=== Results ===")
    
    requeued = stats.get('pending_tasks_requeued', 0)
    if requeued > 0:
        print(f"✅ {requeued} task(s) were requeued by reconciliation")
        
        if len(executing_final) > len(executing_before):
            print(f"✅ Tasks were picked up for execution!")
        elif len(pending_final) < len(pending_before):
            print(f"✅ Some tasks were processed!")
        else:
            print(f"⚠️  Tasks were requeued but not yet processed")
    else:
        print(f"ℹ️  No stuck pending tasks found to requeue")
    
    # Show current stuck tasks if any
    if pending_final:
        print(f"\n📋 Remaining pending tasks:")
        for task in pending_final:
            age = None
            if task.created_at:
                age = (datetime.utcnow() - task.created_at).total_seconds() / 60
            
            deps = len(task.dependencies or [])
            print(f"   - {task.id}: age={age:.1f}min, deps={deps}")
            
            if age and age > 5 and deps == 0:
                print(f"     ⚠️  This task should have been requeued!")
    
    await persistence.shutdown()
    print(f"\n🎉 Requeue mechanism test complete!")


if __name__ == "__main__":
    asyncio.run(main())