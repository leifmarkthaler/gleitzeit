# Gleitzeit 0.0.7 - Working Docker Setup Documentation

## Executive Summary

This document describes the successful Docker-based deployment of Gleitzeit 0.0.7 that completely bypasses the subprocess management issues. The system is now fully operational with workflow submission, validation, execution, and result retrieval all working correctly.

## Key Achievement

**Problem Solved**: The subprocess deadlock issue (`subprocess.Popen` with `PIPE`) that caused all processes to die has been completely eliminated by using Docker for process management.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                   Docker Network                         │
│                  (gleitzeit_network)                     │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────┐         ┌──────────┐        ┌──────────┐ │
│  │  Redis   │◄────────┤   API    │────────►│    UI    │ │
│  │  :6379   │         │  :8000   │         │  :8004   │ │
│  └────┬─────┘         └──────────┘         └──────────┘ │
│       │                                                  │
│       ▼                                                  │
│  ┌──────────────────────────────────────────────────┐   │
│  │              Worker Containers                    │   │
│  │                                                   │   │
│  │  • workflow-loader (validates & loads workflows)  │   │
│  │  • dependency-worker (creates tasks from WF)     │   │
│  │  • task-execution (executes Python code)         │   │
│  │  • workflow-submission (handles submissions)     │   │
│  │  • retry-worker (handles retries)                │   │
│  │  • timer-worker (scheduled tasks)                │   │
│  │                                                   │   │
│  └──────────────────────────────────────────────────┘   │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

## Critical Discovery & Fix

### The Problem
Workers were failing to connect to Redis with error:
```
redis.exceptions.ConnectionError: Error Multiple exceptions:
[Errno 111] Connect call failed ('127.0.0.1', 6379)
```

### Root Cause
- Workers ignore the `--redis-url` command line parameter
- They use `REDIS_CLUSTER_NODES` environment variable instead
- Default value is `localhost:6379` (hardcoded in `redis_cluster.py`)

### The Fix
Add `REDIS_CLUSTER_NODES=redis:6379` to worker environment variables in docker-compose.

## Working Configuration Files

### 1. Dockerfile.worker
```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src/ ./src/

RUN uv venv .venv && uv sync --frozen

ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:${PATH}"
ENV PYTHONPATH=/app/src:${PYTHONPATH}

# Workers need specific commands from docker-compose
CMD ["sleep", "infinity"]
```

### 2. docker-compose-proper.yml (Essential Workers)
```yaml
version: '3.8'

networks:
  gleitzeit:
    driver: bridge
    name: gleitzeit_network

volumes:
  redis-data:
  logs:

services:
  redis:
    image: redis:7-alpine
    container_name: gleitzeit_redis
    ports:
      - "6379:6379"
    networks:
      - gleitzeit
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 3
    restart: unless-stopped

  api:
    build:
      dockerfile: Dockerfile.api
    ports:
      - "8000:8000"
    environment:
      - REDIS_URL=redis://redis:6379
      - REDIS_CLUSTER_NODES=redis:6379  # Critical!
      - LOG_LEVEL=INFO
    depends_on:
      redis:
        condition: service_healthy
    networks:
      - gleitzeit
    restart: unless-stopped

  # Essential Worker: Workflow Loader
  worker-workflow-loader:
    build:
      dockerfile: Dockerfile.worker
    command: ["python", "-m", "gleitzeit.workers.runner",
              "--worker-class", "gleitzeit.workers.workflow_loader_worker_v2.WorkflowLoaderWorkerV2",
              "--worker-id", "workflow-loader-1",
              "--worker-type", "workflow_loader",
              "--redis-url", "redis://redis:6379",  # Ignored!
              "--shards", "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15",
              "--max-concurrent", "10"]
    environment:
      - REDIS_CLUSTER_NODES=redis:6379  # This is what actually works!
      - LOG_LEVEL=INFO
    depends_on:
      redis:
        condition: service_healthy
    networks:
      - gleitzeit

  # Essential Worker: Dependency Worker
  worker-dependency:
    build:
      dockerfile: Dockerfile.worker
    command: ["python", "-m", "gleitzeit.workers.runner",
              "--worker-class", "gleitzeit.workers.dependency_worker.DependencyWorker",
              "--worker-id", "dependency-1",
              "--worker-type", "dependency",
              "--redis-url", "redis://redis:6379",
              "--shards", "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15",
              "--max-concurrent", "10"]
    environment:
      - REDIS_CLUSTER_NODES=redis:6379  # Critical!
      - LOG_LEVEL=INFO
    depends_on:
      redis:
        condition: service_healthy
    networks:
      - gleitzeit

  # Essential Worker: Task Execution
  worker-task-execution:
    build:
      dockerfile: Dockerfile.worker
    command: ["python", "-m", "gleitzeit.workers.runner",
              "--worker-class", "gleitzeit.workers.task_execution_worker.TaskExecutionWorker",
              "--worker-id", "task-exec-1",
              "--worker-type", "task_execution",
              "--redis-url", "redis://redis:6379",
              "--shards", "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15",
              "--max-concurrent", "5"]
    environment:
      - REDIS_CLUSTER_NODES=redis:6379  # Critical!
      - LOG_LEVEL=INFO
    depends_on:
      redis:
        condition: service_healthy
    networks:
      - gleitzeit
```

## Workflow Submission Format

### Important: Dependencies Use Task Names, Not IDs!

```json
{
  "workflow": {
    "name": "my_workflow",
    "version": "1.0",
    "description": "Example workflow",
    "tasks": [
      {
        "name": "First Task",  // This name is used in dependencies
        "type": "python",
        "handler": "python",
        "method": "python/execute",
        "params": {
          "code": "print('Hello'); result = {'value': 42}"
        }
      },
      {
        "name": "Second Task",
        "type": "python",
        "handler": "python",
        "method": "python/execute",
        "depends_on": ["First Task"],  // References task name!
        "params": {
          "code": "print('World'); result = {'value': 100}"
        }
      }
    ]
  },
  "workflow_id": "my-workflow-001",
  "metadata": {
    "submitted_by": "user"
  }
}
```

## API Endpoints

### Submit Workflow
```bash
curl -X POST http://localhost:8000/workflows/submit \
  -H "Content-Type: application/json" \
  -d @workflow.json
```

Response:
```json
{
  "workflow_id": "my-workflow-001",
  "status": "submitted",
  "message": "Workflow submitted to stream {shard:N}:workflow:load",
  "submitted_at": "2025-09-27T17:59:56.616376"
}
```

### Check Workflow Status
```bash
curl http://localhost:8000/workflows/{workflow_id}
```

Response includes:
- `status`: submitted → validation → running → completed
- `total_tasks`: Number of tasks
- `completed_tasks`: Tasks finished
- Full workflow definition with generated task IDs

### List All Tasks
```bash
curl http://localhost:8000/tasks/list
```

### Get Task Result
```bash
curl http://localhost:8000/tasks/{task_id}
```

Response includes:
```json
{
  "task_id": "...",
  "workflow_id": "...",
  "state": {
    "status": "completed",
    "result": {
      // Your task's return value
      "_stdout": "Captured print output\n"
    },
    "executed_at": "...",
    "completed_at": "..."
  }
}
```

## Complete Working Example

### 1. Start Everything
```bash
docker-compose -f docker-compose-proper.yml up -d
```

### 2. Create Workflow File
```bash
cat > test-workflow.json << 'EOF'
{
  "workflow": {
    "name": "test_workflow",
    "version": "1.0",
    "description": "Test workflow",
    "tasks": [
      {
        "name": "Task A",
        "type": "python",
        "handler": "python",
        "method": "python/execute",
        "params": {
          "code": "print('Starting workflow'); result = {'status': 'started'}"
        }
      },
      {
        "name": "Task B",
        "type": "python",
        "handler": "python",
        "method": "python/execute",
        "depends_on": ["Task A"],
        "params": {
          "code": "import time; time.sleep(1); print('Processing...'); result = {'status': 'processing'}"
        }
      },
      {
        "name": "Task C",
        "type": "python",
        "handler": "python",
        "method": "python/execute",
        "depends_on": ["Task B"],
        "params": {
          "code": "print('Complete!'); result = {'status': 'done', 'success': True}"
        }
      }
    ]
  },
  "workflow_id": "test-001"
}
EOF
```

### 3. Submit Workflow
```bash
curl -X POST http://localhost:8000/workflows/submit \
  -H "Content-Type: application/json" \
  -d @test-workflow.json
```

### 4. Check Status
```bash
# Wait a few seconds, then:
curl http://localhost:8000/workflows/test-001 | python -m json.tool
```

### 5. Get Results
```bash
# List tasks
curl http://localhost:8000/tasks/list

# Get individual task results
curl http://localhost:8000/tasks/{task_id} | python -m json.tool
```

## Workflow Execution Flow

1. **API receives workflow** → Writes to Redis stream `{shard:N}:workflow:load`
2. **WorkflowLoaderWorker** → Validates and forwards to `workflow:submitted`
3. **DependencyWorker** → Creates tasks with dependencies, writes to task streams
4. **TaskExecutionWorker** → Executes Python code, captures results and stdout
5. **Results stored in Redis** → Accessible via API

## Key Insights

### What Docker Solves
- **No subprocess management** - Docker handles all process lifecycle
- **No port conflicts** - Docker network isolation
- **Automatic restarts** - Docker restart policies
- **Health monitoring** - Docker health checks
- **Log aggregation** - `docker-compose logs`

### Critical Configuration
- **MUST set `REDIS_CLUSTER_NODES=redis:6379`** in worker environments
- The `--redis-url` parameter is ignored by workers
- Dependencies in workflows use task **names**, not IDs
- Task IDs are generated internally by the system

### System Requirements
- Docker and Docker Compose
- Ports 8000 (API), 8004 (UI), 6379 (Redis)
- No other dependencies - everything runs in containers

## Monitoring

### Check Container Status
```bash
docker-compose -f docker-compose-proper.yml ps
```

### View Logs
```bash
# All logs
docker-compose -f docker-compose-proper.yml logs -f

# Specific service
docker-compose -f docker-compose-proper.yml logs worker-task-execution
```

### Health Check
```bash
curl http://localhost:8000/health/
# Response: {"status":"healthy","components":{"api":"healthy","redis":"healthy"}}
```

## Troubleshooting

### Workers Can't Connect to Redis
- Check `REDIS_CLUSTER_NODES` environment variable
- Must be set to `redis:6379` not `localhost:6379`

### Workflow Validation Failed
- Check task dependencies reference task names exactly
- Task names are case-sensitive
- Don't use IDs in `depends_on` field

### No Task Results
- Ensure all essential workers are running
- Check worker logs for errors
- Verify Redis connectivity

## Conclusion

The Docker-based deployment successfully eliminates the subprocess management issues that plagued the native Python deployment. By leveraging Docker's process management capabilities and fixing the Redis connection configuration, Gleitzeit 0.0.7 is now fully operational for workflow orchestration and task execution.