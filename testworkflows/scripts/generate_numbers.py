#!/usr/bin/env python3
"""
Generate a list of random numbers.
"""
import random

# Generate 5 random numbers between 1 and 100
numbers = [random.randint(1, 100) for _ in range(5)]

result = {
    "numbers": numbers,
    "count": len(numbers)
}

print(f"Generated {len(numbers)} random numbers: {numbers}")