# Design: API and UI as Workers

## Core Concept

**Treat API and UI services as special worker types** instead of separately managed processes.

This unifies the architecture around the proven worker pattern that already works reliably.

---

## Current Architecture Problems

### API/UI (Centrally Managed)
```python
# async_process_manager.py
await self.start_api()  # Spawns subprocess
await self.start_ui()   # Spawns subprocess

# Separate heartbeat loop manages them externally
async def _service_heartbeat_loop(self):
    for name, info in self.process_manager.processes.items():
        service_data = {"pid": str(info.pid), ...}  # FROM MEMORY ❌
        await self.smart_manager.register_service(name, service_data)
```

**Problems:**
- ❌ Memory-based state (can become stale)
- ❌ No process verification
- ❌ External management (stateful dependency)
- ❌ Different key pattern (`service:registry:*`)

### Workers (Self-Managed) ✅
```python
# workers/base.py
class BaseWorker:
    async def _register_worker(self):
        worker_info = {
            "pid": os.getpid(),  # ALWAYS CURRENT ✅
            "worker_type": self.config.worker_type,
            ...
        }
        await self.redis.hset(key, mapping=worker_info)
        await self.redis.expire(key, 60)

    async def _heartbeat_loop(self):
        while self._running:
            await self._register_worker()  # Self-registers
            await asyncio.sleep(30)
```

**Advantages:**
- ✅ Stateless (uses `os.getpid()` directly)
- ✅ Self-contained (no external manager needed)
- ✅ Proven working (4+ hour uptime)
- ✅ Better for distributed systems

---

## Proposed Architecture: Unified Worker Pattern

### 1. Create APIWorker Class

```python
# src/gleitzeit/workers/api_worker.py

from gleitzeit.workers.base import BaseWorker
from gleitzeit.api.main import create_app
import uvicorn
import os

class APIWorker(BaseWorker):
    """API service as a worker - self-registers and manages heartbeat"""

    def __init__(self, config):
        super().__init__(config)
        self.worker_type = "api"
        self.host = config.get("host", "0.0.0.0")
        self.port = config.get("port", 8000)
        self.app = None
        self.server = None

    async def initialize(self):
        """Initialize API application"""
        await super().initialize()
        self.app = create_app()

    async def _process_loop(self):
        """Main API server loop"""
        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            loop="asyncio",
            log_config=None
        )
        self.server = uvicorn.Server(config)
        await self.server.serve()

    async def _register_worker(self):
        """Register API worker in Redis - includes port info"""
        worker_info = {
            "worker_type": "api",
            "worker_id": self.config.worker_id,
            "status": "running",
            "pid": os.getpid(),  # ✅ ALWAYS CURRENT
            "host": self.host,
            "port": str(self.port),
            "started_at": self.start_time.isoformat(),
        }

        # Use worker registry pattern (not service pattern)
        key = f"{{shard:0}}:worker:registry:api:{self.config.worker_id}"
        await self.redis.hset(key.encode(), mapping={
            k.encode(): str(v).encode() for k, v in worker_info.items()
        })
        await self.redis.expire(key.encode(), 60)

    async def shutdown(self):
        """Graceful shutdown - unregister from Redis"""
        if self.server:
            self.server.should_exit = True

        # Unregister immediately (don't wait for TTL)
        key = f"{{shard:0}}:worker:registry:api:{self.config.worker_id}"
        await self.redis.delete(key.encode())

        await super().shutdown()
```

### 2. Create UIWorker Class

```python
# src/gleitzeit/workers/ui_worker.py

from gleitzeit.workers.base import BaseWorker
import subprocess
import os
import signal

class UIWorker(BaseWorker):
    """UI service as a worker - self-registers and manages heartbeat"""

    def __init__(self, config):
        super().__init__(config)
        self.worker_type = "ui"
        self.host = config.get("host", "0.0.0.0")
        self.port = config.get("port", 3000)
        self.process = None

    async def _process_loop(self):
        """Main UI server loop"""
        # Start UI server subprocess
        env = os.environ.copy()
        env["HOST"] = self.host
        env["PORT"] = str(self.port)

        self.process = subprocess.Popen(
            ["npm", "start"],
            cwd=self.config.ui_path,
            env=env
        )

        # Wait for process to exit
        while self._running and self.process.poll() is None:
            await asyncio.sleep(1)

    async def _register_worker(self):
        """Register UI worker in Redis - includes port info"""
        worker_info = {
            "worker_type": "ui",
            "worker_id": self.config.worker_id,
            "status": "running",
            "pid": os.getpid(),  # ✅ Parent process PID
            "ui_pid": str(self.process.pid) if self.process else "N/A",
            "host": self.host,
            "port": str(self.port),
            "started_at": self.start_time.isoformat(),
        }

        key = f"{{shard:0}}:worker:registry:ui:{self.config.worker_id}"
        await self.redis.hset(key.encode(), mapping={
            k.encode(): str(v).encode() for k, v in worker_info.items()
        })
        await self.redis.expire(key.encode(), 60)

    async def shutdown(self):
        """Graceful shutdown - terminate UI process and unregister"""
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

        # Unregister immediately
        key = f"{{shard:0}}:worker:registry:ui:{self.config.worker_id}"
        await self.redis.delete(key.encode())

        await super().shutdown()
```

### 3. Update serve_unified.py

```python
# src/gleitzeit/cli/serve_unified.py

async def serve_unified_async(...):
    # Start API as worker
    if start_api:
        from gleitzeit.workers.api_worker import APIWorker
        api_config = WorkerConfig(
            worker_type="api",
            worker_id=f"api-{instance_id}",
            redis_url=redis_url,
            host=api_host,
            port=api_port
        )
        api_worker = APIWorker(api_config)
        await api_worker.start()  # ✅ Self-manages heartbeat

    # Start UI as worker
    if start_ui:
        from gleitzeit.workers.ui_worker import UIWorker
        ui_config = WorkerConfig(
            worker_type="ui",
            worker_id=f"ui-{instance_id}",
            redis_url=redis_url,
            host=ui_host,
            port=ui_port,
            ui_path=ui_path
        )
        ui_worker = UIWorker(ui_config)
        await ui_worker.start()  # ✅ Self-manages heartbeat

    # Start processing workers (no change)
    if start_workers:
        # ... existing worker startup code
```

---

## Benefits of This Approach

### 1. Unified Architecture ✅
- **One pattern for everything**: All services are workers
- **Consistent registry keys**: All use `{shard:0}:worker:registry:{type}:{id}`
- **Same code paths**: Initialization, heartbeat, shutdown
- **Easier to understand**: No special cases

### 2. Stateless by Design ✅
- **No memory-based state**: Each service uses `os.getpid()`
- **No external manager**: Services manage themselves
- **Distributed-friendly**: Multiple instances work naturally
- **No state synchronization**: OS is the source of truth

### 3. Simplified Codebase ✅
- **Remove AsyncServiceManager heartbeat loop**: No longer needed
- **Remove service registry logic**: Use worker registry instead
- **Less code to maintain**: ~200 lines removed
- **Fewer edge cases**: One code path instead of two

### 4. Better Operational Characteristics ✅
- **Graceful shutdown**: Workers can unregister on exit
- **Port in worker info**: Included in registration data
- **Health monitoring**: `gleitzeit ps` shows all services uniformly
- **Proven reliability**: Using pattern that works for 4+ hours

### 5. Horizontal Scaling ✅
```bash
# Instance A
gleitzeit serve --api-port 8000 --ui-port 3000

# Instance B
gleitzeit serve --api-port 8001 --ui-port 3001

# gleitzeit ps shows:
# worker:registry:api:api-instance-a  (port 8000)
# worker:registry:api:api-instance-b  (port 8001)
# worker:registry:ui:ui-instance-a    (port 3000)
# worker:registry:ui:ui-instance-b    (port 3001)
# worker:registry:python:python-1
# worker:registry:python:python-2
# ...all with consistent health monitoring
```

---

## Migration Path

### Phase 1: Create New Worker Classes
1. Implement `APIWorker` in `src/gleitzeit/workers/api_worker.py`
2. Implement `UIWorker` in `src/gleitzeit/workers/ui_worker.py`
3. Add tests to verify self-registration works

### Phase 2: Update serve_unified.py
1. Add logic to start API/UI as workers
2. Keep old path as fallback (feature flag?)
3. Test both native and Docker modes

### Phase 3: Update ps Command
1. Update `gleitzeit ps` to show API/UI workers
2. No code change needed! Already scans `worker:registry:*`
3. Verify display shows port info correctly

### Phase 4: Remove Old Code
1. Remove `_service_heartbeat_loop` from AsyncServiceManager
2. Remove `service:registry:*` logic
3. Clean up process_manager API/UI special cases

### Phase 5: Documentation
1. Update README to explain unified worker model
2. Document how to run multiple API/UI instances
3. Add horizontal scaling examples

---

## Backward Compatibility

### Registry Keys
**Old:** `service:registry:api`, `service:registry:ui`
**New:** `{shard:0}:worker:registry:api:{id}`, `{shard:0}:worker:registry:ui:{id}`

**Migration Strategy:**
1. Run both patterns temporarily
2. Update consumers to check both key patterns
3. Phase out old pattern after transition period

### Process Management
- Keep `AsyncServiceManager` for Docker orchestration
- Remove only the heartbeat loop, not process spawning
- API/UI workers can still be spawned by process manager

---

## Potential Issues and Solutions

### Issue 1: API Worker Blocks Event Loop
**Problem:** Uvicorn server runs in same event loop as heartbeat
**Solution:** Already handled - BaseWorker runs `_process_loop()` and `_heartbeat_loop()` as concurrent tasks

### Issue 2: UI Worker Subprocess PID
**Problem:** UI runs as subprocess, not in Python process
**Solution:** Register both parent PID (worker) and child PID (UI server)

### Issue 3: Port Conflicts
**Problem:** Multiple workers trying to bind same port
**Solution:** Already handled - port conflict detection in serve_unified.py

### Issue 4: Graceful Shutdown in Docker
**Problem:** Docker SIGTERM might not reach worker
**Solution:** Add signal handlers in worker base class (already planned)

---

## Open Questions

1. **Worker ID generation**: Use instance ID? Hostname? UUID?
   - Proposal: `{type}-{instance_id}` (e.g., `api-instance-a`)

2. **Health checks**: Should API/UI workers have health endpoints?
   - Proposal: Yes, inherit from BaseWorker and add HTTP health check

3. **Metrics**: Should we track API request counts in worker info?
   - Proposal: Later enhancement, not required for MVP

4. **Load balancing**: How do clients discover multiple API instances?
   - Proposal: Separate design doc for load balancer integration

5. **TTL configuration**: Should API/UI use different TTL than processing workers?
   - Proposal: Make TTL configurable per worker type

---

## Success Criteria

1. ✅ API and UI self-register using `os.getpid()`
2. ✅ `gleitzeit ps` shows API/UI with port info
3. ✅ Multiple API instances can run simultaneously
4. ✅ Heartbeat keeps services registered for 4+ hours (like current workers)
5. ✅ Graceful shutdown removes registration immediately
6. ✅ No more memory-based state in heartbeat
7. ✅ Codebase simplified (AsyncServiceManager heartbeat removed)

---

## Estimated Implementation Time

- **Phase 1** (Worker classes): 4-6 hours
- **Phase 2** (serve_unified update): 2-3 hours
- **Phase 3** (ps command update): 1 hour (likely already works!)
- **Phase 4** (cleanup): 2-3 hours
- **Phase 5** (documentation): 2 hours

**Total:** ~12-15 hours

---

## Conclusion

Making API and UI into workers is the **correct architectural choice** because:

1. ✅ Uses proven pattern (4+ hour uptime evidence)
2. ✅ Eliminates stateful memory-based heartbeat
3. ✅ Simplifies codebase significantly
4. ✅ Better for horizontal scaling
5. ✅ Consistent with distributed systems best practices

**Recommendation:** Implement this design instead of trying to fix the current API/UI heartbeat approach.
