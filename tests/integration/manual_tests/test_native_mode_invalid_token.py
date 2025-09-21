#!/usr/bin/env python3
"""Test if NATIVE mode rejects invalid service token."""

import asyncio
from gleitzeit.client import GleitzeitClient, ClientMode

async def test_native_mode_with_invalid_token():
    """Test if external Python code can use NATIVE mode with wrong token."""
    
    print("Testing NATIVE mode access with invalid token...")
    
    try:
        # Try to create a client with NATIVE mode and invalid token
        client = GleitzeitClient(
            mode=ClientMode.NATIVE,
            service_token="invalid_token_12345",  # Wrong token
            enable_events=False
        )
        
        await client.initialize()
        
        print("❌ SECURITY ISSUE: NATIVE mode accepted invalid token!")
        
    except PermissionError as e:
        print(f"✅ Good! Invalid token rejected: {e}")
        return
    except Exception as e:
        print(f"Unexpected error: {e}")
        return
    
    print("❌ This should not be reached!")

if __name__ == "__main__":
    asyncio.run(test_native_mode_with_invalid_token())