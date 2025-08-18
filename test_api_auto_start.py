#!/usr/bin/env python3
"""Test that API mode auto-starts server if needed"""

import asyncio
from gleitzeit import Client

async def test_api_auto_start():
    """Test API mode with auto-start"""
    print("Testing API mode with auto-start server...")
    print("=" * 50)
    
    # Use API mode explicitly - should auto-start server
    async with Client(mode="api", auto_start_server=True) as client:
        print(f"Mode: {client.get_mode()}")
        
        result = await client.execute_task(
            protocol="mcp/v1",
            method="mcp/tool.add",
            params={"a": 100, "b": 200},
            name="API Auto-Start Test"
        )
        
        if result and result.status == "completed":
            print(f"✓ Task executed: {result.result}")
        else:
            print(f"✗ Task failed")
    
    print("\n✅ API auto-start test passed!")

if __name__ == "__main__":
    asyncio.run(test_api_auto_start())
