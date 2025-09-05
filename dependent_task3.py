#!/usr/bin/env python3
"""
Dependent workflow - Task 3: Calculate the sum of original and doubled
This depends on task 2's results
"""
import json
import os

# Get the result from task 2
previous_result = os.environ.get('TASK2_RESULT', '{"original": 42, "doubled": 84}')

try:
    data = json.loads(previous_result)
    original = data.get('original', 42)
    doubled = data.get('doubled', 84)
except:
    # Fallback for testing
    original = 42
    doubled = 84

total = original + doubled
print(f"Task 3: Sum of {original} + {doubled} = {total}")

# Output final result
result = {"original": original, "doubled": doubled, "sum": total}
print(json.dumps(result))