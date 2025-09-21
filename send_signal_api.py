#!/usr/bin/env python3
"""Send signal to the waiting workflow using the API directly."""

import asyncio
import httpx
import json
from datetime import datetime

async def main():
    workflow_id = "workflow-5d3e871b1d7e41a79f9678f43ad7cf4a"
    
    # Check status before signal
    print("=== Before sending signal ===")
    async with httpx.AsyncClient() as client:
        response = await client.get(f"http://localhost:8000/workflows/{workflow_id}")
        if response.status_code == 200:
            workflow = response.json()
            print(f"Workflow status: {workflow.get('status')}")
            for task in workflow.get('tasks', []):
                print(f"  - {task.get('name')}: {task.get('status')}")
        else:
            print(f"Error getting workflow: {response.status_code} - {response.text}")
            return
    
    # Send the signal via the API endpoint
    print("\n=== Sending signal 'test_approval' ===")
    signal_data = {
        "signal_name": "test_approval",
        "payload": {"approved": True}
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"http://localhost:8000/signals/workflows/{workflow_id}/send",
            json=signal_data
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"Signal result: {result}")
        else:
            print(f"Error sending signal: {response.status_code} - {response.text}")
            return
    
    # Wait for processing
    await asyncio.sleep(3)
    
    # Check status after signal
    print("\n=== After sending signal ===")
    async with httpx.AsyncClient() as client:
        response = await client.get(f"http://localhost:8000/workflows/{workflow_id}")
        if response.status_code == 200:
            workflow = response.json()
            print(f"Workflow status: {workflow.get('status')}")
            for task in workflow.get('tasks', []):
                print(f"  - {task.get('name')}: {task.get('status')}")
        else:
            print(f"Error getting workflow: {response.status_code} - {response.text}")

if __name__ == "__main__":
    asyncio.run(main())