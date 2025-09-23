#!/usr/bin/env python3
"""Test script for fixed subprocess pool workflow"""

import json

# Test computation
result = {
    "message": "Hello from FIXED subprocess pool!",
    "computation": 6 * 9,
    "pool_status": "working_perfectly",
    "timestamp": "2025-09-22"
}

print(json.dumps(result))