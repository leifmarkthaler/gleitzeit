# Simplified AsyncServiceManager Design

## Current State vs Proposed State

### AsyncServiceManager Responsibilities

**Current (Complex):**
```
AsyncServiceManager
├── Special API handling
│   ├── start_api() - 70 lines
│   ├── Port conflict checking
│   └── Service registry management
├── Special UI handling
│   ├── start_ui() - 70 lines
│   ├── Port conflict checking
│   └── Service registry management
├── Centralized heartbeat
│   ├── _service_heartbeat_loop() - 80 lines
│   ├── Memory-based state tracking
│   └── Registry refreshing
├── Worker spawning
│   ├── start_worker() - Generic
│   └── start_essential_workers()
├── Process monitoring
│   └── monitor_loop() - Restarts dead processes
└── Shutdown coordination
    └── stop_all()
```

**Proposed (Simple):**
```
AsyncServiceManager
├── Worker spawning (unified for ALL workers)
│   ├── start_worker() - API, UI, Python, Timer, etc.
│   └── start_all_workers() - Iterates config
├── Process monitoring
│   └── monitor_loop() - Restarts dead workers
└── Shutdown coordination
    └── stop_all()
```

---

## What Gets Removed

### 1. API-Specific Code ❌
```python
async def start_api(self, host: str = "0.0.0.0", port: int = 8000, dev_mode: bool = False):
    """~70 lines of API-specific subprocess management"""
    # Port checking
    # Subprocess spawning with uvicorn
    # Service registry
    # ... DELETED
```

**Replaced by:** Worker config entry + generic `start_worker()`

### 2. UI-Specific Code ❌
```python
async def start_ui(self, host: str = "0.0.0.0", port: int = 8004, api_port: int = 8000, dev_mode: bool = False):
    """~70 lines of UI-specific subprocess management"""
    # Port checking
    # Subprocess spawning with uvicorn
    # Service registry
    # ... DELETED
```

**Replaced by:** Worker config entry + generic `start_worker()`

### 3. Centralized Heartbeat ❌
```python
async def _service_heartbeat_loop(self):
    """~80 lines of memory-based heartbeat"""
    while self._running:
        for name, info in self.process_manager.processes.items():
            if name == "api" or name == "ui":
                service_data = {"pid": str(info.pid), ...}  # FROM MEMORY
                await self.smart_manager.register_service(name, service_data)
        await asyncio.sleep(30)
    # ... DELETED
```

**Replaced by:** Each worker's own `_heartbeat_loop()` (self-registration)

### 4. Port Checking Helper ❌
```python
def _is_port_in_use(self, port: int, host: str = '0.0.0.0') -> bool:
    """Check if port is in use"""
    # ... DELETED (moved to APIWorker/UIWorker)
```

**Replaced by:** Workers check their own ports in `on_initialize()`

**Total removal: ~300-400 lines**

---

## What Stays (Simplified)

### 1. Worker Spawning (Unchanged)
```python
async def start_worker(self, worker_config: dict):
    """
    Start a worker from configuration.

    This method is ALREADY generic - works for any worker type!
    No changes needed.
    """
    worker_type = worker_config.get('worker_type')
    worker_class = worker_config.get('worker_class')
    worker_id = f"{worker_type}-async"

    # Build config and store in Redis
    full_config = {...}
    config_key = f"worker:config:{worker_id}:{uuid.uuid4().hex[:8]}"
    self.redis_client.setex(config_key, 3600, json.dumps(full_config))

    # Spawn via runner
    command = [
        self.python_path, "-m", "gleitzeit.workers.runner",
        "--config-key", config_key,
        "--redis-url", self.redis_url
    ]

    result = await self.process_manager.start_process(
        f"worker_{worker_type}", command, env=env
    )

    return result
```

**Key insight:** This ALREADY works for any worker type! Just needs config.

### 2. Start All Workers (Simplified)
```python
async def start_all_workers(self, cli_overrides: dict = None):
    """
    Start all workers from configuration.

    SIMPLIFIED: Just iterates workers list and calls start_worker()
    No special cases for API/UI!
    """
    await self._init_smart_manager()
    await validate_sharding_config(self.smart_manager.redis)

    # Get all workers from config
    workers = self.config.get('workers', [])

    for worker_config in workers:
        worker_type = worker_config.get('worker_type')

        # Apply CLI overrides
        if cli_overrides:
            worker_config = self._apply_overrides(worker_config, cli_overrides)

        # Start worker (same code path for ALL workers!)
        await self.start_worker(worker_config)

    return await self.process_manager.monitor_processes()
```

### 3. CLI Override Helper (New)
```python
def _apply_overrides(self, worker_config: dict, overrides: dict) -> dict:
    """
    Apply CLI flags to worker config.

    Examples:
      - --api-port 8080 → override api worker port
      - --no-ui → skip ui worker
      - --dev-mode → set dev_mode for api/ui workers
    """
    config = worker_config.copy()
    worker_type = config.get('worker_type')

    # Filter workers based on mode flags
    if overrides.get('api_only') and worker_type not in ['api', 'ui']:
        return None  # Skip this worker
    if overrides.get('workers_only') and worker_type in ['api', 'ui']:
        return None  # Skip this worker
    if overrides.get('no_ui') and worker_type == 'ui':
        return None  # Skip UI worker
    if overrides.get('no_api') and worker_type == 'api':
        return None  # Skip API worker

    # Apply type-specific overrides
    if 'extra' not in config:
        config['extra'] = {}

    if worker_type == 'api':
        if overrides.get('api_port'):
            config['extra']['port'] = overrides['api_port']
        if overrides.get('api_host'):
            config['extra']['host'] = overrides['api_host']
        if overrides.get('dev_mode'):
            config['extra']['dev_mode'] = True

    elif worker_type == 'ui':
        if overrides.get('ui_port'):
            config['extra']['port'] = overrides['ui_port']
        if overrides.get('ui_host'):
            config['extra']['host'] = overrides['ui_host']
        if overrides.get('api_port'):
            config['extra']['api_port'] = overrides['api_port']
        if overrides.get('dev_mode'):
            config['extra']['dev_mode'] = True

    return config
```

### 4. Process Monitoring (Unchanged)
```python
async def monitor_loop(self, auto_restart=True):
    """
    Monitor worker processes and restart if they die.

    NO CHANGES NEEDED - already works generically.
    """
    while self._running:
        await asyncio.sleep(10)

        status = await self.process_manager.monitor_processes()

        for name, info in status.items():
            if info['status'] == 'dead' and auto_restart:
                logger.warning(f"Worker {name} died, restarting...")
                # Restart logic here

        await asyncio.sleep(5)
```

### 5. Shutdown (Unchanged)
```python
async def stop_all(self):
    """
    Stop all worker processes.

    NO CHANGES NEEDED - already works generically.
    """
    await self.process_manager.stop_all()

    # Workers will unregister themselves via graceful shutdown
    # No need to manually unregister!
```

---

## Updated serve_unified.py

**Before:**
```python
async def serve_native_async(...):
    manager = AsyncServiceManager(config=config, ...)

    # Special handling for API
    if not no_api:
        await manager.start_api(port=api_port, dev_mode=dev_mode)

    # Special handling for UI
    if not no_ui and not no_api:
        await manager.start_ui(port=ui_port, api_port=api_port, dev_mode=dev_mode)

    # Special handling for workers
    if not no_workers:
        await manager.start_essential_workers()

    # Special heartbeat loop
    heartbeat_task = asyncio.create_task(manager._service_heartbeat_loop())

    await manager.monitor_loop()
```

**After:**
```python
async def serve_native_async(...):
    manager = AsyncServiceManager(config=config, ...)

    # Build CLI overrides dict
    cli_overrides = {
        'api_port': api_port,
        'ui_port': ui_port,
        'api_host': api_host,
        'ui_host': ui_host,
        'dev_mode': dev_mode,
        'no_ui': no_ui,
        'no_api': no_api,
        'api_only': api_only,
        'workers_only': workers_only,
    }

    # Start ALL workers (API, UI, processing workers)
    # Single unified code path!
    await manager.start_all_workers(cli_overrides)

    # Monitor and restart dead workers
    await manager.monitor_loop()
```

**That's it! Much simpler.**

---

## Class Hierarchy

```
AsyncProcessManager (base class)
│
│   # Low-level process management
│   ├── start_process()      # Spawn any subprocess
│   ├── stop_process()       # Kill subprocess
│   ├── stop_all()           # Kill all subprocesses
│   └── monitor_processes()  # Check process health
│
└── AsyncServiceManager (extends AsyncProcessManager)
    │
    │   # High-level orchestration
    ├── __init__()                    # Load config, init Redis
    ├── start_worker()                # Spawn worker via runner
    ├── start_all_workers()           # Start all workers from config
    ├── _apply_overrides()            # Apply CLI flags to config
    ├── monitor_loop()                # Monitor + auto-restart
    └── (inherits stop_all from base)
```

**Total: ~200 lines instead of ~600 lines**

---

## Do We Even Need AsyncServiceManager?

**Question:** Could we eliminate AsyncServiceManager entirely?

**Answer:** Technically yes, but it provides value:

### Option 1: Keep AsyncServiceManager (Recommended)

**Pros:**
- ✅ Centralized process monitoring
- ✅ Auto-restart dead workers
- ✅ Graceful shutdown coordination
- ✅ CLI override logic in one place
- ✅ Config loading and validation

**Cons:**
- 🤷 ~200 lines of code (not that much)

### Option 2: Eliminate AsyncServiceManager

**How it would work:**
```python
# serve_unified.py becomes the orchestrator
async def serve_native_async(...):
    config = load_config(config_file)
    workers = config.get('workers', [])

    processes = []

    # Spawn all workers directly
    for worker_config in workers:
        # Apply CLI overrides inline
        if worker_config['type'] == 'api' and api_port:
            worker_config['extra']['port'] = api_port

        # Store config in Redis
        config_key = f"worker:config:{uuid.uuid4()}"
        redis.setex(config_key, 3600, json.dumps(worker_config))

        # Spawn subprocess
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "gleitzeit.workers.runner",
            "--config-key", config_key,
            "--redis-url", redis_url
        )
        processes.append(proc)

    # Monitor loop
    while True:
        for proc in processes:
            if proc.returncode is not None:
                # Process died, restart it
                ...
        await asyncio.sleep(10)
```

**Pros:**
- ✅ Even simpler (no AsyncServiceManager class)
- ✅ Fewer abstractions

**Cons:**
- ❌ Lose reusability (can't use manager elsewhere)
- ❌ Monitoring logic in serve command (wrong layer)
- ❌ No output streaming to log files
- ❌ Harder to test
- ❌ CLI override logic scattered in serve code

**Recommendation: Keep AsyncServiceManager**

It's only ~200 lines and provides good separation of concerns:
- `serve_unified.py` = CLI interface
- `AsyncServiceManager` = Process orchestration
- `Workers` = Business logic

---

## Final Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     gleitzeit serve                         │
│                   (serve_unified.py)                        │
│                                                             │
│  - Parses CLI flags                                         │
│  - Loads config                                             │
│  - Builds override dict                                     │
│  - Creates AsyncServiceManager                              │
│  - Calls start_all_workers(overrides)                       │
└─────────────────────────────────────────────────────────────┘
                            │
                            ↓
┌─────────────────────────────────────────────────────────────┐
│               AsyncServiceManager                           │
│         (async_process_manager.py - SIMPLIFIED)             │
│                                                             │
│  1. start_all_workers(overrides):                           │
│     - Iterate workers from config                           │
│     - Apply CLI overrides                                   │
│     - Call start_worker() for each                          │
│                                                             │
│  2. start_worker(config):                                   │
│     - Store config in Redis                                 │
│     - Spawn: python -m gleitzeit.workers.runner             │
│     - Track subprocess                                      │
│                                                             │
│  3. monitor_loop():                                         │
│     - Check if workers died                                 │
│     - Restart if needed                                     │
│     - Sleep, repeat                                         │
│                                                             │
│  4. stop_all():                                             │
│     - Send SIGTERM to all subprocesses                      │
│     - Wait for graceful shutdown                            │
│     - Force kill if timeout                                 │
└─────────────────────────────────────────────────────────────┘
                            │
                            ↓
         ┌──────────────────┼──────────────────┐
         │                  │                  │
         ↓                  ↓                  ↓
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  APIWorker      │ │  UIWorker       │ │  TaskWorker     │
│  (subprocess)   │ │  (subprocess)   │ │  (subprocess)   │
│                 │ │                 │ │                 │
│  - Runs Uvicorn │ │  - Runs Uvicorn │ │  - Processes    │
│  - Self-        │ │  - Self-        │ │    Redis        │
│    registers    │ │    registers    │ │    streams      │
│  - Heartbeat    │ │  - Heartbeat    │ │  - Self-        │
│    loop         │ │    loop         │ ��    registers    │
│                 │ │                 │ │  - Heartbeat    │
└─────────────────┘ └─────────────────┘ └─────────────────┘
         │                  │                  │
         └──────────────────┼──────────────────┘
                            ↓
                    ┌───────────────┐
                    │  Redis        │
                    │  (Registry)   │
                    │               │
                    │  All workers  │
                    │  visible via  │
                    │  gleitzeit ps │
                    └───────────────┘
```

---

## Conclusion

**Yes, we still need AsyncServiceManager, but it becomes much simpler:**

**Before:** ~600 lines with special cases for API/UI
**After:** ~200 lines with unified worker handling

**Core responsibilities:**
1. ✅ Load config and apply CLI overrides
2. ✅ Spawn worker subprocesses via runner
3. ✅ Monitor workers and auto-restart
4. ✅ Coordinate graceful shutdown

**What we remove:**
1. ❌ `start_api()` - ~70 lines
2. ❌ `start_ui()` - ~70 lines
3. ❌ `_service_heartbeat_loop()` - ~80 lines
4. ❌ Port checking helpers
5. ❌ Service-specific registry logic

**Result:** Clean, simple orchestrator that treats all workers uniformly!
