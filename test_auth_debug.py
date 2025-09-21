#!/usr/bin/env python3
"""
Debug auth mode detection issue.
"""

import asyncio
import os
import sys
sys.path.insert(0, 'src')

from gleitzeit.persistence.factory import PersistenceFactory
from gleitzeit.system.system_manager import SystemManager
from gleitzeit.auth.auth_manager import AuthManager

async def test_auth_initialization():
    """Test if auth manager is being initialized properly."""
    
    print("Testing Auth Manager Initialization")
    print("=" * 60)
    
    # Check environment
    auth_mode = os.getenv("GLEITZEIT_AUTH_MODE", "basic").lower()
    print(f"Environment GLEITZEIT_AUTH_MODE: {auth_mode}")
    
    # Create persistence
    persistence = await PersistenceFactory.create()
    print(f"Persistence backend: {type(persistence).__name__}")
    
    # Create system manager
    system_manager = SystemManager(persistence=persistence)
    await system_manager.initialize()
    print(f"SystemManager initialized: {system_manager is not None}")
    
    # Check auth manager
    print(f"AuthManager exists: {system_manager.auth_manager is not None}")
    if system_manager.auth_manager:
        print(f"AuthManager mode: {system_manager.auth_manager.auth_mode}")
        print(f"Basic user: {system_manager.auth_manager.basic_user}")
    
    # Test direct auth manager creation
    print("\nDirect AuthManager test:")
    auth_manager = AuthManager(persistence=persistence)
    print(f"Direct AuthManager mode: {auth_manager.auth_mode}")
    print(f"Direct basic user: {auth_manager.basic_user}")
    
    print("\n" + "=" * 60)
    print("If auth_mode is 'basic' but AuthManager isn't returning basic user,")
    print("there's a logic issue in the /auth/me endpoint")

if __name__ == "__main__":
    asyncio.run(test_auth_initialization())