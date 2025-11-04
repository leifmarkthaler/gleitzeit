#!/usr/bin/env python3
"""
WebSocket Monitoring Example - Real-Time Event Streaming

This example demonstrates how to monitor workflows in real-time using
WebSocket connections instead of polling.
"""

import asyncio
from gleitzeit.client import GleitzeitClient


async def main():
    """WebSocket-based workflow monitoring"""

    async with GleitzeitClient('http://localhost:8000') as client:
        print("✓ Connected to Gleitzeit API")

        # Define workflow
        workflow = {
            'name': 'WebSocket Monitoring Demo',
            'tasks': [
                {
                    'id': 'step1',
                    'type': 'python',
                    'params': {
                        'code': '''
import time
print("Step 1: Starting...")
time.sleep(2)
result = {"step": 1, "status": "completed"}
print("Step 1: Done!")
'''
                    }
                },
                {
                    'id': 'step2',
                    'type': 'python',
                    'depends_on': ['step1'],
                    'params': {
                        'code': '''
import time
print("Step 2: Starting...")
time.sleep(2)
result = {"step": 2, "status": "completed"}
print("Step 2: Done!")
'''
                    }
                }
            ]
        }

        # Submit workflow
        response = await client.submit_workflow(workflow)
        print(f"✓ Submitted workflow: {response.workflow_id}")

        # Create event to signal completion
        done = asyncio.Event()

        # Define callbacks
        def on_complete(event):
            print(f"✓ Workflow completed!")
            done.set()

        def on_failure(event):
            print(f"✗ Workflow failed: {event}")
            done.set()

        # Monitor with WebSocket (non-blocking)
        print("🔌 Monitoring via WebSocket...")
        await client.wait_for_workflow_async(
            response.workflow_id,
            on_complete=on_complete,
            on_failure=on_failure,
            timeout=60
        )

        # Wait for workflow to complete
        await done.wait()

        # Get final status
        status = await client.get_workflow_status(response.workflow_id)
        print(f"\n📊 Final Status: {status.status}")


if __name__ == "__main__":
    print("=" * 60)
    print("WebSocket Monitoring Example")
    print("=" * 60)
    asyncio.run(main())
