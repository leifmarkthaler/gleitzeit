# Gleitzeit Serve & Stop Command Documentation

## Overview

The `gleitzeit serve` and `gleitzeit stop` commands provide unified service management for Gleitzeit, supporting both Docker and native execution modes with mixed handler configurations.

## Architecture

### Service Management Hierarchy

```
gleitzeit serve
    ├── serve_unified.py (Entry point)
    │   ├── Detects execution mode
    │   ├── Checks for mixed handler configs
    │   └── Routes to appropriate implementation
    │
    ├── Docker Mode (serve_docker.py)
    │   └── Uses docker-compose for all services
    │
    └── Native Mode (serve_native_async)
        ├── AsyncServiceManager
        │   ├── ConfigurationManager (loads gleitzeit.yaml)
        │   ├── SmartProcessManager (service registry)
        │   └── Process monitoring & auto-restart
        │
        └── Handler Execution
            ├── Native handlers (subprocess)
            ├── Container handlers (Docker per-task)
            └── Mixed mode support
```

## Gleitzeit Serve Command

### Basic Usage

```bash
# Auto-detect mode (Docker if available, native otherwise)
gleitzeit serve

# Force native mode
gleitzeit serve --force-native

# Force Docker mode (fails if Docker unavailable)
gleitzeit serve --force-docker

# Custom ports
gleitzeit serve --api-port 8080 --ui-port 8081

# Development mode with auto-reload
gleitzeit serve --dev-mode

# Restart existing services
gleitzeit serve --restart
```

### Mode Detection Logic

1. **Check for mixed handler modes** in gleitzeit.yaml
2. **If mixed modes detected**: Use native services with per-handler execution
3. **If uniform modes**:
   - Check Docker availability
   - Use Docker if available and not forced native
   - Fall back to native if Docker unavailable

### Mixed Mode Execution

When handlers have different execution modes configured in gleitzeit.yaml:

```yaml
handlers:
  python:
    execution:
      mode: container  # Runs in Docker containers
    config:
      # handler config...

  ollama:
    execution:
      mode: native     # Runs as subprocess
    config:
      # handler config...
```

The system will:
1. Start services (API, UI, workers) as native processes
2. Each handler executes tasks according to its configuration
3. Python handler creates Docker containers per task
4. Other handlers run as subprocesses

### Service Registry

Services are registered in Redis for persistence across CLI invocations:

```
Redis Keys:
service:registry:api          -> {pid, port, host, started_at}
service:registry:ui           -> {pid, port, host, started_at}
service:registry:worker_*     -> {pid, port, host, started_at}
```

### Service Detection & Reuse

When starting services:
1. Check Redis for existing service registrations
2. Validate if registered services are still healthy (PID exists)
3. Attach to healthy services instead of starting new ones
4. Clean up stale registrations for dead services

### Auto-Restart Behavior

The AsyncServiceManager includes a monitor loop that:
1. Checks service health every 5 seconds
2. Automatically restarts failed services (up to 3 attempts)
3. Maintains service availability during crashes
4. Tracks restart attempts to prevent infinite loops

## Gleitzeit Stop Command

### Basic Usage

```bash
# Stop services (will auto-restart if monitor running)
gleitzeit stop

# Stop ALL instances including monitor loops
gleitzeit stop --all

# Force kill processes
gleitzeit stop --force

# Custom timeout for graceful shutdown
gleitzeit stop --timeout 30
```

### Stop Modes

#### Standard Stop (`gleitzeit stop`)
- Terminates service processes (API, UI, workers)
- Services will auto-restart if a monitor loop is running
- Useful for restarting services without stopping the monitor

#### Stop All (`gleitzeit stop --all`)
- Stops all service processes
- **Also stops monitor loops** (gleitzeit serve instances)
- Clears Redis service registry
- Prevents auto-restart behavior
- Complete shutdown of all Gleitzeit instances

#### Force Stop (`gleitzeit stop --force`)
- Immediately kills processes (SIGKILL)
- No graceful shutdown period
- Use when services are unresponsive

### Process Detection

The stop command identifies processes by:
1. Scanning for Python processes with 'gleitzeit' in command line
2. Matching specific module patterns:
   - `gleitzeit.api.main` (API server)
   - `gleitzeit.ui.api.app` (UI server)
   - `gleitzeit.workers.runner` (Workers)
   - `gleitzeit serve` (Monitor loops, only with --all)

## Configuration Flow

### Full Configuration Propagation

```
gleitzeit.yaml
    ↓
ConfigurationManager.load_config()
    ↓
AsyncServiceManager (stores full handler configs)
    ↓
Redis (handler:config:* keys with execution section)
    ↓
Workers (receive full config via --config-key)
    ↓
Handlers (can read execution.mode)
```

### Handler Configuration Structure

Handlers receive complete configuration including execution section:

```python
{
    'execution': {
        'mode': 'container',  # or 'native', 'subprocess', etc.
        'docker_image': 'python:3.9'
    },
    'config': {
        # handler-specific configuration
    }
}
```

## Implementation Details

### Key Components

#### AsyncServiceManager (`async_process_manager.py`)
- Manages service lifecycle
- Handles configuration loading via ConfigurationManager
- Stores full handler configs in Redis
- Implements health monitoring and auto-restart
- Tracks attached vs started services

#### SmartProcessManager (`process_manager.py`)
- Manages service registry in Redis
- Provides instance identity for distributed systems
- Implements service discovery methods
- Uses Redis SCAN for efficient key iteration

#### Handler Execution Modes

Each handler can specify its execution mode:

1. **Native Mode** (`mode: native`)
   - Runs directly in worker process
   - Lowest overhead, fastest execution
   - Example: Timer, Signal handlers

2. **Subprocess Mode** (`mode: subprocess`)
   - Spawns new process per task
   - Process isolation
   - Example: File handler

3. **Container Mode** (`mode: container`)
   - Creates Docker container per task
   - Full isolation and environment control
   - Example: Python handler with dependencies

### Service Health Checking

```python
def is_service_healthy(pid):
    """Check if a service process is healthy"""
    if not psutil.pid_exists(pid):
        return False
    proc = psutil.Process(pid)
    return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
```

### Attached vs Started Services

The system tracks whether services were:
- **Started**: Created by this instance (will unregister on shutdown)
- **Attached**: Connected to existing services (won't unregister)

This prevents instances from unregistering services they didn't start.

## Error Handling

### Port Conflicts
- Detected existing services automatically reused
- Clear error messages if ports unavailable
- Use `--restart` flag to force restart

### Docker Availability
- Graceful fallback to native mode
- Clear messaging about Docker status
- Container handlers fall back to subprocess if Docker unavailable

### Service Failures
- Automatic restart with exponential backoff
- Maximum 3 restart attempts
- Clear logging of failure reasons

## Best Practices

### Development Workflow

```bash
# Start services with auto-reload for development
gleitzeit serve --dev-mode

# Make code changes...

# Restart just the services (keeps monitor running)
gleitzeit stop

# Complete shutdown when done
gleitzeit stop --all
```

### Production Deployment

```bash
# Use Docker mode for production (if available)
gleitzeit serve --force-docker

# Or ensure specific ports
gleitzeit serve --api-port 8000 --ui-port 8004

# Graceful shutdown
gleitzeit stop --all --timeout 30
```

### Mixed Mode Configuration

```yaml
# gleitzeit.yaml
handlers:
  # Secure/isolated handlers use containers
  python:
    execution:
      mode: container
      docker_image: custom-python:latest

  # Performance-critical handlers run native
  timer:
    execution:
      mode: native

  # Default handlers use subprocess
  file:
    execution:
      mode: subprocess
```

## Debugging

### Check Service Status

```bash
# View running services
redis-cli keys "service:registry:*"

# Check specific service
redis-cli hgetall "service:registry:api"

# Monitor logs
tail -f logs/api_*.log
tail -f logs/worker_*.log
```

### Common Issues

1. **"Port already in use"**
   - Previous instance still running
   - Solution: `gleitzeit stop --all` or `gleitzeit serve --restart`

2. **Services keep restarting**
   - Monitor loop is running
   - Solution: Use `gleitzeit stop --all` to stop everything

3. **Handler not using configured mode**
   - Check handler receives full config
   - Verify gleitzeit.yaml syntax
   - Check Redis for stored configs: `redis-cli get "handler:config:python/v1"`

## Future Enhancements

1. **Multi-instance coordination**
   - Instance roles (coordinator, worker)
   - Distributed service registry
   - Cross-instance health monitoring

2. **Enhanced monitoring**
   - Prometheus metrics export
   - Real-time service dashboards
   - Performance profiling per handler

3. **Dynamic scaling**
   - Auto-scale workers based on load
   - Container pool management
   - Resource limits per handler

## Summary

The `gleitzeit serve` and `gleitzeit stop` commands provide a robust, unified service management system that:

- **Automatically detects** the best execution mode
- **Supports mixed configurations** with per-handler execution modes
- **Maintains service availability** through auto-restart
- **Enables clean shutdowns** with the `--all` flag
- **Reuses existing services** across CLI invocations
- **Provides clear feedback** about service status

This architecture enables flexible deployment scenarios from development to production, supporting both containerized and native execution based on requirements and available infrastructure.