# Gleitzeit 0.0.7 Startup & Restart Process Audit

**Date**: 2025-09-26
**Status**: Critical Issues Identified
**Priority**: HIGH - System has fundamental process management problems

## Executive Summary

The Gleitzeit startup and restart process has multiple critical issues that prevent reliable operation. The system accumulates zombie processes, has port configuration conflicts, and fails to properly coordinate service startup. While individual components work, the orchestration and process management layer has serious deficiencies.

## Critical Issues Identified

### 1. Zombie Process Accumulation (CRITICAL)

**Current State:**
- Multiple `gleitzeit.cli.serve` processes running simultaneously
- Failed serve attempts don't exit cleanly
- Processes accumulate over time, consuming resources

**Evidence:**
```bash
# Found multiple zombie serve processes:
PID 10082: python -m gleitzeit.cli.serve --restart --api-port 8080
PID 15999: python -m gleitzeit.cli.main serve --instance-name final-restart-test --restart
PID 82791: python -m gleitzeit.cli.main serve --restart --instance-name multi-machine-test
PID 80259: python -m gleitzeit.cli.main serve --restart
PID 69481: python -m gleitzeit.cli.main serve --instance-name redis-port-test-v3 --restart
# ... and more
```

**Root Cause:**
- When serve command encounters port conflicts, it prints error message but doesn't exit
- Process remains running in an idle state waiting for user input
- No timeout or automatic cleanup mechanism

**Impact:**
- Resource leak (memory, file descriptors)
- Confusion about what's actually running
- Potential for process ID exhaustion

### 2. Port Configuration Override Failure (HIGH)

**Current State:**
- Command-line port arguments (`--api-port 8080`) don't actually override config
- Services always use ports from `gleitzeit.yaml`
- Mismatch between requested and actual ports

**Evidence:**
```python
# In serve.py line 73-74:
self.api_port = api_port if api_port is not None else self.instance.get_service_port('api')
# But this value isn't properly propagated to the actual services
```

**Root Cause:**
- Port configuration is read from multiple sources:
  1. Command line arguments
  2. Instance port calculation
  3. Config file (gleitzeit.yaml)
  4. Environment variables
- No clear precedence order
- Services started via subprocess don't receive overridden values

**Impact:**
- Cannot run multiple instances on different ports
- Port conflicts when trying to override defaults
- User confusion when services don't start on expected ports

### 3. Inconsistent Service Discovery (HIGH)

**Current State:**
- API runs on port 8000 (from config)
- UI configured to connect to port 8000 (hardcoded initially, then from config)
- Serve command thinks it's using port 8080 (from command line)
- No coordination between components

**Evidence:**
```bash
# API actually running on:
python -m uvicorn gleitzeit.api.main:app --host 0.0.0.0 --port 8000

# But serve commands trying to use:
python -m gleitzeit.cli.serve --api-port 8080
```

**Root Cause:**
- Multiple configuration sources without proper precedence
- UI reads config independently from serve module
- No central configuration authority

**Impact:**
- UI can't connect to API
- Services can't find each other
- Workflows don't get processed

### 4. Process Cleanup Failures (MEDIUM)

**Current State:**
- `--restart` flag doesn't properly kill all existing processes
- Port-based killing is unreliable
- Process detection misses some running services

**Evidence:**
```python
# Current cleanup in serve.py is incomplete:
subprocess.run(["pkill", "-f", "gleitzeit.orchestrator"], capture_output=True)
# Doesn't catch all variants of running processes
```

**Root Cause:**
- Process matching patterns too specific
- Timing issues (processes restart before cleanup completes)
- No verification that cleanup succeeded

**Impact:**
- Port conflicts on restart
- Multiple instances of same service
- Unpredictable behavior

### 5. Workflow Processing Stoppage (MEDIUM)

**Current State:**
- Workflows submitted but not processed
- 2 items stuck in workflow load stream
- Workers appear connected but not consuming

**Evidence:**
```bash
redis-cli xlen "{shard:0}:workflow:load"
# Returns: 2 (items waiting)

# But workers show as connected:
redis-cli xinfo groups "{shard:0}:workflow:load"
# Shows: WorkflowLoaderWorkerV2-group with consumers
```

**Root Cause:**
- Workers not properly acknowledging messages
- Possible consumer group configuration issue
- Index creation may be failing silently

**Impact:**
- Workflows never execute
- System appears broken to users
- Tasks remain in pending state

## CRITICAL FINDING: Existing Systems Not Being Used

The codebase already contains sophisticated port management and service discovery systems, but the `serve.py` module is NOT using them properly!

### Existing Systems (Working but Unused):

1. **PortManager** (`core/ports.py`):
   - Redis-based distributed port allocation
   - Atomic port allocation with Lua scripts
   - TTL-based leases with automatic refresh
   - Conflict detection and resolution
   - **Problem**: serve.py creates instance but doesn't use async methods

2. **Service Discovery** (`api/discovery.py`):
   - Service registration and discovery
   - Machine and instance tracking
   - **Problem**: Services not registering themselves

3. **ProcessManager** (`core/process_manager.py`):
   - Smart process lifecycle management
   - **Problem**: Not being used for actual process control

### Root Cause:
The `serve.py` module is using basic `subprocess.Popen` instead of leveraging the existing infrastructure. This is why:
- Port conflicts occur (not using PortManager properly)
- Services can't find each other (not using discovery)
- Zombie processes accumulate (not using ProcessManager)

## Architecture Problems

### 1. Configuration Hierarchy Unclear

```
Current Sources (no clear precedence):
1. Command line arguments
2. Environment variables
3. gleitzeit.yaml
4. Hardcoded defaults
5. Instance identity calculations

Should be:
1. Command line (highest priority)
2. Environment variables
3. Instance identity
4. Config file
5. Defaults (lowest priority)
```

### 2. Process Lifecycle Management

```
Current Flow:
serve.py → subprocess.Popen → uvicorn → actual service
         ↓
    (no feedback loop)

Should be:
serve.py → ProcessManager → Service
         ↑                     ↓
         └── health checks ────┘
```

### 3. Service Discovery

```
Current:
- Each service reads its own config
- No central registry
- No health checking

Should be:
- Central service registry in Redis
- Services register on startup
- Health checks and automatic deregistration
```

## Immediate Fixes Required

### Fix 1: Process Cleanup Enhancement

```python
def cleanup_all_gleitzeit_processes():
    """Complete cleanup of all Gleitzeit processes"""
    patterns = [
        "gleitzeit.cli.serve",
        "gleitzeit.cli.main serve",
        "gleitzeit.orchestrator",
        "gleitzeit.workers",
        "uvicorn.*gleitzeit",
    ]

    for pattern in patterns:
        # Use more aggressive matching
        subprocess.run(["pkill", "-9", "-f", pattern], capture_output=True)

    # Verify ports are free
    for port in [8000, 8004, 8080]:
        kill_process_on_port(port)
```

### Fix 2: Configuration Precedence

```python
class ConfigManager:
    def get_port(self, service: str) -> int:
        # Clear precedence order
        sources = [
            ('cli', self.cli_args.get(f"{service}_port")),
            ('env', os.getenv(f"GLEITZEIT_{service.upper()}_PORT")),
            ('instance', self.instance.get_service_port(service)),
            ('config', self.config.get('serve', {}).get(service, {}).get('port')),
            ('default', self.DEFAULTS[service])
        ]

        for source, value in sources:
            if value is not None:
                logger.info(f"Using {service} port {value} from {source}")
                return int(value)
```

### Fix 3: Process State Management

```python
class ProcessStateManager:
    def __init__(self):
        self.redis = get_redis_connection()
        self.processes = {}

    def register_process(self, name: str, pid: int, port: int):
        """Register a process in Redis"""
        key = f"process:{name}"
        self.redis.hset(key, {
            'pid': pid,
            'port': port,
            'started': time.time(),
            'host': socket.gethostname()
        })
        self.redis.expire(key, 300)  # 5 minute TTL

    def cleanup_dead_processes(self):
        """Remove dead processes from registry"""
        for key in self.redis.scan_iter("process:*"):
            data = self.redis.hgetall(key)
            if not process_is_alive(data['pid']):
                self.redis.delete(key)
```

## Long-term Solutions

### 1. Implement Proper Service Mesh

- Use service discovery (Consul, etcd, or Redis-based)
- Health checks and circuit breakers
- Automatic failover and recovery
- Clear service contracts

### 2. Process Supervision

- Use supervisord or systemd for process management
- Automatic restart on failure
- Log aggregation
- Resource limits

### 3. Configuration Management

- Single source of truth for configuration
- Dynamic configuration updates
- Validation and type checking
- Environment-specific overrides

### 4. Monitoring & Observability

- Process metrics (CPU, memory, file descriptors)
- Service health endpoints
- Distributed tracing
- Alert on anomalies

## Testing Requirements

### 1. Process Management Tests

```python
def test_zombie_cleanup():
    # Start serve process
    proc = start_serve_process(port=8080)

    # Simulate failure
    proc.terminate()

    # Start new serve with cleanup
    start_serve_process(port=8080, restart=True)

    # Verify no zombies
    assert count_serve_processes() == 1

def test_port_override():
    # Start with custom port
    start_serve_process(api_port=9000)

    # Verify services use correct port
    assert is_port_in_use(9000)
    assert not is_port_in_use(8000)
```

### 2. Configuration Tests

```python
def test_config_precedence():
    # Set values at different levels
    os.environ['GLEITZEIT_API_PORT'] = '9000'
    config = {'serve': {'api': {'port': 8000}}}

    # CLI should override all
    port = get_port('api', cli_port=9500, config=config)
    assert port == 9500

    # Env should override config
    port = get_port('api', cli_port=None, config=config)
    assert port == 9000
```

## Recommendations

### Immediate (Week 1)

1. **Fix zombie process cleanup** - Add proper cleanup in serve.py
2. **Fix port configuration** - Ensure command-line overrides work
3. **Add process registry** - Track what's actually running
4. **Fix workflow processing** - Debug why workers aren't consuming

### Short-term (Week 2-3)

1. **Implement health checks** - Services should report health
2. **Add service discovery** - Central registry for all services
3. **Improve error handling** - Fail fast with clear messages
4. **Add integration tests** - Test full startup/restart scenarios

### Long-term (Month 2+)

1. **Redesign process management** - Use proper supervision
2. **Implement configuration service** - Single source of truth
3. **Add monitoring** - Prometheus metrics, Grafana dashboards
4. **Create operational runbooks** - Document procedures

## Risk Assessment

**Current Risk Level**: HIGH

- **Data Loss Risk**: Low - Redis persistence protects data
- **Service Availability Risk**: High - Services fail to start reliably
- **Performance Risk**: Medium - Zombie processes consume resources
- **Security Risk**: Low - No direct security implications

## Conclusion

The Gleitzeit startup and restart process has fundamental issues that prevent reliable operation. While the core workflow engine works, the process management and configuration layers need significant refactoring. The system currently relies on manual intervention and external cleanup scripts, which is not sustainable.

**Key Takeaways:**
1. Process lifecycle management is broken
2. Configuration precedence is unclear
3. Service discovery is missing
4. No health checking or monitoring
5. Zombie processes accumulate over time

These issues must be addressed before the system can be considered production-ready.

## Appendix: Current Workarounds

### Manual Cleanup Commands

```bash
# Kill all Gleitzeit processes
pkill -f gleitzeit

# Kill processes on specific ports
lsof -ti:8000 | xargs kill -9
lsof -ti:8004 | xargs kill -9

# Check what's running
ps aux | grep gleitzeit

# Check ports
lsof -i:8000,8004,8080
```

### Correct Startup Sequence

```bash
# 1. Clean everything
pkill -f gleitzeit
sleep 2

# 2. Start with config file (don't use --api-port)
cd /path/to/gleitzeit
PYTHONPATH="src:$PYTHONPATH" python -m gleitzeit.cli.serve --restart

# 3. Verify services
curl http://localhost:8000/health
curl http://localhost:8004/
```

### Debug Workflow Issues

```bash
# Check stream status
redis-cli xinfo stream "{shard:0}:workflow:load"

# Check consumer groups
redis-cli xinfo groups "{shard:0}:workflow:load"

# Read pending messages
redis-cli xpending "{shard:0}:workflow:load" WorkflowLoaderWorkerV2-group

# Force reprocess
redis-cli xclaim "{shard:0}:workflow:load" WorkflowLoaderWorkerV2-group consumer-0 0 <message-id>
```