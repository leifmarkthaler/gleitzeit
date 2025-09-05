#!/usr/bin/env python3
"""
Dependent workflow - Task 2: Double the number from task 1
This would receive the result from task 1 through context/environment
"""
import json
import os
import sys

# In a real dependent workflow, the result would be passed via context
# For testing, we'll simulate receiving the previous task's result
# In production, this would come from the workflow engine's context

# Try to get the input from environment variable (if the engine sets it)
previous_result = os.environ.get('TASK1_RESULT', '{"number": 42}')

try:
    data = json.loads(previous_result)
    number = data.get('number', 42)
except:
    # Fallback for testing
    number = 42

doubled = number * 2
print(f"Task 2: Received {number}, doubled to {doubled}")

# Output result for next task
result = {"original": number, "doubled": doubled}
print(json.dumps(result))