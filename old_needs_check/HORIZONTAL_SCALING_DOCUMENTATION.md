# Gleitzeit Horizontal Scaling Documentation

## Overview

Gleitzeit now supports **horizontal scaling** with stateless instances that can be deployed across multiple machines or containers. This enables distributed deployments for high availability and performance scaling.

## Architecture

### Stateless Design Principles

- **No Local State Dependencies**: All state is stored in Redis
- **Service Discovery**: Instances find each other through Redis registry
- **Shared Configuration**: Common `gleitzeit.yaml` loaded from file or remote URL
- **Network-Aware Registration**: Services register with actual network addresses

### Deployment Modes

1. **Full Instance** (`gleitzeit serve`) - API, UI, and Workers
2. **API-Only** (`--api-only`) - API and UI services only
3. **Workers-Only** (`--workers-only`) - Worker processes only

### Service Registry

Services are registered in Redis with the following information:
```
service:registry:api -> {pid, port, host, started_at, mode}
service:registry:ui  -> {pid, port, host, started_at, mode}
service:registry:worker_* -> {pid, worker_type, started_at, mode}
```

## CLI Options

### Basic Horizontal Scaling

```bash
# API/UI instance
gleitzeit serve --api-only

# Workers instance
gleitzeit serve --workers-only

# Full instance (default)
gleitzeit serve
```

### Advanced Options

```bash
# External Redis
gleitzeit serve --redis-url redis://redis-server:6379

# Remote configuration
gleitzeit serve --config-url https://config.company.com/gleitzeit.yaml

# Port offset for multiple instances on same machine
gleitzeit serve --port-offset 100

# Environment variable support
REDIS_URL=redis://redis-cluster:6379 gleitzeit serve --api-only
```

### Force deployment modes
```bash
# Force native mode (bypass Docker detection)
gleitzeit serve --force-native --workers-only

# Force Docker mode (fail if Docker unavailable)
gleitzeit serve --force-docker --api-only
```

## Configuration

### Port Configuration

Ports are loaded from `gleitzeit.yaml`:

```yaml
api:
  port: 8000

ui:
  port: 8004
```

Port offsets are applied to base configuration:
- `--port-offset 100` → API: 8100, UI: 8104

### Redis Configuration

Redis URL can be specified via:

1. **CLI argument**: `--redis-url redis://host:port`
2. **Environment variable**: `REDIS_URL=redis://host:port`
3. **Default**: `redis://localhost:6379`

### Remote Configuration

Load configuration from remote sources:

```bash
# HTTP/HTTPS
gleitzeit serve --config-url https://config.company.com/gleitzeit.yaml

# Environment variable
CONFIG_URL=https://config.company.com/gleitzeit.yaml gleitzeit serve
```

## Deployment Scenarios

### Scenario 1: Simple Horizontal Scaling

**Machine 1** (API/UI):
```bash
gleitzeit serve --api-only --redis-url redis://shared-redis:6379
```

**Machine 2** (Workers):
```bash
gleitzeit serve --workers-only --redis-url redis://shared-redis:6379
```

### Scenario 2: Multi-Instance Same Machine

**Instance 1** (API/UI):
```bash
gleitzeit serve --api-only
```

**Instance 2** (Workers with offset):
```bash
gleitzeit serve --workers-only --port-offset 100
```

### Scenario 3: Kubernetes/Container Deployment

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
        command: ["gleitzeit", "serve", "--api-only"]
        env:
        - name: REDIS_URL
          value: "redis://redis-service:6379"
        - name: CONFIG_URL
          value: "https://config.company.com/gleitzeit.yaml"
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
        command: ["gleitzeit", "serve", "--workers-only"]
        env:
        - name: REDIS_URL
          value: "redis://redis-service:6379"
        - name: CONFIG_URL
          value: "https://config.company.com/gleitzeit.yaml"
```

### Scenario 4: Docker Compose

```yaml
version: '3.8'
services:
  redis:
    image: redis:alpine
    ports:
      - "6379:6379"

  gleitzeit-api:
    image: gleitzeit:latest
    command: gleitzeit serve --api-only
    environment:
      - REDIS_URL=redis://redis:6379
    ports:
      - "8000:8000"
      - "8004:8004"
    depends_on:
      - redis

  gleitzeit-workers:
    image: gleitzeit:latest
    command: gleitzeit serve --workers-only
    environment:
      - REDIS_URL=redis://redis:6379
    deploy:
      replicas: 3
    depends_on:
      - redis
```

## Service Discovery Process

### Instance Startup

1. **Load Configuration**: From file or remote URL
2. **Initialize Redis Connection**: Using configured Redis URL
3. **Register Instance Identity**: Machine ID and instance ID
4. **Check Service Registry**: Discover existing services
5. **Health Validation**: Verify existing services are healthy
6. **Service Attachment**: Attach to healthy services or start new ones

### Service Registration

When starting new services:

```python
await smart_manager.register_service("api", {
    "pid": str(process.pid),
    "port": str(port),
    "host": network_hostname,  # e.g., "server1.company.com"
    "started_at": datetime.now().isoformat(),
    "mode": "native"
})
```

### Health Checking

Services validate existing processes:

```python
def is_service_healthy(pid):
    if not psutil.pid_exists(pid):
        return False
    proc = psutil.Process(pid)
    return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
```

## Monitoring and Management

### Check Service Status

```bash
# View registered services
redis-cli keys "service:registry:*"

# Check specific service
redis-cli hgetall "service:registry:api"

# Monitor logs
tail -f logs/api_*.log
tail -f logs/worker_*.log
```

### Stop Services

```bash
# Stop services (will auto-restart if monitor running)
gleitzeit stop

# Stop ALL instances including monitors
gleitzeit stop --all

# Force stop
gleitzeit stop --force
```

## Network Requirements

### Ports

- **API**: Default 8000 (configurable)
- **UI**: Default 8004 (configurable)
- **Redis**: Default 6379 (configurable)

### Connectivity

- All instances must reach the Redis server
- API/UI services must be accessible to clients
- Workers need network access for handler execution (HTTP, containers, etc.)

## Security Considerations

### Redis Security

- Use Redis AUTH: `redis://user:password@host:port`
- Enable TLS: `rediss://host:port`
- Network isolation for Redis access
- Regular Redis security updates

### Configuration Security

- Secure remote configuration URLs (HTTPS)
- Avoid secrets in configuration files
- Use environment variables for sensitive data
- Regular configuration validation

### Service Communication

- Consider TLS termination at load balancer
- Network segmentation between components
- Regular security updates for all components

## Troubleshooting

### Common Issues

**Port Already in Use**:
```bash
# Check what's using the port
lsof -i :8000

# Use port offset or stop existing services
gleitzeit serve --port-offset 100
```

**Redis Connection Failed**:
```bash
# Test Redis connectivity
redis-cli -h redis-server -p 6379 ping

# Check environment variables
echo $REDIS_URL
```

**Service Discovery Issues**:
```bash
# Check service registry
redis-cli keys "service:registry:*"

# Verify service health
ps aux | grep gleitzeit
```

**Configuration Loading Failed**:
```bash
# Test remote config URL
curl https://config.company.com/gleitzeit.yaml

# Check local config
cat gleitzeit.yaml
```

### Debug Mode

Enable verbose logging:
```bash
LOG_LEVEL=DEBUG gleitzeit serve --workers-only
```

### Health Monitoring

Monitor service health:
```bash
# Check process status
gleitzeit ps

# Monitor service registry
watch "redis-cli keys 'service:registry:*' | xargs -I {} redis-cli hgetall {}"
```

## Performance Considerations

### Scaling Guidelines

- **API Instances**: Scale based on request load
- **Worker Instances**: Scale based on task queue depth
- **Redis**: Use Redis Cluster for high-throughput scenarios

### Resource Planning

- **API/UI**: CPU and memory for HTTP processing
- **Workers**: Resources based on handler requirements
- **Redis**: Memory for queue and registry data

### Monitoring Metrics

- Service response times
- Task queue depth
- Redis memory usage
- Process CPU/memory usage
- Network connectivity health

## Future Enhancements

### Planned Features

1. **Load Balancing**: Built-in load balancing between API instances
2. **Auto-Scaling**: Dynamic worker scaling based on load
3. **Health Dashboards**: Real-time service health monitoring
4. **Metrics Export**: Prometheus/Grafana integration
5. **Rolling Updates**: Zero-downtime deployment support

### Advanced Features

1. **Cross-Region Deployment**: Multi-region service discovery
2. **Failover**: Automatic failover between regions
3. **Rate Limiting**: Per-instance and global rate limiting
4. **Circuit Breakers**: Fault tolerance patterns

## Examples

### Development Setup

```bash
# Terminal 1: Start API/UI
gleitzeit serve --api-only

# Terminal 2: Start workers
gleitzeit serve --workers-only

# Terminal 3: Submit work
gleitzeit submit workflow.yaml
```

### Production Setup

```bash
# Production API cluster
for i in {1..3}; do
    gleitzeit serve --api-only \
        --redis-url redis://prod-redis-cluster:6379 \
        --config-url https://config.prod.company.com/gleitzeit.yaml &
done

# Production workers
for i in {1..10}; do
    gleitzeit serve --workers-only \
        --redis-url redis://prod-redis-cluster:6379 \
        --config-url https://config.prod.company.com/gleitzeit.yaml &
done
```

This horizontal scaling implementation provides a solid foundation for distributed Gleitzeit deployments while maintaining the stateless architecture principles essential for cloud-native applications.