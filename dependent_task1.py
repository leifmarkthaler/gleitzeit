#!/usr/bin/env python3
"""
Dependent workflow - Task 1: Generate a random number
"""
import random
import json

# Generate a random number between 1 and 100
number = random.randint(1, 100)
print(f"Task 1: Generated random number: {number}")

# Output the result as JSON for the next task to consume
result = {"number": number}
print(json.dumps(result))