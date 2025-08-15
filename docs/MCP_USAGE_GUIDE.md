# MCP Provider Usage Guide

## Overview

The Model Context Protocol (MCP) provider in Gleitzeit enables workflow tasks to use MCP-compatible tools. The current implementation uses `SimpleMCPProvider`, which provides built-in tools for testing and demonstration without requiring external MCP servers.

## Current Implementation

### SimpleMCPProvider

The SimpleMCPProvider (`src/gleitzeit/providers/simple_mcp_provider.py`) is automatically registered when running workflows through the CLI. It provides a simplified MCP implementation with built-in tools.

**Key Features:**
- No external dependencies or subprocess management
- Built-in tools for common operations
- Full integration with Gleitzeit's protocol system
- Automatic backend persistence of results
- Parameter substitution support

## Available Tools

### 1. Echo Tool (`mcp/tool.echo`)
Returns the input message with metadata.

```yaml
- id: "echo_task"
  method: "mcp/tool.echo"
  parameters:
    message: "Hello, MCP!"
```

**Returns:**
```json
{
  "response": "Hello, MCP!",
  "echoed": true,
  "length": 11
}
```

### 2. Add Tool (`mcp/tool.add`)
Adds two numbers together.

```yaml
- id: "add_task"
  method: "mcp/tool.add"
  parameters:
    a: 10
    b: 20
```

**Returns:**
```json
{
  "result": 30,
  "response": "30",
  "calculation": "10 + 20 = 30"
}
```

### 3. Multiply Tool (`mcp/tool.multiply`)
Multiplies two numbers.

```yaml
- id: "multiply_task"
  method: "mcp/tool.multiply"
  parameters:
    a: 5
    b: 6
```

**Returns:**
```json
{
  "result": 30,
  "response": "30",
  "calculation": "5 * 6 = 30"
}
```

### 4. Concat Tool (`mcp/tool.concat`)
Concatenates multiple strings with an optional separator.

```yaml
- id: "concat_task"
  method: "mcp/tool.concat"
  parameters:
    strings:
      - "Hello"
      - "World"
      - "from MCP"
    separator: " "
```

**Returns:**
```json
{
  "result": "Hello World from MCP",
  "response": "Hello World from MCP",
  "count": 3
}
```

## Workflow Examples

### Basic MCP Workflow

```yaml
name: "Basic MCP Example"
description: "Demonstrates MCP tool usage"

tasks:
  - id: "greeting"
    name: "Create Greeting"
    method: "mcp/tool.echo"
    parameters:
      message: "Welcome to MCP!"
    priority: "normal"

  - id: "math_operation"
    name: "Perform Calculation"
    method: "mcp/tool.add"
    parameters:
      a: 100
      b: 50
    priority: "normal"
```

### Using Parameter Substitution

```yaml
name: "MCP with Dependencies"
description: "Chain MCP tools using parameter substitution"

tasks:
  - id: "initial_calc"
    name: "Initial Calculation"
    method: "mcp/tool.add"
    parameters:
      a: 10
      b: 15
    priority: "normal"

  - id: "double_result"
    name: "Double the Result"
    method: "mcp/tool.multiply"
    dependencies: ["initial_calc"]
    parameters:
      a: "${initial_calc.result}"  # Uses result from previous task
      b: 2
    priority: "normal"

  - id: "create_message"
    name: "Create Summary Message"
    method: "mcp/tool.concat"
    dependencies: ["initial_calc", "double_result"]
    parameters:
      strings:
        - "Initial sum: ${initial_calc.result}"
        - "Doubled value: ${double_result.result}"
      separator: " | "
    priority: "normal"
```

### Complete Example Workflow

See `examples/simple_mcp_workflow.yaml` for a comprehensive example:

```yaml
name: "Simple MCP Workflow"
description: "Workflow using the simple MCP provider"

tasks:
  - id: "echo_test"
    name: "Echo Message"
    method: "mcp/tool.echo"
    parameters:
      message: "Hello from Simple MCP!"
    priority: "normal"

  - id: "calculate_sum"
    name: "Add Numbers"
    method: "mcp/tool.add"
    parameters:
      a: 42
      b: 58
    priority: "normal"

  - id: "calculate_product"
    name: "Multiply Numbers"
    method: "mcp/tool.multiply"
    dependencies: ["calculate_sum"]
    parameters:
      a: "${calculate_sum.result}"
      b: 2
    priority: "normal"

  - id: "combine_results"
    name: "Combine All Results"
    method: "mcp/tool.concat"
    dependencies: ["echo_test", "calculate_product"]
    parameters:
      strings:
        - "${echo_test.response}"
        - "Sum was ${calculate_sum.result}"
        - "Product is ${calculate_product.result}"
      separator: " | "
    priority: "normal"
```

## Running MCP Workflows

### Using the CLI

```bash
# Run a simple MCP workflow
python src/gleitzeit/cli/gleitzeit_cli.py run examples/simple_mcp_workflow.yaml

# Run with custom configuration
PYTHONPATH=src python src/gleitzeit/cli/gleitzeit_cli.py run my_mcp_workflow.yaml
```

### Programmatically

```python
import asyncio
from gleitzeit.cli.gleitzeit_cli import GleitzeitCLI

async def run_mcp_workflow():
    cli = GleitzeitCLI()
    success = await cli.run("examples/simple_mcp_workflow.yaml")
    return success

# Run the workflow
asyncio.run(run_mcp_workflow())
```

## Backend Persistence

All MCP task results are automatically persisted to the configured backend (SQLite by default):

- Task execution details stored in `tasks` table
- Results stored in `task_results` table
- Complete workflow state maintained

Results can be retrieved later:

```python
from gleitzeit.persistence.sqlite_backend import SQLiteBackend

backend = SQLiteBackend(db_path)
await backend.initialize()

# Get task result
task_result = await backend.get_task_result("echo_test")
print(task_result.result)  # {'response': 'Hello from Simple MCP!', ...}
```

## Testing

### Unit Tests

Run the MCP backend persistence test:

```bash
python tests/test_mcp_backend_persistence.py
```

### Test All MCP Workflows

```bash
python tests/test_mcp_workflows.py
```

## Protocol Definition

The MCP protocol is defined in `src/gleitzeit/protocols/mcp_protocol.py`:

- **Protocol ID**: `mcp/v1`
- **Tool methods**: `mcp/tool.{tool_name}`
- **Method naming**: Methods must include the `mcp/` prefix

## Configuration

MCP provider is enabled by default in the CLI. To disable:

```python
# In config or environment
providers:
  mcp:
    enabled: false
```

## Future Enhancements

The current SimpleMCPProvider is designed for testing and built-in functionality. Future enhancements will include:

1. **External MCP Server Support**
   - Subprocess-based communication with external MCP servers
   - Support for stdio and HTTP transports
   - Dynamic tool discovery from servers

2. **Advanced Features**
   - Resource management (files, databases, APIs)
   - Prompt and template support
   - Context sharing between tools

3. **Additional Built-in Tools**
   - File operations
   - Data transformation
   - API interactions

See `docs/MCP_PROVIDER_DESIGN.md` for the complete roadmap.

## Troubleshooting

### Common Issues

**Method not found error:**
```
Method 'mcp/ping' not found in protocol 'mcp/v1'
```
- Only the built-in tools are currently available
- Check available methods in SimpleMCPProvider

**Parameter substitution not working:**
- Ensure task dependencies are correctly defined
- Use the correct syntax: `${task_id.field}`
- Check that the referenced task has completed successfully

**Results not persisting:**
- Verify backend is initialized
- Check database connection
- Ensure workflow completes successfully

## Examples Repository

All working examples are in:
- `examples/simple_mcp_workflow.yaml` - Basic MCP workflow
- `examples/mcp_workflow.yaml` - More complex MCP workflow
- `tests/mcp_test_workflow.yaml` - Test workflow for validation