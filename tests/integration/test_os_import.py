#!/usr/bin/env python3
"""Test script to isolate the os import issue"""

import sys
sys.path.insert(0, 'src')

try:
    import os
    print(f"os module imported successfully: {os}")
    print(f"os.getenv works: {os.getenv('HOME')}")
    
    # Try importing the main app
    from gleitzeit.api.main import app
    print("main.py imported successfully")
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()