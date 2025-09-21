# Signal Stream Initialization Issue

## Overview
The signal workflow system fails to process signals due to missing Redis stream initialization. Signal tasks remain in a waiting state indefinitely because the signal streams are never created, preventing the StreamSignalManager from processing signals.

## Problem Description

### Symptoms
- Signal workflows remain in "pending" status indefinitely
- Signal tasks (protocol: `signal/v1`, method: `signal/wait`) never complete
- Workflows waiting for signals cannot progress
- Test output shows workflow stuck at 0/N tasks completed

### Root Cause
The signal system attempts to read from Redis streams that don't exist:
- `signals:immediate`
- `signals:retry`
- `signals:pending`
- `signals:handlers`

These streams are never created, causing continuous errors in the StreamSignalManager.

## Error Messages

### Server Log Errors (Repeated Continuously)
```
gleitzeit.signals.stream_signal_manager - ERROR - Error reading from signal stream signals:immediate:
  NOGROUP No such key 'signals:immediate' or consumer group 'gleitzeit-api-processors-signals'
  in XREADGROUP with GROUP option

gleitzeit.signals.stream_signal_manager - ERROR - Error reading from signal stream signals:retry:
  NOGROUP No such key 'signals:retry' or consumer group 'gleitzeit-api-processors-signals'
  in XREADGROUP with GROUP option
```

### Consumer Group Creation Failures
```
gleitzeit.scheduler.consumer_group_manager - ERROR - Error ensuring consumer group
  gleitzeit-api-processors-signals for signals:pending: no such key

gleitzeit.scheduler.consumer_group_manager - ERROR - Error ensuring consumer group
  gleitzeit-api-processors-signals for signals:immediate: no such key

gleitzeit.scheduler.consumer_group_manager - ERROR - Error ensuring consumer group
  gleitzeit-api-processors-signals for signals:retry: no such key

gleitzeit.scheduler.consumer_group_manager - ERROR - Error ensuring consumer group
  gleitzeit-api-processors-signals for signals:handlers: no such key
```

## Impact

### Workflow Execution
- Workflows with signal tasks cannot complete
- Signal-based approval workflows fail
- Inter-workflow communication via signals is broken
- Pause/resume functionality doesn't work

### System Performance
- Continuous error logging fills disk space
- StreamSignalManager repeatedly attempts to read non-existent streams
- CPU cycles wasted on failed read attempts
- Error noise makes debugging other issues difficult

## Test Results

### test_easy_signal_workflow.py Output
```
=== Creating Signal-Based Workflow ===
✅ Workflow validated successfully
Submitting workflow...
✅ Workflow submitted: workflow-610d456064d24ae4bb963ad567b30368

⏳ Workflow should be waiting for signal...
Current status: pending

📨 Sending signal: approval_signal
✅ Signal sent via workflow: workflow-2c2de22c89794237b5639e1444f1fa9b
Signal workflow status: pending

📊 Monitoring workflow: workflow-610d456064d24ae4bb963ad567b30368
  [1/30] Status: pending
  [2/30] Status: pending
  ...
  [30/30] Status: pending

=== Final Result ===
Status: pending
❌ Signal workflow did not complete as expected
```

## Architecture Analysis

### Expected Signal Flow
1. Task with `signal/v1` protocol submitted
2. SignalProvider creates wait handler
3. Task status set to WAITING
4. Signal sent via API or workflow
5. StreamSignalManager processes signal
6. Waiting task resumes with signal data
7. Workflow continues execution

### Actual Behavior
1. Task with `signal/v1` protocol submitted ✅
2. SignalProvider attempts to register handler ✅
3. Task status set to WAITING ✅
4. Signal sent via API ✅
5. **StreamSignalManager fails to read from non-existent streams** ❌
6. Signal never processed ❌
7. Task remains in WAITING state forever ❌

## Related Components

### StreamSignalManager
**File**: `src/gleitzeit/signals/stream_signal_manager.py`
- Attempts to read from signal streams
- Fails because streams don't exist
- No automatic stream creation logic

### SignalProvider
**File**: `src/gleitzeit/providers/signal_provider.py`
- Correctly handles signal/wait requests
- Returns TaskResult with WAITING status
- But signals never get delivered due to stream issues

### ConsumerGroupManager
**File**: `src/gleitzeit/scheduler/consumer_group_manager.py`
- Tries to create consumer groups for signal streams
- Fails because underlying streams don't exist
- No stream creation before group creation

## Required Fix

### Stream Initialization
The signal streams need to be created during system initialization:

```python
# Required during SystemManager or StreamSignalManager initialization
async def initialize_signal_streams(redis_client):
    """Create signal streams if they don't exist."""
    signal_streams = [
        'signals:immediate',
        'signals:retry',
        'signals:pending',
        'signals:handlers'
    ]

    for stream_key in signal_streams:
        # Create stream with dummy entry if it doesn't exist
        await redis_client.xadd(
            stream_key,
            {'init': 'true'},
            id='0-1',  # Special ID that gets ignored
            maxlen=1  # Keep only this init entry
        )

        # Create consumer group
        try:
            await redis_client.xgroup_create(
                stream_key,
                'gleitzeit-api-processors-signals',
                id='0'
            )
        except ResponseError as e:
            if 'BUSYGROUP' not in str(e):
                raise
```

### Alternative: Lazy Stream Creation
Modify StreamSignalManager to create streams on first use:

```python
async def _ensure_stream_exists(self, stream_key: str):
    """Ensure a stream exists before reading from it."""
    try:
        # Try to get stream info
        await self.redis_client.xinfo_stream(stream_key)
    except ResponseError:
        # Stream doesn't exist, create it
        await self.redis_client.xadd(
            stream_key,
            {'created': str(datetime.utcnow())},
            maxlen=1
        )
        # Create consumer group
        await self.redis_client.xgroup_create(
            stream_key,
            self.consumer_group,
            id='0'
        )
```

## Workaround (Temporary)

Until the fix is implemented, manually create the streams before running signal workflows:

```bash
# Create signal streams manually
redis-cli XADD signals:immediate MAXLEN 1 '*' init true
redis-cli XADD signals:retry MAXLEN 1 '*' init true
redis-cli XADD signals:pending MAXLEN 1 '*' init true
redis-cli XADD signals:handlers MAXLEN 1 '*' init true

# Create consumer groups
redis-cli XGROUP CREATE signals:immediate gleitzeit-api-processors-signals 0
redis-cli XGROUP CREATE signals:retry gleitzeit-api-processors-signals 0
redis-cli XGROUP CREATE signals:pending gleitzeit-api-processors-signals 0
redis-cli XGROUP CREATE signals:handlers gleitzeit-api-processors-signals 0
```

## Related Issues

### Timer Streams
Similar issues may exist with timer streams:
- `timers:scheduled`
- `timers:immediate`
- `timers:retry`

### Event Streams
Main event streams are created properly, but specialized streams might have similar issues.

## Testing After Fix

### Verification Steps
1. Clear Redis: `redis-cli FLUSHALL`
2. Start fresh server
3. Run `test_easy_signal_workflow.py`
4. Verify no stream errors in logs
5. Confirm workflow completes after signal

### Expected Results
- No "NOGROUP" errors in logs
- Signal workflows complete successfully
- `redis-cli KEYS 'signals:*'` shows all signal streams
- Consumer groups exist for each stream

## Priority
**HIGH** - Signal functionality is completely broken without stream initialization.

## Affected Versions
- Current version: 0.0.6
- Likely affects all versions with StreamSignalManager implementation

## Summary
The signal system architecture is sound, but fails due to a simple initialization oversight. Signal streams must be created before the StreamSignalManager attempts to read from them. This is a critical but easily fixable issue that completely breaks signal-based workflow functionality.