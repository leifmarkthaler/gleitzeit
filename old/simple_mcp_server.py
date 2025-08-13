#!/usr/bin/env python3
"""
Simple MCP Server - File System Operations

A minimal MCP server that provides file system operations like ls.
Communicates via stdio using JSON-RPC protocol.
"""

import json
import sys
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
import traceback


class SimpleMCPServer:
    """Simple MCP server with file system operations"""
    
    def __init__(self):
        self.request_id = 0
        self.initialized = False
        self.tools = [
            {
                "name": "list_files",
                "description": "List files and directories in a given path",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to list (default: current directory)"
                        },
                        "show_hidden": {
                            "type": "boolean",
                            "description": "Show hidden files (default: false)"
                        }
                    }
                }
            },
            {
                "name": "read_file",
                "description": "Read contents of a file",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the file to read"
                        },
                        "max_lines": {
                            "type": "integer",
                            "description": "Maximum number of lines to read (default: 100)"
                        }
                    },
                    "required": ["path"]
                }
            },
            {
                "name": "get_file_info",
                "description": "Get information about a file or directory",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to get info for"
                        }
                    },
                    "required": ["path"]
                }
            }
        ]
        
    def send_response(self, response: Dict[str, Any]):
        """Send JSON-RPC response to stdout"""
        json_response = json.dumps(response)
        sys.stdout.write(json_response + "\n")
        sys.stdout.flush()
        
    def send_error(self, id: Any, code: int, message: str, data: Any = None):
        """Send JSON-RPC error response"""
        error = {
            "jsonrpc": "2.0",
            "id": id,
            "error": {
                "code": code,
                "message": message
            }
        }
        if data is not None:
            error["error"]["data"] = data
        self.send_response(error)
        
    def handle_initialize(self, request: Dict[str, Any]):
        """Handle initialize request"""
        self.initialized = True
        
        response = {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {
                "protocolVersion": "0.1.0",
                "capabilities": {
                    "tools": {
                        "listChanged": True
                    },
                    "prompts": {
                        "listChanged": False
                    }
                },
                "serverInfo": {
                    "name": "simple-mcp-server",
                    "version": "1.0.0"
                }
            }
        }
        self.send_response(response)
        
    def handle_tools_list(self, request: Dict[str, Any]):
        """Handle tools/list request"""
        response = {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {
                "tools": self.tools
            }
        }
        self.send_response(response)
        
    def handle_tools_call(self, request: Dict[str, Any]):
        """Handle tools/call request"""
        params = request.get("params", {})
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        
        try:
            if tool_name == "list_files":
                result = self.list_files(arguments)
            elif tool_name == "read_file":
                result = self.read_file(arguments)
            elif tool_name == "get_file_info":
                result = self.get_file_info(arguments)
            else:
                self.send_error(
                    request.get("id"),
                    -32601,
                    f"Unknown tool: {tool_name}"
                )
                return
                
            response = {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2)
                        }
                    ]
                }
            }
            self.send_response(response)
            
        except Exception as e:
            self.send_error(
                request.get("id"),
                -32603,
                str(e),
                {"traceback": traceback.format_exc()}
            )
            
    def list_files(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List files and directories"""
        path_str = arguments.get("path", ".")
        show_hidden = arguments.get("show_hidden", False)
        
        path = Path(path_str)
        if not path.exists():
            return {"error": f"Path does not exist: {path_str}"}
            
        if not path.is_dir():
            return {"error": f"Path is not a directory: {path_str}"}
            
        files = []
        directories = []
        
        for item in path.iterdir():
            if not show_hidden and item.name.startswith("."):
                continue
                
            item_info = {
                "name": item.name,
                "path": str(item),
                "size": item.stat().st_size if item.is_file() else None,
                "modified": item.stat().st_mtime
            }
            
            if item.is_dir():
                directories.append(item_info)
            else:
                files.append(item_info)
                
        return {
            "path": str(path.absolute()),
            "directories": sorted(directories, key=lambda x: x["name"]),
            "files": sorted(files, key=lambda x: x["name"]),
            "total_items": len(files) + len(directories)
        }
        
    def read_file(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Read file contents"""
        path_str = arguments.get("path")
        max_lines = arguments.get("max_lines", 100)
        
        if not path_str:
            return {"error": "Path is required"}
            
        path = Path(path_str)
        if not path.exists():
            return {"error": f"File does not exist: {path_str}"}
            
        if not path.is_file():
            return {"error": f"Path is not a file: {path_str}"}
            
        try:
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()[:max_lines]
                content = ''.join(lines)
                
            return {
                "path": str(path.absolute()),
                "content": content,
                "lines_read": len(lines),
                "truncated": len(lines) == max_lines
            }
        except Exception as e:
            return {"error": f"Failed to read file: {e}"}
            
    def get_file_info(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get file or directory information"""
        path_str = arguments.get("path")
        
        if not path_str:
            return {"error": "Path is required"}
            
        path = Path(path_str)
        if not path.exists():
            return {"error": f"Path does not exist: {path_str}"}
            
        stat = path.stat()
        
        info = {
            "path": str(path.absolute()),
            "name": path.name,
            "type": "directory" if path.is_dir() else "file",
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "created": stat.st_ctime,
            "permissions": oct(stat.st_mode)[-3:],
            "owner_uid": stat.st_uid,
            "group_gid": stat.st_gid
        }
        
        if path.is_dir():
            try:
                items = list(path.iterdir())
                info["item_count"] = len(items)
            except:
                info["item_count"] = "Permission denied"
                
        return info
        
    def handle_request(self, request: Dict[str, Any]):
        """Handle incoming JSON-RPC request"""
        method = request.get("method")
        
        if method == "initialize":
            self.handle_initialize(request)
        elif method == "tools/list":
            self.handle_tools_list(request)
        elif method == "tools/call":
            self.handle_tools_call(request)
        else:
            self.send_error(
                request.get("id"),
                -32601,
                f"Method not found: {method}"
            )
            
    def run(self):
        """Main server loop - read from stdin, write to stdout"""
        sys.stderr.write("Simple MCP Server started\n")
        sys.stderr.flush()
        
        while True:
            try:
                # Read line from stdin
                line = sys.stdin.readline()
                if not line:
                    break
                    
                # Parse JSON-RPC request
                try:
                    request = json.loads(line.strip())
                    self.handle_request(request)
                except json.JSONDecodeError as e:
                    self.send_error(
                        None,
                        -32700,
                        f"Parse error: {e}"
                    )
                    
            except KeyboardInterrupt:
                sys.stderr.write("\nServer interrupted\n")
                break
            except Exception as e:
                sys.stderr.write(f"Server error: {e}\n")
                sys.stderr.write(traceback.format_exc())
                

if __name__ == "__main__":
    server = SimpleMCPServer()
    server.run()