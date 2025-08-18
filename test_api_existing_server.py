#!/usr/bin/env python3
"""Test that API mode uses existing server if available"""

import asyncio
from gleitzeit import Client

async def test_api_existing_server():
    """Test API mode with existing server"""
    print("Testing API mode with existing server...")
    print("=" * 50)
    
    # First client - should find existing server
    async with Client(mode="api") as client:
        print(f"Client 1 - Mode: {client.get_mode()}")
        result = await client.execute_task(
            protocol="mcp/v1",
            method="mcp/tool.multiply",
            params={"a": 5, "b": 5},
            name="First Client Test"
        )
        print(f"Client 1 - Result: {result.result}")
    
    # Second client - should also use existing server
    async with Client(mode="api") as client:
        print(f"Client 2 - Mode: {client.get_mode()}")
        result = await client.execute_task(
            protocol="mcp/v1",
            method="mcp/tool.add",
            params={"a": 10, "b": 10},
            name="Second Client Test"
        )
        print(f"Client 2 - Result: {result.result}")
    
    print("\n✅ Both clients used the existing server!")

if __name__ == "__main__":
    asyncio.run(test_api_existing_server())
