# Docker Horizontal Scaling Documentation

## Overview

Gleitzeit now supports **Docker horizontal scaling** with stateless instances that can be deployed across multiple machines or containers. This enables distributed Docker deployments for high availability and performance scaling, complementing the existing native horizontal scaling capabilities.

## Architecture

### Unified Configuration Approach

- **Single Configuration File**: All settings come from `gleitzeit.yaml` - no separate Docker-specific configs
- **Stateless Design**: All state coordination via Redis service registry
- **Service Discovery**: Docker containers register in the same Redis registry as native services
- **Mixed Deployments**: Docker and native instances can coexist and discover each other

### Service Registry Integration

Docker containers integrate with the existing service registry infrastructure:
```
Redis Keys (Shared with Native):
service:registry:api          -> {pid, port, host, started_at, mode: 'docker'}
service:registry:ui           -> {pid, port, host, started_at, mode: 'docker'}
service:registry:worker-*     -> {pid, port, host, started_at, mode: 'docker'}
```

### Docker Service Registration Module

**File**: `src/gleitzeit/core/docker_service_registry.py`

Provides integrated service registration for Docker containers:
- `register_service()`: Register container in Redis on startup
- `unregister_service()`: Clean up registry on shutdown
- `DockerServiceMonitor`: Handle graceful shutdown signals
- CLI entry points: `python -m gleitzeit.core.docker_service_registry`

## CLI Options

### Docker Horizontal Scaling Flags

```bash
# Deployment modes
--api-only        # Run only API/UI services, no workers
--workers-only    # Run only workers, no API/UI

# External Redis
--redis-url       # External Redis URL (also via REDIS_URL env var)

# Remote configuration
--config-url      # Remote config URL (also via CONFIG_URL env var)

# Force Docker mode
--force-docker    # Force Docker deployment (fail if unavailable)
```

### Usage Examples

```bash
# API-only Docker deployment
gleitzeit serve --force-docker --api-only

# Workers-only Docker deployment
gleitzeit serve --force-docker --workers-only

# External Redis coordination
gleitzeit serve --force-docker --api-only --redis-url redis://shared-redis:6379
gleitzeit serve --force-docker --workers-only --redis-url redis://shared-redis:6379

# Remote configuration
gleitzeit serve --force-docker --config-url https://config.company.com/gleitzeit.yaml

# Environment variable support
REDIS_URL=redis://cluster:6379 gleitzeit serve --force-docker --workers-only
CONFIG_URL=https://config.company.com/gleitzeit.yaml gleitzeit serve --force-docker
```

## Configuration

### Port Configuration from gleitzeit.yaml

Docker containers read ports from configuration instead of hardcoding:

```yaml
# gleitzeit.yaml
serve:
  api:
    port: 8000
  ui:
    port: 8004

workers:
  - worker_type: task_execution
    worker_class: TaskExecutionWorker
    count: 2
  - worker_type: workflow_loader
    worker_class: WorkflowLoaderWorker
    count: 1
```

### Docker Compose Generation

The system generates `docker-compose-proper.yml` with conditional services:

**API-Only Mode** (`--api-only`):
- ✅ Redis (if no external `--redis-url`)
- ✅ API service
- ✅ UI service (if enabled)
- ❌ Worker services (skipped)

**Workers-Only Mode** (`--workers-only`):
- ✅ Redis (if no external `--redis-url`)
- ❌ API/UI services (skipped)
- ✅ Worker services

**External Redis Mode** (`--redis-url`):
- ❌ Redis container (uses external)
- Services connect to external Redis URL

### Service Environment Variables

Docker containers receive these environment variables:
```bash
REDIS_URL=redis://redis:6379        # or external URL
SERVICE_TYPE=api                    # for registry identification
PORT=8000                           # from gleitzeit.yaml
LOG_LEVEL=INFO
```

## Deployment Scenarios

### Scenario 1: Simple Docker Horizontal Scaling

**Machine 1** (API/UI):
```bash
gleitzeit serve --force-docker --api-only --redis-url redis://shared-redis:6379
```

**Machine 2** (Workers):
```bash
gleitzeit serve --force-docker --workers-only --redis-url redis://shared-redis:6379
```

### Scenario 2: Mixed Docker + Native Deployments

**Machine 1** (Native API):
```bash
gleitzeit serve --force-native --api-only --redis-url redis://shared-redis:6379
```

**Machine 2** (Docker Workers):
```bash
gleitzeit serve --force-docker --workers-only --redis-url redis://shared-redis:6379
```

### Scenario 3: Kubernetes Deployment

**API Deployment**:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gleitzeit-api
spec:
  replicas: 2
  template:
    spec:
      containers:
      - name: gleitzeit-api
        image: gleitzeit:latest
        command: ["gleitzeit", "serve", "--force-docker", "--api-only"]
        env:
        - name: REDIS_URL
          value: "redis://redis-service:6379"
        - name: CONFIG_URL
          value: "https://config.company.com/gleitzeit.yaml"
        ports:
        - containerPort: 8000
        - containerPort: 8004
```

**Workers Deployment**:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gleitzeit-workers
spec:
  replicas: 5
  template:
    spec:
      containers:
      - name: gleitzeit-workers
        image: gleitzeit:latest
        command: ["gleitzeit", "serve", "--force-docker", "--workers-only"]
        env:
        - name: REDIS_URL
          value: "redis://redis-service:6379"
        - name: CONFIG_URL
          value: "https://config.company.com/gleitzeit.yaml"
```

### Scenario 4: Docker Compose Stack

```yaml
version: '3.8'
services:
  redis:
    image: redis:alpine
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data

  gleitzeit-api:
    image: gleitzeit:latest
    command: gleitzeit serve --force-docker --api-only
    environment:
      - REDIS_URL=redis://redis:6379
    ports:
      - "8000:8000"
      - "8004:8004"
    depends_on:
      - redis
    volumes:
      - ./gleitzeit.yaml:/app/gleitzeit.yaml:ro

  gleitzeit-workers:
    image: gleitzeit:latest
    command: gleitzeit serve --force-docker --workers-only
    environment:
      - REDIS_URL=redis://redis:6379
    deploy:
      replicas: 3
    depends_on:
      - redis
    volumes:
      - ./gleitzeit.yaml:/app/gleitzeit.yaml:ro

volumes:
  redis-data:
```

## Service Discovery Process

### Docker Container Startup

1. **Load Configuration**: From local `gleitzeit.yaml` or remote URL
2. **Initialize Redis Connection**: Using configured or default Redis URL
3. **Generate Docker Compose**: Conditional services based on flags
4. **Container Registration**: Each container registers itself in Redis
5. **Service Attachment**: Containers discover and connect to existing services

### Docker Service Registration

When Docker containers start, they use the integrated registration module:

```bash
# Inside Docker container (automatic)
python -m gleitzeit.core.docker_service_registry register api
python -m gleitzeit.core.docker_service_registry monitor api &

# Manual usage
python -m gleitzeit.core.docker_service_registry register worker-task
python -m gleitzeit.core.docker_service_registry unregister api
```

### Service Registry Data

Docker containers register with these details:
```python
{
    'host': 'gleitzeit-api',              # Docker hostname
    'port': '8000',                       # From gleitzeit.yaml
    'container_id': 'abc123',             # Docker container ID
    'started_at': '2024-01-15T10:30:00',  # ISO timestamp
    'mode': 'docker',                     # Deployment mode
    'pid': 1                              # Container PID
}
```

## Monitoring and Management

### Check Service Status

```bash
# View all registered services (Docker + Native)
redis-cli keys "service:registry:*"

# Check specific Docker service
redis-cli hgetall "service:registry:api"

# Monitor Docker container logs
docker-compose -f docker-compose-proper.yml logs -f

# Check container status
docker-compose -f docker-compose-proper.yml ps
```

### Stop Services

```bash
# Stop Docker services
docker-compose -f docker-compose-proper.yml down

# Stop with cleanup
docker-compose -f docker-compose-proper.yml down -v

# View service logs
docker-compose -f docker-compose-proper.yml logs api
docker-compose -f docker-compose-proper.yml logs worker-task-execution-1
```

## Network Requirements

### Ports

All ports are configured via `gleitzeit.yaml`:
- **API**: Default 8000 (configurable via `serve.api.port`)
- **UI**: Default 8004 (configurable via `serve.ui.port`)
- **Redis**: Default 6379 (configurable via `--redis-url`)

### Connectivity

- All Docker containers must reach the Redis server
- API/UI containers must be accessible to clients
- Workers need network access for handler execution
- Containers use consistent hostnames for service discovery

### Docker Networks

Generated compose files create a `gleitzeit` network:
```yaml
networks:
  gleitzeit:
    driver: bridge
    name: gleitzeit_network
```

## Implementation Details

### Key Components

#### Updated serve_docker.py
- Added horizontal scaling parameters to `serve_with_docker()`
- Updated `generate_compose_file()` for conditional services
- External Redis URL support
- Port configuration from `gleitzeit.yaml`

#### Updated serve_unified.py
- Passes horizontal scaling flags to Docker mode
- Unified CLI interface across Docker and native modes

#### docker_service_registry.py (New)
- Integrated into `src/gleitzeit/core/`
- Uses existing `SmartProcessManager`
- Async service registration/deregistration
- Signal handling for graceful shutdown
- CLI entry points for container usage

### Generated Docker Compose Structure

```yaml
version: '3.8'
networks:
  gleitzeit:
    driver: bridge
    name: gleitzeit_network
volumes:
  redis-data:
    name: gleitzeit_redis_data
  logs:
    name: gleitzeit_logs

services:
  # Conditional Redis (only if no --redis-url)
  redis:
    image: redis:7-alpine
    hostname: redis
    # ... config

  # Conditional API (only if not --workers-only)
  api:
    build:
      dockerfile: Dockerfile.api
    hostname: gleitzeit-api
    environment:
      - REDIS_URL=redis://redis:6379
      - SERVICE_TYPE=api
      - PORT=8000
    # ... config

  # Conditional UI (only if not --workers-only and UI enabled)
  ui:
    build:
      dockerfile: Dockerfile.ui
    hostname: gleitzeit-ui
    environment:
      - REDIS_URL=redis://redis:6379
      - SERVICE_TYPE=ui
      - PORT=8004
    # ... config

  # Conditional Workers (only if not --api-only)
  worker-task-execution-1:
    build:
      dockerfile: Dockerfile.worker
    hostname: gleitzeit-worker-task-execution-1
    command:
      - python -m gleitzeit.workers.runner
      - --worker-class TaskExecutionWorker
      - --redis-url redis://redis:6379
    environment:
      - REDIS_URL=redis://redis:6379
      - SERVICE_TYPE=worker-task-execution-1
    # ... config
```

## Error Handling

### Docker Availability

```bash
# If Docker not available
❌ Docker is not available or not running
Please ensure Docker is installed and running
Visit https://docs.docker.com/get-docker/ for installation

# Automatic fallback disabled when using --force-docker
```

### Redis Connection Issues

```bash
# Container startup will fail if Redis unreachable
# Check Redis connectivity:
docker run --rm redis:alpine redis-cli -h redis-server -p 6379 ping

# Verify environment variables
docker-compose -f docker-compose-proper.yml config
```

### Service Discovery Issues

```bash
# Check service registry
redis-cli keys "service:registry:*"

# Verify Docker network connectivity
docker network ls
docker network inspect gleitzeit_network

# Check container hostnames
docker-compose -f docker-compose-proper.yml exec api hostname
```

## Security Considerations

### Redis Security

- Use Redis AUTH: `--redis-url redis://user:password@host:port`
- Enable TLS: `--redis-url rediss://host:port`
- Network isolation for Redis access
- Container network segmentation

### Configuration Security

- Secure remote configuration URLs (HTTPS)
- Use environment variables for sensitive data
- Avoid secrets in `gleitzeit.yaml`
- Regular security updates for base images

### Container Security

- Use specific image versions, not `:latest`
- Regular base image security updates
- Network policies for container communication
- Resource limits in production deployments

## Troubleshooting

### Common Issues

**Port Already in Use**:
```bash
# Check what's using the port
lsof -i :8000

# Or use Docker port mapping
# In gleitzeit.yaml: serve.api.port: 8080
```

**Container Registration Failed**:
```bash
# Check container logs
docker-compose -f docker-compose-proper.yml logs api

# Verify Redis connectivity from container
docker-compose -f docker-compose-proper.yml exec api redis-cli -u $REDIS_URL ping

# Check service registration
redis-cli hgetall "service:registry:api"
```

**Service Discovery Not Working**:
```bash
# Verify all services are registered
redis-cli keys "service:registry:*"

# Check Docker network
docker network inspect gleitzeit_network

# Verify container hostnames
docker-compose -f docker-compose-proper.yml ps --format table
```

**Configuration Loading Failed**:
```bash
# Test remote config URL
curl https://config.company.com/gleitzeit.yaml

# Check config file mount
docker-compose -f docker-compose-proper.yml exec api cat /app/gleitzeit.yaml
```

### Debug Mode

Enable verbose logging:
```bash
# In docker-compose, add to environment:
- LOG_LEVEL=DEBUG

# Or rebuild with debug
gleitzeit serve --force-docker --api-only --dev-mode
```

### Health Monitoring

```bash
# Monitor service health
redis-cli keys "service:registry:*" | xargs -I {} redis-cli hgetall {}

# Watch container status
watch "docker-compose -f docker-compose-proper.yml ps"

# Monitor container resource usage
docker stats
```

## Performance Considerations

### Scaling Guidelines

- **API Containers**: Scale based on HTTP request load
- **Worker Containers**: Scale based on task queue depth and processing time
- **Redis**: Use Redis Cluster for high-throughput scenarios

### Resource Planning

- **API/UI Containers**: CPU and memory for HTTP processing
- **Worker Containers**: Resources based on handler requirements
- **Redis Container**: Memory for queue and registry data
- **Docker Host**: Sufficient resources for all containers

### Optimization Tips

- Use multi-stage Dockerfiles for smaller images
- Implement health checks for proper load balancing
- Configure appropriate restart policies
- Monitor and tune container resource limits
- Use Docker layer caching for faster builds

## Future Enhancements

### Planned Features

1. **Load Balancing**: Built-in load balancing between API containers
2. **Auto-Scaling**: Dynamic container scaling based on load
3. **Health Dashboards**: Real-time Docker service health monitoring
4. **Metrics Export**: Prometheus/Grafana integration for containers
5. **Rolling Updates**: Zero-downtime Docker deployments

### Advanced Features

1. **Cross-Region Docker Deployment**: Multi-region container coordination
2. **Container Failover**: Automatic container restart and failover
3. **Resource Limits**: Per-container resource constraints
4. **Security Policies**: Network and access control policies

## Migration Guide

### From Native to Docker

1. **Test Current Config**:
   ```bash
   gleitzeit serve --force-native  # Verify current setup
   ```

2. **Enable Docker Mode**:
   ```bash
   gleitzeit serve --force-docker  # Same config, Docker deployment
   ```

3. **Add Horizontal Scaling**:
   ```bash
   gleitzeit serve --force-docker --api-only
   gleitzeit serve --force-docker --workers-only
   ```

### From Standalone to Distributed

1. **Setup External Redis**:
   ```bash
   # Start shared Redis
   docker run -d -p 6379:6379 redis:alpine
   ```

2. **Deploy API Instance**:
   ```bash
   gleitzeit serve --force-docker --api-only --redis-url redis://localhost:6379
   ```

3. **Deploy Worker Instances**:
   ```bash
   gleitzeit serve --force-docker --workers-only --redis-url redis://localhost:6379
   ```

## Summary

Docker horizontal scaling extends gleitzeit's native horizontal scaling capabilities to containerized environments while maintaining:

- **Unified Configuration**: Single `gleitzeit.yaml` for all deployment modes
- **Stateless Architecture**: All coordination via Redis registry
- **Service Discovery**: Automatic service detection across Docker and native
- **Mixed Deployments**: Docker and native instances work together seamlessly
- **Operational Simplicity**: Same CLI interface and monitoring tools

This implementation enables flexible, scalable Docker deployments suitable for everything from development environments to production Kubernetes clusters.