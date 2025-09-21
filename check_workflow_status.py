#!/usr/bin/env python3
"""Check status of workflows in Redis."""

import redis
import json

# Connect to Redis
r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

# Find all workflow keys
workflow_keys = []
for key in r.scan_iter("gleitzeit:workflow:workflow-*"):
    if "events" not in key and "signals" not in key:
        workflow_keys.append(key)

# Sort by key (which contains the workflow ID)
workflow_keys.sort()

# Check the last 10 workflows
print("=== Recent Workflows ===\n")
for key in workflow_keys[-10:]:
    workflow_id = key.replace("gleitzeit:workflow:", "")
    data = r.hgetall(key)

    status = data.get('status', 'unknown')
    name = data.get('name', 'unnamed')
    created_at = data.get('created_at', 'unknown')
    completed_at = data.get('completed_at', 'not completed')

    print(f"ID: {workflow_id[:20]}...")
    print(f"Name: {name}")
    print(f"Status: {status}")
    print(f"Created: {created_at}")
    if status == 'completed':
        print(f"Completed: {completed_at}")

    # Check for tasks
    if 'tasks' in data:
        tasks = json.loads(data['tasks'])
        print(f"Tasks: {len(tasks)}")
        for task in tasks:
            print(f"  - {task.get('id', 'unknown')[:20]}... ({task.get('status', 'unknown')})")

    print("-" * 40)