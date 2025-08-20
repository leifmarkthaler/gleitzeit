# MCP Hub Integration Design

## Overview
Following Gleitzeit's existing hub pattern (OllamaHub, DockerHub), we'll create an MCPHub that manages multiple MCP server instances, providing automatic discovery, lifecycle management, and intelligent routing.

## Architecture

### Hub-Based Design
```
src/gleitzeit/
├── hub/
│   ├── base.py               # ResourceHub base (existing)
│   ├── ollama_hub.py         # Ollama hub (existing)
│   ├── docker_hub.py         # Docker hub (existing)
│   └── mcp_hub.py           # MCP hub (NEW)
├── providers/
│   ├── simple_mcp_provider.py    # Built-in MCP tools (existing)
│   └── mcp_hub_provider.py       # MCP provider using hub (NEW)
└── hub/configs/
    └── mcp_config.py         # MCP instance config (NEW)
```

## Component Design

### 1. MCP Configuration (`hub/configs/mcp_config.py`)
```python
from dataclasses import dataclass
from typing import Optional, Dict, List, Any
from .base import ResourceConfig

@dataclass
class MCPConfig(ResourceConfig):
    """Configuration for an MCP server instance"""
    
    # Connection settings
    connection_type: str = "stdio"  # stdio, websocket, http
    
    # For stdio connections
    command: Optional[List[str]] = None
    working_dir: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    
    # For network connections
    url: Optional[str] = None
    auth_token: Optional[str] = None
    
    # Behavior settings
    auto_start: bool = True
    restart_on_failure: bool = True
    max_retries: int = 3
    timeout: float = 30.0
    
    # Discovery
    advertise_tools: bool = True
    tool_prefix: Optional[str] = None  # e.g., "github." for github tools
```

### 2. MCP Hub (`hub/mcp_hub.py`)
```python
class MCPHub(ResourceHub[MCPConfig]):
    """
    Hub for managing multiple MCP server instances
    
    Features:
    - Automatic discovery of MCP servers (local and network)
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
        config_file: Optional[str] = None,
        persistence: Optional[Any] = None
    ):
        super().__init__(
            hub_id=hub_id,
            resource_type=ResourceType.MCP,
            enable_metrics=enable_metrics,
            persistence=persistence
        )
        
        self.max_instances = max_instances
        self.auto_discover = auto_discover
        self.config_file = config_file
        
        # Tool registry: tool_name -> List[instance_id]
        self.tool_registry: Dict[str, List[str]] = {}
        
        # Process management for stdio servers
        self.processes: Dict[str, asyncio.subprocess.Process] = {}
        
        # Connection pools for network servers
        self.connections: Dict[str, Any] = {}
    
    async def initialize(self) -> None:
        """Initialize hub and discover/start MCP servers"""
        # Load configuration
        if self.config_file:
            await self._load_config()
        
        # Auto-discover if enabled
        if self.auto_discover:
            await self.discover_instances()
        
        # Start monitoring
        if self.enable_metrics:
            asyncio.create_task(self._monitor_health())
    
    async def discover_instances(self) -> List[MCPInstance]:
        """Discover and register MCP servers"""
        discovered = []
        
        # 1. Discover from configuration file
        if self.config_file:
            config_servers = await self._discover_from_config()
            discovered.extend(config_servers)
        
        # 2. Discover from environment variables
        env_servers = await self._discover_from_env()
        discovered.extend(env_servers)
        
        # 3. Discover well-known MCP servers (if installed)
        well_known = await self._discover_well_known()
        discovered.extend(well_known)
        
        # 4. Register all discovered servers
        for instance in discovered:
            await self.register_instance_object(instance)
            await self._index_tools(instance)
        
        logger.info(f"Discovered {len(discovered)} MCP servers")
        return discovered
    
    async def create_resource(self, config: MCPConfig) -> MCPInstance:
        """Create an MCP server instance"""
        instance = MCPInstance(
            instance_id=f"mcp-{config.name or 'server'}-{self._generate_id()}",
            config=config,
            hub_id=self.hub_id
        )
        
        # Start the server if needed
        if config.auto_start:
            await self._start_server(instance)
        
        # Connect to the server
        await self._connect_server(instance)
        
        # Discover tools
        tools = await self._discover_tools(instance)
        instance.available_tools = tools
        
        return instance
    
    async def _start_server(self, instance: MCPInstance) -> None:
        """Start an MCP server subprocess"""
        if instance.config.connection_type != "stdio":
            return  # Only start stdio servers
        
        if not instance.config.command:
            raise ValueError(f"No command specified for stdio server {instance.instance_id}")
        
        # Start subprocess
        process = await asyncio.create_subprocess_exec(
            *instance.config.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=instance.config.working_dir,
            env={**os.environ, **(instance.config.env or {})}
        )
        
        self.processes[instance.instance_id] = process
        instance.process = process
        logger.info(f"Started MCP server {instance.instance_id}: {' '.join(instance.config.command)}")
    
    async def _connect_server(self, instance: MCPInstance) -> None:
        """Establish connection to MCP server"""
        if instance.config.connection_type == "stdio":
            # Already connected via subprocess pipes
            instance.connected = True
            
        elif instance.config.connection_type == "websocket":
            # Connect via websocket
            import websockets
            ws = await websockets.connect(instance.config.url)
            self.connections[instance.instance_id] = ws
            instance.connected = True
            
        elif instance.config.connection_type == "http":
            # HTTP doesn't need persistent connection
            instance.connected = True
    
    async def _discover_tools(self, instance: MCPInstance) -> Dict[str, Any]:
        """Discover available tools from an MCP server"""
        try:
            # Send tools/list request
            response = await instance.send_request("tools/list", {})
            tools = {}
            
            for tool in response.get("tools", []):
                tool_name = tool["name"]
                if instance.config.tool_prefix:
                    tool_name = f"{instance.config.tool_prefix}{tool_name}"
                tools[tool_name] = tool
            
            return tools
            
        except Exception as e:
            logger.error(f"Failed to discover tools from {instance.instance_id}: {e}")
            return {}
    
    async def _index_tools(self, instance: MCPInstance) -> None:
        """Index tools for routing"""
        for tool_name in instance.available_tools:
            if tool_name not in self.tool_registry:
                self.tool_registry[tool_name] = []
            self.tool_registry[tool_name].append(instance.instance_id)
    
    async def get_instance_for_tool(self, tool_name: str) -> Optional[MCPInstance]:
        """Get best instance for a specific tool"""
        instance_ids = self.tool_registry.get(tool_name, [])
        
        if not instance_ids:
            return None
        
        # Select instance based on load/health
        best_instance = None
        best_score = float('inf')
        
        for instance_id in instance_ids:
            instance = self.instances.get(instance_id)
            if instance and instance.status == ResourceStatus.READY:
                score = await self._calculate_instance_score(instance)
                if score < best_score:
                    best_score = score
                    best_instance = instance
        
        return best_instance
    
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
        
        # Strip prefix if needed
        actual_tool_name = tool_name
        if instance.config.tool_prefix and tool_name.startswith(instance.config.tool_prefix):
            actual_tool_name = tool_name[len(instance.config.tool_prefix):]
        
        # Call tool
        try:
            response = await instance.send_request("tools/call", {
                "name": actual_tool_name,
                "arguments": arguments
            })
            return response
            
        except Exception as e:
            logger.error(f"Tool call failed: {tool_name} on {instance.instance_id}: {e}")
            
            # Retry with different instance if available
            if not instance_id:  # Only retry if not explicitly specified
                other_instances = [
                    iid for iid in self.tool_registry.get(tool_name, [])
                    if iid != instance.instance_id
                ]
                if other_instances:
                    return await self.call_tool(tool_name, arguments, other_instances[0])
            
            raise
```

### 3. MCP Instance (`hub/mcp_hub.py`)
```python
class MCPInstance(ResourceInstance[MCPConfig]):
    """Represents a single MCP server instance"""
    
    def __init__(self, instance_id: str, config: MCPConfig, hub_id: str):
        super().__init__(instance_id, config, hub_id)
        self.available_tools: Dict[str, Any] = {}
        self.process: Optional[asyncio.subprocess.Process] = None
        self.connected: bool = False
        self.request_id: int = 0
    
    async def send_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Send JSON-RPC request to MCP server"""
        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params
        }
        
        if self.config.connection_type == "stdio":
            return await self._send_stdio_request(request)
        elif self.config.connection_type == "websocket":
            return await self._send_ws_request(request)
        elif self.config.connection_type == "http":
            return await self._send_http_request(request)
    
    async def health_check(self) -> bool:
        """Check if server is healthy"""
        try:
            response = await self.send_request("ping", {})
            return response == "pong"
        except:
            return False
```

### 4. MCP Hub Provider (`providers/mcp_hub_provider.py`)
```python
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
        **kwargs
    ):
        super().__init__(
            provider_id=provider_id,
            protocol_id="mcp/v1",
            name="MCP Hub Provider",
            description="Routes MCP requests through MCPHub",
            hub=hub,
            **kwargs
        )
        
        # Create hub if not provided
        if not self.hub:
            self.hub = MCPHub()
    
    async def initialize(self) -> None:
        """Initialize provider and hub"""
        await self.hub.initialize()
        logger.info(f"MCP Hub Provider initialized with {len(self.hub.instances)} servers")
    
    def get_supported_methods(self) -> List[str]:
        """Return all available MCP methods"""
        methods = ["mcp/tools/list", "mcp/servers", "mcp/ping"]
        
        # Add all discovered tools
        for tool_name in self.hub.tool_registry.keys():
            methods.append(f"mcp/tool.{tool_name}")
        
        return methods
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Handle MCP requests by routing through hub"""
        logger.info(f"MCP Hub Provider handling: {method}")
        
        # Strip protocol prefix
        if method.startswith("mcp/"):
            method = method[4:]
        
        # Handle tool calls
        if method.startswith("tool."):
            tool_name = method[5:]
            arguments = params.get("arguments", params)
            return await self.hub.call_tool(tool_name, arguments)
        
        # Handle meta methods
        if method == "tools/list":
            # Return all tools from all servers
            all_tools = {}
            for instance in self.hub.instances.values():
                all_tools.update(instance.available_tools)
            return {"tools": list(all_tools.values())}
        
        elif method == "servers":
            # Return info about all MCP servers
            return {
                "servers": [
                    {
                        "id": instance.instance_id,
                        "status": instance.status.value,
                        "tools": list(instance.available_tools.keys())
                    }
                    for instance in self.hub.instances.values()
                ]
            }
        
        elif method == "ping":
            # Ping all servers
            results = {}
            for instance in self.hub.instances.values():
                results[instance.instance_id] = await instance.health_check()
            return results
        
        else:
            raise MethodNotSupportedError(method, self.provider_id)
```

### 5. Configuration Integration

#### Config File (`~/.gleitzeit/config.yaml`)
```yaml
# MCP Hub configuration
mcp:
  hub:
    auto_discover: true
    max_instances: 20
    enable_metrics: true
  
  servers:
    # Filesystem MCP server
    - name: "filesystem"
      connection_type: "stdio"
      command: ["npx", "-y", "@modelcontextprotocol/server-filesystem"]
      working_dir: "/Users/me/documents"
      auto_start: true
      tool_prefix: "fs."  # Tools will be fs.read, fs.write, etc.
      
    # GitHub MCP server
    - name: "github"
      connection_type: "stdio"
      command: ["npx", "-y", "@modelcontextprotocol/server-github"]
      env:
        GITHUB_TOKEN: "${GITHUB_TOKEN}"
      auto_start: true
      tool_prefix: "gh."  # Tools will be gh.create_issue, gh.list_repos, etc.
      
    # Web search server
    - name: "search"
      connection_type: "stdio"
      command: ["npx", "-y", "@modelcontextprotocol/server-web-search"]
      auto_start: true
      
    # Custom Python MCP server
    - name: "custom"
      connection_type: "stdio"
      command: ["python", "/path/to/my_mcp_server.py"]
      auto_start: true
      
    # Remote MCP server (already running)
    - name: "remote"
      connection_type: "websocket"
      url: "ws://remote-server:8765/mcp"
      auto_start: false  # Don't start, just connect
      auth_token: "${REMOTE_MCP_TOKEN}"
```

### 6. Client Integration

```python
class GleitzeitClient:
    async def _setup_providers(self):
        """Setup all providers including MCP Hub"""
        # ... existing provider setup ...
        
        # Setup MCP Hub
        await self._setup_mcp_hub()
    
    async def _setup_mcp_hub(self):
        """Setup MCP Hub with configured servers"""
        mcp_config = self.config.get('mcp', {})
        
        # Create hub
        hub = MCPHub(
            auto_discover=mcp_config.get('hub', {}).get('auto_discover', True),
            config_file=self.config_file
        )
        
        # Create provider using hub
        mcp_provider = MCPHubProvider(hub=hub)
        await mcp_provider.initialize()
        
        # Register provider
        self.registry.register_provider("mcp", "mcp/v1", mcp_provider)
```

## Usage Examples

### 1. Zero Configuration
```python
# MCP servers from config are automatically available
async with GleitzeitClient() as client:
    # Use filesystem tool (automatically routed to filesystem server)
    result = await client.execute_task({
        "method": "mcp/tool.fs.read",
        "parameters": {"path": "README.md"}
    })
    
    # Use GitHub tool (automatically routed to GitHub server)
    issues = await client.execute_task({
        "method": "mcp/tool.gh.list_issues",
        "parameters": {"repo": "user/repo"}
    })
```

### 2. Workflow Integration
```yaml
name: "Multi-MCP Workflow"
tasks:
  - id: "search"
    method: "mcp/tool.search"  # Routes to search server
    parameters:
      query: "Python MCP protocol"
      
  - id: "read_file"
    method: "mcp/tool.fs.read"  # Routes to filesystem server
    parameters:
      path: "./docs/mcp.md"
      
  - id: "create_issue"
    method: "mcp/tool.gh.create_issue"  # Routes to GitHub server
    dependencies: ["search", "read_file"]
    parameters:
      repo: "myorg/myrepo"
      title: "Update MCP docs"
      body: |
        Search results: ${search.results}
        Current docs: ${read_file.content}
```

### 3. Programmatic Server Addition
```python
async with GleitzeitClient() as client:
    # Add a new MCP server at runtime
    mcp_hub = client.get_provider("mcp").hub
    
    config = MCPConfig(
        name="runtime-server",
        connection_type="stdio",
        command=["./my-custom-mcp-server"],
        auto_start=True
    )
    
    instance = await mcp_hub.create_resource(config)
    await mcp_hub.register_instance_object(instance)
    
    # Tools are immediately available
    result = await client.execute_task({
        "method": "mcp/tool.my_custom_tool",
        "parameters": {"data": "test"}
    })
```

### 4. Direct Hub Usage
```python
from gleitzeit.hub import MCPHub

# Create standalone hub
hub = MCPHub()
await hub.initialize()

# Call tool directly
result = await hub.call_tool("search", {"query": "MCP servers"})

# Get server metrics
metrics = await hub.get_metrics()
for server_id, metric in metrics.items():
    print(f"{server_id}: {metric.requests_per_second} req/s")
```

## Benefits of Hub Approach

1. **Consistency**: Follows existing Gleitzeit patterns (OllamaHub)
2. **Centralized Management**: Single point for all MCP servers
3. **Resource Optimization**: Connection pooling, load balancing
4. **Resilience**: Health monitoring, auto-restart, failover
5. **Scalability**: Can manage many MCP servers efficiently
6. **Observability**: Metrics, monitoring, and debugging
7. **Tool Discovery**: Automatic tool indexing and routing

## Implementation Plan

### Phase 1: Core MCPHub
1. Create MCPConfig dataclass
2. Implement MCPHub with basic stdio support
3. Add tool discovery and indexing
4. Create MCPHubProvider

### Phase 2: Advanced Features
1. Add websocket/HTTP support
2. Implement health monitoring
3. Add auto-restart capability
4. Create metrics collection

### Phase 3: Integration
1. Update client to auto-configure MCPHub
2. Add config file support
3. Create well-known server templates
4. Add documentation and examples

This hub-based approach provides a robust, scalable foundation for MCP integration that fits naturally into Gleitzeit's architecture.