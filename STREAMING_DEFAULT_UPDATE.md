# Redis Streams Enabled by Default

## Change Summary

✅ **Redis Streams are now enabled by default** for better task reliability and prevention of stuck tasks.

## What Changed

### Before
- Default: Standard pub/sub transport (unreliable)
- Streams required: `GLEITZEIT_STREAM_MODE=enabled`
- Tasks could get stuck in PENDING state indefinitely

### After  
- Default: Redis Streams transport (reliable)
- To disable: `GLEITZEIT_STREAM_MODE=disabled`  
- Tasks have guaranteed delivery and automatic requeue

## Benefits

1. **No More Stuck Tasks** - Stream transport ensures events are delivered
2. **Better Reliability** - Messages persist across restarts
3. **Automatic Recovery** - Failed tasks can be replayed
4. **Zero Configuration** - Works out of the box

## Files Modified

- `src/gleitzeit/system/system_manager.py:1317` - Default to enabled
- `src/gleitzeit/core/execution_engine_v2.py:158` - Default logging

## Verification

Starting server without environment variables now shows:
```
INFO - Creating QueueManager with stream transport for reliability
INFO - Stream mode enabled - using transport layer for reliability
```

## Backward Compatibility

- ✅ **Fully backward compatible**
- ✅ **No breaking changes**
- ✅ **Can still disable with env var**

To disable streams (revert to pub/sub):
```bash
export GLEITZEIT_STREAM_MODE=disabled
gleitzeit serve --port 8000
```

## Impact

This change resolves the root cause of the stuck task issue identified in `STUCK_TASK_AUDIT.md` by ensuring reliable event delivery at the transport layer.