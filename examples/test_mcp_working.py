#!/usr/bin/env python3
"""
Working example of MCP provider with Python test server
Shows how to use MCP provider with actual results
"""

import asyncio
import sys
import os
import json
from pathlib import Path

# Add src to path
sys.path.insert(0, 'src')

from gleitzeit.providers.mcp_provider import create_mcp_provider
from gleitzeit.protocols.mcp_protocol import create_mcp_protocol
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.core.protocol import get_protocol_registry

# Color codes for output
GREEN = '\033[92m'
BLUE = '\033[94m'
YELLOW = '\033[93m'
RESET = '\033[0m'


async def main():
    """Run MCP provider example with actual results"""
    
    print(f"{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}MCP Provider Working Example{RESET}")
    print(f"{BLUE}{'='*60}{RESET}\n")
    
    # Step 1: Create and register MCP protocol
    print(f"{YELLOW}1. Setting up MCP protocol...{RESET}")
    protocol = create_mcp_protocol()
    registry = get_protocol_registry()
    registry.register(protocol)
    print(f"{GREEN}✓ MCP protocol registered{RESET}\n")
    
    # Step 2: Create MCP provider for Python test server
    print(f"{YELLOW}2. Creating MCP provider...{RESET}")
    config = {
        "provider_id": "python-mcp-demo",
        "name": "demo",
        "description": "Demo MCP Server",
        "command": [sys.executable, "-u"],  # -u for unbuffered output
        "args": ["examples/test_mcp_server.py"]
    }
    
    provider = create_mcp_provider(config)
    print(f"{GREEN}✓ MCP provider created{RESET}")
    print(f"  Provider ID: {provider.provider_id}")
    print(f"  Protocol ID: {provider.protocol_id}\n")
    
    try:
        # Step 3: Initialize provider (starts the server)
        print(f"{YELLOW}3. Starting MCP server...{RESET}")
        await asyncio.wait_for(provider.initialize(), timeout=3.0)
        print(f"{GREEN}✓ MCP server started successfully{RESET}\n")
        
        # Step 4: Display server capabilities
        print(f"{YELLOW}4. Server Capabilities:{RESET}")
        print(f"  Tools: {list(provider.tools.keys())}")
        print(f"  Resources: {list(provider.resources.keys())}")
        print(f"  Prompts: {list(provider.prompts.keys())}\n")
        
        # Step 5: Execute echo tool
        print(f"{YELLOW}5. Testing 'echo' tool:{RESET}")
        echo_result = await provider.handle_request(
            "tool.echo",
            {"arguments": {"message": "Hello from Gleitzeit MCP!"}}
        )
        print(f"{GREEN}✓ Echo result: {json.dumps(echo_result, indent=2)}{RESET}\n")
        
        # Step 6: Execute add tool
        print(f"{YELLOW}6. Testing 'add' tool:{RESET}")
        add_result = await provider.handle_request(
            "tool.add",
            {"arguments": {"a": 42, "b": 58}}
        )
        print(f"{GREEN}✓ Add result: {json.dumps(add_result, indent=2)}{RESET}\n")
        
        # Step 7: Read resource
        print(f"{YELLOW}7. Testing resource reading:{RESET}")
        resource_result = await provider.handle_request(
            "resource.test://resource",
            {}
        )
        print(f"{GREEN}✓ Resource result: {json.dumps(resource_result, indent=2)}{RESET}\n")
        
        # Step 8: Get prompt
        print(f"{YELLOW}8. Testing prompt generation:{RESET}")
        prompt_result = await provider.handle_request(
            "prompt.greeting",
            {"arguments": {"name": "MCP User"}}
        )
        print(f"{GREEN}✓ Prompt result: {json.dumps(prompt_result, indent=2)}{RESET}\n")
        
        # Step 9: List all tools
        print(f"{YELLOW}9. Listing all tools:{RESET}")
        tools_list = await provider.handle_request("list_tools", {})
        print(f"{GREEN}✓ Available tools: {json.dumps(tools_list, indent=2)}{RESET}\n")
        
        # Step 10: Get server info
        print(f"{YELLOW}10. Getting server info:{RESET}")
        server_info = await provider.handle_request("server_info", {})
        print(f"{GREEN}✓ Server info:{RESET}")
        print(f"  Name: {server_info.get('name', 'N/A')}")
        print(f"  Tools count: {len(server_info.get('tools', {}))}")
        print(f"  Resources count: {len(server_info.get('resources', {}))}")
        print(f"  Prompts count: {len(server_info.get('prompts', {}))}\n")
        
        # Step 11: Health check
        print(f"{YELLOW}11. Performing health check:{RESET}")
        health = await provider.health_check()
        print(f"{GREEN}✓ Health status: {health['status']}{RESET}")
        if 'details' in health:
            print(f"  Details: {health['details']}\n")
        
        print(f"{BLUE}{'='*60}{RESET}")
        print(f"{GREEN}✅ MCP Provider Example Completed Successfully!{RESET}")
        print(f"{BLUE}{'='*60}{RESET}\n")
        
        print("Summary:")
        print("- Successfully started MCP server subprocess")
        print("- Executed 2 tools (echo, add)")
        print("- Read 1 resource")
        print("- Generated 1 prompt")
        print("- Server is healthy and responsive")
        
    except asyncio.TimeoutError:
        print(f"\n❌ Server initialization timed out")
        print("Troubleshooting tips:")
        print("1. Check if test_mcp_server.py exists in examples/")
        print("2. Try running the server directly: python examples/test_mcp_server.py")
        print("3. Check Python path and permissions")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # Always cleanup
        print(f"\n{YELLOW}Shutting down MCP server...{RESET}")
        await provider.shutdown()
        print(f"{GREEN}✓ Server shutdown complete{RESET}")


if __name__ == "__main__":
    # Run the example
    asyncio.run(main())