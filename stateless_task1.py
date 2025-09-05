#!/usr/bin/env python3
"""
Stateless dependent workflow - Task 1: Generate data
Returns data that will be stored in the backend and accessible to other tasks
"""
import random
import json

# Generate some data
number = random.randint(10, 100)
words = ["gleitzeit", "workflow", "stateless"]

print(f"Task 1: Generated number {number}")
print(f"Task 1: Generated words: {words}")

# Return result as JSON - this will be stored in the backend
result = {
    "number": number,
    "words": words,
    "message": f"Generated number {number} with {len(words)} words"
}

# The last print statement becomes the task result
print(json.dumps(result))