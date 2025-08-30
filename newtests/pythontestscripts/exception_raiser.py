#!/usr/bin/env python3
"""
Script that raises an exception for testing exception handling
"""

import sys

def risky_operation():
    """Function that raises an exception"""
    raise RuntimeError("This is a test exception!")

def main():
    """Main function"""
    print("Starting risky operation...")
    
    try:
        risky_operation()
    except Exception as e:
        print(f"Caught exception: {e}", file=sys.stderr)
        # Re-raise to test unhandled exception behavior
        raise
    
    return 0

if __name__ == "__main__":
    sys.exit(main())