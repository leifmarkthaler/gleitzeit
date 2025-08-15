# MCP Provider Implementation

## Overview
The Model Context Protocol (MCP) provider enables Gleitzeit to interact with MCP-compatible tools and services. The current implementation uses a simplified approach with built-in tools for testing and demonstration.

## Current Implementation

### SimpleMCPProvider
The `SimpleMCPProvider` (`src/gleitzeit/providers/simple_mcp_provider.py`) is the current working implementation that provides MCP functionality without the complexity of subprocess communication.

```python
class SimpleMCPProvider(ProtocolProvider):
    """
    Simplified MCP Provider for testing and demonstration
    
    Features:
    - Built-in tools (echo, add, multiply, concat)
    - Direct method execution without subprocess overhead
    - Full integration with Gleitzeit's protocol system
    """
```

### Key Components

#### 1. Protocol Definition
The MCP protocol is defined in `src/gleitzeit/protocols/mcp_protocol.py`:
- Protocol ID: `mcp/v1`
- Tool methods use prefix: `mcp/tool.{tool_name}`
- Server info methods: `mcp/server_info`, `mcp/ping`
- Tool listing: `mcp/tools/list`

#### 2. Method Handling
```python
def get_supported_methods(self) -> List[str]:
    """Returns methods WITH protocol prefix"""
    methods = ["mcp/tools/list", "mcp/server_info", "mcp/ping"]
    for tool_name in self.tools.keys():
        methods.append(f"mcp/tool.{tool_name}")
    return methods

async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
    """Strips protocol prefix for internal processing"""
    if method.startswith("mcp/"):
        method = method[4:]  # Remove "mcp/" prefix
```

#### 3. Built-in Tools
- **echo**: Returns the input message with metadata
- **add**: Adds two numbers
- **multiply**: Multiplies two numbers  
- **concat**: Concatenates two strings

## Workflow Integration

### Example MCP Workflow
```yaml
name: "Simple MCP Workflow"
description: "Demonstration of MCP provider capabilities"

tasks:
  - id: "echo_test"
    name: "Echo Test"
    method: "mcp/tool.echo"
    parameters:
      message: "Hello from Simple MCP!"
    priority: "normal"

  - id: "add_numbers"
    name: "Add Numbers"
    method: "mcp/tool.add"
    dependencies: ["echo_test"]
    parameters:
      a: 50
      b: 50
    priority: "normal"

  - id: "multiply_result"
    name: "Multiply Result"
    method: "mcp/tool.multiply"
    dependencies: ["add_numbers"]
    parameters:
      a: "${add_numbers.result}"  # Use result from previous task
      b: 2
    priority: "normal"
```

## CLI Integration

The MCP provider is automatically registered when running workflows through the CLI:

```python
# In gleitzeit_cli.py
mcp_config = provider_config.get('mcp', {})
if mcp_config.get('enabled', True):
    registry.register_protocol(MCP_PROTOCOL_V1)
    mcp_provider = SimpleMCPProvider("cli-mcp-provider")
    await mcp_provider.initialize()
    registry.register_provider("cli-mcp-provider", "mcp/v1", mcp_provider)
```

## Backend Persistence

MCP task results are automatically persisted to the configured backend (SQLite/Redis):
- Task execution details stored in `tasks` table
- Results stored in `task_results` table
- Full workflow state maintained across executions

## Testing

### Unit Tests
Located in `/tests/test_mcp_backend_persistence.py`:
- Tests MCP task execution
- Verifies backend persistence
- Validates result retrieval

### Running Tests
```bash
# Run MCP-specific tests
python tests/test_mcp_backend_persistence.py

# Run with workflow file
python -m gleitzeit.cli.gleitzeit_cli run examples/simple_mcp_workflow.yaml
```

## Future Enhancements

### Phase 1: External MCP Server Support
- Add subprocess-based communication for external MCP servers
- Support for stdio and HTTP transports
- Dynamic tool discovery from external servers

### Phase 2: Advanced Features
- Resource management (files, databases, APIs)
- Prompt/template support
- Context sharing between tools
- Authentication and authorization

### Phase 3: Production Features
- Connection pooling for external servers
- Health monitoring and auto-reconnect
- Comprehensive error handling
- Performance optimization

## Configuration

### Provider Configuration
```yaml
providers:
  mcp:
    enabled: true
    # Future: external server configurations
    servers:
      - name: "filesystem"
        transport: "stdio"
        command: ["npx", "@modelcontextprotocol/server-filesystem"]
        args: ["--root", "/data"]
```

## Architecture Benefits

1. **Simplicity**: Current implementation avoids subprocess complexity
2. **Reliability**: No external process management required
3. **Testing**: Easy to test with built-in tools
4. **Integration**: Full compatibility with Gleitzeit's protocol system
5. **Extensibility**: Easy to extend with new tools or external servers

## Migration Path

When adding external MCP server support:
1. Keep SimpleMCPProvider for testing and built-in tools
2. Create MCPSubprocessProvider for external servers
3. Use factory pattern to instantiate appropriate provider
4. Maintain backward compatibility with existing workflows