# Unified Service Management & Configuration Flow Design

## Overview
This design addresses two critical issues:
1. **Configuration Flow**: Handlers not receiving proper configuration from gleitzeit.yaml
2. **Service Detection**: `gleitzeit serve` not detecting/reusing already running services

## Current Problems

### Problem 1: Configuration Flow Fragmentation
- Configuration flows differently in Docker vs Native modes
- ComponentOrchestrator (Docker mode) properly loads and propagates handler configs
- AsyncServiceManager (Native mode) bypasses configuration loading
- Handlers receive incomplete or missing configuration

### Problem 2: Service Management Fragmentation
- Each `gleitzeit serve` invocation creates a new manager instance
- No persistent tracking of running services
- Port conflicts instead of service reuse
- No central service registry

## Proposed Solution: Unified Service Registry

### Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                     Service Registry                         │
│                    (Redis-backed)                           │
├─────────────────────────────────────────────────────────────┤
│  - service:registry:api         → PID, port, status        │
│  - service:registry:ui          → PID, port, status        │
│  - service:registry:workers:*   → PID, port, status        │
│  - service:config:global        → gleitzeit.yaml content   │
│  - service:config:handlers:*    → handler configs          │
└─────────────────────────────────────────────────────────────┘
                              ▲
                              │
                ┌─────────────┴─────────────┐
                │                           │
        ┌───────▼────────┐         ┌───────▼────────┐
        │ Native Mode    │         │ Docker Mode    │
        │ (AsyncManager) │         │ (Orchestrator) │
        └────────────────┘         └────────────────┘
```

## Implementation Plan

### Phase 1: Service Registry Infrastructure

#### 1.1 Create ServiceRegistry Class
```python
# src/gleitzeit/core/service_registry.py

class ServiceRegistry:
    """Central registry for all running services"""

    def __init__(self, redis_client):
        self.redis = redis_client
        self.namespace = "service:registry"

    async def register_service(self, name: str, info: Dict):
        """Register a running service"""
        key = f"{self.namespace}:{name}"
        await self.redis.hset(key, mapping={
            "pid": info["pid"],
            "port": info.get("port"),
            "host": info.get("host", "localhost"),
            "started_at": datetime.now().isoformat(),
            "status": "running",
            "mode": info.get("mode", "native"),  # native/docker
            "config_key": info.get("config_key"),
        })

    async def get_service(self, name: str) -> Optional[Dict]:
        """Get service info if running"""
        key = f"{self.namespace}:{name}"
        data = await self.redis.hgetall(key)
        if not data:
            return None

        # Verify process is actually running
        if not self._is_process_running(int(data["pid"])):
            await self.unregister_service(name)
            return None

        return data

    async def list_services(self) -> Dict[str, Dict]:
        """List all registered services"""
        pattern = f"{self.namespace}:*"
        services = {}

        async for key in self.redis.scan_iter(pattern):
            name = key.decode().split(":")[-1]
            info = await self.get_service(name)
            if info:
                services[name] = info

        return services

    async def unregister_service(self, name: str):
        """Remove service from registry"""
        key = f"{self.namespace}:{name}"
        await self.redis.delete(key)

    def _is_process_running(self, pid: int) -> bool:
        """Check if process is still running"""
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False
```

#### 1.2 Create Configuration Manager
```python
# src/gleitzeit/core/config_manager.py

class ConfigurationManager:
    """Central configuration management"""

    def __init__(self, redis_client):
        self.redis = redis_client
        self.namespace = "service:config"

    async def load_config(self, config_file: Path) -> Dict:
        """Load and store configuration"""
        with open(config_file) as f:
            config = yaml.safe_load(f)

        # Store in Redis for persistence
        await self.redis.set(
            f"{self.namespace}:global",
            json.dumps(config),
            ex=86400  # 24 hour TTL
        )

        # Store handler configs separately for easy access
        if "handlers" in config:
            for handler_name, handler_config in config["handlers"].items():
                await self.redis.set(
                    f"{self.namespace}:handlers:{handler_name}",
                    json.dumps(handler_config),
                    ex=86400
                )

        return config

    async def get_config(self) -> Dict:
        """Get stored configuration"""
        data = await self.redis.get(f"{self.namespace}:global")
        if data:
            return json.loads(data)
        return {}

    async def get_handler_config(self, handler_name: str) -> Dict:
        """Get specific handler configuration"""
        data = await self.redis.get(f"{self.namespace}:handlers:{handler_name}")
        if data:
            return json.loads(data)
        return {}
```

### Phase 2: Unified Service Manager

#### 2.1 Create UnifiedServiceManager
```python
# src/gleitzeit/core/unified_manager.py

class UnifiedServiceManager:
    """Unified manager for both Docker and Native modes"""

    def __init__(self, config_file: Path, mode: str = "auto"):
        self.config_file = config_file
        self.mode = mode
        self.redis = None
        self.registry = None
        self.config_manager = None
        self.process_manager = None

    async def initialize(self):
        """Initialize manager and detect existing services"""
        # Connect to Redis
        self.redis = await aioredis.from_url("redis://localhost:6379")

        # Initialize registry and config manager
        self.registry = ServiceRegistry(self.redis)
        self.config_manager = ConfigurationManager(self.redis)

        # Load configuration
        self.config = await self.config_manager.load_config(self.config_file)

        # Detect running services
        self.existing_services = await self.registry.list_services()

        # Initialize appropriate process manager
        if self.mode == "docker" or (self.mode == "auto" and docker_available()):
            self.process_manager = DockerProcessManager(self.config)
        else:
            self.process_manager = AsyncProcessManager(self.config)

    async def start_service(self, name: str, **kwargs) -> bool:
        """Start or attach to existing service"""

        # Check if already running
        existing = await self.registry.get_service(name)
        if existing:
            print(f"✅ {name} already running (PID: {existing['pid']})")
            return True

        # Start new service
        if name == "api":
            success = await self._start_api(**kwargs)
        elif name == "ui":
            success = await self._start_ui(**kwargs)
        elif name.startswith("worker:"):
            success = await self._start_worker(name, **kwargs)
        else:
            raise ValueError(f"Unknown service: {name}")

        if success:
            # Register in registry
            await self.registry.register_service(name, {
                "pid": self.process_manager.get_pid(name),
                "port": kwargs.get("port"),
                "mode": "docker" if isinstance(self.process_manager, DockerProcessManager) else "native"
            })

        return success

    async def start_all(self, **kwargs):
        """Start all services (reuse existing ones)"""

        print("\n🔍 Checking for existing services...")
        if self.existing_services:
            print(f"   Found {len(self.existing_services)} running services:")
            for name, info in self.existing_services.items():
                print(f"   - {name} (PID: {info['pid']}, Port: {info.get('port', 'N/A')})")
        else:
            print("   No existing services found")

        print("\n🚀 Starting services...")

        # Start API
        await self.start_service("api", port=kwargs.get("api_port", 8000))

        # Start UI
        if not kwargs.get("no_ui"):
            await self.start_service("ui", port=kwargs.get("ui_port", 8004))

        # Start workers
        for worker_config in self.config.get("workers", []):
            await self.start_service(f"worker:{worker_config['name']}", config=worker_config)

    async def stop_service(self, name: str):
        """Stop a specific service"""
        existing = await self.registry.get_service(name)
        if existing:
            # Stop the process
            if existing["mode"] == "docker":
                await self._stop_docker_service(name)
            else:
                await self._stop_native_service(int(existing["pid"]))

            # Unregister
            await self.registry.unregister_service(name)

    async def stop_all(self):
        """Stop all services"""
        services = await self.registry.list_services()
        for name in services:
            await self.stop_service(name)
```

### Phase 3: Update CLI Commands

#### 3.1 Update serve_unified.py
```python
# src/gleitzeit/cli/serve_unified.py

async def serve_native_async(...):
    """Updated native serve with service detection"""

    # Create unified manager
    manager = UnifiedServiceManager(
        config_file=Path(config_file),
        mode="native" if force_native else "auto"
    )

    await manager.initialize()

    # Handle restart flag
    if restart:
        click.echo("🔄 Restarting services...")
        await manager.stop_all()
        await asyncio.sleep(1)

    # Start or reuse services
    try:
        await manager.start_all(
            api_port=api_port,
            ui_port=ui_port,
            no_ui=no_ui,
            dev_mode=dev_mode
        )

        # Monitor loop
        while True:
            status = await manager.get_status()
            # ... monitoring logic ...
            await asyncio.sleep(5)

    except KeyboardInterrupt:
        click.echo("\n🛑 Stopping services...")
        if not no_detach:  # New flag to keep services running
            await manager.stop_all()
```

#### 3.2 Add New CLI Commands
```python
# src/gleitzeit/cli/main.py

@cli.command()
def ps():
    """List running services"""
    asyncio.run(_ps())

async def _ps():
    redis = await aioredis.from_url("redis://localhost:6379")
    registry = ServiceRegistry(redis)
    services = await registry.list_services()

    if not services:
        click.echo("No services running")
        return

    # Display in table format
    click.echo("\nRunning Services:")
    click.echo("-" * 60)
    for name, info in services.items():
        click.echo(f"{name:20} PID: {info['pid']:8} Port: {info.get('port', 'N/A'):6} Mode: {info['mode']}")

@cli.command()
@click.argument('service')
def attach(service):
    """Attach to logs of a running service"""
    # Implementation to tail logs of specific service

@cli.command()
@click.option('--keep-data', is_flag=True)
def clean(keep_data):
    """Clean up services and optionally data"""
    asyncio.run(_clean(keep_data))
```

### Phase 4: Configuration Flow Fix

#### 4.1 Update AsyncServiceManager
```python
# src/gleitzeit/core/async_process_manager.py

class AsyncServiceManager:
    def __init__(self, config: Dict, log_dir: Path, config_file: Path = None):
        self.config = config
        self.config_file = config_file
        self.config_manager = None  # Will be initialized

    async def initialize(self):
        """Initialize with configuration"""
        redis = await aioredis.from_url("redis://localhost:6379")
        self.config_manager = ConfigurationManager(redis)

        # Load and store configuration
        if self.config_file:
            self.config = await self.config_manager.load_config(self.config_file)

        # Load handler configs
        self.handler_configs = {}
        if "handlers" in self.config:
            for name, cfg in self.config["handlers"].items():
                self.handler_configs[f"{name}/v1"] = cfg
```

## Benefits

### 1. Service Detection & Reuse
- `gleitzeit serve` detects and reuses existing services
- No more "port already in use" errors
- Seamless service management

### 2. Unified Configuration
- Single source of truth for configuration
- Consistent flow in both Docker and Native modes
- Handlers always receive proper configuration

### 3. Better Developer Experience
- `gleitzeit ps` to see running services
- `gleitzeit attach <service>` to view logs
- `gleitzeit clean` for cleanup
- Services persist across CLI invocations

### 4. Reliability
- Automatic cleanup of dead processes
- Service health monitoring
- Graceful degradation

## Migration Path

1. **Phase 1**: Implement ServiceRegistry and ConfigurationManager
2. **Phase 2**: Create UnifiedServiceManager
3. **Phase 3**: Update CLI commands to use new manager
4. **Phase 4**: Fix configuration flow in AsyncServiceManager
5. **Phase 5**: Add new CLI commands (ps, attach, clean)
6. **Phase 6**: Deprecate old implementations

## Testing Strategy

1. Unit tests for ServiceRegistry and ConfigurationManager
2. Integration tests for UnifiedServiceManager
3. E2E tests for service detection and reuse
4. Configuration propagation tests
5. Multi-instance deployment tests

## Estimated Timeline

- Phase 1-2: 2 days (Core infrastructure)
- Phase 3-4: 2 days (Integration and configuration fix)
- Phase 5: 1 day (New CLI commands)
- Testing: 2 days
- Total: ~1 week

## Backwards Compatibility

- Existing commands continue to work
- Gradual migration to new system
- Feature flags for rollback if needed