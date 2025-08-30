#!/usr/bin/env python3
"""
Script that intentionally produces an error for testing error handling
"""

import sys

def main():
    """Main function that raises an error"""
    print("Starting script...", file=sys.stderr)
    
    # Write to stderr
    sys.stderr.write("ERROR: Something went wrong!\n")
    sys.stderr.write("This is a test error\n")
    
    # Exit with error code
    return 1

if __name__ == "__main__":
    sys.exit(main())