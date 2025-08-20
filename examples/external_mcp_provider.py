"""
External MCP Server Integration with Gleitzeit

This example shows how to integrate an external MCP server with Gleitzeit's
MCP protocol implementation.
"""

import asyncio
import subprocess
import json
import sys
from typing import Dict, List, Any, Optional
import logging
from gleitzeit.providers.base import ProtocolProvider
from gleitzeit.core.errors import ProviderError, TaskExecutionError

logger = logging.getLogger(__name__)


class ExternalMCPProvider(ProtocolProvider):
    """
    MCP Provider that connects to external MCP servers via subprocess.
    
    This provider can connect to any MCP-compliant server that communicates
    via stdio (standard input/output).
    """
    
    def __init__(
        self,
        provider_id: str,
        server_command: List[str],
        server_env: Optional[Dict[str, str]] = None,
        resource_manager=None,
        hub=None,
        **kwargs
    ):
        """
        Initialize external MCP provider.
        
        Args:
            provider_id: Unique identifier for this provider
            server_command: Command to launch the MCP server (e.g., ["python", "mcp_server.py"])
            server_env: Optional environment variables for the server process
        """
        super().__init__(
            provider_id=provider_id,
            protocol_id="mcp/v1",
            name=f"External MCP Provider ({provider_id})",
            description="Connects to external MCP servers via subprocess",
            resource_manager=resource_manager,
            hub=hub
        )
        
        self.server_command = server_command
        self.server_env = server_env
        self.process = None
        self.request_id = 0
        self.available_tools = {}
        self.server_info = {}
        
        logger.info(f"Created External MCP Provider: {provider_id}")
    
    async def initialize(self) -> None:
        """Start the external MCP server and initialize connection"""
        try:
            # Start the MCP server process
            self.process = await asyncio.create_subprocess_exec(
                *self.server_command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self.server_env
            )
            
            logger.info(f"Started MCP server process: {' '.join(self.server_command)}")
            
            # Initialize MCP connection
            init_response = await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                    "resources": {},
                    "prompts": {}
                },
                "clientInfo": {
                    "name": "gleitzeit",
                    "version": "0.0.5"
                }
            })
            
            self.server_info = init_response.get("serverInfo", {})
            logger.info(f"Connected to MCP server: {self.server_info.get('name', 'Unknown')}")
            
            # Discover available tools
            tools_response = await self._send_request("tools/list", {})
            self.available_tools = {
                tool["name"]: tool 
                for tool in tools_response.get("tools", [])
            }
            
            logger.info(f"Discovered {len(self.available_tools)} tools: {list(self.available_tools.keys())}")
            
        except Exception as e:
            raise ProviderError(f"Failed to initialize MCP server: {e}")
    
    async def shutdown(self) -> None:
        """Shutdown the external MCP server"""
        if self.process:
            try:
                # Try graceful shutdown first
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                # Force kill if graceful shutdown fails
                self.process.kill()
                await self.process.wait()
            
            self.process = None
            logger.info("Shut down MCP server process")
    
    async def health_check(self) -> bool:
        """Check if the MCP server is healthy"""
        if not self.process or self.process.returncode is not None:
            return False
        
        try:
            # Send ping to check server responsiveness
            response = await self._send_request("ping", {}, timeout=2.0)
            return response == "pong"
        except:
            return False
    
    def get_supported_methods(self) -> List[str]:
        """Return supported MCP methods"""
        methods = [
            "mcp/tools/list",
            "mcp/resources/list", 
            "mcp/prompts/list",
            "mcp/server_info",
            "mcp/ping"
        ]
        
        # Add discovered tool methods
        for tool_name in self.available_tools:
            methods.append(f"mcp/tool.{tool_name}")
        
        return methods
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Handle incoming MCP requests"""
        logger.info(f"External MCP handling: {method}")
        
        # Strip protocol prefix
        if method.startswith("mcp/"):
            method = method[4:]
        
        # Handle tool calls
        if method.startswith("tool."):
            tool_name = method[5:]
            return await self._call_tool(tool_name, params)
        
        # Handle other methods
        if method == "tools/list":
            return {"tools": list(self.available_tools.values())}
        
        elif method == "server_info":
            return {
                "server": self.server_info,
                "provider_id": self.provider_id,
                "tools": list(self.available_tools.keys())
            }
        
        elif method == "ping":
            response = await self._send_request("ping", {})
            return {"response": response}
        
        elif method == "resources/list":
            response = await self._send_request("resources/list", {})
            return response
        
        elif method == "prompts/list":
            response = await self._send_request("prompts/list", {})
            return response
        
        else:
            # Forward unknown methods directly to server
            response = await self._send_request(method, params)
            return response
    
    async def _call_tool(self, tool_name: str, params: Dict[str, Any]) -> Any:
        """Call a tool on the external MCP server"""
        if tool_name not in self.available_tools:
            raise ProviderError(f"Unknown tool: {tool_name}")
        
        # Get arguments from params
        arguments = params.get("arguments", params)
        
        try:
            # Call tool via MCP protocol
            response = await self._send_request("tools/call", {
                "name": tool_name,
                "arguments": arguments
            })
            
            logger.info(f"Tool {tool_name} executed successfully")
            return response
            
        except Exception as e:
            error_msg = f"MCP tool '{tool_name}' failed: {str(e)}"
            logger.error(error_msg)
            raise TaskExecutionError(
                task_id=f"mcp_tool_{tool_name}",
                message=error_msg
            )
    
    async def _send_request(
        self, 
        method: str, 
        params: Dict[str, Any],
        timeout: float = 30.0
    ) -> Any:
        """Send JSON-RPC request to MCP server and get response"""
        if not self.process or self.process.returncode is not None:
            raise ProviderError("MCP server is not running")
        
        # Create JSON-RPC request
        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params
        }
        
        # Send request
        request_str = json.dumps(request) + "\n"
        self.process.stdin.write(request_str.encode())
        await self.process.stdin.drain()
        
        # Read response with timeout
        try:
            response_line = await asyncio.wait_for(
                self.process.stdout.readline(),
                timeout=timeout
            )
            
            if not response_line:
                raise ProviderError("MCP server closed connection")
            
            # Parse response
            response = json.loads(response_line.decode())
            
            # Check for error
            if "error" in response:
                error = response["error"]
                raise ProviderError(f"MCP error: {error.get('message', 'Unknown error')}")
            
            return response.get("result")
            
        except asyncio.TimeoutError:
            raise ProviderError(f"MCP request timeout for method: {method}")
        except json.JSONDecodeError as e:
            raise ProviderError(f"Invalid JSON response from MCP server: {e}")
    
    async def __aenter__(self) -> 'ExternalMCPProvider':
        """Async context manager entry"""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit"""
        await self.shutdown()


# Example: Custom MCP server implementations

class WebSearchMCPProvider(ExternalMCPProvider):
    """MCP Provider that connects to a web search MCP server"""
    
    def __init__(self, provider_id: str = "web-search-mcp", **kwargs):
        super().__init__(
            provider_id=provider_id,
            server_command=["npx", "-y", "@modelcontextprotocol/server-web-search"],
            **kwargs
        )


class FilesystemMCPProvider(ExternalMCPProvider):
    """MCP Provider that connects to a filesystem MCP server"""
    
    def __init__(self, provider_id: str = "filesystem-mcp", root_dir: str = ".", **kwargs):
        super().__init__(
            provider_id=provider_id,
            server_command=["npx", "-y", "@modelcontextprotocol/server-filesystem", root_dir],
            **kwargs
        )


class GitHubMCPProvider(ExternalMCPProvider):
    """MCP Provider that connects to a GitHub MCP server"""
    
    def __init__(self, provider_id: str = "github-mcp", token: Optional[str] = None, **kwargs):
        env = {}
        if token:
            env["GITHUB_TOKEN"] = token
        
        super().__init__(
            provider_id=provider_id,
            server_command=["npx", "-y", "@modelcontextprotocol/server-github"],
            server_env=env,
            **kwargs
        )


# Usage example
async def main():
    """Example of using external MCP providers"""
    
    print("External MCP Provider Integration Example")
    print("=" * 60)
    
    # Example 1: Connect to the test MCP server
    print("\n1. Connecting to test MCP server...")
    test_provider = ExternalMCPProvider(
        provider_id="test-mcp",
        server_command=["python", "test_mcp_server.py"]
    )
    
    async with test_provider:
        # List available tools
        tools = await test_provider.handle_request("mcp/tools/list", {})
        print(f"   Available tools: {tools}")
        
        # Call echo tool
        echo_result = await test_provider.handle_request(
            "mcp/tool.echo",
            {"arguments": {"message": "Hello from Gleitzeit!"}}
        )
        print(f"   Echo result: {echo_result}")
        
        # Call add tool
        add_result = await test_provider.handle_request(
            "mcp/tool.add",
            {"arguments": {"a": 10, "b": 20}}
        )
        print(f"   Add result: {add_result}")
    
    # Example 2: Connect to npm-based MCP servers (if available)
    print("\n2. Example configurations for popular MCP servers:")
    
    print("""
    # Web Search MCP
    web_search = WebSearchMCPProvider()
    
    # Filesystem MCP
    filesystem = FilesystemMCPProvider(root_dir="/path/to/files")
    
    # GitHub MCP
    github = GitHubMCPProvider(token="your_github_token")
    """)
    
    # Example 3: Register with Gleitzeit
    print("\n3. Registering external MCP with Gleitzeit:")
    print("""
    from gleitzeit import GleitzeitClient
    from gleitzeit.registry import ProtocolProviderRegistry
    
    # Create and initialize provider
    external_mcp = ExternalMCPProvider(
        provider_id="my-mcp",
        server_command=["path/to/mcp/server"]
    )
    
    # Register with Gleitzeit's registry
    registry = ProtocolProviderRegistry()
    registry.register_provider("my-mcp", "mcp/v1", external_mcp)
    
    # Use in workflows
    async with GleitzeitClient() as client:
        result = await client.execute_task(
            protocol="mcp/v1",
            method="mcp/tool.my_tool",
            params={"arg": "value"}
        )
    """)
    
    print("\n" + "=" * 60)
    print("External MCP integration complete!")


# YAML workflow example using external MCP
YAML_EXAMPLE = """
# workflow_with_external_mcp.yaml
name: "External MCP Workflow"
description: "Using external MCP servers in workflows"

tasks:
  - id: "web_search"
    protocol: "mcp/v1"
    method: "mcp/tool.search"
    params:
      query: "latest AI developments"
    
  - id: "analyze_results"
    protocol: "llm/v1"
    method: "llm/chat"
    dependencies: ["web_search"]
    params:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Analyze these search results: ${web_search.response}"
  
  - id: "save_to_file"
    protocol: "mcp/v1"
    method: "mcp/tool.write_file"
    dependencies: ["analyze_results"]
    params:
      path: "analysis.md"
      content: "${analyze_results.response}"
"""


if __name__ == "__main__":
    print("\nTo run the example:")
    print("1. Make sure test_mcp_server.py is in the same directory")
    print("2. Run: python external_mcp_provider.py")
    
    asyncio.run(main())
    
    print("\nYAML Workflow Example:")
    print(YAML_EXAMPLE)