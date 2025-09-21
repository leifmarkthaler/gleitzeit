#!/usr/bin/env python3
"""
Debug auth issue - check what's returned
"""

import asyncio
import uuid
from src.gleitzeit.persistence.scalable_redis import ScalableRedisAdapter, PersistenceMode
from src.gleitzeit.persistence.factory_v2 import PersistenceFactory


async def test_exact_auth_pattern():
    """Test the exact pattern used by auth manager."""
    print("\n=== Testing Exact Auth Pattern ===")
    
    adapter = await PersistenceFactory.create(
        mode=PersistenceMode.SINGLE,
        config={"key_prefix": f"test_exact_{uuid.uuid4().hex[:8]}"}
    )
    
    try:
        # This is exactly what the auth manager does
        global_sessions_key = "sessions:active"
        
        # First get (should be None or empty set)
        active_sessions = await adapter.get(global_sessions_key) or set()
        print(f"Step 1 - Get result: {repr(active_sessions)} (type: {type(active_sessions)})")
        
        # Check if it's a set
        if not isinstance(active_sessions, set):
            print(f"ERROR: Not a set! It's a {type(active_sessions)}")
            # Try to convert
            if isinstance(active_sessions, list):
                active_sessions = set(active_sessions)
                print(f"Converted list to set: {active_sessions}")
            elif isinstance(active_sessions, str):
                print(f"Got string value: '{active_sessions}'")
                print("This is the problem - returning string instead of None or set")
        
        # Try to add (this is where it fails)
        try:
            active_sessions.add("test-session-id")
            print(f"Step 2 - After add: {active_sessions}")
        except AttributeError as e:
            print(f"ERROR adding to sessions: {e}")
            print(f"Value is: {repr(active_sessions)}")
            return
        
        # Save it back
        await adapter.set(global_sessions_key, list(active_sessions))
        print(f"Step 3 - Saved as list: {list(active_sessions)}")
        
        # Get it again
        retrieved = await adapter.get(global_sessions_key)
        print(f"Step 4 - Retrieved: {retrieved} (type: {type(retrieved)})")
        
        print("\n✅ Test completed successfully!")
        
    finally:
        await adapter.close()


async def main():
    await test_exact_auth_pattern()


if __name__ == "__main__":
    asyncio.run(main())