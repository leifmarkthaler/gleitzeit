# Stale Consumer Group Audit

**Date**: 2025-10-26
**Issue**: Messages getting stuck in PENDING state due to stale consumers
**Status**: ✅ FIXED

## Problem Summary

Workers that crash or restart leave their consumer registration in Redis Stream consumer groups. When these "zombie" consumers have claimed messages, those messages become stuck in PENDING state and are never processed by active workers.

## Root Cause Analysis

### How Redis Streams Consumer Groups Work

1. Workers join a consumer group by calling `XREADGROUP`
2. Redis tracks each consumer and which messages they've claimed
3. **Important**: Consumers persist in the group until explicitly removed with `XGROUP DELCONSUMER`
4. Redis does NOT automatically remove inactive consumers

### The Bug

In `BaseWorker._cleanup()` (line 712-726 before fix):

```python
async def _cleanup(self):
    """Cleanup worker resources"""
    # Cancel any active tasks
    for task in self._tasks.values():
        task.cancel()

    # Unregister worker from cluster
    key = f"{{shard:0}}:worker:registry:{self.config.worker_type}:{self.config.worker_id}"
    await self.redis.delete(key.encode())

    # Close Redis Cluster connections
    if self.redis:
        await self.redis.close()

    self.logger.info(f"Worker {self.config.worker_id} cleaned up")
```

**Missing**: No call to `XGROUP DELCONSUMER` to remove the worker from consumer groups

### Impact Timeline

1. Worker `task_execution-1` starts and joins `task_execution-group`
2. Worker claims message `1761487406349-0` (timer task)
3. Worker crashes or is killed (`gleitzeit stop --force`)
4. Consumer `task_execution-1` remains in group with 1 pending message
5. New worker `task_execution-async` starts
6. Message is stuck - `task_execution-async` sees it's already claimed by `task_execution-1`
7. Workflow fails because timer task never completes

### Evidence

```bash
$ redis-cli XINFO CONSUMERS "{shard:1}:task:ready" "task_execution-group"

name
task_execution-1      # Dead consumer
pending
1                     # 1 stuck message
idle
145510                # Inactive for 145 seconds (over 2 minutes)
inactive
145510

name
task_execution-async  # Active consumer
pending
0                     # Can't claim the stuck message
idle
4504
inactive
84656
```

## The Fix

Added consumer cleanup to `BaseWorker._cleanup()`:

```python
# Remove this consumer from all consumer groups it joined
# This prevents messages from getting stuck in PENDING state when worker dies
if self.redis and self._consumer_groups_created:
    for stream_key in self._consumer_groups_created:
        try:
            # Get consumer group name (derived from stream name)
            stream_str = stream_key.decode() if isinstance(stream_key, bytes) else stream_key
            # Extract stream type from key (e.g., "{shard:0}:task:ready" -> "task")
            parts = stream_str.split(':')
            if len(parts) >= 3:
                stream_type = parts[1]  # e.g., "task", "workflow", "signal"
                consumer_group = f"{stream_type}-group"

                # Delete this consumer from the group
                # XGROUP DELCONSUMER returns number of pending messages that were reassigned
                pending_count = await self.redis.xgroup_delconsumer(
                    stream_key,
                    consumer_group.encode(),
                    self.config.consumer_name.encode()
                )
                if pending_count > 0:
                    self.logger.warning(
                        f"Removed consumer {self.config.consumer_name} from {stream_str} "
                        f"with {pending_count} pending messages"
                    )
                else:
                    self.logger.info(
                        f"Removed consumer {self.config.consumer_name} from {stream_str}"
                    )
        except Exception as e:
            # Don't fail cleanup if consumer deletion fails
            self.logger.warning(f"Failed to remove consumer from {stream_key}: {e}")
```

### What This Does

1. **Iterates** through `self._consumer_groups_created` (set of streams the worker joined)
2. **Extracts** consumer group name from stream key
3. **Calls** `XGROUP DELCONSUMER` to remove the consumer
4. **Logs** how many pending messages were reassigned (important for debugging)
5. **Handles errors** gracefully so cleanup doesn't fail

## Benefits

✅ **Automatic cleanup**: Workers remove themselves on graceful shutdown
✅ **Pending message recovery**: Messages are automatically reassigned to other consumers
✅ **Logging visibility**: We see how many messages were stuck when workers die
✅ **Error resilience**: Cleanup continues even if some deletions fail

## Related Issues

This fix also addresses:
- **Timer task failures**: Timer tasks stuck in PENDING caused workflows to fail
- **python_specialist conflicts**: When specialized workers couldn't process certain task types, messages got stuck
- **Restart problems**: Every restart left zombie consumers accumulating in groups

## Testing

After fix:
1. Start workers
2. Submit workflow
3. Kill workers with `gleitzeit stop --force`
4. Check consumer groups - should be empty
5. Restart workers
6. No stale consumers, messages process normally

## Remaining Considerations

### Force Kill Protection

The fix handles **graceful shutdown** (`SIGTERM`, `gleitzeit stop`). For **force kill** scenarios (`SIGKILL`, `kill -9`), we also need:

1. **Pending recovery task**: Already exists in BaseWorker - claims old pending messages
2. **Consumer TTL monitoring**: Could add background cleanup of inactive consumers
3. **FLUSHDB on dev restart**: For development, always start clean

### python_specialist Worker

We **disabled** the python_specialist worker (commented out in gleitzeit.yaml) because:
- It only handled `[python, script]` types
- When it received timer/signal/other tasks, it failed them permanently
- General `task_execution` workers handle all task types better
- Specialized workers need proper message filtering (NACK instead of FAIL)

## Files Modified

- `src/gleitzeit/workers/base.py` - Added consumer cleanup to `_cleanup()` method
- `gleitzeit.yaml` - Disabled python_specialist worker

## Conclusion

**Stale consumer groups** were causing message processing failures across the system. The fix ensures workers clean up after themselves, preventing messages from getting stuck and workflows from failing.

This is a **critical fix** for production reliability - without it, any worker restart leaves orphaned messages.
