#!/usr/bin/env python
"""
Simple test task for workflow execution.
"""

def main():
    """Simple task that prints and returns a result."""
    print("Task executing successfully!")
    result = {
        "status": "success",
        "message": "Python task completed",
        "value": 42
    }
    print(f"Returning: {result}")
    return result

if __name__ == "__main__":
    result = main()
    print(f"Final result: {result}")