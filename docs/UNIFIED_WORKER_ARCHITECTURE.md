# Unified Worker Architecture

## Overview

As of version 0.0.7, Gleitzeit uses a **unified worker architecture** where API, UI, and processing workers all follow the same self-registration pattern. This eliminates special-case code and makes the system more reliable and scalable.

## Key Concepts

### Everything is a Worker

In the unified architecture, there are no longer separate "services" and "workers". Instead:

- **API Worker** - Runs the Uvicorn API server and self-registers
- **UI Worker** - Runs the Uvicorn UI server and self-registers
- **Processing Workers** - Task execution, dependency resolution, etc.

All workers:
- Register themselves in Redis with `{shard:0}:worker:registry:{type}:{id}`
- Maintain their own heartbeat loop (30s interval, 60s TTL)
- Use `os.getpid()` for stateless registration (always current PID)
- Gracefully unregister on shutdown
- Are monitored and auto-restarted by AsyncServiceManager

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│              gleitzeit serve                            │
│            (serve_unified.py)                           │
│                                                         │
│  - Loads config                                         │
│  - Builds CLI override dict                             │
│  - Creates AsyncServiceManager                          │
│  - Calls start_all_workers(overrides)                   │
└─────────────────────────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────┐
│          AsyncServiceManager (Simplified)                │
│       (async_process_manager.py)                        │
│                                                         │
│  1. start_all_workers(overrides):                       │
│     - Check for existing workers in Redis               │
│     - If workers exist: show message, exit              │
│     - Iterate workers from config                       │
│     - Apply CLI overrides (--api-port, etc.)            │
│     - Call start_worker() for each                      │
│                                                         │
│  2. start_worker(config):                               │
│     - Store config in Redis                             │
│     - Spawn: python -m gleitzeit.workers.runner         │
│     - Track subprocess                                  │
│                                                         │
│  3. monitor_loop():                                     │
│     - Check if workers died                             │
│     - Restart if needed                                 │
│     - Sleep, repeat                                     │
└─────────────────────────────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
         ↓               ↓               ↓
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ APIWorker    │ │ UIWorker     │ │ TaskWorker   │
│ (subprocess) │ │ (subprocess) │ │ (subprocess) │
│              │ │              │ │              │
│ - Uvicorn    │ │ - Uvicorn    │ │ - Process    │
│   API        │ │   UI         │ │   streams    │
│ - Self-      │ │ - Self-      │ │ - Self-      │
│   register   │ │   register   │ │   register   │
│ - Heartbeat  │ │ - Heartbeat  │ │ - Heartbeat  │
└──────────────┘ └──────────────┘ └──────────────┘
         │               │               │
         └───────────────┼───────────────┘
                         ↓
                  ┌─────────────┐
                  │   Redis     │
                  │  (Registry) │
                  │             │
                  │ All workers │
                  │ visible via │
                  │ gleitzeit ps│
                  └─────────────┘
```

## Configuration

### Adding Workers to Config

Workers are defined in `gleitzeit.yaml`:

```yaml
workers:
  # API service as worker
  - worker_type: api
    worker_class: gleitzeit.workers.api_worker.APIWorker
    count: 1
    extra:
      host: 0.0.0.0
      port: 8000
      dev_mode: false

  # UI service as worker
  - worker_type: ui
    worker_class: gleitzeit.workers.ui_worker.UIWorker
    count: 1
    extra:
      host: 0.0.0.0
      port: 8004
      api_port: 8000
      dev_mode: false

  # Processing workers
  - worker_type: task_execution
    worker_class: gleitzeit.workers.task_execution_worker.TaskExecutionWorker
    count: 2
    max_concurrent: 5
    batch_size: 10
    block_timeout: 5000
```

### CLI Overrides

CLI flags override config values:

```bash
# Override API port
gleitzeit serve --api-port 8080

# Override UI port
gleitzeit serve --ui-port 8081

# Run in dev mode
gleitzeit serve --dev-mode

# Start only API/UI (no processing workers)
gleitzeit serve --api-only

# Start only processing workers (no API/UI)
gleitzeit serve --workers-only

# Skip UI
gleitzeit serve --no-ui
```

## Worker Types

Gleitzeit has **17 worker types** organized into core execution workers, support workers, and infrastructure workers. All workers follow the same self-registration pattern.

### Core Execution Workers

#### 1. **Task Execution Worker**
**File:** `task_execution_worker.py`
**Purpose:** Executes tasks using registered handlers
**Listens to:** `{shard:X}:task:ready`
**Count:** 2+ (horizontally scalable)

**Responsibilities:**
- Load appropriate handler for task protocol
- Execute task with circuit breaker protection
- Store results in Redis
- Emit `task:completed` or `task:failed` events
- Handle timeouts and errors

**Related Docs:** [UNIFIED_WORKER_ARCHITECTURE.md](#), Handler documentation in `/docs/handlers/`

#### 2. **Dependency Worker**
**File:** `dependency_worker.py`
**Purpose:** Manages task dependencies and readiness
**Listens to:** `{shard:X}:task:completed`, `{shard:X}:task:failed`, `{shard:X}:workflow:submitted`
**Count:** 1-2

**Responsibilities:**
- Track task completion status
- Check if task dependencies are satisfied
- Resolve input variables from dependency outputs
- Move ready tasks to execution queue
- Update consolidated workflow state

**Related Docs:** [CONSOLIDATED_STATE_ARCHITECTURE.md](CONSOLIDATED_STATE_ARCHITECTURE.md)

#### 3. **Workflow Loader Worker**
**File:** `workflow_loader_worker_v2.py`
**Purpose:** Validates and loads workflow definitions
**Listens to:** `{shard:X}:workflow:load`
**Count:** 2+ (can scale with load)

**Responsibilities:**
- Validate workflow structure and syntax
- Transform tasks from simplified to protocol-based schema
- Verify handler capabilities for all tasks
- Create task records in Redis
- Emit `workflow:submitted` event

**Related Docs:** [WORKFLOW_VALIDATION_ARCHITECTURE.md](WORKFLOW_VALIDATION_ARCHITECTURE.md)

#### 4. **Workflow Submission Worker**
**File:** `workflow_submission_worker.py`
**Purpose:** Handles workflow submissions from workflow handler
**Listens to:** `{shard:X}:workflow:submission`
**Count:** 1

**Responsibilities:**
- Receive nested workflow submissions
- Route to workflow loader
- Track parent-child workflow relationships
- Manage workflow invocation metadata

**Related Docs:** [WORKFLOW_HANDLER_EXECUTION_FLOW.md](WORKFLOW_HANDLER_EXECUTION_FLOW.md)

#### 5. **Workflow Monitor Worker**
**File:** `workflow_monitor_worker.py`
**Purpose:** Detects workflow completion and updates parent tasks
**Listens to:** `{shard:X}:task:completed`, `{shard:X}:task:failed`
**Count:** 1

**Responsibilities:**
- Monitor all tasks in workflows
- Detect when all tasks complete
- Mark workflow as completed or failed
- Wake parent task if workflow was invoked from another workflow
- Update workflow completion timestamp

**Related Docs:** [WORKFLOW_HANDLER_EXECUTION_FLOW.md](WORKFLOW_HANDLER_EXECUTION_FLOW.md)

#### 6. **Timer Worker**
**File:** `timer_worker.py`
**Purpose:** Manages timer tasks (sleep, delayed execution)
**Listens to:** Direct Redis scan of timer metadata
**Count:** 2+ (horizontally scalable)

**Responsibilities:**
- Scan timer metadata every 1 second
- Check for expired timers
- Atomically delete expired timers and wake tasks
- Support sleep and retry timer types
- No buckets or registry (simple direct-scan design)

**Related Docs:** [timer-system.md](timer-system.md)

#### 7. **Signal Worker**
**File:** `signal_worker.py`
**Purpose:** Manages signal communication (wait/send/broadcast)
**Listens to:** Direct Redis scan of signal metadata
**Count:** 1 (uses leader election)

**Responsibilities:**
- Leader election for signal processing
- Match signal senders with waiters
- Handle broadcast signals across workflows
- Timeout expired signal waits
- Support scoped and broadcast signals

**Related Docs:** [SIGNAL_SEND_BROADCAST.md](SIGNAL_SEND_BROADCAST.md)

#### 8. **Retry Worker**
**File:** `retry_worker.py`
**Purpose:** Handles task retries with exponential backoff
**Listens to:** `{shard:X}:task:retry`
**Count:** 1-2

**Responsibilities:**
- Classify errors (retryable vs non-retryable)
- Implement exponential backoff with jitter
- Track retry attempts and history
- Move to failed state after max retries
- Dead letter queue for non-retryable errors

**Related Docs:** [retry_mechanism.md](retry_mechanism.md), [RECOVERY_SYSTEM.md](RECOVERY_SYSTEM.md)

### Infrastructure Workers

#### 9. **API Worker**
**File:** `api_worker.py`
**Purpose:** Serves REST API and WebSocket connections
**Port:** 8000 (default, configurable)
**Count:** 1+ (horizontally scalable with load balancing)

**Responsibilities:**
- Serve FastAPI REST API
- Handle WebSocket connections
- Session-based authentication
- Workflow submission endpoint
- Status and monitoring endpoints
- Port conflict detection

**Related Docs:** [api/QUICK_START.md](api/QUICK_START.md), [api/API_AUTHENTICATION.md](api/API_AUTHENTICATION.md)

#### 10. **UI Worker**
**File:** `ui_worker.py`
**Purpose:** Serves web UI for workflow monitoring
**Port:** 8004 (default, configurable)
**Count:** 1

**Responsibilities:**
- Serve HTML/CSS/JS frontend
- Real-time workflow status display
- Task timeline visualization
- Event log viewing
- Worker registry display

**Related Docs:** [UNIFIED_WORKER_ARCHITECTURE.md](#)

### Support Workers

#### 11. **Reconciliation Worker**
**File:** `reconciliation_worker.py`
**Purpose:** Cleanup and garbage collection
**Scan Interval:** 60 seconds (configurable)
**Count:** 1

**Responsibilities:**
- Clean up orphaned tasks
- Remove expired workflows
- Prune old events from streams
- Maintain Redis memory usage
- Detect and recover zombie workflows

**Configuration:**
```yaml
- worker_type: reconciliation
  worker_class: gleitzeit.workers.reconciliation_worker.WorkflowReconciliationWorker
  count: 1
  extra:
    scan_interval: 60
    zombie_threshold: 600
```

#### 12. **Loki Exporter Worker**
**File:** `loki_exporter_worker.py`
**Purpose:** Exports logs to Grafana Loki
**Poll Interval:** 5 seconds (configurable)
**Count:** 1

**Responsibilities:**
- Poll Redis for new logs
- Format logs for Loki ingestion
- Batch and push to Loki endpoint
- Add workflow/task metadata labels
- Handle Loki connection failures

**Note:** Configured via `logging.loki.enabled` in gleitzeit.yaml, not in workers list.

**Configuration:**
```yaml
logging:
  loki:
    enabled: true
    url: http://localhost:3100
    batch_size: 100
    poll_interval: 5
```

#### 13. **File Loader Worker**
**File:** `file_loader_worker.py`
**Purpose:** Loads workflow definitions from files
**Status:** Available but not in default config
**Count:** 0-1 (optional)

**Responsibilities:**
- Watch filesystem for workflow files (.yaml, .json)
- Parse workflow definitions
- Submit workflows automatically
- Hot-reload on file changes
- Support directory watching

**Use Case:** Development environments, automated workflow deployment

#### 14. **Health Monitor Worker**
**File:** `health_monitor_worker.py`
**Purpose:** Monitors system health
**Status:** Available but not in default config
**Count:** 0-1 (optional)

**Responsibilities:**
- Track worker heartbeats
- Monitor Redis performance
- Alert on worker failures
- Check stream lengths
- Expose health metrics

**Use Case:** Production environments with monitoring dashboards

#### 15. **Redis Monitor Worker**
**File:** `redis_monitor_worker.py`
**Purpose:** Monitors Redis metrics
**Status:** Available but not in default config
**Count:** 0-1 (optional)

**Responsibilities:**
- Track stream lengths and lag
- Monitor memory usage
- Detect slow commands
- Alert on Redis issues
- Collect performance metrics

**Use Case:** Large deployments, performance tuning

#### 16. **Replay Worker**
**File:** `replay_worker.py`
**Purpose:** Replays events for debugging
**Status:** Available but not in default config
**Count:** 0-1 (optional)

**Responsibilities:**
- Capture event streams
- Store event history
- Replay events for debugging
- Support time-travel debugging
- Event filtering and search

**Use Case:** Debugging complex workflows, post-mortem analysis

### Deprecated Workers

#### 17. **Time Advance Worker** ⚠️
**File:** `time_advance_worker.py`
**Status:** Deprecated (kept for backward compatibility)
**Replaced by:** Direct timer scanning in TimerWorker

**Note:** The old bucket-based timer system with TimeAdvanceWorker was replaced by a simpler direct-scan approach in version 0.0.7. This worker is no longer used but remains in the codebase for backward compatibility.

**Related Docs:** [timer-system.md](timer-system.md#migration-from-old-system)

## Worker Self-Registration

### How It Works

Each worker registers itself in Redis using the **worker registry pattern**:

**APIWorker Example:**
```python
async def _register_worker(self):
    """Register API worker in Redis - includes port info"""
    worker_info = {
        "worker_type": "api",
        "worker_id": self.config.worker_id,
        "status": "running",
        "pid": os.getpid(),  # ✅ ALWAYS CURRENT (stateless!)
        "host": self.host,
        "port": str(self.port),
        "started_at": self.start_time.isoformat(),
    }

    # Use worker registry pattern
    key = f"{{shard:0}}:worker:registry:api:{self.config.worker_id}"
    await self.redis.hset(key.encode(), mapping={
        k.encode(): str(v).encode() for k, v in worker_info.items()
    })
    await self.redis.expire(key.encode(), 60)  # 60s TTL

async def _heartbeat_loop(self):
    """Maintain heartbeat to prevent TTL expiry"""
    while self._running:
        await asyncio.sleep(30)  # Heartbeat every 30s
        await self._register_worker()  # Refresh registration
```

### Benefits of Self-Registration

1. **Stateless** - Uses `os.getpid()` directly, not memory
2. **No external heartbeat manager** - Each worker manages itself
3. **Graceful shutdown** - Workers unregister immediately
4. **Proven reliable** - Pattern works for 4+ hours in production
5. **Distributed-friendly** - No centralized state to synchronize

## Service Discovery

### Using `gleitzeit ps`

All workers are visible through the unified `ps` command:

```bash
$ gleitzeit ps

📊 Service Registry Status:
────��───────────────────────────────────────────────────────
Service         Host        Port    Mode      Status    Uptime
────────────────────────────────────────────────────────────
api             0.0.0.0     8000    native    ✅ healthy 2h 15m
ui              0.0.0.0     8004    native    ✅ healthy 2h 15m
python-1        localhost   N/A     docker    ✅ healthy 2h 15m
python-2        localhost   N/A     docker    ✅ healthy 2h 15m
timer-1         localhost   N/A     native    ✅ healthy 2h 15m

Summary: 5 healthy, 0 stale | Total registered: 5
```

### Registry Keys

**New unified pattern:**
```
{shard:0}:worker:registry:api:api-instance-a
{shard:0}:worker:registry:ui:ui-instance-a
{shard:0}:worker:registry:python:python-1
{shard:0}:worker:registry:timer:timer-1
```

**Old pattern (deprecated):**
```
service:registry:api
service:registry:ui
```

## Horizontal Scaling

### Multiple API Instances

Run multiple API workers on different ports:

```bash
# Instance A
gleitzeit serve --api-only --api-port 8000

# Instance B
gleitzeit serve --api-only --api-port 8001

# Instance C
gleitzeit serve --api-only --api-port 8002
```

All instances share:
- Same Redis
- Same worker pool
- Same service discovery

### Load Balancing

Use a load balancer (nginx, HAProxy) to distribute traffic:

```nginx
upstream gleitzeit_api {
    server localhost:8000;
    server localhost:8001;
    server localhost:8002;
}

server {
    listen 80;
    location / {
        proxy_pass http://gleitzeit_api;
    }
}
```

## Idempotent Behavior

### Native Mode is Now Idempotent

Like Docker mode, native mode is safe to run multiple times:

```bash
# First run - starts services
$ gleitzeit serve
✅ Started worker_api (PID: 12345)
✅ Started worker_ui (PID: 12346)

# Second run - detects existing, doesn't fail!
$ gleitzeit serve
⚠️  Found 2 services already running
   Services are already registered in Redis
   Use --restart to force restart, or stop services first

   To stop: pkill -f 'gleitzeit'
   Or use: gleitzeit ps

# Force restart if needed
$ gleitzeit serve --restart
🔄 Restarting services...
✅ Started worker_api (PID: 12347)
✅ Started worker_ui (PID: 12348)
```

### How It Works

1. **Check existing workers** - Scans `{shard:0}:worker:registry:*` keys
2. **Verify they're alive** - Checks PIDs with `psutil`
3. **Clean up stale entries** - Removes dead workers from registry
4. **Exit gracefully** - If workers exist and no `--restart` flag

## Port Conflict Detection

### Workers Check Ports

Each worker checks if its port is available before starting:

**APIWorker:**
```python
async def on_initialize(self):
    """Initialize API application"""
    # Check if port is already in use
    if self._is_port_in_use(self.port, self.host):
        error_msg = f"Cannot start API: Port {self.port} is already in use. "
        error_msg += f"Either stop the existing service or use --api-port to specify a different port."
        self.logger.error(error_msg)
        raise RuntimeError(error_msg)

    # ... proceed with initialization
```

### Clear Error Messages

```bash
$ gleitzeit serve --api-port 8000
❌ Error: Process worker_api failed to start
   Cannot start API: Port 8000 is already in use.
   Either stop the existing service or use --api-port to specify a different port.
```

## Code Simplification

### Before: Separate Code Paths (~600 lines)

```python
# AsyncServiceManager (OLD)
class AsyncServiceManager:
    async def start_api(self, ...):      # 70 lines
        # Special API startup logic

    async def start_ui(self, ...):       # 70 lines
        # Special UI startup logic

    async def _service_heartbeat_loop(self, ...):  # 80 lines
        # External heartbeat management

    async def start_worker(self, ...):   # Generic worker startup
```

### After: Unified Worker Handling (~200 lines)

```python
# AsyncServiceManager (NEW)
class AsyncServiceManager:
    def _apply_overrides(self, worker_config, cli_overrides):
        """Apply CLI flags to any worker config"""
        # Unified override logic for all workers

    async def start_worker(self, worker_config):
        """Start ANY worker (API, UI, or processing)"""
        # Same code path for all workers!

    async def start_all_workers(self, cli_overrides):
        """Start all workers from config"""
        for worker_config in self.config.get('workers', []):
            config = self._apply_overrides(worker_config, cli_overrides)
            await self.start_worker(config)
```

**Result:** ~400 lines of complex code removed! ✅

## Migration Guide

### From Old Architecture

**Old code (0.0.6):**
```python
# API/UI were special services
await manager.start_api(port=8000)
await manager.start_ui(port=8004)
await manager.start_essential_workers()

# External heartbeat loop
heartbeat_task = asyncio.create_task(manager._service_heartbeat_loop())
```

**New code (0.0.7):**
```python
# Everything is a worker
cli_overrides = {
    'api_port': 8000,
    'ui_port': 8004,
    'dev_mode': False,
}
await manager.start_all_workers(cli_overrides)

# No external heartbeat - workers manage themselves!
```

### Updating Custom Deployments

1. **Update `gleitzeit.yaml`** - Add API/UI workers to config
2. **Remove old scripts** - No need for separate API/UI startup
3. **Use unified commands** - `gleitzeit serve` handles everything
4. **Update monitoring** - Use `gleitzeit ps` for all services

## Troubleshooting

### Services Won't Start

**Problem:** `Process worker_api died immediately with code 1`

**Check:**
1. Is port already in use? `lsof -i :8000`
2. Are workers already running? `gleitzeit ps`
3. Check logs: Workers log to Redis (queryable via UI)

**Solution:**
```bash
# Stop existing services
pkill -f gleitzeit

# Or force restart
gleitzeit serve --restart
```

### Stale Registry Entries

**Problem:** `gleitzeit ps` shows workers that aren't running

**Cause:** Workers crashed without graceful shutdown

**Solution:**
```bash
# Registry auto-cleans on next startup
gleitzeit serve

# Or manually clean
redis-cli KEYS "{shard:0}:worker:registry:*" | xargs redis-cli DEL
```

### Multiple Instances Conflict

**Problem:** Running multiple instances on same machine with same ports

**Solution:**
```bash
# Use different ports for each instance
gleitzeit serve --api-port 8000 --ui-port 8004  # Instance A
gleitzeit serve --api-port 8001 --ui-port 8005  # Instance B
```

## Performance Characteristics

### Memory Usage

**Same as before** - Each worker runs in separate subprocess:
- Main process: AsyncServiceManager (minimal memory)
- API worker: Uvicorn process
- UI worker: Uvicorn process
- N processing workers: One subprocess each

### Startup Time

**Potentially faster** - Workers start in parallel:
```
Before: API → wait 2s → UI → Workers (sequential)
After:  All workers spawn concurrently (parallel)
```

### Heartbeat Overhead

**Trade-off:**
- Before: 1 centralized heartbeat loop (30s interval)
- After: Each worker has own heartbeat (30s interval each)

**Impact:** More Redis writes, but better isolation and reliability

## Future Enhancements

### Planned Improvements

1. **Configurable TTL** - Make 60s TTL configurable per worker type
2. **Health checks** - Add HTTP health endpoints to workers
3. **Metrics tracking** - Include request counts in worker registration
4. **Process verification** - Verify PID before re-registration
5. **Load balancer integration** - Auto-register with load balancer

### Long-term Vision

- Migrate to service mesh (Consul, etcd) for production
- Kubernetes operator for cloud deployments
- Auto-scaling based on queue depth
- Cross-datacenter worker sharing

## Best Practices

### Development

```bash
# Use dev mode for hot reload
gleitzeit serve --dev-mode

# Check worker status frequently
watch -n 1 'gleitzeit ps'

# Use --restart for quick iteration
gleitzeit serve --restart --dev-mode
```

### Production

```bash
# Use systemd or supervisor for process management
# Let them handle restart on crash

# Monitor with gleitzeit ps
*/5 * * * * gleitzeit ps --format json > /var/log/gleitzeit-status.json

# Set up alerts for stale workers
# (TTL expired but process still in registry)
```

### Horizontal Scaling

```bash
# Dedicated API instances (high availability)
gleitzeit serve --api-only --api-port 8000  # Instance 1
gleitzeit serve --api-only --api-port 8001  # Instance 2

# Dedicated worker instances (processing power)
gleitzeit serve --workers-only  # Instance 3
gleitzeit serve --workers-only  # Instance 4
```

## Summary

The unified worker architecture simplifies Gleitzeit by:

1. ✅ **Eliminating special cases** - API/UI/workers all the same
2. ✅ **Using proven patterns** - Self-registration works for 4+ hours
3. ✅ **Reducing code complexity** - ~400 lines removed
4. ✅ **Improving reliability** - Stateless heartbeat, graceful shutdown
5. ✅ **Enabling scaling** - Multiple API/UI instances work naturally
6. ✅ **Making it idempotent** - Safe to run multiple times

The result is a cleaner, more maintainable, and more scalable system! 🎉
