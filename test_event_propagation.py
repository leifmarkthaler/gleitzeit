#!/usr/bin/env python3
"""
Test event propagation from signal monitor to orchestrator.
"""

import asyncio
import httpx
import json
import redis.asyncio as redis

async def test_event_propagation():
    """Test that TASK_COMPLETED events are propagated correctly."""

    # Connect to Redis
    r = await redis.from_url("redis://localhost:6379/0")

    # First, let's check what's in the event stream
    print("Checking gleitzeit:events:stream:task:completed stream...")
    try:
        # Get last 10 messages from the stream
        messages = await r.xrevrange("gleitzeit:events:stream:task:completed", count=10)
        print(f"Found {len(messages)} messages in task:completed stream")
        for msg_id, data in messages:
            print(f"  Message {msg_id}: {data}")
    except Exception as e:
        print(f"Error reading stream: {e}")

    # Check consumer groups
    print("\nChecking consumer groups...")
    try:
        groups = await r.xinfo_groups("gleitzeit:events:stream:task:completed")
        for group in groups:
            print(f"  Group: {group['name']}, consumers: {group['consumers']}, pending: {group['pending']}")

            # Check pending messages for this group
            if group['pending'] > 0:
                pending = await r.xpending("gleitzeit:events:stream:task:completed", group['name'])
                print(f"    Pending summary: {pending}")
    except Exception as e:
        print(f"Error checking groups: {e}")

    # Now test with API
    async with httpx.AsyncClient(base_url="http://localhost:8003", follow_redirects=True) as client:
        # Submit a simple workflow first
        simple_workflow = {
            "tasks": [{
                "id": "simple_task",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "print('Hello'); result = 'done'"
                }
            }]
        }

        print("\nSubmitting simple workflow...")
        resp = await client.post("/workflows", json={"workflow": simple_workflow})
        result = resp.json()
        workflow_id = result.get("workflow_id")
        print(f"Simple workflow ID: {workflow_id}")

        # Wait and check status
        await asyncio.sleep(2)
        resp = await client.get(f"/workflows/{workflow_id}")
        workflow = resp.json()
        print(f"Simple workflow status: {workflow['status']}")

        # Check if task completed event was emitted
        print("\nChecking for new events after simple workflow...")
        messages_after = await r.xrevrange("gleitzeit:events:stream:task:completed", count=5)
        print(f"Found {len(messages_after)} recent messages")
        for msg_id, data in messages_after[:2]:  # Show first 2
            print(f"  {msg_id}: task_id={data.get(b'data', b'').decode()[:100]}")

    await r.close()

if __name__ == "__main__":
    asyncio.run(test_event_propagation())