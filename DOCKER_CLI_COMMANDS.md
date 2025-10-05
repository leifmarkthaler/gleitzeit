# Gleitzeit Docker-Integrated CLI Commands

## Overview

Gleitzeit 0.0.7 provides unified CLI commands that work seamlessly with both Docker and native modes. Commands automatically detect which mode is running and apply the appropriate operations.

## Mode Detection

All commands automatically detect the running mode:
- **Docker Mode**: When services are running via `docker-compose`
- **Native Mode**: When services are running as Python processes
- **Auto-Detection**: Commands adapt their behavior based on the detected mode

## Commands

### 1. `gleitzeit serve`

Start Gleitzeit services with automatic Docker detection.

```bash
# Auto-detect and use Docker if available
gleitzeit serve

# Force Docker mode
gleitzeit serve --force-docker

# Force native mode
gleitzeit serve --force-native

# Restart existing services
gleitzeit serve --restart

# Build Docker images before starting
gleitzeit serve --build
```

**Features:**
- Automatic Docker detection with fallback to native mode
- Builds and starts all required services
- Health checks for service readiness
- Auto-restart capability for crashed services

---

### 2. `gleitzeit ps`

List running services with detailed status information.

```bash
# Show running services (auto-detects mode)
gleitzeit ps

# Show all services including stopped
gleitzeit ps --all

# Different output formats
gleitzeit ps --format table    # Detailed table (default)
gleitzeit ps --format simple   # Simple list
gleitzeit ps --format json     # JSON output

# Group by service type
gleitzeit ps --services
```

**Docker Mode Output:**
```
🐳 Docker Services:
--------------------------------------------------------------------------------
NAME                    IMAGE                 STATUS              PORTS
gleitzeit_api          gleitzeit007-api      Up 12 minutes       0.0.0.0:8000->8000/tcp
gleitzeit_ui           gleitzeit007-ui       Up 12 minutes       0.0.0.0:8004->8004/tcp
worker-task-execution  gleitzeit007-worker   Up 12 minutes
worker-dependency      gleitzeit007-worker   Up 12 minutes
```

**Native Mode Output:**
```
🔧 Native Processes:
--------------------------------------------------------------------------------
PID        Service                   Status       Memory (MB)  Started
-----------------------------------------------------------------------------------------
75032      API                       running      60.9         2025-09-27 23:14:40
75049      UI                        running      66.0         2025-09-27 23:14:42
75050      Worker (task_execution)   running      51.0         2025-09-27 23:14:43
75053      Worker (dependency)       running      41.7         2025-09-27 23:14:43

Summary: 4 running, 0 stopped | Total memory: 219.6 MB
```

---

### 3. `gleitzeit logs`

View service logs from Docker containers or native processes.

```bash
# View all logs
gleitzeit logs

# View specific service logs
gleitzeit logs api
gleitzeit logs worker_task_execution

# Follow log output
gleitzeit logs -f
gleitzeit logs api -f

# Show last N lines
gleitzeit logs -n 50
gleitzeit logs api -n 100

# Show logs since timestamp (Docker only)
gleitzeit logs --since 10m    # Last 10 minutes
gleitzeit logs --since 1h     # Last hour
gleitzeit logs --since 2023-01-01

# Show timestamps
gleitzeit logs -t
```

**Service Names:**
- `api` - API service
- `ui` - UI service
- `redis` - Redis service (Docker only)
- `worker_task_execution` - Task execution workers
- `worker_dependency` - Dependency workers
- `worker_workflow_loader` - Workflow loader workers
- `worker_workflow_submission` - Workflow submission workers

---

### 4. `gleitzeit scale`

Scale worker services (Docker mode only).

```bash
# Scale specific worker type
gleitzeit scale task_execution=3
gleitzeit scale dependency=2
gleitzeit scale workflow_loader=1

# Scale all workers to same count
gleitzeit scale all=2

# Stop all workers
gleitzeit scale all=0

# Dry run to preview changes
gleitzeit scale --dry-run task_execution=5
```

**Supported Worker Types:**
- `task_execution` - Task execution workers
- `dependency` - Dependency resolution workers
- `workflow_loader` - Workflow loading workers
- `workflow_submission` - Workflow submission workers
- `timer` - Timer/scheduler workers
- `retry` - Retry handler workers
- `all` - All worker types

**Notes:**
- Currently only supported in Docker mode
- For services with multiple pre-defined instances in docker-compose, manual editing is required
- Native mode scaling requires restart with different configuration

**Example:**
```bash
$ gleitzeit scale dependency=2
📊 Scaling worker-dependency to 2 instances...
✅ Successfully scaled worker-dependency to 2 instances

📋 Current status:
   NAME                               STATUS
   gleitzeit007-worker-dependency-1   Up 7 minutes (healthy)
   gleitzeit007-worker-dependency-2   Up Less than a second (health: starting)
```

---

### 5. `gleitzeit stop`

Stop all running services intelligently.

```bash
# Gracefully stop services
gleitzeit stop

# Force stop all processes
gleitzeit stop --force

# Custom timeout for graceful shutdown
gleitzeit stop --timeout 30
```

**Features:**
- Auto-detects running mode (Docker or native)
- Graceful shutdown with configurable timeout
- Force stop option for immediate termination
- Cleans up PID files in native mode

**Docker Mode:**
- Executes `docker-compose down` with timeout
- Falls back to `docker-compose kill` if needed

**Native Mode:**
- Sends SIGTERM for graceful shutdown
- Waits for processes to exit
- Force kills remaining processes after timeout
- Stops processes on known ports (8000, 8004)

---

### 6. `gleitzeit clean`

Clean up Gleitzeit resources and artifacts.

```bash
# Remove specific resources
gleitzeit clean --logs        # Remove log files
gleitzeit clean --volumes     # Remove Docker volumes
gleitzeit clean --images      # Remove Docker images
gleitzeit clean --cache       # Remove cache files

# Remove everything
gleitzeit clean --all

# Force removal without confirmation
gleitzeit clean --all --force

# Combine options
gleitzeit clean --logs --cache
```

**Cleaned Resources:**
- **Logs**: All files in `logs/` directory
- **Volumes**: Docker volumes with gleitzeit prefix
- **Images**: Docker images built for gleitzeit
- **Cache**: Python cache (`__pycache__`, `.pytest_cache`, `.pyc` files)

**Safety Features:**
- Confirmation prompt before deletion (unless `--force`)
- Checks if services are running before cleaning
- Reports what will be cleaned before proceeding

---

## Mode-Specific Behavior

### Docker Mode Features

When running in Docker mode:
- Services run in isolated containers
- Networking handled by Docker
- Logs available via `docker-compose logs`
- Scaling supported via `docker-compose scale`
- Health checks built into containers
- Automatic restart on failure

### Native Mode Features

When running in native mode:
- Services run as Python processes
- Direct process management via asyncio
- Logs written to `logs/` directory
- Process monitoring via psutil
- Auto-restart capability
- Resource usage tracking

---

## Usage Examples

### Complete Workflow - Docker Mode

```bash
# 1. Start services with Docker
gleitzeit serve --force-docker

# 2. Check status
gleitzeit ps

# 3. Scale workers
gleitzeit scale task_execution=3
gleitzeit scale dependency=2

# 4. View logs
gleitzeit logs -f api
gleitzeit logs worker_task_execution -n 100

# 5. Stop services
gleitzeit stop

# 6. Clean up
gleitzeit clean --volumes --logs
```

### Complete Workflow - Native Mode

```bash
# 1. Start services natively
gleitzeit serve --force-native

# 2. Check status
gleitzeit ps --services

# 3. View logs
gleitzeit logs api -f
gleitzeit logs -n 50

# 4. Stop services
gleitzeit stop

# 5. Clean up
gleitzeit clean --logs --cache
```

### Auto-Detection Workflow

```bash
# Let Gleitzeit choose the best mode
gleitzeit serve

# All commands work regardless of mode
gleitzeit ps
gleitzeit logs api
gleitzeit stop
gleitzeit clean --all
```

---

## Troubleshooting

### Issue: Commands don't detect Docker mode

**Solution:**
- Ensure Docker and docker-compose are installed
- Check if `docker-compose-proper.yml` exists
- Verify Docker daemon is running: `docker ps`

### Issue: Scale command not working

**Solution:**
- Scale command only works in Docker mode
- For services with multiple pre-defined instances, edit docker-compose.yml
- In native mode, modify gleitzeit.yaml and restart

### Issue: Logs not showing

**Docker Mode:**
- Check container is running: `docker-compose ps`
- Use `docker-compose logs <service>` directly

**Native Mode:**
- Check `logs/` directory exists
- Verify processes are running: `gleitzeit ps`
- Look for `*.log` files in logs directory

### Issue: Stop command leaves processes running

**Solution:**
- Use `gleitzeit stop --force` for immediate termination
- Check for zombie processes: `ps aux | grep gleitzeit`
- Manually kill stuck processes: `pkill -f gleitzeit`

---

## Configuration

### Docker Configuration

Docker mode uses `docker-compose-proper.yml` for service definitions. Key configurations:

```yaml
services:
  worker-task-execution:
    scale: 2  # Number of instances
    environment:
      - REDIS_URL=redis://redis:6379
      - REDIS_CLUSTER_NODES=redis:6379
```

### Native Configuration

Native mode uses `gleitzeit.yaml` for configuration:

```yaml
workers:
  task_execution:
    count: 2
    redis_url: redis://localhost:6379
```

---

## Best Practices

1. **Use Auto-Detection**: Let Gleitzeit choose the appropriate mode unless you have specific requirements

2. **Monitor Services**: Regularly check service status with `gleitzeit ps`

3. **Clean Logs**: Periodically clean old logs with `gleitzeit clean --logs`

4. **Graceful Shutdown**: Always try graceful stop before force stopping

5. **Scale Gradually**: When scaling workers, increase counts gradually and monitor performance

6. **Check Logs**: Use `gleitzeit logs -f` to monitor services during development

---

## Command Reference Summary

| Command | Description | Mode Support |
|---------|-------------|--------------|
| `serve` | Start services | Both |
| `ps` | List services | Both |
| `logs` | View logs | Both |
| `scale` | Scale workers | Docker only |
| `stop` | Stop services | Both |
| `clean` | Clean resources | Both |

### Quick Options Reference

| Command | Common Options |
|---------|---------------|
| `serve` | `--force-docker`, `--force-native`, `--restart`, `--build` |
| `ps` | `--all`, `--format`, `--services` |
| `logs` | `-f`, `-n`, `--since`, `-t` |
| `scale` | `service=count`, `--dry-run` |
| `stop` | `--force`, `--timeout` |
| `clean` | `--volumes`, `--images`, `--logs`, `--cache`, `--all`, `--force` |