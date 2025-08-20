# External MCP Provider Integration Design

## Overview
This document outlines the design for seamlessly integrating external MCP (Model Context Protocol) servers into Gleitzeit's existing architecture, making them first-class citizens alongside built-in providers.

## Current State

### Existing Components
- **SimpleMCPProvider**: Built-in provider with hardcoded tools (echo, add, multiply, concat)
- **ExternalMCPProvider** (in examples/): Basic implementation for subprocess-based MCP servers
- **Protocol Registry**: Maps protocols to providers
- **Client**: Currently manually registers providers

### Limitations
1. External MCP providers must be manually instantiated and registered
2. No configuration-based MCP server discovery
3. No automatic tool discovery and registration
4. External providers are second-class citizens (in examples/, not core)

## Proposed Architecture

### 1. Core MCP Provider System

```
src/gleitzeit/providers/
├── mcp_provider.py          # Base MCP provider class
├── simple_mcp_provider.py   # Built-in tools (unchanged)
└── external_mcp_provider.py # External server connector (new)
```

#### Base MCP Provider (`mcp_provider.py`)
```python
class MCPProvider(ProtocolProvider):
    """Base class for all MCP providers"""
    
    def __init__(self, provider_id: str, **kwargs):
        super().__init__(
            provider_id=provider_id,
            protocol_id="mcp/v1",
            **kwargs
        )
    
    @abstractmethod
    async def discover_tools(self) -> Dict[str, Any]:
        """Discover available tools from the provider"""
        pass
    
    @abstractmethod
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Execute a tool with given arguments"""
        pass
```

#### External MCP Provider (`external_mcp_provider.py`)
```python
class ExternalMCPProvider(MCPProvider):
    """Connects to external MCP servers via subprocess or network"""
    
    def __init__(
        self,
        provider_id: str,
        connection_type: str = "stdio",  # stdio, websocket, http
        server_command: Optional[List[str]] = None,
        server_url: Optional[str] = None,
        auto_start: bool = True,
        **kwargs
    ):
        super().__init__(provider_id, **kwargs)
        self.connection_type = connection_type
        self.server_command = server_command
        self.server_url = server_url
        self.auto_start = auto_start
```

### 2. Configuration System Integration

#### Config File (`~/.gleitzeit/config.yaml`)
```yaml
# Gleitzeit configuration with MCP servers
mcp_servers:
  # Subprocess-based MCP servers
  - id: "filesystem"
    type: "external"
    connection: "stdio"
    command: ["npx", "-y", "@modelcontextprotocol/server-filesystem"]
    args: ["--root", "/path/to/files"]
    auto_start: true
    
  - id: "github"
    type: "external"
    connection: "stdio"
    command: ["npx", "-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_TOKEN: "${GITHUB_TOKEN}"
    auto_start: true
    
  - id: "web-search"
    type: "external"
    connection: "stdio"
    command: ["npx", "-y", "@modelcontextprotocol/server-web-search"]
    auto_start: true
    
  # Network-based MCP servers
  - id: "remote-tools"
    type: "external"
    connection: "websocket"
    url: "ws://localhost:8765/mcp"
    auto_start: false  # Already running
    
  # Built-in provider (always available)
  - id: "simple"
    type: "builtin"
    enabled: true
```

#### Environment Variables
```bash
# Override config file
export GLEITZEIT_MCP_SERVERS='[{"id":"custom","command":["./my-mcp-server"]}]'
export GLEITZEIT_MCP_AUTO_DISCOVER=true
```

### 3. Auto-Registration System

#### In `client.py`
```python
class GleitzeitClient:
    async def _setup_providers(self):
        """Setup all providers including MCP servers from config"""
        # ... existing provider setup ...
        
        # Auto-register MCP servers from config
        await self._register_mcp_servers()
    
    async def _register_mcp_servers(self):
        """Register all configured MCP servers"""
        mcp_config = self.config.get('mcp_servers', [])
        
        for server_config in mcp_config:
            if server_config.get('type') == 'external':
                provider = ExternalMCPProvider(
                    provider_id=server_config['id'],
                    connection_type=server_config.get('connection', 'stdio'),
                    server_command=server_config.get('command'),
                    server_url=server_config.get('url'),
                    auto_start=server_config.get('auto_start', True)
                )
                await provider.initialize()
                self.registry.register_provider(
                    server_config['id'], 
                    "mcp/v1", 
                    provider
                )
```

### 4. Dynamic Tool Discovery

#### Tool Registration Flow
1. Provider connects to MCP server
2. Calls `tools/list` to discover available tools
3. Dynamically registers each tool as a method
4. Tools become available as `mcp/<provider_id>.<tool_name>`

#### Method Routing
```python
# In workflow YAML
tasks:
  - id: "search"
    method: "mcp/web-search.search"  # Routes to web-search provider's search tool
    parameters:
      query: "AI news"
      
  - id: "read_file"
    method: "mcp/filesystem.read"  # Routes to filesystem provider's read tool
    parameters:
      path: "/docs/readme.md"
      
  - id: "github_issue"
    method: "mcp/github.create_issue"  # Routes to github provider's create_issue tool
    parameters:
      repo: "user/repo"
      title: "New feature"
```

### 5. Provider Selection Strategy

#### Smart Routing
```python
class MCPProviderRouter:
    """Routes MCP method calls to appropriate providers"""
    
    def get_provider_for_method(self, method: str) -> MCPProvider:
        # Parse method: mcp/[provider_id.]tool_name
        if '.' in method:
            # Explicit provider: mcp/github.create_issue
            provider_id, tool_name = method.split('.', 1)
            return self.providers[provider_id]
        else:
            # Find first provider with this tool
            for provider in self.providers.values():
                if tool_name in provider.available_tools:
                    return provider
```

### 6. Lifecycle Management

#### Provider Lifecycle
```python
class ExternalMCPProvider:
    async def initialize(self):
        """Start server if needed and establish connection"""
        if self.auto_start and self.connection_type == "stdio":
            await self._start_server()
        await self._connect()
        await self._discover_tools()
    
    async def _start_server(self):
        """Start the MCP server subprocess"""
        self.process = await asyncio.create_subprocess_exec(...)
    
    async def _connect(self):
        """Establish connection to MCP server"""
        if self.connection_type == "stdio":
            # Already connected via subprocess
            pass
        elif self.connection_type == "websocket":
            self.ws = await websockets.connect(self.server_url)
    
    async def cleanup(self):
        """Graceful shutdown"""
        if self.auto_start and self.process:
            await self._stop_server()
        await self._disconnect()
```

### 7. Error Handling & Resilience

#### Retry Logic
```python
class ExternalMCPProvider:
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Call tool with automatic retry on connection failure"""
        for attempt in range(self.max_retries):
            try:
                return await self._send_tool_request(tool_name, arguments)
            except ConnectionError:
                if attempt < self.max_retries - 1:
                    await self._reconnect()
                else:
                    raise
```

#### Health Monitoring
```python
class MCPHealthMonitor:
    """Monitor MCP provider health"""
    
    async def check_providers(self):
        """Periodic health check of all MCP providers"""
        for provider in self.providers:
            if not await provider.health_check():
                await self._handle_unhealthy_provider(provider)
```

## Usage Examples

### 1. Configuration-Based Setup
```yaml
# ~/.gleitzeit/config.yaml
mcp_servers:
  - id: "my-tools"
    type: "external"
    command: ["python", "/path/to/my_mcp_server.py"]
    auto_start: true
```

```python
# No code needed - auto-registered!
async with GleitzeitClient() as client:
    result = await client.execute_task({
        "method": "mcp/my-tools.custom_tool",
        "parameters": {"arg": "value"}
    })
```

### 2. Programmatic Registration
```python
from gleitzeit import GleitzeitClient
from gleitzeit.providers import ExternalMCPProvider

async with GleitzeitClient() as client:
    # Add a new MCP server at runtime
    mcp = ExternalMCPProvider(
        provider_id="runtime-tools",
        server_command=["./special-mcp-server"]
    )
    await client.register_provider("runtime-tools", mcp)
    
    # Use immediately
    result = await client.execute_task({
        "method": "mcp/runtime-tools.special_tool",
        "parameters": {"data": "test"}
    })
```

### 3. Workflow Integration
```yaml
name: "Multi-MCP Workflow"
tasks:
  - id: "search_web"
    method: "mcp/web-search.search"
    parameters:
      query: "Python MCP servers"
      
  - id: "read_local"
    method: "mcp/filesystem.read"
    parameters:
      path: "./docs/mcp.md"
      
  - id: "analyze"
    method: "llm/chat"
    dependencies: ["search_web", "read_local"]
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: |
            Compare web results: ${search_web.results}
            With local docs: ${read_local.content}
```

## Implementation Phases

### Phase 1: Core Infrastructure (Week 1)
1. Move ExternalMCPProvider to src/gleitzeit/providers/
2. Create base MCPProvider class
3. Implement connection types (stdio, websocket)
4. Add tool discovery

### Phase 2: Configuration (Week 2)
1. Add MCP section to config schema
2. Implement config loading in client
3. Add auto-registration logic
4. Environment variable support

### Phase 3: Advanced Features (Week 3)
1. Provider health monitoring
2. Retry and reconnection logic
3. Tool caching and optimization
4. Provider selection strategies

### Phase 4: Documentation & Testing (Week 4)
1. Complete documentation
2. Add integration tests
3. Create example MCP servers
4. Tutorial and guides

## Benefits

1. **Zero-Configuration**: MCP servers defined in config are automatically available
2. **First-Class Integration**: External MCP providers work exactly like built-in providers
3. **Flexibility**: Support for subprocess, websocket, and HTTP connections
4. **Discoverability**: Automatic tool discovery and registration
5. **Reliability**: Built-in retry, health checks, and graceful degradation
6. **Simplicity**: Single config file for all MCP servers

## Compatibility

- **Backward Compatible**: Existing SimpleMCPProvider continues to work
- **MCP Spec Compliant**: Follows official MCP protocol specification
- **Provider Agnostic**: Works with any MCP-compliant server

## Future Enhancements

1. **MCP Server Hub**: Central registry of available MCP servers
2. **Authentication**: Support for authenticated MCP connections
3. **Load Balancing**: Multiple instances of same MCP server
4. **Caching Layer**: Cache tool responses for performance
5. **UI Integration**: Browse and test MCP tools via web UI