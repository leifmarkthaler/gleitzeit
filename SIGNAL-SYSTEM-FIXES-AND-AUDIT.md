# Signal System Fixes and Audit Report

## Date: 2025-09-14

## Issue Summary
The easy client's signal workflow was failing because:
1. `UnifiedRedisAdapter` was missing the `scan_iter` method needed by `SignalMonitorService`
2. Signal handler was inconsistently using `self.persistence.redis` vs `self.persistence`
3. Signal workflows were getting stuck in "running" state despite signals being sent

## Fixes Applied

### 1. Implemented `scan_iter` in UnifiedRedisAdapter
**File**: `src/gleitzeit/persistence/unified_redis.py` (lines 1615-1667)

**Implementation**:
```python
async def scan_iter(self, pattern: str = "*", count: int = 100):
    """
    Async generator that yields keys matching pattern using Redis SCAN.

    - Automatically adds key prefix to pattern
    - Yields decoded keys without the prefix
    - Handles byte/string conversion
    - Gracefully handles errors without raising
    """
```

**Key Features**:
- Properly handles the `gleitzeit:` key prefix
- Uses Redis SCAN for memory-efficient iteration
- Returns keys without prefix for consistency with other methods

### 2. Fixed SignalMonitorService Persistence Calls
**File**: `src/gleitzeit/signals/monitor.py`

**Changes**:
- Line 251: `self.redis.scan_iter` → `self.persistence.scan_iter`
- Line 347: `self.redis.complete_task` → `self.persistence.complete_task`

**Rationale**:
- The monitor receives persistence from SystemManager
- Should use persistence methods consistently for proper key prefixing

### 3. Fixed SignalHandler Redis Access Pattern
**File**: `src/gleitzeit/signals/handler.py`

**Changes Applied**:
- All `self.persistence.redis.sadd` → `self.persistence.sadd`
- All `self.persistence.redis.hset` → `self.persistence.hset`
- All `self.persistence.redis.zadd` → `self.persistence.zadd`
- All `self.persistence.redis.smembers` → `self.persistence.smembers`
- All `self.persistence.redis.srem` → `self.persistence.srem`

**Impact**:
- Keys are now stored with proper `gleitzeit:` prefix
- Consistent with how other components access Redis

## Current Status After Fixes

### Working:
✅ Server starts without scan_iter errors
✅ Signal workflows can be submitted
✅ Signal wait tasks register successfully
✅ Signals can be sent to workflows
✅ Signal monitor processes incoming signals

### Still Not Working:
❌ Signal monitor doesn't find/wake waiting tasks
❌ Workflows remain stuck in "running" state
❌ No "Waking task" log messages appear

## Root Cause Analysis

### The Key Mismatch Problem

The signal system has a fundamental key pattern mismatch:

1. **Signal Handler Storage** (uses persistence layer with prefix):
   - Stores waiter metadata: `gleitzeit:signal:waiter:{signal_id}`
   - Stores signal waiters: `gleitzeit:signal:{workflow_id}:{signal_name}:waiters`

2. **Signal Monitor Retrieval** (expects keys with prefix):
   - Scans for: `gleitzeit:signal:waiter:*`
   - Gets waiters from: `gleitzeit:signal:{workflow_id}:{signal_name}:waiters`

3. **The Problem**:
   - Monitor line 232: Creates scoped key WITHOUT prefix
   - Monitor line 233: Tries to get members using persistence.smembers
   - But the handler stored them WITH prefix via persistence.sadd

### Critical Code Path

**Signal Registration** (`handler.py`):
```python
# Line 102-106
scoped_signal_key = self._get_scoped_signal_key(workflow_id, signal_name)
# Returns: "signal:{workflow_id}:{signal_name}:waiters"

await self.persistence.sadd(scoped_signal_key, waiter_key)
# Stores at: "gleitzeit:signal:{workflow_id}:{signal_name}:waiters"
```

**Signal Wake Attempt** (`monitor.py`):
```python
# Line 232-233
scoped_signal_key = f"signal:{workflow_id}:{signal_name}:waiters"
waiters = await self.redis.smembers(scoped_signal_key)
# Looks for: "signal:{workflow_id}:{signal_name}:waiters" (NO PREFIX!)
```

## Remaining Issues to Fix

### Issue 1: Monitor Uses Wrong Redis Access
**Location**: `src/gleitzeit/signals/monitor.py`, lines 233, 252, 260, 273, 276, etc.

The monitor uses `self.redis.*` for some operations but should use `self.persistence.*` consistently.

### Issue 2: Missing `update_workflow` Method
**Error**: `'UnifiedRedisAdapter' object has no attribute 'update_workflow'`
**Location**: Called by `ReconciliationService`

The reconciliation service expects an `update_workflow` method that doesn't exist in UnifiedRedisAdapter.

### Issue 3: Event System Websocket Errors
**Errors**:
- `WebSocketMessage() got multiple values for keyword argument 'type'`
- WebSocket connection issues in client event system

## Recommended Next Steps

### 1. Fix Signal Monitor Redis Access
Replace all `self.redis.*` calls in `monitor.py` with `self.persistence.*`:
- Line 233: `await self.redis.smembers` → `await self.persistence.smembers`
- Line 252: `await self.redis.hgetall` → `await self.persistence.hgetall`
- Line 260: `await self.redis.delete` → `await self.persistence.delete`
- Line 273: `await self.redis.srem` → `await self.persistence.srem`
- Line 276: `await self.redis.delete` → `await self.persistence.delete`
- And all other similar occurrences

### 2. Implement Missing Methods in UnifiedRedisAdapter
Add the `update_workflow` method that ReconciliationService expects:
```python
async def update_workflow(self, workflow_id: str, **updates) -> bool:
    """Update workflow fields."""
    workflow_key = f"workflow:{workflow_id}"
    if updates:
        await self.hset(workflow_key, mapping=updates)
        return True
    return False
```

### 3. Fix Key Pattern Generation
Ensure the monitor uses the same key generation methods as the handler:
- Both should use `_get_scoped_signal_key()` method
- Both should use persistence layer methods consistently

### 4. Add Debug Logging
Add detailed logging to trace the exact keys being used:
```python
# In handler.py
logger.debug(f"Storing waiter at key: {scoped_signal_key}")

# In monitor.py
logger.debug(f"Looking for waiters at key: {scoped_signal_key}")
logger.debug(f"Found {len(waiters)} waiters")
```

## Test Case for Verification

```python
# test_signal_debug.py
import asyncio
from gleitzeit.client import GleitzeitClient

async def debug_signal_flow():
    client = GleitzeitClient(base_url="http://localhost:8000")
    await client.initialize()

    # Check what keys exist after signal registration
    # This would need a debug endpoint or direct Redis access

    # Submit a simple signal wait task
    workflow = {
        "tasks": [{
            "id": "wait_task",
            "protocol": "signal/v1",
            "method": "signal/wait",
            "params": {"signal": "test_signal", "timeout": 60}
        }]
    }

    result = await client.submit_workflow(workflow)
    workflow_id = result["workflow_id"]

    # Wait for task to register
    await asyncio.sleep(2)

    # Send the signal
    signal_workflow = {
        "tasks": [{
            "id": "send_signal",
            "protocol": "signal/v1",
            "method": "signal/send",
            "params": {
                "signal": "test_signal",
                "target_workflow": workflow_id,
                "payload": {"test": True}
            }
        }]
    }

    await client.submit_workflow(signal_workflow)

    # Check if task wakes up
    await asyncio.sleep(5)
    workflow_obj = await client.get_workflow(workflow_id)
    print(f"Final status: {workflow_obj.status}")

if __name__ == "__main__":
    asyncio.run(debug_signal_flow())
```

## Conclusion

The core issue is a mismatch between how keys are stored (with persistence layer adding prefix) and how they're retrieved (some operations bypass persistence layer). The fix requires:

1. Consistent use of `self.persistence.*` methods throughout the signal system
2. Implementation of missing persistence methods
3. Proper key pattern handling in both storage and retrieval

The signal system architecture is sound, but the implementation has inconsistencies in Redis access patterns that prevent proper signal delivery.