#!/usr/bin/env python3
"""Test signal workflow functionality."""

import asyncio
import json
import time
import requests
from pathlib import Path

async def main():
    server_url = "http://localhost:8000"
    
    # Read and submit the workflow
    workflow_file = Path("test_signal_simple.yaml")
    
    print("=" * 60)
    print("SIGNAL WORKFLOW TEST")
    print("=" * 60)
    
    # Submit workflow via API
    print(f"\n1. Submitting workflow from {workflow_file}")
    
    with open(workflow_file, 'r') as f:
        workflow_yaml = f.read()
    
    submit_response = requests.post(
        f"{server_url}/workflows/submit",
        json={"workflow_yaml": workflow_yaml}
    )
    
    if submit_response.status_code != 200:
        print(f"❌ Failed to submit workflow: {submit_response.text}")
        return
    
    workflow_data = submit_response.json()
    workflow_id = workflow_data.get("workflow_id")
    print(f"✅ Workflow submitted: {workflow_id}")
    
    # Wait a moment for workflow to start
    await asyncio.sleep(2)
    
    # Check workflow status
    print("\n2. Checking workflow status...")
    status_response = requests.get(f"{server_url}/workflows/{workflow_id}")
    
    if status_response.status_code == 200:
        status = status_response.json()
        print(f"   Status: {status.get('status')}")
        print(f"   Current phase: Waiting for signal 'test_approval'")
    
    # Check for waiting signals
    print("\n3. Checking waiting signals...")
    waiting_response = requests.get(f"{server_url}/signals/workflows/{workflow_id}/waiting")
    
    if waiting_response.status_code == 200:
        waiting = waiting_response.json()
        print(f"   Waiting signals: {waiting.get('waiting_count', 0)}")
        for signal in waiting.get('waiting_signals', []):
            print(f"   - {signal['signal']} (task: {signal['task_id']})")
    
    # Send the signal
    print("\n4. Sending approval signal...")
    signal_response = requests.post(
        f"{server_url}/signals/workflows/{workflow_id}/send",
        json={
            "signal_name": "test_approval",
            "payload": {"approved": True, "message": "Test approval granted"}
        }
    )
    
    if signal_response.status_code == 200:
        print("✅ Signal sent successfully!")
    else:
        print(f"❌ Failed to send signal: {signal_response.text}")
        return
    
    # Wait for workflow to complete
    print("\n5. Waiting for workflow to complete...")
    await asyncio.sleep(3)
    
    # Check final status
    final_response = requests.get(f"{server_url}/workflows/{workflow_id}")
    if final_response.status_code == 200:
        final_status = final_response.json()
        print(f"   Final status: {final_status.get('status')}")
        
        # Get task results
        tasks = final_status.get('tasks', {})
        for task_name, task_data in tasks.items():
            print(f"\n   Task '{task_name}':")
            print(f"     Status: {task_data.get('status')}")
            if task_data.get('result'):
                print(f"     Result: {task_data.get('result')}")
    
    print("\n" + "=" * 60)
    print("Signal workflow test completed!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())