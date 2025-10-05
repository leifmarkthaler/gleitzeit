# Gleitzeit Stop and Restart Command Audit

**Date**: 2025-09-30
**Focus**: `gleitzeit stop` and `gleitzeit serve --restart` implementations
**Status**: 🔴 **CRITICAL ISSUES FOUND**

## Executive Summary

Found **6 critical issues** in stop and restart implementations that can cause:
- Race conditions between restart and existing services
- Orphaned processes not being cleaned up
- Port conflicts on restart
- Service registry inconsistencies
- Memory leaks from unclosed Redis connections

## Detailed Findings

---

## Issue 1: Race Condition in `serve --restart`

**File**: `src/gleitzeit/cli/serve_unified.py:283-303`

**Severity**: 🔴 **CRITICAL**

### Problem

The `--restart` flag has a race condition when killing existing processes:

```python
if restart:
    click.echo("🔄 Restarting services...")
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            connections = proc.connections()
            for conn in connections:
                if hasattr(conn, 'laddr') and conn.laddr.port in [api_port, ui_port]:
                    click.echo(f"  Stopping existing process on port {conn.laddr.port} (PID: {proc.info['pid']})")
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except psutil.TimeoutExpired:
                        proc.kill()
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    await asyncio.sleep(1)  # ← Only 1 second wait!
```

**Issues**:
1. **Only checks API/UI ports** - doesn't kill workers
2. **1 second wait is too short** - ports may not be released
3. **No service registry cleanup** - stale entries remain in Redis
4. **Doesn't check if processes actually died**
5. **Race condition with AsyncServiceManager.stop_all()** at line 748-752

### Impact

- New services start while old ones are still shutting down
- Port conflicts (`EADDRINUSE`)
- Multiple workers processing same messages (duplicate work)
- Service registry shows dead services as "healthy"

### Fix Required

```python
async def restart_services(manager, api_port, ui_port):
    """Properly restart all services with cleanup"""
    click.echo("🔄 Restarting services...")

    # 1. Stop via service manager first
    await manager.stop_all()

    # 2. Wait for graceful shutdown
    await asyncio.sleep(3)

    # 3. Force kill any remaining processes
    import psutil
    killed_pids = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = ' '.join(proc.info.get('cmdline', []))
            # Check for gleitzeit processes
            if 'gleitzeit' in cmdline and any(x in cmdline for x in [
                'api.main', 'ui.api.app', 'workers.runner'
            ]):
                click.echo(f"  Force killing gleitzeit process PID {proc.pid}")
                proc.kill()
                killed_pids.append(proc.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # 4. Wait for OS to release ports
    if killed_pids:
        click.echo(f"  Waiting for {len(killed_pids)} processes to die...")
        await asyncio.sleep(5)

    # 5. Clear service registry
    if manager.smart_manager:
        # Clear all service entries
        await manager.smart_manager.redis.delete(
            *[f"service:registry:{name}" for name in manager.process_manager.processes.keys()]
        )
        click.echo("  Cleared service registry")

    click.echo("✅ Restart cleanup complete")
```

---

## Issue 2: Incomplete Process Cleanup in stop_native_services

**File**: `src/gleitzeit/cli/stop_command.py:118-236`

**Severity**: 🔴 **CRITICAL**

### Problem

The `stop_native_services` function has multiple cleanup gaps:

```python
def stop_native_services(force: bool, timeout: int, stop_all: bool):
    # ...
    # Collect processes to stop
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        cmdline_str = ' '.join(cmdline)

        if 'python' in cmdline_str and 'gleitzeit' in cmdline_str:
            # Always stop service processes
            if any(module in cmdline_str for module in [
                'gleitzeit.api.main',
                'gleitzeit.ui.api.app',
                'gleitzeit.workers.runner'
            ]):
                processes_to_stop.append(proc)
            # If --all flag is used, also stop gleitzeit serve processes
            elif stop_all and 'gleitzeit serve' in cmdline_str:
                processes_to_stop.append(proc)
```

**Issues**:
1. **Doesn't stop background worker processes** - only stops main processes
2. **Misses container-based handlers** - Python handlers running in Docker
3. **Service registry cleanup only with --all flag** (line 226-235)
4. **No cleanup of worker metrics keys**
5. **No cleanup of handler registration keys**
6. **Doesn't stop AsyncServiceManager heartbeat loops**

### Impact

- Orphaned worker processes continue running after "stop"
- Memory leak from unclosed Redis connections
- Stale metrics accumulate in Redis
- Service registry shows services as "running" after stop
- Handler configs remain registered

### Fix Required

```python
def stop_native_services(force: bool, timeout: int, stop_all: bool):
    """Stop native Python processes with complete cleanup"""
    click.echo("🔧 Stopping native services...")

    # 1. Find ALL gleitzeit processes
    processes_to_stop = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info.get('cmdline', [])
            if not cmdline:
                continue
            cmdline_str = ' '.join(cmdline)

            # Stop ALL gleitzeit processes (not just main ones)
            if 'python' in cmdline_str and 'gleitzeit' in cmdline_str:
                # Include: api, ui, workers, serve, handlers
                processes_to_stop.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # 2. Gracefully terminate
    for proc in processes_to_stop:
        try:
            click.echo(f"   Terminating PID {proc.pid}")
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # 3. Wait for graceful shutdown
    if processes_to_stop:
        click.echo(f"   Waiting up to {timeout}s for graceful shutdown...")
        gone, alive = psutil.wait_procs(processes_to_stop, timeout=timeout)

        # 4. Force kill remaining processes
        if alive:
            click.echo(f"   Force killing {len(alive)} remaining processes...")
            for proc in alive:
                try:
                    proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

    # 5. ALWAYS clean service registry (not just with --all)
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379)

        # Clear service registry
        for key in r.scan_iter(match="service:registry:*"):
            r.delete(key)

        # Clear worker metrics
        for key in r.scan_iter(match="{shard:0}:worker:metrics:*"):
            r.delete(key)

        # Clear worker registry
        for key in r.scan_iter(match="{shard:0}:worker:registry:*"):
            r.delete(key)

        # Clear handler registrations
        for key in r.scan_iter(match="handler:registration:*"):
            r.delete(key)

        click.echo("   ✅ Cleaned Redis keys (service registry, worker metrics, handler configs)")
    except Exception as e:
        click.echo(f"   ⚠️  Redis cleanup failed: {e}")

    # 6. Clean PID files
    log_dir = Path("logs")
    if log_dir.exists():
        for pid_file in log_dir.glob("*.pid"):
            pid_file.unlink()

    click.echo(f"✅ Stopped {len(processes_to_stop)} native processes")
```

---

## Issue 3: Inconsistent Service Registry Cleanup

**File**: `src/gleitzeit/core/async_process_manager.py:777-793`

**Severity**: 🟡 **MODERATE**

### Problem

The `stop_all()` method only unregisters services it started:

```python
async def stop_all(self):
    """Stop all services"""
    await self.process_manager.stop_all()

    # Only unregister services if we started them (not if we attached)
    if self.smart_manager and not getattr(self, 'attached_mode', False):
        # Track which services we actually started vs attached to
        started_services = set()
        for name, info in self.process_manager.processes.items():
            # Services with actual subprocess objects were started by us
            if info.process is not None:
                started_services.add(name)

        # Only unregister services we started
        for service_name in started_services:
            await self.smart_manager.unregister_service(service_name)
```

**Issues**:
1. **Doesn't unregister attached services** - leaves stale registry entries
2. **No cleanup of service heartbeat task** - heartbeat loop keeps running
3. **No cleanup of worker configs in Redis**
4. **Race condition**: heartbeat loop may re-register after unregister

### Impact

- `gleitzeit ps` shows dead services as healthy
- Service registry grows indefinitely (memory leak)
- Heartbeat loop keeps running after stop
- TTL-based cleanup takes 60+ seconds

### Fix Required

```python
async def stop_all(self):
    """Stop all services with complete cleanup"""
    # 1. Stop heartbeat loop first to prevent re-registration
    if hasattr(self, '_heartbeat_task') and self._heartbeat_task:
        self._heartbeat_task.cancel()
        try:
            await self._heartbeat_task
        except asyncio.CancelledError:
            pass
        logger.info("Stopped service heartbeat loop")

    # 2. Stop all processes
    await self.process_manager.stop_all()

    # 3. Unregister ALL services (not just ones we started)
    if self.smart_manager:
        all_services = list(self.process_manager.processes.keys())
        for service_name in all_services:
            await self.smart_manager.unregister_service(service_name)
            logger.info(f"Unregistered service {service_name}")

        # 4. Clean worker configs
        if hasattr(self, '_stored_worker_configs'):
            for config_key in self._stored_worker_configs:
                await self.smart_manager.redis.delete(config_key)
                logger.info(f"Deleted worker config {config_key}")

        # 5. Close Redis connection
        await self.smart_manager.redis.close()
        logger.info("Closed Redis connections")
```

---

## Issue 4: Missing Docker Process Cleanup

**File**: `src/gleitzeit/cli/stop_command.py:43-115`

**Severity**: 🟡 **MODERATE**

### Problem

The `stop_docker_services` function doesn't stop container-based handlers:

```python
def stop_docker_services(force: bool, timeout: int, stop_all: bool):
    """Stop Docker services"""
    # Find all gleitzeit Docker compose files (new UUID-based pattern)
    compose_files = list(Path(".").glob("docker-compose-*.yml"))

    # ...only stops compose-managed containers
```

**Issues**:
1. **Doesn't stop standalone handler containers** (e.g., Python handler containers)
2. **Doesn't check `docker ps` for orphaned containers**
3. **No network cleanup** - Docker networks remain
4. **No volume cleanup** - volumes accumulate

### Impact

- Handler containers keep running after "stop"
- Docker networks accumulate (memory leak)
- Volumes fill disk space
- Port conflicts when restarting

### Fix Required

```python
def stop_docker_services(force: bool, timeout: int, stop_all: bool):
    """Stop Docker services including handler containers"""
    click.echo("🐳 Stopping Docker services...")

    # 1. Stop compose-managed services
    compose_files = list(Path(".").glob("docker-compose-gleitzeit-*.yml"))
    for compose_file in compose_files:
        # ... existing code ...

    # 2. Stop standalone handler containers
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", "label=gleitzeit.handler", "--format", "{{.ID}}"],
            capture_output=True,
            text=True,
            timeout=10
        )
        container_ids = result.stdout.strip().split('\n')
        container_ids = [cid for cid in container_ids if cid]

        if container_ids:
            click.echo(f"   Found {len(container_ids)} handler containers")
            stop_cmd = ["docker", "stop"]
            if force:
                stop_cmd.extend(["-t", "1"])
            else:
                stop_cmd.extend(["-t", str(timeout)])
            stop_cmd.extend(container_ids)

            subprocess.run(stop_cmd, timeout=timeout + 5)
            click.echo(f"   ✅ Stopped {len(container_ids)} handler containers")
    except Exception as e:
        click.echo(f"   ⚠️  Failed to stop handler containers: {e}")

    # 3. Clean up networks
    try:
        result = subprocess.run(
            ["docker", "network", "ls", "--filter", "name=gleitzeit", "--format", "{{.ID}}"],
            capture_output=True,
            text=True,
            timeout=5
        )
        network_ids = result.stdout.strip().split('\n')
        network_ids = [nid for nid in network_ids if nid]

        if network_ids:
            subprocess.run(["docker", "network", "rm"] + network_ids, timeout=10)
            click.echo(f"   🗑️  Removed {len(network_ids)} Docker networks")
    except Exception as e:
        click.echo(f"   ⚠️  Network cleanup failed: {e}")
```

---

## Issue 5: No Validation of Stop Success

**File**: `src/gleitzeit/cli/stop_command.py:238-241`

**Severity**: 🟡 **MODERATE**

### Problem

The `check_if_stopped()` function only checks mode detection:

```python
def check_if_stopped() -> bool:
    """Check if all services have been stopped"""
    mode = detect_running_mode()
    return mode is None
```

**Issues**:
1. **Doesn't verify processes actually died**
2. **Doesn't check for orphaned containers**
3. **Doesn't check Redis for stale keys**
4. **Returns True even if cleanup failed**

### Impact

- False positive: reports "stopped" when services still running
- No feedback on orphaned processes
- User thinks stop succeeded when it partially failed

### Fix Required

```python
def check_if_stopped() -> Tuple[bool, List[str]]:
    """
    Check if all services have been stopped.

    Returns:
        (success: bool, issues: List[str])
    """
    issues = []

    # 1. Check for running processes
    import psutil
    running_procs = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = ' '.join(proc.info.get('cmdline', []))
            if 'gleitzeit' in cmdline and 'python' in cmdline:
                running_procs.append(proc.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if running_procs:
        issues.append(f"Found {len(running_procs)} running processes: {running_procs}")

    # 2. Check for Docker containers
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", "label=gleitzeit", "--format", "{{.ID}}"],
            capture_output=True,
            text=True,
            timeout=5
        )
        containers = [c for c in result.stdout.strip().split('\n') if c]
        if containers:
            issues.append(f"Found {len(containers)} running containers")
    except:
        pass

    # 3. Check Redis for stale service registry
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379)
        stale_keys = []
        for key in r.scan_iter(match="service:registry:*"):
            stale_keys.append(key.decode())
        if stale_keys:
            issues.append(f"Found {len(stale_keys)} stale registry keys")
    except:
        pass

    return (len(issues) == 0, issues)
```

---

## Issue 6: Restart Logic Duplication

**File**: Multiple files

**Severity**: 🟢 **LOW**

### Problem

Restart logic exists in multiple places with inconsistent behavior:

1. **serve_unified.py:283-303** - CLI --restart flag
2. **async_process_manager.py:747-752** - Manager restart parameter
3. **No coordination between them**

```python
# serve_unified.py
if restart:
    # Kills processes on ports (API/UI only)
    await asyncio.sleep(1)

# async_process_manager.py
if restart and self.existing_services:
    logger.info("Restarting services...")
    await self.stop_all()
    await asyncio.sleep(2)
```

**Issues**:
1. **Different sleep durations** (1s vs 2s)
2. **serve_unified kills by port, manager kills by service**
3. **Race condition**: both try to stop at same time
4. **No synchronization**

### Impact

- Inconsistent restart behavior
- Difficult to debug restart issues
- Code maintenance burden

### Fix Required

Create single restart coordinator:

```python
# src/gleitzeit/core/restart_coordinator.py
class RestartCoordinator:
    """Coordinates safe restart of all services"""

    async def restart_all(
        self,
        manager: AsyncServiceManager,
        api_port: int,
        ui_port: int,
        force: bool = False
    ):
        """
        Safely restart all services with proper cleanup.

        Steps:
        1. Stop via service manager (graceful)
        2. Force kill remaining processes
        3. Clean Redis keys
        4. Wait for port release
        5. Verify cleanup
        6. Start new services
        """
        # ... centralized restart logic ...
```

---

## Summary of Issues

| Issue | Severity | File | Impact |
|-------|----------|------|--------|
| Race condition in --restart | 🔴 CRITICAL | serve_unified.py:283 | Port conflicts, duplicate workers |
| Incomplete process cleanup | 🔴 CRITICAL | stop_command.py:118 | Orphaned processes, memory leaks |
| Service registry inconsistency | 🟡 MODERATE | async_process_manager.py:777 | Stale registry entries |
| Missing Docker cleanup | 🟡 MODERATE | stop_command.py:43 | Orphaned containers |
| No stop validation | 🟡 MODERATE | stop_command.py:238 | False positive reports |
| Restart logic duplication | 🟢 LOW | Multiple | Maintenance burden |

---

## Recommended Actions

### Priority 1 (Fix Immediately)
1. Fix race condition in `serve --restart` (Issue #1)
2. Complete process cleanup in `stop_native_services` (Issue #2)

### Priority 2 (Fix Soon)
3. Consistent service registry cleanup (Issue #3)
4. Docker handler container cleanup (Issue #4)

### Priority 3 (Enhancement)
5. Stop validation with detailed feedback (Issue #5)
6. Centralize restart logic (Issue #6)

---

## Testing Recommendations

### Test Case 1: Basic Stop
```bash
# Start services
gleitzeit serve -c gleitzeit.yaml

# Wait 30s for heartbeats
sleep 30

# Stop services
gleitzeit stop

# Verify no processes running
ps aux | grep gleitzeit | grep -v grep
# Should return nothing

# Verify no stale registry
redis-cli KEYS "service:registry:*"
# Should return empty
```

### Test Case 2: Restart
```bash
# Start services
gleitzeit serve -c gleitzeit.yaml

# Restart
gleitzeit serve -c gleitzeit.yaml --restart

# Should NOT get EADDRINUSE errors
# Check logs for port conflicts
```

### Test Case 3: Docker Cleanup
```bash
# Start in Docker mode
gleitzeit serve -c gleitzeit.yaml --force-docker

# Stop
gleitzeit stop

# Verify no containers running
docker ps --filter "label=gleitzeit"
# Should return nothing
```

### Test Case 4: Orphaned Processes
```bash
# Start services
gleitzeit serve -c gleitzeit.yaml

# Kill main process only (simulate crash)
pkill -f "gleitzeit serve"

# Workers should still be running (orphaned)
ps aux | grep "gleitzeit.workers.runner"

# Run stop command
gleitzeit stop

# Verify workers are killed
ps aux | grep "gleitzeit.workers.runner"
# Should return nothing
```

---

## Backward Compatibility

All proposed fixes are backward compatible:
- ✅ Existing CLI arguments unchanged
- ✅ New cleanup is stricter but safe
- ✅ Stop command still works with --force, --timeout, --all flags
- ✅ --restart flag behavior improves (no breaking changes)

---

## Architecture Compliance

These issues don't violate the stateless architecture:
- ✅ Still using Redis as source of truth
- ✅ Still TTL-based for auto-cleanup
- ✅ Fixes improve cleanup, don't add local state
- ⚠️  Issue: stop/restart bypass stateless cleanup (should trigger via Redis signals)

**Recommendation**: Consider adding stop/restart signals to Redis:
```python
# Stateless stop via Redis
await redis.publish("gleitzeit:commands", json.dumps({
    "command": "stop_all",
    "timestamp": datetime.utcnow().isoformat()
}))

# Workers/services listen for stop commands
# Self-terminate when received
```

This would make stop/restart truly stateless and distributed.
