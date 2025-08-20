#!/usr/bin/env python3
"""
Test MCP Hub Integration

This script demonstrates how to use the MCP Hub with Gleitzeit.
"""
import asyncio
import logging
from pathlib import Path

from gleitzeit import GleitzeitClient
from gleitzeit.hub.mcp_hub import MCPHub
from gleitzeit.providers.mcp_hub_provider import MCPHubProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_simple_mcp():
    """Test with simple built-in MCP provider"""
    print("\n" + "="*60)
    print("Testing Simple MCP Provider (built-in tools)")
    print("="*60)
    
    async with GleitzeitClient(mode="native") as client:
        # Simple MCP tools are available by default
        
        # Test echo tool
        result = await client.execute_task(
            protocol="mcp/v1",
            method="mcp/tool.echo",
            params={"message": "Hello from Gleitzeit!"}
        )
        print(f"Echo result: {result}")
        
        # Test add tool
        result = await client.execute_task(
            protocol="mcp/v1",
            method="mcp/tool.add",
            params={"a": 10, "b": 20}
        )
        print(f"Add result: {result}")
        
        # List available tools
        result = await client.execute_task(
            protocol="mcp/v1",
            method="mcp/tools/list",
            params={}
        )
        print(f"Available tools: {result}")


async def test_mcp_hub():
    """Test with MCP Hub and external servers"""
    print("\n" + "="*60)
    print("Testing MCP Hub with External Servers")
    print("="*60)
    
    # Configuration for MCP servers
    mcp_config = {
        "servers": [
            # Test server (if you have test_mcp_server.py)
            {
                "name": "test",
                "connection_type": "stdio",
                "command": ["python", "test_mcp_server.py"],
                "auto_start": True,
                "tool_prefix": "test."
            }
        ]
    }
    
    # Create client with MCP configuration
    async with GleitzeitClient(
        mode="native",
        native_config={"mcp": mcp_config}
    ) as client:
        
        # List all MCP servers
        result = await client.execute_task(
            protocol="mcp/v1",
            method="mcp/servers",
            params={}
        )
        print(f"MCP Servers: {result}")
        
        # List all available tools
        result = await client.execute_task(
            protocol="mcp/v1",
            method="mcp/tools/list",
            params={}
        )
        print(f"Available tools: {result}")
        
        # Ping all servers
        result = await client.execute_task(
            protocol="mcp/v1",
            method="mcp/ping",
            params={}
        )
        print(f"Ping results: {result}")


async def test_direct_hub():
    """Test using MCPHub directly"""
    print("\n" + "="*60)
    print("Testing Direct MCPHub Usage")
    print("="*60)
    
    # Create hub with configuration
    mcp_config = {
        "servers": []  # Add server configs here if needed
    }
    
    hub = MCPHub(
        auto_discover=True,
        config_data=mcp_config
    )
    
    try:
        await hub.initialize()
        
        print(f"Hub initialized with {len(hub.instances)} servers")
        print(f"Available tools: {list(hub.tool_registry.keys())}")
        
        # If you have external servers configured, test them here
        # result = await hub.call_tool("tool_name", {"arg": "value"})
        
    finally:
        await hub.cleanup()


async def test_workflow_with_mcp():
    """Test workflow using MCP tools"""
    print("\n" + "="*60)
    print("Testing Workflow with MCP Tools")
    print("="*60)
    
    workflow = {
        "name": "MCP Test Workflow",
        "tasks": [
            {
                "id": "echo_task",
                "method": "mcp/tool.echo",
                "parameters": {
                    "message": "Starting MCP workflow"
                }
            },
            {
                "id": "add_task",
                "method": "mcp/tool.add",
                "parameters": {
                    "a": 100,
                    "b": 200
                }
            },
            {
                "id": "multiply_task",
                "method": "mcp/tool.multiply",
                "dependencies": ["add_task"],
                "parameters": {
                    "a": 5,
                    "b": 10
                }
            }
        ]
    }
    
    async with GleitzeitClient(mode="native") as client:
        results = await client.run_workflow(workflow)
        
        print("Workflow Results:")
        for task_id, result in results.items():
            print(f"  {task_id}: {result}")


def main():
    """Main entry point"""
    print("\nMCP Hub Integration Test Suite")
    print("================================\n")
    
    # Run tests
    asyncio.run(test_simple_mcp())
    
    # Test with hub (requires external servers)
    # Uncomment if you have test_mcp_server.py or other MCP servers
    # asyncio.run(test_mcp_hub())
    
    # Test direct hub usage
    asyncio.run(test_direct_hub())
    
    # Test workflow
    asyncio.run(test_workflow_with_mcp())
    
    print("\n" + "="*60)
    print("MCP Integration Tests Complete!")
    print("="*60)


if __name__ == "__main__":
    main()