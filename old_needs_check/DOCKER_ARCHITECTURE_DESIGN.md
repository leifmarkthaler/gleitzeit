# Docker Architecture Design - Gleitzeit 0.0.7

## Executive Summary

Replace Gleitzeit's complex process management with Docker's battle-tested container orchestration. This design leverages Docker to handle all the distributed system complexities that Gleitzeit currently struggles with: process lifecycle, health monitoring, service discovery, and recovery.

## 1. DESIGN PRINCIPLES

### 1.1 Core Philosophy
- **Let Docker handle what it does best**: Process management, networking, health checks
- **Keep Gleitzeit focused on its core**: Workflow orchestration and task execution
- **Eliminate subprocess management**: No more Popen, PIPE deadlocks, or zombie processes
- **Embrace container patterns**: One process per container, stateless services

### 1.2 Benefits of Containerization
```
Current Problems → Docker Solutions:
- Subprocess deadlock → Container runtime handles I/O
- Port conflicts → Docker network isolation
- Process monitoring → Built-in health checks
- No auto-recovery → Restart policies
- State confusion → Single source (Docker)
- Manual scaling → Docker Compose scale
- Complex deployment → Single docker-compose up
```

## 2. ARCHITECTURE OVERVIEW

### 2.1 Service Decomposition
```
┌─────────────────────────────────────────────────────────┐
│                   Docker Network                         │
│                    (gleitzeit_net)                       │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │   API    │  │    UI    │  │  Redis   │             │
│  │  :8000   │  │  :8004   │  │  :6379   │             │
│  └──────────┘  └──────────┘  └──────────┘             │
│                                                          │
│  ┌──────────────────────────────────────┐              │
│  │         Worker Pool (Scaled)          │              │
│  │  ┌────────┐  ┌────────┐  ┌────────┐ │              │
│  │  │Worker-1│  │Worker-2│  │Worker-N│ │              │
│  │  └────────┘  └────────┘  └────────┘ │              │
│  └──────────────────────────────────────┘              │
│                                                          │
│  ┌──────────────────────────────────────┐              │
│  │      Specialized Workers              │              │
│  │  ┌────────┐  ┌────────┐  ┌────────┐ │              │
│  │  │Scheduler│  │Monitor │  │Recovery│ │              │
│  │  └────────┘  └────────┘  └────────┘ │              │
│  └──────────────────────────────────────┘              │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### 2.2 Container Hierarchy
```yaml
gleitzeit/
├── gleitzeit-base        # Base image with dependencies
├── gleitzeit-api         # API server
├── gleitzeit-ui          # UI server
├── gleitzeit-worker      # Generic worker
├── gleitzeit-scheduler   # Cron scheduler
├── gleitzeit-monitor     # System monitor
└── gleitzeit-cli         # CLI tools
```

## 3. CONTAINER DEFINITIONS

### 3.1 Base Image
```dockerfile
# Dockerfile.base
FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv for dependency management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.cargo/bin:${PATH}"

# Create app directory
WORKDIR /app

# Copy project files
COPY pyproject.toml .
COPY src/ ./src/

# Install dependencies with uv
RUN uv venv .venv && \
    uv sync --frozen

# Set Python path
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:${PATH}"
ENV PYTHONPATH=/app/src:${PYTHONPATH}
```

### 3.2 Service Containers
```dockerfile
# Dockerfile.api
FROM gleitzeit-base

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "gleitzeit.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```dockerfile
# Dockerfile.ui
FROM gleitzeit-base

EXPOSE 8004
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD curl -f http://localhost:8004/health || exit 1

CMD ["uvicorn", "gleitzeit.ui.api.app:app", "--host", "0.0.0.0", "--port", "8004"]
```

### 3.3 Worker Containers
```dockerfile
# Dockerfile.worker
FROM gleitzeit-base

# Worker-specific environment
ENV WORKER_TYPE=${WORKER_TYPE:-task}
ENV WORKER_SHARDS=${WORKER_SHARDS:-"0,1,2,3"}
ENV WORKER_CONCURRENCY=${WORKER_CONCURRENCY:-10}

# No exposed ports for workers
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD python -c "from gleitzeit.workers.health import check; exit(0 if check() else 1)"

CMD ["python", "-m", "gleitzeit.workers.runner"]
```

## 4. DOCKER COMPOSE CONFIGURATION

### 4.1 Development Environment
```yaml
# docker-compose.yml
version: '3.8'

networks:
  gleitzeit:
    driver: bridge

volumes:
  redis-data:
  logs:

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    networks:
      - gleitzeit
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 3

  api:
    build:
      context: .
      dockerfile: Dockerfile.api
    ports:
      - "8000:8000"
    environment:
      - REDIS_URL=redis://redis:6379
      - LOG_LEVEL=INFO
    depends_on:
      redis:
        condition: service_healthy
    networks:
      - gleitzeit
    restart: unless-stopped
    volumes:
      - logs:/app/logs
      - ./src:/app/src:ro  # Mount source for development

  ui:
    build:
      context: .
      dockerfile: Dockerfile.ui
    ports:
      - "8004:8004"
    environment:
      - REDIS_URL=redis://redis:6379
      - API_URL=http://api:8000
      - LOG_LEVEL=INFO
    depends_on:
      - api
    networks:
      - gleitzeit
    restart: unless-stopped
    volumes:
      - logs:/app/logs

  # Task workers (scalable)
  worker-task:
    build:
      context: .
      dockerfile: Dockerfile.worker
    environment:
      - REDIS_URL=redis://redis:6379
      - WORKER_TYPE=task
      - WORKER_SHARDS=0,1,2,3
      - LOG_LEVEL=INFO
    depends_on:
      redis:
        condition: service_healthy
    networks:
      - gleitzeit
    restart: unless-stopped
    deploy:
      replicas: 2  # Scale as needed
    volumes:
      - logs:/app/logs

  # Specialized workers (single instance)
  worker-scheduler:
    build:
      context: .
      dockerfile: Dockerfile.worker
    environment:
      - REDIS_URL=redis://redis:6379
      - WORKER_TYPE=scheduler
      - USE_LEADER_ELECTION=true
      - LOG_LEVEL=INFO
    depends_on:
      redis:
        condition: service_healthy
    networks:
      - gleitzeit
    restart: unless-stopped
    volumes:
      - logs:/app/logs

  worker-monitor:
    build:
      context: .
      dockerfile: Dockerfile.worker
    environment:
      - REDIS_URL=redis://redis:6379
      - WORKER_TYPE=monitor
      - LOG_LEVEL=INFO
    depends_on:
      redis:
        condition: service_healthy
    networks:
      - gleitzeit
    restart: unless-stopped
    volumes:
      - logs:/app/logs
```

### 4.2 Production Environment
```yaml
# docker-compose.prod.yml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD}
    deploy:
      resources:
        limits:
          memory: 2G
        reservations:
          memory: 512M

  api:
    deploy:
      replicas: 3
      restart_policy:
        condition: any
        delay: 5s
        max_attempts: 3
      resources:
        limits:
          cpus: '2'
          memory: 1G
    environment:
      - LOG_LEVEL=WARNING
      - ENVIRONMENT=production

  worker-task:
    deploy:
      replicas: 10  # Production scale
      restart_policy:
        condition: any
        delay: 5s
      resources:
        limits:
          cpus: '1'
          memory: 512M
```

## 5. ORCHESTRATION PATTERNS

### 5.1 Service Discovery
```yaml
# Services discover each other by name
API_URL: http://api:8000
REDIS_URL: redis://redis:6379

# No port management needed - Docker handles it
```

### 5.2 Health Management
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
  interval: 30s      # Check every 30s
  timeout: 3s        # Timeout after 3s
  retries: 3         # Unhealthy after 3 failures
  start_period: 40s  # Grace period on startup
```

### 5.3 Scaling Patterns
```bash
# Development scaling
docker-compose up --scale worker-task=4

# Production scaling with Swarm
docker service scale gleitzeit_worker-task=20

# Kubernetes scaling
kubectl scale deployment worker-task --replicas=20
```

### 5.4 Recovery Patterns
```yaml
restart: unless-stopped  # Auto-restart on failure
deploy:
  restart_policy:
    condition: on-failure
    delay: 5s
    max_attempts: 3
    window: 120s
```

## 6. MIGRATION STRATEGY

### 6.1 Code Changes Required

#### Remove Process Management
```python
# DELETE these files/classes:
- ProcessOrchestrator (not needed)
- ProcessManager (Docker handles this)
- ServiceManager (simplified to config only)
- PortManager (Docker networking)
- Subprocess handling code

# KEEP these:
- WorkerManager (for worker logic)
- Task execution logic
- Business logic
```

#### Simplify Service Startup
```python
# Old (complex process management):
class ProcessOrchestrator:
    async def start_all(self):
        # Complex subprocess handling
        # Port allocation
        # Process monitoring

# New (simple direct start):
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("gleitzeit.api.main:app", host="0.0.0.0", port=8000)
```

#### Environment-Based Configuration
```python
# config.py
import os

class Config:
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')
    API_PORT = int(os.getenv('API_PORT', '8000'))
    WORKER_TYPE = os.getenv('WORKER_TYPE', 'task')
    WORKER_SHARDS = os.getenv('WORKER_SHARDS', '0,1,2,3').split(',')

    @classmethod
    def from_environment(cls):
        return cls()
```

### 6.2 Deployment Workflow

#### Development
```bash
# Build images
docker-compose build

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Scale workers
docker-compose up -d --scale worker-task=4

# Stop everything
docker-compose down
```

#### Production
```bash
# Build and push images
docker build -t gleitzeit:latest .
docker push registry/gleitzeit:latest

# Deploy with Swarm
docker stack deploy -c docker-compose.yml gleitzeit

# Or deploy with Kubernetes
kubectl apply -f k8s/
```

## 7. KUBERNETES EVOLUTION

### 7.1 Natural Progression
```yaml
# k8s/api-deployment.yml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gleitzeit-api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: gleitzeit-api
  template:
    metadata:
      labels:
        app: gleitzeit-api
    spec:
      containers:
      - name: api
        image: gleitzeit:latest
        command: ["uvicorn", "gleitzeit.api.main:app"]
        ports:
        - containerPort: 8000
        env:
        - name: REDIS_URL
          valueFrom:
            secretKeyRef:
              name: redis-secret
              key: url
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
        readinessProbe:
          httpGet:
            path: /ready
            port: 8000
```

### 7.2 Advanced Features
```yaml
# HorizontalPodAutoscaler
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: worker-autoscaler
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: gleitzeit-worker
  minReplicas: 2
  maxReplicas: 100
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

## 8. ADVANTAGES OF DOCKER APPROACH

### 8.1 Immediate Benefits
1. **No subprocess management**: Docker handles all process lifecycle
2. **No port conflicts**: Docker networking provides isolation
3. **Built-in health checks**: Docker monitors and restarts unhealthy containers
4. **Easy scaling**: Simple commands to scale up/down
5. **Consistent environments**: Same containers in dev/staging/prod

### 8.2 Operational Benefits
1. **Standard tooling**: Use existing Docker/K8s ecosystem
2. **Better observability**: Container metrics, logs aggregation
3. **Rolling updates**: Zero-downtime deployments
4. **Resource limits**: CPU/memory constraints per container
5. **Network isolation**: Security by default

### 8.3 Development Benefits
1. **Faster onboarding**: `docker-compose up` and done
2. **Consistent behavior**: No "works on my machine"
3. **Easy testing**: Spin up test environments quickly
4. **Service isolation**: Test components independently

## 9. IMPLEMENTATION TIMELINE

### Phase 1: Containerize (Week 1)
- Create Dockerfiles for each service
- Set up docker-compose.yml
- Test basic functionality

### Phase 2: Simplify Code (Week 2)
- Remove ProcessOrchestrator
- Simplify service startup
- Environment-based config

### Phase 3: Production Ready (Week 3)
- Add health checks
- Configure restart policies
- Set up logging
- Create deployment scripts

### Phase 4: Documentation & Testing (Week 4)
- Update documentation
- Create runbooks
- Load testing
- Chaos testing

## 10. DECISION MATRIX

| Aspect | Current (Process Manager) | Docker Solution |
|--------|---------------------------|-----------------|
| Process Management | Complex, buggy | Docker handles |
| Port Management | 3 conflicting systems | Docker networking |
| Health Monitoring | Manual, incomplete | Built-in probes |
| Auto-recovery | Not implemented | Restart policies |
| Scaling | Manual, complex | `--scale` flag |
| Deployment | Complex setup | `docker-compose up` |
| Resource Control | None | CPU/memory limits |
| Logging | File-based, scattered | Centralized |
| Development Setup | Complex | Simple |
| Production Ready | No | Yes |

## CONCLUSION

Docker solves Gleitzeit's fundamental problems by replacing complex, buggy process management with battle-tested container orchestration. This isn't just containerizing the existing architecture—it's embracing container patterns to eliminate entire categories of problems.

**Key Insight**: We don't need to fix subprocess management, port allocation, or process monitoring. Docker already solved these problems. Let Gleitzeit focus on what it does best: workflow orchestration.

**Recommended Approach**: Start with docker-compose for immediate relief, evolve to Kubernetes for production scale.