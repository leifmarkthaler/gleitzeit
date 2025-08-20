#!/usr/bin/env python3
"""Simple test of MCP integration"""
import asyncio
import logging

logging.basicConfig(level=logging.INFO)

async def test():
    from gleitzeit import GleitzeitClient
    
    print("Creating client...")
    async with GleitzeitClient(mode="native") as client:
        print("Client created, testing MCP...")
        
        # Test with simple execute_task
        result = await client.execute_task(
            protocol="mcp/v1",
            method="tool.echo",
            params={"message": "Hello MCP!"}
        )
        print(f"Result: {result}")
        
        print("Test complete!")

if __name__ == "__main__":
    asyncio.run(test())