#!/usr/bin/env python3
"""Test script for File Handler → Python Handler workflow"""

import json

# Simple computation
message = "Hello from File Handler → Python Handler workflow!"
result = {
    "greeting": message,
    "computation": 5 * 7,
    "status": "success"
}

print(json.dumps(result))