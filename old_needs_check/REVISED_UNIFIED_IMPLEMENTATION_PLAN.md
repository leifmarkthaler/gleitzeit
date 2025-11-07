# Revised Unified Service Management Implementation Plan

## Audit Results: Existing Components

### 1. Existing Managers & Orchestrators

#### Docker Mode:
- **ComponentOrchestrator** (`orchestrator/component_orchestrator.py`)
  - Full Docker mode orchestrator
  - Already stores PID in Redis: `orchestrator:pid`
  - Properly loads and propagates handler configs
  - Used when running without --force-native

- **DockerOrchestrator** (`cli/serve_docker.py`)
  - Docker Compose based orchestration
  - Used for docker-compose operations

#### Native Mode:
- **AsyncProcessManager** (`core/async_process_manager.py`)
  - Low-level async process management
  - Fixes subprocess deadlock issues
  - Tracks processes in memory (self.processes dict)
  - BUT: No persistent tracking between runs

- **AsyncServiceManager** (`core/async_process_manager.py`)
  - High-level service management using AsyncProcessManager
  - Missing configuration loading (root cause of config bug)
  - Creates new instance each run (no service detection)

#### Other Managers:
- **SmartProcessManager** (`core/process_manager.py`)
  - Instance-aware process management
  - Has Redis integration for tracking

- **ProcessOrchestrator** (`core/process_orchestrator.py`)
  - Layered management system
  - Not currently used in main flows

- **ServiceManager** (`core/service_manager.py`)
  - API/UI service lifecycle management
  - Works with SmartProcessManager

- **WorkerManager** (`core/worker_manager.py`)
  - Worker lifecycle and shard management
  - Works with SmartProcessManager

- **ConfigurationManager** (`core/config_manager.py`)
  - Already exists! Has configuration precedence system
  - Not currently used by AsyncServiceManager

- **PortManager** (`core/ports.py`)
  - Redis-based distributed port management
  - Could be leveraged for port allocation

### 2. Existing CLI Commands

Already implemented:
- `gleitzeit ps` - Shows running services (Docker & native)
- `gleitzeit stop` - Stops services intelligently
- `gleitzeit clean` - Cleanup command
- `gleitzeit logs` - View service logs
- `gleitzeit scale` - Scale workers

### 3. Existing Detection & Registry

- **mode_utils.py** - Detects running mode (Docker vs native)
  - `detect_running_mode()`
  - `is_docker_running()`
  - `is_native_running()`
  - `get_running_services()`

- **HandlerRegistry** (`handlers/registry.py`)
  - For handler registration only
  - Not for service tracking

### 4. Existing Redis Keys

Already in use:
- `orchestrator:pid` - Orchestrator PID tracking
- `worker:*` - Worker tracking
- Port allocations via PortManager

## Revised Implementation Plan

### Key Insight: We have most pieces, they're just not connected!

### Phase 1: Extend Existing Components (Don't Reinvent)

#### 1.1 Enhance SmartProcessManager for Service Registry
```python
# src/gleitzeit/core/process_manager.py

class SmartProcessManager:
    # Already has Redis integration!

    async def register_service(self, name: str, info: Dict):
        """Add persistent service registration"""
        key = f"service:registry:{name}"
        await self.redis.hset(key, mapping=info)

    async def get_registered_services(self) -> Dict:
        """Get all registered services"""
        # Implementation using existing Redis connection
```

#### 1.2 Fix AsyncServiceManager Configuration
```python
# src/gleitzeit/core/async_process_manager.py

class AsyncServiceManager:
    def __init__(self, config: dict = None, log_dir: Path = None, config_file: str = None):
        # Use existing ConfigurationManager!
        self.config_manager = ConfigurationManager()
        if config_file:
            self.config = self.config_manager.load(config_file)

        # Use SmartProcessManager instead of AsyncProcessManager
        self.process_manager = SmartProcessManager(config=self.config)
```

### Phase 2: Unify Service Detection

#### 2.1 Update serve_unified.py to Check Existing Services
```python
# src/gleitzeit/cli/serve_unified.py

async def serve_native_async(...):
    # Check for existing services first
    smart_manager = SmartProcessManager()
    existing = await smart_manager.get_registered_services()

    if existing and not restart:
        click.echo("🔍 Found existing services:")
        for name, info in existing.items():
            click.echo(f"   - {name} (PID: {info['pid']})")

        # Attach to existing instead of failing
        manager = AsyncServiceManager(...)
        await manager.attach_to_existing(existing)
        await manager.monitor_loop()
        return

    # Otherwise start fresh...
```

### Phase 3: Connect Existing Commands

#### 3.1 Update ps_command.py to Use SmartProcessManager
```python
# Already works! Just needs to also check service:registry:* keys
```

#### 3.2 Update stop_command.py
```python
# Already works! Just needs to clean registry when stopping
```

### Phase 4: Minimal New Code

#### 4.1 Service Registry Protocol
```python
# src/gleitzeit/core/service_registry_protocol.py

class ServiceRegistryProtocol:
    """
    Protocol for service registration that all managers follow
    """
    REGISTRY_PREFIX = "service:registry"
    CONFIG_PREFIX = "service:config"

    @staticmethod
    def get_service_key(name: str) -> str:
        return f"{ServiceRegistryProtocol.REGISTRY_PREFIX}:{name}"
```

### Phase 5: Migration Path

1. **Step 1**: Add service registration to ComponentOrchestrator (Docker mode)
   - Already has Redis PID tracking
   - Just extend to full service info

2. **Step 2**: Add service registration to AsyncServiceManager (Native mode)
   - Use SmartProcessManager instead of AsyncProcessManager
   - Leverage existing ConfigurationManager

3. **Step 3**: Update serve_unified.py
   - Check for existing services before starting
   - Attach to existing or start new

4. **Step 4**: Update CLI commands
   - ps: Check registry keys
   - stop: Clean registry
   - clean: Already exists

## Benefits of This Approach

1. **Minimal New Code**: Reuse existing managers
2. **No Breaking Changes**: Existing flows continue to work
3. **Gradual Migration**: Can implement piece by piece
4. **Proven Components**: SmartProcessManager already has Redis integration

## Implementation Priority

1. **Fix AsyncServiceManager config loading** (fixes handler config bug)
2. **Add service detection to serve_unified.py** (fixes port conflict)
3. **Connect SmartProcessManager to AsyncServiceManager**
4. **Update CLI commands to use registry**

## Risks & Mitigation

### Risk: Multiple Manager Classes
- **Issue**: Confusion between AsyncProcessManager, SmartProcessManager, ProcessOrchestrator
- **Mitigation**: Document clear usage boundaries, deprecate unused ones

### Risk: Redis Key Conflicts
- **Issue**: Different managers using different key patterns
- **Mitigation**: Use ServiceRegistryProtocol for consistent keys

### Risk: Breaking Existing Flows
- **Issue**: Current users depend on existing behavior
- **Mitigation**: Add feature flags for new behavior

## Next Steps

1. Fix AsyncServiceManager configuration loading (immediate bug fix)
2. Add service detection to serve_unified.py
3. Test with both Docker and native modes
4. Document the unified flow

## Estimated Timeline

- Phase 1: 1 day (extend existing components)
- Phase 2: 1 day (unify detection)
- Phase 3: 0.5 day (connect commands)
- Phase 4: 0.5 day (minimal new code)
- Testing: 1 day
- **Total: 4 days** (vs 7 days in original plan)