#!/usr/bin/env python3
"""Test that the simple import works correctly"""

import asyncio
from gleitzeit import Client  # Only import Client!

async def test_simple_import():
    """Test the simplified import"""
    print("Testing simplified import: from gleitzeit import Client")
    
    # Test using string mode
    async with Client(mode="native") as client:
        print(f"✓ Client initialized in {client.get_mode()} mode")
        
        # Test a simple task
        result = await client.execute_task(
            protocol="mcp/v1",
            method="mcp/tool.add",
            params={"a": 10, "b": 20},
            name="Import Test"
        )
        
        if result and result.status == "completed":
            print(f"✓ Task executed successfully: {result.result}")
        else:
            print(f"✗ Task failed")
    
    print("\n✅ Simple import test passed!")

if __name__ == "__main__":
    asyncio.run(test_simple_import())