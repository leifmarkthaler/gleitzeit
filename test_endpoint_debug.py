#!/usr/bin/env python3
"""
Debug /auth/me endpoint with detailed output.
"""

import asyncio
import sys
sys.path.insert(0, 'src')

from fastapi import Request
from unittest.mock import Mock

# Import dependencies
from gleitzeit.api.dependencies import get_system_manager
from gleitzeit.api.routes.auth import get_current_user

async def test_endpoint():
    """Test the /auth/me endpoint logic directly."""
    
    print("Testing /auth/me endpoint logic")
    print("=" * 60)
    
    # Mock request with no credentials
    mock_request = Mock(spec=Request)
    mock_request.cookies = {}
    
    # Get system manager
    system_manager = await get_system_manager()
    print(f"System manager exists: {system_manager is not None}")
    
    if system_manager:
        print(f"Auth manager exists: {system_manager.auth_manager is not None}")
        if system_manager.auth_manager:
            print(f"Auth mode: {system_manager.auth_manager.auth_mode}")
            print(f"Basic user: {system_manager.auth_manager.basic_user}")
    
    # Test the endpoint logic
    print("\nTesting endpoint with no credentials:")
    try:
        result = await get_current_user(
            request=mock_request,
            credentials=None,
            system_manager=system_manager
        )
        print(f"Result: {result}")
    except Exception as e:
        print(f"Error: {e}")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    asyncio.run(test_endpoint())