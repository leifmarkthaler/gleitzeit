#!/usr/bin/env python3
"""
Simple script without sys.exit for thread testing
"""

import json

def main():
    """Main function that doesn't call sys.exit"""
    result = {
        "message": "Hello from thread!",
        "status": "success"
    }
    
    print(json.dumps(result, indent=2))
    return 0

if __name__ == "__main__":
    main()