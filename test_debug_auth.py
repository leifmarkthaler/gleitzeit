#!/usr/bin/env python3
"""
Debug auth issue with ScalableRedisAdapter
"""

import asyncio
import uuid
from src.gleitzeit.persistence.scalable_redis import ScalableRedisAdapter, PersistenceMode
from src.gleitzeit.persistence.factory_v2 import PersistenceFactory


async def test_session_storage():
    """Test basic set/get operations for session data."""
    print("\n=== Testing Session Storage ===")
    
    adapter = await PersistenceFactory.create(
        mode=PersistenceMode.SINGLE,
        config={"key_prefix": f"test_debug_{uuid.uuid4().hex[:8]}"}
    )
    
    try:
        # Test 1: Store and retrieve a set as the auth manager does
        key = "sessions:active"
        
        # Initially should return empty set
        result = await adapter.get(key)
        print(f"Initial get('{key}'): {result} (type: {type(result)})")
        assert result == set() or result is None
        
        # Store a set (as list)
        sessions = {"session1", "session2", "session3"}
        success = await adapter.set(key, sessions)
        print(f"Set {sessions}: {success}")
        
        # Retrieve and check type
        retrieved = await adapter.get(key)
        print(f"Retrieved: {retrieved} (type: {type(retrieved)})")
        
        # Should be a set
        if not isinstance(retrieved, set):
            print(f"ERROR: Expected set, got {type(retrieved)}")
            print(f"Value: {repr(retrieved)}")
        else:
            print("✅ Successfully retrieved as set")
            
        # Test adding to the set
        if isinstance(retrieved, set):
            retrieved.add("session4")
            await adapter.set(key, retrieved)
            
            final = await adapter.get(key)
            print(f"After adding session4: {final}")
            assert "session4" in final
            print("✅ Set operations work correctly")
    
    finally:
        await adapter.close()


async def main():
    await test_session_storage()


if __name__ == "__main__":
    asyncio.run(main())