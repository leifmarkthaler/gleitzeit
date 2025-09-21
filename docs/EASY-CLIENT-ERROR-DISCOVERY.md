# Easy Client Error Discovery Documentation

## Overview

The Gleitzeit Easy Client integrates with the system's error discovery mechanism to help developers understand what errors providers can raise and how to handle them appropriately.

## Error Discovery System

The error discovery system allows runtime inspection of:
- What errors each provider can raise
- Which errors are retryable
- Error codes and their meanings
- Error hierarchies and relationships

## Using Error Discovery

### Basic Discovery

Discover errors for a specific provider:

```python
import asyncio
from gleitzeit.client import GleitzeitClient

async def discover_provider_errors():
    client = GleitzeitClient(base_url="http://localhost:8000")
    await client.initialize()

    # Discover errors for Python provider
    errors = await client.get_provider_errors("python/v1")

    for error in errors:
        print(f"Error: {error['name']}")
        print(f"  Class: {error['class']}")
        print(f"  Base: {error['base_class']}")
        print(f"  Module: {error['module']}")
        print(f"  Code: {error.get('error_code_name', 'N/A')}")
        print(f"  Retryable: {error.get('is_retryable', False)}")
        print(f"  Description: {error.get('description', 'No description')}")
        print()

asyncio.run(discover_provider_errors())
```

### Discover All Provider Errors

Get errors from all registered providers:

```python
async def discover_all_errors():
    client = GleitzeitClient(base_url="http://localhost:8000")
    await client.initialize()

    # Get all provider errors
    all_errors = await client.get_all_provider_errors()

    for provider_id, errors in all_errors.items():
        print(f"\n=== Provider: {provider_id} ===")
        print(f"Total errors: {len(errors)}")

        # Separate retryable from non-retryable
        retryable = [e for e in errors if e.get('is_retryable', False)]
        non_retryable = [e for e in errors if not e.get('is_retryable', False)]

        print(f"  Retryable: {len(retryable)}")
        print(f"  Non-retryable: {len(non_retryable)}")

        # Show some examples
        if retryable:
            print("\n  Example retryable errors:")
            for error in retryable[:3]:
                print(f"    - {error['name']}: {error.get('description', '')[:50]}")

asyncio.run(discover_all_errors())
```

### Protocol-Level Error Discovery

Discover errors for a specific protocol:

```python
async def discover_protocol_errors():
    client = GleitzeitClient(base_url="http://localhost:8000")
    await client.initialize()

    # Get errors for a protocol
    errors = await client.get_protocol_errors("python/v1")

    print("Protocol-level errors:")
    for error in errors:
        print(f"  - {error['name']} ({error['error_code_name']})")

asyncio.run(discover_protocol_errors())
```

### Error Hierarchy Discovery

Get the complete error hierarchy:

```python
async def discover_error_hierarchy():
    client = GleitzeitClient(base_url="http://localhost:8000")
    await client.initialize()

    # Get error hierarchy
    hierarchy = await client.get_error_hierarchy()

    def print_hierarchy(errors, indent=0):
        for error_class, children in errors.items():
            print("  " * indent + f"- {error_class}")
            if children:
                print_hierarchy(children, indent + 1)

    print("Error Hierarchy:")
    print_hierarchy(hierarchy)

asyncio.run(discover_error_hierarchy())
```

## Error Information Structure

Each discovered error contains:

```python
{
    "name": "ProviderTimeoutError",           # Error class name
    "class": "ProviderTimeoutError",          # Class type name
    "base_class": "ProviderError",            # Parent class
    "module": "gleitzeit.core.errors",        # Module containing the error
    "error_code": 40002,                      # Numeric error code
    "error_code_name": "PROVIDER_TIMEOUT",    # Error code enum name
    "description": "Provider operation timed out",  # Human-readable description
    "is_retryable": true                      # Whether automatic retry is possible
}
```

## Using Discovery with Easy Client

### Adaptive Error Handling

Use discovery to configure error handling based on provider capabilities:

```python
from gleitzeit.easy import t, w
from gleitzeit.client import GleitzeitClient

async def create_workflow_with_discovered_errors():
    client = GleitzeitClient(base_url="http://localhost:8000")
    await client.initialize()

    # Discover what errors the Python provider can raise
    errors = await client.get_provider_errors("python/v1")

    # Check if provider supports retryable errors
    has_retryable = any(e.get('is_retryable', False) for e in errors)

    # Create task with appropriate error handling
    task = t("data_processing", "python/v1:python/execute").with_(file="process.py")

    if has_retryable:
        # Provider has retryable errors, configure retry
        task = task.with_retry(max_attempts=3, delay=2.0)

    # Check for timeout support
    has_timeout_errors = any('TIMEOUT' in e.get('error_code_name', '') for e in errors)
    if has_timeout_errors:
        task = task.with_timeout(60)

    # Create workflow
    workflow = w(task).name("adaptive_error_handling")

    # Submit workflow
    workflow_dict = workflow.to_dict()
    result = await client.submit_workflow(workflow_dict)
    print(f"Submitted: {result['workflow_id']}")

asyncio.run(create_workflow_with_discovered_errors())
```

### Error Report Generation

Generate comprehensive error reports:

```python
async def generate_error_report():
    client = GleitzeitClient(base_url="http://localhost:8000")
    await client.initialize()

    # Generate report for specific provider
    report = await client.get_error_report("python/v1")
    print(report)

    # Generate system-wide report
    full_report = await client.get_error_report()

    # Save to file
    with open("error_report.md", "w") as f:
        f.write(full_report)

asyncio.run(generate_error_report())
```

## Practical Examples

### Example 1: Check Retryability Before Submission

```python
async def smart_task_configuration():
    client = GleitzeitClient(base_url="http://localhost:8000")
    await client.initialize()

    # Check if specific error codes are retryable
    is_timeout_retryable = await client.check_error_retryability(40002)  # PROVIDER_TIMEOUT

    task = t("api_call", "python/v1:python/execute").with_(file="call_api.py")

    if is_timeout_retryable:
        task = task.with_retry(max_attempts=3, delay=2.0)

    return task
```

### Example 2: Provider Capability Detection

```python
async def detect_provider_capabilities():
    client = GleitzeitClient(base_url="http://localhost:8000")
    await client.initialize()

    providers = ["python/v1", "llm/v1", "timer/v1"]
    capabilities = {}

    for provider_id in providers:
        try:
            errors = await client.get_provider_errors(provider_id)

            capabilities[provider_id] = {
                "supports_retry": any(e.get('is_retryable', False) for e in errors),
                "supports_timeout": any('TIMEOUT' in e.get('error_code_name', '') for e in errors),
                "total_errors": len(errors),
                "retryable_count": sum(1 for e in errors if e.get('is_retryable', False))
            }
        except Exception as e:
            capabilities[provider_id] = {"error": str(e)}

    # Use capabilities to configure tasks
    for provider_id, caps in capabilities.items():
        print(f"\n{provider_id}:")
        print(f"  Supports retry: {caps.get('supports_retry', False)}")
        print(f"  Supports timeout: {caps.get('supports_timeout', False)}")
        print(f"  Total errors: {caps.get('total_errors', 0)}")
        print(f"  Retryable errors: {caps.get('retryable_count', 0)}")

asyncio.run(detect_provider_capabilities())
```

### Example 3: Dynamic Workflow Configuration

```python
from gleitzeit.easy import t, w

async def create_resilient_workflow():
    client = GleitzeitClient(base_url="http://localhost:8000")
    await client.initialize()

    tasks = []

    # Define task configurations
    task_configs = [
        ("fetch_data", "python/v1:python/execute", "fetch.py"),
        ("process_llm", "llm/v1:llm/generate", None),
        ("save_results", "python/v1:python/execute", "save.py")
    ]

    for task_id, protocol_method, file_path in task_configs:
        protocol = protocol_method.split(":")[0]

        # Discover errors for this protocol
        errors = await client.get_provider_errors(protocol)

        # Create base task
        task = t(task_id, protocol_method)
        if file_path:
            task = task.with_(file=file_path)

        # Configure based on discovered capabilities
        retryable_errors = [e for e in errors if e.get('is_retryable', False)]
        if retryable_errors:
            # More retries for tasks with many retryable error types
            max_attempts = min(5, 2 + len(retryable_errors))
            task = task.with_retry(max_attempts=max_attempts, delay=2.0)

        # Add timeout if provider supports it
        timeout_errors = [e for e in errors if 'TIMEOUT' in e.get('error_code_name', '')]
        if timeout_errors:
            task = task.with_timeout(60)

        tasks.append(task)

    # Create workflow with discovered configuration
    workflow = (
        w(*tasks)
        .name("resilient_pipeline")
        .description("Workflow with dynamically discovered error handling")
    )

    return workflow

# Use the resilient workflow
async def main():
    workflow = await create_resilient_workflow()

    client = GleitzeitClient(base_url="http://localhost:8000")
    await client.initialize()

    result = await client.submit_workflow(workflow.to_dict())
    print(f"Submitted resilient workflow: {result['workflow_id']}")

asyncio.run(main())
```

## Integration with RealErrorHandler

The `RealErrorHandler` class uses error discovery internally:

```python
from gleitzeit.easy import t

async def use_real_error_handler():
    task = t("my_task", "python/v1:python/execute").with_(file="script.py")

    # Access the real error handler
    handler = task.real_errors()

    client = GleitzeitClient(base_url="http://localhost:8000")
    await client.initialize()

    # Discover errors for this task's protocol
    errors = await handler.discover_errors(client)

    # Print discovered errors
    handler.print_discovered_errors(errors)

    # Get retryable error codes
    retryable_codes = handler.get_retryable_error_codes()
    print(f"Retryable error codes: {retryable_codes}")

    # Configure based on discovery
    if errors:
        task = handler.handle_retryable_errors()
        task = handler.with_timeout(30)

    return task
```

## Best Practices

1. **Cache Discovery Results**: Error definitions rarely change, cache results to avoid repeated API calls
2. **Fail Gracefully**: If discovery fails, use sensible defaults for error handling
3. **Log Discovery**: Log what errors were discovered for debugging
4. **Version Awareness**: Different provider versions may support different errors
5. **Test Discovery**: Test error discovery in development before production

## Summary

Error discovery enables:
- **Dynamic Configuration**: Adapt error handling to provider capabilities
- **Better Debugging**: Understand what errors can occur
- **Intelligent Retries**: Only retry on actually retryable errors
- **Documentation**: Generate error documentation automatically
- **Validation**: Verify error handling configuration matches provider capabilities

The easy client's integration with error discovery ensures that workflows use appropriate error handling based on what's actually implemented in the system.