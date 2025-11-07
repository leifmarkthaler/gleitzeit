#!/usr/bin/env python
import requests
import json
import time

# Submit workflow
workflow_id = f"test-python-{int(time.time())}"
payload = {
    "workflow": {
        "workflow_id": workflow_id,
        "tasks": [
            {
                "id": "calc",
                "name": "Simple Calculation",
                "type": "python",
                "params": {
                    "code": "result = 42 * 2\nprint(f'Result: {result}')"
                }
            }
        ]
    },
    "workflow_id": workflow_id
}

print("Submitting workflow...")
response = requests.post(
    "http://localhost:8000/workflows/submit",
    json=payload
)

print(f"Status: {response.status_code}")
print(f"Response: {response.text}")

# Wait a moment
time.sleep(2)

# Check workflow status
print(f"\nChecking workflow {workflow_id}...")
status_response = requests.get(f"http://localhost:8000/workflows/{workflow_id}")
print(f"Status: {status_response.status_code}")
if status_response.status_code == 200:
    print(json.dumps(status_response.json(), indent=2))
else:
    print(f"Response: {status_response.text}")
