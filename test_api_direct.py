#!/usr/bin/env python3
"""
Test API directly with curl to understand the format.
"""

import requests
import json
import uuid

# Create a simple workflow
workflow = {
    "id": str(uuid.uuid4()),
    "name": "Test Workflow",
    "tasks": [
        {
            "id": str(uuid.uuid4()),
            "name": "Test Task",
            "protocol": "python",
            "config": {
                "script": "/Users/leifmarkthaler/github/gleitzeit 0.0.6/test_tasks/calculate.py",
                "function": "add_numbers",
                "args": {"a": 5, "b": 3}
            }
        }
    ]
}

# Test different formats
print("Testing workflow submission formats...")
print("=" * 60)

# Format 1: Just workflow
print("\n1. Sending just workflow:")
response = requests.post(
    "http://localhost:8000/workflows",
    json={"workflow": workflow}
)
print(f"   Status: {response.status_code}")
if response.status_code != 200:
    print(f"   Error: {response.text}")
else:
    print(f"   Success: {response.json()}")

# Format 2: With request wrapper
print("\n2. Sending with request wrapper:")
response = requests.post(
    "http://localhost:8000/workflows",
    json={"request": {"workflow": workflow}}
)
print(f"   Status: {response.status_code}")
if response.status_code != 200:
    print(f"   Error: {response.text}")
else:
    print(f"   Success: {response.json()}")

print("\n" + "=" * 60)