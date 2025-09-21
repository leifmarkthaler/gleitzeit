#!/usr/bin/env python3
"""
Simple calculation task for testing.
"""

def add_numbers(a, b):
    """Add two numbers."""
    result = a + b
    print(f"Adding {a} + {b} = {result}")
    return result

def multiply_numbers(a, b):
    """Multiply two numbers."""
    result = a * b
    print(f"Multiplying {a} * {b} = {result}")
    return result

def process_data(data):
    """Process some data."""
    print(f"Processing data: {data}")
    
    # Do some calculations
    total = sum(data)
    average = total / len(data) if data else 0
    
    result = {
        "total": total,
        "average": average,
        "count": len(data),
        "max": max(data) if data else None,
        "min": min(data) if data else None
    }
    
    print(f"Result: {result}")
    return result

# For direct execution testing
if __name__ == "__main__":
    # Test functions
    print("Testing add_numbers(5, 3):", add_numbers(5, 3))
    print("Testing multiply_numbers(4, 7):", multiply_numbers(4, 7))
    print("Testing process_data([1, 2, 3, 4, 5]):", process_data([1, 2, 3, 4, 5]))