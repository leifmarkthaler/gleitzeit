"""
MCP Provider for Gleitzeit V2

Handles Model Context Protocol (MCP) server connections and function execution.
"""

import asyncio
import json
import logging
import subprocess
import sys
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import socketio
from pathlib import Path

from ..core.models import TaskType, Task, TaskStatus

logger = logging.getLogger(__name__)


@dataclass
class MCPServer:
    """MCP Server configuration"""
    name: str
    command: List[str]  # Command to start server (for stdio)
    transport: str = "stdio"  # stdio or http
    url: Optional[str] = None  # For HTTP transport
    process: Optional[subprocess.Popen] = None
    available_functions: List[str] = field(default_factory=list)
    

class MCPServerManager:
    """Manages connections to MCP servers"""
    
    def __init__(self):
        self.servers: Dict[str, MCPServer] = {}
        self.active_connections: Dict[str, Any] = {}
        
    async def add_server(self, server: MCPServer):
        """Add and connect to an MCP server"""
        self.servers[server.name] = server
        
        if server.transport == "stdio":
            await self._connect_stdio_server(server)
        elif server.transport == "http":
            await self._connect_http_server(server)
        else:
            raise ValueError(f"Unknown transport: {server.transport}")
            
        logger.info(f"✅ Connected to MCP server: {server.name}")
        
    async def _connect_stdio_server(self, server: MCPServer):
        """Connect to stdio-based MCP server"""
        try:
            # Start the MCP server process
            server.process = subprocess.Popen(
                server.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Send initialization
            init_request = {
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "0.1.0",
                    "capabilities": {}
                },
                "id": 1
            }
            
            server.process.stdin.write(json.dumps(init_request) + "\n")
            server.process.stdin.flush()
            
            # Read response
            response = server.process.stdout.readline()
            if response:
                result = json.loads(response)
                
                # Discover available tools/functions
                if "result" in result and "capabilities" in result["result"]:
                    await self._discover_functions(server)
                    
        except Exception as e:
            logger.error(f"Failed to connect to {server.name}: {e}")
            raise
            
    async def _connect_http_server(self, server: MCPServer):
        """Connect to HTTP-based MCP server"""
        # TODO: Implement HTTP connection
        pass
        
    async def _discover_functions(self, server: MCPServer):
        """Discover available functions from MCP server"""
        try:
            # Send tools/list request
            list_request = {
                "jsonrpc": "2.0",
                "method": "tools/list",
                "params": {},
                "id": 2
            }
            
            server.process.stdin.write(json.dumps(list_request) + "\n")
            server.process.stdin.flush()
            
            response = server.process.stdout.readline()
            if response:
                result = json.loads(response)
                if "result" in result and "tools" in result["result"]:
                    tools = result["result"]["tools"]
                    server.available_functions = [tool["name"] for tool in tools]
                    logger.info(f"Discovered {len(server.available_functions)} functions in {server.name}")
                    
        except Exception as e:
            logger.error(f"Failed to discover functions from {server.name}: {e}")
            
    async def execute_function(self, server_name: str, function_name: str, arguments: Dict[str, Any]) -> Any:
        """Execute a function on an MCP server"""
        if server_name not in self.servers:
            raise ValueError(f"Server not found: {server_name}")
            
        server = self.servers[server_name]
        
        if server.transport == "stdio":
            return await self._execute_stdio_function(server, function_name, arguments)
        elif server.transport == "http":
            return await self._execute_http_function(server, function_name, arguments)
            
    async def _execute_stdio_function(self, server: MCPServer, function_name: str, arguments: Dict[str, Any]) -> Any:
        """Execute function via stdio"""
        try:
            # Create function call request
            call_request = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": function_name,
                    "arguments": arguments
                },
                "id": 3
            }
            
            server.process.stdin.write(json.dumps(call_request) + "\n")
            server.process.stdin.flush()
            
            # Read response
            response = server.process.stdout.readline()
            if response:
                result = json.loads(response)
                if "result" in result:
                    # Extract content from MCP response format
                    mcp_result = result["result"]
                    if isinstance(mcp_result, dict) and "content" in mcp_result:
                        # Extract text content from MCP format
                        content = mcp_result["content"]
                        if isinstance(content, list) and len(content) > 0:
                            first_content = content[0]
                            if isinstance(first_content, dict) and "text" in first_content:
                                return first_content["text"]
                    return mcp_result
                elif "error" in result:
                    raise RuntimeError(f"MCP error: {result['error']}")
                    
        except Exception as e:
            logger.error(f"Failed to execute {function_name} on {server.name}: {e}")
            raise
            
    async def _execute_http_function(self, server: MCPServer, function_name: str, arguments: Dict[str, Any]) -> Any:
        """Execute function via HTTP"""
        # TODO: Implement HTTP execution
        pass
        
    async def close_all(self):
        """Close all server connections"""
        for server in self.servers.values():
            if server.process:
                server.process.terminate()
                await asyncio.sleep(0.5)
                if server.process.poll() is None:
                    server.process.kill()
                    

class MCPProvider:
    """
    MCP Provider for Gleitzeit V2
    
    Handles MCP function execution through the provider-executor model.
    """
    
    def __init__(
        self,
        provider_id: str = "mcp_provider",
        provider_name: str = "MCP Function Provider",
        server_url: str = "http://localhost:8000",
        max_concurrent: int = 10
    ):
        self.provider_id = provider_id
        self.provider_name = provider_name
        self.server_url = server_url
        self.max_concurrent = max_concurrent
        
        # Socket.IO client
        self.sio = socketio.AsyncClient()
        self.connected = False
        self.registered = False
        
        # MCP server manager
        self.server_manager = MCPServerManager()
        
        # Task tracking
        self.current_tasks = 0
        
        # Setup handlers
        self._setup_handlers()
        
        logger.info(f"MCPProvider initialized: {provider_name}")
        
    def _setup_handlers(self):
        """Setup Socket.IO event handlers"""
        
        @self.sio.event
        async def connect():
            self.connected = True
            logger.info("✅ Connected to central Socket.IO server")
            
            # Register as provider
            await self._register_provider()
            
        @self.sio.event
        async def disconnect():
            self.connected = False
            self.registered = False
            logger.info("🔌 Disconnected from central Socket.IO server")
            
        @self.sio.on('provider:registered')
        async def provider_registered(data):
            self.registered = True
            logger.info(f"✅ Provider registered: {data.get('provider_id')}")
            
        @self.sio.on('task:assign')
        async def task_assign(data):
            """Handle task assignment"""
            task_id = data.get('task_id')
            task_type = data.get('task_type')
            logger.info(f"📋 Received MCP task: {task_id} (type: {task_type})")
            
            # Process task in background
            asyncio.create_task(self._process_task(data))
            
        @self.sio.event
        async def error(data):
            message = data.get('message', 'Unknown error')
            logger.error(f"Server error: {message}")
            
    async def start(self):
        """Start the provider"""
        try:
            # Initialize default MCP servers
            await self._initialize_default_servers()
            
            # Connect to Gleitzeit server
            await self.sio.connect(self.server_url)
            
            logger.info("🚀 MCP provider started")
            
        except Exception as e:
            logger.error(f"Failed to start MCP provider: {e}")
            raise
            
    async def stop(self):
        """Stop the provider"""
        # Close MCP servers
        await self.server_manager.close_all()
        
        # Disconnect from Gleitzeit
        if self.connected:
            await self.sio.disconnect()
            
        logger.info("🛑 MCP provider stopped")
        
    async def _initialize_default_servers(self):
        """Initialize default MCP servers"""
        # Try our simple Python MCP server first
        simple_server_path = Path("./simple_mcp_server.py")
        if simple_server_path.exists():
            simple_server = MCPServer(
                name="filesystem",
                command=[sys.executable, str(simple_server_path)],
                transport="stdio"
            )
            try:
                await self.server_manager.add_server(simple_server)
                logger.info("✅ Connected to simple MCP server")
            except Exception as e:
                logger.warning(f"Could not connect to simple MCP server: {e}")
        
        # Check if filesystem MCP server is available
        filesystem_path = Path("./mcp-filesystem")
        if filesystem_path.exists() and "filesystem" not in self.server_manager.servers:
            filesystem_server = MCPServer(
                name="filesystem",
                command=["node", str(filesystem_path)],
                transport="stdio"
            )
            try:
                await self.server_manager.add_server(filesystem_server)
            except Exception as e:
                logger.warning(f"Could not connect to Node.js MCP server: {e}")
            
        # Add more default servers as needed
        logger.info(f"Initialized {len(self.server_manager.servers)} MCP servers")
        
    async def _register_provider(self):
        """Register with the Gleitzeit server"""
        # Collect all available functions
        all_functions = []
        for server in self.server_manager.servers.values():
            for func in server.available_functions:
                all_functions.append(f"{server.name}.{func}")
                
        capabilities = {
            'task_types': [
                TaskType.MCP_FUNCTION.value,
                TaskType.MCP_QUERY.value,
                TaskType.MCP_TOOL.value
            ],
            'max_concurrent': self.max_concurrent,
            'features': ['function_discovery', 'batch_operations'] + all_functions
        }
        
        await self.sio.emit('provider:register', {
            'provider': {
                'id': self.provider_id,
                'name': self.provider_name,
                'type': 'mcp',
                'capabilities': capabilities
            }
        })
        
    async def _process_task(self, task_data: Dict[str, Any]):
        """Process assigned MCP task"""
        task_id = task_data.get('task_id')
        workflow_id = task_data.get('workflow_id')
        task_type = task_data.get('task_type')
        parameters = task_data.get('parameters', {})
        
        if not workflow_id:
            logger.error(f"❌ Task {task_id} has no workflow_id - cannot process")
            return
        
        try:
            self.current_tasks += 1
            
            # Acknowledge task
            await self.sio.emit('task:accepted', {
                'task_id': task_id,
                'provider_id': self.provider_id,
                'workflow_id': workflow_id
            })
            
            logger.info(f"🔄 Processing MCP task: {task_id} (type: {task_type})")
            
            # Route to appropriate handler
            if task_type == TaskType.MCP_FUNCTION.value:
                result = await self._execute_mcp_function(parameters)
            elif task_type == TaskType.MCP_QUERY.value:
                result = await self._execute_mcp_query(parameters)
            elif task_type == TaskType.MCP_TOOL.value:
                result = await self._execute_mcp_tool(parameters)
            else:
                raise ValueError(f"Unsupported task type: {task_type}")
                
            # Report success
            completion_data = {
                'task_id': task_id,
                'workflow_id': workflow_id,
                'provider_id': self.provider_id,
                'result': result
            }
            logger.info(f"🚀 Sending task:completed event for {task_id} with data: {completion_data}")
            await self.sio.emit('task:completed', completion_data)
            logger.info(f"✅ MCP task completed event sent for: {task_id}")
            
        except Exception as e:
            logger.error(f"❌ MCP task failed: {task_id} - {e}")
            
            # Report failure
            await self.sio.emit('task:failed', {
                'task_id': task_id,
                'workflow_id': workflow_id,
                'provider_id': self.provider_id,
                'error': str(e)
            })
            
        finally:
            self.current_tasks = max(0, self.current_tasks - 1)
            
    async def _execute_mcp_function(self, parameters: Dict[str, Any]) -> Any:
        """Execute MCP function"""
        server_name = parameters.get('server')
        function_name = parameters.get('function')
        arguments = parameters.get('arguments', {})
        
        if not server_name or not function_name:
            raise ValueError("Server and function name required")
            
        result = await self.server_manager.execute_function(
            server_name, function_name, arguments
        )
        
        return result
        
    async def _execute_mcp_query(self, parameters: Dict[str, Any]) -> Any:
        """Execute MCP query"""
        # Similar to function but for query-type operations
        return await self._execute_mcp_function(parameters)
        
    async def _execute_mcp_tool(self, parameters: Dict[str, Any]) -> Any:
        """Execute MCP tool"""
        # Similar to function but for tool-type operations
        return await self._execute_mcp_function(parameters)


async def main():
    """Main entry point for MCP provider"""
    import argparse
    
    parser = argparse.ArgumentParser(description="MCP Provider for Gleitzeit V2")
    parser.add_argument('--server-url', default='http://localhost:8000',
                       help='Gleitzeit server URL')
    parser.add_argument('--provider-id', default='mcp_provider',
                       help='Provider ID')
    parser.add_argument('--verbose', action='store_true',
                       help='Verbose logging')
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(levelname)s:%(name)s:%(message)s'
    )
    
    # Create and start provider
    provider = MCPProvider(
        provider_id=args.provider_id,
        server_url=args.server_url
    )
    
    try:
        await provider.start()
        
        # Keep running
        while True:
            await asyncio.sleep(10)
            
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await provider.stop()


if __name__ == '__main__':
    asyncio.run(main())