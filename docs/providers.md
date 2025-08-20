# Providers

Providers implement protocols and execute tasks. Gleitzeit includes several built-in providers and supports custom provider development.

## Built-in Providers

### OllamaProvider

Handles LLM operations using Ollama models.

**Protocol:** `llm/v1`

**Methods:**

#### llm/chat

Text generation with conversation context.

```yaml
method: "llm/chat"
parameters:
  model: "llama3.2"          # Required: Ollama model name
  messages:                  # Required: Conversation messages
    - role: "system"         # Optional system message
      content: "You are helpful"
    - role: "user"
      content: "Hello"
  temperature: 0.7           # Optional: 0-1, default 0.7
  max_tokens: 500           # Optional: Max response length
  top_p: 0.9                # Optional: Nucleus sampling
  top_k: 40                 # Optional: Top-k sampling
  seed: 42                  # Optional: For reproducibility
```

#### llm/vision

Image analysis with vision models.

```yaml
method: "llm/vision"
parameters:
  model: "llava"            # Required: Vision model
  images:                   # Required: Image paths
    - "photo.jpg"
  messages:
    - role: "user"
      content: "What's in this image?"
```

#### llm/generate

Direct text generation without conversation context.

```yaml
method: "llm/generate"
parameters:
  model: "llama3.2"
  prompt: "Complete this: Once upon a time"
  temperature: 0.8
```

#### llm/embeddings

Generate text embeddings.

```yaml
method: "llm/embeddings"
parameters:
  model: "llama3.2"
  text: "Text to embed"
```

**Available Models:**

Install models with Ollama:

```bash
# General purpose
ollama pull llama3.2
ollama pull mistral

# Code generation
ollama pull codellama
ollama pull deepseek-coder

# Vision
ollama pull llava
ollama pull bakllava

# Small/fast
ollama pull phi
ollama pull tinyllama
```

### PythonProvider

Executes Python scripts in isolated environments.

**Protocol:** `python/v1`

**Methods:**

#### python/execute

Execute a Python script file.

```yaml
method: "python/execute"
parameters:
  script: "process.py"      # Required: Script path
  args:                     # Optional: Arguments as JSON
    input: "data.csv"
    output: "results.json"
  timeout: 30              # Optional: Timeout in seconds
  env:                     # Optional: Environment variables
    PYTHONPATH: "/custom/path"
```

**Script Requirements:**

Scripts receive arguments via `sys.argv[1]` as JSON and should print JSON output:

```python
#!/usr/bin/env python3
import sys
import json

# Get arguments
args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}

# Process
result = {"status": "success", "data": process(args)}

# Output as JSON
print(json.dumps(result))
```

#### python/validate

Validate Python syntax without execution.

```yaml
method: "python/validate"
parameters:
  script: "code.py"
```

### MCPHubProvider

Manages external MCP (Model Context Protocol) servers.

**Protocol:** `mcp/v1`

**Description:** MCPHubProvider routes MCP tool calls to external MCP servers. It supports stdio, WebSocket, and HTTP connections to MCP-compliant servers.

**Configuration Required:** MCP servers must be configured in `~/.gleitzeit/config.yaml`:

```yaml
mcp:
  servers:
    - name: "filesystem"
      connection_type: "stdio"
      command: ["npx", "-y", "@modelcontextprotocol/server-filesystem"]
      tool_prefix: "fs."
    - name: "github"
      connection_type: "stdio"
      command: ["npx", "-y", "@modelcontextprotocol/server-github"]
      env:
        GITHUB_TOKEN: "${GITHUB_TOKEN}"
```

**Methods:**

#### mcp/tool.*

Execute tools from registered MCP servers. The available tools depend on your configured servers.

Example with filesystem server:

```yaml
method: "mcp/tool.fs.read"
parameters:
  path: "./data.json"
```

Example with GitHub server:

```yaml
method: "mcp/tool.gh.create_issue"
parameters:
  repo: "myorg/myrepo"
  title: "New Issue"
  body: "Issue description"
```

#### mcp/tools/list

List all available tools from all registered servers.

```yaml
method: "mcp/tools/list"
```

#### mcp/servers

Get information about registered MCP servers.

```yaml
method: "mcp/servers"
```



## Provider Configuration

### Ollama Configuration

```yaml
# In ~/.gleitzeit/config.yaml
providers:
  ollama:
    endpoint: http://localhost:11434
    timeout: 30
    max_retries: 3
    models:
      default: llama3.2
      vision: llava
      code: codellama
```

### Python Configuration

```yaml
providers:
  python:
    timeout: 60
    max_memory: "512M"
    allowed_modules:
      - json
      - csv
      - math
      - datetime
    sandbox: true  # Enable sandboxing
```

## Creating Custom Protocols and Providers

### Step 1: Define Your Protocol

First, create a protocol definition file that specifies your protocol's interface:

```python
# my_protocol.py
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from enum import Enum

# Define protocol version
MY_PROTOCOL_V1 = "myprotocol/v1"

# Define method names as constants
class MyProtocolMethods(Enum):
    PROCESS = "myprotocol/process"
    ANALYZE = "myprotocol/analyze"
    TRANSFORM = "myprotocol/transform"

# Define data models for your protocol
@dataclass
class ProcessRequest:
    """Request model for process method"""
    data: str
    options: Dict[str, Any]
    timeout: Optional[int] = 30

@dataclass
class ProcessResponse:
    """Response model for process method"""
    result: Any
    metadata: Dict[str, Any]
    execution_time: float

# Define protocol specification
PROTOCOL_SPEC = {
    "id": MY_PROTOCOL_V1,
    "name": "My Custom Protocol",
    "version": "1.0.0",
    "description": "Protocol for custom data processing",
    "methods": {
        "myprotocol/process": {
            "description": "Process data with custom logic",
            "parameters": {
                "data": {"type": "string", "required": True},
                "options": {"type": "object", "required": False},
                "timeout": {"type": "integer", "default": 30}
            },
            "returns": {
                "result": {"type": "any"},
                "metadata": {"type": "object"}
            }
        },
        "myprotocol/analyze": {
            "description": "Analyze data patterns",
            "parameters": {
                "data": {"type": "string", "required": True},
                "depth": {"type": "string", "enum": ["shallow", "deep"]}
            }
        },
        "myprotocol/transform": {
            "description": "Transform data format",
            "parameters": {
                "input": {"type": "string", "required": True},
                "format": {"type": "string", "required": True}
            }
        }
    }
}
```

### Step 2: Create Your Provider

Implement a provider that handles your protocol's methods:

```python
# my_provider.py
import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from gleitzeit.providers.base import ProtocolProvider
from gleitzeit.core.models import TaskResult
from gleitzeit.core.errors import ProviderError, ValidationError
from my_protocol import (
    MY_PROTOCOL_V1, 
    MyProtocolMethods,
    ProcessRequest,
    ProcessResponse,
    PROTOCOL_SPEC
)

class MyCustomProvider(ProtocolProvider):
    """Provider implementation for my custom protocol"""
    
    def __init__(
        self,
        provider_id: str,
        config: Optional[Dict[str, Any]] = None,
        resource_manager=None,
        hub=None,
        **kwargs
    ):
        """Initialize the custom provider"""
        super().__init__(
            provider_id=provider_id,
            protocol_id=MY_PROTOCOL_V1,
            name="MyCustomProvider",
            description="Handles custom data processing operations",
            resource_manager=resource_manager,
            hub=hub
        )
        self.config = config or {}
        self.logger = logging.getLogger(__name__)
        
        # Initialize any resources (connections, clients, etc.)
        self._initialize_resources()
    
    def _initialize_resources(self):
        """Initialize provider resources"""
        # Example: Initialize connection pools, clients, etc.
        self.max_workers = self.config.get("max_workers", 5)
        self.default_timeout = self.config.get("default_timeout", 30)
        
    async def initialize(self):
        """Async initialization"""
        self.logger.info(f"Initializing {self.name} with ID {self.provider_id}")
        # Perform any async initialization here
        await self._connect_to_service()
        
    async def _connect_to_service(self):
        """Connect to external service if needed"""
        # Example: Connect to database, API, etc.
        pass
    
    def get_supported_methods(self) -> List[str]:
        """Return list of supported methods"""
        return [method.value for method in MyProtocolMethods]
    
    async def validate_request(self, method: str, parameters: Dict[str, Any]) -> None:
        """Validate request parameters"""
        if method not in self.get_supported_methods():
            raise ValidationError(f"Unsupported method: {method}")
        
        # Get method spec from protocol
        method_spec = PROTOCOL_SPEC["methods"].get(method)
        if not method_spec:
            raise ValidationError(f"No specification for method: {method}")
        
        # Validate required parameters
        param_spec = method_spec.get("parameters", {})
        for param_name, param_info in param_spec.items():
            if param_info.get("required") and param_name not in parameters:
                raise ValidationError(f"Missing required parameter: {param_name}")
            
            # Type validation (simplified example)
            if param_name in parameters:
                value = parameters[param_name]
                expected_type = param_info.get("type")
                if expected_type == "string" and not isinstance(value, str):
                    raise ValidationError(f"Parameter {param_name} must be a string")
                elif expected_type == "integer" and not isinstance(value, int):
                    raise ValidationError(f"Parameter {param_name} must be an integer")
    
    async def handle_request(self, method: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Handle incoming requests"""
        # Validate request
        await self.validate_request(method, parameters)
        
        # Route to appropriate handler
        if method == MyProtocolMethods.PROCESS.value:
            return await self._handle_process(parameters)
        elif method == MyProtocolMethods.ANALYZE.value:
            return await self._handle_analyze(parameters)
        elif method == MyProtocolMethods.TRANSFORM.value:
            return await self._handle_transform(parameters)
        else:
            raise ProviderError(f"Method not implemented: {method}")
    
    async def _handle_process(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle process method"""
        start_time = datetime.now()
        
        # Create request object
        request = ProcessRequest(
            data=params["data"],
            options=params.get("options", {}),
            timeout=params.get("timeout", self.default_timeout)
        )
        
        try:
            # Process the data (your custom logic here)
            result = await self._process_data(request)
            
            # Create response
            execution_time = (datetime.now() - start_time).total_seconds()
            response = ProcessResponse(
                result=result,
                metadata={
                    "processed_at": datetime.now().isoformat(),
                    "provider": self.provider_id
                },
                execution_time=execution_time
            )
            
            return {
                "success": True,
                "result": response.result,
                "metadata": response.metadata,
                "execution_time": response.execution_time
            }
            
        except Exception as e:
            self.logger.error(f"Process failed: {e}")
            raise ProviderError(f"Processing failed: {str(e)}")
    
    async def _process_data(self, request: ProcessRequest) -> Any:
        """Actual data processing logic"""
        # Implement your custom processing here
        await asyncio.sleep(0.1)  # Simulate processing
        
        # Example processing
        processed = request.data.upper()
        if "reverse" in request.options:
            processed = processed[::-1]
        
        return processed
    
    async def _handle_analyze(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle analyze method"""
        data = params["data"]
        depth = params.get("depth", "shallow")
        
        # Perform analysis
        analysis = {
            "length": len(data),
            "type": type(data).__name__,
            "depth": depth
        }
        
        if depth == "deep":
            # Add more detailed analysis
            analysis["word_count"] = len(data.split())
            analysis["unique_chars"] = len(set(data))
        
        return {"analysis": analysis}
    
    async def _handle_transform(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle transform method"""
        input_data = params["input"]
        target_format = params["format"]
        
        # Transform based on format
        if target_format == "upper":
            result = input_data.upper()
        elif target_format == "lower":
            result = input_data.lower()
        elif target_format == "title":
            result = input_data.title()
        else:
            raise ValidationError(f"Unsupported format: {target_format}")
        
        return {"transformed": result, "format": target_format}
    
    async def health_check(self) -> Dict[str, Any]:
        """Provider health check"""
        return {
            "status": "healthy",
            "provider": self.provider_id,
            "protocol": self.protocol_id,
            "supported_methods": len(self.get_supported_methods())
        }
    
    async def shutdown(self):
        """Clean shutdown"""
        self.logger.info(f"Shutting down {self.name}")
        # Clean up resources
        await self._cleanup_resources()
    
    async def _cleanup_resources(self):
        """Clean up provider resources"""
        # Close connections, clean up temp files, etc.
        pass
```

### Step 3: Register Your Protocol and Provider

Create a registration module to integrate with Gleitzeit:

```python
# register_my_protocol.py
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.core.protocol import Protocol
from my_protocol import MY_PROTOCOL_V1, PROTOCOL_SPEC
from my_provider import MyCustomProvider

def register_my_protocol():
    """Register custom protocol and provider with Gleitzeit"""
    
    # Get registry instance
    registry = ProtocolProviderRegistry.get_instance()
    
    # Create protocol object
    protocol = Protocol(
        id=MY_PROTOCOL_V1,
        name=PROTOCOL_SPEC["name"],
        version=PROTOCOL_SPEC["version"],
        description=PROTOCOL_SPEC["description"],
        methods=list(PROTOCOL_SPEC["methods"].keys())
    )
    
    # Register protocol
    registry.register_protocol(protocol)
    
    # Create and register provider
    provider = MyCustomProvider(
        provider_id="my-provider-1",
        config={
            "max_workers": 10,
            "default_timeout": 60
        }
    )
    
    # Register provider for the protocol
    registry.register_provider(MY_PROTOCOL_V1, provider)
    
    # Register individual method handlers (optional, for fine-grained control)
    for method in PROTOCOL_SPEC["methods"].keys():
        registry.register_method_handler(method, provider)
    
    return provider

# Auto-register when imported
if __name__ != "__main__":
    register_my_protocol()
```

### Step 4: Use Your Custom Protocol in Workflows

Once registered, use your protocol in workflows:

```yaml
name: "Custom Protocol Example"
tasks:
  - id: "process_data"
    method: "myprotocol/process"
    parameters:
      data: "Hello World"
      options:
        reverse: true
      timeout: 30
  
  - id: "analyze_result"
    method: "myprotocol/analyze"
    dependencies: ["process_data"]
    parameters:
      data: "${process_data.result}"
      depth: "deep"
  
  - id: "transform_output"
    method: "myprotocol/transform"
    dependencies: ["analyze_result"]
    parameters:
      input: "${process_data.result}"
      format: "title"
```

### Step 5: Integrate with Gleitzeit Client

Use your custom protocol from Python:

```python
import asyncio
from gleitzeit import GleitzeitClient
from register_my_protocol import register_my_protocol

async def use_custom_protocol():
    # Register protocol (if not auto-registered)
    register_my_protocol()
    
    async with GleitzeitClient(mode="native") as client:
        # Execute custom task
        result = await client.execute_task({
            "id": "custom_task",
            "method": "myprotocol/process",
            "parameters": {
                "data": "test data",
                "options": {"reverse": True}
            }
        })
        
        print(f"Result: {result}")
        
        # Run workflow with custom protocol
        workflow_result = await client.run_workflow("custom_workflow.yaml")
        print(f"Workflow result: {workflow_result}")

asyncio.run(use_custom_protocol())
```

### Best Practices for Custom Protocols

1. **Protocol Design**
   - Keep protocols focused on a single domain
   - Use versioning (e.g., `myprotocol/v1`, `myprotocol/v2`)
   - Define clear method signatures
   - Document all parameters and return types

2. **Provider Implementation**
   - Inherit from `ProtocolProvider` base class
   - Implement proper validation
   - Handle errors gracefully
   - Include health checks
   - Clean up resources on shutdown

3. **Error Handling**
   - Use specific exception types
   - Provide helpful error messages
   - Log errors appropriately
   - Implement retry logic where appropriate

4. **Performance**
   - Use connection pooling
   - Implement caching where beneficial
   - Handle concurrent requests properly
   - Set appropriate timeouts

5. **Testing**
   ```python
   import pytest
   from my_provider import MyCustomProvider
   
   @pytest.mark.asyncio
   async def test_process_method():
       provider = MyCustomProvider("test-provider")
       await provider.initialize()
       
       result = await provider.handle_request(
           "myprotocol/process",
           {"data": "test", "options": {}}
       )
       
       assert result["success"] == True
       assert "result" in result
   ```

### Example: Database Protocol

Here's a complete example of a database protocol:

```python
# db_protocol.py
DATABASE_PROTOCOL_V1 = "database/v1"

class DatabaseProvider(ProtocolProvider):
    def __init__(self, provider_id: str, connection_string: str):
        super().__init__(
            provider_id=provider_id,
            protocol_id=DATABASE_PROTOCOL_V1,
            name="DatabaseProvider"
        )
        self.connection_string = connection_string
        self.pool = None
    
    async def initialize(self):
        # Create connection pool
        import asyncpg
        self.pool = await asyncpg.create_pool(self.connection_string)
    
    async def handle_request(self, method: str, parameters: Dict[str, Any]):
        if method == "database/query":
            return await self._execute_query(parameters)
        elif method == "database/insert":
            return await self._execute_insert(parameters)
    
    async def _execute_query(self, params):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(params["sql"], *params.get("values", []))
            return {"rows": [dict(row) for row in rows]}
    
    async def shutdown(self):
        if self.pool:
            await self.pool.close()
```

Use in workflow:
```yaml
tasks:
  - id: "fetch_users"
    method: "database/query"
    parameters:
      sql: "SELECT * FROM users WHERE active = $1"
      values: [true]
```

## Provider Selection

Providers are selected based on the method prefix:

- `llm/*` → OllamaProvider
- `python/*` → PythonProvider
- `mcp/*` → MCPHubProvider

## Resource Management

### OllamaHub

Manages Ollama instances:

```python
# Auto-discovery on ports 11434-11439
# Health monitoring
# Load balancing across instances
# Model-aware routing
```

### DockerHub (Optional)

Manages Docker containers for Python execution:

```python
# Container lifecycle management
# Resource limits
# Security isolation
```

## Error Handling

Providers implement automatic retry logic:

```yaml
tasks:
  - id: "task"
    method: "llm/chat"
    retry:
      max_attempts: 3
      delay: 2
      exponential_backoff: true
```

## Performance Considerations

### Connection Pooling

Providers use connection pooling for efficiency:

```python
# OllamaProvider uses aiohttp session pooling
# Reuses connections across requests
# Configurable pool size
```

### Caching

Some providers implement caching:

```python
# Python bytecode caching
# Model response caching (optional)
```

### Timeouts

All providers support configurable timeouts:

```yaml
parameters:
  timeout: 30  # Task-level timeout
```

## Provider Capabilities

| Provider | Async | Streaming | Batch | Caching | Sandboxed |
|----------|-------|-----------|-------|---------|-----------|
| Ollama | ✓ | ✓ | ✓ | ✗ | N/A |
| Python | ✓ | ✗ | ✗ | ✓ | ✓ |
| MCP | ✓ | ✗ | ✗ | ✗ | N/A |

## Best Practices

1. **Set appropriate timeouts** - Prevent hanging tasks
2. **Use retry logic** - Handle transient failures
3. **Validate inputs** - Check parameters before execution
4. **Handle errors gracefully** - Provide useful error messages
5. **Log operations** - For debugging
6. **Use connection pooling** - For efficiency
7. **Implement caching** - Where appropriate
8. **Monitor resource usage** - Prevent resource exhaustion

## Examples

### Multi-Provider Workflow

```yaml
name: "Multi-Provider Example"
tasks:
  # Generate data with Python
  - id: "generate"
    method: "python/execute"
    parameters:
      script: "generate_data.py"
  
  # Analyze with LLM
  - id: "analyze"
    method: "llm/chat"
    dependencies: ["generate"]
    parameters:
      model: "llama3.2"
      messages:
        - content: "Analyze: ${generate.data}"
  
  # Process data with Python
  - id: "calculate"
    method: "python/execute"
    dependencies: ["analyze"]
    parameters:
      code: |
        result = 100 + 50
        print({"result": result})
  
  # Generate final report
  - id: "report"
    method: "llm/chat"
    dependencies: ["analyze", "calculate"]
    parameters:
      model: "llama3.2"
      messages:
        - content: |
            Create a report with:
            Analysis: ${analyze.response}
            Calculation result: ${calculate.result}
```