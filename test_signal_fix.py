#!/usr/bin/env python3
"""Test signal workflow after fix."""

import asyncio
import json
import time
import requests
from pathlib import Path

# Read workflow file
workflow_file = Path("test_signal_simple.yaml")
with open(workflow_file, 'r') as f:
    workflow_yaml = f.read()

# Submit workflow
print("Submitting signal workflow...")

# Parse YAML to dict
import yaml
workflow_dict = yaml.safe_load(workflow_yaml)

response = requests.post(
    "http://localhost:8000/workflows/",
    json={"workflow": workflow_dict}
)

if response.status_code != 200:
    print(f"Failed to submit: {response.text}")
    exit(1)

data = response.json()
workflow_id = data.get("workflow_id")
print(f"Workflow submitted: {workflow_id}")

# Wait for workflow to start
time.sleep(2)

# Check status
print("\nChecking workflow status...")
response = requests.get(f"http://localhost:8000/workflows/{workflow_id}")
if response.status_code == 200:
    status = response.json()
    print(f"Status: {status.get('status')}")
    
    # Check task statuses
    tasks = status.get('tasks', [])
    if tasks:
        completed = sum(1 for t in tasks if t.get('status') == 'completed')
        print(f"Tasks: {completed}/{len(tasks)} completed")
        
        print("\nTask details:")
        for task in tasks:
            print(f"  - {task.get('name')}: {task.get('status')}")

# Send signal
print("\nSending signal 'test_approval'...")
signal_response = requests.post(
    f"http://localhost:8000/signals/workflows/{workflow_id}/send",
    json={
        "signal_name": "test_approval",
        "payload": {"approved": True}
    }
)

if signal_response.status_code == 200:
    print("Signal sent successfully!")
else:
    print(f"Failed to send signal: {signal_response.text}")

# Wait for workflow to complete
time.sleep(3)

# Check final status
print("\nChecking final status...")
response = requests.get(f"http://localhost:8000/workflows/{workflow_id}")
if response.status_code == 200:
    status = response.json()
    print(f"Status: {status.get('status')}")
    
    # Check task statuses
    tasks = status.get('tasks', [])
    if tasks:
        completed = sum(1 for t in tasks if t.get('status') == 'completed')
        print(f"Tasks: {completed}/{len(tasks)} completed")
        
        print("\nTask details:")
        for task in tasks:
            print(f"  - {task.get('name')}: {task.get('status')}")

print("\n✅ Test complete!")