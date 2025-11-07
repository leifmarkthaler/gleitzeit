# Docker Horizontal Scaling Implementation Plan (REVISED)

## Phase 1: Foundation Changes (Required First)

### 1.1 Update serve_docker.py Function Signatures
**File**: `src/gleitzeit/cli/serve_docker.py`

**Changes**:
```python
# Line 249: Add horizontal scaling parameters
def serve_with_docker(
    config_file: str = "gleitzeit.yaml",
    host: str = "0.0.0.0",
    api_port: int = None,
    ui_port: int = None,
    dev_mode: bool = False,
    restart: bool = False,
    build: bool = False,
    no_ui: bool = False,
    # NEW PARAMETERS
    api_only: bool = False,
    workers_only: bool = False,
    redis_url: str = None,
    config_url: str = None
) -> None:

# Line 51: Add conditional service generation
def generate_compose_file(
    self,
    config: dict,
    api_only: bool = False,
    workers_only: bool = False,
    redis_url: str = None
) -> None:
```

### 1.2 Update serve_unified.py Parameter Passing
**File**: `src/gleitzeit/cli/serve_unified.py`

**Changes**:
```python
# Line 212: Pass missing parameters to Docker mode
serve_with_docker(
    config_file=config_file,
    host=api_host or "0.0.0.0",
    api_port=api_port,
    ui_port=ui_port,
    dev_mode=dev_mode,
    restart=restart,
    build=build,
    no_ui=no_ui,
    # ADD THESE
    api_only=api_only,
    workers_only=workers_only,
    redis_url=redis_url,
    config_url=config_url
)
```

## Phase 2: Service Registry Integration (REVISED)

### 2.1 ~~Create Docker Service Registry Module~~ **REMOVED**
**REVISION**: We already have `SmartProcessManager` in `src/gleitzeit/core/process_manager.py` with:
- `async def register_service(self, name: str, info: Dict)`
- `async def get_registered_services(self) -> Dict`
- Uses Redis keys: `service:registry:{service_name}`

**No new registry module needed** - Docker containers will use existing infrastructure.

### 2.2 Create Docker Registration Module
**New File**: `src/gleitzeit/core/docker_service_registry.py`

```python
"""Docker service registration module for container startup/shutdown"""
import os
import sys
import asyncio
import socket
import signal
from datetime import datetime
from typing import Optional

from .process_manager import SmartProcessManager


async def register_service(service_type: str, redis_url: Optional[str] = None) -> None:
    """Register Docker service in existing Redis service registry on startup"""
    redis_url = redis_url or os.getenv('REDIS_URL', 'redis://localhost:6379')
    hostname = socket.gethostname()

    # Use existing SmartProcessManager - no new registry needed
    manager = SmartProcessManager(redis_url=redis_url)

    # Register using existing service registry infrastructure
    await manager.register_service(service_type, {
        'host': hostname,
        'port': os.getenv('PORT', '8000'),
        'container_id': os.getenv('HOSTNAME'),
        'started_at': datetime.now().isoformat(),
        'mode': 'docker',
        'pid': os.getpid()  # Container PID for compatibility
    })

    print(f"Registered {service_type} service in Redis registry")


async def unregister_service(service_type: str, redis_url: Optional[str] = None) -> None:
    """Deregister Docker service from existing Redis registry on shutdown"""
    redis_url = redis_url or os.getenv('REDIS_URL', 'redis://localhost:6379')

    # Use existing SmartProcessManager
    manager = SmartProcessManager(redis_url=redis_url)
    await manager.unregister_service(service_type)

    print(f"Deregistered {service_type} service from Redis registry")


class DockerServiceMonitor:
    """Monitor Docker service for shutdown signals and handle cleanup"""

    def __init__(self, service_type: str, redis_url: Optional[str] = None):
        self.service_type = service_type
        self.redis_url = redis_url
        self.running = True

    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, sig, frame):
        """Handle shutdown signals"""
        print(f"Received signal {sig}, shutting down {self.service_type} service...")
        asyncio.create_task(self._cleanup_and_exit())

    async def _cleanup_and_exit(self):
        """Cleanup service registration and exit"""
        try:
            await unregister_service(self.service_type, self.redis_url)
        except Exception as e:
            print(f"Error during cleanup: {e}")
        finally:
            self.running = False
            sys.exit(0)

    async def monitor(self):
        """Monitor service and handle signals"""
        self.setup_signal_handlers()
        print(f"Monitoring {self.service_type} service for shutdown signals...")

        try:
            while self.running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            await self._cleanup_and_exit()


# CLI entry points for docker containers
async def main():
    """Main entry point for docker service registration"""
    if len(sys.argv) < 2:
        print("Usage: python -m gleitzeit.core.docker_service_registry <command> [service_type]")
        print("Commands: register, monitor, unregister")
        sys.exit(1)

    command = sys.argv[1]

    if command == 'register' and len(sys.argv) >= 3:
        service_type = sys.argv[2]
        await register_service(service_type)

    elif command == 'unregister' and len(sys.argv) >= 3:
        service_type = sys.argv[2]
        await unregister_service(service_type)

    elif command == 'monitor' and len(sys.argv) >= 3:
        service_type = sys.argv[2]
        monitor = DockerServiceMonitor(service_type)
        await monitor.monitor()

    else:
        print(f"Invalid command or missing service_type: {command}")
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
```

### 2.3 Update Dockerfile Entrypoints
**Files**: `Dockerfile.api`, `Dockerfile.ui`, `Dockerfile.worker`

**In Dockerfile.api**:
```dockerfile
# Update CMD to use integrated registration
CMD sh -c "\
    python -m gleitzeit.core.docker_service_registry register api && \
    python -m gleitzeit.core.docker_service_registry monitor api & \
    python -m uvicorn gleitzeit.api.main:app --host 0.0.0.0 --port 8000 \
    "
```

**In Dockerfile.ui**:
```dockerfile
# Update CMD to use integrated registration
CMD sh -c "\
    python -m gleitzeit.core.docker_service_registry register ui && \
    python -m gleitzeit.core.docker_service_registry monitor ui & \
    python -m uvicorn gleitzeit.ui.api.app:app --host 0.0.0.0 --port 8004 \
    "
```

**In Dockerfile.worker**:
```dockerfile
# Worker startup will be handled by docker-compose command override
# Example usage in docker-compose.yml:
# command: ["sh", "-c", "python -m gleitzeit.core.docker_service_registry register worker-task && python -m gleitzeit.core.docker_service_registry monitor worker-task & python -m gleitzeit.workers.runner --worker-class TaskExecutionWorker"]
```

## Phase 3: Conditional Service Generation

### 3.1 Update Docker Compose Generation Logic
**File**: `src/gleitzeit/cli/serve_docker.py`

**Changes to `generate_compose_file()` method**:

```python
def generate_compose_file(self, config: dict, api_only=False, workers_only=False, redis_url=None):
    compose = {
        "version": "3.8",
        "networks": {"gleitzeit": {"driver": "bridge"}},
        "volumes": {"logs": {"name": "gleitzeit_logs"}},
        "services": {}
    }

    # External Redis support
    redis_connection = redis_url or "redis://redis:6379"

    # Only create Redis container if using internal Redis
    if not redis_url:
        compose["services"]["redis"] = {
            "image": "redis:7-alpine",
            "container_name": "gleitzeit_redis",
            "ports": ["6379:6379"],
            "networks": ["gleitzeit"],
            "healthcheck": {
                "test": ["CMD", "redis-cli", "ping"],
                "interval": "10s",
                "timeout": "3s",
                "retries": 3
            },
            "restart": "unless-stopped",
            "volumes": ["redis-data:/data"],
            "command": "redis-server --appendonly yes"
        }

    # API/UI services (skip if workers-only)
    if not workers_only:
        compose["services"]["api"] = {
            "build": {"context": ".", "dockerfile": "Dockerfile.api"},
            "container_name": "gleitzeit_api",
            "hostname": "gleitzeit-api",  # Consistent hostname
            "environment": [
                f"REDIS_URL={redis_connection}",
                "SERVICE_TYPE=api",
                "PORT=8000",
                "LOG_LEVEL=INFO",
                "GLEITZEIT_AUTO_LOGIN=true"
            ],
            "ports": [f"{config.get('serve', {}).get('api', {}).get('port', 8000)}:8000"],
            "networks": ["gleitzeit"],
            "restart": "unless-stopped",
            "volumes": [
                "logs:/app/logs",
                "./gleitzeit.yaml:/app/gleitzeit.yaml:ro"
            ]
        }

        # Add depends_on for internal Redis
        if not redis_url:
            compose["services"]["api"]["depends_on"] = {
                "redis": {"condition": "service_healthy"}
            }

        if not no_ui:
            compose["services"]["ui"] = {
                "build": {"context": ".", "dockerfile": "Dockerfile.ui"},
                "container_name": "gleitzeit_ui",
                "hostname": "gleitzeit-ui",
                "environment": [
                    f"REDIS_URL={redis_connection}",
                    "SERVICE_TYPE=ui",
                    "PORT=8004",
                    "API_URL=http://gleitzeit-api:8000"
                ],
                "ports": [f"{config.get('serve', {}).get('ui', {}).get('port', 8004)}:8004"],
                "networks": ["gleitzeit"],
                "restart": "unless-stopped",
                "volumes": [
                    "logs:/app/logs",
                    "./gleitzeit.yaml:/app/gleitzeit.yaml:ro"
                ],
                "depends_on": ["api"]
            }

    # Worker services (skip if api-only)
    if not api_only:
        workers = config.get("workers", [])
        for idx, worker_config in enumerate(workers):
            worker_type = worker_config.get("worker_type", f"worker_{idx}")
            service_name = f"worker-{worker_type}"

            compose["services"][service_name] = {
                "build": {"context": ".", "dockerfile": "Dockerfile.worker"},
                "hostname": f"gleitzeit-{service_name}",
                "environment": [
                    f"REDIS_URL={redis_connection}",
                    f"SERVICE_TYPE={service_name}",
                    "LOG_LEVEL=INFO"
                ],
                "command": [
                    "sh", "-c",
                    f"python -m gleitzeit.core.docker_service_registry register {service_name} && "
                    f"python -m gleitzeit.core.docker_service_registry monitor {service_name} & "
                    f"python -m gleitzeit.workers.runner "
                    f"--worker-class {worker_config.get('worker_class')} "
                    f"--worker-id {service_name} "
                    f"--worker-type {worker_type} "
                    f"--redis-url {redis_connection}"
                ],
                "networks": ["gleitzeit"],
                "restart": "unless-stopped",
                "volumes": [
                    "logs:/app/logs",
                    "./gleitzeit.yaml:/app/gleitzeit.yaml:ro"
                ]
            }

            # Add depends_on for internal Redis
            if not redis_url:
                compose["services"][service_name]["depends_on"] = {
                    "redis": {"condition": "service_healthy"}
                }
```

## Phase 4: Pre-flight Service Discovery

### 4.1 Add Service Discovery Before Container Start
**File**: `src/gleitzeit/cli/serve_docker.py`

**New method in `DockerOrchestrator` class**:

```python
async def check_existing_services(self, redis_url: str, requested_services: list) -> dict:
    """Check existing service registry before starting containers"""
    if not redis_url:
        return {}  # No external Redis, no conflicts possible

    try:
        # Use existing SmartProcessManager instead of creating new registry
        manager = SmartProcessManager(redis_url=redis_url)
        registered_services = await manager.get_registered_services()

        existing = {}
        for service_type in requested_services:
            if service_type in registered_services:
                service_info = registered_services[service_type]
                if await self.is_service_healthy(service_info):
                    existing[service_type] = service_info

        return existing
    except Exception as e:
        click.echo(f"⚠️  Could not check existing services: {e}")
        return {}

async def is_service_healthy(self, service_info: dict) -> bool:
    """Check if registered service is actually healthy"""
    try:
        import aiohttp
        host = service_info.get('host', 'localhost')
        port = service_info.get('port', '8000')

        # Try HTTP health check for API/UI services
        if service_info.get('service_type') in ['api', 'ui']:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://{host}:{port}/health", timeout=2) as resp:
                    return resp.status == 200

        # For workers, check if PID exists (if running in same network)
        if 'pid' in service_info:
            try:
                import psutil
                return psutil.pid_exists(int(service_info['pid']))
            except:
                pass

        return True  # Assume healthy if can't verify
    except Exception:
        return False
```

### 4.2 Update serve_with_docker() Flow
**File**: `src/gleitzeit/cli/serve_docker.py`

```python
async def serve_with_docker(..., redis_url=None, api_only=False, workers_only=False):
    orchestrator = DockerOrchestrator()

    # Check for existing services if using external Redis
    if redis_url:
        requested_services = []
        if not workers_only:
            requested_services.extend(['api', 'ui'])
        if not api_only:
            # Add worker service names based on config
            workers = config.get("workers", [])
            for idx, worker_config in enumerate(workers):
                worker_type = worker_config.get("worker_type", f"worker_{idx}")
                requested_services.append(f"worker-{worker_type}")

        existing_services = await orchestrator.check_existing_services(redis_url, requested_services)

        if existing_services:
            click.echo("🔍 Found existing services in registry:")
            for service, info in existing_services.items():
                click.echo(f"   {service}: {info.get('host')}:{info.get('port')}")

            # Ask user or automatically skip conflicting services
            if not click.confirm("Continue with new containers? (may cause conflicts)"):
                click.echo("Aborting to avoid service conflicts")
                return

    # Generate compose file with discovered conflicts
    orchestrator.generate_compose_file(config, api_only, workers_only, redis_url)
    # ... rest of startup logic
```

## Phase 5: Container Lifecycle Integration

### 5.1 ~~Graceful Shutdown with Deregistration~~ **ALREADY HANDLED**
**REVISION**: Already covered in Phase 2.2 with `docker-deregister.py` script and signal handlers.

## Phase 6: Testing & Validation

### 6.1 Test Scenarios
1. **API-only Docker deployment with external Redis**
   ```bash
   gleitzeit serve --force-docker --api-only --redis-url redis://external:6379
   ```

2. **Workers-only Docker deployment discovering existing API**
   ```bash
   gleitzeit serve --force-docker --workers-only --redis-url redis://external:6379
   ```

3. **Mixed Docker + Native deployments**
   ```bash
   # Native API
   gleitzeit serve --force-native --api-only --redis-url redis://external:6379

   # Docker workers
   gleitzeit serve --force-docker --workers-only --redis-url redis://external:6379
   ```

4. **Service conflict detection and resolution**
5. **Container failure and re-registration**

### 6.2 Integration Tests
**New File**: `tests/test_docker_horizontal_scaling.py`

```python
def test_docker_api_only_with_external_redis():
    """Test Docker API-only mode with external Redis"""

def test_docker_workers_discover_existing_api():
    """Test workers-only finding existing API services"""

def test_service_registry_conflict_detection():
    """Test detection of conflicting services"""

def test_mixed_docker_native_deployments():
    """Test Docker and native services working together"""
```

## Phase 7: Documentation Updates

### 7.1 Update Docker Deployment Documentation
- Add horizontal scaling examples for Docker mode
- Document external Redis configuration
- Add troubleshooting guide for service conflicts

### 7.2 Update CLI Help
- Update `--force-docker` flag documentation
- Add examples combining Docker flags with horizontal scaling

## Implementation Priority

**Critical Path** (implement in order):
1. Phase 1: Function signatures (blocks everything else)
2. Phase 3: Conditional service generation (enables basic functionality)
3. Phase 2: Service registry integration (enables discovery)
4. Phase 4: Pre-flight discovery (enables conflict detection)
5. Phase 6: Testing (validation)
6. Phase 7: Documentation (completeness)

**Estimated Effort**:
- Phase 1+3: ~1-2 days (core functionality using existing infrastructure)
- Phase 2+4: ~2-3 days (integration with existing registry)
- Phase 6-7: ~2-3 days (testing & docs)

## Key Revisions Made

### ✅ **What Changed:**
1. **Removed Phase 2.1**: No new `DockerServiceRegistry` module needed
2. **Reuse Existing Infrastructure**: Use `SmartProcessManager` from `process_manager.py`
3. **Simplified Registration**: Docker containers register in same Redis keys as native services
4. **Unified Service Discovery**: Same `service:registry:*` keys work for both modes
5. **Integrated Package Structure**: Registration functionality included in gleitzeit package as `docker_service_registry.py`

### ✅ **Why This Is Better:**
1. **Code Reuse**: No duplicate registry systems
2. **Unified Experience**: Same service discovery across Docker and native
3. **Less Complexity**: Fewer new components to maintain
4. **Immediate Compatibility**: Docker services appear in existing monitoring/debugging tools
5. **Package Integration**: No external scripts, all functionality within gleitzeit package

### ✅ **Architecture Simplification:**
```
Before (Planned):
Native Services → SmartProcessManager → Redis service:registry:*
Docker Services → DockerServiceRegistry → Redis docker:registry:*

After (Revised):
Native Services → SmartProcessManager → Redis service:registry:*
Docker Services → docker_service_registry.py → SmartProcessManager → Redis service:registry:*  ← Same keys!
```

### ✅ **Integration Approach:**
The Docker service registration is now integrated into the gleitzeit package structure:

```
src/gleitzeit/core/docker_service_registry.py  # New module
├── register_service()        # Async function for service registration
├── unregister_service()      # Async function for cleanup
├── DockerServiceMonitor      # Signal handling class
└── main()                    # CLI entry point

Usage in Docker containers:
python -m gleitzeit.core.docker_service_registry register api
python -m gleitzeit.core.docker_service_registry monitor api
python -m gleitzeit.core.docker_service_registry unregister api
```

This revision achieves the same horizontal scaling goals while leveraging existing, proven infrastructure and maintaining clean package integration rather than relying on external scripts.