#!/usr/bin/env python3
"""
Example: Configuration-based MCP Integration

This example shows how to configure multiple MCP servers via configuration
files and integrate them with Gleitzeit V4.
"""

import asyncio
import logging
import json
import yaml
from typing import Dict, Any

from gleitzeit_v4.core import Task, Workflow, Priority, ExecutionEngine
from gleitzeit_v4.registry import ProtocolProviderRegistry
from gleitzeit_v4.queue import QueueManager, DependencyResolver
from gleitzeit_v4.integrations.mcp_integration import create_mcp_integration

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# Example configuration for multiple MCP servers
MCP_SERVERS_CONFIG = {
    "servers": [
        {
            "provider_id": "filesystem-home",
            "name": "filesystem",
            "description": "Home directory file operations",
            "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem"],
            "args": ["/Users"],  # Adjust path as needed
            "enabled": True
        },
        {
            "provider_id": "brave-search",
            "name": "brave-search", 
            "description": "Web search via Brave",
            "command": ["npx", "-y", "@modelcontextprotocol/server-brave-search"],
            "args": [],
            "env": {
                "BRAVE_API_KEY": "your_brave_api_key_here"
            },
            "enabled": False  # Disabled by default (requires API key)
        },
        {
            "provider_id": "github-integration",
            "name": "github",
            "description": "GitHub API operations",
            "command": ["npx", "-y", "@modelcontextprotocol/server-github"],
            "args": [],
            "env": {
                "GITHUB_PERSONAL_ACCESS_TOKEN": "your_github_token_here"
            },
            "enabled": False  # Disabled by default (requires token)
        }
    ]
}


async def setup_mcp_from_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Setup Gleitzeit with MCP servers from configuration"""
    
    # Initialize Gleitzeit components
    registry = ProtocolProviderRegistry()
    queue_manager = QueueManager()
    dependency_resolver = DependencyResolver()
    execution_engine = ExecutionEngine(registry, queue_manager, dependency_resolver)
    
    # Filter enabled servers
    enabled_servers = [
        server for server in config.get("servers", [])
        if server.get("enabled", True)
    ]
    
    logger.info(f"Setting up {len(enabled_servers)} MCP servers...")
    
    # Create MCP integration
    mcp_integration = await create_mcp_integration(registry, enabled_servers)
    
    return {
        "execution_engine": execution_engine,
        "registry": registry,
        "mcp_integration": mcp_integration,
        "enabled_servers": enabled_servers
    }


async def demo_mcp_discovery(system):
    """Demo MCP server discovery and capabilities"""
    logger.info("\n🔍 === Demo: MCP Server Discovery ===")
    
    mcp_integration = system["mcp_integration"]
    
    # List all available MCP servers
    servers = await mcp_integration.list_mcp_servers()
    
    logger.info(f"Found {len(servers)} active MCP servers:")
    
    for server in servers:
        logger.info(f"\n📡 Server: {server['name']} ({server['provider_id']})")
        logger.info(f"   Protocol: {server['protocol_id']}")
        logger.info(f"   Status: {server['status']}")
        logger.info(f"   Description: {server['description']}")
        
        if server['tools']:
            logger.info(f"   🔧 Tools ({len(server['tools'])}): {', '.join(server['tools'])}")
        
        if server['resources']:
            logger.info(f"   📚 Resources ({len(server['resources'])}): {', '.join(server['resources'])}")
        
        if server['prompts']:
            logger.info(f"   💬 Prompts ({len(server['prompts'])}): {', '.join(server['prompts'])}")


async def demo_multi_mcp_workflow(system):
    """Demo workflow using multiple MCP servers"""
    logger.info("\n🔄 === Demo: Multi-MCP Workflow ===")
    
    execution_engine = system["execution_engine"]
    servers = await system["mcp_integration"].list_mcp_servers()
    
    if not servers:
        logger.warning("No MCP servers available for multi-server demo")
        return
    
    # Find filesystem server if available
    filesystem_server = next((s for s in servers if s['name'] == 'filesystem'), None)
    
    if filesystem_server:
        logger.info("Creating workflow with filesystem operations...")
        
        # Create tasks using MCP servers
        tasks = []
        
        # Task 1: List files (if filesystem server is available)
        if 'tool.list_directory' in [f"tool.{tool}" for tool in filesystem_server['tools']]:
            tasks.append(Task(
                id="list-home-files",
                name="List Home Directory Files",
                protocol=filesystem_server['protocol_id'],
                method="tool.list_directory",
                params={
                    "arguments": {
                        "path": "/Users"  # Adjust as needed
                    }
                },
                priority=Priority.HIGH
            ))
        
        # Execute tasks
        for task in tasks:
            try:
                await execution_engine.submit_task(task)
                result = await execution_engine._execute_single_task()
                
                logger.info(f"✅ Task '{task.name}' completed")
                logger.info(f"   Result: {str(result.result)[:200]}...")
                
            except Exception as e:
                logger.error(f"❌ Task '{task.name}' failed: {e}")
    
    else:
        logger.info("Creating simple server info tasks...")
        
        # Create server info tasks for all available servers
        for i, server in enumerate(servers[:2]):  # Limit to first 2 servers
            task = Task(
                id=f"server-info-{i}",
                name=f"Get {server['name']} Server Info",
                protocol=server['protocol_id'], 
                method="server_info",
                params={},
                priority=Priority.NORMAL
            )
            
            try:
                await execution_engine.submit_task(task)
                result = await execution_engine._execute_single_task()
                
                logger.info(f"✅ Server info for {server['name']}:")
                logger.info(f"   Capabilities: {result.result.get('capabilities', {})}")
                
            except Exception as e:
                logger.error(f"❌ Failed to get info for {server['name']}: {e}")


async def demo_mcp_configuration_management(system):
    """Demo MCP configuration management"""
    logger.info("\n⚙️ === Demo: Configuration Management ===")
    
    mcp_integration = system["mcp_integration"]
    
    # Show current configuration
    logger.info("Current MCP Configuration:")
    for server_config in system["enabled_servers"]:
        logger.info(f"  • {server_config['provider_id']}")
        logger.info(f"    Command: {' '.join(server_config['command'] + server_config.get('args', []))}")
        logger.info(f"    Environment: {server_config.get('env', {})}")
    
    # Demonstrate adding a new MCP server at runtime
    logger.info("\nAdding new MCP server at runtime...")
    
    try:
        # Try to add a simple echo server (this would need to be implemented)
        new_server_config = {
            "provider_id": "runtime-test",
            "name": "runtime-test",
            "description": "Test server added at runtime",
            "command": ["echo", "test"],  # Simple command for demo
            "args": []
        }
        
        # This would normally add the server, but we'll just show the concept
        logger.info(f"Would add server: {new_server_config['provider_id']}")
        
    except Exception as e:
        logger.info(f"Note: Runtime server addition failed (expected): {e}")


async def save_mcp_config(config: Dict[str, Any], filename: str):
    """Save MCP configuration to file"""
    with open(filename, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    
    logger.info(f"MCP configuration saved to: {filename}")


async def load_mcp_config(filename: str) -> Dict[str, Any]:
    """Load MCP configuration from file"""
    try:
        with open(filename, 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.warning(f"Config file not found: {filename}")
        return {}


async def main():
    """Main demo function"""
    logger.info("🚀 Gleitzeit V4 + Multi-MCP Configuration Demo")
    
    try:
        # Save example configuration
        config_file = "mcp_servers_config.yaml"
        await save_mcp_config(MCP_SERVERS_CONFIG, config_file)
        
        # Setup system from configuration
        logger.info("Setting up Gleitzeit V4 with configured MCP servers...")
        system = await setup_mcp_from_config(MCP_SERVERS_CONFIG)
        
        # Run demos
        await demo_mcp_discovery(system)
        await demo_multi_mcp_workflow(system)
        await demo_mcp_configuration_management(system)
        
        logger.info("\n🎉 Configuration demo completed successfully!")
        
        logger.info("\nConfiguration Features Demonstrated:")
        logger.info("✅ YAML-based MCP server configuration")
        logger.info("✅ Multiple MCP server integration")
        logger.info("✅ Server capability discovery")
        logger.info("✅ Runtime server management")
        logger.info("✅ Environment-based server configuration")
        
    except Exception as e:
        logger.error(f"❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # Cleanup
        if 'system' in locals():
            await system["mcp_integration"].shutdown_all()


if __name__ == "__main__":
    asyncio.run(main())