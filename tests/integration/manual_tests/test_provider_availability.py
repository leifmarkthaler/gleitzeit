#!/usr/bin/env python
"""Quick test to check which providers are available."""

import asyncio
from gleitzeit.client import GleitzeitClient

async def check_providers():
    """Check which providers are available."""
    
    # Create client
    client = GleitzeitClient(base_url="http://localhost:8060")
    await client.initialize()
    
    # Try to get server info
    try:
        response = await client.session.get(f"{client.base_url}/providers")
        if response.status == 200:
            providers = await response.json()
            print("Available providers:")
            for provider in providers:
                print(f"  - {provider}")
        else:
            print(f"Could not get providers: {response.status}")
    except Exception as e:
        print(f"Error getting providers: {e}")
    
    # Try a simple test
    print("\nTesting provider availability by checking workflow submission...")
    
if __name__ == "__main__":
    asyncio.run(check_providers())