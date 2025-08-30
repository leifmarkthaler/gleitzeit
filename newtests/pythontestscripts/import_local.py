#!/usr/bin/env python3
"""
Script that imports from a local module to test module dependency handling
"""

import json
import sys
import os

# Add current directory to path to import local module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import local module
from math_utils import add_numbers, multiply_numbers

def main():
    """Main function using local imports"""
    a, b = 10, 5
    
    result = {
        "addition": add_numbers(a, b),
        "multiplication": multiply_numbers(a, b),
        "message": "Successfully imported and used local module"
    }
    
    print(json.dumps(result, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())