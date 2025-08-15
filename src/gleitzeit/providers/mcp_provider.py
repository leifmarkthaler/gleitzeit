"""
MCP (Model Context Protocol) Provider for Gleitzeit V4

This provider allows Gleitzeit to integrate with external MCP servers,
enabling access to tools, resources, and capabilities exposed via MCP.
"""

import asyncio
import json
import logging
import os
from typing import Dict, Any, List, Optional
import subprocess
import sys

from gleitzeit.providers.base import ProtocolProvider
from gleitzeit.core.jsonrpc import JSONRPCRequest, JSONRPCResponse, JSONRPCError
from gleitzeit.core.errors import (
    ErrorCode, ProviderError, ProviderTimeoutError, SystemError, 
    ConfigurationError, is_retryable_error
)

logger = logging.getLogger(__name__)


class MCPProvider(ProtocolProvider):
    """
    Provider that connects to external MCP servers
    
    This provider can:
    - Connect to MCP servers via stdio or other transports
    - Expose MCP tools as Gleitzeit tasks
    - Handle MCP resources and prompts
    - Manage MCP server lifecycle
    """
    
    def __init__(self, provider_id: str, server_config: Dict[str, Any]):
        self.provider_id = provider_id
        self.protocol_id = "mcp/v1"  # Use generic MCP protocol
        self.name = f"MCP Provider ({server_config.get('name', 'Unknown')})"
        self.description = server_config.get('description', 'MCP server integration')
        
        # Server configuration
        self.server_config = server_config
        self.server_command = server_config.get('command', [])
        self.server_args = server_config.get('args', [])
        self.server_env = server_config.get('env', {})
        
        # Connection state
        self.process: Optional[subprocess.Popen] = None
        self.connected = False
        self.capabilities = {}
        self.tools = {}
        self.resources = {}
        self.prompts = {}
        
        # Message handling
        self.request_id_counter = 0
        self.pending_requests: Dict[str, asyncio.Future] = {}
        
        logger.info(f"Initialized MCP Provider: {self.name}")
    
    async def initialize(self):
        """Initialize connection to MCP server"""
        try:
            logger.info(f"Starting MCP server: {' '.join(self.server_command + self.server_args)}")
            
            # Start MCP server process
            env = {**self.server_env, **dict(os.environ)}
            self.process = subprocess.Popen(
                self.server_command + self.server_args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
                bufsize=1  # Line buffered for text mode
            )
            
            # Start message handling task
            self.message_task = asyncio.create_task(self._handle_messages())
            
            # Initialize MCP connection
            await self._send_initialize()
            
            # Get server capabilities
            await self._get_server_info()
            
            self.connected = True
            logger.info(f"Successfully connected to MCP server: {self.name}")
            
        except Exception as e:
            logger.error(f"Failed to initialize MCP server {self.name}: {e}")
            await self.shutdown()
            
            # Wrap initialization errors
            raise ProviderError(
                message=f"MCP server initialization failed: {e}",
                code=ErrorCode.PROVIDER_INITIALIZATION_FAILED,
                provider_id=self.provider_id,
                data={"server_command": ' '.join(self.server_command + self.server_args)},
                cause=e
            )
    
    async def shutdown(self):
        """Shutdown MCP server connection"""
        self.connected = False
        
        # Cancel message handling
        if hasattr(self, 'message_task'):
            self.message_task.cancel()
            try:
                await self.message_task
            except asyncio.CancelledError:
                pass
        
        # Terminate process
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            
            self.process = None
        
        logger.info(f"Shutdown MCP server: {self.name}")
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Handle Gleitzeit task by calling MCP server"""
        if not self.connected:
            raise ProviderError(
                message=f"MCP server is not connected",
                code=ErrorCode.PROVIDER_NOT_AVAILABLE,
                provider_id=self.provider_id,
                data={"server_name": self.name}
            )
        
        # Map Gleitzeit methods to MCP operations
        if method.startswith("tool."):
            # Execute MCP tool
            tool_name = method[5:]  # Remove "tool." prefix
            return await self._call_tool(tool_name, params.get("arguments", {}))
        
        elif method.startswith("resource."):
            # Get MCP resource
            resource_uri = method[9:]  # Remove "resource." prefix
            return await self._get_resource(resource_uri)
        
        elif method.startswith("prompt."):
            # Get MCP prompt
            prompt_name = method[7:]  # Remove "prompt." prefix
            return await self._get_prompt(prompt_name, params.get("arguments", {}))
        
        elif method == "list_tools":
            # List available tools
            return {"tools": list(self.tools.keys())}
        
        elif method == "list_resources":
            # List available resources
            return {"resources": list(self.resources.keys())}
        
        elif method == "list_prompts":
            # List available prompts
            return {"prompts": list(self.prompts.keys())}
        
        elif method == "server_info":
            # Get server information
            return {
                "name": self.name,
                "capabilities": self.capabilities,
                "tools": self.tools,
                "resources": self.resources,
                "prompts": self.prompts
            }
        
        else:
            raise ProviderError(
                message=f"Unsupported MCP method: {method}",
                code=ErrorCode.METHOD_NOT_SUPPORTED,
                provider_id=self.provider_id,
                data={"method": method, "supported_methods": self.get_supported_methods()}
            )
    
    async def health_check(self) -> Dict[str, Any]:
        """Check MCP server health"""
        if not self.process or self.process.poll() is not None:
            return {
                "status": "unhealthy",
                "details": "MCP server process is not running"
            }
        
        if not self.connected:
            return {
                "status": "unhealthy", 
                "details": "MCP server is not connected"
            }
        
        try:
            # Try a simple ping operation
            await self._send_ping()
            
            return {
                "status": "healthy",
                "details": f"MCP server {self.name} is responding",
                "capabilities": self.capabilities,
                "tool_count": len(self.tools),
                "resource_count": len(self.resources),
                "prompt_count": len(self.prompts)
            }
            
        except Exception as e:
            return {
                "status": "degraded",
                "details": f"MCP server health check failed: {e}"
            }
    
    def get_supported_methods(self) -> List[str]:
        """Get list of supported methods based on MCP server capabilities"""
        methods = ["server_info", "list_tools", "list_resources", "list_prompts"]
        
        # Add tool methods
        for tool_name in self.tools.keys():
            methods.append(f"tool.{tool_name}")
        
        # Add resource methods
        for resource_uri in self.resources.keys():
            methods.append(f"resource.{resource_uri}")
        
        # Add prompt methods
        for prompt_name in self.prompts.keys():
            methods.append(f"prompt.{prompt_name}")
        
        return methods
    
    async def _handle_messages(self):
        """Handle incoming messages from MCP server"""
        while self.connected and self.process:
            try:
                # Read message from stdout
                line = await asyncio.get_event_loop().run_in_executor(
                    None, self.process.stdout.readline
                )
                
                if not line:
                    # EOF reached
                    break
                
                try:
                    message = json.loads(line.strip())
                    await self._process_message(message)
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON from MCP server: {line.strip()}")
                    continue
                
            except Exception as e:
                logger.error(f"Error handling MCP messages: {e}")
                break
    
    async def _process_message(self, message: Dict[str, Any]):
        """Process a single message from MCP server"""
        if "id" in message:
            # Response to our request
            request_id = str(message["id"])
            if request_id in self.pending_requests:
                future = self.pending_requests.pop(request_id)
                if "error" in message:
                    # Convert MCP error to structured error
                    mcp_error = message["error"]
                    error = ProviderError(
                        message=f"MCP server error: {mcp_error.get('message', 'Unknown error')}",
                        code=ErrorCode.PROVIDER_NOT_AVAILABLE,
                        provider_id=self.provider_id,
                        data={"mcp_error_code": mcp_error.get("code"), "mcp_error": mcp_error}
                    )
                    future.set_exception(error)
                else:
                    future.set_result(message.get("result"))
        else:
            # Notification from server
            method = message.get("method")
            if method == "notifications/resources/updated":
                await self._refresh_resources()
            elif method == "notifications/tools/updated":
                await self._refresh_tools()
            elif method == "notifications/prompts/updated":
                await self._refresh_prompts()
    
    async def _send_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Send JSON-RPC request to MCP server and wait for response"""
        self.request_id_counter += 1
        request_id = str(self.request_id_counter)
        
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method
        }
        
        if params:
            request["params"] = params
        
        # Create future for response
        future = asyncio.Future()
        self.pending_requests[request_id] = future
        
        # Send request
        request_json = json.dumps(request) + "\n"
        self.process.stdin.write(request_json)
        self.process.stdin.flush()
        
        # Wait for response
        try:
            result = await asyncio.wait_for(future, timeout=30.0)
            return result
        except asyncio.TimeoutError as e:
            self.pending_requests.pop(request_id, None)
            raise ProviderTimeoutError(
                provider_id=self.provider_id,
                timeout=30.0,
                cause=e
            )
    
    async def _send_initialize(self):
        """Send initialize request to MCP server"""
        params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "roots": {"listChanged": True},
                "sampling": {}
            },
            "clientInfo": {
                "name": "gleitzeit-v4",
                "version": "4.0.0"
            }
        }
        
        result = await self._send_request("initialize", params)
        self.capabilities = result.get("capabilities", {})
        return result
    
    async def _get_server_info(self):
        """Get server tools, resources, and prompts"""
        # Get tools
        if self.capabilities.get("tools"):
            try:
                tools_result = await self._send_request("tools/list")
                self.tools = {tool["name"]: tool for tool in tools_result.get("tools", [])}
            except Exception as e:
                logger.warning(f"Failed to get MCP tools: {e}")
        
        # Get resources
        if self.capabilities.get("resources"):
            try:
                resources_result = await self._send_request("resources/list")
                self.resources = {res["uri"]: res for res in resources_result.get("resources", [])}
            except Exception as e:
                logger.warning(f"Failed to get MCP resources: {e}")
        
        # Get prompts
        if self.capabilities.get("prompts"):
            try:
                prompts_result = await self._send_request("prompts/list")
                self.prompts = {prompt["name"]: prompt for prompt in prompts_result.get("prompts", [])}
            except Exception as e:
                logger.warning(f"Failed to get MCP prompts: {e}")
    
    async def _call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Call an MCP tool"""
        if tool_name not in self.tools:
            raise ProviderError(
                message=f"Unknown MCP tool: {tool_name}",
                code=ErrorCode.METHOD_NOT_FOUND,
                provider_id=self.provider_id,
                data={"tool_name": tool_name, "available_tools": list(self.tools.keys())}
            )
        
        params = {
            "name": tool_name,
            "arguments": arguments
        }
        
        result = await self._send_request("tools/call", params)
        return result
    
    async def _get_resource(self, resource_uri: str) -> Any:
        """Get an MCP resource"""
        if resource_uri not in self.resources:
            raise ProviderError(
                message=f"Unknown MCP resource: {resource_uri}",
                code=ErrorCode.METHOD_NOT_FOUND,
                provider_id=self.provider_id,
                data={"resource_uri": resource_uri, "available_resources": list(self.resources.keys())}
            )
        
        params = {"uri": resource_uri}
        result = await self._send_request("resources/read", params)
        return result
    
    async def _get_prompt(self, prompt_name: str, arguments: Dict[str, Any]) -> Any:
        """Get an MCP prompt"""
        if prompt_name not in self.prompts:
            raise ProviderError(
                message=f"Unknown MCP prompt: {prompt_name}",
                code=ErrorCode.METHOD_NOT_FOUND,
                provider_id=self.provider_id,
                data={"prompt_name": prompt_name, "available_prompts": list(self.prompts.keys())}
            )
        
        params = {
            "name": prompt_name,
            "arguments": arguments
        }
        
        result = await self._send_request("prompts/get", params)
        return result
    
    async def _send_ping(self) -> Any:
        """Send ping to check server health"""
        return await self._send_request("ping")
    
    async def _refresh_tools(self):
        """Refresh tools list"""
        if self.capabilities.get("tools"):
            try:
                tools_result = await self._send_request("tools/list")
                self.tools = {tool["name"]: tool for tool in tools_result.get("tools", [])}
                logger.info(f"Refreshed MCP tools: {list(self.tools.keys())}")
            except Exception as e:
                logger.error(f"Failed to refresh MCP tools: {e}")
    
    async def _refresh_resources(self):
        """Refresh resources list"""
        if self.capabilities.get("resources"):
            try:
                resources_result = await self._send_request("resources/list")
                self.resources = {res["uri"]: res for res in resources_result.get("resources", [])}
                logger.info(f"Refreshed MCP resources: {list(self.resources.keys())}")
            except Exception as e:
                logger.error(f"Failed to refresh MCP resources: {e}")
    
    async def _refresh_prompts(self):
        """Refresh prompts list"""
        if self.capabilities.get("prompts"):
            try:
                prompts_result = await self._send_request("prompts/list")
                self.prompts = {prompt["name"]: prompt for prompt in prompts_result.get("prompts", [])}
                logger.info(f"Refreshed MCP prompts: {list(self.prompts.keys())}")
            except Exception as e:
                logger.error(f"Failed to refresh MCP prompts: {e}")


def create_mcp_provider(config: Dict[str, Any]) -> MCPProvider:
    """
    Factory function to create MCP provider from configuration
    
    Example config:
    {
        "provider_id": "filesystem-mcp",
        "name": "filesystem",
        "description": "Filesystem operations via MCP",
        "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem"],
        "args": ["/path/to/directory"],
        "env": {
            "NODE_ENV": "production"
        }
    }
    """
    provider_id = config.get("provider_id")
    if not provider_id:
        raise ConfigurationError(
            message="provider_id is required in MCP configuration",
            data={"config": config}
        )
    
    return MCPProvider(provider_id, config)