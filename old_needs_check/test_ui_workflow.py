#!/usr/bin/env python
import requests
import yaml

# Simple example from UI
workflow_yaml = """name: Simple Python Task
tasks:
  - id: hello
    type: python
    params:
      code: |
        print("Hello from Gleitzeit!")
        result = {"message": "Success"}
"""

print("Submitting UI example workflow...")
response = requests.post(
    "http://localhost:8004/api/workflows/submit",
    headers={"Content-Type": "application/x-yaml"},
    data=workflow_yaml
)

print(f"Status: {response.status_code}")
print(f"Response: {response.text}")
