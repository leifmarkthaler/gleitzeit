# Provider Security Documentation

## Provider Security Model

Gleitzeit V4 uses a **purpose-specific provider model** where each provider is designed for specific use cases with appropriate security levels:

## Current Providers

### 1. Python Function Provider (python/v1)
**Purpose: Internal workflow computations and data transformations**

**Current Security Model:**
- ✅ Restricted `exec()` environment with limited builtins
- ✅ Whitelisted safe modules (math, json, datetime, etc.)
- ✅ No file system access
- ✅ No network operations
- ✅ No process spawning
- ✅ Output capture and size limits

**Intended Use Cases:**
- Data transformations within workflows
- Mathematical computations
- JSON/data structure manipulation
- String processing
- Simple algorithmic operations
- Workflow variable calculations

**NOT Intended For:**
- Running external user scripts
- Executing untrusted code
- System administration tasks
- File system operations
- Network requests
- Database operations

**Security Status: ADEQUATE for intended use**
The current restricted environment is appropriate for internal workflow computations. The limitations are intentional and serve as guardrails.

### 2. Ollama Provider (llm/v1)
**Purpose: LLM inference via Ollama API**

**Security Model:**
- ✅ API-based isolation
- ✅ No code execution
- ✅ Rate limiting capable
- ✅ HTTP session lifecycle management
- ✅ Centralized resource cleanup

**Resource Management:**
- HTTP sessions created during provider initialization
- Sessions automatically cleaned up when provider shuts down
- Cleanup triggered by centralized registry management
- Compatible with both pooling (`cleanup()`) and direct (`shutdown()`) patterns

**Security Status: PRODUCTION READY** ✅

### 3. MCP Provider (mcp/v1)
**Purpose: Model Context Protocol tool execution**

**Security Model:**
- ✅ Protocol-based communication
- ✅ JSON-RPC message validation
- ✅ Tool capability restrictions

**Security Status: PRODUCTION READY**

## Planned Providers

### Docker Execution Provider (docker/v1) - PLANNED
**Purpose: Secure execution of external/untrusted scripts**

**Planned Security Model:**
```yaml
provider:
  id: docker-executor
  type: docker/v1
  config:
    images:
      python: "python:3.11-slim"
      node: "node:18-slim"
      custom: "user/custom-image:latest"
    
    security:
      network_disabled: true      # No network access
      read_only_root: true        # Read-only filesystem
      no_new_privileges: true     # Prevent privilege escalation
      
    limits:
      memory: "512m"              # Memory limit
      cpu_quota: 50000           # CPU limit (50%)
      timeout: 60                # Max execution time
      
    volumes:
      # Mount points for data exchange
      input: "/data/input"
      output: "/data/output"
      
    capabilities:
      - execute_script
      - read_input_data
      - write_output_data
```

**Use Cases:**
- Running user-provided scripts
- Executing untrusted code
- Complex data processing pipelines
- Language-agnostic script execution
- Integration with external tools
- CI/CD workflow steps

**Security Features:**
- Complete OS-level isolation
- Resource limits enforced by kernel
- Network isolation
- Filesystem isolation
- No host system access
- Automatic cleanup

### Kubernetes Job Provider (k8s/v1) - FUTURE
**Purpose: Distributed execution in Kubernetes clusters**

**Planned Features:**
- Pod-based isolation
- Resource quotas
- Network policies
- Service account restrictions
- Namespace isolation

## Provider Selection Guidelines

### Use Python Provider When:
- ✅ Running trusted, internal workflow logic
- ✅ Performing data transformations
- ✅ Need fast, lightweight execution
- ✅ Working with workflow variables
- ✅ Doing mathematical computations

### Use Docker Provider (When Available) When:
- ✅ Running external user scripts
- ✅ Executing untrusted code
- ✅ Need complete isolation
- ✅ Running code in different languages
- ✅ Need specific runtime environments
- ✅ Performing system-level operations

### Use Ollama Provider When:
- ✅ Need LLM inference
- ✅ Text generation/completion
- ✅ Language understanding tasks

### Use MCP Provider When:
- ✅ Integrating with MCP-compatible tools
- ✅ Need structured tool execution
- ✅ Working with external services via MCP

## Migration Path

### Current State (v4.0)
```
User Scripts → ❌ Not Recommended
Workflow Logic → ✅ Python Provider
LLM Tasks → ✅ Ollama Provider
Tool Calls → ✅ MCP Provider
```

### Future State (v4.1)
```
User Scripts → ✅ Docker Provider
Workflow Logic → ✅ Python Provider  
LLM Tasks → ✅ Ollama Provider
Tool Calls → ✅ MCP Provider
```

## Security Best Practices

### 1. Provider Isolation
Each provider runs in its own context with specific security boundaries:
- Python Provider: Process-level isolation with restricted globals
- Docker Provider: Container-level isolation
- Ollama/MCP: Network API isolation

### 2. Least Privilege Principle
Each provider has only the permissions needed for its intended use:
- Python: Computation only, no I/O
- Docker: Configurable capabilities
- Ollama: API access only
- MCP: Protocol-defined operations

### 3. Resource Limits
All providers enforce resource limits:
- Execution timeouts
- Memory limits
- Output size limits
- Rate limiting

### 4. Audit Logging
All provider executions are logged with:
- Task ID and workflow context
- Execution duration
- Resource usage
- Success/failure status
- Error messages

## Implementation Timeline

### Phase 1: Current (v4.0) ✅
- Python Provider with restricted execution
- Ollama Provider for LLM
- MCP Provider for tools
- Basic security model

### Phase 2: Docker Provider (v4.1) 🚧
- Design Docker provider interface
- Implement container lifecycle management
- Add volume mounting for data exchange
- Create security policies
- Test with common languages (Python, Node, Go)

### Phase 3: Enhanced Security (v4.2) 📋
- Add code signing for trusted scripts
- Implement provider chaining
- Add security scanning
- Create provider marketplace

## Configuration Examples

### Current Python Provider (Internal Use)
```yaml
tasks:
  - name: "Process Data"
    protocol: "python/v1"
    method: "python/execute"
    params:
      code: |
        # Safe internal computation
        import json
        data = json.loads(input_data)
        result = sum(data['values']) / len(data['values'])
```

### Future Docker Provider (External Scripts)
```yaml
tasks:
  - name: "Run User Script"
    protocol: "docker/v1"
    method: "docker/execute"
    params:
      image: "python:3.11-slim"
      script_path: "/user/scripts/analysis.py"
      input_files:
        - "data.csv"
      output_files:
        - "results.json"
      timeout: 60
      memory_limit: "512m"
```

## Summary

The current Python provider is **working as designed** for internal workflow computations with appropriate security restrictions. For external script execution, the planned Docker provider will provide complete isolation and security.

**Key Points:**
1. Python provider is NOT intended for external scripts - this is by design
2. Docker provider is the correct solution for external script execution
3. Each provider has a specific security model for its use case
4. The system supports multiple providers for different security needs
5. Migration path is clear: keep Python for internal, add Docker for external

**Production Status:**
- ✅ Python Provider: Ready for internal workflow use
- ✅ Ollama Provider: Ready with full resource management
- ✅ MCP Provider: Ready
- 🚧 Docker Provider: Planned for v4.1

**Resource Management Features:**
- ✅ Centralized provider lifecycle management
- ✅ HTTP session cleanup on shutdown
- ✅ Event-driven cleanup architecture
- ✅ Comprehensive test coverage for cleanup scenarios
- ✅ Error-resilient cleanup (provider failures don't crash system)