# DockerHub Guide

The DockerHub manages Docker containers for isolated Python code execution, providing basic security and resource isolation.

## Overview

DockerHub provides:
- **Container management** for Python code execution
- **Basic resource isolation** and security
- **Simple container lifecycle management**

## Current Implementation

### Basic Docker Execution

The `DockerHub` class manages Docker containers:

```python
from gleitzeit.hub.docker_hub import DockerHub

# Initialize Docker hub
docker_hub = DockerHub(config={
    "max_containers": 10,
    "timeout": 300,
    "image": "python:3.11-slim"
})

# Execute Python code in container
result = await docker_hub.execute_code(
    code="""
import math
result = math.sqrt(16)
print(result)
    """,
    timeout=30
)
```

### Configuration

```yaml
# ~/.gleitzeit/config.yaml
hubs:
  docker:
    type: "DockerHub"
    max_containers: 10
    timeout: 300
    image: "python:3.11-slim"
    
    # Basic security settings
    network_mode: "none"  # No network access
    memory_limit: "512MB"
    cpu_shares: 1024
```

## Python Execution

### Through Python Provider

Most Python execution happens through the `PythonProvider`:

```python
from gleitzeit.providers.python_provider import PythonProvider

provider = PythonProvider(config={
    "execution_mode": "docker",
    "docker_image": "python:3.11-slim",
    "timeout": 300
})

# Execute code
result = await provider.execute("python/execute", {
    "code": "result = 2 + 2"
})
```

### In Workflows

```yaml
tasks:
  - id: "python_task"
    method: "python/execute"
    parameters:
      code: |
        import json
        data = {"result": "processed"}
        print(json.dumps(data))
      environment: "docker"
      timeout: 30
```

## Security Features

### Basic Isolation

Current implementation provides:

1. **Network isolation**: Containers run with `network_mode: none`
2. **Resource limits**: Memory and CPU constraints
3. **Timeout enforcement**: Maximum execution time
4. **User restrictions**: Runs as non-root user

### Limitations

Current implementation does NOT include:
- Container pooling or warming
- Custom image building
- Package installation management
- Volume mounting
- Advanced security policies

## Container Lifecycle

### Simple Execution Flow

1. **Create container** with Python image
2. **Execute code** with timeout
3. **Capture output** (stdout/stderr)
4. **Clean up container** after execution

```python
# Simplified execution
async def execute_in_docker(code: str, timeout: int = 30):
    container = docker_client.containers.create(
        image="python:3.11-slim",
        command=["python", "-c", code],
        network_mode="none",
        mem_limit="512m",
        user="nobody"
    )
    
    try:
        container.start()
        result = container.wait(timeout=timeout)
        logs = container.logs()
        return logs.decode()
    finally:
        container.remove(force=True)
```

## Error Handling

### Common Errors

- **Container creation failure**: Docker daemon issues
- **Timeout exceeded**: Code runs too long
- **Memory limit exceeded**: Code uses too much memory
- **Syntax errors**: Invalid Python code

### Error Messages

```python
# Execution errors are returned as task failures
{
    "status": "failed",
    "error": "Container execution timeout (30s exceeded)",
    "details": {
        "container_id": "abc123",
        "exit_code": -1
    }
}
```

## Usage Examples

### Basic Math Computation

```yaml
- id: "calculate"
  method: "python/execute"
  parameters:
    code: |
      import math
      radius = 5
      area = math.pi * radius ** 2
      print(f"Area: {area}")
```

### Data Processing

```yaml
- id: "process_data"
  method: "python/execute" 
  parameters:
    code: |
      data = [1, 2, 3, 4, 5]
      average = sum(data) / len(data)
      result = {"average": average, "count": len(data)}
      print(result)
```

## Best Practices

### Code Execution

1. **Keep code simple**: Avoid complex dependencies
2. **Use standard library**: Minimize external packages
3. **Handle errors**: Include try/except blocks
4. **Set timeouts**: Prevent infinite loops

### Resource Management

1. **Monitor container count**: Avoid resource exhaustion
2. **Clean up containers**: Ensure proper cleanup
3. **Set appropriate limits**: Memory and CPU constraints

## Future Enhancements

Planned improvements (not yet implemented):
- Container pooling for faster execution
- Custom image support with pre-installed packages
- Persistent volumes for data sharing
- Advanced security policies
- Distributed container orchestration

## CLI Usage

```bash
# Execute Python code via workflow
gleitzeit run python_workflow.yaml

# The workflow uses Docker automatically when configured
```

## Limitations

Current Docker hub implementation is basic:
- No container reuse or pooling
- No custom package installation
- No persistent storage
- No GPU support
- No distributed execution
- Basic error handling only

For production use cases requiring advanced Docker features, consider using external container orchestration platforms like Kubernetes or Docker Swarm alongside Gleitzeit.