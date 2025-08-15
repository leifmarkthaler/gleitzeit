#!/usr/bin/env python3
"""
Simple Python MCP server for testing Gleitzeit's MCP provider.
Implements basic MCP protocol over stdio with proper JSON-RPC handling.
"""

import sys
import json
import asyncio
from typing import Dict, Any, List
import logging

# Disable logging to avoid interfering with stdio
logging.disable(logging.CRITICAL)

class SimpleMCPServer:
    def __init__(self):
        self.tools = {
            "echo": {
                "name": "echo",
                "description": "Echo back the input",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string"}
                    }
                }
            },
            "add": {
                "name": "add",
                "description": "Add two numbers",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "a": {"type": "number"},
                        "b": {"type": "number"}
                    }
                }
            }
        }
        
        self.resources = {
            "test://resource": {
                "uri": "test://resource",
                "name": "Test Resource",
                "description": "A test resource"
            }
        }
        
        self.prompts = {
            "greeting": {
                "name": "greeting",
                "description": "Generate a greeting",
                "arguments": [
                    {"name": "name", "description": "Name to greet"}
                ]
            }
        }
    
    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle JSON-RPC request"""
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")
        
        try:
            if method == "initialize":
                result = await self.initialize(params)
            elif method == "tools/list":
                result = await self.list_tools()
            elif method == "tools/call":
                result = await self.call_tool(params)
            elif method == "resources/list":
                result = await self.list_resources()
            elif method == "resources/read":
                result = await self.read_resource(params)
            elif method == "prompts/list":
                result = await self.list_prompts()
            elif method == "prompts/get":
                result = await self.get_prompt(params)
            elif method == "ping":
                result = "pong"
            else:
                raise ValueError(f"Unknown method: {method}")
            
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
    
    async def initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Initialize MCP connection"""
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {},
                "resources": {},
                "prompts": {}
            },
            "serverInfo": {
                "name": "test-mcp-server",
                "version": "1.0.0"
            }
        }
    
    async def list_tools(self) -> Dict[str, Any]:
        """List available tools"""
        return {"tools": list(self.tools.values())}
    
    async def call_tool(self, params: Dict[str, Any]) -> Any:
        """Call a tool"""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        
        if tool_name == "echo":
            return {"message": arguments.get("message", "")}
        elif tool_name == "add":
            a = arguments.get("a", 0)
            b = arguments.get("b", 0)
            return {"result": a + b}
        else:
            raise ValueError(f"Unknown tool: {tool_name}")
    
    async def list_resources(self) -> Dict[str, Any]:
        """List available resources"""
        return {"resources": list(self.resources.values())}
    
    async def read_resource(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Read a resource"""
        uri = params.get("uri")
        if uri == "test://resource":
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "text/plain",
                        "text": "This is test resource content"
                    }
                ]
            }
        else:
            raise ValueError(f"Unknown resource: {uri}")
    
    async def list_prompts(self) -> Dict[str, Any]:
        """List available prompts"""
        return {"prompts": list(self.prompts.values())}
    
    async def get_prompt(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get a prompt"""
        name = params.get("name")
        arguments = params.get("arguments", {})
        
        if name == "greeting":
            user_name = arguments.get("name", "World")
            return {
                "description": f"Greeting for {user_name}",
                "messages": [
                    {
                        "role": "user",
                        "content": f"Hello, {user_name}!"
                    }
                ]
            }
        else:
            raise ValueError(f"Unknown prompt: {name}")
    
    def run(self):
        """Run the MCP server (synchronous for subprocess compatibility)"""
        # Ensure stdout is unbuffered
        sys.stdout = sys.stdout
        sys.stderr = sys.stderr
        
        while True:
            try:
                # Read line from stdin
                line = sys.stdin.readline()
                if not line:
                    break
                
                line = line.strip()
                if not line:
                    continue
                    
                # Parse JSON-RPC request
                try:
                    request = json.loads(line)
                except json.JSONDecodeError:
                    # Skip invalid JSON
                    continue
                
                # Handle request synchronously (run async in event loop)
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                response = loop.run_until_complete(self.handle_request(request))
                loop.close()
                
                # Send response immediately
                response_str = json.dumps(response)
                sys.stdout.write(response_str + "\n")
                sys.stdout.flush()
                
            except EOFError:
                break
            except KeyboardInterrupt:
                break
            except Exception:
                # Silently continue on any error
                continue

if __name__ == "__main__":
    server = SimpleMCPServer()
    server.run()