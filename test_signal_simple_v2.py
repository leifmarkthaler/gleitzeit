#!/usr/bin/env python3
"""
Simple test for signal workflow without events - using port 8003.
"""

import asyncio
import httpx
import json

async def test_signal():
    """Test basic signal workflow."""
    async with httpx.AsyncClient(base_url="http://localhost:8003", follow_redirects=True) as client:
        # Submit a workflow that waits for a signal
        wait_workflow = {
            "tasks": [{
                "id": "wait_for_signal",
                "protocol": "signal/v1",
                "method": "signal/wait",
                "params": {
                    "signal": "test_signal",
                    "timeout": 60
                }
            }]
        }

        print("Submitting wait workflow...")
        resp = await client.post("/workflows", json={"workflow": wait_workflow})
        print(f"Response status: {resp.status_code}")
        wait_result = resp.json()
        print(f"Response: {wait_result}")

        if "workflow_id" not in wait_result:
            print(f"Error: {wait_result}")
            return

        wait_id = wait_result["workflow_id"]
        print(f"Wait workflow ID: {wait_id}")

        # Wait a bit for the workflow to start
        await asyncio.sleep(2)

        # Check workflow status
        resp = await client.get(f"/workflows/{wait_id}")
        workflow = resp.json()
        print(f"Workflow status: {workflow['status']}")

        # Now send the signal to this specific workflow
        signal_workflow = {
            "tasks": [{
                "id": "send_signal",
                "protocol": "signal/v1",
                "method": "signal/send",
                "params": {
                    "signal": "test_signal",
                    "target_workflow": wait_id,
                    "payload": {"message": "Hello from signal!"}
                }
            }]
        }

        print(f"\nSending signal to workflow {wait_id}...")
        resp = await client.post("/workflows", json={"workflow": signal_workflow})
        signal_result = resp.json()
        signal_id = signal_result["workflow_id"]
        print(f"Signal workflow ID: {signal_id}")

        # Wait for signal to be processed
        await asyncio.sleep(3)

        # Check signal workflow status
        resp = await client.get(f"/workflows/{signal_id}")
        signal_workflow_obj = resp.json()
        print(f"Signal workflow status: {signal_workflow_obj['status']}")

        # Check wait workflow status again
        resp = await client.get(f"/workflows/{wait_id}")
        workflow = resp.json()
        print(f"Wait workflow final status: {workflow['status']}")

        if workflow['status'] == 'completed':
            print("✅ Signal workflow completed successfully!")
        else:
            print(f"❌ Workflow still in {workflow['status']} state")
            # Get task details
            resp = await client.get(f"/workflows/{wait_id}/tasks")
            tasks = resp.json()
            for task in tasks:
                print(f"  Task {task['id']}: {task['status']}")

if __name__ == "__main__":
    asyncio.run(test_signal())