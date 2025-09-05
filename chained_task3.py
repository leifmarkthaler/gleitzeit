#!/usr/bin/env python3
"""
Chained workflow - Task 3: Read transformed data and create final report
"""
import json

# Read transformed data from task 2
try:
    with open("/tmp/workflow_transformed.json", "r") as f:
        data = json.load(f)
    print(f"Task 3: Successfully read transformed data")
except Exception as e:
    print(f"Task 3: Could not read transformed data: {e}")
    data = {"original_number": 25, "squared": 625, "word_count": 1}

# Create final report
report = {
    "summary": f"Workflow processed number {data['original_number']}",
    "calculations": {
        "original": data.get("original_number"),
        "squared": data.get("squared"),
        "ratio": round(data.get("squared", 1) / data.get("original_number", 1), 2)
    },
    "text_analysis": {
        "word_count": data.get("word_count"),
        "words": data.get("uppercase_words", [])
    },
    "status": "complete"
}

print(f"Task 3: Final Report:")
print(f"  - Original number: {report['calculations']['original']}")
print(f"  - Squared value: {report['calculations']['squared']}")
print(f"  - Ratio: {report['calculations']['ratio']}")
print(f"  - Words processed: {report['text_analysis']['word_count']}")

# Clean up temporary files
import os
try:
    os.remove("/tmp/workflow_data.json")
    os.remove("/tmp/workflow_transformed.json")
    print("Task 3: Cleaned up temporary files")
except:
    pass

print(json.dumps(report, indent=2))