#!/usr/bin/env python3
"""
Test different submission formats to understand FastAPI's expectation.
"""

import requests
import json
import uuid

base_url = "http://localhost:8000"

# Create a simple workflow
workflow = {
    "id": str(uuid.uuid4()),
    "name": "Test Workflow",
    "tasks": [
        {
            "id": str(uuid.uuid4()),
            "name": "Test Task",
            "protocol": "python/v1",
            "method": "execute",
            "params": {}
        }
    ]
}

print("Testing different submission formats:")
print("=" * 60)

# Test 1: Send with 'workflow' key (what we've been trying)
print("\n1. Sending with 'workflow' key:")
response = requests.post(
    f"{base_url}/workflows",
    json={"workflow": workflow}
)
print(f"   Status: {response.status_code}")
if response.status_code != 200:
    print(f"   Error: {response.text[:200]}")
else:
    print(f"   Success!")

# Test 2: Send with 'submission' key containing 'workflow'
print("\n2. Sending with 'submission' key containing 'workflow':")
response = requests.post(
    f"{base_url}/workflows",
    json={"submission": {"workflow": workflow}}
)
print(f"   Status: {response.status_code}")
if response.status_code != 200:
    print(f"   Error: {response.text[:200]}")
else:
    print(f"   Success!")

# Test 3: Send just the workflow directly
print("\n3. Sending workflow directly:")
response = requests.post(
    f"{base_url}/workflows",
    json=workflow
)
print(f"   Status: {response.status_code}")
if response.status_code != 200:
    print(f"   Error: {response.text[:200]}")
else:
    print(f"   Success!")

print("\n" + "=" * 60)