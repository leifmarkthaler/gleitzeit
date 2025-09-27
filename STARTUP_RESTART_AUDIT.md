# Comprehensive Startup and Restart Code Audit - Gleitzeit 0.0.7

## Executive Summary
This audit traces the complete flow from CLI invocation to subprocess death, identifying critical failures in the startup and restart mechanisms.

## 1. STARTUP FLOW ANALYSIS

### 1.1 Entry Point Chain
```
User runs: python -m gleitzeit.cli.main serve --restart
    ↓
main.py: cli.add_command(serve_v3) [line 730]
    ↓
serve_v3.py: serve_v3() function [line 278]
    ↓
GleitzeitServerV3.__init__() [line 36-68]
    ↓
GleitzeitServerV3.start() [line 202]
    ↓
GleitzeitServerV3.start_async() [line 241]
    ↓
ProcessOrchestrator.start_all() [line 88]
    ↓
ServiceManager.start_all_services() [line 125]
    ↓
ServiceManager.start_api() [line 47]
    ↓
ProcessManager.start_service() [line 691]
    ↓
ProcessManager._start_process() [line 718]
    ↓
subprocess.Popen() [line 793]
```

### 1.2 Configuration Flow
```yaml
# Default config loaded from:
1. CLI arguments (--api-port, --ui-port, etc.)
2. gleitzeit.yaml (if exists)
3. Hardcoded defaults in serve_v3.py
```

**ISSUE #1**: Multiple config sources without clear precedence
- CLI args should override config file
- Config file should override defaults
- Current implementation is inconsistent

### 1.3 Instance Initialization
```python
# serve_v3.py line 71-81
instance = initialize_instance(
    name=self.instance_name,
    role=self.instance_role,
    port_offset=self.port_offset
)
```

**ISSUE #2**: Instance identity not validated for uniqueness
- Multiple instances can claim same identity
- No cleanup of stale instances

## 2. ENVIRONMENT VARIABLE PROPAGATION

### 2.1 Environment Building Chain

#### Layer 1: serve_v3.py (_setup_environment)
```python
# Line 155-196
self.env = os.environ.copy()  # PROBLEM: Copies everything including PYTHONPATH
self.env['GLEITZEIT_INSTANCE_ID'] = instance.instance_id
self.env['REDIS_URL'] = redis_url
```

#### Layer 2: ProcessOrchestrator (_get_service_env)
```python
# Line 172-218
env = {}
# Line 176-180 (CURRENT CODE - WRONG):
src_path = Path(__file__).parent.parent.absolute()
env['PYTHONPATH'] = f"{src_path}:{current_pythonpath}"  # CONFLICTS WITH VENV!
```

#### Layer 3: ProcessManager (_start_process)
```python
# Line 773-783 (CURRENT CODE):
process_env = {
    'PATH': os.environ.get('PATH', ''),
    'HOME': os.environ.get('HOME', ''),
    # Missing critical env vars!
}
```

**ISSUE #3**: Environment variable chaos
- PYTHONPATH conflicts between system/venv/custom
- Missing critical environment variables (TERM, SHELL, etc.)
- Each layer modifies environment differently

## 3. SUBPROCESS LIFECYCLE

### 3.1 Process Creation
```python
# ProcessManager._start_process() line 793-800
proc = subprocess.Popen(
    command,
    env=process_env,
    cwd=str(cwd),
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    preexec_fn=os.setsid  # Creates new process group
)
```

### 3.2 Process Verification
```python
# Line 839-853
time.sleep(2)  # Wait 2 seconds
if proc.poll() is None:
    time.sleep(1)  # Wait another second
    if proc.poll() is None:
        logger.info(f"Service started successfully (PID: {proc.pid})")
        return process_info
```

**ISSUE #4**: Unreliable process verification
- Only checks if process exists, not if it's functional
- No health check verification
- Process can die immediately after check

### 3.3 Command Building
```python
# ServiceManager._build_service_command() line 184-203
venv_python = project_root / ".venv" / "bin" / "python"
if not venv_python.exists():
    raise RuntimeError("Virtual environment not found")

cmd = [
    str(venv_python), "-m", config['module'],
    config['app'],
    "--host", host,
    "--port", str(port)
]
```

**ISSUE #5**: Port confusion
- ServiceManager builds command with port
- Then updates port again (lines 66-69)
- ProcessManager uses different port for tracking

## 4. RESTART MECHANISM ANALYSIS

### 4.1 --restart Flag Flow
```
CLI --restart → serve_v3() → GleitzeitServerV3(restart=True)
    ↓
ProcessOrchestrator.start_all(restart=True)
    ↓
ServiceManager.start_all_services(kill_existing=True)
    ↓
ProcessManager.start_service(kill_existing=True)
    ↓
ProcessManager._start_process(kill_existing=True)
```

### 4.2 Port Conflict Detection
```python
# ProcessOrchestrator.start_all() line 99-108
conflicts = await self.port_manager.check_port_conflicts()
if conflicts:
    if not restart:
        logger.error("Use --restart flag to override")
        return False
```

### 4.3 Process Killing
```python
# ProcessManager._start_process() line 750-763
existing_proc = self._find_process_on_port(port)
if existing_proc:
    if kill_existing:
        self._kill_process_tree(existing_proc)
        time.sleep(2)  # Wait for port release
```

**ISSUE #6**: Ineffective process killing
- _find_process_on_port was buggy (fixed but still issues)
- Port locks not always cleaned up
- Redis service ownership can become stale

## 5. CRITICAL ISSUES CAUSING PROCESS DEATH

### 5.1 Root Cause: Environment Corruption
The processes start but die because:

1. **PYTHONPATH Conflict**:
   - ProcessOrchestrator adds PYTHONPATH pointing to src/gleitzeit
   - This conflicts with venv's site-packages
   - Python finds wrong version of modules

2. **Missing Environment Variables**:
   - Terminal-related vars (TERM, SHELL) missing
   - Locale vars incomplete
   - No TMPDIR set

3. **Working Directory Issues**:
   - CWD set to project root
   - But PYTHONPATH points to src/
   - Relative imports fail

### 5.2 Startup Failure Sequence
```
1. subprocess.Popen() succeeds → PID assigned
2. Python interpreter starts
3. uvicorn module loads
4. uvicorn tries to import gleitzeit.api.main
5. Import fails due to PYTHONPATH confusion
6. Process exits with error
7. ProcessManager checks after 2 seconds
8. Process already dead, but reported as "started successfully"
```

## 6. PORT MANAGEMENT ISSUES

### 6.1 Triple Port Tracking
1. **PortManager (Redis)**: Allocates ports per instance
2. **ProcessManager (Filesystem)**: Locks ports with PID files
3. **Actual OS**: Real port binding

**ISSUE #7**: Port management desynchronization
- PortManager allocates 8001, but command uses 8000
- Lock files not cleaned on crash
- Redis and filesystem can disagree

## 7. MONITORING AND RECOVERY

### 7.1 Monitor Loop
```python
# ProcessOrchestrator._monitor_loop() line 278-292
while self.running:
    await self.process_manager.monitor_services()
    await asyncio.sleep(5)
```

**ISSUE #8**: No automatic recovery
- Monitor detects failures but doesn't restart
- No health checks beyond process existence
- No exponential backoff for restarts

## 8. RECOMMENDED FIXES

### Fix 1: Clean Environment Setup
```python
# ProcessOrchestrator._get_service_env()
def _get_service_env(self):
    # Start fresh, don't copy os.environ
    env = {
        'PATH': os.environ.get('PATH'),
        'HOME': os.environ.get('HOME'),
        'USER': os.environ.get('USER'),
        'TERM': os.environ.get('TERM', 'xterm'),
        'LANG': os.environ.get('LANG', 'en_US.UTF-8'),
        'LC_ALL': os.environ.get('LC_ALL', 'en_US.UTF-8'),
        # Don't set PYTHONPATH - venv handles it
    }
    # Add Gleitzeit-specific vars
    env.update(self._get_gleitzeit_env())
    return env
```

### Fix 2: Reliable Process Verification
```python
# ProcessManager._start_process()
# After starting, verify with actual health check
async def _verify_service_health(self, service_name, port, timeout=10):
    start = time.time()
    while time.time() - start < timeout:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://localhost:{port}/health") as resp:
                    if resp.status == 200:
                        return True
        except:
            pass
        await asyncio.sleep(0.5)
    return False
```

### Fix 3: Proper Restart Implementation
```python
# Add to ProcessOrchestrator
async def cleanup_stale_processes(self):
    """Kill all processes from previous runs"""
    # 1. Find all gleitzeit processes
    for proc in psutil.process_iter(['cmdline']):
        if 'gleitzeit' in str(proc.cmdline()):
            # Check if it's from our instance
            if not self._is_our_process(proc):
                proc.kill()

    # 2. Clean up stale locks
    await self.port_manager.cleanup_stale_locks()

    # 3. Clear Redis ownership
    await self.process_manager.clear_stale_ownership()
```

### Fix 4: Unified Port Management
```python
# Single source of truth for ports
class UnifiedPortManager:
    async def allocate_port(self, service_name):
        port = self._get_base_port(service_name)

        # Check if available
        if not self._is_port_free(port):
            if self.kill_existing:
                await self._kill_port_owner(port)
            else:
                raise PortInUse(port)

        # Lock in all systems
        await self._lock_redis(port)
        self._lock_filesystem(port)

        return port
```

## 9. TESTING RECOMMENDATIONS

1. **Unit Tests for Each Layer**:
   - Test environment building separately
   - Test command construction
   - Test process lifecycle

2. **Integration Tests**:
   - Test full startup sequence
   - Test restart with existing processes
   - Test port conflict resolution

3. **Failure Scenarios**:
   - Test with corrupted environment
   - Test with port conflicts
   - Test with import errors

## 10. CONCLUSION

The startup/restart system has fundamental issues:

1. **Environment corruption** from PYTHONPATH conflicts
2. **Unreliable process verification** - no health checks
3. **Port management chaos** - three separate systems
4. **No automatic recovery** from failures
5. **Incomplete cleanup** on restart

The system reports success when processes are actually dying. The fixes require:
- Clean environment management (no PYTHONPATH)
- Health-check based verification
- Unified port management
- Proper cleanup on restart
- Automatic recovery with backoff

These issues explain why processes die after being reported as "started successfully".