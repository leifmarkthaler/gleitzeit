#!/usr/bin/env python3
"""
Script that reads and reports environment variables
"""

import os
import json
import sys

def main():
    """Read environment variables"""
    
    # Read specific environment variables
    result = {
        "test_var": os.environ.get("TEST_VAR", "not_set"),
        "custom_setting": os.environ.get("CUSTOM_SETTING", "not_set"),
        "python_path": os.environ.get("PYTHONPATH", "not_set"),
        "user": os.environ.get("USER", "not_set"),
        "home": os.environ.get("HOME", "not_set"),
        "working_dir": os.getcwd()
    }
    
    # Output as JSON
    print(json.dumps(result, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())