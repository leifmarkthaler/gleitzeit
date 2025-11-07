# Gleitzeit 0.0.7 Instance Management, Startup & Restart Process Audit

## Executive Summary

This comprehensive audit examines the instance management, startup, and restart mechanisms in Gleitzeit 0.0.7. The analysis reveals a sophisticated multi-layered architecture with several critical issues that prevent reliable service startup and restart functionality.

### Key Findings
1. **Port Detection Bug**: Fixed - was finding wrong PIDs due to not checking LISTEN state
2. **Subprocess PID Reporting**: Suspicious low PIDs (443, 460) indicate process creation failures
3. **Multiple Serve Processes**: Old serve processes can conflict and spawn duplicate services
4. **Service Integration**: ServiceManager is correctly integrated but processes fail to start properly
5. **Error Handling Gaps**: Process output not properly captured when subprocess fails immediately

## 1. Architecture Overview

### Component Hierarchy
```
CLI (serve_v3.py)
  ↓
ProcessOrchestrator
  ├── ServiceManager (API, UI)
  ├── WorkerManager (Workers)
  └── ProcessManager (Core)
      ├── Port Management
      ├── Instance Identity
      └── Subprocess Lifecycle
```

### Key Components

#### 1.1 Instance Identity (`instance.py`)
- **Purpose**: Unique identification of each Gleitzeit instance
- **Components**:
  - `InstanceCapabilities`: Hardware/software capabilities (CPU, memory, GPU)
  - `MachineInfo`: Machine-level identification (hostname, IPs, fingerprint)
  - `InstanceMetadata`: Deployment metadata (environment, region, tags)
  - `InstanceIdentity`: Core identity combining all above

#### 1.2 Process Orchestrator (`process_orchestrator.py`)
- **Purpose**: Top-level coordination of all services and workers
- **Responsibilities**:
  - Initialize managers (Service, Worker, Port, Process)
  - Sequence startup (services first, then workers)
  - Monitor and restart failed processes
  - Handle graceful shutdown

#### 1.3 Service Manager (`service_manager.py`)
- **Purpose**: Service-specific process management (API, UI)
- **Integration**: ✅ Correctly integrated with ProcessManager
- **Issue**: Missing log-level parameters (fixed in audit)

#### 1.4 Process Manager (`process_manager.py`)
- **Purpose**: Core process lifecycle management
- **Features**:
  - Port locking (filesystem-based)
  - Service ownership (Redis-based)
  - Process tree management
  - Restart with backoff

## 2. Startup Process Flow

### 2.1 Initialization Sequence
```python
1. CLI: serve_v3.py
   - Parse arguments (--restart flag)
   - Initialize instance identity
   - Load configuration (gleitzeit.yaml)

2. ProcessOrchestrator.__init__
   - Create ProcessManager with instance
   - Create ServiceManager
   - Create WorkerManager
   - Initialize PortManager

3. ProcessOrchestrator.start_all(restart=True/False)
   - Check port conflicts
   - If restart=False and conflicts: fail
   - If restart=True: proceed to kill existing

4. Start Services
   - ServiceManager.start_all_services(kill_existing=restart)
   - For each service (API, UI):
     a. Build command
     b. Get port allocation
     c. ProcessManager.start_service()

5. Start Workers
   - WorkerManager.start_all_workers()
   - Similar process for each worker type
```

### 2.2 Service Start Details (`ProcessManager._start_process`)
```python
1. Port Lock Acquisition
   - Check filesystem lock
   - If locked by another instance:
     - If kill_existing=False: fail
     - If kill_existing=True: kill process, remove lock

2. Find Existing Process
   - Call _find_process_on_port()
   - FIXED: Now checks LISTEN state only
   - Previously: Found any connection (bug)

3. Kill Existing (if restart)
   - _kill_process_tree(): Kill parent and children
   - Wait 2 seconds for port release

4. Claim Service Ownership (Redis)
   - Set distributed lock in Redis
   - Register in service registry

5. Start Subprocess
   - subprocess.Popen() with new process group
   - Capture stdout/stderr combined
   - Wait 2 seconds to check if running

6. Verify Running
   - proc.poll() == None: Success
   - proc.poll() != None: Failed
     - Attempt to capture error output
     - Clean up locks and ownership
```

## 3. Restart Mechanism Analysis

### 3.1 --restart Flag Flow
```
CLI --restart
  ↓
ProcessOrchestrator.start_all(restart=True)
  ↓
ServiceManager.start_all_services(kill_existing=True)
  ↓
ProcessManager.start_service(kill_existing=True)
  ↓
ProcessManager._start_process(kill_existing=True)
```

### 3.2 Kill Existing Process Logic
```python
if kill_existing:
    1. Find process on port (_find_process_on_port)
    2. Kill process tree (_kill_process_tree)
    3. Remove port lock file
    4. Wait 2 seconds
    5. Retry lock acquisition
```

### 3.3 Issues with Restart

#### Issue 1: Port Detection (FIXED)
**Problem**: `_find_process_on_port` was finding processes with ANY connection to the port, not just LISTENING processes.

**Fix Applied**:
```python
# Now checks specifically for LISTEN state
if 'LISTEN' in line:  # lsof output
if conn.status == psutil.CONN_LISTEN:  # psutil
```

#### Issue 2: Multiple Serve Processes
**Problem**: Old `gleitzeit serve` processes remain running and spawn conflicting services.

**Example**:
- Process 48456 from 4:56PM still running
- Spawning uvicorn on ports 8000, 8004
- New serve process can't bind to ports

**Solution Needed**: Kill all gleitzeit serve processes before starting new one.

#### Issue 3: Subprocess Immediate Failure
**Problem**: Subprocess starts (gets PID) but immediately exits.

**Symptoms**:
- Low PIDs reported (443, 460) - suspicious
- No uvicorn processes found after "successful" start
- Error output not captured properly

**Possible Causes**:
- Python module import failures
- Environment variable issues
- Working directory problems

## 4. Port Management System

### 4.1 Dual-Layer Port Management

#### Filesystem Locks (`ProcessManager`)
```python
/var/run/gleitzeit/locks/port_8000.lock
{
  "instance_id": "Leifs-Ai-7bd8dad1",
  "pid": 99515,
  "timestamp": "2025-09-27T08:36:25"
}
```

#### Redis Allocation (`PortManager`)
```python
port:machine:Leifs-Air:api = 8001
port:instance:Leifs-Air:instance-id:api = 8001
```

### 4.2 Port Conflict Resolution
1. Check Redis for machine-wide allocation
2. Check filesystem lock for local process
3. Verify actual port usage with lsof/psutil
4. If conflict and kill_existing: kill and retry
5. If conflict and not kill_existing: fail

## 5. Service Ownership Model

### 5.1 Redis-Based Distributed Locking
```python
service_lock:api = "instance-id:pid"
service:registry:api = {members: ["instance-id"]}
instance:instance-id:services = {members: ["api", "ui"]}
```

### 5.2 Ownership Flow
1. **Claim**: Set Redis lock with instance ID + PID
2. **Register**: Add to service registry
3. **Track**: Add to instance's service list
4. **Release**: Remove lock, registry, and tracking

### 5.3 Issues
- Lock can become stale if instance crashes
- No automatic cleanup of dead instances
- TTL not consistently applied

## 6. Process Lifecycle Management

### 6.1 Process States
```
starting → running → failed/stopped
           ↓
        monitoring → restart (with backoff)
```

### 6.2 Restart Policy
```python
MAX_RESTART_COUNT = 5
RESTART_BACKOFF_BASE = 2  # seconds
stable_uptime_seconds = 60

backoff = min(300, RESTART_BACKOFF_BASE ** restart_count)
```

### 6.3 Monitoring Loop
- Check every 30 seconds
- Verify process is alive (psutil)
- Restart if dead and under limit
- Reset count if stable for 60 seconds

## 7. Critical Issues Identified

### 7.1 Subprocess Creation Failure
**Problem**: Services report as started but immediately die.

**Evidence**:
```
Service api started successfully (PID: 443)  # Suspicious low PID
ps aux | grep 443  # Process doesn't exist
```

**Root Cause Analysis**:
1. subprocess.Popen() succeeds initially
2. Process gets PID
3. Python interpreter starts but module import fails
4. Process exits before 2-second check
5. Error output not properly captured

**Fix Needed**:
```python
# Better error capture
proc = subprocess.Popen(
    command,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,  # Separate stderr
    env=process_env,
    cwd=working_directory  # Set proper working directory
)

# Immediate check for startup failures
time.sleep(0.5)  # Quick initial check
if proc.poll() is not None:
    stdout, stderr = proc.communicate()
    logger.error(f"Immediate failure: {stderr.decode()}")
```

### 7.2 Environment Configuration
**Problem**: Subprocess may not have correct Python path.

**Current**:
```python
process_env = os.environ.copy()
```

**Needed**:
```python
process_env = os.environ.copy()
process_env['PYTHONPATH'] = '/path/to/gleitzeit/src:' + process_env.get('PYTHONPATH', '')
```

### 7.3 Working Directory
**Problem**: No working directory set for subprocess.

**Fix**:
```python
proc = subprocess.Popen(
    command,
    cwd=os.path.dirname(os.path.dirname(__file__)),  # Project root
    ...
)
```

### 7.4 Command Building
**Problem**: ServiceManager builds command but doesn't verify Python can import modules.

**Add Validation**:
```python
# Test import before starting
test_cmd = [sys.executable, "-c", "import gleitzeit.api.main"]
result = subprocess.run(test_cmd, capture_output=True)
if result.returncode != 0:
    logger.error(f"Module import test failed: {result.stderr}")
```

## 8. Error Handling Gaps

### 8.1 Missing Error Captures
1. **Subprocess immediate failure**: Output not captured before process dies
2. **Import errors**: Python module failures not reported
3. **Environment issues**: PATH/PYTHONPATH problems silent
4. **Port bind errors**: Sometimes caught, sometimes not

### 8.2 Insufficient Logging
- Debug logs for command execution added but need log level set
- Process output capture improved but needs stderr separation
- Need pre-flight checks before subprocess launch

### 8.3 Cleanup Failures
- Port locks not always removed on crash
- Redis service ownership can become stale
- Zombie processes not detected

## 9. Recommendations

### 9.1 Immediate Fixes

#### Fix 1: Improve Subprocess Launch
```python
def _start_process(self, ...):
    # Pre-flight checks
    if not self._verify_command(command):
        return None

    # Set working directory
    cwd = self._get_working_directory()

    # Ensure PYTHONPATH
    process_env['PYTHONPATH'] = self._get_python_path()

    # Start with better error capture
    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,  # Separate
        env=process_env,
        cwd=cwd,
        preexec_fn=os.setsid
    )

    # Quick check for immediate failure
    time.sleep(0.5)
    if proc.poll() is not None:
        stdout, stderr = proc.communicate()
        logger.error(f"Startup failed:\nSTDOUT: {stdout}\nSTDERR: {stderr}")
        return None
```

#### Fix 2: Kill Old Serve Processes
```python
def cleanup_old_serves(self):
    """Kill any existing serve processes"""
    for proc in psutil.process_iter(['pid', 'cmdline']):
        cmdline = proc.info.get('cmdline', [])
        if 'gleitzeit.cli' in str(cmdline) and 'serve' in str(cmdline):
            logger.info(f"Killing old serve process {proc.pid}")
            proc.kill()
```

#### Fix 3: Better Port Release
```python
def _kill_and_wait_for_port(self, port: int, timeout: int = 10):
    """Kill process and wait for port to be released"""
    proc = self._find_process_on_port(port)
    if proc:
        self._kill_process_tree(proc)

    # Wait for port to be actually free
    start = time.time()
    while time.time() - start < timeout:
        if not self._is_port_in_use(port):
            return True
        time.sleep(0.5)
    return False
```

### 9.2 Long-term Improvements

1. **Health Checks**: Implement HTTP health checks instead of just process checks
2. **Graceful Shutdown**: Send SIGTERM before SIGKILL
3. **Process Groups**: Better management of parent-child relationships
4. **Distributed Coordination**: Improve Redis-based instance coordination
5. **Monitoring**: Add metrics for process starts, failures, restarts
6. **Configuration Validation**: Validate all config before starting processes

## 10. Conclusion

The Gleitzeit instance management system is architecturally sound with sophisticated features like distributed locking, multi-instance support, and automatic restart policies. However, critical implementation issues prevent reliable service startup:

1. **Subprocess creation fails silently** - processes die immediately after getting PID
2. **Error output not captured** - failures occur without diagnostic information
3. **Environment not properly configured** - Python modules can't be imported
4. **Old processes not cleaned up** - multiple serve instances conflict

The fixes are straightforward:
- Set proper working directory and PYTHONPATH
- Capture stderr separately
- Add immediate failure detection
- Clean up old serve processes on restart
- Implement pre-flight validation

With these fixes, the sophisticated architecture can function as designed, providing reliable multi-instance process orchestration.