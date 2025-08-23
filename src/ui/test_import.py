#!/usr/bin/env python
"""Test gleitzeit import"""

import sys
from pathlib import Path

print("Python path:")
for p in sys.path:
    print(f"  {p}")

print("\nTrying to import gleitzeit...")
try:
    from gleitzeit.client import GleitzeitClient
    print("✅ Successfully imported GleitzeitClient from installed package")
    print(f"   GleitzeitClient: {GleitzeitClient}")
    print(f"   Module location: {GleitzeitClient.__module__}")
except ImportError as e:
    print(f"❌ Failed to import: {e}")
    
print("\nTrying with local path...")
sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    from gleitzeit.client import GleitzeitClient
    print("✅ Successfully imported GleitzeitClient from local path")
    print(f"   GleitzeitClient: {GleitzeitClient}")
except ImportError as e:
    print(f"❌ Failed to import from local path: {e}")