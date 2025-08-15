"""
MCP Provider using JSON-RPC Layer for Gleitzeit V4

A proper MCP provider that integrates with the existing protocol and provider
framework, using the JSON-RPC layer for communication.
"""

import asyncio
import json
import logging
import subprocess
from typing import Dict, Any, List, Optional
from datetime import datetime

from gleitzeit.providers.base import ProtocolProvider
from gleitzeit.core.jsonrpc import JSONRPCRequest, JSONRPCResponse
from gleitzeit.core.errors import (
    ErrorCode, ProviderError, ProviderTimeoutError, 
    ProviderNotFoundError, ConfigurationError
)

logger = logging.getLogger(__name__)


class MCPJSONRPCProvider(ProtocolProvider):
    """
    MCP Provider using JSON-RPC communication
    
    This provider integrates MCP servers with Gleitzeit using the standard
    protocol and provider framework.
    """
    
    def __init__(self, provider_id: str, config: Dict[str, Any]):
        """Initialize MCP provider"""
        # Initialize base class
        super().__init__(
            provider_id=provider_id,
            protocol_id="mcp/v1",
            name=config.get('name', 'MCP Provider'),
            description=config.get('description', 'MCP server integration'),
            version="1.0.0"
        )
        
        self.config = config
        
        # Server configuration
        self.command = config.get('command', [])
        self.args = config.get('args', [])
        self.env = config.get('env', {})
        
        # Connection state
        self.process: Optional[subprocess.Popen] = None
        self.connected = False
        self.server_capabilities = {}
        self.tools = {}
        self.resources = {}
        self.prompts = {}
        
        # Request tracking
        self.request_id_counter = 0
        self.pending_requests: Dict[str, asyncio.Future] = {}
        self.message_handler_task: Optional[asyncio.Task] = None
        
        logger.info(f"Initialized MCP provider: {self.name}")
    
    async def initialize(self) -> None:
        """Initialize the MCP server connection"""
        try:
            logger.info(f"Starting MCP server: {' '.join(self.command + self.args)}")
            
            # Start MCP server process
            import os
            env = {**os.environ, **self.env}
            
            self.process = subprocess.Popen(
                self.command + self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=0,
                env=env
            )
            
            # Mark as connected so message handler can work
            self.connected = True
            
            # Start message handler
            self.message_handler_task = asyncio.create_task(self._handle_messages())
            
            # Initialize MCP connection
            await self._initialize_mcp()
            
            # Discover server capabilities
            await self._discover_capabilities()
            
            logger.info(f"MCP server connected: {self.name}")
            
        except Exception as e:
            logger.error(f"Failed to initialize MCP server: {e}")
            await self.shutdown()
            raise ProviderError(
                message=f"MCP server initialization failed: {e}",
                code=ErrorCode.PROVIDER_INITIALIZATION_FAILED,
                provider_id=self.provider_id
            )
    
    async def shutdown(self) -> None:
        """Clean up MCP server connection"""
        self.connected = False
        
        # Cancel message handler
        if self.message_handler_task:
            self.message_handler_task.cancel()
            try:
                await self.message_handler_task
            except asyncio.CancelledError:
                pass
        
        # Terminate process
        if self.process:
            try:
                self.process.terminate()
                await asyncio.sleep(1)
                if self.process.poll() is None:
                    self.process.kill()
            except Exception as e:
                logger.warning(f"Error terminating MCP process: {e}")
            finally:
                self.process = None
        
        logger.info(f"MCP server cleanup complete: {self.name}")
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Handle a request using the MCP server"""
        if not self.connected:
            raise ProviderError(
                message="MCP server not connected",
                code=ErrorCode.PROVIDER_NOT_AVAILABLE,
                provider_id=self.provider_id
            )
        
        # Create JSON-RPC request
        request = JSONRPCRequest.create(
            method=method,
            params=params,
            request_id=self._next_request_id()
        )
        
        # Send request and wait for response
        try:
            result = await self._send_jsonrpc_request(request)
            return result
            
        except Exception as e:
            logger.error(f"MCP request failed: {method} - {e}")
            raise ProviderError(
                message=f"MCP request failed: {e}",
                code=ErrorCode.PROVIDER_NOT_AVAILABLE,
                provider_id=self.provider_id
            )
    
    async def health_check(self) -> Dict[str, Any]:
        """Check MCP server health"""
        if not self.process or self.process.poll() is not None:
            return {"status": "unhealthy", "reason": "Process not running"}
        
        if not self.connected:
            return {"status": "unhealthy", "reason": "Not connected"}
        
        try:
            # Try a ping request
            await self.handle_request("ping", {})
            return {
                "status": "healthy",
                "server_name": self.name,
                "tools_count": len(self.tools),
                "resources_count": len(self.resources),
                "prompts_count": len(self.prompts)
            }
        except Exception as e:
            return {"status": "degraded", "reason": str(e)}
    
    def get_supported_methods(self) -> List[str]:
        """Get list of supported methods"""
        methods = ["ping", "tools/list", "resources/list", "prompts/list"]
        
        # Add dynamic tool methods
        for tool_name in self.tools.keys():
            methods.append(f"tools/call")  # MCP uses tools/call with name parameter
        
        return methods
    
    async def _initialize_mcp(self) -> None:
        """Send MCP initialize request"""
        # Wait for initial notification first
        await asyncio.sleep(0.5)
        
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
        
        request = JSONRPCRequest.create(
            method="initialize",
            params=params,
            request_id=self._next_request_id()
        )
        
        result = await self._send_jsonrpc_request(request)
        self.server_capabilities = result.get("capabilities", {})
        logger.info(f"MCP initialized with capabilities: {list(self.server_capabilities.keys())}")
    
    async def _discover_capabilities(self) -> None:
        """Discover server tools, resources, and prompts"""
        # Get tools
        if self.server_capabilities.get("tools"):
            try:
                tools_request = JSONRPCRequest.create(
                    method="tools/list",
                    request_id=self._next_request_id()
                )
                tools_result = await self._send_jsonrpc_request(tools_request)
                self.tools = {tool["name"]: tool for tool in tools_result.get("tools", [])}
                logger.info(f"Discovered tools: {list(self.tools.keys())}")
            except Exception as e:
                logger.warning(f"Failed to discover tools: {e}")
        
        # Get resources  
        if self.server_capabilities.get("resources"):
            try:
                resources_request = JSONRPCRequest.create(
                    method="resources/list",
                    request_id=self._next_request_id()
                )
                resources_result = await self._send_jsonrpc_request(resources_request)
                self.resources = {res["uri"]: res for res in resources_result.get("resources", [])}
                logger.info(f"Discovered resources: {list(self.resources.keys())}")
            except Exception as e:
                logger.warning(f"Failed to discover resources: {e}")
        
        # Get prompts
        if self.server_capabilities.get("prompts"):
            try:
                prompts_request = JSONRPCRequest.create(
                    method="prompts/list",
                    request_id=self._next_request_id()
                )
                prompts_result = await self._send_jsonrpc_request(prompts_request)
                self.prompts = {prompt["name"]: prompt for prompt in prompts_result.get("prompts", [])}
                logger.info(f"Discovered prompts: {list(self.prompts.keys())}")
            except Exception as e:
                logger.warning(f"Failed to discover prompts: {e}")
    
    async def _send_jsonrpc_request(self, request: JSONRPCRequest, timeout: float = 30.0) -> Any:
        """Send JSON-RPC request and wait for response"""
        if not self.process or not self.process.stdin:
            raise ProviderError(
                message="MCP server process not available",
                code=ErrorCode.PROVIDER_NOT_AVAILABLE,
                provider_id=self.provider_id
            )
        
        # Create future for response
        future = asyncio.Future()
        self.pending_requests[str(request.id)] = future
        
        try:
            # Send request
            request_json = request.to_json() + "\n"
            self.process.stdin.write(request_json)
            self.process.stdin.flush()
            
            # Wait for response
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
            
        except asyncio.TimeoutError:
            # Clean up pending request
            self.pending_requests.pop(str(request.id), None)
            raise ProviderTimeoutError(
                provider_id=self.provider_id,
                timeout=timeout
            )
        except Exception as e:
            # Clean up pending request
            self.pending_requests.pop(str(request.id), None)
            raise
    
    async def _handle_messages(self) -> None:
        """Handle incoming messages from MCP server"""
        logger.info("Starting MCP message handler")
        
        while self.process and self.process.stdout:
            try:
                # Read line from stdout (blocking, run in executor)
                line = await asyncio.get_event_loop().run_in_executor(
                    None, self.process.stdout.readline
                )
                
                if not line:
                    # EOF - server closed
                    logger.warning("MCP server closed stdout")
                    break
                
                line = line.strip()
                if not line:
                    continue
                
                logger.debug(f"Received MCP message: {line}")
                
                try:
                    # Parse JSON-RPC message
                    message = json.loads(line)
                    await self._process_message(message)
                    
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON from MCP server: {line[:100]}")
                    continue
                
            except Exception as e:
                logger.error(f"Error in message handler: {e}")
                break
        
        # Mark as disconnected when message handler stops
        self.connected = False
        logger.info("MCP message handler stopped")
    
    async def _process_message(self, message: Dict[str, Any]) -> None:
        """Process a JSON-RPC message from the server"""
        if "id" in message:
            # Response to our request
            request_id = str(message["id"])
            future = self.pending_requests.pop(request_id, None)
            
            if future and not future.done():
                if "error" in message:
                    # Convert JSON-RPC error to exception
                    error_info = message["error"]
                    error = ProviderError(
                        message=f"MCP server error: {error_info.get('message', 'Unknown error')}",
                        code=ErrorCode.PROVIDER_NOT_AVAILABLE,
                        provider_id=self.provider_id,
                        data=error_info
                    )
                    future.set_exception(error)
                else:
                    # Success response
                    future.set_result(message.get("result"))
        else:
            # Notification from server (no response needed)
            method = message.get("method")
            logger.debug(f"Received notification: {method}")
            
            # Handle specific notifications
            if method == "notifications/tools/changed":
                asyncio.create_task(self._refresh_tools())
            elif method == "notifications/resources/changed":
                asyncio.create_task(self._refresh_resources())
            elif method == "notifications/prompts/changed":
                asyncio.create_task(self._refresh_prompts())
    
    async def _refresh_tools(self) -> None:
        """Refresh tools list"""
        try:
            request = JSONRPCRequest.create(method="tools/list", request_id=self._next_request_id())
            result = await self._send_jsonrpc_request(request)
            self.tools = {tool["name"]: tool for tool in result.get("tools", [])}
            logger.info(f"Refreshed tools: {list(self.tools.keys())}")
        except Exception as e:
            logger.error(f"Failed to refresh tools: {e}")
    
    async def _refresh_resources(self) -> None:
        """Refresh resources list"""
        try:
            request = JSONRPCRequest.create(method="resources/list", request_id=self._next_request_id())
            result = await self._send_jsonrpc_request(request)
            self.resources = {res["uri"]: res for res in result.get("resources", [])}
            logger.info(f"Refreshed resources: {list(self.resources.keys())}")
        except Exception as e:
            logger.error(f"Failed to refresh resources: {e}")
    
    async def _refresh_prompts(self) -> None:
        """Refresh prompts list"""
        try:
            request = JSONRPCRequest.create(method="prompts/list", request_id=self._next_request_id())
            result = await self._send_jsonrpc_request(request)
            self.prompts = {prompt["name"]: prompt for prompt in result.get("prompts", [])}
            logger.info(f"Refreshed prompts: {list(self.prompts.keys())}")
        except Exception as e:
            logger.error(f"Failed to refresh prompts: {e}")
    
    def _next_request_id(self) -> str:
        """Generate next request ID"""
        self.request_id_counter += 1
        return str(self.request_id_counter)


def create_mcp_provider(config: Dict[str, Any]) -> MCPJSONRPCProvider:
    """Factory function to create MCP provider"""
    provider_id = config.get("provider_id")
    if not provider_id:
        raise ConfigurationError("provider_id is required for MCP provider")
    
    return MCPJSONRPCProvider(provider_id, config)