# Docker Horizontal Scaling Implementation Plan

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

## Phase 2: Service Discovery Infrastructure

### 2.1 Create Docker Service Registry Module
**File**: `src/gleitzeit/core/docker_registry.py` (NEW)

**Purpose**: Handle container service registration and discovery

```python
class DockerServiceRegistry:
    def __init__(self, redis_url: str):
        self.redis_url = redis_url

    async def register_service(self, service_type: str, container_info: dict):
        """Register Docker container in Redis service registry"""

    async def discover_services(self) -> dict:
        """Find existing services in registry"""

    async def check_service_conflicts(self, requested_services: list) -> list:
        """Check for service conflicts before starting containers"""

    def generate_container_hostname(self, service_type: str) -> str:
        """Generate consistent hostnames for service discovery"""
```

### 2.2 Update Dockerfile Entrypoints
**Files**: `Dockerfile.api`, `Dockerfile.ui`, `Dockerfile.worker`

**Purpose**: Add service registration on container startup

```dockerfile
# In Dockerfile.api - add registration script
COPY scripts/docker-register.py /app/scripts/
CMD ["python", "/app/scripts/docker-register.py", "api", "&&", \
     "python", "-m", "uvicorn", "gleitzeit.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**New File**: `scripts/docker-register.py`
```python
#!/usr/bin/env python3
"""Register Docker service in Redis registry on startup"""
import os
import sys
import redis
import socket
from datetime import datetime

def register_service(service_type: str):
    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
    hostname = socket.gethostname()

    # Register service in Redis
    r = redis.Redis.from_url(redis_url)
    r.hset(f'service:registry:{service_type}', mapping={
        'host': hostname,
        'port': os.getenv('PORT', '8000'),
        'container_id': os.getenv('HOSTNAME'),
        'started_at': datetime.now().isoformat(),
        'mode': 'docker'
    })

if __name__ == '__main__':
    register_service(sys.argv[1])
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
            # ... existing Redis config
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
                # ... other env vars
            ],
            # ... existing API config
        }

        if not no_ui:
            compose["services"]["ui"] = {
                # Similar pattern for UI
            }

    # Worker services (skip if api-only)
    if not api_only:
        workers = config.get("workers", [])
        for idx, worker_config in enumerate(workers):
            # Generate worker services with Redis registration
```

## Phase 4: Pre-flight Service Discovery

### 4.1 Add Service Discovery Before Container Start
**File**: `src/gleitzeit/cli/serve_docker.py`

**New method in `DockerOrchestrator` class**:

```python
async def check_existing_services(self, redis_url: str, requested_services: list) -> dict:
    """Check Redis for existing services before starting containers"""
    if not redis_url:
        return {}  # No external Redis, no conflicts possible

    try:
        r = redis.Redis.from_url(redis_url)
        existing = {}

        for service_type in requested_services:
            registry_key = f"service:registry:{service_type}"
            if r.exists(registry_key):
                service_info = r.hgetall(registry_key)
                if self.is_service_healthy(service_info):
                    existing[service_type] = service_info

        return existing
    except Exception as e:
        click.echo(f"⚠️  Could not check existing services: {e}")
        return {}

def is_service_healthy(self, service_info: dict) -> bool:
    """Check if registered service is actually healthy"""
    # Implement health check logic (HTTP ping, etc.)
    pass
```

### 4.2 Update serve_with_docker() Flow
**File**: `src/gleitzeit/cli/serve_docker.py`

```python
def serve_with_docker(..., redis_url=None, api_only=False, workers_only=False):
    orchestrator = DockerOrchestrator()

    # Check for existing services if using external Redis
    if redis_url:
        requested_services = []
        if not workers_only:
            requested_services.extend(['api', 'ui'])
        if not api_only:
            requested_services.extend(['worker_task', 'worker_workflow'])

        existing_services = await orchestrator.check_existing_services(redis_url, requested_services)

        if existing_services:
            click.echo("🔍 Found existing services:")
            for service, info in existing_services.items():
                click.echo(f"   {service}: {info['host']}:{info['port']}")

            # Ask user or automatically skip conflicting services
            if not click.confirm("Continue with new containers?"):
                return

    # Generate compose file with discovered conflicts
    orchestrator.generate_compose_file(config, api_only, workers_only, redis_url)
    # ... rest of startup logic
```

## Phase 5: Container Lifecycle Integration

### 5.1 Add Graceful Shutdown with Deregistration
**Files**: `Dockerfile.api`, `Dockerfile.ui`, `Dockerfile.worker`

```dockerfile
# Add cleanup script
COPY scripts/docker-deregister.py /app/scripts/
# Use init system or signal handlers for cleanup
```

**New File**: `scripts/docker-deregister.py`
```python
#!/usr/bin/env python3
"""Deregister Docker service from Redis on shutdown"""
import os
import redis
import signal
import sys

def cleanup_service(service_type: str):
    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
    r = redis.Redis.from_url(redis_url)
    r.delete(f'service:registry:{service_type}')

def signal_handler(sig, frame):
    cleanup_service(os.getenv('SERVICE_TYPE', 'unknown'))
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)
```

## Phase 6: Testing & Validation

### 6.1 Test Scenarios
1. **API-only Docker deployment with external Redis**
2. **Workers-only Docker deployment discovering existing API**
3. **Mixed Docker + Native deployments**
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
3. Phase 2: Service registry infrastructure (enables discovery)
4. Phase 4: Pre-flight discovery (enables conflict detection)
5. Phase 5: Lifecycle management (production readiness)
6. Phase 6: Testing (validation)
7. Phase 7: Documentation (completeness)

**Estimated Effort**:
- Phase 1-3: ~2-3 days (core functionality)
- Phase 4-5: ~3-4 days (advanced features)
- Phase 6-7: ~2-3 days (testing & docs)

## Summary

This plan achieves **feature parity** between Docker and native horizontal scaling modes while maintaining backward compatibility.

### Current State
- ✅ Native horizontal scaling working (stateless, Redis-based discovery)
- ❌ Docker mode missing horizontal scaling support
- ❌ Docker containers don't register in service registry
- ❌ No cross-container service discovery

### After Implementation
- ✅ Unified CLI interface for both Docker and native modes
- ✅ Docker containers register in Redis service registry
- ✅ Cross-deployment service discovery (Docker ↔ Native)
- ✅ External Redis support for distributed deployments
- ✅ Conflict detection and resolution
- ✅ Graceful container lifecycle management

### Key Benefits
1. **Consistent Experience**: Same CLI flags work for both deployment modes
2. **True Statelessness**: Docker containers coordinate via Redis registry
3. **Mixed Deployments**: Docker and native instances can coexist
4. **Production Ready**: Proper service discovery and conflict handling
5. **Backward Compatible**: Existing Docker usage continues to work

This implementation enables Docker-based horizontal scaling that matches the capabilities and user experience of the native mode.