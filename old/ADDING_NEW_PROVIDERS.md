# Adding New Functions and Providers

This guide shows you exactly how to add new functions with new providers to Gleitzeit V3.

## Example: Web Search Provider

We'll walk through adding a **Web Search Provider** that supports multiple web-related functions.

## Step 1: Create the Provider Class

Create `/gleitzeit_v3/providers/your_provider.py`:

```python
from .base import BaseProvider
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

class YourProvider(BaseProvider):
    def __init__(self, provider_id: str, server_url: str):
        super().__init__(
            provider_id=provider_id,
            provider_name="Your Provider Name",
            provider_type="your_type",
            supported_functions=[
                "function1",
                "function2", 
                "function3"
            ],
            max_concurrent_tasks=5,
            server_url=server_url
        )
        
        # Your provider-specific initialization
        self.your_config = {}
        logger.info("YourProvider initialized")
    
    async def start(self):
        # Initialize resources (HTTP sessions, connections, etc.)
        await super().start()
        logger.info("🚀 Your Provider started")
    
    async def stop(self):
        # Cleanup resources
        await super().stop()
        logger.info("🛑 Your Provider stopped")
    
    async def health_check(self) -> Dict[str, Any]:
        """Required: Implement health check"""
        try:
            # Test your provider's health
            return {"status": "healthy"}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
    
    async def execute_task(self, task_type: str, parameters: Dict[str, Any]) -> Any:
        """Main task execution method"""
        function = parameters.get("function")
        
        # Route to specific function handlers
        if function == "function1":
            return await self._handle_function1(parameters)
        elif function == "function2":
            return await self._handle_function2(parameters)
        elif function == "function3":
            return await self._handle_function3(parameters)
        else:
            raise ValueError(f"Unsupported function: {function}")
    
    async def _handle_function1(self, parameters: Dict[str, Any]) -> Any:
        """Handle function1 execution"""
        # Extract parameters
        param1 = parameters.get("param1")
        param2 = parameters.get("param2", "default_value")
        
        # Your business logic here
        result = f"Processed {param1} with {param2}"
        
        return {
            "result": result,
            "function": "function1",
            "parameters_used": parameters
        }
    
    async def _handle_function2(self, parameters: Dict[str, Any]) -> Any:
        """Handle function2 execution"""
        # Different function, different logic
        return {"function2": "completed"}
    
    async def _handle_function3(self, parameters: Dict[str, Any]) -> Any:
        """Handle function3 execution"""
        # Another function
        return {"function3": "done"}
```

## Step 2: Integrate into CLI

Edit `/gleitzeit_v3/cli.py`:

### Add Import
```python
from .providers.your_provider import YourProvider
```

### Add to Constructor
```python
def __init__(
    self,
    # ... existing parameters
    enable_your_provider: bool = True,
    # ... rest
):
    # ... existing code
    self.enable_your_provider = enable_your_provider
```

### Add to Startup Sequence
```python
async def start(self):
    # ... existing provider starts
    
    if self.enable_your_provider:
        print("🔧 Starting Your Provider...")
        try:
            your_provider = YourProvider(
                provider_id="main_your_provider",
                server_url=f"http://{self.host}:{self.port}"
            )
            await your_provider.start()
            self.providers.append(your_provider)
            provider_count += 1
            print(f"   ✅ Your Provider ready")
        except Exception as e:
            print(f"   ⚠️ Your Provider failed: {e}")
```

### Add Function Detection
```python
def _infer_function(description: str) -> str:
    """Infer function type from task description"""
    desc_lower = description.lower()
    
    # Add your function detection
    if any(word in desc_lower for word in ['your', 'keyword', 'trigger']):
        return 'function1'
    elif any(word in desc_lower for word in ['another', 'trigger']):
        return 'function2'
    # ... existing detection logic
```

### Add CLI Arguments
```python
def add_run_parser(subparsers):
    run_parser = subparsers.add_parser('run', help='Start queue processor')
    # ... existing args
    run_parser.add_argument('--no-your-provider', action='store_true', help='Disable Your Provider')

def add_add_parser(subparsers):
    add_parser = subparsers.add_parser('add', help='Add a task to the queue')
    # ... existing args
    add_parser.add_argument('--function', choices=[
        'generate', 'list_files', 'vision',
        'function1', 'function2', 'function3'  # Add your functions
    ], help='Specific function to use')
```

## Step 3: Test Your Provider

### Direct Test
```python
import asyncio
from gleitzeit_v3.cli import GleitzeitV3Service

async def test_your_provider():
    service = GleitzeitV3Service(
        enable_ollama=False,
        enable_mcp=False, 
        enable_your_provider=True
    )
    
    try:
        await service.start()
        result = await service.ask_task("trigger function1 with data")
        print("Result:", result)
    finally:
        await service.stop()

asyncio.run(test_your_provider())
```

### Queue Test
```bash
# Start system
gleitzeit run

# Add task (will auto-detect function or specify manually)
gleitzeit add "your trigger phrase here"

# Or specify function explicitly
gleitzeit add "some task" --function function1

# Check results
gleitzeit queue --completed
```

## Example: Actual Web Search Provider

Here's the real Web Search Provider we just implemented:

### Functions Supported:
- `web_search` - Search the web for information
- `url_fetch` - Fetch content from a URL  
- `web_summarize` - Summarize webpage content

### Usage Examples:
```bash
# Auto-detected as web search
gleitzeit add "Search for Python asyncio tutorial"

# Explicit function
gleitzeit add "Get Python docs" --function web_search

# URL fetching
gleitzeit add "https://example.com" --function url_fetch

# Web summarization  
gleitzeit add "https://example.com/article" --function web_summarize
```

### Provider Features:
- ✅ HTTP session management
- ✅ Graceful error handling with fallbacks
- ✅ Health checking via test requests
- ✅ Configurable timeouts and limits
- ✅ Clean content extraction
- ✅ Multiple function support

## Key Implementation Points

### 1. **Error Handling**
Always provide fallback results instead of failing:
```python
try:
    # Try main functionality
    return successful_result
except Exception as e:
    # Return fallback instead of raising
    return fallback_result_with_error_info
```

### 2. **Resource Management**
Use proper async context managers:
```python
async def start(self):
    self.session = aiohttp.ClientSession()
    await super().start()

async def stop(self):
    if self.session:
        await self.session.close()
    await super().stop()
```

### 3. **Health Checking**
Implement meaningful health checks:
```python
async def health_check(self) -> Dict[str, Any]:
    try:
        # Test actual functionality
        test_result = await self._test_core_feature()
        return {"status": "healthy", "details": test_result}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
```

### 4. **Function Routing**
Keep functions organized and extensible:
```python
async def execute_task(self, task_type: str, parameters: Dict[str, Any]) -> Any:
    function = parameters.get("function")
    
    # Clear routing logic
    handlers = {
        "function1": self._handle_function1,
        "function2": self._handle_function2,
        "function3": self._handle_function3,
    }
    
    handler = handlers.get(function)
    if handler:
        return await handler(parameters)
    else:
        raise ValueError(f"Unsupported function: {function}")
```

## Testing Your Provider

### 1. **Unit Testing**
```python
import pytest
from your_provider import YourProvider

@pytest.mark.asyncio
async def test_function1():
    provider = YourProvider("test_id", "http://localhost:8000")
    result = await provider._handle_function1({"param1": "test"})
    assert result["result"] == "expected_value"
```

### 2. **Integration Testing**  
```python
@pytest.mark.asyncio
async def test_full_integration():
    service = GleitzeitV3Service(enable_your_provider=True)
    await service.start()
    result = await service.ask_task("trigger your function")
    await service.stop()
    assert "expected" in result
```

### 3. **Manual Testing**
```bash
# Test startup
gleitzeit run --no-ollama --no-mcp

# Test function detection
gleitzeit add "phrase that should trigger your function"

# Test explicit function
gleitzeit add "any description" --function your_function

# Check results
gleitzeit queue --completed
```

This pattern allows you to easily add any type of provider with multiple functions to the Gleitzeit V3 system!