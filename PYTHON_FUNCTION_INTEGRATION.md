# Python Function Integration in Gleitzeit V4

## Overview

Gleitzeit V4 provides seamless integration with Python functions through the `python/v1` protocol. This allows you to:
- Execute arbitrary Python functions as workflow tasks
- Use custom business logic in workflows
- Process data with Python's rich ecosystem
- Create reusable function libraries

## Integration Methods

### 1. Built-in Functions

The Python function provider comes with common functions pre-registered:

```yaml
# workflow.yaml
tasks:
  - id: "calculate-sqrt"
    protocol: "python/v1"
    method: "execute"
    params:
      function: "math.sqrt"
      args: [16]
```

Available built-in functions:
- Math: `math.sqrt`, `math.sin`, `math.cos`, `math.factorial`
- String: `str.upper`, `str.lower`, `str.strip`
- List: `len`, `sum`, `max`, `min`, `sorted`
- JSON: `json.dumps`, `json.loads`

### 2. Custom Function Files

Create Python functions in a `.py` file:

```python
# ~/.gleitzeit/functions/my_functions.py
def process_data(data: list, operation: str) -> dict:
    """Process data with specified operation"""
    if operation == "sum":
        return {"result": sum(data)}
    elif operation == "average":
        return {"result": sum(data) / len(data)}
    elif operation == "stats":
        return {
            "sum": sum(data),
            "mean": sum(data) / len(data),
            "min": min(data),
            "max": max(data)
        }
    return {"error": "Unknown operation"}

async def async_fetch_data(url: str) -> dict:
    """Async function to fetch data"""
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.json()
```

Use in workflow:

```yaml
tasks:
  - id: "process"
    protocol: "python/v1"
    method: "execute"
    params:
      function: "my_functions.process_data"
      args: [[1, 2, 3, 4, 5], "stats"]
```

### 3. Lambda Functions

Register lambda functions dynamically:

```yaml
tasks:
  - id: "register-lambda"
    protocol: "python/v1"
    method: "register"
    params:
      name: "double"
      type: "lambda"
      lambda: "lambda x: x * 2"
  
  - id: "use-lambda"
    protocol: "python/v1"
    method: "execute"
    dependencies: ["register-lambda"]
    params:
      function: "double"
      args: [21]
```

### 4. Module Functions

Import functions from Python standard library or installed packages:

```yaml
tasks:
  - id: "register-module-func"
    protocol: "python/v1"
    method: "register"
    params:
      name: "url_parse"
      type: "module"
      module: "urllib.parse"
      function: "urlparse"
  
  - id: "parse-url"
    protocol: "python/v1"
    method: "execute"
    dependencies: ["register-module-func"]
    params:
      function: "url_parse"
      args: ["https://example.com/path?query=value"]
```

## Complete Example Workflow

```yaml
# data_pipeline.yaml
name: "Data Processing Pipeline"
description: "Process data using Python functions"

tasks:
  # Generate initial data
  - id: "generate-data"
    name: "Generate Fibonacci Numbers"
    protocol: "python/v1"
    method: "execute"
    priority: "high"
    params:
      function: "data_processing.calculate_fibonacci"
      args: [10]

  # Analyze generated data
  - id: "analyze-data"
    name: "Statistical Analysis"
    protocol: "python/v1"
    method: "execute"
    dependencies: ["generate-data"]
    params:
      function: "data_processing.analyze_data"
      args: ["${generate-data.result.result}"]

  # Transform results
  - id: "transform-json"
    name: "Transform JSON Structure"
    protocol: "python/v1"
    method: "execute"
    dependencies: ["analyze-data"]
    params:
      function: "data_processing.transform_json"
      args: [
        "${analyze-data.result.result}",
        {"mean": "average", "sum": "total"}
      ]

  # Validate final data
  - id: "validate"
    name: "Validate Results"
    protocol: "python/v1"
    method: "execute"
    dependencies: ["transform-json"]
    params:
      function: "data_processing.validate_data"
      args: ["${transform-json.result.result}"]
      kwargs:
        rules:
          type: "dict"
          min_length: 1
```

## Setting Up Python Function Provider

### 1. Standalone Provider

```python
from gleitzeit_v4.providers.python_function_provider import CustomFunctionProvider
from pathlib import Path

# Create provider with custom functions directory
provider = CustomFunctionProvider(
    provider_id="my-python-provider",
    functions_dir=Path("./my_functions")
)

# Initialize
await provider.initialize()

# Execute function
result = await provider.handle_request("execute", {
    "function": "my_module.my_function",
    "args": [1, 2, 3],
    "kwargs": {"option": "value"}
})
```

### 2. Socket.IO Provider

```python
from gleitzeit_v4.client.socketio_provider import SocketIOPythonFunctionProvider
from pathlib import Path

# Start provider client
provider = SocketIOPythonFunctionProvider(
    provider_id="python-provider-1",
    server_url="http://localhost:8000",
    functions_dir=Path("./my_functions")
)

await provider.start()
```

### 3. CLI Usage

```bash
# Submit workflow with Python functions
python -m gleitzeit_v4.cli workflow submit data_pipeline.yaml --wait

# Execute single Python function task
python -m gleitzeit_v4.cli task submit \
  --protocol python/v1 \
  --method execute \
  --params '{"function": "math.sqrt", "args": [16]}' \
  --wait
```

## Writing Custom Functions

### Best Practices

1. **Type Hints**: Use type hints for clarity
```python
def process(data: List[Dict[str, Any]], config: Dict[str, str]) -> Dict[str, Any]:
    """Process data with configuration"""
    pass
```

2. **Error Handling**: Return errors in structured format
```python
def safe_divide(a: float, b: float) -> Dict[str, Any]:
    """Safely divide two numbers"""
    if b == 0:
        return {"error": "Division by zero", "success": False}
    return {"result": a / b, "success": True}
```

3. **Async Support**: Use async for I/O operations
```python
async def fetch_and_process(url: str) -> Dict[str, Any]:
    """Fetch and process data asynchronously"""
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.json()
            return {"processed": transform_data(data)}
```

4. **Parameter Validation**: Validate inputs
```python
def validate_and_process(data: Any, schema: Dict) -> Dict[str, Any]:
    """Validate data against schema before processing"""
    errors = validate_schema(data, schema)
    if errors:
        return {"errors": errors, "valid": False}
    
    result = process_valid_data(data)
    return {"result": result, "valid": True}
```

## Advanced Features

### 1. Dynamic Function Registration

```python
# Register function at runtime
await provider.handle_request("register", {
    "name": "custom_processor",
    "type": "lambda",
    "lambda": "lambda x, y: {'sum': x + y, 'product': x * y}"
})
```

### 2. Function Introspection

```python
# Get function information
info = await provider.handle_request("info", {
    "function": "data_processing.analyze_data"
})
# Returns: name, signature, docstring, is_async
```

### 3. Batch Processing

```python
def batch_process(items: List[Any], func_name: str) -> List[Any]:
    """Apply function to each item in batch"""
    func = globals().get(func_name)
    if not func:
        return {"error": f"Function {func_name} not found"}
    
    return [func(item) for item in items]
```

### 4. State Management

```python
# Global state for stateful operations
_state = {}

def set_state(key: str, value: Any) -> Dict[str, Any]:
    """Set global state value"""
    _state[key] = value
    return {"key": key, "value": value, "success": True}

def get_state(key: str) -> Dict[str, Any]:
    """Get global state value"""
    if key in _state:
        return {"key": key, "value": _state[key], "found": True}
    return {"key": key, "found": False}
```

## Security Considerations

### Allowed Modules

By default, only safe standard library modules are allowed:
- `math`, `statistics`, `json`, `re`, `datetime`
- `collections`, `itertools`, `functools`, `operator`
- `urllib.parse`, `hashlib`, `base64`, `uuid`

To add custom modules:

```python
provider = CustomFunctionProvider(
    provider_id="custom-provider",
    allowed_modules=["math", "numpy", "pandas", "custom_module"]
)
```

### Restricted Operations

The following are disabled by default:
- `eval()` without explicit permission
- `exec()` completely disabled
- File system access (unless explicitly coded)
- Network access (unless in async functions)
- System commands

### Safe Evaluation

For dynamic expressions, use restricted evaluation:

```yaml
tasks:
  - id: "safe-eval"
    protocol: "python/v1"
    method: "eval"
    params:
      expression: "len(data) * 2 + sum(values)"
      context:
        data: [1, 2, 3]
        values: [10, 20, 30]
      allow_eval: true  # Must explicitly allow
```

## Testing Python Functions

### Unit Testing Functions

```python
# test_my_functions.py
import pytest
from my_functions import process_data

def test_process_data():
    result = process_data([1, 2, 3], "sum")
    assert result["result"] == 6
    
    result = process_data([1, 2, 3], "average")
    assert result["result"] == 2.0
```

### Integration Testing

```python
# test_integration.py
async def test_python_workflow():
    # Start server and provider
    server = CentralServer(port=8000)
    provider = SocketIOPythonFunctionProvider(
        functions_dir=Path("./my_functions")
    )
    
    # Submit workflow
    workflow = load_yaml("workflow.yaml")
    results = await execute_workflow(workflow)
    
    # Verify results
    assert results["task-1"]["success"] == True
```

## Troubleshooting

### Common Issues

1. **Function not found**
   - Check function is registered: `provider.functions.keys()`
   - Verify module/file is in correct location
   - Check import statements

2. **Import errors**
   - Ensure module is in allowed list
   - Check Python path includes function directory
   - Verify dependencies installed

3. **Parameter errors**
   - Match function signature exactly
   - Use `args` for positional, `kwargs` for named parameters
   - Check parameter types match function expectations

4. **Async function issues**
   - Ensure async functions use `async def`
   - Provider automatically handles async execution
   - Don't mix sync/async incorrectly

## Performance Tips

1. **Cache expensive operations**
```python
from functools import lru_cache

@lru_cache(maxsize=128)
def expensive_calculation(n: int) -> int:
    """Cache results of expensive calculations"""
    return factorial(n)
```

2. **Use async for I/O**
```python
async def parallel_fetch(urls: List[str]) -> List[Dict]:
    """Fetch multiple URLs in parallel"""
    import aiohttp
    import asyncio
    
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_url(session, url) for url in urls]
        return await asyncio.gather(*tasks)
```

3. **Batch operations**
```python
def batch_transform(items: List[Any], batch_size: int = 100) -> List[Any]:
    """Process items in batches for efficiency"""
    results = []
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        results.extend(process_batch(batch))
    return results
```

## Examples Repository

Find more examples in `/examples/python_functions/`:
- `data_processing.py` - Data manipulation functions
- `ml_functions.py` - Machine learning utilities
- `web_scraping.py` - Web scraping functions
- `file_operations.py` - File handling functions
- `api_integration.py` - API client functions

---

Python function integration provides unlimited extensibility to Gleitzeit V4 workflows, allowing you to leverage Python's entire ecosystem while maintaining the workflow orchestration benefits of the platform.