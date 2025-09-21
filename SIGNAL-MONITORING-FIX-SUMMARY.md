# Signal Monitoring Fix Summary

## Overview
Fixed duplicate TASK_COMPLETED event processing in the Gleitzeit signal workflow system that was causing multiple signal registrations and task enqueueing.

## Root Cause
The TaskOrchestrator had a duplicate event tracking mechanism (`_processed_events`) but wasn't using it in the `_handle_task_completed` method, leading to the same task completion event being processed multiple times.

## Files Modified

### 1. src/gleitzeit/signals/monitor.py
**Purpose**: Updated to use SystemManager persistence layer instead of direct Redis access.

**Key Changes**:
- Changed constructor to accept `persistence` parameter instead of `redis_client`
- Added `self.redis = getattr(persistence, 'redis', persistence)` to access underlying Redis client
- Fixed `_process_signal_streams` method to use `self.redis.scan_iter`

**Before**:
```python
def __init__(self, redis_client, check_interval: float = 0.1, instance_id: Optional[str] = None, event_bus=None):
    self.redis = redis_client
```

**After**:
```python
def __init__(self, persistence, check_interval: float = 0.1, instance_id: Optional[str] = None, event_bus=None):
    self.persistence = persistence
    self.redis = getattr(persistence, 'redis', persistence)
```

### 2. src/gleitzeit/signals/signal_manager.py
**Purpose**: Updated SignalMonitorService initialization to pass persistence layer.

**Key Changes**:
- Changed SignalMonitorService initialization to pass `persistence` instead of `redis_client`

**Before**:
```python
self.signal_monitor = SignalMonitorService(
    redis_client=self.persistence.redis,
    # ...
)
```

**After**:
```python
self.signal_monitor = SignalMonitorService(
    persistence=self.persistence,
    # ...
)
```

### 3. src/gleitzeit/core/task_orchestrator.py
**Purpose**: Added duplicate event detection to prevent multiple processing of the same TASK_COMPLETED event.

**Key Changes**:
- Implemented proper event deduplication in `_handle_task_completed` method
- Uses task_id and timestamp to create unique event identifiers
- Leverages existing `_processed_events` mechanism

**Added Code**:
```python
async def _handle_task_completed(self, event: GleitzeitEvent):
    """Handle task completion event."""
    task_id = event.data.get("task_id")
    
    # Create event identifier for duplicate detection
    event_id = f"task_completed:{task_id}"
    if hasattr(event, 'timestamp'):
        event_id += f":{event.timestamp}"
    elif 'timestamp' in event.data:
        event_id += f":{event.data['timestamp']}"
    
    # Check if we've already processed this event
    if event_id in self._processed_events[EventType.TASK_COMPLETED]:
        logger.debug(f"Ignoring duplicate TASK_COMPLETED event for task {task_id}")
        return
        
    # Mark event as processed
    self._processed_events[EventType.TASK_COMPLETED].add(event_id)
    
    # Get workflow_id from persistence
    if self.persistence and task_id:
        task = await self.persistence.get_task(task_id)
        if task and task.workflow_id:
            # Check for workflow progression
            await self._check_workflow_progression(task.workflow_id)
```

## Architecture Improvements

### SystemManager Integration
- SignalMonitorService now properly integrates with SystemManager's persistence layer
- Maintains backward compatibility by accessing underlying Redis client when needed
- Follows the established pattern of using persistence abstraction while allowing low-level Redis operations

### Event Deduplication
- Implemented robust duplicate event detection using unique event identifiers
- Combines task_id with timestamp for reliable event identification
- Leverages existing `_processed_events` tracking mechanism in TaskOrchestrator

## Impact
- Eliminates duplicate TASK_COMPLETED event processing
- Prevents multiple signal registrations for the same task
- Ensures signal workflows progress correctly without duplicate task enqueueing
- Maintains proper SystemManager architectural patterns

## Testing
Fixed issues are verified through the `test_signal_simple.yaml` workflow which tests:
1. Signal workflow initialization
2. Task completion event handling
3. Signal waiting and progression
4. Proper task status transitions

## Configuration
No configuration changes required. The fixes maintain existing behavior while eliminating duplicate processing.