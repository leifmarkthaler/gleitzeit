#!/usr/bin/env python3
"""Verify the pipe deadlock fix by monitoring workers under load"""

import asyncio
import sys
from datetime import datetime
from gleitzeit.client.client import GleitzeitClient
import redis.asyncio as aioredis

async def submit_test_workflows(count=100):
    """Submit test workflows"""
    client = GleitzeitClient()
    
    print(f"🚀 Submitting {count} test workflows...")
    submitted = []
    
    for i in range(count):
        workflow = {
            "name": f"fix_verification_{i}",
            "tasks": [{
                "id": f"task_{i}",
                "type": "python",
                "protocol": "python/v1",
                "method": "execute",
                "code": f"result = {i} * 2"
            }]
        }
        try:
            response = await client.submit_workflow(workflow)
            wf_id = response.workflow_id if hasattr(response, 'workflow_id') else response
            submitted.append(wf_id)
            if (i + 1) % 10 == 0:
                print(f"  Submitted {i + 1}/{count}...")
        except Exception as e:
            print(f"  Error submitting workflow {i}: {e}")
    
    await client.close()
    print(f"✅ Submitted {len(submitted)} workflows")
    return submitted

async def monitor_worker_health(duration=120):
    """Monitor workflow_loader health"""
    redis = await aioredis.from_url("redis://localhost:6379")
    
    print(f"\n🔍 Monitoring workflow_loader health for {duration} seconds...")
    print("Time   | Heartbeat Age | Registry Status | FD Status")
    print("-" * 60)
    
    for i in range(duration):
        await asyncio.sleep(1)
        
        if i % 10 == 0:  # Check every 10 seconds
            # Check heartbeat
            metrics = await redis.hget("{shard:0}:worker:metrics:workflow_loader-async", "last_heartbeat")
            
            if metrics:
                last_hb = datetime.fromisoformat(metrics.decode())
                age = (datetime.utcnow() - last_hb).total_seconds()
                hb_status = f"{age:.1f}s"
            else:
                hb_status = "NO METRICS"
            
            # Check registry
            exists = await redis.exists("{shard:0}:worker:registry:workflow_loader:workflow_loader-async")
            reg_status = "✅ Present" if exists else "❌ Missing"
            
            # Check if still processing
            pending = 0
            for shard in range(16):
                count = await redis.llen(f"{{shard:{shard}}}:workflows:pending")
                pending += count
            
            print(f"{i:3d}s  | {hb_status:13s} | {reg_status:15s} | Pending: {pending}")
    
    await redis.aclose()
    print("\n✅ Monitoring complete")

async def main():
    """Run verification test"""
    print("=" * 70)
    print("WORKER LIFECYCLE FIX VERIFICATION TEST")
    print("=" * 70)
    print()
    
    # Submit workflows to generate load
    submitted = await submit_test_workflows(100)
    
    # Monitor worker health
    await monitor_worker_health(120)
    
    print()
    print("=" * 70)
    print("TEST RESULTS:")
    print(f"  Workflows submitted: {len(submitted)}")
    print(f"  Monitoring duration: 120 seconds")
    print(f"  Expected: Worker stays in registry throughout")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
