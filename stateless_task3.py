#!/usr/bin/env python3
"""
Stateless dependent workflow - Task 3: Combine results from multiple tasks
This task receives data from both task 1 and task 2
"""
import json
import sys

# Parse command line arguments
# Arg 1: data from task 1
# Arg 2: data from task 2
task1_data = {}
task2_data = {}

if len(sys.argv) > 1:
    try:
        # Extract JSON from task1's output (last line)
        output_lines = sys.argv[1].strip().split('\n')
        json_line = output_lines[-1]
        task1_data = json.loads(json_line)
        print(f"Task 3: Received task1 data: {task1_data}")
    except Exception as e:
        print(f"Task 3: Could not parse task1 data: {e}")

if len(sys.argv) > 2:
    try:
        # Extract JSON from task2's output (last line)
        output_lines = sys.argv[2].strip().split('\n')
        json_line = output_lines[-1]
        task2_data = json.loads(json_line)
        print(f"Task 3: Received task2 data: {task2_data}")
    except Exception as e:
        print(f"Task 3: Could not parse task2 data: {e}")

# Create final summary combining both results
original_number = task1_data.get('number', 0)
squared = task2_data.get('squared', 0)
original_words = task1_data.get('words', [])
uppercase_words = task2_data.get('uppercase_words', [])

print(f"Task 3: Creating final summary")
print(f"  Original: {original_number} -> Squared: {squared}")
print(f"  Words: {original_words} -> {uppercase_words}")

# Calculate some final metrics
if original_number > 0:
    ratio = round(squared / original_number, 2)
else:
    ratio = 0

result = {
    "summary": "Workflow completed successfully",
    "original_number": original_number,
    "squared_value": squared,
    "square_ratio": ratio,
    "original_words": original_words,
    "processed_words": uppercase_words,
    "total_operations": 3
}

print(json.dumps(result, indent=2))