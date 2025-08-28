#!/usr/bin/env python3
"""Test the Advanced Queue Control API endpoints"""
import asyncio
import aiohttp
import json

API_BASE = "http://localhost:8000"

async def test_queue_endpoints():
    """Test the advanced queue control endpoints"""
    async with aiohttp.ClientSession() as session:
        
        print("Testing Advanced Queue Control Endpoints")
        print("=" * 50)
        
        # 1. Test Queue Listing
        print("\n1. Queue Management:")
        
        # List all queues
        async with session.get(f"{API_BASE}/queues") as resp:
            if resp.status == 200:
                queues = await resp.json()
                print(f"   ✓ Found {queues.get('total_queues', 0)} queues")
                
                # Test details for each queue
                for queue_name in queues.get("queues", {}).keys():
                    async with session.get(f"{API_BASE}/queues/{queue_name}") as detail_resp:
                        if detail_resp.status == 200:
                            details = await detail_resp.json()
                            print(f"   ✓ Queue '{queue_name}': {details.get('size', 0)} tasks")
                        else:
                            print(f"   ✗ Failed to get queue details: {detail_resp.status}")
            else:
                print(f"   ✗ Failed to list queues: {resp.status}")
        
        # 2. Test Queue Pause/Resume
        print("\n2. Queue Control (Pause/Resume):")
        
        # Test pause
        async with session.post(f"{API_BASE}/queues/default/pause") as resp:
            if resp.status == 200:
                result = await resp.json()
                print(f"   ✓ Pause endpoint: {result.get('status')}")
                if result.get('status') == 'not_implemented':
                    print(f"     (Feature planned for future release)")
            else:
                print(f"   ✗ Pause failed: {resp.status}")
        
        # Test resume
        async with session.post(f"{API_BASE}/queues/default/resume") as resp:
            if resp.status == 200:
                result = await resp.json()
                print(f"   ✓ Resume endpoint: {result.get('status')}")
                if result.get('status') == 'not_implemented':
                    print(f"     (Feature planned for future release)")
            else:
                print(f"   ✗ Resume failed: {resp.status}")
        
        # 3. Test Queue Clear
        print("\n3. Queue Clear:")
        
        # First, submit some test tasks
        task_ids = []
        for i in range(3):
            task_data = {
                "id": f"queue-test-{i}",
                "name": f"Queue Test Task {i}",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": f"import time; time.sleep(100)"  # Long-running to stay in queue
                }
            }
            async with session.post(f"{API_BASE}/tasks", json=task_data) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    task_ids.append(result.get('task_id'))
        
        if task_ids:
            print(f"   ✓ Created {len(task_ids)} test tasks")
            
            # Wait a bit for tasks to be queued
            await asyncio.sleep(1)
            
            # Clear the queue
            async with session.post(f"{API_BASE}/queues/default/clear") as resp:
                if resp.status == 200:
                    result = await resp.json()
                    print(f"   ✓ Clear queue: {result.get('tasks_cleared', 0)} tasks cleared")
                else:
                    error = await resp.text()
                    print(f"   ✗ Clear failed: {error}")
        
        # 4. Test Queue Configuration
        print("\n4. Queue Configuration:")
        
        config_updates = {
            "max_size": 1000,
            "max_concurrent": 10,
            "priority_mode": "strict"
        }
        
        async with session.put(
            f"{API_BASE}/queues/default/config",
            params=config_updates
        ) as resp:
            if resp.status == 200:
                result = await resp.json()
                print(f"   ✓ Config update endpoint: {result.get('status')}")
                if result.get('status') == 'not_implemented':
                    print(f"     (Feature planned for future release)")
                    print(f"     Requested updates: {result.get('requested_updates')}")
            else:
                print(f"   ✗ Config update failed: {resp.status}")
        
        # 5. Test non-existent queue
        print("\n5. Error Handling:")
        
        async with session.get(f"{API_BASE}/queues/non_existent_queue") as resp:
            if resp.status == 404:
                print(f"   ✓ Correctly returns 404 for non-existent queue")
            else:
                print(f"   ✗ Unexpected status for non-existent queue: {resp.status}")
        
        print("\n" + "=" * 50)
        print("Queue Control Testing Complete!")

if __name__ == "__main__":
    asyncio.run(test_queue_endpoints())