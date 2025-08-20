"""
MCP Hub Provider - Routes MCP requests through MCPHub
"""
import logging
from typing import Dict, List, Any, Optional

from gleitzeit.providers.base import ProtocolProvider
from gleitzeit.hub.mcp_hub import MCPHub
from gleitzeit.core.errors import MethodNotSupportedError, ProviderError, TaskExecutionError

logger = logging.getLogger(__name__)


class MCPHubProvider(ProtocolProvider):
    """
    MCP Provider that uses MCPHub for server management
    
    This provider acts as a bridge between Gleitzeit's protocol system
    and the MCP Hub, routing requests to appropriate MCP servers.
    """
    
    def __init__(
        self,
        provider_id: str = "mcp",
        hub: Optional[MCPHub] = None,
        config_data: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        super().__init__(
            provider_id=provider_id,
            protocol_id="mcp/v1",
            name="MCP Hub Provider",
            description="Routes MCP requests through MCPHub to external MCP servers",
            hub=hub,
            **kwargs
        )
        
        self.config_data = config_data or {}
        
        # Create hub if not provided
        if not self.hub:
            self.hub = MCPHub(
                auto_discover=True,
                config_data=self.config_data
            )
        
        logger.info(f"Initialized MCP Hub Provider: {provider_id}")
    
    async def initialize(self) -> None:
        """Initialize provider and hub"""
        await self.hub.initialize()
        
        # Log discovered servers and tools
        server_count = len(self.hub.instances)
        tool_count = len(self.hub.tool_registry)
        
        logger.info(f"MCP Hub Provider initialized with {server_count} servers and {tool_count} tools")
        
        if tool_count > 0:
            logger.info(f"Available MCP tools: {list(self.hub.tool_registry.keys())[:10]}...")
    
    async def shutdown(self) -> None:
        """Cleanup provider and hub"""
        logger.info(f"Shutting down MCP Hub Provider {self.provider_id}")
        await self.hub.cleanup()
    
    async def health_check(self) -> bool:
        """Check provider health"""
        # Provider is healthy if at least one MCP server is available
        return len(self.hub.instances) > 0
    
    def get_supported_methods(self) -> List[str]:
        """Return all available MCP methods"""
        methods = [
            "mcp/tools/list",
            "mcp/servers",
            "mcp/server_info",
            "mcp/ping"
        ]
        
        # Add all discovered tools as methods
        for tool_name in self.hub.tool_registry.keys():
            methods.append(f"mcp/tool.{tool_name}")
        
        return methods
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Handle MCP requests by routing through hub"""
        logger.info(f"MCP Hub Provider handling: {method}")
        
        # Strip protocol prefix if present
        if method.startswith("mcp/"):
            method = method[4:]
        
        try:
            # Handle tool calls
            if method.startswith("tool."):
                tool_name = method[5:]
                return await self._handle_tool_call(tool_name, params)
            
            # Handle meta methods
            elif method == "tools/list":
                return await self._handle_tools_list()
            
            elif method == "servers":
                return await self._handle_servers_list()
            
            elif method == "server_info":
                return await self._handle_server_info(params)
            
            elif method == "ping":
                return await self._handle_ping()
            
            else:
                raise MethodNotSupportedError(method, self.provider_id)
                
        except Exception as e:
            logger.error(f"MCP request failed: {method} - {e}")
            raise TaskExecutionError(
                task_id=f"mcp_{method}",
                message=str(e)
            )
    
    async def _handle_tool_call(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tool execution"""
        # Get arguments from params
        arguments = params.get("arguments", params)
        
        # Get specific instance if requested
        instance_id = params.get("_instance_id")
        
        try:
            # Call tool through hub
            result = await self.hub.call_tool(tool_name, arguments, instance_id)
            
            # Return standardized response
            return {
                "response": result,
                "tool": tool_name,
                "provider_id": self.provider_id,
                "success": True
            }
            
        except ValueError as e:
            # Tool or server not found
            logger.error(f"Tool not found: {tool_name} - {e}")
            
            # Return list of available tools with similar names
            available = [t for t in self.hub.tool_registry.keys() if tool_name.lower() in t.lower()]
            
            return {
                "error": str(e),
                "available_tools": available[:10],  # Limit suggestions
                "provider_id": self.provider_id,
                "success": False
            }
    
    async def _handle_tools_list(self) -> Dict[str, Any]:
        """Return all available tools from all servers"""
        all_tools = []
        
        for instance in self.hub.instances.values():
            for tool_name, tool_info in instance.available_tools.items():
                all_tools.append({
                    "name": tool_name,
                    "description": tool_info.get("description", ""),
                    "inputSchema": tool_info.get("inputSchema", {}),
                    "server": instance.config.name,
                    "instance_id": instance.instance_id
                })
        
        return {
            "tools": all_tools,
            "count": len(all_tools),
            "servers": len(self.hub.instances),
            "provider_id": self.provider_id
        }
    
    async def _handle_servers_list(self) -> Dict[str, Any]:
        """Return information about all MCP servers"""
        servers = []
        
        for instance in self.hub.instances.values():
            servers.append({
                "id": instance.instance_id,
                "name": instance.config.name,
                "status": instance.status.value,
                "connection_type": instance.config.connection_type,
                "tools": list(instance.available_tools.keys()),
                "tool_count": len(instance.available_tools),
                "healthy": await instance.health_check()
            })
        
        return {
            "servers": servers,
            "count": len(servers),
            "provider_id": self.provider_id
        }
    
    async def _handle_server_info(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get detailed info about a specific server"""
        instance_id = params.get("instance_id") or params.get("server_id")
        
        if not instance_id:
            # Return info about the provider itself
            return {
                "name": self.name,
                "provider_id": self.provider_id,
                "protocol": self.protocol_id,
                "servers": len(self.hub.instances),
                "tools": len(self.hub.tool_registry),
                "status": "active"
            }
        
        instance = self.hub.instances.get(instance_id)
        if not instance:
            raise ValueError(f"Server not found: {instance_id}")
        
        return {
            "id": instance.instance_id,
            "name": instance.config.name,
            "status": instance.status.value,
            "connection_type": instance.config.connection_type,
            "config": {
                "command": instance.config.command,
                "url": instance.config.url,
                "tool_prefix": instance.config.tool_prefix,
                "auto_start": instance.config.auto_start,
                "restart_on_failure": instance.config.restart_on_failure
            },
            "tools": instance.available_tools,
            "healthy": await instance.health_check(),
            "restart_count": instance.restart_count
        }
    
    async def _handle_ping(self) -> Dict[str, Any]:
        """Ping all servers and return results"""
        results = {}
        
        for instance in self.hub.instances.values():
            try:
                healthy = await instance.health_check()
                results[instance.instance_id] = {
                    "name": instance.config.name,
                    "healthy": healthy,
                    "status": instance.status.value
                }
            except Exception as e:
                results[instance.instance_id] = {
                    "name": instance.config.name,
                    "healthy": False,
                    "error": str(e)
                }
        
        return {
            "servers": results,
            "healthy_count": sum(1 for r in results.values() if r.get("healthy")),
            "total_count": len(results),
            "provider_id": self.provider_id
        }
    
    async def __aenter__(self) -> 'MCPHubProvider':
        """Async context manager entry"""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit"""
        await self.shutdown()