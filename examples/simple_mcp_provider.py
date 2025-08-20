"""
Example: Simple MCP Provider Implementation
This is a reference implementation showing how to create a basic MCP provider
that implements tools directly without requiring external servers.

This can be useful for:
- Testing MCP workflows without external dependencies
- Learning how MCP providers work
- Creating custom in-process MCP tools
"""

from typing import Dict, List, Any, Optional, Type
import logging

# Note: In a real implementation, you'd import from gleitzeit
# from gleitzeit.providers.base import ProtocolProvider
# from gleitzeit.core.errors import MethodNotSupportedError, InvalidParameterError, TaskExecutionError

logger = logging.getLogger(__name__)


class SimpleMCPProvider:
    """
    Simple MCP provider that implements tools directly
    No subprocess needed - perfect for testing and demos
    
    This example shows how to:
    1. Implement MCP tools as Python methods
    2. Handle MCP protocol methods (tools/list, ping, etc.)
    3. Provide a zero-configuration MCP experience
    """
    
    def __init__(
        self, 
        provider_id: str = "simple-mcp",
        **kwargs
    ):
        self.provider_id = provider_id
        self.protocol_id = "mcp/v1"
        self.name = "Simple MCP Provider"
        self.description = "Direct MCP tool implementation for testing"
        
        # Built-in tools - each tool is a method
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
    
    async def health_check(self) -> bool:
        """Check provider health"""
        return True
    
    def get_supported_methods(self) -> List[str]:
        """Return supported methods WITH protocol prefix"""
        methods = ["mcp/tools/list", "mcp/server_info", "mcp/ping"]
        # Add tool methods with protocol prefix
        for tool_name in self.tools.keys():
            methods.append(f"mcp/tool.{tool_name}")
        return methods
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Handle incoming MCP requests"""
        logger.info(f"Simple MCP handling: {method}")
        
        # Strip protocol prefix if present
        if method.startswith("mcp/"):
            method = method[4:]  # Remove "mcp/" prefix
        
        # Handle tool calls
        if method.startswith("tool."):
            tool_name = method[5:]  # Remove "tool." prefix
            return await self._execute_tool(tool_name, params)
        
        # Handle meta methods
        if method == "tools/list":
            return await self._handle_tools_list()
        
        elif method == "server_info":
            return {
                "name": self.name,
                "tools": list(self.tools.keys()),
                "provider_id": self.provider_id
            }
        
        elif method == "ping":
            return "pong"
        
        else:
            raise ValueError(f"Method not supported: {method}")
    
    async def _handle_tools_list(self) -> Dict[str, Any]:
        """Return list of available tools in MCP format"""
        tools = []
        for name, func in self.tools.items():
            tools.append({
                "name": name,
                "description": func.__doc__ or f"Tool: {name}",
                "inputSchema": {
                    "type": "object",
                    "properties": self._get_tool_schema(name)
                }
            })
        
        return {
            "tools": tools,
            "count": len(tools)
        }
    
    def _get_tool_schema(self, tool_name: str) -> Dict[str, Any]:
        """Get input schema for a tool"""
        schemas = {
            "echo": {
                "message": {"type": "string", "description": "Message to echo"}
            },
            "add": {
                "a": {"type": "number", "description": "First number"},
                "b": {"type": "number", "description": "Second number"}
            },
            "multiply": {
                "a": {"type": "number", "description": "First number"},
                "b": {"type": "number", "description": "Second number"}
            },
            "concat": {
                "strings": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Strings to concatenate"
                },
                "separator": {
                    "type": "string",
                    "description": "Separator between strings",
                    "default": " "
                }
            }
        }
        return schemas.get(tool_name, {})
    
    async def _execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Any:
        """Execute a tool"""
        if tool_name not in self.tools:
            raise ValueError(f"Unknown tool: {tool_name}")
        
        # Get arguments from params
        arguments = params.get("arguments", params)
        
        try:
            # Execute tool
            tool_func = self.tools[tool_name]
            result = await tool_func(arguments)
            
            logger.info(f"Tool {tool_name} executed successfully")
            return result
            
        except Exception as e:
            error_msg = f"MCP tool '{tool_name}' failed: {str(e)}"
            logger.error(error_msg)
            raise ValueError(error_msg)
    
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
        
        # Validate inputs are numeric
        try:
            a = float(a) if not isinstance(a, (int, float)) else a
            b = float(b) if not isinstance(b, (int, float)) else b
        except (ValueError, TypeError):
            raise ValueError(f"Invalid numeric inputs: a={args.get('a')}, b={args.get('b')}")
        
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
        
        # Validate inputs are numeric
        try:
            a = float(a) if not isinstance(a, (int, float)) else a
            b = float(b) if not isinstance(b, (int, float)) else b
        except (ValueError, TypeError):
            raise ValueError(f"Invalid numeric inputs: a={args.get('a')}, b={args.get('b')}")
        
        result = a * b
        return {
            "response": str(result),
            "result": result,
            "calculation": f"{a} * {b} = {result}"
        }
    
    async def _tool_concat(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Concatenate tool - joins strings"""
        # Support both formats: {strings: [...]} and {a: "...", b: "..."}
        if "a" in args and "b" in args:
            # Simple two-string concatenation
            a = str(args.get("a", ""))
            b = str(args.get("b", ""))
            result = a + b
            return {
                "response": result,
                "joined": True,
                "count": 2
            }
        else:
            # List-based concatenation
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
    
    async def __aenter__(self) -> 'SimpleMCPProvider':
        """Async context manager entry"""
        await self.initialize()
        return self
    
    async def __aexit__(self, 
                         exc_type: Optional[Type[BaseException]], 
                         exc_val: Optional[BaseException], 
                         exc_tb: Optional[Any]) -> None:
        """Async context manager exit"""
        await self.shutdown()


# Example usage
if __name__ == "__main__":
    import asyncio
    
    async def demo():
        """Demonstrate the Simple MCP Provider"""
        provider = SimpleMCPProvider()
        await provider.initialize()
        
        # List tools
        tools_response = await provider.handle_request("mcp/tools/list", {})
        print("Available tools:")
        for tool in tools_response["tools"]:
            print(f"  - {tool['name']}: {tool['description']}")
        
        # Test echo tool
        echo_result = await provider.handle_request(
            "mcp/tool.echo",
            {"message": "Hello, MCP!"}
        )
        print(f"\nEcho result: {echo_result}")
        
        # Test add tool
        add_result = await provider.handle_request(
            "mcp/tool.add",
            {"a": 10, "b": 20}
        )
        print(f"Add result: {add_result}")
        
        # Test multiply tool
        multiply_result = await provider.handle_request(
            "mcp/tool.multiply",
            {"a": 5, "b": 6}
        )
        print(f"Multiply result: {multiply_result}")
        
        # Test concat tool
        concat_result = await provider.handle_request(
            "mcp/tool.concat",
            {"strings": ["Hello", " ", "World"], "separator": ""}
        )
        print(f"Concat result: {concat_result}")
        
        await provider.shutdown()
    
    asyncio.run(demo())