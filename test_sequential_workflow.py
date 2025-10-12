#!/usr/bin/env python
import requests
import yaml

# Sequential example from UI
workflow_yaml = """name: Sequential Tasks
tasks:
  - id: task1
    type: python
    params:
      code: |
        print("Task 1 starting")
        result = {"data": "from task 1"}

  - id: task2
    type: python
    depends_on: [task1]
    params:
      code: |
        print("Task 2 starting")
        result = {"data": "from task 2"}

  - id: task3
    type: python
    depends_on: [task2]
    params:
      code: |
        print("Task 3 starting")
        result = {"result": "All tasks completed"}
"""

print("Submitting sequential tasks workflow...")
response = requests.post(
    "http://localhost:8004/api/workflows/submit",
    headers={"Content-Type": "application/x-yaml"},
    data=workflow_yaml
)

print(f"Status: {response.status_code}")
print(f"Response: {response.text}")
