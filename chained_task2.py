#!/usr/bin/env python3
"""
Chained workflow - Task 2: Read data from file and transform it
"""
import json
import os

# Read data from the file created by task 1
try:
    with open("/tmp/workflow_data.json", "r") as f:
        data = json.load(f)
    print(f"Task 2: Successfully read data from previous task")
except Exception as e:
    print(f"Task 2: Could not read data file: {e}")
    data = {"number": 25, "words": ["fallback"]}

# Transform the data
transformed = {
    "original_number": data.get("number", 25),
    "squared": data.get("number", 25) ** 2,
    "word_count": len(data.get("words", [])),
    "uppercase_words": [w.upper() for w in data.get("words", [])]
}

print(f"Task 2: Original number: {transformed['original_number']}, Squared: {transformed['squared']}")
print(f"Task 2: Word count: {transformed['word_count']}, Words: {transformed['uppercase_words']}")

# Save transformed data for next task
with open("/tmp/workflow_transformed.json", "w") as f:
    json.dump(transformed, f)

print(json.dumps(transformed))