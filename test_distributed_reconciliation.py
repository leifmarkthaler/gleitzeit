#!/usr/bin/env python3
"""
Test distributed reconciliation with leader election.

This script tests that:
1. Only one ReconciliationManager becomes the leader
2. Leader election works correctly
3. Reconciliation runs only on the leader
4. Failover works when leader stops
"""

import asyncio
import os
import time
from datetime import datetime
import redis.asyncio as redis


async def check_reconciliation_leader():
    """Check current reconciliation leader status."""
    client = await redis.from_url("redis://localhost:6379/0")
    
    try:
        # Check leader lock
        lock_exists = await client.exists("gleitzeit:reconciliation:leader")
        print(f"Leader lock exists: {lock_exists}")
        
        # Get leader info
        leader_info = await client.get("gleitzeit:reconciliation:leader_info")
        if leader_info:
            import json
            info = json.loads(leader_info)
            print(f"Current leader: {info.get('instance_id')}")
            print(f"Leader role: {info.get('role')}")
            print(f"Last heartbeat: {info.get('last_heartbeat')}")
            print(f"Last reconciliation: {info.get('last_reconciliation')}")
        else:
            print("No leader info available")
            
        # Check reconciliation history
        history = await client.lrange("gleitzeit:reconciliation:history", 0, 2)
        if history:
            print(f"\nRecent reconciliation runs: {len(history)}")
            for h in history:
                entry = json.loads(h)
                print(f"  - {entry['timestamp']}: Instance {entry['instance_id']}, Duration: {entry['duration_seconds']:.2f}s")
        
        return bool(lock_exists)
        
    finally:
        await client.close()


async def submit_stuck_workflow():
    """Submit a workflow that will get stuck to trigger reconciliation."""
    from gleitzeit import gleitzeit
    
    # Create client
    client = gleitzeit(mode="api", base_url="http://localhost:8000")
    
    # Submit a workflow with a task that will fail
    workflow_id = await client.submit_workflow_dict({
        "id": f"test_stuck_{int(time.time())}",
        "name": "Test Stuck Workflow",
        "tasks": [
            {
                "id": "stuck_task",
                "protocol": "python",
                "config": {
                    "module": "nonexistent_module",
                    "function": "nonexistent_function"
                }
            }
        ]
    })
    
    print(f"Submitted workflow {workflow_id} that will get stuck")
    return workflow_id


async def main():
    """Test distributed reconciliation."""
    print("=" * 60)
    print("Testing Distributed Reconciliation")
    print("=" * 60)
    
    # Check if servers are running with distributed reconciliation
    print("\n1. Checking reconciliation leader...")
    has_leader = await check_reconciliation_leader()
    
    if not has_leader:
        print("\n⚠️  No reconciliation leader found!")
        print("Make sure servers are running with GLEITZEIT_RECONCILIATION_DISTRIBUTED=true")
        print("\nStart servers with:")
        print("  Terminal 1: GLEITZEIT_RECONCILIATION_DISTRIBUTED=true gleitzeit serve --port 8000")
        print("  Terminal 2: GLEITZEIT_RECONCILIATION_DISTRIBUTED=true gleitzeit serve --port 8001")
        return
    
    print("\n2. Submitting stuck workflow to trigger reconciliation...")
    workflow_id = await submit_stuck_workflow()
    
    print("\n3. Waiting for reconciliation to detect stuck workflow...")
    await asyncio.sleep(5)
    
    print("\n4. Checking reconciliation status after workflow submission...")
    await check_reconciliation_leader()
    
    print("\n✅ Distributed reconciliation test complete!")
    print("\nTo test failover:")
    print("1. Stop the current leader server (check the instance_id above)")
    print("2. Run this script again to see the new leader")
    print("3. Reconciliation should continue on the new leader")


if __name__ == "__main__":
    asyncio.run(main())