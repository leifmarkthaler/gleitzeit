# Signal Registry Memory Leak Fix

**Date**: 2025-10-17
**Issue**: Signal registry memory leak - entries never expired if no waiter appeared
**Severity**: MEDIUM
**Status**: ✅ FIXED

---

## Problem Description

The signal registry was using a Redis **SET** (`signal:registry`) to track emitted signals waiting for handlers. When TaskExecutionWorker emitted a signal, it added an entry to this set:

```python
# OLD CODE (task_execution_worker.py:672-674)
registry_key = default_sharding.get_global_key("signal:registry")
registry_entry = f"{target_workflow}:{signal_name}"
await self.redis.sadd(registry_key, registry_entry)  # Adds to SET
```

SignalWorker would scan this set and remove entries when signals were processed:

```python
# OLD CODE (signal_worker.py:138-139)
registry_key = default_sharding.get_global_key("signal:registry")
registry_entries = await self.redis.smembers(registry_key)  # Read from SET
```

### The Memory Leak

**Problem**: If a signal was emitted but **no waiter ever appeared**, the registry entry would **never be removed**.

**Scenario**:
1. Task emits signal "task_complete"
2. Entry added to `signal:registry` set: `"workflow_123:task_complete"`
3. NO task is waiting for this signal (maybe workflow design changed, or task was cancelled)
4. SignalWorker sees no waiters, leaves entry in registry
5. **Entry stays in Redis forever** → Memory leak

**Impact**:
- Unbounded memory growth in `signal:registry` set
- Over time, thousands of orphaned signal entries could accumulate
- Increased SCAN time for SignalWorker

---

## Solution

Use **individual Redis keys with TTL** instead of a set. Redis will automatically expire entries after 1 hour.

### Architecture Change

**BEFORE**:
```
Redis SET: signal:registry
├── "workflow_123:signal_a"
├── "workflow_456:signal_b"  ← Never removed if no waiter
└── "workflow_789:signal_c"
```

**AFTER**:
```
Individual keys with TTL:
├── signal:registry:workflow_123:signal_a  (TTL: 3600s)
├── signal:registry:workflow_456:signal_b  (TTL: 3600s) ← Auto-expires
└── signal:registry:workflow_789:signal_c  (TTL: 3600s)
```

---

## Implementation

### 1. TaskExecutionWorker Changes

**File**: [src/gleitzeit/workers/task_execution_worker.py](src/gleitzeit/workers/task_execution_worker.py:670-675)

**Change**: Use `SETEX` (set with expiration) instead of `SADD`:

```python
# BEFORE (lines 672-674)
registry_key = default_sharding.get_global_key("signal:registry")
registry_entry = f"{target_workflow}:{signal_name}"
await self.redis.sadd(registry_key, registry_entry)

# AFTER (lines 670-675)
# CRITICAL: Also register in global signal registry for SignalWorker
# This eliminates race conditions - signals are discoverable immediately
# Use individual key with TTL for automatic cleanup (prevents memory leak)
registry_entry_key = f"signal:registry:{target_workflow}:{signal_name}"
signal_ttl = 3600  # 1 hour - signals expire if no waiter appears
await self.redis.setex(registry_entry_key, signal_ttl, "1")
```

**Key Changes**:
- ✅ Individual key per signal: `signal:registry:workflow_id:signal_name`
- ✅ TTL of 3600 seconds (1 hour)
- ✅ Automatic cleanup by Redis (no manual deletion loop needed)

### 2. SignalWorker Changes

**File**: [src/gleitzeit/workers/signal_worker.py](src/gleitzeit/workers/signal_worker.py:134-230)

**Change**: Use `SCAN` to find keys instead of `SMEMBERS` to read set:

```python
# BEFORE (lines 137-150)
# Get all pending signals from global registry
registry_key = default_sharding.get_global_key("signal:registry")
registry_entries = await self.redis.smembers(registry_key)

if not registry_entries:
    return

# Process each registry entry: "workflow_id:signal_name"
for entry in registry_entries:
    entry_str = entry.decode() if isinstance(entry, bytes) else entry
    workflow_id, signal_name = entry_str.split(":", 1)

# AFTER (lines 137-168)
# Scan for registry keys (now using individual keys with TTL instead of set)
# Pattern: signal:registry:workflow_id:signal_name
registry_pattern = "signal:registry:*"
registry_keys = []

cursor = 0
while True:
    cursor, keys = await self.redis.scan(cursor, match=registry_pattern, count=100)
    registry_keys.extend(keys)
    if cursor == 0:
        break

if not registry_keys:
    return

# Process each registry key: "signal:registry:workflow_id:signal_name"
for registry_key in registry_keys:
    key_str = registry_key.decode() if isinstance(registry_key, bytes) else registry_key

    # Extract workflow_id and signal_name from key
    # Key format: "signal:registry:workflow_id:signal_name"
    parts = key_str.split(":", 3)  # Split into max 4 parts
    if len(parts) < 4:
        logger.warning(f"Invalid registry key format: {key_str}")
        continue

    workflow_id = parts[2]
    signal_name = parts[3]
```

**Key Changes**:
- ✅ Use `SCAN` with pattern `signal:registry:*` instead of `SMEMBERS`
- ✅ Parse workflow_id and signal_name from key format
- ✅ Remove entries using `DELETE` instead of `SREM`

**Cleanup Changes** (2 locations):

```python
# BEFORE (line 187)
await self.redis.srem(registry_key, entry)

# AFTER (line 205)
await self.redis.delete(registry_key)

# BEFORE (line 205)
await self.redis.srem(registry_key, entry)

# AFTER (line 223)
await self.redis.delete(registry_key)
```

---

## Benefits

### 1. Automatic Cleanup ✅
- **No memory leak**: Signals expire after 1 hour if no waiter appears
- **No manual cleanup loop**: Redis handles TTL automatically
- **Configurable TTL**: Easy to adjust `signal_ttl` if needed

### 2. Simplified Code ✅
- **Less code**: No need for manual expiration logic
- **Redis-idiomatic**: Using built-in TTL mechanism
- **Easier to reason about**: Clear expiration policy

### 3. Better Observability ✅
- **Can monitor TTL**: `TTL signal:registry:*` shows remaining time
- **Can count orphaned signals**: `SCAN` shows how many exist
- **Clear key format**: Easy to identify in Redis

---

## Testing

### Manual Test

1. **Emit signal without waiter**:
   ```python
   # Task emits signal but no one is waiting
   await emit_signal(workflow_id="test_wf", signal_name="orphan_signal")
   ```

2. **Verify key exists with TTL**:
   ```bash
   redis-cli TTL signal:registry:test_wf:orphan_signal
   # Output: 3600 (or less if time has passed)
   ```

3. **Wait 1 hour** (or use `redis-cli EXPIRE signal:registry:test_wf:orphan_signal 5`)

4. **Verify automatic cleanup**:
   ```bash
   redis-cli EXISTS signal:registry:test_wf:orphan_signal
   # Output: 0 (key expired)
   ```

### Integration Test

Check SignalWorker logs:
```
SignalWorker found 0 signals in global registry  # After TTL expires
```

Check memory growth:
```bash
redis-cli INFO memory | grep used_memory_human
# Should not grow unbounded over time
```

---

## Performance Considerations

### SCAN vs SMEMBERS

**BEFORE**:
- `SMEMBERS signal:registry` - O(N) where N = number of entries
- Single Redis call
- Returns all entries at once

**AFTER**:
- `SCAN cursor MATCH signal:registry:*` - O(N) where N = number of keys (but cursor-based)
- Multiple Redis calls (cursor iteration)
- Returns keys in batches of 100

**Performance Impact**:
- **Minimal**: SCAN is cursor-based and non-blocking
- **Scalable**: Works well even with thousands of keys
- **Trade-off**: Slight increase in Redis round-trips vs unbounded memory growth

### TTL Overhead

- TTL tracking in Redis has minimal overhead
- Much cheaper than scanning and manually deleting expired entries
- Redis handles TTL expiration efficiently in background

---

## Configuration

The TTL can be adjusted if needed:

```python
# In task_execution_worker.py line 674
signal_ttl = 3600  # 1 hour (default)

# Can be configured via config:
signal_ttl = self.config.get('signal_registry_ttl', 3600)
```

**Recommendations**:
- **1 hour (3600s)**: Good default for most workflows
- **Shorter (300s)**: For high-throughput, short-lived workflows
- **Longer (7200s)**: For long-running workflows with delayed signals

---

## Migration Notes

### Backward Compatibility

**Old registry entries** (if any exist):
```bash
# Old set-based registry may still exist
redis-cli SMEMBERS signal:registry

# Clean up old registry:
redis-cli DEL signal:registry
```

### Deployment

No special migration needed:
1. Deploy new code
2. New signals use individual keys with TTL
3. Old set-based registry (if exists) can be manually deleted
4. SignalWorker will automatically switch to SCAN-based lookup

---

## Related Issues

This fix addresses Issue #6 from [HANDLER_WORKER_ARCHITECTURE_REVIEW.md](HANDLER_WORKER_ARCHITECTURE_REVIEW.md):

> **6. Signal Registry Memory Leak**
> **Severity**: 🟡 MEDIUM
> **Issue**: Global signal registry entries never expire if no waiter appears
> **Impact**: Unbounded memory growth in `signal:registry` set
> **Recommendation**: Use sorted set with expiration times

**Implementation Note**: We chose **individual keys with TTL** instead of sorted set because:
- ✅ Simpler implementation
- ✅ Redis handles cleanup automatically
- ✅ No need for manual cleanup loop
- ✅ Easier to monitor and debug

---

## Summary

✅ **Memory leak fixed**: Signals now expire after 1 hour if no waiter appears
✅ **Automatic cleanup**: Redis TTL mechanism handles expiration
✅ **Code simplified**: No manual cleanup logic needed
✅ **Redis-idiomatic**: Using built-in key expiration

**Files Changed**:
1. [src/gleitzeit/workers/task_execution_worker.py](src/gleitzeit/workers/task_execution_worker.py) (lines 670-675)
2. [src/gleitzeit/workers/signal_worker.py](src/gleitzeit/workers/signal_worker.py) (lines 134-230)

**Severity Reduced**: 🟡 MEDIUM → ✅ RESOLVED

---

*Fixed on 2025-10-17*
