#!/usr/bin/env python3
"""
Stateless dependent workflow - Task 2: Process data from task 1
This task receives data through parameter substitution
"""
import json
import sys

# This script expects to receive the output from previous task as command line argument
# The workflow engine will substitute ${generate_data.result.output} with the output string
if len(sys.argv) > 1:
    try:
        # The output contains multiple lines, JSON is in the last line
        output_lines = sys.argv[1].strip().split('\n')
        json_line = output_lines[-1]  # Last line should be JSON
        previous_data = json.loads(json_line)
        print(f"Task 2: Received data from previous task: {previous_data}")
        
        number = previous_data.get('number', 0)
        words = previous_data.get('words', [])
    except:
        print("Task 2: Could not parse input data, using defaults")
        number = 50
        words = ["default"]
else:
    print("Task 2: No input data provided, using defaults")
    number = 50
    words = ["default"]

# Process the data
squared = number ** 2
word_count = len(words)
uppercase_words = [w.upper() for w in words]

print(f"Task 2: Original number: {number}, Squared: {squared}")
print(f"Task 2: Word count: {word_count}, Uppercase: {uppercase_words}")

# Return processed result
result = {
    "original": number,
    "squared": squared,
    "word_count": word_count,
    "uppercase_words": uppercase_words,
    "calculation": f"{number}^2 = {squared}"
}

print(json.dumps(result))