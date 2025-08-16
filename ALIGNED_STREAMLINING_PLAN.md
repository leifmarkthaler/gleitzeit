# Aligned Streamlining Plan for Gleitzeit

## Executive Summary

After thorough analysis of Gleitzeit's architecture, this plan proposes streamlining improvements that enhance the system while preserving its core orchestration principles.

## System Understanding

### Core Architecture
1. **Orchestration Engine**: Central workflow and task execution coordinator
2. **Protocol System**: JSON-RPC 2.0 based protocol specifications
3. **Provider Registry**: Manages protocol provider instances
4. **Task Queue**: Handles scheduling, dependencies, and execution
5. **Persistence Layer**: SQLite/Redis/InMemory backends for workflow and result storage
6. **Client APIs**: CLI and Python client for user interaction

### Key Principles to Preserve
- Tasks flow through: Client → Workflow → Queue → Engine → Provider → Result
- All operations create traceable workflows and tasks
- Protocol specifications define provider contracts
- Persistence enables recovery and auditing
- Dependencies and parameter substitution are core features

### Existing Provider Ecosystem
1. **LLM Providers**:
   - `OllamaProvider` - Single Ollama instance
   - `OllamaPoolProvider` - Multiple instances with load balancing
   - Hub architecture started with `OllamaProviderStreamlined`

2. **Python Providers**:
   - `CustomFunctionProvider` - Local Python execution
   - `PythonProviderStreamlined` - Docker container management
   - Hub architecture for container pooling

3. **MCP Providers**:
   - `SimpleMCPProvider` - Built-in tools for testing
   - Dev commands support external MCP servers
   - Protocol allows for dynamic tool discovery

## Streamlining Opportunities

### 1. Provider Improvements ✅ HIGH PRIORITY
**What exists**: 
- `OllamaProvider` - Basic single-instance
- `OllamaPoolProvider` - Multi-instance with load balancing
- `CustomFunctionProvider` - Python execution
- Hub architecture partially implemented

**Streamlining approach**:
- Complete the hub-based providers (already started)
- Unify resource management across all providers
- Add auto-discovery to existing pool providers

**Benefits**:
- Better resource utilization
- Automatic failover and health monitoring
- Consistent provider interface

### 2. Client Experience Enhancement ✅ HIGH PRIORITY
**What exists**:
- `GleitzeitClient` with convenience methods (`chat()`, `vision()`, `execute_python()`)
- Methods already create proper workflows internally

**Streamlining approach**:
- Add auto-discovery option to client initialization
- Enhance error messages with actionable suggestions
- Add progress tracking for long-running workflows

**Implementation**:
```python
# Enhanced client initialization
client = GleitzeitClient(
    auto_discover_providers=True,  # New option
    show_progress=True,            # New option
    retry_failed_tasks=True        # New option
)
```

### 3. Configuration Simplification ✅ MEDIUM PRIORITY
**What exists**:
- Manual provider registration in client
- Environment variables for basic config

**Streamlining approach**:
- Add configuration file support (YAML/TOML)
- Auto-detect common setups (Ollama, Docker)
- Provider presets for common scenarios

**Example config**:
```yaml
# ~/.gleitzeit/config.yaml
providers:
  ollama:
    auto_discover: true
    ports: [11434, 11435, 11436]
    
  python:
    enable_docker: true
    enable_local: true
    max_containers: 5
    
persistence:
  backend: sqlite
  path: ~/.gleitzeit/data.db
  
defaults:
  retry_attempts: 3
  timeout: 60
```

### 4. Workflow Builder Enhancement ✅ MEDIUM PRIORITY
**What exists**:
- YAML workflow files
- Programmatic workflow creation in client

**Streamlining approach**:
- Add fluent API for workflow building
- Template library for common patterns
- Workflow validation and suggestions

**Example**:
```python
# Fluent workflow builder
workflow = (
    WorkflowBuilder("Data Pipeline")
    .add_llm("analyze", prompt="Analyze this data")
    .add_python("process", code="result = process_data()")
    .depends_on("process", ["analyze"])
    .with_retry(max_attempts=3)
    .build()
)
```

### 5. MCP Provider Integration ✅ MEDIUM PRIORITY
**What exists**:
- `SimpleMCPProvider` with built-in tools (echo, add, multiply, concat)
- MCP protocol specification registered
- Support for external MCP servers in dev commands

**Streamlining approach**:
- Auto-discover local MCP servers
- Support for external MCP server connections
- Dynamic tool discovery from MCP servers
- Hub-based MCP provider for multiple servers

**Implementation**:
```python
# Enhanced MCP provider with external server support
class MCPProvider(ProtocolProvider):
    """MCP provider that can connect to external servers"""
    
    async def discover_tools(self):
        """Discover available tools from MCP server"""
        # Connect to MCP server
        # Query available tools
        # Register tool methods dynamically
        
# MCP Hub for multiple servers
class MCPHub(HubProvider):
    """Manage multiple MCP servers"""
    
    async def auto_discover(self):
        """Discover local MCP servers"""
        # Check common ports
        # Query for MCP servers
        # Register discovered servers
```

### 6. Backend Manager Integration ✅ MEDIUM PRIORITY
**What exists**:
- `PersistenceBackend` abstract base class
- `SQLiteBackend`, `RedisBackend`, `InMemoryBackend` implementations
- Manual backend selection in `GleitzeitClient.__init__()`
- Environment variable support for backend configuration

**Streamlining approach**:
- Create unified backend manager for automatic selection
- Support for backend migration and hot-swapping
- Automatic fallback chain (Redis → SQLite → InMemory)
- Connection pooling and retry logic

**Implementation**:
```python
class BackendManager:
    """Manages persistence backends with automatic selection"""
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or self._load_config()
        self.backends = {}
        self.current_backend = None
        
    async def auto_select(self) -> PersistenceBackend:
        """Auto-select best available backend"""
        # Try Redis first (best for distributed)
        if await self._try_redis():
            return self.backends['redis']
        
        # Fall back to SQLite (good for single node)
        if await self._try_sqlite():
            return self.backends['sqlite']
        
        # Last resort: in-memory
        return InMemoryBackend()
    
    async def migrate(self, from_backend: str, to_backend: str):
        """Migrate data between backends"""
        source = self.backends[from_backend]
        target = self.backends[to_backend]
        
        # Migrate tasks
        tasks = await source.get_all_queued_tasks()
        await target.save_tasks_batch(tasks)
        
        # Migrate workflows
        # ... migration logic
```

**Configuration**:
```yaml
# gleitzeit.yaml
persistence:
  primary: redis
  fallback_chain:
    - redis
    - sqlite
    - memory
  
  redis:
    url: redis://localhost:6379/0
    max_connections: 10
    retry_attempts: 3
    
  sqlite:
    path: ~/.gleitzeit/data.db
    wal_mode: true
    
  migration:
    auto_migrate_on_failure: true
    keep_backup: true
```

### 7. Provider Auto-Registration ✅ LOW PRIORITY
**What exists**:
- Manual provider registration
- `OllamaPoolProvider` for multi-instance

**Streamlining approach**:
- Auto-discover available providers on startup
- Dynamic provider registration API
- Health-based provider selection

**Implementation**:
```python
# In client initialization
async def _auto_register_providers(self):
    """Auto-discover and register available providers"""
    
    # Check for Ollama instances
    ollama_instances = await discover_ollama_instances()
    if ollama_instances:
        if len(ollama_instances) > 1:
            # Use pool provider for multiple instances
            provider = OllamaPoolProvider(
                provider_id="ollama-auto",
                instances=ollama_instances
            )
        else:
            # Use simple provider for single instance
            provider = OllamaProvider(
                provider_id="ollama-auto",
                url=ollama_instances[0]['url']
            )
        await provider.initialize()
        self.registry.register_provider(
            provider_id=provider.provider_id,
            protocol_id="llm/v1",
            provider_instance=provider
        )
```

## Unified Architecture with Streamlining

### How Components Work Together

```
┌─────────────────────────────────────────────────────────────┐
│                     Configuration Layer                      │
│  YAML/TOML Config │ Environment Vars │ Auto-Discovery      │
└────────────────┬────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────┐
│                      Backend Manager                         │
│  Auto-select persistence (Redis → SQLite → Memory)          │
│  Migration support │ Connection pooling │ Retry logic       │
└────────────────┬────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────┐
│                    Provider Registry                         │
│  Auto-register discovered providers                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                    │
│  │ Ollama   │ │ Python   │ │   MCP    │                    │
│  │   Hub    │ │   Hub    │ │   Hub    │                    │
│  └──────────┘ └──────────┘ └──────────┘                    │
└────────────────┬────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────┐
│                  Enhanced Client API                         │
│  GleitzeitClient(auto_discover=True, auto_backend=True)     │
│  Convenience methods │ Progress tracking │ Error help       │
└────────────────┬────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────┐
│              Orchestration Engine (Unchanged)                │
│  Workflow → Task Queue → Execution → Results                │
└──────────────────────────────────────────────────────────────┘
```

### Integration Flow

1. **Startup**:
   ```python
   # User code - maximally simple
   client = GleitzeitClient(auto_configure=True)
   
   # What happens internally:
   # 1. BackendManager auto-selects best persistence
   # 2. Provider auto-discovery finds Ollama/Docker/MCP
   # 3. Providers registered with appropriate hubs
   # 4. Client ready to use
   ```

2. **Execution**:
   ```python
   # User code
   result = await client.chat("Hello")
   
   # What happens internally:
   # 1. Creates workflow with single task
   # 2. Task queued with persistence
   # 3. Engine routes to OllamaHub
   # 4. Hub selects best instance
   # 5. Result persisted and returned
   ```

3. **Failure Handling**:
   ```python
   # Automatic failover at multiple levels:
   # - Backend: Redis fails → SQLite takes over
   # - Provider: Ollama instance fails → Hub routes to another
   # - Task: Failure → Automatic retry per policy
   ```

## Implementation Priority

### Phase 1: Enhance Existing Components (Week 1)
1. ✅ Complete hub-based provider implementations (Ollama, Python, MCP)
2. ✅ Add auto-discovery to `OllamaPoolProvider`
3. ✅ Enhance client with auto-discovery option
4. ✅ Integrate streamlined providers with registry

### Phase 2: Configuration & UX (Week 2)
1. ✅ Add configuration file support
2. ✅ Implement provider presets
3. ✅ Add progress tracking to client
4. ✅ Enhanced MCP provider with external server support

### Phase 3: Advanced Features (Week 3)
1. ✅ Fluent workflow builder API
2. ✅ Workflow template library
3. ✅ Enhanced error handling and suggestions
4. ✅ Multi-provider hub management (Ollama, Python, MCP)

## What NOT to Do

❌ **Don't bypass the orchestration engine** - All operations must flow through workflows
❌ **Don't create alternative execution paths** - Use the existing task queue system
❌ **Don't break protocol specifications** - Maintain JSON-RPC compatibility
❌ **Don't remove persistence** - Traceability is crucial
❌ **Don't simplify away power features** - Dependencies and substitution must remain

## Success Metrics

1. **Ease of Use**: Time to first successful workflow execution < 2 minutes
2. **Reliability**: Automatic failover reduces failures by 80%
3. **Performance**: Multi-instance support increases throughput by 3x
4. **Compatibility**: 100% backward compatibility maintained
5. **Adoption**: 50% of users adopt auto-configuration features

## Example: Streamlined Usage

```python
# Before streamlining
from gleitzeit import GleitzeitClient
from gleitzeit.providers import OllamaProvider, CustomFunctionProvider, SimpleMCPProvider

client = GleitzeitClient()
await client.initialize()

# Manually register providers
ollama = OllamaProvider("ollama-1", "http://localhost:11434")
await ollama.initialize()
client.registry.register_provider("ollama-1", "llm/v1", ollama)

python = CustomFunctionProvider("python-1")
await python.initialize()
client.registry.register_provider("python-1", "python/v1", python)

mcp = SimpleMCPProvider("mcp-1")
await mcp.initialize()
client.registry.register_provider("mcp-1", "mcp/v1", mcp)

result = await client.chat("Hello")

# After streamlining
from gleitzeit import GleitzeitClient

# Everything auto-configured!
async with GleitzeitClient(auto_discover_providers=True) as client:
    # Automatically discovers and registers:
    # - Multiple Ollama instances (uses OllamaPoolProvider)
    # - Python execution (Docker or local)
    # - MCP servers (SimpleMCPProvider + external servers)
    
    result = await client.chat("Hello")
    
    # MCP tools also available
    calc = await client.execute_task(
        method="mcp/tool.add",
        params={"a": 10, "b": 20}
    )
```

## Conclusion

This streamlining plan:
1. **Enhances** the existing system without replacing it
2. **Preserves** the orchestration architecture
3. **Simplifies** common use cases
4. **Maintains** power user features
5. **Ensures** backward compatibility

The key insight: Make the system easier to use by improving provider management and configuration, not by bypassing the orchestration layer.