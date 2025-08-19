#!/usr/bin/env python3
"""
Test that all providers work correctly with hub integration
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit import Client


async def test_providers():
    """Test that providers work with hub integration"""
    
    print("Testing Provider Hub Integration...")
    print("-" * 50)
    
    # Use native mode with resource management
    from gleitzeit.client import ClientMode
    async with Client(
        mode=ClientMode.NATIVE,
        native_config={'enable_resource_management': True}
    ) as client:
        print("✓ Client initialized")
        
        # Test Python provider with file execution
        print("\nTesting Python provider...")
        try:
            # Execute a Python script that exists
            result = await client.execute_task(
                protocol="python/v1",
                method="python/execute",
                params={"file": "examples/scripts/calculate_sum.py"},
                wait=True
            )
            if result.status == "completed":
                print(f"✓ Python file execution works")
            else:
                print(f"✗ Python execution failed: {result.error}")
        except Exception as e:
            print(f"✗ Python provider error: {e}")
        
        # Test MCP provider
        print("\nTesting MCP provider...")
        try:
            result = await client.execute_task(
                protocol="mcp/v1",
                method="mcp/tool.add",
                params={"a": 5, "b": 3},
                wait=True
            )
            if result.status == "completed":
                print(f"✓ MCP provider works, result: {result.result}")
            else:
                print(f"✗ MCP execution failed: {result.error}")
        except Exception as e:
            print(f"✗ MCP provider error: {e}")
        
        # Test LLM provider (Ollama)
        print("\nTesting LLM provider...")
        try:
            response = await client.chat("Say 'Hello from provider test' in 5 words or less")
            print(f"✓ LLM provider works: {response}")
        except Exception as e:
            print(f"✗ LLM provider error: {e}")
        
        print("\n" + "=" * 50)
        print("Provider hub integration test complete!")


if __name__ == "__main__":
    asyncio.run(test_providers())