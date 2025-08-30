#!/usr/bin/env python3
"""
Simple hello world script for testing
"""

import sys
import json

def main():
    """Main function"""
    args = sys.argv[1:]
    
    result = {
        "message": "Hello from Python!",
        "args": args,
        "python_version": sys.version.split()[0],
        "status": "success"
    }
    
    # Output as JSON for easy parsing
    print(json.dumps(result, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())