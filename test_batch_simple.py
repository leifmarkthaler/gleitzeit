#!/usr/bin/env python3
"""Simple test for batch endpoint"""

import requests
import json

# Simple workflow that works
workflow = {
    "name": "test-batch",
    "tasks": [
        {
            "name": "simple_task",
            "protocol": "python/v1",
            "method": "python/execute",
            "params": {
                "file": "test_tasks/bulk_task1.py"
            }
        }
    ]
}

# Test batch endpoint
batch_data = [
    {"workflow": workflow},
    {"workflow": workflow},
    {"workflow": workflow}
]

response = requests.post(
    "http://localhost:8000/workflows/batch",
    json=batch_data,
    timeout=10
)

print(f"Status: {response.status_code}")
print(f"Response: {json.dumps(response.json(), indent=2)}")