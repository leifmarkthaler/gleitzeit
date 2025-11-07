# Gleitzeit 0.0.7 Startup Sequence Audit

## Executive Summary

This document audits the startup sequences for Gleitzeit 0.0.7 both with and without Docker, identifying issues and providing recommendations for improvement.

## Current Architecture Overview

Gleitzeit uses a distributed worker-based architecture with:
- **Multiple worker types**: workflow_loader, dependency, task_execution, signal, timer
- **Component Orchestrator**: Manages worker lifecycle
- **Redis Cluster**: Distributed state management with hash-tag based sharding
- **CLI Interface**: Command-line management tool

---

## 1. Startup Sequence WITHOUT Docker

### A. Manual Worker Startup

#### Method 1: Direct Python Module Execution
```bash
# Start individual workers manually
python -m gleitzeit.workers.runner \
  --worker-class gleitzeit.workers.workflow_loader_worker_v2.WorkflowLoaderWorkerV2 \
  --worker-id loader-1 \
  --shards 0,1,2,3 \
  --redis-url redis://localhost:6379

python -m gleitzeit.workers.runner \
  --worker-class gleitzeit.workers.dependency_worker.DependencyWorker \
  --worker-id dep-1 \
  --shards 0,1,2,3
```

**Issues Identified:**
1. ❌ **Manual coordination required** - Must start each worker individually
2. ❌ **No health checking** - Workers can fail silently
3. ❌ **Shard assignment is manual** - Risk of gaps or overlaps
4. ❌ **Redis cluster nodes hardcoded** - Uses localhost:6379 as default
5. ❌ **No automatic restart** on failure
6. ❌ **Process management burden** - User must track PIDs

#### Method 2: CLI Worker Start
```bash
# Using the CLI
gleitzeit worker start --type task_execution --id exec-1 --shards 0,1,2,3
```

**Issues Identified:**
1. ❌ **Limited worker types** in CLI choices (only 3 of 5 types)
2. ❌ **No signal/timer worker options** in CLI
3. ❌ **Still requires manual coordination**

### B. Orchestrator-Managed Startup

```bash
# Start orchestrator
gleitzeit orchestrator start --config config.yaml
```

**Expected config.yaml:**
```yaml
workers:
  workflow_loader:
    count: 2
    class: gleitzeit.workers.workflow_loader_worker_v2.WorkflowLoaderWorkerV2
  dependency:
    count: 2
    class: gleitzeit.workers.dependency_worker.DependencyWorker
  task_execution:
    count: 4
    class: gleitzeit.workers.task_execution_worker_v2.TaskExecutionWorkerV2
  signal:
    count: 1
    class: gleitzeit.workers.signal_worker.SignalWorker
  timer:
    count: 1
    class: gleitzeit.workers.timer_worker.TimerWorker
```

**Issues Identified:**
1. ❌ **Config file not provided** - No example config.yaml in repo
2. ❌ **Class paths required** - User must know internal structure
3. ❌ **No default configuration** - Falls back to hardcoded defaults
4. ❌ **Redis cluster config missing** - No way to specify cluster nodes
5. ⚠️ **Process spawning issues** - Uses asyncio.create_subprocess_exec which may have platform limitations

### C. Development Setup

```bash
# Install dependencies
pip install -e .

# Start Redis (single instance)
redis-server

# Run tests
pytest tests/
```

**Issues Identified:**
1. ❌ **No Redis Cluster setup script** - Manual cluster setup required
2. ❌ **Missing development dependencies** - redis-py[cluster] not in requirements
3. ❌ **No environment file template** - Users must guess env vars
4. ❌ **No quickstart script** - High barrier to entry

---

## 2. Startup Sequence WITH Docker

### A. Docker Files Status

**Current State:**
- ❌ **NO Dockerfile found** in repository
- ❌ **NO docker-compose.yml** found
- ❌ **NO .dockerignore** found
- ❌ **NO container registry** configuration

### B. Required Docker Setup (Missing)

#### Recommended Dockerfile
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY setup.py README.md ./
COPY src/ ./src/
RUN pip install -e .[dev]

# Create non-root user
RUN useradd -m -u 1000 gleitzeit
USER gleitzeit

# Default command
CMD ["gleitzeit", "orchestrator", "start"]
```

#### Recommended docker-compose.yml
```yaml
version: '3.8'

services:
  # Redis Cluster Setup
  redis-node-1:
    image: redis:7-alpine
    command: redis-server --port 7000 --cluster-enabled yes
    ports:
      - "7000:7000"
    volumes:
      - redis-1:/data

  redis-node-2:
    image: redis:7-alpine
    command: redis-server --port 7001 --cluster-enabled yes
    ports:
      - "7001:7001"
    volumes:
      - redis-2:/data

  redis-node-3:
    image: redis:7-alpine
    command: redis-server --port 7002 --cluster-enabled yes
    ports:
      - "7002:7002"
    volumes:
      - redis-3:/data

  # Redis Cluster Init
  redis-cluster-init:
    image: redis:7-alpine
    depends_on:
      - redis-node-1
      - redis-node-2
      - redis-node-3
    command: |
      sh -c "
      sleep 5;
      redis-cli --cluster create
        redis-node-1:7000 redis-node-2:7001 redis-node-3:7002
        --cluster-replicas 0 --cluster-yes
      "

  # Gleitzeit Orchestrator
  orchestrator:
    build: .
    environment:
      - REDIS_CLUSTER_NODES=redis-node-1:7000,redis-node-2:7001,redis-node-3:7002
      - REDIS_MAX_CONNECTIONS=50
    depends_on:
      - redis-cluster-init
    volumes:
      - ./config:/config
    command: gleitzeit orchestrator start --config /config/orchestrator.yaml

  # Individual Workers (if not using orchestrator)
  workflow-loader:
    build: .
    environment:
      - REDIS_CLUSTER_NODES=redis-node-1:7000,redis-node-2:7001,redis-node-3:7002
    depends_on:
      - redis-cluster-init
    command: |
      python -m gleitzeit.workers.runner
        --worker-class gleitzeit.workers.workflow_loader_worker_v2.WorkflowLoaderWorkerV2
        --worker-id loader-1
        --shards 0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15

volumes:
  redis-1:
  redis-2:
  redis-3:
```

---

## 3. Critical Issues Identified

### High Priority Issues

1. **No Docker Support**
   - Impact: Cannot deploy in containerized environments
   - Solution: Add Dockerfile and docker-compose.yml

2. **Missing Configuration Templates**
   - Impact: Users don't know how to configure the system
   - Solution: Provide example configs for different scenarios

3. **Incomplete CLI**
   - Impact: Cannot start all worker types via CLI
   - Solution: Add signal and timer worker options

4. **No Redis Cluster Setup**
   - Impact: Complex manual setup required
   - Solution: Provide setup scripts or docker-compose

5. **Hardcoded Redis Connection**
   - Impact: Cannot easily connect to remote/cluster Redis
   - Solution: Use environment variables consistently

### Medium Priority Issues

6. **No Health Checks**
   - Impact: Workers can fail without detection
   - Solution: Implement health check endpoints

7. **Manual Shard Management**
   - Impact: Risk of misconfiguration
   - Solution: Auto-distribute shards based on worker count

8. **No Graceful Shutdown**
   - Impact: Data loss on shutdown
   - Solution: Implement proper signal handling

9. **Missing Metrics/Monitoring**
   - Impact: No visibility into system performance
   - Solution: Add Prometheus metrics endpoint

### Low Priority Issues

10. **No Development Tools**
    - Impact: Harder to onboard new developers
    - Solution: Add Makefile or development scripts

---

## 4. Recommendations

### Immediate Actions (Week 1)

1. **Create Docker Support Files**
   ```bash
   touch Dockerfile
   touch docker-compose.yml
   touch .dockerignore
   touch .env.example
   ```

2. **Add Configuration Templates**
   ```bash
   mkdir configs/
   touch configs/orchestrator.yaml.example
   touch configs/workers.yaml.example
   touch configs/redis-cluster.yaml.example
   ```

3. **Fix CLI Worker Types**
   - Add signal and timer workers to CLI choices
   - Add --all-workers flag to start complete stack

4. **Create Quickstart Script**
   ```bash
   #!/bin/bash
   # quickstart.sh
   docker-compose up -d redis-cluster-init
   sleep 10
   docker-compose up -d orchestrator
   docker-compose logs -f
   ```

### Short Term (Month 1)

5. **Implement Health Checks**
   - Add /health endpoint to workers
   - Add liveness/readiness probes
   - Integrate with orchestrator monitoring

6. **Add Auto-Sharding**
   - Calculate shard distribution automatically
   - Rebalance on worker count changes

7. **Improve Process Management**
   - Use supervisord or systemd for non-Docker deployments
   - Add proper signal handling

### Long Term (Quarter 1)

8. **Add Observability**
   - Prometheus metrics
   - OpenTelemetry tracing
   - Structured logging with correlation IDs

9. **Create Helm Charts**
   - For Kubernetes deployment
   - Include autoscaling configurations

10. **Build Admin UI**
    - Web interface for monitoring
    - Workflow submission UI
    - Worker management dashboard

---

## 5. Example Startup Commands (After Fixes)

### Development (Local)
```bash
# One-command startup
make dev

# Or using docker-compose
docker-compose up
```

### Production (Docker)
```bash
# Using docker-compose with overrides
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Or using Kubernetes
kubectl apply -f k8s/
```

### Testing
```bash
# Run all tests with Redis Cluster
make test-cluster

# Or manually
./scripts/start-test-cluster.sh
pytest tests/
./scripts/stop-test-cluster.sh
```

---

## Conclusion

The current startup sequence has significant gaps, particularly around:
- **Docker support** (completely missing)
- **Configuration management** (no templates or examples)
- **Operational tooling** (health checks, monitoring)
- **Developer experience** (high barrier to entry)

Implementing the recommended changes would significantly improve the deployment and operational experience of Gleitzeit 0.0.7.