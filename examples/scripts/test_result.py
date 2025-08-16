#!/usr/bin/env python3
"""
Test script that produces a result for testing.
"""

import json

# Do some calculation
numbers = [1, 2, 3, 4, 5]
total = sum(numbers)
average = total / len(numbers)

result = {
    "numbers": numbers,
    "sum": total,
    "average": average,
    "message": "Calculation complete"
}

# Output as JSON for parsing
print(json.dumps(result))