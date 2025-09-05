#!/usr/bin/env python3
"""
Chained workflow - Task 1: Generate data and save to file
"""
import random
import json

# Generate some data
data = {
    "number": random.randint(10, 50),
    "words": ["hello", "world", "gleitzeit"],
    "timestamp": "2025-09-02"
}

print(f"Task 1: Generated data with number {data['number']}")

# Save to a temporary file that next task can read
with open("/tmp/workflow_data.json", "w") as f:
    json.dump(data, f)

print(f"Saved data to /tmp/workflow_data.json")
print(json.dumps(data))