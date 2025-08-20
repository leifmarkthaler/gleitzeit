"""
MCP Hub - Manages multiple MCP (Model Context Protocol) server instances
"""
import asyncio
import json
import os
import logging
from typing import Dict, List, Any, Optional, Set, Tuple
from datetime import datetime
import aiohttp

from .base import ResourceHub, ResourceInstance, ResourceStatus, ResourceMetrics, ResourceType
from .configs import MCPConfig

logger = logging.getLogger(__name__)


class MCPInstance(ResourceInstance[MCPConfig]):
    """Represents a single MCP server instance"""
    
    def __init__(self, instance_id: str, config: MCPConfig, hub_id: str):
        # MCPInstance doesn't have a traditional endpoint, use name or URL
        endpoint = config.url if config.url else config.name
        super().__init__(instance_id, config, hub_id, endpoint=endpoint)
        self.available_tools: Dict[str, Any] = {}
        self.process: Optional[asyncio.subprocess.Process] = None
        self.connection: Optional[Any] = None  # WebSocket or HTTP session
        self.connected: bool = False
        self.request_id: int = 0
        self.restart_count: int = 0
        self._read_task: Optional[asyncio.Task] = None
        self._pending_requests: Dict[int, asyncio.Future] = {}
    
    async def send_request(self, method: str, params: Dict[str, Any], timeout: Optional[float] = None) -> Any:
        """Send JSON-RPC request to MCP server"""
        if not self.connected:
            raise ConnectionError(f"MCP instance {self.instance_id} is not connected")
        
        self.request_id += 1
        request_id = self.request_id
        
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params
        }
        
        timeout = timeout or self.config.timeout
        
        if self.config.connection_type == "stdio":
            return await self._send_stdio_request(request, timeout)
        elif self.config.connection_type == "websocket":
            return await self._send_websocket_request(request, timeout)
        elif self.config.connection_type == "http":
            return await self._send_http_request(request, timeout)
        else:
            raise ValueError(f"Unsupported connection type: {self.config.connection_type}")
    
    async def _send_stdio_request(self, request: Dict[str, Any], timeout: float) -> Any:
        """Send request via stdio"""
        if not self.process or self.process.returncode is not None:
            raise ConnectionError("MCP server process is not running")
        
        # Create future for response
        future = asyncio.Future()
        self._pending_requests[request["id"]] = future
        
        try:
            # Send request
            request_str = json.dumps(request) + "\n"
            self.process.stdin.write(request_str.encode())
            await self.process.stdin.drain()
            
            # Wait for response with timeout
            response = await asyncio.wait_for(future, timeout=timeout)
            return response
            
        except asyncio.TimeoutError:
            self._pending_requests.pop(request["id"], None)
            raise TimeoutError(f"Request timeout after {timeout}s")
        except Exception as e:
            self._pending_requests.pop(request["id"], None)
            raise
    
    async def _send_websocket_request(self, request: Dict[str, Any], timeout: float) -> Any:
        """Send request via WebSocket"""
        if not self.connection:
            raise ConnectionError("WebSocket connection not established")
        
        # Create future for response
        future = asyncio.Future()
        self._pending_requests[request["id"]] = future
        
        try:
            # Send request
            await self.connection.send(json.dumps(request))
            
            # Wait for response with timeout
            response = await asyncio.wait_for(future, timeout=timeout)
            return response
            
        except asyncio.TimeoutError:
            self._pending_requests.pop(request["id"], None)
            raise TimeoutError(f"Request timeout after {timeout}s")
        except Exception as e:
            self._pending_requests.pop(request["id"], None)
            raise
    
    async def _send_http_request(self, request: Dict[str, Any], timeout: float) -> Any:
        """Send request via HTTP"""
        if not self.connection:
            raise ConnectionError("HTTP session not established")
        
        headers = {"Content-Type": "application/json"}
        if self.config.auth_token:
            headers["Authorization"] = f"Bearer {self.config.auth_token}"
        if self.config.headers:
            headers.update(self.config.headers)
        
        try:
            async with self.connection.post(
                self.config.url,
                json=request,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as response:
                result = await response.json()
                
                if "error" in result:
                    raise Exception(f"MCP error: {result['error']}")
                
                return result.get("result")
                
        except asyncio.TimeoutError:
            raise TimeoutError(f"Request timeout after {timeout}s")
    
    async def _read_stdio_responses(self):
        """Background task to read responses from stdio"""
        while self.connected and self.process and self.process.returncode is None:
            try:
                line = await self.process.stdout.readline()
                if not line:
                    break
                
                try:
                    response = json.loads(line.decode())
                    request_id = response.get("id")
                    
                    if request_id and request_id in self._pending_requests:
                        future = self._pending_requests.pop(request_id)
                        
                        if "error" in response:
                            future.set_exception(Exception(response["error"]))
                        else:
                            future.set_result(response.get("result"))
                            
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON from MCP server: {line}")
                    
            except Exception as e:
                logger.error(f"Error reading from MCP server: {e}")
                break
    
    async def _read_websocket_responses(self):
        """Background task to read responses from WebSocket"""
        while self.connected and self.connection:
            try:
                message = await self.connection.recv()
                
                try:
                    response = json.loads(message)
                    request_id = response.get("id")
                    
                    if request_id and request_id in self._pending_requests:
                        future = self._pending_requests.pop(request_id)
                        
                        if "error" in response:
                            future.set_exception(Exception(response["error"]))
                        else:
                            future.set_result(response.get("result"))
                            
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON from MCP server: {message}")
                    
            except Exception as e:
                logger.error(f"Error reading from WebSocket: {e}")
                break
    
    async def health_check(self) -> bool:
        """Check if server is healthy"""
        try:
            # Try ping first
            response = await self.send_request("ping", {}, timeout=2.0)
            return True
        except:
            # Fallback to checking connection status
            if self.config.connection_type == "stdio":
                return self.process is not None and self.process.returncode is None
            else:
                return self.connected
    
    async def cleanup(self) -> None:
        """Clean up instance resources"""
        self.connected = False
        
        # Cancel read task
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
        
        # Terminate process if stdio
        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
            self.process = None
        
        # Close network connections
        if self.connection:
            if self.config.connection_type == "websocket":
                await self.connection.close()
            # HTTP session is managed by hub
            self.connection = None


class MCPHub(ResourceHub[MCPConfig]):
    """
    Hub for managing multiple MCP server instances
    
    Features:
    - Automatic discovery of MCP servers
    - Tool inventory management across all servers
    - Intelligent routing based on tool availability
    - Process lifecycle management for stdio servers
    - Connection pooling for network servers
    - Health monitoring and auto-restart
    """
    
    def __init__(
        self,
        hub_id: str = "mcp-hub",
        auto_discover: bool = True,
        enable_metrics: bool = True,
        max_instances: int = 20,
        config_data: Optional[Dict[str, Any]] = None,
        persistence: Optional[Any] = None
    ):
        super().__init__(
            hub_id=hub_id,
            resource_type=ResourceType.COMPUTE,  # MCP servers are compute resources
            enable_metrics=enable_metrics,
            persistence=persistence
        )
        
        self.max_instances = max_instances
        self.auto_discover = auto_discover
        self.config_data = config_data or {}
        
        # Tool registry: tool_name -> List[instance_id]
        self.tool_registry: Dict[str, List[str]] = {}
        
        # HTTP session for HTTP-based MCP servers
        self.http_session: Optional[aiohttp.ClientSession] = None
        
        # Health check task
        self._health_check_task: Optional[asyncio.Task] = None
        
        logger.info(f"Initialized MCPHub {hub_id} with auto_discover={auto_discover}")
    
    async def initialize(self) -> None:
        """Initialize hub and discover/start MCP servers"""
        # Create HTTP session for HTTP-based servers
        self.http_session = aiohttp.ClientSession()
        
        # Auto-discover if enabled
        if self.auto_discover:
            await self.discover_instances()
        
        # Start health monitoring
        if self.enable_metrics:
            self._health_check_task = asyncio.create_task(self._monitor_health())
    
    async def discover_instances(self) -> List[MCPInstance]:
        """Discover and register MCP servers"""
        discovered = []
        
        # Discover from configuration
        mcp_servers = self.config_data.get("servers", [])
        for server_config in mcp_servers:
            try:
                config = MCPConfig(**server_config)
                config.validate()
                
                instance = await self.create_resource(config)
                if instance:
                    await self.register_instance_object(instance)
                    discovered.append(instance)
                    logger.info(f"Discovered MCP server: {config.name}")
                    
            except Exception as e:
                logger.error(f"Failed to create MCP server from config: {e}")
        
        # Discover from environment variables
        env_servers = os.environ.get("GLEITZEIT_MCP_SERVERS")
        if env_servers:
            try:
                servers = json.loads(env_servers)
                for server_data in servers:
                    config = MCPConfig(**server_data)
                    config.validate()
                    
                    instance = await self.create_resource(config)
                    if instance:
                        await self.register_instance_object(instance)
                        discovered.append(instance)
                        logger.info(f"Discovered MCP server from env: {config.name}")
                        
            except Exception as e:
                logger.error(f"Failed to parse MCP servers from environment: {e}")
        
        logger.info(f"Discovered {len(discovered)} MCP servers")
        return discovered
    
    async def create_resource(self, config: MCPConfig) -> MCPInstance:
        """Create an MCP server instance"""
        instance_id = f"mcp-{config.name}-{self._generate_id()}"
        instance = MCPInstance(instance_id, config, self.hub_id)
        
        try:
            # Start the server if needed
            if config.auto_start and config.connection_type == "stdio":
                await self._start_server(instance)
            
            # Connect to the server
            await self._connect_server(instance)
            
            # Initialize MCP connection
            await self._initialize_mcp(instance)
            
            # Discover tools
            tools = await self._discover_tools(instance)
            instance.available_tools = tools
            
            # Index tools for routing
            await self._index_tools(instance)
            
            instance.status = ResourceStatus.READY
            return instance
            
        except Exception as e:
            logger.error(f"Failed to create MCP instance {instance_id}: {e}")
            instance.status = ResourceStatus.ERROR
            await instance.cleanup()
            raise
    
    async def _start_server(self, instance: MCPInstance) -> None:
        """Start an MCP server subprocess"""
        if not instance.config.command:
            raise ValueError(f"No command specified for stdio server {instance.instance_id}")
        
        # Prepare environment
        env = dict(os.environ)
        if instance.config.env:
            env.update(instance.config.env)
        
        # Start subprocess
        instance.process = await asyncio.create_subprocess_exec(
            *instance.config.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=instance.config.working_dir,
            env=env
        )
        
        logger.info(f"Started MCP server {instance.instance_id}: {' '.join(instance.config.command)}")
    
    async def _connect_server(self, instance: MCPInstance) -> None:
        """Establish connection to MCP server"""
        if instance.config.connection_type == "stdio":
            # Start background task to read responses
            instance._read_task = asyncio.create_task(instance._read_stdio_responses())
            instance.connected = True
            
        elif instance.config.connection_type == "websocket":
            # Connect via websocket
            try:
                import websockets
                instance.connection = await websockets.connect(
                    instance.config.url,
                    extra_headers=instance.config.headers or {}
                )
                # Start background task to read responses
                instance._read_task = asyncio.create_task(instance._read_websocket_responses())
                instance.connected = True
                
            except ImportError:
                raise ImportError("websockets package required for WebSocket connections")
                
        elif instance.config.connection_type == "http":
            # Use shared HTTP session
            instance.connection = self.http_session
            instance.connected = True
    
    async def _initialize_mcp(self, instance: MCPInstance) -> None:
        """Initialize MCP protocol connection"""
        try:
            # Send initialize request
            response = await instance.send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                    "resources": {},
                    "prompts": {}
                },
                "clientInfo": {
                    "name": "gleitzeit",
                    "version": "0.0.5"
                }
            })
            
            logger.info(f"Initialized MCP connection for {instance.instance_id}")
            
        except Exception as e:
            logger.error(f"Failed to initialize MCP for {instance.instance_id}: {e}")
            raise
    
    async def _discover_tools(self, instance: MCPInstance) -> Dict[str, Any]:
        """Discover available tools from an MCP server"""
        try:
            # Send tools/list request
            response = await instance.send_request("tools/list", {})
            tools = {}
            
            for tool in response.get("tools", []):
                tool_name = tool["name"]
                
                # Apply prefix if configured
                if instance.config.tool_prefix:
                    display_name = f"{instance.config.tool_prefix}{tool_name}"
                else:
                    display_name = tool_name
                
                tools[display_name] = {
                    "original_name": tool_name,
                    "description": tool.get("description", ""),
                    "inputSchema": tool.get("inputSchema", {}),
                    "instance_id": instance.instance_id
                }
            
            logger.info(f"Discovered {len(tools)} tools from {instance.instance_id}")
            return tools
            
        except Exception as e:
            logger.error(f"Failed to discover tools from {instance.instance_id}: {e}")
            return {}
    
    async def _index_tools(self, instance: MCPInstance) -> None:
        """Index tools for routing"""
        for tool_name in instance.available_tools:
            if tool_name not in self.tool_registry:
                self.tool_registry[tool_name] = []
            if instance.instance_id not in self.tool_registry[tool_name]:
                self.tool_registry[tool_name].append(instance.instance_id)
    
    async def get_instance_for_tool(self, tool_name: str) -> Optional[MCPInstance]:
        """Get best instance for a specific tool"""
        instance_ids = self.tool_registry.get(tool_name, [])
        
        if not instance_ids:
            return None
        
        # Find first healthy instance
        for instance_id in instance_ids:
            instance = self.instances.get(instance_id)
            if instance and instance.status == ResourceStatus.READY:
                return instance
        
        return None
    
    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        instance_id: Optional[str] = None
    ) -> Any:
        """Call a tool on an MCP server"""
        # Get instance
        if instance_id:
            instance = self.instances.get(instance_id)
        else:
            instance = await self.get_instance_for_tool(tool_name)
        
        if not instance:
            raise ValueError(f"No MCP server available for tool: {tool_name}")
        
        # Get original tool name
        tool_info = instance.available_tools.get(tool_name)
        if not tool_info:
            raise ValueError(f"Tool {tool_name} not found on instance {instance.instance_id}")
        
        original_name = tool_info["original_name"]
        
        # Call tool
        try:
            response = await instance.send_request("tools/call", {
                "name": original_name,
                "arguments": arguments
            })
            
            # Update metrics
            if self.enable_metrics:
                await self._update_metrics(instance.instance_id, success=True)
            
            return response
            
        except Exception as e:
            logger.error(f"Tool call failed: {tool_name} on {instance.instance_id}: {e}")
            
            # Update metrics
            if self.enable_metrics:
                await self._update_metrics(instance.instance_id, success=False)
            
            # Try another instance if available
            if not instance_id:  # Only retry if not explicitly specified
                other_instances = [
                    iid for iid in self.tool_registry.get(tool_name, [])
                    if iid != instance.instance_id
                ]
                if other_instances:
                    logger.info(f"Retrying tool {tool_name} on different instance")
                    return await self.call_tool(tool_name, arguments, other_instances[0])
            
            raise
    
    async def _monitor_health(self) -> None:
        """Monitor health of all MCP instances"""
        while True:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                
                for instance in list(self.instances.values()):
                    if instance.status == ResourceStatus.READY:
                        healthy = await instance.health_check()
                        
                        if not healthy:
                            logger.warning(f"MCP instance {instance.instance_id} is unhealthy")
                            instance.status = ResourceStatus.ERROR
                            
                            # Try to restart if configured
                            if instance.config.restart_on_failure and instance.restart_count < instance.config.max_retries:
                                logger.info(f"Attempting to restart {instance.instance_id}")
                                await self._restart_instance(instance)
                                
            except Exception as e:
                logger.error(f"Health monitoring error: {e}")
    
    async def _restart_instance(self, instance: MCPInstance) -> None:
        """Restart an MCP instance"""
        instance.restart_count += 1
        
        try:
            # Cleanup existing connection
            await instance.cleanup()
            
            # Restart based on type
            if instance.config.connection_type == "stdio" and instance.config.auto_start:
                await self._start_server(instance)
            
            # Reconnect
            await self._connect_server(instance)
            await self._initialize_mcp(instance)
            
            # Re-discover tools
            tools = await self._discover_tools(instance)
            instance.available_tools = tools
            await self._index_tools(instance)
            
            instance.status = ResourceStatus.READY
            logger.info(f"Successfully restarted {instance.instance_id}")
            
        except Exception as e:
            logger.error(f"Failed to restart {instance.instance_id}: {e}")
            instance.status = ResourceStatus.ERROR
    
    def _generate_id(self) -> str:
        """Generate unique ID suffix"""
        import uuid
        return str(uuid.uuid4())[:8]
    
    async def check_health(self, instance_id: str) -> bool:
        """Check health of a specific MCP instance"""
        instance = self.instances.get(instance_id)
        if not instance:
            return False
        return await instance.health_check()
    
    async def collect_metrics(self, instance_id: str) -> ResourceMetrics:
        """Collect metrics for a specific MCP instance"""
        instance = self.instances.get(instance_id)
        if not instance:
            return ResourceMetrics()
        
        # Basic metrics for MCP instances
        return ResourceMetrics(
            cpu_usage=0.0,  # Could track process CPU if needed
            memory_usage=0.0,  # Could track process memory if needed
            requests_per_second=0.0,
            active_connections=1 if instance.connected else 0,
            error_rate=0.0,
            custom_metrics={
                "tools_available": len(instance.available_tools),
                "restart_count": instance.restart_count,
                "connected": instance.connected
            }
        )
    
    async def start_instance(self, instance_id: str) -> None:
        """Start a specific MCP instance"""
        instance = self.instances.get(instance_id)
        if not instance:
            raise ValueError(f"Instance not found: {instance_id}")
        
        if instance.config.connection_type == "stdio" and instance.config.auto_start:
            await self._start_server(instance)
            await self._connect_server(instance)
            await self._initialize_mcp(instance)
            instance.status = ResourceStatus.READY
    
    async def stop_instance(self, instance_id: str) -> None:
        """Stop a specific MCP instance"""
        instance = self.instances.get(instance_id)
        if not instance:
            raise ValueError(f"Instance not found: {instance_id}")
        
        await instance.cleanup()
        instance.status = ResourceStatus.STOPPED
    
    async def restart_instance(self, instance_id: str) -> None:
        """Restart a specific MCP instance"""
        instance = self.instances.get(instance_id)
        if not instance:
            raise ValueError(f"Instance not found: {instance_id}")
        
        await self._restart_instance(instance)
    
    async def cleanup(self) -> None:
        """Clean up all resources"""
        # Cancel health check task
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        
        # Cleanup all instances
        for instance in self.instances.values():
            await instance.cleanup()
        
        # Close HTTP session
        if self.http_session:
            await self.http_session.close()
        
        await super().cleanup()