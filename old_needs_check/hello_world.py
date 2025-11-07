#!/usr/bin/env python3
"""Simple test script for Python handler validation"""

import json

# Simple computation
result = {
    "message": "Hello from unified file operations!",
    "status": "success",
    "computation": 2 + 2
}

print(json.dumps(result))