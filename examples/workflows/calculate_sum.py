#!/usr/bin/env python3
"""Calculate sum of numbers task."""

# Calculate sum of numbers
numbers = [10, 20, 30, 40, 50]
result = sum(numbers)
print(f"Sum of {numbers} = {result}")

# The output variable is what gets returned
output = {
    "sum": result, 
    "count": len(numbers), 
    "average": result / len(numbers)
}