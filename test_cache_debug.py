#!/usr/bin/env python3
"""Debug SystemManager caching."""

import asyncio
import sys
sys.path.insert(0, 'src')

from gleitzeit.system.system_manager import SystemManager
from gleitzeit.persistence.factory import PersistenceFactory


async def test_cache():
    """Test caching behavior."""
    print("\n=== Testing Cache ===\n")
    
    # Get persistence
    persistence = await PersistenceFactory.create()
    print(f"Persistence ID: {id(persistence)}")
    
    # First call
    print("\n1. First get_or_create()...")
    sm1 = await SystemManager.get_or_create(persistence=persistence)
    print(f"   SM1: {sm1}")
    print(f"   Instance ID: {sm1.instance_id}")
    print(f"   Cache state: {SystemManager._instances}")
    
    # Second call with same persistence
    print("\n2. Second get_or_create()...")
    sm2 = await SystemManager.get_or_create(persistence=persistence)
    print(f"   SM2: {sm2}")
    print(f"   Instance ID: {sm2.instance_id if sm2 else 'None'}")
    print(f"   Same object? {sm1 is sm2}")
    print(f"   Cache state: {SystemManager._instances}")
    
    # Third call without persistence (should create new)
    print("\n3. Third get_or_create() without persistence...")
    sm3 = await SystemManager.get_or_create()
    print(f"   SM3: {sm3}")
    print(f"   Instance ID: {sm3.instance_id if sm3 else 'None'}")
    print(f"   Same as SM1? {sm1 is sm3}")
    print(f"   Cache state: {SystemManager._instances}")


if __name__ == "__main__":
    asyncio.run(test_cache())