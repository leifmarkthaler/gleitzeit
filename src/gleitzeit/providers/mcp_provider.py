"""
MCP (Model Context Protocol) Provider

Universal provider for integrating MCP services with automatic protocol generation.
MCP services are self-describing through JSON-RPC 2.0 interface.
"""

import asyncio
import aiohttp
import json
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass
import logging

from .simple import SimpleProvider
from gleitzeit.core.errors import (
    ProviderError, ConnectionTimeoutError, NetworkError
)

logger = logging.getLogger(__name__)


@dataclass
class MCPCapability:
    """Represents an MCP service capability/method"""
    name: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]


class MCPProvider(SimpleProvider):
    """
    Universal provider for MCP services.
    
    Features:
    - Auto-discovers capabilities through MCP handshake
    - Auto-generates protocol from discovered capabilities
    - Forwards all requests to MCP service via JSON-RPC
    - Supports any MCP service without pre-configuration
    """
    
    def __init__(
        self,
        mcp_endpoint: str,
        mcp_name: Optional[str] = None,
        timeout: int = 30,
        **kwargs
    ):
        """
        Initialize MCP provider.
        
        Args:
            mcp_endpoint: URL of the MCP service
            mcp_name: Optional name for the MCP service
            timeout: Request timeout in seconds
            **kwargs: Additional provider arguments
        """
        # Auto-generate protocol_id if not provided
        if 'protocol_id' not in kwargs:
            service_name = mcp_name or kwargs.get('provider_id', 'mcp')
            kwargs['protocol_id'] = f"mcp-{service_name}/auto"
        
        # Enable auto-protocol generation by default
        kwargs.setdefault('auto_generate_protocol', True)
        
        super().__init__(**kwargs)
        
        self.mcp_endpoint = mcp_endpoint.rstrip('/')
        self.mcp_name = mcp_name or self.provider_id
        self.timeout = timeout
        
        # MCP service information
        self.mcp_version: Optional[str] = None
        self.mcp_capabilities: Dict[str, MCPCapability] = {}
        self.capabilities: Dict[str, Any] = {}  # For protocol generation
        
        # HTTP session
        self._session: Optional[aiohttp.ClientSession] = None
        self._request_id = 0
    
    async def initialize(self):
        """
        Initialize connection to MCP service and discover capabilities.
        """
        logger.info(f"Initializing MCP connection to {self.mcp_endpoint}")
        
        # Create HTTP session
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        )
        
        try:
            # Perform MCP handshake
            await self._mcp_handshake()
            
            # Regenerate protocol with discovered capabilities
            if self.auto_generate_protocol:
                self._generated_protocol = self._generate_protocol()
                if self.register_protocol and self._generated_protocol and self.protocol_registry:
                    self._register_generated_protocol()
            
            logger.info(f"MCP provider initialized: {len(self.mcp_capabilities)} methods discovered")
            
        except Exception as e:
            await self.shutdown()
            raise ConnectionTimeoutError(f"Failed to initialize MCP connection: {e}")
    
    async def shutdown(self):
        """Clean up resources."""
        if self._session:
            await self._session.close()
            self._session = None
    
    async def _mcp_handshake(self):
        """
        Perform MCP handshake to discover service capabilities.
        """
        # Send initialize request
        response = await self._send_jsonrpc_request(
            "initialize",
            {
                "protocolVersion": "0.1.0",
                "clientInfo": {
                    "name": "gleitzeit",
                    "version": "1.0.0"
                }
            }
        )
        
        # Parse response
        if "error" in response:
            raise ProviderError(f"MCP handshake failed: {response['error']}")
        
        result = response.get("result", {})
        self.mcp_version = result.get("protocolVersion", "unknown")
        
        # Extract capabilities
        capabilities = result.get("capabilities", {})
        
        # Process tools/methods
        tools = capabilities.get("tools", {})
        if isinstance(tools, dict):
            for method_name, method_spec in tools.items():
                self._process_mcp_method(method_name, method_spec)
        
        # Process resources if available
        resources = capabilities.get("resources", {})
        if isinstance(resources, dict):
            for resource_name, resource_spec in resources.items():
                # Resources can be exposed as methods too
                self._process_mcp_resource(resource_name, resource_spec)
        
        # Store raw capabilities for protocol generation
        self.capabilities = self._convert_to_protocol_capabilities()
    
    def _process_mcp_method(self, name: str, spec: Dict[str, Any]):
        """Process an MCP method specification."""
        self.mcp_capabilities[name] = MCPCapability(
            name=name,
            description=spec.get("description", f"MCP method {name}"),
            input_schema=spec.get("inputSchema", {"type": "object"}),
            output_schema=spec.get("outputSchema", {"type": "object"})
        )
    
    def _process_mcp_resource(self, name: str, spec: Dict[str, Any]):
        """Process an MCP resource specification."""
        # Create methods for resource operations
        resource_methods = {
            f"read_{name}": f"Read {name} resource",
            f"list_{name}": f"List {name} resources"
        }
        
        for method_name, description in resource_methods.items():
            self.mcp_capabilities[method_name] = MCPCapability(
                name=method_name,
                description=description,
                input_schema={"type": "object"},
                output_schema={"type": "object"}
            )
    
    def _convert_to_protocol_capabilities(self) -> Dict[str, Any]:
        """
        Convert MCP capabilities to format expected by protocol generation.
        """
        capabilities = {}
        
        for name, cap in self.mcp_capabilities.items():
            capabilities[name] = {
                "description": cap.description,
                "inputSchema": cap.input_schema,
                "outputSchema": cap.output_schema
            }
        
        return capabilities
    
    async def _send_jsonrpc_request(self, method: str, params: Any) -> Dict[str, Any]:
        """
        Send a JSON-RPC 2.0 request to the MCP service.
        """
        if not self._session:
            raise ProviderError("MCP provider not initialized")
        
        # Build JSON-RPC request
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params if params is not None else {}
        }
        
        try:
            # Send request
            async with self._session.post(
                self.mcp_endpoint,
                json=request,
                headers={"Content-Type": "application/json"}
            ) as response:
                response.raise_for_status()
                return await response.json()
                
        except aiohttp.ClientError as e:
            raise NetworkError(f"MCP request failed: {e}")
    
    async def execute(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a method by forwarding to the MCP service.
        
        Args:
            method: Method name to execute
            params: Parameters for the method
            
        Returns:
            Result from the MCP service
        """
        # Check if method is supported
        if method not in self.mcp_capabilities:
            available = ", ".join(self.mcp_capabilities.keys())
            raise ProviderError(
                f"Method '{method}' not supported by MCP service. "
                f"Available methods: {available}"
            )
        
        # Forward to MCP service
        try:
            response = await self._send_jsonrpc_request(method, params)
            
            if "error" in response:
                error = response["error"]
                raise ProviderError(
                    f"MCP method '{method}' failed: {error.get('message', 'Unknown error')}"
                )
            
            return response.get("result", {})
            
        except Exception as e:
            if isinstance(e, ProviderError):
                raise
            raise ProviderError(f"Failed to execute MCP method '{method}': {e}")
    
    def get_supported_methods(self) -> List[str]:
        """
        Return list of methods discovered from MCP service.
        """
        return list(self.mcp_capabilities.keys())
    
    async def health_check(self) -> bool:
        """
        Check if MCP service is healthy.
        """
        try:
            # Try a simple ping or info request
            response = await self._send_jsonrpc_request("ping", None)
            return "error" not in response
        except:
            return False
    
    def get_info(self) -> Dict[str, Any]:
        """
        Get information about the MCP provider.
        """
        info = super().get_info()
        info.update({
            "mcp_endpoint": self.mcp_endpoint,
            "mcp_version": self.mcp_version,
            "mcp_name": self.mcp_name,
            "discovered_methods": len(self.mcp_capabilities),
            "methods": list(self.mcp_capabilities.keys())
        })
        return info


class MCPFileSystemProvider(MCPProvider):
    """
    Specialized MCP provider for filesystem operations.
    
    Provides convenience methods for common filesystem operations
    while still auto-discovering all capabilities from the MCP service.
    """
    
    def __init__(self, mcp_endpoint: str, **kwargs):
        kwargs.setdefault('provider_id', 'mcp_filesystem')
        kwargs.setdefault('mcp_name', 'filesystem')
        super().__init__(mcp_endpoint, **kwargs)
    
    async def read_file(self, path: str) -> str:
        """Convenience method for reading files."""
        result = await self.execute("read_file", {"path": path})
        return result.get("content", "")
    
    async def write_file(self, path: str, content: str) -> bool:
        """Convenience method for writing files."""
        result = await self.execute("write_file", {"path": path, "content": content})
        return result.get("success", False)
    
    async def list_directory(self, path: str = ".") -> List[str]:
        """Convenience method for listing directories."""
        result = await self.execute("list_directory", {"path": path})
        return result.get("files", [])


class MCPSearchProvider(MCPProvider):
    """
    Specialized MCP provider for search operations.
    """
    
    def __init__(self, mcp_endpoint: str, **kwargs):
        kwargs.setdefault('provider_id', 'mcp_search')
        kwargs.setdefault('mcp_name', 'search')
        super().__init__(mcp_endpoint, **kwargs)
    
    async def search(self, query: str, **options) -> List[Dict[str, Any]]:
        """Convenience method for search."""
        params = {"query": query}
        params.update(options)
        result = await self.execute("search", params)
        return result.get("results", [])