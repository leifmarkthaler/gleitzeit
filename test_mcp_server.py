#!/usr/bin/env python3
"""
Simple MCP Server for Testing

A minimal MCP server that implements the protocol for testing purposes.
Communicates via stdio (stdin/stdout) using JSON-RPC.
"""
import sys
import json
import asyncio
from typing import Dict, Any


class TestMCPServer:
    """Test MCP Server with basic tools"""
    
    def __init__(self):
        self.tools = {
            "echo": "Echo back the input message",
            "reverse": "Reverse a string",
            "uppercase": "Convert string to uppercase",
            "add_numbers": "Add two numbers together"
        }
    
    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle JSON-RPC request"""
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")
        
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {
                        "name": "test-mcp-server",
                        "version": "1.0.0"
                    },
                    "capabilities": {
                        "tools": {}
                    }
                }
            
            elif method == "tools/list":
                result = {
                    "tools": [
                        {
                            "name": name,
                            "description": desc,
                            "inputSchema": {
                                "type": "object",
                                "properties": self._get_tool_schema(name)
                            }
                        }
                        for name, desc in self.tools.items()
                    ]
                }
            
            elif method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {})
                result = await self._call_tool(tool_name, arguments)
            
            elif method == "ping":
                result = "pong"
            
            else:
                raise Exception(f"Unknown method: {method}")
            
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            }
            
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }
    
    def _get_tool_schema(self, tool_name: str) -> Dict[str, Any]:
        """Get input schema for a tool"""
        if tool_name == "echo":
            return {
                "message": {"type": "string", "description": "Message to echo"}
            }
        elif tool_name == "reverse":
            return {
                "text": {"type": "string", "description": "Text to reverse"}
            }
        elif tool_name == "uppercase":
            return {
                "text": {"type": "string", "description": "Text to convert"}
            }
        elif tool_name == "add_numbers":
            return {
                "a": {"type": "number", "description": "First number"},
                "b": {"type": "number", "description": "Second number"}
            }
        return {}
    
    async def _call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Execute a tool"""
        if tool_name == "echo":
            message = arguments.get("message", "")
            return {
                "output": message,
                "echoed": True
            }
        
        elif tool_name == "reverse":
            text = arguments.get("text", "")
            return {
                "output": text[::-1],
                "original": text
            }
        
        elif tool_name == "uppercase":
            text = arguments.get("text", "")
            return {
                "output": text.upper(),
                "original": text
            }
        
        elif tool_name == "add_numbers":
            a = arguments.get("a", 0)
            b = arguments.get("b", 0)
            return {
                "result": a + b,
                "calculation": f"{a} + {b} = {a + b}"
            }
        
        else:
            raise Exception(f"Unknown tool: {tool_name}")
    
    async def run(self):
        """Run the server, reading from stdin and writing to stdout"""
        sys.stderr.write("Test MCP Server started\n")
        sys.stderr.flush()
        
        while True:
            try:
                # Read line from stdin
                line = sys.stdin.readline()
                if not line:
                    break
                
                # Parse JSON-RPC request
                request = json.loads(line.strip())
                sys.stderr.write(f"Received: {request.get('method')}\n")
                sys.stderr.flush()
                
                # Handle request
                response = await self.handle_request(request)
                
                # Send response
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
                
            except Exception as e:
                sys.stderr.write(f"Error: {e}\n")
                sys.stderr.flush()


async def main():
    """Main entry point"""
    server = TestMCPServer()
    await server.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.stderr.write("\nServer stopped\n")
        sys.stderr.flush()