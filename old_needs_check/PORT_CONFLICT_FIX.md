# Port Conflict Detection - Critical Fix for Horizontal Scaling

## Problem Identified

When running `gleitzeit serve`, the API would fail with a cryptic error:
```
❌ Error: Process api died immediately with code 1
```

### Root Cause Analysis

1. **Service Registry TTL**: Services are registered in Redis with a 60-second TTL
2. **Expired Registrations**: Old processes running since 10:03AM had expired from registry by 11:54
3. **No Port Detection**: New instances couldn't detect orphaned processes on the same ports
4. **Poor Error Messages**: Actual uvicorn error ("address already in use") was hidden

**This broke horizontal scaling** because you couldn't start additional instances without getting cryptic failures.

## Solution Implemented

### Added Port-In-Use Detection

**File:** [src/gleitzeit/core/async_process_manager.py](src/gleitzeit/core/async_process_manager.py)

Added `_is_port_in_use()` method that checks if a port is available BEFORE trying to start a service:

```python
def _is_port_in_use(self, port: int, host: str = '0.0.0.0') -> bool:
    """Check if a port is already in use"""
    import socket as sock_module
    try:
        with sock_module.socket(sock_module.AF_INET, sock_module.SOCK_STREAM) as s:
            s.setsockopt(sock_module.SOL_SOCKET, sock_module.SO_REUSEADDR, 1)
            s.bind((host, port))
            return False
    except OSError:
            return True
```

### Enhanced Error Messages

Both `start_api()` and `start_ui()` now check for port conflicts and provide clear error messages:

```python
# Check if port is already in use (even if not in registry - handles orphaned processes)
if self._is_port_in_use(port, host):
    error_msg = f"Cannot start API: Port {port} is already in use. "
    error_msg += f"Either stop the existing service or use --api-port to specify a different port."
    logger.error(error_msg)
    raise RuntimeError(error_msg)
```

## Before vs After

### Before (Cryptic)
```
2025-10-18 11:47:23,570 - gleitzeit.core.async_process_manager - ERROR - Process api died immediately with code 1
❌ Error: Process api failed to start
```

### After (Clear & Actionable)
```
2025-10-18 12:01:51,318 - gleitzeit.core.async_process_manager - ERROR - Cannot start API: Port 8000 is already in use. Either stop the existing service or use --api-port to specify a different port.
❌ Error: Cannot start API: Port 8000 is already in use. Either stop the existing service or use --api-port to specify a different port.
```

## Horizontal Scaling Now Works

### Scenario 1: Scale API Instances

```bash
# Terminal 1: Primary instance
gleitzeit serve --force-docker

# Terminal 2: Additional API instance on different port
gleitzeit serve --api-only --api-port 8001 --force-docker

# Terminal 3: Another API instance
gleitzeit serve --api-only --api-port 8002 --force-docker
```

All instances share the same Redis and worker pool through the shared `gleitzeit_network`.

### Scenario 2: Scale Workers

```bash
# Terminal 1: API + some workers
gleitzeit serve --force-docker

# Terminal 2: Additional workers only
gleitzeit serve --workers-only --force-docker

# Workers from both instances process jobs from shared Redis
```

### Scenario 3: Port Conflict Detection

```bash
# If port 8000 is already in use:
$ gleitzeit serve
❌ Error: Cannot start API: Port 8000 is already in use.
   Either stop the existing service or use --api-port to specify a different port.

# Solution: Use different port
$ gleitzeit serve --api-port 8001 --ui-port 8005
✅ Started successfully on ports 8001/8005
```

## Critical Fix #2: Heartbeat TTL Bug

### Problem Discovered

The service registry heartbeat had a **critical bug** that caused services to disappear from the registry:

1. Services registered with **60-second TTL**
2. Heartbeat runs every **30 seconds**
3. **BUG**: Heartbeat tried to read existing registry data before refreshing:
   ```python
   service_data = await self.smart_manager.redis.hgetall(f"service:registry:{name}")
   if service_data:  # ← This fails if TTL expired!
       await self.smart_manager.register_service(name, decoded_data)
   ```
4. If TTL expired between heartbeats (network hiccup, CPU spike, etc.), the key was gone
5. Heartbeat couldn't refresh because `if service_data` was False
6. **Result**: Services disappeared from registry permanently after ~60 seconds

### Fix Implemented

**File:** [src/gleitzeit/core/async_process_manager.py:935-957](src/gleitzeit/core/async_process_manager.py#L935-L957)

Now the heartbeat **always re-registers** services using current process info from memory, regardless of whether the registry key still exists:

```python
# Always re-register even if key expired - this fixes the TTL expiry bug
service_data = {
    "pid": str(info.pid),
    "port": str(info.port) if info.port else "",
    "started_at": info.started_at.isoformat(),
    "mode": "native"
}
await self.smart_manager.register_service(name, service_data)
logger.debug(f"Refreshed registration for {name} (PID: {info.pid}, Port: {info.port})")
```

**Result:**
- ✅ Services stay in registry as long as they're running
- ✅ Heartbeat properly refreshes TTL every 30 seconds
- ✅ Immune to transient Redis issues or expired keys
- ✅ Multi-instance deployments can properly discover each other

## Remaining Issues (Future Work)

### 1. No Automatic Cleanup of Orphaned Processes

When services die without proper cleanup (kill -9, crash, etc.), they leave ports occupied but aren't in the registry.

**Potential Solutions:**
- Add `gleitzeit ps` command to show all running instances
- Add `gleitzeit clean` command to kill orphaned processes
- Implement process ID tracking in filesystem

### 2. Docker Mode Has Different Behavior

Docker mode uses docker-compose which handles port conflicts differently.

**Consistency Needed:**
- Ensure both native and Docker modes have same error messages
- Document port management strategy for each mode

## Testing

Tested scenarios:
- ✅ Detect port conflicts for API (port 8000)
- ✅ Detect port conflicts for UI (port 8004)
- ✅ Clear error messages with actionable solutions
- ✅ Can start multiple instances with different ports
- ✅ Prevents silent failures

## Related Files

- [src/gleitzeit/core/async_process_manager.py](src/gleitzeit/core/async_process_manager.py) - Port detection logic
- [src/gleitzeit/core/process_manager.py](src/gleitzeit/core/process_manager.py) - Service registry with 60s TTL
- [NETWORK_FIX_SUMMARY.md](NETWORK_FIX_SUMMARY.md) - Related network sharing fix

## User Impact

**Positive:**
- ✅ Clear error messages instead of cryptic failures
- ✅ Horizontal scaling actually works
- ✅ Actionable guidance (use `--api-port` flag)

**Breaking Changes:**
- None - this is a pure improvement

**Migration:**
- No changes needed for existing users
- Old orphaned processes will now be properly detected
