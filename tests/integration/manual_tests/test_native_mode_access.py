#!/usr/bin/env python3
"""Test if NATIVE mode is accessible from Python client."""

import asyncio
from gleitzeit.client import GleitzeitClient, ClientMode

async def test_native_mode_access():
    """Test if external Python code can use NATIVE mode."""
    
    print("Testing NATIVE mode access from external Python code...")
    
    # Try to create a client with NATIVE mode
    client = GleitzeitClient(
        mode=ClientMode.NATIVE,  # Can external code use NATIVE mode?
        enable_events=False
    )
    
    await client.initialize()
    
    print(f"Client mode: {client.mode}")
    print(f"Adapter type: {type(client._adapter).__name__}")
    
    # Test if it works
    print("\nTesting NATIVE mode operations...")
    
    # List workflows (should go directly to persistence)
    workflows = await client.list_workflows(limit=5)
    print(f"Workflows via NATIVE: {workflows}")
    
    # Get system status
    status = await client.get_system_status()
    print(f"System status: {status}")
    
    await client.shutdown()
    print("\n✅ NATIVE mode IS accessible from external Python code!")

if __name__ == "__main__":
    asyncio.run(test_native_mode_access())