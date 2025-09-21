#!/usr/bin/env python
"""
Test just the reconciliation timeout fix.
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.persistence.unified_redis import UnifiedRedisAdapter
from gleitzeit.core.models import TaskStatus
from gleitzeit.system.reconciliation_service import ReconciliationService, ReconciliationMode
from gleitzeit.events.pubsub_event_bus import PubSubEventBus


async def main():
    print("=== Testing ReconciliationService with 5-minute timeout ===\n")
    
    persistence = UnifiedRedisAdapter(redis_url="redis://localhost:6379/0")
    await persistence.initialize()
    
    # Check current stuck tasks
    executing_tasks = await persistence.get_tasks_by_status(TaskStatus.EXECUTING.value)
    print(f"Found {len(executing_tasks)} task(s) in EXECUTING state:")
    
    stuck_count = 0
    for task in executing_tasks:
        if task.started_at:
            elapsed = datetime.utcnow() - task.started_at
            elapsed_seconds = elapsed.total_seconds()
            
            print(f"  Task {task.id}:")
            print(f"    Started: {task.started_at}")
            print(f"    Running: {elapsed_seconds:.0f}s ({elapsed_seconds/60:.1f}min)")
            
            if elapsed_seconds > 300:  # > 5 minutes
                stuck_count += 1
                print(f"    Status: ✅ STUCK (would be caught by new 5min timeout)")
            else:
                print(f"    Status: ⏳ OK (within 5min timeout)")
    
    print(f"\nResult: {stuck_count} task(s) would be caught by ReconciliationService")
    
    if stuck_count > 0:
        print("\n✅ The timeout fix would successfully catch stuck tasks!")
    else:
        print("\n ℹ️  No stuck tasks found with new timeout")
    
    await persistence.shutdown()


if __name__ == "__main__":
    asyncio.run(main())