# Gleitzeit Startup Loop Audit Report

## Executive Summary
The startup loop is caused by a process management race condition where restarted processes kill each other due to port conflicts. When the monitoring loop detects a dead process and restarts it with `kill_existing=False`, the new process still attempts to bind to ports that may be in use, causing cascading failures.

## Root Causes

### 1. **Port Conflict Management**
- When `kill_existing=False`, processes should NOT kill anything on the port
- Current code respects this flag, but the 0.5s health check is insufficient
- Processes die with exit code -9 (SIGKILL) indicating external termination

### 2. **Process Lifecycle Issues**
- No differentiation between "managed" processes and external ones
- Restart counter resets too early (before process stability confirmed)
- No exponential backoff for restart attempts

### 3. **Race Conditions**
- Multiple serve instances running simultaneously (see background tasks)
- Each instance tries to manage the same ports
- No inter-process coordination or locking

## Evidence from Logs

```
17:50:02,041 - Killing existing process on port 8004 (PID: 74239)
17:50:07,545 - ui process died (exit code: -9)
```

Pattern repeats hundreds of times showing:
- 5+ second delay between kill and death notification
- Exit codes: -9 (SIGKILL), -15 (SIGTERM), 1 (general error)
- Alternating between API (port 8000) and UI (port 8004)

## Recommended Fixes

### Immediate Fixes

1. **Implement Process Ownership**
```python
# Track process PIDs we actually started
self.managed_pids: Set[int] = set()

# Only kill processes we don't own
if proc.pid not in self.managed_pids:
    proc.kill()
```

2. **Add Exponential Backoff**
```python
backoff_seconds = min(300, 2 ** self.restart_attempts[name])
time.sleep(backoff_seconds)
```

3. **Improve Health Checks**
```python
# Wait longer and verify port binding
for i in range(10):  # Check for 10 seconds
    time.sleep(1)
    if self._check_port_bound(port, proc.pid):
        break
```

### Long-term Solutions

1. **Use Process Groups**
- Create processes in separate process groups
- Use `os.setpgid()` to isolate process trees
- Kill only processes in our group

2. **Implement Lock Files**
```python
lock_file = f"/tmp/gleitzeit_{port}.lock"
with open(lock_file, 'w') as f:
    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
```

3. **Add Process Communication**
- Use Redis pubsub for coordination
- Implement leader election for single manager
- Share process state across instances

## Testing Recommendations

1. **Chaos Testing**
   - Randomly kill processes during operation
   - Simulate port conflicts
   - Test with multiple simultaneous serve instances

2. **Performance Testing**
   - Measure restart time under load
   - Track resource usage during restart loops
   - Monitor for memory/fd leaks

3. **Integration Testing**
   - Test with actual workflows running
   - Verify data consistency after restarts
   - Check Redis connection pooling behavior

## Implementation Priority

1. **Critical** - Fix process ownership tracking
2. **High** - Add exponential backoff
3. **High** - Improve health checks
4. **Medium** - Implement lock files
5. **Low** - Add process groups

## Metrics to Track

- Time to recovery after process death
- Number of restart attempts before stability
- Resource usage during restart cycles
- Port binding success rate
- Process uptime distribution

## Conclusion

The startup loop is a critical issue affecting system stability. The root cause is poor process lifecycle management combined with aggressive port conflict resolution. The recommended fixes focus on:

1. Better process ownership tracking
2. Smarter restart strategies
3. Improved inter-process coordination

Implementation should proceed incrementally with thorough testing at each stage.