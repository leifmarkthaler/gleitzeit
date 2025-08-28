#!/usr/bin/env python3
"""Test script for log output streaming"""
import sys
import time
import json

print("Starting test script...")
print("This is line 2 on stdout")
time.sleep(0.5)

print("Progress: 25%", file=sys.stderr)
time.sleep(0.5)

print("Processing data...")
time.sleep(0.5)

print("Progress: 50%", file=sys.stderr)
time.sleep(0.5)

print("Almost done...")
time.sleep(0.5)

print("Progress: 75%", file=sys.stderr)
time.sleep(0.5)

# Output some JSON data
result = {
    "status": "success",
    "items_processed": 100,
    "errors": 0
}
print(json.dumps(result))

print("Progress: 100%", file=sys.stderr)
print("Test script completed!")