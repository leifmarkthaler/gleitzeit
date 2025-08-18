#!/usr/bin/env python3
"""Test the simplified Client import and usage"""

import asyncio
from gleitzeit import Client  # That's all we need!

async def test_string_modes():
    """Test using string modes directly"""
    print("Testing simplified Client with string modes")
    print("=" * 50)
    
    # Test with string mode - native
    print("\n1. Testing native mode (string):")
    async with Client(mode="native") as client:
        print(f"   Mode: {client.get_mode()}")
        result = await client.execute_task(
            protocol="mcp/v1",
            method="mcp/tool.echo",
            params={"message": "Hello from native"},
            name="Native Test"
        )
        print(f"   Result: {result.result if result else 'Failed'}")
    
    # Test with auto mode (default)
    print("\n2. Testing auto mode (default):")
    async with Client() as client:  # No mode specified = auto
        print(f"   Mode: {client.get_mode()}")
        result = await client.execute_task(
            protocol="mcp/v1",
            method="mcp/tool.add",
            params={"a": 5, "b": 10},
            name="Auto Test"
        )
        print(f"   Result: {result.result if result else 'Failed'}")
    
    # Test with mode constants on Client class
    print("\n3. Testing with Client class constants:")
    async with Client(mode=Client.NATIVE) as client:
        print(f"   Mode: {client.get_mode()}")
        result = await client.execute_task(
            protocol="mcp/v1",
            method="mcp/tool.multiply",
            params={"a": 3, "b": 7},
            name="Constant Test"
        )
        print(f"   Result: {result.result if result else 'Failed'}")
    
    print("\n✅ All tests passed!")

async def example_usage():
    """Show simple real-world usage"""
    print("\n" + "=" * 50)
    print("Real-world usage example:")
    print("=" * 50)
    
    # This is all you need for most use cases
    async with Client() as client:
        # Run a workflow
        # result = await client.run_workflow("workflow.yaml")
        
        # Execute a task
        result = await client.execute_task(
            protocol="mcp/v1",
            method="mcp/tool.concat",
            params={"a": "Hello", "b": "World"},
            name="Simple Example"
        )
        
        print(f"Task result: {result.result}")
        
        # Batch process (if needed)
        # batch_result = await client.batch_process(
        #     directory="docs",
        #     pattern="*.txt",
        #     prompt="Summarize this"
        # )

async def main():
    print("\n" + "#" * 50)
    print("# SIMPLIFIED CLIENT IMPORT TEST")
    print("#" * 50)
    
    await test_string_modes()
    await example_usage()
    
    print("\n" + "#" * 50)
    print("# TEST COMPLETE")
    print("#" * 50)
    print("\nKey points:")
    print("1. Import is just: from gleitzeit import Client")
    print("2. No need to import ClientMode separately")
    print("3. Can use strings: 'auto', 'api', 'native'")
    print("4. Or use constants: Client.AUTO, Client.API, Client.NATIVE")
    print("5. Default is 'auto' mode when not specified")

if __name__ == "__main__":
    asyncio.run(main())