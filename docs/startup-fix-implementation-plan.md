# Gleitzeit Startup & Restart Fix Implementation Plan

**Date**: 2025-09-26
**Last Updated**: 2025-09-26 (Phase 1 & 2 Completed)
**Priority**: HIGH - System reliability depends on this
**Timeline**: 1-2 weeks
**Complexity**: Medium - Systems exist, need integration
**Status**: Phase 1 COMPLETE ✅ | Phase 2 COMPLETE ✅ | Phase 3-5 PENDING

## Executive Summary

Gleitzeit has sophisticated port management, service discovery, and process management systems that were NOT being used by the serve module. This implementation plan details how to properly integrate these existing systems to solve all startup/restart issues.

## ✅ PHASE 1 COMPLETED (2025-09-26)

### Implemented Successfully:
1. **PortManager Integration** - Atomic port allocation via Redis with proper TTL management
2. **Zombie Process Cleanup** - Automatic detection and cleanup of stuck serve processes
3. **Service Registration** - Services now register/deregister in Redis for discovery
4. **Port Release** - Proper cleanup on shutdown

### Verified Working:
- API running on port 8000 ✅
- UI running on port 8004 ✅
- Port allocations in Redis ✅
- Service registrations in Redis ✅
- No zombie process accumulation ✅

## Current State vs Target State

### Current State (BROKEN)
```
serve.py → subprocess.Popen → uvicorn → service
   ↓                              ↓
(no tracking)              (no registration)
   ↓                              ↓
ZOMBIE PROCESSES          PORT CONFLICTS
```

### Target State (FIXED)
```
serve.py → ProcessManager → Service
   ↓            ↓              ↓
PortManager  Discovery   Health Checks
   ↓            ↓              ↓
CLEAN STATE  COORDINATION  RELIABILITY
```

## Phase 1: Immediate Fixes (Day 1-2)

### Task 1.1: Integrate PortManager Properly
**File**: `src/gleitzeit/cli/serve.py`
**Priority**: CRITICAL
**Effort**: 4 hours

#### Current (Broken):
```python
class GleitzeitServer:
    def __init__(self):
        self.port_manager = PortManager()  # Created but not used!
        # ...
        # Ports are set from config/CLI but not allocated via PortManager
        self.api_port = api_port if api_port is not None else self.instance.get_service_port('api')
```

#### Fix:
```python
import asyncio
from ..core.ports import PortManager

class GleitzeitServer:
    def __init__(self):
        self.port_manager = PortManager()
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def _allocate_ports(self):
        """Properly allocate ports using PortManager"""
        # Run async port allocation in sync context
        async def allocate():
            # Override from CLI takes precedence
            if self.api_port_override:
                # Try to claim the requested port
                allocated = await self.port_manager._allocate_port('api', self.api_port_override)
                if allocated != self.api_port_override:
                    raise RuntimeError(f"Port {self.api_port_override} not available")
                self.api_port = allocated
            else:
                # Let PortManager find available port
                self.api_port = await self.port_manager.get_service_port('api')

            if not self.no_ui:
                if self.ui_port_override:
                    allocated = await self.port_manager._allocate_port('ui', self.ui_port_override)
                    if allocated != self.ui_port_override:
                        raise RuntimeError(f"Port {self.ui_port_override} not available")
                    self.ui_port = allocated
                else:
                    self.ui_port = await self.port_manager.get_service_port('ui')

            return self.api_port, self.ui_port

        # Execute async allocation
        api_port, ui_port = self.loop.run_until_complete(allocate())

        logger.info(f"Allocated ports - API: {api_port}, UI: {ui_port}")

    def start(self):
        """Start all components with proper port allocation"""
        # Allocate ports BEFORE checking/starting services
        self._allocate_ports()

        # Now start services with allocated ports
        self.start_api()
        if not self.no_ui:
            self.start_ui()
```

### Task 1.2: Fix Zombie Process Cleanup
**File**: `src/gleitzeit/cli/serve.py`
**Priority**: CRITICAL
**Effort**: 2 hours

#### Add Automatic Zombie Cleanup:
```python
def _cleanup_zombie_serve_processes(self):
    """Kill zombie serve processes automatically"""
    current_pid = os.getpid()
    killed_pids = []

    for proc in psutil.process_iter(['pid', 'cmdline', 'create_time']):
        try:
            cmdline = proc.info.get('cmdline', [])
            if not cmdline:
                continue

            # Identify serve processes
            if any('gleitzeit.cli.serve' in str(c) for c in cmdline):
                if proc.pid == current_pid:
                    continue  # Don't kill self

                # Check if process is stuck (not binding ports)
                create_time = proc.info.get('create_time', 0)
                age = time.time() - create_time

                if age > 30:  # Process older than 30 seconds
                    # Check if it has any listening ports
                    has_ports = False
                    try:
                        for conn in proc.connections():
                            if conn.status == 'LISTEN':
                                has_ports = True
                                break
                    except:
                        pass

                    if not has_ports:
                        # It's a zombie - kill it
                        logger.warning(f"Killing zombie serve process {proc.pid} (age: {age:.0f}s)")
                        proc.terminate()
                        killed_pids.append(proc.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # Wait for termination
    for pid in killed_pids:
        try:
            psutil.Process(pid).wait(timeout=2)
        except:
            try:
                psutil.Process(pid).kill()  # Force kill if needed
            except:
                pass

    if killed_pids:
        logger.info(f"Cleaned up {len(killed_pids)} zombie serve processes")
        time.sleep(1)  # Give OS time to release resources

def start(self):
    """Start with automatic cleanup"""
    # ALWAYS clean zombies first
    self._cleanup_zombie_serve_processes()

    # Then proceed with normal startup
    self._allocate_ports()
    # ...
```

### Task 1.3: Implement Service Registration
**File**: `src/gleitzeit/cli/serve.py`
**Priority**: HIGH
**Effort**: 3 hours

#### Register Services in Discovery:
```python
import aioredis
from ..api.discovery import DiscoveryService

class GleitzeitServer:
    async def _register_service(self, name: str, port: int):
        """Register service in discovery system"""
        redis = await aioredis.from_url(self.env.get('REDIS_URL', 'redis://localhost:6379'))
        discovery = DiscoveryService(redis)

        service_info = {
            'name': name,
            'instance_id': self.instance.instance_id,
            'machine_id': self.instance.machine_id,
            'host': self.api_host if name == 'api' else self.ui_host,
            'port': port,
            'status': 'starting',
            'started_at': datetime.utcnow().isoformat(),
            'pid': os.getpid()
        }

        await discovery.register_service(service_info)
        logger.info(f"Registered {name} service on port {port}")

        await redis.close()

    def start_api(self):
        """Start API with registration"""
        # ... existing startup code ...

        # Register in discovery
        self.loop.run_until_complete(
            self._register_service('api', self.api_port)
        )

        # Update status to running
        self.loop.run_until_complete(
            self._update_service_status('api', 'running')
        )
```

## Phase 2: Process Management Integration (Day 3-4)

### Task 2.1: Replace subprocess.Popen with ProcessManager
**File**: `src/gleitzeit/cli/serve.py`
**Priority**: HIGH
**Effort**: 4 hours

#### Current:
```python
proc = subprocess.Popen(cmd, env=self.env, ...)
self.processes["api"] = proc
```

#### Fixed:
```python
from ..core.process_manager import SmartProcessManager

class GleitzeitServer:
    def __init__(self):
        self.process_manager = SmartProcessManager()

    async def start_api_async(self):
        """Start API using ProcessManager"""
        config = {
            'name': 'api',
            'command': [sys.executable, "-m", "uvicorn", "gleitzeit.api.main:app"],
            'args': ["--host", self.api_host, "--port", str(self.api_port)],
            'env': self.env,
            'restart_policy': 'on-failure',
            'max_restarts': 3,
            'health_check': {
                'endpoint': f"http://localhost:{self.api_port}/health",
                'interval': 30,
                'timeout': 5
            }
        }

        process = await self.process_manager.start_process(config)

        # Wait for health check
        healthy = await self.process_manager.wait_for_health('api', timeout=30)
        if not healthy:
            raise RuntimeError("API failed health check")

        return process
```

### Task 2.2: Add Health Monitoring
**Priority**: MEDIUM
**Effort**: 3 hours

```python
class HealthMonitor:
    """Monitor service health and restart if needed"""

    def __init__(self, process_manager: SmartProcessManager):
        self.process_manager = process_manager
        self.monitoring = True

    async def monitor_loop(self):
        """Continuous health monitoring"""
        while self.monitoring:
            try:
                # Check all services
                statuses = await self.process_manager.get_all_statuses()

                for service, status in statuses.items():
                    if status['state'] == 'failed':
                        logger.warning(f"Service {service} failed, attempting restart")
                        await self.process_manager.restart_process(service)

                    elif status['state'] == 'unhealthy':
                        consecutive_failures = status.get('consecutive_failures', 0)
                        if consecutive_failures > 3:
                            logger.warning(f"Service {service} unhealthy, restarting")
                            await self.process_manager.restart_process(service)

                await asyncio.sleep(10)  # Check every 10 seconds

            except Exception as e:
                logger.error(f"Health monitor error: {e}")
                await asyncio.sleep(30)
```

## Phase 3: Configuration Management (Day 5-6)

### Task 3.1: Implement Clear Configuration Precedence
**Priority**: HIGH
**Effort**: 3 hours

```python
class ConfigurationManager:
    """Unified configuration with clear precedence"""

    PRECEDENCE = [
        'cli_args',      # 1. Command line (highest)
        'env_vars',      # 2. Environment variables
        'instance',      # 3. Instance configuration
        'config_file',   # 4. YAML config file
        'defaults'       # 5. Hardcoded defaults (lowest)
    ]

    def __init__(self, config_file: str, cli_args: dict):
        self.config_file = config_file
        self.cli_args = cli_args
        self.yaml_config = self._load_yaml()
        self.instance = get_current_instance()

    def get_port(self, service: str) -> int:
        """Get port with clear precedence"""
        sources = {
            'cli_args': self.cli_args.get(f'{service}_port'),
            'env_vars': os.getenv(f'GLEITZEIT_{service.upper()}_PORT'),
            'instance': self.instance.get_service_port(service) if self.instance else None,
            'config_file': self.yaml_config.get('serve', {}).get(service, {}).get('port'),
            'defaults': PortManager.DEFAULT_PORTS.get(service)
        }

        for source in self.PRECEDENCE:
            value = sources.get(source)
            if value is not None:
                logger.info(f"Port for {service}: {value} (source: {source})")
                return int(value)

        raise ValueError(f"No port configuration found for {service}")
```

### Task 3.2: Add Configuration Validation
**Priority**: MEDIUM
**Effort**: 2 hours

```python
def validate_configuration(config: dict) -> List[str]:
    """Validate configuration and return errors"""
    errors = []

    # Check port ranges
    for service in ['api', 'ui']:
        port = config.get('serve', {}).get(service, {}).get('port')
        if port:
            if not (1024 <= port <= 65535):
                errors.append(f"{service} port {port} out of valid range")

    # Check Redis connectivity
    redis_config = config.get('redis', {})
    if not can_connect_redis(redis_config):
        errors.append("Cannot connect to Redis")

    # Check for port conflicts in config
    ports = []
    for service in ['api', 'ui', 'orchestrator']:
        port = config.get('serve', {}).get(service, {}).get('port')
        if port:
            if port in ports:
                errors.append(f"Port {port} configured for multiple services")
            ports.append(port)

    return errors
```

## Phase 4: Service Coordination (Day 7-8)

### Task 4.1: Implement Startup Sequencing
**Priority**: HIGH
**Effort**: 4 hours

```python
class ServiceCoordinator:
    """Coordinate service startup with dependencies"""

    # Service startup order and dependencies
    STARTUP_SEQUENCE = [
        {'name': 'redis', 'depends_on': [], 'required': True},
        {'name': 'orchestrator', 'depends_on': ['redis'], 'required': False},
        {'name': 'api', 'depends_on': ['redis'], 'required': True},
        {'name': 'ui', 'depends_on': ['api'], 'required': False}
    ]

    async def start_services(self, server: GleitzeitServer):
        """Start services in correct order"""
        started = set()

        for service_def in self.STARTUP_SEQUENCE:
            name = service_def['name']

            # Skip if not enabled
            if name == 'orchestrator' and server.no_orchestrator:
                continue
            if name == 'ui' and server.no_ui:
                continue

            # Wait for dependencies
            for dep in service_def['depends_on']:
                if dep not in started:
                    if service_def['required']:
                        raise RuntimeError(f"Required dependency {dep} not started")
                    else:
                        logger.warning(f"Skipping {name}, dependency {dep} not available")
                        continue

            # Start service
            try:
                logger.info(f"Starting {name}...")

                if name == 'redis':
                    # Just verify Redis is accessible
                    await self._verify_redis()
                elif name == 'orchestrator':
                    await server.start_orchestrator_async()
                elif name == 'api':
                    await server.start_api_async()
                elif name == 'ui':
                    await server.start_ui_async()

                started.add(name)
                logger.info(f"✓ {name} started successfully")

            except Exception as e:
                if service_def['required']:
                    raise RuntimeError(f"Failed to start required service {name}: {e}")
                else:
                    logger.warning(f"Failed to start optional service {name}: {e}")
```

### Task 4.2: Add Graceful Shutdown
**Priority**: MEDIUM
**Effort**: 2 hours

```python
class GracefulShutdown:
    """Handle graceful shutdown of all services"""

    def __init__(self, server: GleitzeitServer):
        self.server = server
        self.shutting_down = False

    async def shutdown(self):
        """Gracefully shutdown all services"""
        if self.shutting_down:
            return  # Already shutting down

        self.shutting_down = True
        logger.info("Starting graceful shutdown...")

        # 1. Stop accepting new work
        await self._stop_accepting_work()

        # 2. Wait for in-flight requests (with timeout)
        await self._wait_for_requests(timeout=30)

        # 3. Deregister from discovery
        await self._deregister_services()

        # 4. Release port allocations
        await self._release_ports()

        # 5. Stop processes in reverse order
        await self._stop_processes()

        logger.info("Graceful shutdown complete")

    async def _deregister_services(self):
        """Remove services from discovery"""
        for service in ['api', 'ui', 'orchestrator']:
            try:
                await self.server.discovery.deregister_service(
                    service,
                    self.server.instance.instance_id
                )
            except Exception as e:
                logger.error(f"Failed to deregister {service}: {e}")

    async def _release_ports(self):
        """Release port allocations in Redis"""
        for service in ['api', 'ui']:
            try:
                await self.server.port_manager.release_port(service)
            except Exception as e:
                logger.error(f"Failed to release port for {service}: {e}")
```

## Phase 5: Testing & Validation (Day 9-10)

### Task 5.1: Integration Tests
**Priority**: HIGH
**Effort**: 4 hours

```python
# tests/test_startup_restart.py

@pytest.mark.asyncio
async def test_port_allocation_with_conflict():
    """Test port allocation handles conflicts"""
    # Start first instance
    server1 = GleitzeitServer(api_port=8000)
    await server1.start()

    # Try to start second instance on same port
    with pytest.raises(RuntimeError, match="Port 8000 not available"):
        server2 = GleitzeitServer(api_port=8000)
        await server2.start()

    # Second instance should work with different port
    server2 = GleitzeitServer(api_port=8001)
    await server2.start()

    # Cleanup
    await server1.shutdown()
    await server2.shutdown()

@pytest.mark.asyncio
async def test_zombie_cleanup():
    """Test zombie process cleanup"""
    # Create zombie process
    proc = subprocess.Popen(
        [sys.executable, "-m", "gleitzeit.cli.serve", "--api-port", "9999"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    # Let it fail to bind
    time.sleep(2)

    # Start new server - should clean zombie
    server = GleitzeitServer()
    await server.start()

    # Verify zombie was cleaned
    assert not psutil.pid_exists(proc.pid)

    await server.shutdown()

@pytest.mark.asyncio
async def test_service_discovery_integration():
    """Test services register and discover each other"""
    server = GleitzeitServer()
    await server.start()

    # Check services are registered
    services = await server.discovery.list_services()
    assert 'api' in [s['name'] for s in services]
    assert 'ui' in [s['name'] for s in services]

    # Check UI can find API
    api_info = await server.discovery.find_service('api')
    assert api_info['port'] == server.api_port

    await server.shutdown()
```

### Task 5.2: Load Tests
**Priority**: MEDIUM
**Effort**: 3 hours

```python
# tests/test_startup_load.py

async def test_rapid_restart():
    """Test system handles rapid restart cycles"""
    for i in range(10):
        logger.info(f"Restart cycle {i+1}/10")

        server = GleitzeitServer()
        await server.start()

        # Verify services are up
        assert await check_health(server.api_port)

        # Quick restart
        await server.shutdown()

        # No sleep - immediate restart

    # Verify no resource leaks
    assert count_zombie_processes() == 0
    assert count_open_ports() <= 2  # Only current services

async def test_concurrent_startup():
    """Test multiple instances can start concurrently"""
    servers = []

    # Start 5 instances with different ports
    tasks = []
    for i in range(5):
        server = GleitzeitServer(
            api_port=8000 + i*10,
            ui_port=8004 + i*10,
            instance_name=f"instance-{i}"
        )
        servers.append(server)
        tasks.append(server.start())

    # All should start successfully
    await asyncio.gather(*tasks)

    # Verify all are running
    for server in servers:
        assert await check_health(server.api_port)

    # Cleanup
    for server in servers:
        await server.shutdown()
```

## Implementation Timeline

### Week 1: Core Fixes
- **Day 1-2**: Port allocation and zombie cleanup (Tasks 1.1-1.3)
- **Day 3-4**: Process management integration (Tasks 2.1-2.2)
- **Day 5**: Configuration management (Task 3.1-3.2)

### Week 2: Advanced Features & Testing
- **Day 6-7**: Service coordination (Tasks 4.1-4.2)
- **Day 8-9**: Testing and validation (Tasks 5.1-5.2)
- **Day 10**: Documentation and deployment

## Success Criteria

### Functional Requirements
- ✅ No zombie processes accumulate
- ✅ Port conflicts are properly detected and handled
- ✅ Services can find each other via discovery
- ✅ Clean restart without manual intervention
- ✅ Graceful shutdown releases all resources

### Performance Requirements
- ✅ Startup time < 5 seconds
- ✅ Restart time < 10 seconds
- ✅ Zero resource leaks after 100 restart cycles
- ✅ Support 10+ concurrent instances

### Reliability Requirements
- ✅ Automatic recovery from process crashes
- ✅ Health monitoring and auto-restart
- ✅ No data loss during restart
- ✅ Clean error messages for all failure modes

## Risk Mitigation

### Risk 1: Breaking Changes
**Mitigation**:
- Keep backward compatibility with existing CLI
- Add feature flags for new behavior
- Extensive testing before deployment

### Risk 2: Async/Sync Integration Issues
**Mitigation**:
- Use asyncio.run() for clean async/sync boundaries
- Proper event loop management
- Thread-safe operations where needed

### Risk 3: Redis Dependency
**Mitigation**:
- Fallback to local port allocation if Redis unavailable
- Clear error messages if Redis required but not available
- Document Redis requirements

## Rollout Strategy

### Phase 1: Internal Testing
- Deploy to development environment
- Run integration test suite
- Monitor for 24 hours

### Phase 2: Canary Deployment
- Deploy to 10% of users
- Monitor metrics and errors
- Gradual rollout over 1 week

### Phase 3: Full Deployment
- Deploy to all users
- Monitor for issues
- Quick rollback plan ready

## Monitoring & Metrics

### Key Metrics to Track
- Startup success rate
- Average startup time
- Zombie process count
- Port conflict rate
- Service discovery hit rate
- Health check success rate

### Alerts to Configure
- Startup failures > 5% (WARNING)
- Zombie processes > 10 (WARNING)
- Port allocation failures > 1% (ERROR)
- Service discovery failures > 1% (ERROR)

## Conclusion

This implementation plan leverages Gleitzeit's existing sophisticated systems (PortManager, ProcessManager, Discovery) that are currently being bypassed. By properly integrating these systems, we can solve all startup/restart issues while maintaining backward compatibility.

The key insight is that **the solutions already exist in the codebase** - they just need to be properly connected. This reduces implementation risk and complexity significantly.