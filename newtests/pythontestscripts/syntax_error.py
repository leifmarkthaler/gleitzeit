#!/usr/bin/env python3
"""
Script with syntax error for validation testing
"""

import sys

def main():
    """This function has a syntax error"""
    print("This line is fine")
    if True
        print("Missing colon above")  # Syntax error on line above
    return 0

if __name__ == "__main__":
    sys.exit(main())