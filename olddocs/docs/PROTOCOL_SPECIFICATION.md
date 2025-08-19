# Protocol Specification

Gleitzeit uses a protocol-based architecture where providers implement specific protocols to handle different types of tasks. This document defines the protocol specifications and how to implement them.

## Protocol Overview

### Core Concept

A protocol defines:
- **Method signatures**: What methods are available
- **Parameter schemas**: Expected input formats
- **Response formats**: Standard output structures
- **Error handling**: How failures are communicated

### Protocol Structure

```python
from gleitzeit.core.protocol import Protocol

class MyProtocol(Protocol):
    protocol_name = "my_protocol"
    version = "v1"
    
    async def handle_request(self, method: str, params: dict) -> dict:
        # Implementation
        pass
```

## Built-in Protocols

### LLM Protocol (`llm/v1`)

For Large Language Model interactions.

#### Methods

**`llm/chat`** - Text generation
```yaml
method: "llm/chat"
parameters:
  model: "llama3.2:latest"          # Required
  messages:                         # Required
    - role: "user"
      content: "Hello, world!"
  temperature: 0.7                  # Optional (0.0-2.0)
  max_tokens: 1000                  # Optional
  stream: false                     # Optional
```

**`llm/vision`** - Image analysis
```yaml
method: "llm/vision"
parameters:
  model: "llava:latest"             # Required
  messages:                         # Required
    - role: "user"
      content: "Describe this image"
  image: "base64_encoded_image"     # Required
  temperature: 0.7                  # Optional
```

#### Response Format

```json
{
  "response": "Generated text content",
  "metadata": {
    "model": "llama3.2:latest",
    "usage": {
      "prompt_tokens": 50,
      "completion_tokens": 200,
      "total_tokens": 250
    },
    "finish_reason": "stop",
    "cost": 0.001
  }
}
```

### Python Protocol (`python/v1`)

For Python code execution.

#### Methods

**`python/execute`** - Run Python code
```yaml
method: "python/execute"
parameters:
  code: |                          # Required
    import math
    result = math.sqrt(16)
    print(f"Result: {result}")
  timeout: 30                      # Optional (seconds)
  environment: "docker"            # Optional: docker|local
  packages: ["numpy", "pandas"]    # Optional: pip packages
```

**`python/validate`** - Syntax validation
```yaml
method: "python/validate"
parameters:
  code: |                          # Required
    def hello():
        print("Hello, world!")
```

#### Response Format

```json
{
  "response": "4.0",              // Script output/return value
  "metadata": {
    "exit_code": 0,
    "execution_time": 0.150,
    "stdout": "Result: 4.0\n",
    "stderr": "",
    "environment": "docker",
    "python_version": "3.11.5"
  }
}
```

### MCP Protocol (`mcp/v1`)

For Model Context Protocol tool integration.

#### Methods

**`mcp/tool.*`** - Tool execution (dynamic methods)
```yaml
method: "mcp/tool.echo"
parameters:
  message: "Hello from MCP!"      # Tool-specific parameters

method: "mcp/tool.add"
parameters:
  a: 5
  b: 3

method: "mcp/tool.file_read"
parameters:
  path: "/path/to/file.txt"
```

#### Response Format

```json
{
  "response": "Tool-specific output",
  "metadata": {
    "tool": "echo",
    "server": "simple_mcp",
    "execution_time": 0.050,
    "success": true
  }
}
```

## Custom Protocol Implementation

### Basic Protocol

```python
from typing import Dict, Any
from gleitzeit.core.protocol import Protocol
from gleitzeit.core.errors import ProtocolError

class DatabaseProtocol(Protocol):
    protocol_name = "database"
    version = "v1"
    
    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self.connection = None
    
    async def initialize(self) -> None:
        """Initialize protocol resources"""
        # Setup database connection
        pass
    
    async def cleanup(self) -> None:
        """Cleanup protocol resources"""
        # Close database connection
        pass
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle protocol method calls"""
        if method == "database/query":
            return await self._execute_query(params)
        elif method == "database/insert":
            return await self._insert_data(params)
        else:
            raise ProtocolError(f"Unknown method: {method}")
    
    async def _execute_query(self, params: Dict[str, Any]) -> Dict[str, Any]:
        sql = params["sql"]
        # Execute query
        result = await self._run_sql(sql)
        
        return {
            "response": result,
            "metadata": {
                "rows_affected": len(result),
                "execution_time": 0.150,
                "query": sql
            }
        }
    
    async def _insert_data(self, params: Dict[str, Any]) -> Dict[str, Any]:
        table = params["table"]
        data = params["data"]
        # Insert data
        rows_inserted = await self._insert(table, data)
        
        return {
            "response": f"Inserted {rows_inserted} rows",
            "metadata": {
                "table": table,
                "rows_inserted": rows_inserted
            }
        }
```

### Protocol Registration

```python
from gleitzeit.registry import ProtocolProviderRegistry

# Register custom protocol
registry = ProtocolProviderRegistry()
registry.register_protocol("database/v1", DatabaseProtocol)

# Create provider using protocol
provider = registry.create_provider("database/v1", connection_string="postgresql://...")
```

### Usage in Workflows

```yaml
tasks:
  - id: "fetch_users"
    method: "database/query"
    parameters:
      sql: "SELECT * FROM users WHERE active = true"
  
  - id: "process_users"
    method: "python/execute"
    dependencies: ["fetch_users"]
    parameters:
      code: |
        users = ${fetch_users.response}
        result = f"Found {len(users)} active users"
```

## Protocol Best Practices

### Error Handling

```python
from gleitzeit.core.errors import ProtocolError, ProtocolValidationError

async def handle_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        # Validate parameters
        if "required_param" not in params:
            raise ProtocolValidationError("Missing required parameter: required_param")
        
        # Execute method
        result = await self._execute_method(method, params)
        
        return {
            "response": result,
            "metadata": {
                "method": method,
                "success": True
            }
        }
        
    except ValidationError as e:
        raise ProtocolValidationError(f"Invalid parameters: {e}")
    except TimeoutError as e:
        raise ProtocolError(f"Operation timed out: {e}")
    except Exception as e:
        raise ProtocolError(f"Unexpected error: {e}")
```

### Parameter Validation

```python
from pydantic import BaseModel, Field
from typing import Optional

class QueryParams(BaseModel):
    sql: str = Field(..., description="SQL query to execute")
    limit: Optional[int] = Field(None, gt=0, le=1000)
    timeout: Optional[float] = Field(30.0, gt=0, le=300)

async def _execute_query(self, params: Dict[str, Any]) -> Dict[str, Any]:
    # Validate parameters using Pydantic
    validated_params = QueryParams(**params)
    
    # Use validated parameters
    result = await self._run_sql(
        validated_params.sql,
        limit=validated_params.limit,
        timeout=validated_params.timeout
    )
    
    return {"response": result}
```

### Resource Management

```python
class HttpProtocol(Protocol):
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.session = None
    
    async def initialize(self) -> None:
        """Initialize HTTP session"""
        import aiohttp
        self.session = aiohttp.ClientSession()
    
    async def cleanup(self) -> None:
        """Clean up HTTP session"""
        if self.session:
            await self.session.close()
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if method == "http/get":
            async with self.session.get(f"{self.base_url}{params['path']}") as response:
                data = await response.text()
                return {
                    "response": data,
                    "metadata": {
                        "status_code": response.status,
                        "headers": dict(response.headers)
                    }
                }
```

## Protocol Testing

### Unit Tests

```python
import pytest
from gleitzeit.protocols.database import DatabaseProtocol

@pytest.mark.asyncio
async def test_database_query():
    protocol = DatabaseProtocol("sqlite://memory:")
    await protocol.initialize()
    
    try:
        result = await protocol.handle_request(
            "database/query",
            {"sql": "SELECT 1 as test"}
        )
        
        assert result["response"] == [{"test": 1}]
        assert result["metadata"]["rows_affected"] == 1
        
    finally:
        await protocol.cleanup()

@pytest.mark.asyncio  
async def test_database_validation():
    protocol = DatabaseProtocol("sqlite://memory:")
    
    with pytest.raises(ProtocolValidationError):
        await protocol.handle_request("database/query", {})  # Missing sql parameter
```

### Integration Tests

```python
from gleitzeit.core.execution_engine import ExecutionEngine
from gleitzeit.core.models import Workflow, Task

@pytest.mark.asyncio
async def test_custom_protocol_integration():
    # Setup engine with custom protocol
    registry = ProtocolProviderRegistry()
    registry.register_protocol("database/v1", DatabaseProtocol)
    
    engine = ExecutionEngine(registry=registry)
    
    # Create workflow using custom protocol
    workflow = Workflow(
        name="Database Test",
        tasks=[
            Task(
                id="query_test",
                method="database/query",
                parameters={"sql": "SELECT * FROM test_table"}
            )
        ]
    )
    
    # Execute workflow
    result = await engine.execute_workflow(workflow)
    assert result.status == "completed"
```

## Protocol Versioning

### Version Management

```python
class MyProtocol(Protocol):
    protocol_name = "my_protocol"
    version = "v2"  # Updated version
    
    # Maintain backward compatibility
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        # Handle v1 compatibility
        if self._is_v1_request(params):
            return await self._handle_v1_request(method, params)
        
        # Handle v2 request
        return await self._handle_v2_request(method, params)
```

### Migration Strategy

1. **Additive changes**: Add new methods/parameters without breaking existing ones
2. **Deprecation warnings**: Warn about deprecated features before removal
3. **Version negotiation**: Support multiple versions simultaneously
4. **Clear documentation**: Document breaking changes and migration paths

This protocol system provides flexibility while maintaining consistency across different types of task execution.