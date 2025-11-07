# Unified Worker Architecture - Design Document

## Executive Summary

**Proposal:** Treat API and UI as workers in the configuration, eliminating the need for AsyncServiceManager's special-case code and achieving a fully unified architecture.

**Key Insight:** If everything is a worker that self-registers, we don't need complex centralized management.

---

## Current Architecture Problems

### 1. Two Different Code Paths

**API/UI (Special Case):**
- Started by `AsyncServiceManager.start_api()` / `start_ui()`
- Managed externally with centralized heartbeat
- Uses memory-based state (`self.process_manager.processes`)
- Different registry keys (`service:registry:*`)
- ❌ Stateful, can become stale

**Workers (Standard):**
- Started by `AsyncServiceManager.start_worker()`
- Self-managing with own heartbeat loop
- Uses `os.getpid()` directly (stateless)
- Worker registry keys (`{shard:0}:worker:registry:*`)
- ✅ Stateless, proven to work for 4+ hours

### 2. Code Duplication

AsyncServiceManager has ~500 lines just for API/UI management:
- `start_api()` - 70 lines
- `start_ui()` - 70 lines
- `_service_heartbeat_loop()` - 80 lines
- Port checking, process management, registry logic

This is all **duplicated** from what workers already do better!

---

## Proposed Architecture: Everything is a Worker

### Core Concept

**Add API and UI to the workers configuration:**

```yaml
# gleitzeit.yaml
workers:
  # API as a worker
  - worker_type: api
    worker_class: gleitzeit.workers.api_worker.APIWorker
    count: 1
    extra:
      host: 0.0.0.0
      port: 8000
      dev_mode: false

  # UI as a worker
  - worker_type: ui
    worker_class: gleitzeit.workers.ui_worker.UIWorker
    count: 1
    extra:
      host: 0.0.0.0
      port: 8004
      api_port: 8000
      dev_mode: false

  # All processing workers (no change)
  - worker_type: task_execution
    worker_class: gleitzeit.workers.task_execution_worker.TaskExecutionWorker
    count: 2
    max_concurrent: 5
    # ... rest of config
```

### How It Works

**1. Startup Flow:**
```
gleitzeit serve
  ↓
serve_unified.py loads config
  ↓
For each worker in config (including api, ui):
  ↓
AsyncServiceManager.start_worker(worker_config)
  ↓
Spawns: python -m gleitzeit.workers.runner --config-key <redis_key>
  ↓
Runner loads worker class (APIWorker, UIWorker, or TaskWorker)
  ↓
Worker.initialize() → Worker.run()
  ↓
Worker self-registers in Redis with heartbeat
```

**2. Worker Self-Management:**
```python
# APIWorker (same pattern as TaskWorker)
class APIWorker(BaseWorker):
    async def run(self):
        self._running = True
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        # Start Uvicorn server
        await self.server.serve()

    async def _register_worker(self):
        # Uses os.getpid() - always current!
        worker_info = {
            "worker_type": "api",
            "pid": os.getpid(),  # ✅ Stateless
            "port": self.port,
            ...
        }
        key = f"{{shard:0}}:worker:registry:api:{self.worker_id}"
        await self.redis.hset(key, worker_info)
        await self.redis.expire(key, 60)
```

**3. Service Discovery:**
```bash
$ gleitzeit ps

# Shows ALL services uniformly:
WORKER TYPE  HOST       PORT  MODE    STATUS     UPTIME
api          localhost  8000  native  ✅ healthy 4h 13m
ui           localhost  8004  native  ✅ healthy 4h 13m
python-1     localhost  N/A   docker  ✅ healthy 4h 13m
timer-1      localhost  N/A   native  ✅ healthy 4h 13m
...
```

---

## Implementation Changes

### 1. Already Complete ✅

- ✅ `APIWorker` class created ([api_worker.py](src/gleitzeit/workers/api_worker.py))
- ✅ `UIWorker` class created ([ui_worker.py](src/gleitzeit/workers/ui_worker.py))
- ✅ Both inherit from `BaseWorker` and self-register
- ✅ Worker runner already supports loading any worker class

### 2. Configuration Changes

**Update default config** ([gleitzeit.yaml.default](src/gleitzeit/config/gleitzeit.yaml.default)):

```yaml
workers:
  # API service as worker (NEW)
  - worker_type: api
    worker_class: gleitzeit.workers.api_worker.APIWorker
    count: 1
    extra:
      host: ${API_HOST:-0.0.0.0}
      port: ${API_PORT:-8000}
      dev_mode: false

  # UI service as worker (NEW)
  - worker_type: ui
    worker_class: gleitzeit.workers.ui_worker.UIWorker
    count: 1
    extra:
      host: ${UI_HOST:-0.0.0.0}
      port: ${UI_PORT:-8004}
      api_port: ${API_PORT:-8000}
      dev_mode: false

  # Existing workers (no changes needed)
  - worker_type: task_execution
    worker_class: gleitzeit.workers.task_execution_worker.TaskExecutionWorker
    # ... rest unchanged
```

### 3. AsyncServiceManager Simplification

**Current `start_all()` method:**
```python
async def start_all(self, ...):
    await self._init_smart_manager()
    await validate_sharding_config(...)

    # Special cases for API/UI
    if not no_api:
        await self.start_api(port=api_port, dev_mode=dev_mode)
    if not no_ui and not no_api:
        await self.start_ui(port=ui_port, api_port=api_port, dev_mode=dev_mode)

    # Workers
    if not no_workers:
        await self.start_essential_workers()
```

**New simplified `start_all()` method:**
```python
async def start_all(self, api_port=8000, ui_port=8004, no_ui=False,
                    no_api=False, no_workers=False, dev_mode=False, ...):
    await self._init_smart_manager()
    await validate_sharding_config(...)

    # Get all workers from config
    workers = self.config.get('workers', [])

    for worker_config in workers:
        worker_type = worker_config.get('worker_type')

        # Apply CLI flags to filter workers
        if no_api and worker_type == 'api':
            continue
        if no_ui and worker_type == 'ui':
            continue
        if no_workers and worker_type not in ['api', 'ui']:
            continue

        # Apply CLI overrides to worker config
        if worker_type == 'api':
            worker_config = self._apply_api_overrides(worker_config, api_port, dev_mode)
        elif worker_type == 'ui':
            worker_config = self._apply_ui_overrides(worker_config, ui_port, api_port, dev_mode)

        # Start worker (same code path for all workers!)
        await self.start_worker(worker_config)

    return await self.process_manager.monitor_processes()
```

**Helper methods:**
```python
def _apply_api_overrides(self, config, port, dev_mode):
    """Apply CLI overrides to API worker config"""
    config = config.copy()
    if 'extra' not in config:
        config['extra'] = {}
    config['extra']['port'] = port
    config['extra']['dev_mode'] = dev_mode
    return config

def _apply_ui_overrides(self, config, port, api_port, dev_mode):
    """Apply CLI overrides to UI worker config"""
    config = config.copy()
    if 'extra' not in config:
        config['extra'] = {}
    config['extra']['port'] = port
    config['extra']['api_port'] = api_port
    config['extra']['dev_mode'] = dev_mode
    return config
```

### 4. Code Removal

**Can be deleted entirely:**
- ❌ `AsyncServiceManager.start_api()` - ~70 lines
- ❌ `AsyncServiceManager.start_ui()` - ~70 lines
- ❌ `AsyncServiceManager._service_heartbeat_loop()` - ~80 lines
- ❌ `AsyncServiceManager._is_port_in_use()` - Port checking now in worker initialization
- ❌ Special-case service registration logic

**Total removal: ~300-400 lines of complex, stateful code!**

---

## Benefits

### 1. Unified Architecture ✅

**Before:**
- API/UI: Special subprocess management + external heartbeat
- Workers: Worker runner + self-heartbeat
- Two completely different code paths

**After:**
- Everything: Worker runner + self-heartbeat
- One code path for all services

### 2. Simplified Codebase ✅

- **Remove ~400 lines** of complex code from AsyncServiceManager
- **No special cases** for API/UI
- **Easier to understand** - one pattern for everything
- **Easier to maintain** - less code, less bugs

### 3. Better Reliability ✅

- **Stateless heartbeat** - Uses `os.getpid()` directly (always current)
- **Proven pattern** - Same code that keeps workers running for 4+ hours
- **No memory drift** - No external state that can become stale
- **Self-contained** - Each worker manages its own lifecycle

### 4. Horizontal Scaling ✅

**Starting multiple API instances:**
```bash
# Instance 1
gleitzeit serve --api-only --api-port 8000

# Instance 2
gleitzeit serve --api-only --api-port 8001

# gleitzeit ps shows both:
api-instance-a  localhost  8000  ✅ healthy
api-instance-b  localhost  8001  ✅ healthy
```

All instances share same Redis, same worker pool, perfect for scaling!

### 5. Consistent Service Discovery ✅

**Unified registry keys:**
```
{shard:0}:worker:registry:api:api-instance-a
{shard:0}:worker:registry:ui:ui-instance-a
{shard:0}:worker:registry:python:python-1
{shard:0}:worker:registry:timer:timer-1
```

**Consistent data structure:**
```json
{
  "worker_type": "api",
  "worker_id": "api-instance-a",
  "pid": "12345",
  "status": "running",
  "host": "0.0.0.0",
  "port": "8000",
  "started_at": "2025-01-15T10:30:00"
}
```

**Same query tool:**
```bash
gleitzeit ps              # Shows everything
gleitzeit ps --type api   # Filter by type
gleitzeit ps --all        # Include stale services
```

### 6. Graceful Shutdown ✅

All workers (including API/UI) can:
- Unregister immediately on shutdown
- No waiting for 60-second TTL
- Clean service discovery state

---

## CLI Flag Handling

### Current Behavior Preserved

```bash
# Start everything (reads from config)
gleitzeit serve

# API only
gleitzeit serve --api-only --api-port 8001

# Workers only
gleitzeit serve --workers-only

# No UI
gleitzeit serve --no-ui

# Custom ports
gleitzeit serve --api-port 8080 --ui-port 8081

# Dev mode
gleitzeit serve --dev-mode
```

### Implementation

CLI flags override config values by modifying worker config before spawning:

```python
# serve_unified.py
for worker_config in workers:
    worker_type = worker_config.get('worker_type')

    # Filter based on flags
    if no_api and worker_type == 'api':
        continue
    if api_only and worker_type not in ['api', 'ui']:
        continue

    # Override config with CLI values
    if worker_type == 'api' and api_port:
        worker_config['extra']['port'] = api_port
    if worker_type == 'api' and dev_mode:
        worker_config['extra']['dev_mode'] = True

    await manager.start_worker(worker_config)
```

---

## Migration Path

### Phase 1: Add Workers to Config ✅
1. Update `gleitzeit.yaml.default` with api/ui workers
2. Document new configuration format
3. Keep backward compatibility (CLI flags still work)

### Phase 2: Update serve_unified.py
1. Modify `start_all()` to iterate all workers from config
2. Add helper methods for CLI override merging
3. Remove calls to `start_api()` / `start_ui()`

### Phase 3: Remove Old Code
1. Delete `start_api()` method
2. Delete `start_ui()` method
3. Delete `_service_heartbeat_loop()` method
4. Clean up imports and unused code

### Phase 4: Update Documentation
1. Update README with new architecture explanation
2. Update examples showing API/UI as workers
3. Document horizontal scaling patterns

### Phase 5: Testing
1. Test `gleitzeit serve` starts all workers
2. Test `gleitzeit ps` shows all services
3. Test horizontal scaling (multiple API instances)
4. Test graceful shutdown
5. Test CLI flag overrides work correctly

---

## Backward Compatibility

### Configuration

**Old configs without api/ui workers still work:**
- CLI flags `--api-port`, `--ui-port` still apply
- Default behavior: Start API on 8000, UI on 8004
- Migration: Add api/ui to workers section over time

**New configs with api/ui workers:**
- Config values used as defaults
- CLI flags override config
- Better control over service placement

### Service Discovery

**Old registry keys** (`service:registry:api`):
- Deprecated but not breaking
- Can coexist temporarily during migration
- `gleitzeit ps` checks both patterns

**New registry keys** (`{shard:0}:worker:registry:api:*`):
- Preferred going forward
- Better sharding support
- Consistent with all workers

---

## Edge Cases and Solutions

### Edge Case 1: Multiple API Workers in Config

**Scenario:**
```yaml
workers:
  - worker_type: api
    worker_class: gleitzeit.workers.api_worker.APIWorker
    count: 2  # Start 2 API instances
```

**Solution:**
- Each gets unique worker_id: `api-1`, `api-2`
- Must use different ports (config or auto-increment)
- All register in same registry pattern

### Edge Case 2: Port Conflicts

**Scenario:** Two API workers try to bind same port

**Solution:**
- APIWorker checks port availability in `on_initialize()`
- Fails fast with clear error message
- User must configure different ports

### Edge Case 3: Worker-Specific Config for API/UI

**Scenario:** User wants API-specific timeout settings

**Solution:**
```yaml
workers:
  - worker_type: api
    worker_class: gleitzeit.workers.api_worker.APIWorker
    extra:
      port: 8000
      timeout: 300  # API-specific setting
      max_connections: 1000
```

Extra config passed through `WorkerConfig.extra`, accessible in worker.

### Edge Case 4: Docker vs Native Mode

**Scenario:** Running API in Docker, workers native

**Current:** AsyncServiceManager handles Docker separately via serve_docker.py

**This design:** Focuses on native mode. Docker mode uses docker-compose (unchanged).

**Future:** Could unify Docker mode too by making docker-compose generate per-worker containers.

---

## Performance Considerations

### Memory

**Before:**
- AsyncServiceManager in main process
- API subprocess (Uvicorn)
- UI subprocess (Uvicorn)
- N worker subprocesses
- **Total:** 1 main + 2 services + N workers

**After:**
- AsyncServiceManager in main process
- API worker subprocess (Uvicorn)
- UI worker subprocess (Uvicorn)
- N worker subprocesses
- **Total:** 1 main + 2 services + N workers

**Same memory footprint!** Just cleaner architecture.

### Startup Time

**Before:**
```
Start API → Wait 2s → Start UI → Start workers
```

**After:**
```
Start all workers in parallel (async)
```

**Potential improvement:** Parallel startup = faster!

### Heartbeat Overhead

**Before:**
- 1 centralized heartbeat loop (30s interval)
- Checks all services, writes to Redis

**After:**
- Each worker has own heartbeat loop (30s interval)
- Each worker writes only its own data

**Trade-off:** More Redis writes, but better isolation and reliability.

---

## Security Considerations

### Process Isolation

**Same as before:**
- Each worker runs in separate subprocess
- API/UI have own process space
- No shared memory between workers

### Redis Access

**Same as before:**
- All workers connect to same Redis
- Service discovery data is public within cluster
- Authentication/authorization at API layer (unchanged)

### Port Binding

**Same as before:**
- API/UI bind to configured ports
- Port conflict detection prevents unauthorized binding
- Firewall rules apply normally

---

## Monitoring and Observability

### Health Checks

**Unified health monitoring:**
```bash
# All workers visible in one place
gleitzeit ps

# Filter by type
gleitzeit ps --type api
gleitzeit ps --type ui
gleitzeit ps --type python

# Check specific worker
gleitzeit ps --worker-id api-1
```

### Metrics

**Consistent metrics for all workers:**
- Heartbeat timestamp
- Uptime
- Process ID
- Memory usage (if psutil available)
- CPU usage (if psutil available)

**API/UI specific metrics:**
- Port number
- Request count (future)
- Error rate (future)

### Logging

**Same logging infrastructure:**
- All workers use LoggingMixin
- Redis-backed queryable logs
- Loki export (if enabled)
- Same log levels, sampling, TTLs

---

## Success Criteria

1. ✅ `gleitzeit serve` starts API, UI, and all workers
2. ✅ `gleitzeit ps` shows all services with consistent format
3. ✅ All workers self-register with stateless heartbeat
4. ✅ No memory-based state in service management
5. ✅ CLI flags (`--api-port`, `--no-ui`, etc.) work correctly
6. ✅ Horizontal scaling: Multiple API instances can run simultaneously
7. ✅ Graceful shutdown: Services unregister immediately
8. ✅ Code reduction: ~400 lines removed from AsyncServiceManager
9. ✅ Tests pass: All existing tests continue to work
10. ✅ Documentation updated: Architecture diagrams reflect new design

---

## Timeline Estimate

### Phase 1: Config Changes (1 hour)
- Update `gleitzeit.yaml.default`
- Add API/UI worker definitions
- Document new format

### Phase 2: AsyncServiceManager Refactor (3-4 hours)
- Rewrite `start_all()` to iterate workers
- Add CLI override helper methods
- Test worker spawning logic

### Phase 3: Code Removal (2 hours)
- Delete old `start_api()`, `start_ui()` methods
- Delete `_service_heartbeat_loop()`
- Clean up unused imports
- Run tests

### Phase 4: Testing (2-3 hours)
- Test basic `gleitzeit serve`
- Test all CLI flag combinations
- Test horizontal scaling
- Test graceful shutdown
- Test `gleitzeit ps` display

### Phase 5: Documentation (2 hours)
- Update README
- Update architecture diagrams
- Add horizontal scaling examples
- Update troubleshooting guide

**Total: ~10-12 hours**

---

## Risks and Mitigations

### Risk 1: Breaking Existing Deployments

**Risk:** Users with existing deployments might break

**Mitigation:**
- Maintain backward compatibility
- CLI flags continue to work
- Old registry keys coexist with new ones
- Clear migration guide in release notes

### Risk 2: Unforeseen Edge Cases

**Risk:** API/UI as workers might have edge cases we haven't considered

**Mitigation:**
- Thorough testing before release
- Beta period with early adopters
- Easy rollback (keep old code in separate branch)

### Risk 3: Performance Regression

**Risk:** New architecture might be slower

**Mitigation:**
- Benchmark startup time, heartbeat overhead
- Profile memory usage
- Compare before/after metrics
- Optimize if needed

---

## Alternatives Considered

### Alternative 1: Fix Heartbeat, Keep Separate Code Paths

**Approach:** Keep AsyncServiceManager but fix heartbeat to query process state

**Pros:**
- Smaller change
- Less risky

**Cons:**
- Still maintains two code paths
- Still has special-case logic
- Doesn't address fundamental architecture issue
- Doesn't reduce code complexity

**Decision:** Rejected. Doesn't solve the root problem.

### Alternative 2: Embed API/UI in Main Process

**Approach:** Run API/UI in same process as AsyncServiceManager

**Pros:**
- No subprocess overhead
- Simpler process management

**Cons:**
- API crash kills entire system
- Can't scale API independently
- Shared event loop (complexity)
- Against microservices principles

**Decision:** Rejected. Worse isolation and scaling.

### Alternative 3: Use Process Manager (systemd, supervisord)

**Approach:** Let external process manager handle everything

**Pros:**
- Battle-tested tools
- Better monitoring

**Cons:**
- Requires system dependencies
- Less portable
- No unified service discovery
- Complicates deployment

**Decision:** Rejected. Loses Gleitzeit's self-contained nature.

---

## Conclusion

**Treating API and UI as workers is the correct architectural choice** because:

1. ✅ **Unifies architecture** - One pattern for all services
2. ✅ **Eliminates stateful code** - No memory-based heartbeat
3. ✅ **Reduces complexity** - ~400 lines of code removed
4. ✅ **Improves reliability** - Uses proven self-registration pattern
5. ✅ **Enables scaling** - Multiple API/UI instances work naturally
6. ✅ **Simplifies monitoring** - Consistent service discovery
7. ✅ **Future-proof** - Better foundation for distributed systems

**Recommendation:** Implement this design to achieve a cleaner, more maintainable, and more scalable architecture for Gleitzeit.
