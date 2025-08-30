#!/usr/bin/env python3
"""
Script that produces different types of output for testing output capture
"""

import sys
import json
import warnings

def main():
    """Produce various types of output"""
    
    # Standard output
    print("This is standard output")
    
    # Standard error
    sys.stderr.write("This is standard error\n")
    
    # Warning
    warnings.warn("This is a warning message")
    
    # JSON output (should be parsed)
    result = {
        "string": "hello",
        "number": 42,
        "float": 3.14,
        "boolean": True,
        "null": None,
        "array": [1, 2, 3],
        "object": {"nested": "value"}
    }
    
    # Print JSON (should be detected and parsed)
    print(json.dumps(result))
    
    return 0

if __name__ == "__main__":
    sys.exit(main())