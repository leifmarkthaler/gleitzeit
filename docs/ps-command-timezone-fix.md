# Fix: ps Command Timezone Bug and Mode Mislabeling

## Problem Summary

When running `gleitzeit ps`, workers were showing:
- **Incorrect uptime**: "2h 7m" instead of actual "9m"
- **Wrong mode**: "docker" instead of "native"
- **Confusing service names**: "worker-api" instead of "worker_api"

## Root Causes

### 1. Timezone Mismatch Bug
**Location**: [src/gleitzeit/cli/ps_command.py:80,127](../src/gleitzeit/cli/ps_command.py#L80)

**The Bug**:
- Workers store timestamps using `datetime.utcnow().isoformat()` → UTC time
- ps_command was calculating uptime using `datetime.now() - started_at` → local time
- On systems with timezone offset (e.g., CEST = UTC+2), this created a 2-hour error

**Example**:
```python
# Worker stores (UTC):     2025-10-22T15:11:28
# ps reads as naive time:  2025-10-22 15:11:28 (assumes local)
# Current time (CEST):     2025-10-22 17:19:12 (UTC+2)
# Calculated uptime:       17:19 - 15:11 = 2h 8m ❌
# Actual uptime:           ~9 minutes ✅
```

**The Fix**:
```python
# Before:
time_since_start = datetime.now() - started_at

# After:
time_since_start = datetime.utcnow() - started_at
```

### 2. Hardcoded Docker Mode
**Location**: [src/gleitzeit/cli/ps_command.py:139](../src/gleitzeit/cli/ps_command.py#L139)

**The Bug**:
```python
worker_info['mode'] = 'docker'  # Workers are typically Docker-based
```

This hardcoded ALL workers as `mode='docker'`, even native async workers.

**The Fix**:
```python
# Use mode from worker_info if present, otherwise default to 'native'
if 'mode' not in worker_info:
    worker_info['mode'] = 'native'
```

### 3. Service Name Convention
**Location**: [src/gleitzeit/cli/ps_command.py:137](../src/gleitzeit/cli/ps_command.py#L137)

**The Bug**:
```python
worker_info['service_type'] = f"worker-{worker_type}"  # Using dash
```

This created inconsistency with registry keys which use underscores.

**The Fix**:
```python
worker_info['service_type'] = f"worker_{worker_type}"  # Using underscore
```

## Verification

### Before Fix:
```
worker-api      0.0.0.0    8000    docker    ✅ healthy  2h 7m
worker-ui       0.0.0.0    8004    docker    ✅ healthy  2h 7m
```

### After Fix:
```
worker_api      0.0.0.0    8000    native    ✅ healthy  9m 5s
worker_ui       0.0.0.0    8004    native    ✅ healthy  9m 5s
```

## No Cleanup Issue

During investigation, we confirmed that:
- ✅ Service registry entries DO have TTL (60 seconds)
- ✅ Cleanup on shutdown works correctly
- ✅ No stale entries persist in Redis
- ✅ The "stale" entries were actually current workers with wrong uptime calculation

## Files Modified

1. [src/gleitzeit/cli/ps_command.py](../src/gleitzeit/cli/ps_command.py)
   - Line 80: Changed `datetime.now()` → `datetime.utcnow()`
   - Line 127: Changed `datetime.now()` → `datetime.utcnow()`
   - Line 139: Changed hardcoded `'docker'` to conditional `'native'` default
   - Line 137: Changed `worker-{type}` → `worker_{type}`

## Related Work

As part of this investigation, we also:
- Removed debug logging from EventBroadcaster initialization
- Confirmed API worker startup is working correctly
- Verified EventBroadcaster creates its own Redis connection (avoiding deadlock)

## Testing

```bash
# Test ps command shows correct uptimes and modes
gleitzeit ps

# Should show:
# - Uptimes in minutes (not hours due to timezone offset)
# - Mode as 'native' for async workers
# - Service names with underscores (worker_api, worker_ui)
```
