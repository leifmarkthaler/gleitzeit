# Docker Quickstart Guide

## Prerequisites
- Docker and Docker Compose installed
- Port 8000, 8004, and 6379 available

## Quick Start

### 1. Start Everything
```bash
# Development mode (with hot reload)
make dev

# OR basic mode
make up

# OR using docker-compose directly
docker-compose up -d
```

### 2. Access Services
- **API**: http://localhost:8000
- **UI**: http://localhost:8004
- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

### 3. View Logs
```bash
# All services
make logs

# Specific services
make logs-api
make logs-worker
```

### 4. Scale Workers
```bash
# Scale task workers to 5 instances
make scale-workers N=5

# Or using docker-compose
docker-compose up -d --scale worker-task=5
```

## Development Workflow

### Hot Reload Development
```bash
# Start in dev mode with source mounted
make dev

# Edit files in src/ - changes auto-reload
# View logs to see reload happening
make logs-api
```

### Debugging
```bash
# Open shell in debug container
make shell

# Then inside container:
python
>>> from gleitzeit.api import *
>>> # Debug your code
```

### Testing Changes
```bash
# Rebuild after code changes
make build

# Restart services
make restart

# Check health
make health
```

## Common Commands

### Service Management
```bash
# Stop everything
make down

# Restart everything
make restart

# Check status
make status

# Clean up everything (including data)
make clean
```

### Specific Services
```bash
# Restart just API
make restart-api

# Restart workers
make restart-workers

# View UI logs
make logs-ui
```

### Redis Access
```bash
# Connect to Redis CLI
make redis-cli

# Inside Redis:
> KEYS *
> GET some:key
```

## Production Deployment

### Using Production Config
```bash
# Set environment variables
export REDIS_PASSWORD=your-secure-password
export SECRET_KEY=your-secret-key
export JWT_SECRET=your-jwt-secret

# Start in production mode
make prod

# Or manually
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Production Scaling
```bash
# Scale for production load
docker-compose -f docker-compose.yml -f docker-compose.prod.yml \
  up -d \
  --scale worker-task=20 \
  --scale worker-executor=10 \
  --scale api=5
```

## Troubleshooting

### Services Not Starting
```bash
# Check logs
docker-compose logs api
docker-compose logs redis

# Check if ports are in use
lsof -i :8000
lsof -i :6379
```

### Container Crashes
```bash
# Check container status
docker-compose ps

# View detailed logs
docker-compose logs --tail=100 api

# Restart specific service
docker-compose restart api
```

### Redis Connection Issues
```bash
# Verify Redis is running
docker-compose exec redis redis-cli ping

# Check Redis logs
docker-compose logs redis
```

### Clean Restart
```bash
# Stop and remove everything
make clean

# Rebuild and start fresh
make build
make up
```

## Architecture Notes

### What Docker Handles
- Process lifecycle (no more subprocess.Popen)
- Port management (no conflicts)
- Health monitoring (automatic restarts)
- Service discovery (by container name)
- Log aggregation (docker-compose logs)
- Resource limits (CPU/memory)

### What's Removed
- ProcessOrchestrator (not needed)
- ProcessManager (Docker handles)
- ServiceManager (simplified)
- PortManager (Docker networking)
- Subprocess management code

### Container Structure
```
redis          - State management
api            - REST API server
ui             - Web UI server
worker-task    - Task processing (scalable)
worker-executor - Task execution (scalable)
worker-workflow - Workflow orchestration
worker-scheduler - Cron jobs (single)
worker-monitor  - System monitoring (single)
worker-recovery - Failed task recovery
```

## Next Steps

1. **Customize Workers**: Edit `WORKER_TYPE` and `WORKER_SHARDS` in docker-compose.yml
2. **Add Monitoring**: Integrate Prometheus/Grafana
3. **Setup CI/CD**: Build and push images automatically
4. **Deploy to Cloud**: Use Docker Swarm or Kubernetes
5. **Add Load Balancer**: Put nginx/traefik in front