#!/usr/bin/env python3
"""Test the new API endpoints"""
import asyncio
import aiohttp
import json

API_BASE = "http://localhost:8000"

async def test_endpoints():
    """Test various new API endpoints"""
    async with aiohttp.ClientSession() as session:
        
        print("Testing New API Endpoints")
        print("=" * 50)
        
        # 1. Test system statistics
        print("\n1. System Statistics:")
        async with session.get(f"{API_BASE}/statistics/system") as resp:
            if resp.status == 200:
                stats = await resp.json()
                print(f"   ✓ Uptime: {stats.get('uptime_seconds', 0):.1f} seconds")
                print(f"   ✓ Task stats: {stats.get('tasks', {})}")
                print(f"   ✓ Queue stats: {len(stats.get('queues', {}).get('queues', {}))} queues")
            else:
                print(f"   ✗ Failed: {resp.status}")
        
        # 2. Test task statistics
        print("\n2. Task Statistics:")
        async with session.get(f"{API_BASE}/statistics/tasks") as resp:
            if resp.status == 200:
                stats = await resp.json()
                print(f"   ✓ Total tasks: {stats.get('total', 0)}")
                print(f"   ✓ Pending: {stats.get('pending', 0)}")
                print(f"   ✓ Completed: {stats.get('completed', 0)}")
                print(f"   ✓ Failed: {stats.get('failed', 0)}")
            else:
                print(f"   ✗ Failed: {resp.status}")
        
        # 3. Test queue listing
        print("\n3. Queue Management:")
        async with session.get(f"{API_BASE}/queues") as resp:
            if resp.status == 200:
                queues = await resp.json()
                print(f"   ✓ Total queues: {queues.get('total_queues', 0)}")
                for queue_name, queue_data in queues.get('queues', {}).items():
                    print(f"   ✓ Queue '{queue_name}': {queue_data.get('size', 0)} tasks")
            else:
                print(f"   ✗ Failed: {resp.status}")
        
        # 4. Submit a test task to test control endpoints
        print("\n4. Task Control Endpoints:")
        
        # Submit a long-running task
        task_data = {
            "id": "test-task-control",
            "name": "Test Control Task",
            "protocol": "python/v1",
            "method": "python/execute",
            "params": {
                "code": "import time; print('Starting...'); time.sleep(10); print('Done!')"
            }
        }
        
        print("   Submitting test task...")
        async with session.post(f"{API_BASE}/tasks", json=task_data) as resp:
            if resp.status == 200:
                result = await resp.json()
                task_id = result.get('task_id')
                print(f"   ✓ Task submitted: {task_id}")
                
                # Wait a bit for task to start
                await asyncio.sleep(1)
                
                # Try to cancel the task
                print("   Testing cancel endpoint...")
                async with session.post(f"{API_BASE}/tasks/{task_id}/cancel") as cancel_resp:
                    if cancel_resp.status == 200:
                        print(f"   ✓ Task cancelled successfully")
                    else:
                        error = await cancel_resp.text()
                        print(f"   ✗ Cancel failed: {error}")
                
                # Try to retry the cancelled task
                print("   Testing retry endpoint...")
                await asyncio.sleep(1)
                async with session.post(f"{API_BASE}/tasks/{task_id}/retry") as retry_resp:
                    if retry_resp.status == 200:
                        retry_result = await retry_resp.json()
                        print(f"   ✓ Task retried: new ID = {retry_result.get('new_task_id')}")
                    else:
                        error = await retry_resp.text()
                        print(f"   ✗ Retry failed: {error}")
            else:
                print(f"   ✗ Failed to submit task: {resp.status}")
        
        # 5. Test workflow control (would need an actual workflow)
        print("\n5. Workflow Control Endpoints:")
        print("   (Skipping - would need an active workflow)")
        
        # 6. Test cleanup endpoint
        print("\n6. Data Management:")
        async with session.delete(f"{API_BASE}/cleanup?days=90") as resp:
            if resp.status == 200:
                result = await resp.json()
                print(f"   ✓ Cleanup executed: {result.get('items_deleted', 0)} items deleted")
            else:
                print(f"   ✗ Failed: {resp.status}")
        
        # 7. Test health check
        print("\n7. Health Check:")
        async with session.get(f"{API_BASE}/health") as resp:
            if resp.status == 200:
                health = await resp.json()
                print(f"   ✓ Status: {health.get('status')}")
                print(f"   ✓ Timestamp: {health.get('timestamp')}")
            else:
                print(f"   ✗ Failed: {resp.status}")
        
        print("\n" + "=" * 50)
        print("API Endpoint Testing Complete!")

if __name__ == "__main__":
    asyncio.run(test_endpoints())