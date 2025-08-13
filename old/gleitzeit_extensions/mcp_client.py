"""
MCP Client Integration for Gleitzeit

This module provides Model Context Protocol (MCP) client functionality,
allowing Gleitzeit to connect to MCP servers for LLM providers and tools.
"""

import asyncio
import os
import subprocess
import json
from contextlib import AsyncExitStack
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field
from pathlib import Path

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    # Create stub classes for when MCP is not available
    class ClientSession:
        pass
    class StdioServerParameters:
        pass
    def stdio_client(*args, **kwargs):
        pass

from .exceptions import ExtensionError, ExtensionNotFound, ExtensionLoadError


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server"""
    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    working_directory: Optional[str] = None
    timeout: int = 30
    models: List[str] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    description: str = ""


@dataclass
class MCPServerConnection:
    """Active MCP server connection"""
    config: MCPServerConfig
    session: Optional[ClientSession] = None
    exit_stack: Optional[AsyncExitStack] = None
    process: Optional[subprocess.Popen] = None
    connected: bool = False
    last_error: Optional[str] = None


class MCPClientManager:
    """
    Manager for MCP server connections in Gleitzeit
    
    Handles discovery, connection, and communication with MCP servers
    for LLM providers and tools.
    """
    
    def __init__(self):
        if not MCP_AVAILABLE:
            raise ExtensionError("MCP is not available. Install with: pip install 'mcp[cli]'")
        
        self.servers: Dict[str, MCPServerConfig] = {}
        self.connections: Dict[str, MCPServerConnection] = {}
        self._running = False
    
    def add_server(
        self, 
        name: str,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        working_directory: Optional[str] = None,
        timeout: int = 30,
        models: Optional[List[str]] = None,
        capabilities: Optional[List[str]] = None,
        description: str = ""
    ) -> None:
        """
        Add an MCP server configuration
        
        Args:
            name: Unique server name
            command: Command to run the server
            args: Command line arguments
            env: Environment variables
            working_directory: Working directory for server
            timeout: Connection timeout
            models: Models provided by this server
            capabilities: Capabilities provided by this server
            description: Human-readable description
        """
        config = MCPServerConfig(
            name=name,
            command=command,
            args=args or [],
            env=env or {},
            working_directory=working_directory,
            timeout=timeout,
            models=models or [],
            capabilities=capabilities or [],
            description=description
        )
        
        self.servers[name] = config
        print(f"📡 Added MCP server: {name}")
    
    def add_server_from_config(self, config_dict: Dict[str, Any]) -> None:
        """Add server from dictionary configuration"""
        name = config_dict.get('name')
        if not name:
            raise ValueError("Server configuration must have 'name' field")
        
        self.add_server(
            name=name,
            command=config_dict.get('command', ''),
            args=config_dict.get('args', []),
            env=config_dict.get('env', {}),
            working_directory=config_dict.get('working_directory'),
            timeout=config_dict.get('timeout', 30),
            models=config_dict.get('models', []),
            capabilities=config_dict.get('capabilities', []),
            description=config_dict.get('description', '')
        )
    
    def load_servers_from_file(self, config_file: str) -> None:
        """Load server configurations from JSON/YAML file"""
        config_path = Path(config_file)
        if not config_path.exists():
            raise ExtensionLoadError("mcp_config", f"Config file not found: {config_file}")
        
        try:
            if config_path.suffix.lower() in ['.yml', '.yaml']:
                import yaml
                with open(config_path) as f:
                    config = yaml.safe_load(f)
            else:
                with open(config_path) as f:
                    config = json.load(f)
            
            servers = config.get('servers', [])
            for server_config in servers:
                self.add_server_from_config(server_config)
                
            print(f"📡 Loaded {len(servers)} MCP server configurations from {config_file}")
            
        except Exception as e:
            raise ExtensionLoadError("mcp_config", f"Failed to load config: {e}")
    
    async def connect_server(self, name: str) -> bool:
        """
        Connect to an MCP server
        
        Args:
            name: Server name to connect to
            
        Returns:
            True if connection successful
        """
        if name not in self.servers:
            raise ExtensionNotFound(f"MCP server '{name}' not found")
        
        if name in self.connections and self.connections[name].connected:
            print(f"📡 MCP server '{name}' already connected")
            return True
        
        config = self.servers[name]
        connection = MCPServerConnection(config=config)
        
        try:
            print(f"📡 Connecting to MCP server: {name}")
            
            # Set up environment
            env = os.environ.copy()
            env.update(config.env)
            
            # Create server parameters
            server_params = StdioServerParameters(
                command=config.command,
                args=config.args,
                env=env
            )
            
            # Create exit stack for proper cleanup
            exit_stack = AsyncExitStack()
            connection.exit_stack = exit_stack
            
            # Connect to server
            stdio_transport = await exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            
            # Create session
            session = await exit_stack.enter_async_context(
                ClientSession(stdio_transport[0], stdio_transport[1])
            )
            
            # Initialize session
            await session.initialize()
            
            connection.session = session
            connection.connected = True
            self.connections[name] = connection
            
            print(f"✅ Connected to MCP server: {name}")
            return True
            
        except Exception as e:
            connection.last_error = str(e)
            print(f"❌ Failed to connect to MCP server '{name}': {e}")
            
            # Clean up on failure
            if connection.exit_stack:
                try:
                    await connection.exit_stack.aclose()
                except Exception:
                    pass
            
            return False
    
    async def disconnect_server(self, name: str) -> None:
        """Disconnect from an MCP server"""
        if name not in self.connections:
            return
        
        connection = self.connections[name]
        
        try:
            print(f"📡 Disconnecting MCP server: {name}")
            
            if connection.exit_stack:
                await connection.exit_stack.aclose()
            
            connection.connected = False
            connection.session = None
            connection.exit_stack = None
            
            print(f"✅ Disconnected MCP server: {name}")
            
        except Exception as e:
            print(f"⚠️ Error disconnecting MCP server '{name}': {e}")
        
        finally:
            del self.connections[name]
    
    async def connect_all_servers(self) -> Dict[str, bool]:
        """Connect to all configured servers"""
        results = {}
        
        print(f"📡 Connecting to {len(self.servers)} MCP servers...")
        
        for name in self.servers:
            results[name] = await self.connect_server(name)
        
        connected_count = sum(1 for success in results.values() if success)
        print(f"✅ Connected to {connected_count}/{len(self.servers)} MCP servers")
        
        return results
    
    async def disconnect_all_servers(self) -> None:
        """Disconnect from all servers"""
        print(f"📡 Disconnecting {len(self.connections)} MCP servers...")
        
        for name in list(self.connections.keys()):
            await self.disconnect_server(name)
        
        print("✅ All MCP servers disconnected")
    
    async def call_tool(
        self, 
        server_name: str, 
        tool_name: str, 
        arguments: Dict[str, Any]
    ) -> Any:
        """Call a tool on an MCP server"""
        if server_name not in self.connections:
            raise ExtensionError(f"MCP server '{server_name}' not connected")
        
        connection = self.connections[server_name]
        if not connection.connected or not connection.session:
            raise ExtensionError(f"MCP server '{server_name}' not properly connected")
        
        try:
            result = await connection.session.call_tool(tool_name, arguments)
            return result
        except Exception as e:
            raise ExtensionError(f"MCP tool call failed on '{server_name}': {e}")
    
    async def get_server_resources(self, server_name: str) -> List[Dict[str, Any]]:
        """Get available resources from an MCP server"""
        if server_name not in self.connections:
            raise ExtensionError(f"MCP server '{server_name}' not connected")
        
        connection = self.connections[server_name]
        if not connection.connected or not connection.session:
            raise ExtensionError(f"MCP server '{server_name}' not properly connected")
        
        try:
            response = await connection.session.list_resources()
            return response.resources if hasattr(response, 'resources') else []
        except Exception as e:
            raise ExtensionError(f"Failed to get resources from '{server_name}': {e}")
    
    async def get_server_tools(self, server_name: str) -> List[Dict[str, Any]]:
        """Get available tools from an MCP server"""
        if server_name not in self.connections:
            raise ExtensionError(f"MCP server '{server_name}' not connected")
        
        connection = self.connections[server_name]
        if not connection.connected or not connection.session:
            raise ExtensionError(f"MCP server '{server_name}' not properly connected")
        
        try:
            response = await connection.session.list_tools()
            return response.tools if hasattr(response, 'tools') else []
        except Exception as e:
            raise ExtensionError(f"Failed to get tools from '{server_name}': {e}")
    
    def get_available_models(self) -> Dict[str, List[str]]:
        """Get all models available from MCP servers"""
        models = {}
        for name, config in self.servers.items():
            if config.models:
                models[name] = config.models
        return models
    
    def find_server_for_model(self, model: str) -> Optional[str]:
        """Find which MCP server provides a specific model"""
        for server_name, config in self.servers.items():
            if model in config.models:
                return server_name
        return None
    
    def get_server_status(self, name: str) -> Dict[str, Any]:
        """Get status information for an MCP server"""
        if name not in self.servers:
            return {"found": False}
        
        config = self.servers[name]
        connection = self.connections.get(name)
        
        status = {
            "name": name,
            "command": config.command,
            "description": config.description,
            "models": config.models,
            "capabilities": config.capabilities,
            "configured": True,
            "connected": connection.connected if connection else False
        }
        
        if connection:
            status["last_error"] = connection.last_error
        
        return status
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of all MCP servers"""
        return {
            "total_servers": len(self.servers),
            "connected_servers": len([c for c in self.connections.values() if c.connected]),
            "available_models": sum(len(config.models) for config in self.servers.values()),
            "servers": {name: self.get_server_status(name) for name in self.servers}
        }
    
    async def __aenter__(self):
        """Async context manager entry"""
        await self.connect_all_servers()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.disconnect_all_servers()


def is_mcp_available() -> bool:
    """Check if MCP is available for use"""
    return MCP_AVAILABLE


def create_standard_llm_servers() -> Dict[str, Dict[str, Any]]:
    """
    Create configurations for standard LLM provider MCP servers
    
    Returns:
        Dictionary of server configurations
    """
    return {
        "openai": {
            "name": "openai",
            "command": "mcp-server-openai",
            "env": {"OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", "")},
            "models": ["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo", "gpt-4o"],
            "capabilities": ["text", "vision", "function_calling"],
            "description": "OpenAI GPT models via MCP"
        },
        "anthropic": {
            "name": "anthropic", 
            "command": "mcp-server-anthropic",
            "env": {"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")},
            "models": ["claude-3-opus", "claude-3-sonnet", "claude-3-haiku"],
            "capabilities": ["text", "function_calling"],
            "description": "Anthropic Claude models via MCP"
        },
        "ollama": {
            "name": "ollama",
            "command": "mcp-server-ollama", 
            "args": ["--host", "localhost:11434"],
            "models": ["llama3", "llava", "codellama", "mistral"],
            "capabilities": ["text", "vision"],
            "description": "Local Ollama models via MCP"
        }
    }