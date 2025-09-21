#!/usr/bin/env python3
"""
Log error messages for debugging.
"""

def main(message="Error occurred", task_results=None):
    """Log an error message."""
    print(message)
    return {"logged": True, "message": message}

if __name__ == "__main__":
    main()