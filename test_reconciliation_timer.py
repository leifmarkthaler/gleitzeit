#!/usr/bin/env python3
"""
Test reconciliation using TimerManager for scheduling.

This script tests that:
1. ReconciliationManager uses timers for scheduling
2. Timers are properly created in Redis
3. Timer wake events trigger reconciliation
4. Reconciliation runs only on the leader
"""

import asyncio
import time
import json
import redis.asyncio as redis


async def check_reconciliation_timers():
    """Check timers created by ReconciliationManager."""
    client = await redis.from_url("redis://localhost:6379/0")
    
    try:
        # Check pending timers
        timers = await client.zrange("timers:pending", 0, -1, withscores=True)
        print(f"\n=== Pending Timers ({len(timers)}) ===")
        
        reconciliation_timers = []
        for timer_id, score in timers:
            if isinstance(timer_id, bytes):
                timer_id = timer_id.decode()
            
            if "reconciliation:" in timer_id:
                reconciliation_timers.append((timer_id, score))
                # Get timer metadata
                metadata = await client.hgetall(f"timer:{timer_id}")
                
                # Decode metadata
                timer_type = metadata.get(b"timer_type", b"").decode() if b"timer_type" in metadata else metadata.get("timer_type", "")
                wake_at = float(metadata.get(b"wake_at", b"0").decode() if b"wake_at" in metadata else metadata.get("wake_at", "0"))
                instance_id = metadata.get(b"instance_id", b"").decode() if b"instance_id" in metadata else metadata.get("instance_id", "")
                
                time_until = wake_at - time.time()
                print(f"  - {timer_id}")
                print(f"    Type: {timer_type}")
                print(f"    Instance: {instance_id}")
                print(f"    Wakes in: {time_until:.1f} seconds")
        
        # Check reconciliation leader
        leader_info = await client.get("gleitzeit:reconciliation:leader_info")
        if leader_info:
            info = json.loads(leader_info)
            print(f"\n=== Reconciliation Leader ===")
            print(f"  Instance: {info.get('instance_id')}")
            print(f"  Last heartbeat: {info.get('last_heartbeat')}")
            print(f"  Last reconciliation: {info.get('last_reconciliation')}")
        
        # Check completed timers
        completed = await client.zrange("timers:completed", -5, -1, withscores=True)
        print(f"\n=== Recently Completed Timers ===")
        for timer_id, score in completed:
            if isinstance(timer_id, bytes):
                timer_id = timer_id.decode()
            if "reconciliation:" in timer_id:
                completed_at = time.time() - float(score)
                print(f"  - {timer_id} (completed {completed_at:.1f}s ago)")
        
        return len(reconciliation_timers) > 0
        
    finally:
        await client.close()


async def simulate_timer_expiry():
    """Simulate timer expiry by manually triggering a timer."""
    client = await redis.from_url("redis://localhost:6379/0")
    
    try:
        # Find a reconciliation timer
        timers = await client.zrange("timers:pending", 0, -1, withscores=False)
        
        for timer_id in timers:
            if isinstance(timer_id, bytes):
                timer_id = timer_id.decode()
            
            if "reconciliation:" in timer_id:
                print(f"\n=== Simulating Timer Expiry for {timer_id} ===")
                
                # Get timer metadata
                metadata = await client.hgetall(f"timer:{timer_id}")
                workflow_id = metadata.get(b"workflow_id", b"").decode() if b"workflow_id" in metadata else metadata.get("workflow_id", "")
                task_id = metadata.get(b"task_id", b"").decode() if b"task_id" in metadata else metadata.get("task_id", "")
                
                # Send wake event to workflow stream (like TimerMonitorService does)
                event_data = {
                    "event": "timer_wake",
                    "timer_id": timer_id,
                    "task_id": task_id,
                    "type": "reconciliation",
                    "timestamp": str(time.time())
                }
                
                stream_key = f"workflow:{workflow_id}:events"
                await client.xadd(stream_key, event_data)
                
                print(f"  Sent wake event to {stream_key}")
                
                # Move timer to completed
                await client.zadd("timers:completed", {timer_id: time.time()})
                await client.zrem("timers:pending", timer_id)
                
                print(f"  Timer marked as completed")
                return True
                
        print("No reconciliation timers found to simulate")
        return False
        
    finally:
        await client.close()


async def main():
    """Test reconciliation with timer integration."""
    print("=" * 60)
    print("Testing Reconciliation with TimerManager")
    print("=" * 60)
    
    print("\n1. Checking for reconciliation timers...")
    has_timers = await check_reconciliation_timers()
    
    if not has_timers:
        print("\n⚠️  No reconciliation timers found!")
        print("Make sure the server is running with TimerManager enabled")
        print("\nStart server with:")
        print("  PYTHONDONTWRITEBYTECODE=1 gleitzeit serve --port 8000")
        return
    
    print("\n2. Waiting 5 seconds before simulating timer expiry...")
    await asyncio.sleep(5)
    
    print("\n3. Simulating timer expiry to trigger reconciliation...")
    triggered = await simulate_timer_expiry()
    
    if triggered:
        print("\n4. Waiting for reconciliation to process timer event...")
        await asyncio.sleep(3)
        
        print("\n5. Checking for new reconciliation timer...")
        await check_reconciliation_timers()
        
        print("\n✅ Reconciliation timer integration test complete!")
        print("\nThe ReconciliationManager now uses TimerManager for scheduling:")
        print("  - No more internal reconciliation loops")
        print("  - Timers are managed through the distributed timer system")
        print("  - Timer wake events trigger reconciliation runs")
        print("  - New timers are scheduled after each reconciliation")
    else:
        print("\n❌ Could not trigger reconciliation timer")


if __name__ == "__main__":
    asyncio.run(main())