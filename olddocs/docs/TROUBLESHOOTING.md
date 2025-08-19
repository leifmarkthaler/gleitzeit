# Troubleshooting Guide

## Overview

This guide helps diagnose and resolve common issues with Gleitzeit v0.0.5. Each section includes symptoms, causes, and solutions.

## Quick Diagnostics

### System Health Check

```bash
# Run comprehensive health check
gleitzeit system health --verbose

# Check specific components
gleitzeit system health --check persistence
gleitzeit system health --check resources
gleitzeit system health --check providers
```

### Debug Mode

```bash
# Enable debug logging
export GLEITZEIT_LOG_LEVEL=DEBUG
gleitzeit --debug workflow submit workflow.yaml

# Or use command line
gleitzeit --log-level DEBUG workflow submit workflow.yaml
```

## Common Issues

### 1. Workflow Not Starting

#### Symptoms
- Workflow submitted but stays in "pending" status
- No tasks executing
- No error messages

#### Diagnosis
```bash
# Check workflow status
gleitzeit workflow status <workflow-id>

# Check execution engine
gleitzeit system status --component engine

# Check logs
gleitzeit logs --component engine --tail 50
```

#### Solutions

**Issue: No providers available**
```bash
# Check registered providers
gleitzeit provider list

# Solution: Initialize providers
gleitzeit provider init
```

**Issue: Resource unavailable**
```bash
# Check resource availability
gleitzeit resource list --status healthy

# Solution: Start required resources
gleitzeit resource start ollama
gleitzeit resource start docker
```

**Issue: Persistence not initialized**
```bash
# Check persistence
gleitzeit system health --check persistence

# Solution: Initialize persistence
gleitzeit system init --persistence
```

### 2. Ollama Connection Issues

#### Symptoms
- "Connection refused" errors
- "No Ollama instances available"
- LLM tasks failing

#### Diagnosis
```bash
# Check Ollama service
curl http://localhost:11434/api/tags

# Check Ollama hub status
gleitzeit resource status ollama

# Test Ollama directly
ollama list
```

#### Solutions

**Issue: Ollama not running**
```bash
# Start Ollama
ollama serve

# Or with systemd
sudo systemctl start ollama

# Or with Docker
docker run -d -p 11434:11434 ollama/ollama
```

**Issue: Wrong host/port**
```bash
# Update configuration
export GLEITZEIT_OLLAMA_HOST=localhost
export GLEITZEIT_OLLAMA_PORT=11434

# Or in config file
gleitzeit config set resources.ollama.default_host localhost
gleitzeit config set resources.ollama.default_port 11434
```

**Issue: Model not available**
```bash
# Pull required model
ollama pull llama3.2

# List available models
ollama list
```

### 3. Docker Execution Failures

#### Symptoms
- Python tasks failing with "Container error"
- "Docker daemon not responding"
- Permission denied errors

#### Diagnosis
```bash
# Check Docker daemon
docker ps

# Check Docker socket
ls -la /var/run/docker.sock

# Test container creation
docker run --rm python:3.11-slim python -c "print('test')"
```

#### Solutions

**Issue: Docker not running**
```bash
# Start Docker
sudo systemctl start docker

# On macOS
open -a Docker
```

**Issue: Permission denied**
```bash
# Add user to docker group
sudo usermod -aG docker $USER

# Then logout and login again
# Or use newgrp
newgrp docker
```

**Issue: Docker socket path**
```bash
# Update Docker socket path
export GLEITZEIT_DOCKER_SOCKET=unix:///var/run/docker.sock

# For Docker Desktop on macOS
export GLEITZEIT_DOCKER_SOCKET=unix://${HOME}/.docker/run/docker.sock
```

### 4. Persistence Issues

#### Symptoms
- Workflows not being saved
- Results disappearing
- "Persistence unavailable" errors

#### Diagnosis
```bash
# Check persistence status
gleitzeit system health --check persistence

# Test Redis connection (if using Redis)
redis-cli ping

# Check SQLite file (if using SQLite)
ls -la gleitzeit.db
sqlite3 gleitzeit.db "SELECT COUNT(*) FROM workflows;"
```

#### Solutions

**Issue: Redis not available**
```bash
# Start Redis
redis-server

# Or with Docker
docker run -d -p 6379:6379 redis:alpine

# Update configuration
export GLEITZEIT_REDIS_URL=redis://localhost:6379
```

**Issue: SQLite file permissions**
```bash
# Fix permissions
chmod 644 gleitzeit.db
chmod 755 $(dirname gleitzeit.db)
```

**Issue: Persistence fallback not working**
```bash
# Force specific persistence type
export GLEITZEIT_PERSISTENCE_TYPE=sqlite
# or
export GLEITZEIT_PERSISTENCE_TYPE=memory
```

### 5. Task Timeout Issues

#### Symptoms
- Tasks failing with "timeout" status
- Long-running tasks being cancelled
- Workflow stuck on specific task

#### Diagnosis
```bash
# Check task details
gleitzeit task status <task-id>

# Check timeout configuration
gleitzeit config show | grep timeout
```

#### Solutions

**Issue: Timeout too short**
```bash
# Increase global timeout
export GLEITZEIT_TASK_TIMEOUT=600  # 10 minutes

# Or per-workflow in YAML
tasks:
  - id: long_task
    timeout: 1800  # 30 minutes
```

**Issue: Infinite loops in Python code**
```python
# Add timeout to Python tasks
tasks:
  - id: python_task
    protocol: python/v1
    timeout: 60
    parameters:
      code: |
        import time
        # Add safety checks
        for i in range(100):  # Limit iterations
            if i > 50:
                break
            process_item(i)
```

### 6. Memory Issues

#### Symptoms
- "Out of memory" errors
- System becoming unresponsive
- Container killed (exit code 137)

#### Diagnosis
```bash
# Check system memory
free -h

# Check Docker memory limits
docker stats

# Check process memory
ps aux | grep gleitzeit
```

#### Solutions

**Issue: Container memory limits**
```bash
# Increase Docker memory limit
export GLEITZEIT_DOCKER_MEMORY_LIMIT=1g
export GLEITZEIT_DOCKER_CPU_LIMIT=2.0
```

**Issue: Too many parallel tasks**
```bash
# Reduce parallelism
export GLEITZEIT_MAX_PARALLEL_TASKS=5
```

**Issue: Memory leaks**
```python
# Use memory-efficient patterns
# Bad: Loading everything into memory
data = load_all_data()  # Loads entire dataset

# Good: Stream processing
for chunk in load_data_chunks():
    process_chunk(chunk)
    del chunk  # Explicit cleanup
```

### 7. Network Issues

#### Symptoms
- "Connection timeout" errors
- "Host unreachable" errors
- Slow API responses

#### Diagnosis
```bash
# Test network connectivity
ping localhost
curl -I http://localhost:8000

# Check firewall
sudo iptables -L
sudo ufw status

# Check ports
netstat -tuln | grep -E "8000|11434|6379"
```

#### Solutions

**Issue: Firewall blocking ports**
```bash
# Allow required ports
sudo ufw allow 8000/tcp  # API
sudo ufw allow 11434/tcp  # Ollama
sudo ufw allow 6379/tcp  # Redis
```

**Issue: Port conflicts**
```bash
# Check what's using the port
lsof -i :8000

# Use different port
export GLEITZEIT_API_PORT=8080
```

### 8. Parameter Substitution Issues

#### Symptoms
- "${variable}" appearing in output
- "Cannot resolve reference" errors
- Wrong values being substituted

#### Diagnosis
```bash
# Check workflow with debug
gleitzeit --debug workflow submit workflow.yaml

# Validate workflow
gleitzeit workflow validate workflow.yaml
```

#### Solutions

**Issue: Typo in reference**
```yaml
# Wrong
parameters:
  model: "${task1.response}"  # task1 doesn't exist

# Correct
parameters:
  model: "${task1.result.response}"  # Correct path
```

**Issue: Task not completed**
```yaml
# Ensure proper dependencies
tasks:
  - id: task2
    dependencies: ["task1"]  # Wait for task1
    parameters:
      input: "${task1.result}"
```

### 9. Provider Registration Issues

#### Symptoms
- "Provider not found" errors
- "No provider for protocol" errors
- Methods not recognized

#### Diagnosis
```bash
# List registered providers
gleitzeit provider list

# Check provider details
gleitzeit provider info <provider-id>

# Check protocol registry
gleitzeit protocol list
```

#### Solutions

**Issue: Provider not initialized**
```python
# Ensure providers are registered
from gleitzeit.core.registry import ProtocolProviderRegistry
from gleitzeit.providers.ollama_provider import OllamaProvider

registry = ProtocolProviderRegistry()
provider = OllamaProvider()
await provider.initialize()
await registry.register_provider("llm/v1", provider)
```

**Issue: Wrong protocol ID**
```yaml
# Check protocol ID
tasks:
  - protocol: "llm/v1"  # Correct
    # protocol: "llm"  # Wrong - missing version
```

### 10. Workflow Dependencies Issues

#### Symptoms
- Tasks executing out of order
- Dependency cycles detected
- Tasks stuck waiting

#### Diagnosis
```bash
# Visualize workflow dependencies
gleitzeit workflow visualize workflow.yaml

# Check dependency resolution
gleitzeit workflow validate --check-dependencies workflow.yaml
```

#### Solutions

**Issue: Circular dependencies**
```yaml
# Wrong - circular dependency
tasks:
  - id: task1
    dependencies: ["task2"]
  - id: task2
    dependencies: ["task1"]

# Correct - no cycles
tasks:
  - id: task1
  - id: task2
    dependencies: ["task1"]
```

**Issue: Missing dependencies**
```yaml
# Ensure all referenced tasks exist
tasks:
  - id: task1
  - id: task2
    dependencies: ["task1"]  # task1 must exist
```

## Performance Issues

### Slow Workflow Execution

#### Diagnosis
```bash
# Profile workflow execution
gleitzeit workflow profile <workflow-id>

# Check resource utilization
gleitzeit resource metrics
```

#### Solutions

1. **Increase parallelism**
```bash
export GLEITZEIT_MAX_PARALLEL_TASKS=20
```

2. **Use container pooling**
```bash
export GLEITZEIT_DOCKER_ENABLE_REUSE=true
```

3. **Enable caching**
```yaml
providers:
  ollama:
    cache_enabled: true
    cache_ttl: 3600
```

### High Memory Usage

#### Solutions

1. **Limit container memory**
```bash
export GLEITZEIT_DOCKER_MEMORY_LIMIT=512m
```

2. **Clean up old workflows**
```bash
gleitzeit system cleanup --older-than 7d
```

3. **Use streaming for large data**
```python
# Stream large files
async for chunk in read_file_chunks(file_path):
    process_chunk(chunk)
```

## Debugging Techniques

### 1. Enable Verbose Logging

```bash
# Maximum verbosity
export GLEITZEIT_LOG_LEVEL=DEBUG
export GLEITZEIT_LOG_FORMAT="%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"
```

### 2. Use Test Mode

```bash
# Test without execution
gleitzeit workflow submit --dry-run workflow.yaml

# Test specific components
gleitzeit test persistence
gleitzeit test providers
gleitzeit test resources
```

### 3. Interactive Debugging

```python
# Add breakpoints in Python tasks
import pdb

tasks:
  - protocol: python/v1
    parameters:
      code: |
        import pdb
        pdb.set_trace()  # Debugger breakpoint
        result = process_data(input)
```

### 4. Trace Execution

```bash
# Enable execution tracing
export GLEITZEIT_TRACE_ENABLED=true
export GLEITZEIT_TRACE_FILE=./trace.log

# Analyze trace
gleitzeit trace analyze ./trace.log
```

## Error Messages Reference

### Common Error Messages

| Error | Cause | Solution |
|-------|-------|----------|
| "No provider found for protocol" | Provider not registered | Register provider or check protocol ID |
| "Task timeout" | Task exceeded timeout | Increase timeout or optimize task |
| "Resource unavailable" | No healthy instances | Start resources or check health |
| "Persistence error" | Storage backend issue | Check Redis/SQLite connection |
| "Invalid workflow" | YAML syntax or schema error | Validate workflow file |
| "Dependency cycle detected" | Circular task dependencies | Fix task dependencies |
| "Parameter resolution failed" | Invalid substitution reference | Check parameter syntax |
| "Container creation failed" | Docker issues | Check Docker daemon |
| "Model not found" | Ollama model missing | Pull required model |
| "Authentication failed" | Invalid API key | Check API key configuration |

## Getting Help

### 1. Diagnostic Information

When reporting issues, include:

```bash
# Generate diagnostic report
gleitzeit system diagnostic > diagnostic.txt

# Include:
# - Gleitzeit version
# - Configuration
# - Error messages
# - Workflow YAML
# - Log excerpts
```

### 2. Community Support

- GitHub Issues: [Report bugs](https://github.com/yourusername/gleitzeit/issues)
- Discussions: [Ask questions](https://github.com/yourusername/gleitzeit/discussions)
- Documentation: Check `/newdocs` folder

### 3. Debug Checklist

Before reporting an issue:

- [ ] Check logs with DEBUG level
- [ ] Run system health check
- [ ] Validate workflow syntax
- [ ] Test with minimal workflow
- [ ] Check resource availability
- [ ] Verify configuration
- [ ] Try with different persistence
- [ ] Update to latest version

## Prevention Best Practices

### 1. Regular Health Checks
```bash
# Add to crontab
*/5 * * * * gleitzeit system health --alert-on-failure
```

### 2. Resource Monitoring
```bash
# Monitor resources
gleitzeit resource monitor --interval 60
```

### 3. Backup Configuration
```bash
# Backup important data
gleitzeit backup create --include workflows,results
```

### 4. Test Before Production
```bash
# Test workflow before production
gleitzeit workflow test workflow.yaml
gleitzeit workflow validate workflow.yaml
```

## Summary

Most Gleitzeit issues fall into these categories:
- **Connection issues**: Check services (Ollama, Docker, Redis)
- **Configuration issues**: Verify settings and paths
- **Resource issues**: Ensure resources are available and healthy
- **Workflow issues**: Validate syntax and dependencies
- **Permission issues**: Check file and socket permissions

Use debug mode and health checks to quickly identify and resolve problems.