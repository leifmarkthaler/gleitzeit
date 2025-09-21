#!/usr/bin/env python3
"""Test external client with API mode and auth."""

import asyncio
from gleitzeit.client import GleitzeitClient, ClientMode

async def test_external_client():
    """Test that external clients work with API mode."""
    
    # External clients use API mode
    client = GleitzeitClient(
        mode=ClientMode.API,  # External client uses API mode
        api_host="localhost",
        api_port=8000,
        auto_start_server=False  # Server already running
    )
    
    await client.initialize()
    
    # Test login (will use cookies)
    print("Testing login...")
    result = await client.login("testuser", "testpass")
    print(f"Login result: {result}")
    
    # Test listing workflows (should use cookie auth)
    print("\nListing workflows...")
    workflows = await client.list_workflows(limit=5)
    print(f"Workflows: {workflows}")
    
    # Test system status
    print("\nGetting system status...")
    status = await client.get_system_status()
    print(f"Status: {status}")
    
    await client.shutdown()
    print("\nExternal client test completed!")

if __name__ == "__main__":
    asyncio.run(test_external_client())