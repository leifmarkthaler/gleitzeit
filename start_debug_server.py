#!/usr/bin/env python3
"""Debug server startup with detailed error tracking"""

import sys
import os
import traceback
sys.path.insert(0, 'src')

def debug_os_issue():
    """Try to reproduce the os issue"""
    try:
        print(f"os before import: {os}")
        from gleitzeit.api.main import app
        print(f"os after import: {os}")
        
        # Test calling os.getenv directly
        auth_enabled = os.getenv("GLEITZEIT_AUTH_ENABLED", "false")
        print(f"os.getenv works: {auth_enabled}")
        
        # Try the lifespan function
        import uvicorn
        print("Starting uvicorn...")
        uvicorn.run(app, host="127.0.0.1", port=8000)
        
    except Exception as e:
        print(f"ERROR: {e}")
        print("\nFull traceback:")
        traceback.print_exc()

if __name__ == "__main__":
    debug_os_issue()