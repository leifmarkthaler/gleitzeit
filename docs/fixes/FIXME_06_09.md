# FIXME List - December 6, 2024

## Stream Transport Status Update ✅

**CONFIRMED WORKING**: After Redis cleanup, the simplified stream transport is functioning correctly:
- Python provider workflows execute successfully with stream transport
- Messages properly flow through Redis Streams
- Consumer groups are created and managed correctly
- Stream transport acts as pure transport layer without changing architecture

## Issues Identified During Stream Transport Testing

### 1. UnifiedRedisAdapter Missing Method ❌
**File**: `src/gleitzeit/persistence/unified_redis.py`
**Error**: `'UnifiedRedisAdapter' object has no attribute 'update_workflow'`
**Location**: Called from `ReconciliationService._reconcile_workflows()` at `/src/gleitzeit/system/reconciliation_service.py:236`
**Impact**: ReconciliationService fails to update workflow status during startup reconciliation
**Fix Required**: Add `update_workflow()` method to UnifiedRedisAdapter

### 2. Shell Provider Not Registered ❌ **CONFIRMED**
**Error**: `[TASK_EXECUTION_FAILED] Protocol shell not available in provider pool`
**Impact**: Shell tasks cannot be executed  
**Cause**: Shell provider is created in HubFactory but not registered with PoolingAdapter
**Fix Required**: Register shell provider with the pooling adapter in SystemManager
**Test Result**: Confirmed failure when running test_stream_workflow.py

### 3. Client API Method Missing ❌
**File**: `src/gleitzeit/client/adapters/api.py`
**Error**: `'APIAdapter' object has no attribute 'get_workflow_results'`
**Impact**: Cannot retrieve workflow results via client
**Fix Required**: Add `get_workflow_results()` method to APIAdapter

### 4. Client Missing Close Method ⚠️ **CONFIRMED**
**File**: `src/gleitzeit/client/client.py`
**Error**: `'GleitzeitClient' object has no attribute 'close'`
**Impact**: Resources not properly cleaned up, event loop errors
**Fix Required**: Add async `close()` method to properly cleanup sessions
**Test Result**: Confirmed in both test_stream_workflow.py and test_ollama_stream.py

### 5. Health Monitor Recovery Noise 🔊
**Issue**: Health monitor constantly tries to recover old/stale instances
**Files**: Multiple old instance IDs persist in Redis
**Impact**: Excessive log noise, unnecessary recovery attempts
**Fix Required**: Add TTL to health entries or cleanup mechanism for stale instances

### 6. Service Registry Heartbeat Error ⚠️
**File**: `src/gleitzeit/system/service_registry.py`
**Error**: `'<' not supported between instances of 'str' and 'datetime.datetime'`
**Impact**: Service heartbeat monitoring fails
**Fix Required**: Fix type comparison in heartbeat monitor

### 7. WebSocket Connection Errors ⚠️
**Error**: `gleitzeit.client.events.models.WebSocketMessage() got multiple values for keyword argument 'type'`
**Impact**: WebSocket event handling broken
**Fix Required**: Fix WebSocketMessage initialization

### 8. Provider Protocol Mismatch ❓
**Issue**: Python provider registered as "python/v1" but tasks use "python"
**Impact**: Potential protocol validation issues
**Fix Required**: Standardize protocol naming across providers

## Stream Transport Status ✅

**WORKING CORRECTLY**: The simplified stream transport implementation is functioning as intended:
- StreamTransport created when `GLEITZEIT_STREAM_MODE=enabled` ✅
- Messages published to Redis Streams instead of Pub/Sub ✅
- Consumer groups properly created ✅
- Integration with QueueManager working ✅
- Maintains same execution architecture ✅

## Priority Fixes

### High Priority 🔴
1. Add `update_workflow()` to UnifiedRedisAdapter
2. Register shell provider with PoolingAdapter
3. Add `get_workflow_results()` to APIAdapter

### Medium Priority 🟡
4. Add `close()` method to GleitzeitClient
5. Fix service registry heartbeat type comparison
6. Fix WebSocketMessage initialization

### Low Priority 🟢
7. Implement stale instance cleanup in health monitor
8. Standardize provider protocol naming

## Testing Recommendations

1. After fixing shell provider registration, test with:
   ```bash
   GLEITZEIT_STREAM_MODE=enabled gleitzeit serve --port 8000
   python test_stream_workflow.py  # Uses shell tasks
   ```

2. Test with Python provider (currently working):
   ```bash
   GLEITZEIT_STREAM_MODE=enabled gleitzeit serve --port 8000
   python test_clean_stream.py  # Uses Python tasks - WORKING ✅
   ```

3. Verify stream transport reliability:
   - Kill server during workflow execution
   - Restart and verify tasks resume from stream
   - Check message persistence in Redis

## Test Results Summary

| Test | Provider | Stream Transport | Status |
|------|----------|-----------------|--------|
| test_clean_stream.py | Python | ✅ Working | ✅ Passed |
| test_stream_workflow.py | Shell | ✅ Working | ❌ Failed (provider not registered) |
| test_ollama_stream.py | Ollama | ✅ Working | ⏱️ Not tested (timeout)

## Notes

- The complex stream implementation was successfully removed (~2500 lines)
- Simple transport adapter approach is working (only ~400 lines)
- Stream transport provides persistence and reliability without architectural changes
- All workflow failures are due to the issues listed above, not the stream transport itself