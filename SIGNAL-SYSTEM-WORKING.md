# Signal System Fix - WORKING

## Date: 2025-09-14

## Summary
The signal system is now FULLY operational! Signals are being sent, received, and processed correctly. The monitor successfully finds new signal streams, reads messages, and wakes waiting tasks when signals arrive.

## Key Fixes Applied

### 1. Fixed XREADGROUP Dict/List Handling
- **File**: `src/gleitzeit/persistence/unified_redis.py`
- **Issue**: XREADGROUP can return either a list or dict depending on Redis version
- **Fix**: Added conversion from list to dict format (line 2291-2292)
```python
# Convert list to dict if needed (Redis returns list format: [[stream_key, messages], ...])
if isinstance(result, list):
    result = dict(result)
```

### 2. Fixed Monitor Stream Iteration
- **File**: `src/gleitzeit/signals/monitor.py`
- **Issue**: Monitor expected to iterate over results as a list
- **Fix**: Changed to iterate over dict items (line ~190)
```python
# OLD (incorrect):
for stream_key, messages in results:

# NEW (correct):
for stream_key, messages in results.items():
```

### 3. Fixed Consumer Group Message Reading
- **File**: `src/gleitzeit/signals/monitor.py`
- **Issue**: Using '0-0' or '0' only reads pending messages for current consumer
- **Fix**: Use '>' to read new messages not yet delivered to any consumer
```python
# Use '>' to read new messages not yet delivered to any consumer
# in this consumer group
streams[key] = '>'
```

### 4. Added Logging to scan_iter
- **File**: `src/gleitzeit/persistence/unified_redis.py`
- **Issue**: Needed visibility into scan operations
- **Fix**: Changed debug to info logging for scan_iter operations

### 5. Fixed Timestamp Format in Signal Monitor
- **File**: `src/gleitzeit/signals/monitor.py`
- **Issue**: Monitor was using Unix timestamp instead of ISO format when marking tasks complete
- **Fix**: Changed from `str(time.time())` to `datetime.utcnow().isoformat()` (lines 378, 388)
```python
# OLD (caused "Invalid isoformat string" error):
"completed_at": str(time.time()),

# NEW (correct ISO format):
from datetime import datetime
"completed_at": datetime.utcnow().isoformat(),
```
This was the final fix that allowed workflows to complete properly after signal tasks were woken.

## Current State

### ✅ FULLY WORKING:
- Signal workflows can be submitted
- Signal wait tasks register successfully
- Signals are sent to target workflows
- Signal monitor finds and monitors signal streams
- Monitor reads messages from streams using XREADGROUP
- Monitor processes signals and wakes waiting tasks
- Task completion events are emitted
- Workflows correctly transition to "completed" status after signal tasks complete

## Test Results

Successfully processed signals with complete workflow:
```
Submitting wait workflow...
Response: {'success': True, 'workflow_id': 'workflow-f726e36dd85b402da57615cbf275e5c6'}
Wait workflow status: pending

Sending signal to workflow workflow-f726e36dd85b402da57615cbf275e5c6...
Signal workflow status: completed
Wait workflow final status: completed
✅ Signal workflow completed successfully!
```

The signal system now successfully:
1. Accepts signal wait task submissions
2. Monitors for incoming signals via Redis Streams
3. Processes signals and wakes waiting tasks
4. Properly marks tasks as completed with ISO format timestamps
5. Transitions workflows to completed status

## Architecture Notes

### Signal Flow:
1. **Wait Task Registration**: Signal wait task registers with handler
2. **Signal Stream Creation**: Creates `workflow:signals:{workflow_id}` stream
3. **Signal Sending**: Signal sent via XADD to stream
4. **Monitor Detection**: Monitor scans and finds signal streams
5. **Message Reading**: XREADGROUP reads new messages from stream
6. **Task Waking**: Monitor processes signal and marks task as completed
7. **Event Emission**: Task:completed event emitted

### Key Components:
- **SignalHandler**: Manages signal registration and sending
- **SignalMonitor**: Polls Redis streams for signals
- **UnifiedRedisAdapter**: Provides Redis operations with key prefixing
- **Consumer Groups**: Ensure exactly-once processing of signals

## Summary
The signal system is now fully operational. All issues have been resolved through a series of fixes to handle Redis version differences, consumer group behavior, and timestamp formatting. Workflows correctly complete when signal tasks are woken.