# MCP (Model Context Protocol) Integration

## Overview

Gleitzeit provides comprehensive support for the Model Context Protocol (MCP), enabling seamless integration with external tools and services through MCP servers. The integration follows Gleitzeit's hub-based architecture, making MCP servers first-class citizens alongside other providers like Ollama and Python.

## Architecture

### Components

```
┌─────────────────────────────────────────────────────┐
│                  GleitzeitClient                     │
├─────────────────────────────────────────────────────┤
│                 Protocol Registry                    │
├─────────────────────────────────────────────────────┤
│              MCPHubProvider (mcp/v1)                │
├─────────────────────────────────────────────────────┤
│                     MCPHub                          │
├──────────────┬──────────────┬──────────────────────┤
│  MCPInstance │  MCPInstance │    MCPInstance        │
│  (built-in)  │  (stdio)     │    (websocket)       │
└──────────────┴──────────────┴──────────────────────┘
```

### Key Components

1. **MCPHub** (`hub/mcp_hub.py`)
   - Manages multiple MCP server instances
   - Handles server lifecycle (start/stop/restart)
   - Maintains tool registry for routing
   - Provides health monitoring and metrics

2. **MCPHubProvider** (`providers/mcp_hub_provider.py`)
   - Bridge between protocol system and MCPHub
   - Routes MCP method calls to appropriate servers
   - Handles tool discovery and registration

3. **Example Implementation** (`examples/simple_mcp_provider.py`)
   - Reference implementation showing how to build MCP providers
   - Demonstrates direct tool implementation without external servers
   - Useful for learning and testing

## Quick Start

### Configuring MCP Servers

MCP requires external servers to be configured. Without any servers, MCPHub will initialize but won't have any tools available:

```yaml
# ~/.gleitzeit/config.yaml
mcp:
  servers:
    - name: "filesystem"
      connection_type: "stdio"
      command: ["npx", "-y", "@modelcontextprotocol/server-filesystem"]
      tool_prefix: "fs."
```

Then use the configured tools:

```python
from gleitzeit import GleitzeitClient

async with GleitzeitClient(mode="native") as client:
    # Use filesystem tool
    result = await client.execute_task(
        protocol="mcp/v1",
        method="tool.fs.read",
        params={"path": "README.md"}
    )
    print(result)
```

### Using in Workflows

```yaml
name: "MCP Example Workflow"
tasks:
  - id: "read_config"
    method: "mcp/tool.fs.read"
    parameters:
      path: "config.json"
      
  - id: "process"
    method: "llm/chat"
    dependencies: ["read_config"]
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Summarize this config: ${read_config.content}"
```

## External MCP Servers

### Configuration

Configure external MCP servers in your Gleitzeit configuration:

```yaml
# ~/.gleitzeit/config.yaml or passed via native_config
mcp:
  auto_discover: true
  enable_metrics: true
  
  servers:
    # Filesystem MCP server
    - name: "filesystem"
      connection_type: "stdio"
      command: ["npx", "-y", "@modelcontextprotocol/server-filesystem"]
      working_dir: "${HOME}/documents"
      auto_start: true
      tool_prefix: "fs."  # Tools: fs.read, fs.write, etc.
      
    # GitHub MCP server
    - name: "github"
      connection_type: "stdio"
      command: ["npx", "-y", "@modelcontextprotocol/server-github"]
      env:
        GITHUB_TOKEN: "${GITHUB_TOKEN}"
      auto_start: true
      tool_prefix: "gh."  # Tools: gh.create_issue, gh.list_repos
      
    # Web search server
    - name: "search"
      connection_type: "stdio"
      command: ["npx", "-y", "@modelcontextprotocol/server-web-search"]
      auto_start: true
      
    # Custom Python MCP server
    - name: "custom"
      connection_type: "stdio"
      command: ["python", "my_mcp_server.py"]
      working_dir: "/path/to/server"
      env:
        CUSTOM_VAR: "value"
      auto_start: true
      
    # Remote WebSocket server
    - name: "remote"
      connection_type: "websocket"
      url: "ws://remote-server:8765/mcp"
      auth_token: "${REMOTE_TOKEN}"
      auto_start: false  # Already running
      
    # HTTP-based MCP server
    - name: "api"
      connection_type: "http"
      url: "https://api.example.com/mcp"
      headers:
        X-API-Key: "${API_KEY}"
      auto_start: false
```

### Configuration Options

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `name` | string | Friendly name for the server | Required |
| `connection_type` | string | Connection type: `stdio`, `websocket`, `http` | `stdio` |
| `command` | list | Command to launch stdio server | Required for stdio |
| `working_dir` | string | Working directory for stdio server | Current dir |
| `env` | dict | Environment variables | `{}` |
| `url` | string | URL for network connections | Required for ws/http |
| `auth_token` | string | Authentication token | Optional |
| `headers` | dict | HTTP headers | `{}` |
| `auto_start` | bool | Auto-start stdio servers | `true` |
| `restart_on_failure` | bool | Restart on failure | `true` |
| `max_retries` | int | Max restart attempts | `3` |
| `timeout` | float | Request timeout (seconds) | `30.0` |
| `tool_prefix` | string | Prefix for tool names | Optional |

### Using External Servers

Once configured, external MCP server tools are automatically available:

```python
from gleitzeit import GleitzeitClient

# Load configuration with MCP servers
config = {
    "mcp": {
        "servers": [
            {
                "name": "filesystem",
                "connection_type": "stdio",
                "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem"],
                "tool_prefix": "fs."
            }
        ]
    }
}

async with GleitzeitClient(mode="native", native_config=config) as client:
    # Use filesystem tool
    result = await client.execute_task(
        protocol="mcp/v1",
        method="tool.fs.read",
        params={"path": "README.md"}
    )
    print(result)
```

## Advanced Features

### Tool Discovery

MCP servers are queried for available tools on initialization:

```python
async with GleitzeitClient(mode="native", native_config=config) as client:
    # List all available tools
    result = await client.execute_task(
        protocol="mcp/v1",
        method="tools/list",
        params={}
    )
    
    for tool in result["tools"]:
        print(f"Tool: {tool['name']}")
        print(f"  Description: {tool.get('description', 'N/A')}")
```

### Server Management

```python
# List all MCP servers
result = await client.execute_task(
    protocol="mcp/v1",
    method="servers",
    params={}
)

for server in result["servers"]:
    print(f"Server: {server['name']}")
    print(f"  Status: {server['status']}")
    print(f"  Tools: {server['tool_count']}")

# Ping all servers
result = await client.execute_task(
    protocol="mcp/v1",
    method="ping",
    params={}
)
```

### Direct Hub Usage

For advanced use cases, you can use MCPHub directly:

```python
from gleitzeit.hub.mcp_hub import MCPHub

# Create and configure hub
hub = MCPHub(
    auto_discover=True,
    config_data={
        "servers": [
            {
                "name": "my-server",
                "connection_type": "stdio",
                "command": ["python", "server.py"]
            }
        ]
    }
)

await hub.initialize()

# Call tool directly
result = await hub.call_tool(
    "tool_name",
    {"param": "value"}
)

# Get metrics
metrics = await hub.get_metrics()

# Cleanup
await hub.cleanup()
```

### Health Monitoring

MCPHub automatically monitors server health and can restart failed servers:

```python
# Configuration with health monitoring
config = {
    "mcp": {
        "enable_metrics": true,
        "servers": [
            {
                "name": "monitored-server",
                "connection_type": "stdio",
                "command": ["python", "server.py"],
                "restart_on_failure": true,
                "max_retries": 3,
                "health_check_interval": 30.0
            }
        ]
    }
}
```

## Creating Custom MCP Servers

### Basic MCP Server Template

```python
#!/usr/bin/env python3
"""Custom MCP Server"""
import sys
import json
import asyncio

class CustomMCPServer:
    def __init__(self):
        self.tools = {
            "my_tool": "Description of my tool"
        }
    
    async def handle_request(self, request):
        method = request.get("method")
        params = request.get("params", {})
        
        if method == "initialize":
            return {
                "protocolVersion": "2024-11-05",
                "serverInfo": {
                    "name": "custom-server",
                    "version": "1.0.0"
                },
                "capabilities": {"tools": {}}
            }
        
        elif method == "tools/list":
            return {
                "tools": [
                    {
                        "name": name,
                        "description": desc,
                        "inputSchema": {
                            "type": "object",
                            "properties": {}
                        }
                    }
                    for name, desc in self.tools.items()
                ]
            }
        
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            # Implement tool logic
            return {"result": "tool output"}
        
        elif method == "ping":
            return "pong"
    
    async def run(self):
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            
            request = json.loads(line.strip())
            response = await self.handle_request(request)
            
            result = {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "result": response
            }
            
            sys.stdout.write(json.dumps(result) + "\n")
            sys.stdout.flush()

if __name__ == "__main__":
    server = CustomMCPServer()
    asyncio.run(server.run())
```

## Integration Examples

### Example 1: File Processing Pipeline

```yaml
name: "File Processing with MCP"
tasks:
  - id: "read_file"
    method: "mcp/tool.fs.read"
    parameters:
      path: "input.txt"
      
  - id: "process"
    method: "llm/chat"
    dependencies: ["read_file"]
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Summarize: ${read_file.content}"
          
  - id: "save_result"
    method: "mcp/tool.fs.write"
    dependencies: ["process"]
    parameters:
      path: "summary.txt"
      content: "${process.response}"
```

### Example 2: GitHub Integration

```yaml
name: "GitHub Workflow"
tasks:
  - id: "search_web"
    method: "mcp/tool.search"
    parameters:
      query: "latest Python best practices"
      
  - id: "create_issue"
    method: "mcp/tool.gh.create_issue"
    dependencies: ["search_web"]
    parameters:
      repo: "myorg/myrepo"
      title: "Update Python practices"
      body: "Research findings: ${search_web.results}"
```

### Example 3: Multi-Server Coordination

```python
async def coordinate_servers():
    config = {
        "mcp": {
            "servers": [
                {
                    "name": "data",
                    "command": ["python", "data_server.py"],
                    "tool_prefix": "data."
                },
                {
                    "name": "analysis",
                    "command": ["python", "analysis_server.py"],
                    "tool_prefix": "analysis."
                }
            ]
        }
    }
    
    async with GleitzeitClient(mode="native", native_config=config) as client:
        # Load data
        data = await client.execute_task(
            protocol="mcp/v1",
            method="tool.data.load",
            params={"source": "database"}
        )
        
        # Analyze
        result = await client.execute_task(
            protocol="mcp/v1",
            method="tool.analysis.process",
            params={"data": data["result"]}
        )
        
        return result
```

## Troubleshooting

### Common Issues

#### MCP Server Not Starting

**Problem:** External MCP server fails to start

**Solutions:**
1. Check the command is correct and executable
2. Verify working directory exists
3. Check environment variables are set
4. Review server logs in stderr

```python
# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)
```

#### Tools Not Discovered

**Problem:** Tools from external server not appearing

**Solutions:**
1. Ensure server implements `tools/list` method
2. Check tool_prefix configuration
3. Verify server initialization completes
4. Check server returns proper JSON-RPC responses

#### Connection Issues

**Problem:** Cannot connect to WebSocket/HTTP server

**Solutions:**
1. Verify server URL is correct
2. Check authentication tokens
3. Ensure server is running
4. Test connection independently:

```bash
# Test WebSocket
websocat ws://localhost:8765/mcp

# Test HTTP
curl -X POST https://api.example.com/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"ping","params":{},"id":1}'
```

### Debug Mode

Enable detailed MCP logging:

```python
import logging

# Set logging level
logging.getLogger("gleitzeit.hub.mcp_hub").setLevel(logging.DEBUG)
logging.getLogger("gleitzeit.providers.mcp_hub_provider").setLevel(logging.DEBUG)
```

## Performance Considerations

### Connection Pooling

MCPHub uses connection pooling for network-based servers:
- HTTP: Shared aiohttp session with connection pool
- WebSocket: Persistent connections with reconnection logic
- Stdio: Process management with pipe buffering

### Concurrent Requests

- Multiple tools can be called concurrently
- Each MCP instance handles requests sequentially
- Load balancing across multiple instances of same server

### Resource Limits

Configure resource limits for stdio servers:

```yaml
servers:
  - name: "limited-server"
    command: ["python", "server.py"]
    max_memory_mb: 512
    max_cpu_percent: 50.0
    timeout: 30.0
```

## Best Practices

1. **Use Tool Prefixes**: Prevent naming conflicts between servers
2. **Set Appropriate Timeouts**: Adjust based on expected operation duration
3. **Enable Health Monitoring**: For production deployments
4. **Implement Retry Logic**: Handle transient failures
5. **Log Server Output**: Capture stderr for debugging
6. **Version Your Protocols**: Include version in server info
7. **Validate Input**: Check parameters before processing
8. **Handle Graceful Shutdown**: Clean up resources on exit

## API Reference

### Client Methods

```python
# Execute MCP tool
await client.execute_task(
    protocol="mcp/v1",
    method="tool.{name}",
    params={...}
)

# List all tools
await client.execute_task(
    protocol="mcp/v1",
    method="tools/list",
    params={}
)

# List servers
await client.execute_task(
    protocol="mcp/v1",
    method="servers",
    params={}
)

# Ping servers
await client.execute_task(
    protocol="mcp/v1",
    method="ping",
    params={}
)
```

### MCPHub Methods

```python
# Initialize hub
await hub.initialize()

# Call tool
await hub.call_tool(tool_name, arguments, instance_id=None)

# Get instance for tool
instance = await hub.get_instance_for_tool(tool_name)

# Health check
healthy = await hub.check_health(instance_id)

# Restart instance
await hub.restart_instance(instance_id)

# Cleanup
await hub.cleanup()
```

## Further Reading

- [Model Context Protocol Specification](https://modelcontextprotocol.io)
- [Gleitzeit Architecture](./architecture.md)
- [Creating Custom Providers](./providers.md)
- [Workflow Documentation](./workflows.md)