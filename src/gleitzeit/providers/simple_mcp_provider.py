"""
Simple MCP Provider for testing
Implements MCP tools directly without subprocess
"""

from typing import Dict, List, Any
import logging
from gleitzeit.providers.base import ProtocolProvider

logger = logging.getLogger(__name__)


class SimpleMCPProvider(ProtocolProvider):
    """
    Simple MCP provider that implements tools directly
    No subprocess needed - perfect for testing
    """
    
    def __init__(self, provider_id: str = "simple-mcp"):
        super().__init__(
            provider_id=provider_id,
            protocol_id="mcp/v1",
            name="Simple MCP Provider",
            description="Direct MCP tool implementation for testing"
        )
        
        # Built-in tools
        self.tools = {
            "echo": self._tool_echo,
            "add": self._tool_add,
            "multiply": self._tool_multiply,
            "concat": self._tool_concat
        }
        
        logger.info(f"Initialized Simple MCP Provider with {len(self.tools)} tools")
    
    async def initialize(self) -> None:
        """Initialize provider"""
        logger.info(f"Simple MCP Provider {self.provider_id} ready")
    
    async def shutdown(self) -> None:
        """Cleanup provider"""
        logger.info(f"Simple MCP Provider {self.provider_id} shutdown")
    
    async def health_check(self) -> Dict[str, Any]:
        """Check provider health"""
        return {
            "status": "healthy",
            "details": f"Simple MCP provider with {len(self.tools)} tools",
            "tools": list(self.tools.keys())
        }
    
    def get_supported_methods(self) -> List[str]:
        """Return supported methods WITH protocol prefix as per documentation"""
        # All methods must have protocol prefix "mcp/"
        methods = ["mcp/tools/list", "mcp/server_info", "mcp/ping"]
        # Add tool methods with protocol prefix
        for tool_name in self.tools.keys():
            methods.append(f"mcp/tool.{tool_name}")
        return methods
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Handle incoming requests - strip mcp/ prefix like other providers"""
        logger.info(f"Simple MCP handling: {method}")
        
        # Strip protocol prefix if present (following pattern from ollama_provider.py)
        if method.startswith("mcp/"):
            method = method[4:]  # Remove "mcp/" prefix
        
        # Handle tool calls
        if method.startswith("tool."):
            tool_name = method[5:]  # Remove "tool." prefix
            return await self._execute_tool(tool_name, params)
        
        # Handle other methods
        if method == "list_tools":
            return {"tools": list(self.tools.keys())}
        
        elif method == "server_info":
            return {
                "name": self.name,
                "tools": list(self.tools.keys()),
                "provider_id": self.provider_id
            }
        
        else:
            raise ValueError(f"Unsupported method: {method}")
    
    async def _execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Any:
        """Execute a tool"""
        if tool_name not in self.tools:
            raise ValueError(f"Unknown tool: {tool_name}")
        
        # Get arguments from params
        arguments = params.get("arguments", params)
        
        # Execute tool
        tool_func = self.tools[tool_name]
        result = await tool_func(arguments)
        
        logger.info(f"Tool {tool_name} executed successfully")
        return result
    
    # Tool implementations
    async def _tool_echo(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Echo tool - returns the input message"""
        message = args.get("message", "")
        return {
            "response": message,
            "echoed": True,
            "length": len(message)
        }
    
    async def _tool_add(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Add tool - adds two numbers"""
        a = args.get("a", 0)
        b = args.get("b", 0)
        result = a + b
        return {
            "response": str(result),
            "result": result,
            "calculation": f"{a} + {b} = {result}"
        }
    
    async def _tool_multiply(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Multiply tool - multiplies two numbers"""
        a = args.get("a", 1)
        b = args.get("b", 1)
        result = a * b
        return {
            "response": str(result),
            "result": result,
            "calculation": f"{a} * {b} = {result}"
        }
    
    async def _tool_concat(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Concatenate tool - joins strings"""
        strings = args.get("strings", [])
        separator = args.get("separator", " ")
        
        if isinstance(strings, list):
            result = separator.join(str(s) for s in strings)
        else:
            result = str(strings)
        
        return {
            "response": result,
            "joined": True,
            "count": len(strings) if isinstance(strings, list) else 1
        }