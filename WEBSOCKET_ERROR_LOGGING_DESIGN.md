# WebSocket Error and Logging Broadcasting Design

## Overview

This document extends the WebSocket implementation to include comprehensive error and logging event broadcasting. Currently, the WebSocket system broadcasts workflow/task state changes but does not broadcast validation errors, execution errors, warnings, or critical logging events.

## Current State Analysis

### What Currently Broadcasts

The existing WebSocket implementation broadcasts events through EventStore:

```python
# src/gleitzeit/core/event_store.py:138-154
await self.redis.publish(
    'gleitzeit:events',
    json.dumps({
        'type': 'workflow_event',
        'workflow_id': workflow_id,
        'task_id': task_id,
        'event_type': event_type.value,
        'timestamp': event.timestamp,
        'level': level.value,
        'data': data or {}
    })
)
```

**Events Currently Broadcast:**
- workflow:started
- workflow:completed
- workflow:failed
- task:ready
- task:started
- task:completed
- task:failed
- task:cancelled
- (All EventType events that go through EventStore)

### What Does NOT Broadcast

**Validation Errors:**
- Workflow validation failures (workflow_loader_worker_v2.py:301-346)
- Task validation failures (task_execution_worker.py:253-277)
- Configuration validation errors

**Execution Errors:**
- Handler initialization failures (task_execution_worker.py:147)
- Task execution exceptions (task_execution_worker.py:362)
- Protocol mismatch errors (task_execution_worker.py:253)

**Warning Events:**
- Unknown task types (workflow_loader_worker_v2.py:499)
- Handler async initialization failures (task_execution_worker.py:147)
- Redis logging failures (task_execution_worker.py:676)
- Unknown result statuses (task_execution_worker.py:418)

**Critical Errors:**
- Worker failures
- System errors
- Redis connection issues

## Design Goals

1. **Comprehensive Error Visibility**: All errors should be broadcast to WebSocket clients
2. **Selective Logging**: Only ERROR, WARNING, and CRITICAL logs should broadcast (not INFO/DEBUG)
3. **Consistent Format**: Use standardized message format across all error/log broadcasts
4. **Performance**: Minimize overhead, don't broadcast every log line
5. **Backwards Compatibility**: Don't break existing WebSocket event flow

## Architecture

### Message Types

Extend the WebSocket message format to include new message types:

```json
{
  "type": "workflow_event",      // Existing - state change events
  "type": "error_event",          // NEW - error events
  "type": "log_event",            // NEW - logging events
  "type": "validation_error",     // NEW - validation-specific errors
  "type": "system_event"          // NEW - system-level events
}
```

### Event Broadcasting Helper

Create a centralized helper to standardize error/log broadcasting:

```python
# src/gleitzeit/core/websocket_publisher.py

import json
import logging
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

class WebSocketPublisher:
    """Helper for publishing events to WebSocket via Redis Pub/Sub"""

    def __init__(self, redis_client):
        self.redis = redis_client
        self.channel = 'gleitzeit:events'

    async def publish_error(
        self,
        error_type: str,
        error_message: str,
        workflow_id: Optional[str] = None,
        task_id: Optional[str] = None,
        error_data: Optional[Dict[str, Any]] = None,
        severity: str = "error"
    ):
        """Publish error event to WebSocket"""
        try:
            await self.redis.publish(
                self.channel,
                json.dumps({
                    'type': 'error_event',
                    'error_type': error_type,
                    'message': error_message,
                    'workflow_id': workflow_id,
                    'task_id': task_id,
                    'severity': severity,
                    'timestamp': datetime.utcnow().isoformat(),
                    'data': error_data or {}
                })
            )
        except Exception as e:
            logger.error(f"Failed to publish error to WebSocket: {e}")

    async def publish_validation_error(
        self,
        validation_type: str,
        errors: list,
        workflow_id: Optional[str] = None,
        task_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        """Publish validation error to WebSocket"""
        try:
            await self.redis.publish(
                self.channel,
                json.dumps({
                    'type': 'validation_error',
                    'validation_type': validation_type,
                    'errors': errors,
                    'workflow_id': workflow_id,
                    'task_id': task_id,
                    'timestamp': datetime.utcnow().isoformat(),
                    'context': context or {}
                })
            )
        except Exception as e:
            logger.error(f"Failed to publish validation error to WebSocket: {e}")

    async def publish_log(
        self,
        level: str,
        message: str,
        logger_name: str,
        workflow_id: Optional[str] = None,
        task_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None
    ):
        """Publish log event to WebSocket (WARNING, ERROR, CRITICAL only)"""
        if level.lower() not in ['warning', 'error', 'critical']:
            return

        try:
            await self.redis.publish(
                self.channel,
                json.dumps({
                    'type': 'log_event',
                    'level': level,
                    'message': message,
                    'logger': logger_name,
                    'workflow_id': workflow_id,
                    'task_id': task_id,
                    'timestamp': datetime.utcnow().isoformat(),
                    'extra': extra or {}
                })
            )
        except Exception as e:
            logger.error(f"Failed to publish log to WebSocket: {e}")

    async def publish_system_event(
        self,
        event_type: str,
        message: str,
        severity: str = "info",
        data: Optional[Dict[str, Any]] = None
    ):
        """Publish system-level event to WebSocket"""
        try:
            await self.redis.publish(
                self.channel,
                json.dumps({
                    'type': 'system_event',
                    'event_type': event_type,
                    'message': message,
                    'severity': severity,
                    'timestamp': datetime.utcnow().isoformat(),
                    'data': data or {}
                })
            )
        except Exception as e:
            logger.error(f"Failed to publish system event to WebSocket: {e}")
```

## Implementation Plan

### Phase 1: Core Infrastructure

**1. Create WebSocketPublisher Helper**
- Location: `src/gleitzeit/core/websocket_publisher.py`
- Provides centralized publishing methods
- Handles errors gracefully (no failures due to WebSocket issues)

**2. Integrate into BaseWorker**
- Add WebSocketPublisher instance to BaseWorker
- Make available to all workers via `self.ws_publisher`

```python
# src/gleitzeit/workers/base.py

from ..core.websocket_publisher import WebSocketPublisher

class BaseWorker:
    def __init__(self, config: WorkerConfig):
        # ... existing code ...
        self.ws_publisher = WebSocketPublisher(self.redis)
```

### Phase 2: Workflow Validation Errors

**Target: workflow_loader_worker_v2.py**

Add WebSocket broadcasting for validation failures:

```python
# Line 301 - Validation/configuration/resource limit errors
except (WorkflowValidationError, ConfigurationError, ResourceLimitError) as e:
    logger.error(f"Workflow validation/configuration/resource limit failed: {e}")

    # NEW: Broadcast validation error via WebSocket
    await self.ws_publisher.publish_validation_error(
        validation_type='workflow_validation',
        errors=[str(e)],
        workflow_id=workflow_id,
        context={
            'workflow_path': workflow_path,
            'error_type': e.__class__.__name__
        }
    )

    # ... existing error handling ...
```

**Location:** After line 301

### Phase 3: Task Execution Errors

**Target: task_execution_worker.py**

**3.1 Handler Protocol Mismatch (Line 253)**
```python
# No handler for protocol
await self.ws_publisher.publish_error(
    error_type='handler_not_found',
    error_message=f"No handler for protocol '{task.protocol}'",
    workflow_id=workflow_id,
    task_id=task_id,
    error_data={
        'protocol': task.protocol,
        'available_handlers': list(self.handlers.keys())
    },
    severity='error'
)
```

**3.2 Task Execution Failure (Line 362)**
```python
except Exception as e:
    logger.error(f"Task execution failed for {task_id}: {e}", exc_info=True)

    # NEW: Broadcast execution error
    await self.ws_publisher.publish_error(
        error_type='task_execution_failed',
        error_message=str(e),
        workflow_id=workflow_id,
        task_id=task_id,
        error_data={
            'exception_type': e.__class__.__name__,
            'traceback': traceback.format_exc()
        },
        severity='error'
    )

    await self.handle_task_failure(task_id, workflow_id, str(e))
    return False
```

**3.3 Handler Initialization Warning (Line 147)**
```python
except Exception as e:
    logger.warning(f"Failed to async initialize handler {protocol}: {e}")

    # NEW: Broadcast warning
    await self.ws_publisher.publish_log(
        level='warning',
        message=f"Failed to async initialize handler {protocol}: {e}",
        logger_name=__name__,
        extra={'protocol': protocol}
    )
```

### Phase 4: Warning Events

**Target: workflow_loader_worker_v2.py - Line 499**
```python
logger.warning(f"Unknown task type '{task_type}' in task '{task_id}', using placeholder protocol '{protocol}'")

# NEW: Broadcast warning
await self.ws_publisher.publish_log(
    level='warning',
    message=f"Unknown task type '{task_type}', using placeholder protocol",
    logger_name=__name__,
    workflow_id=workflow_id,
    task_id=task_id,
    extra={'task_type': task_type, 'protocol': protocol}
)
```

**Target: task_execution_worker.py - Line 418**
```python
logger.warning(f"Unknown result status: {result.status} for task {task_id}")

# NEW: Broadcast warning
await self.ws_publisher.publish_log(
    level='warning',
    message=f"Unknown result status: {result.status}",
    logger_name=__name__,
    workflow_id=workflow_id,
    task_id=task_id,
    extra={'result_status': result.status}
)
```

### Phase 5: UI Updates

**Update UI to handle new message types:**

```javascript
// src/gleitzeit/ui2/templates/workflows.html

ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    console.log('WebSocket message:', message);

    if (message.type === 'workflow_event') {
        // Existing - reload workflows on state change
        loadWorkflows();
    }
    else if (message.type === 'error_event') {
        // NEW - Show error notification
        showErrorNotification(message);
    }
    else if (message.type === 'validation_error') {
        // NEW - Show validation error details
        showValidationError(message);
    }
    else if (message.type === 'log_event') {
        // NEW - Show log event (warning/error/critical)
        showLogEvent(message);
    }
    else if (message.type === 'system_event') {
        // NEW - Show system event
        showSystemEvent(message);
    }
    else if (message.type === 'connected') {
        console.log('WebSocket connection confirmed:', message.message);
    }
};

function showErrorNotification(error) {
    // Display error notification banner
    const banner = document.createElement('div');
    banner.className = 'error-banner';
    banner.innerHTML = `
        <strong>Error:</strong> ${error.message}
        ${error.workflow_id ? `<br>Workflow: ${error.workflow_id}` : ''}
        ${error.task_id ? `<br>Task: ${error.task_id}` : ''}
    `;
    document.body.prepend(banner);

    // Auto-dismiss after 10 seconds
    setTimeout(() => banner.remove(), 10000);
}

function showValidationError(error) {
    // Display validation error with details
    const banner = document.createElement('div');
    banner.className = 'validation-error-banner';
    banner.innerHTML = `
        <strong>Validation Failed:</strong> ${error.validation_type}
        <ul>${error.errors.map(e => `<li>${e}</li>`).join('')}</ul>
        ${error.workflow_id ? `<br>Workflow: ${error.workflow_id}` : ''}
    `;
    document.body.prepend(banner);

    setTimeout(() => banner.remove(), 15000);
}

function showLogEvent(log) {
    // Display log event
    if (log.level === 'critical' || log.level === 'error') {
        console.error(`[${log.logger}] ${log.message}`, log.extra);
    } else if (log.level === 'warning') {
        console.warn(`[${log.logger}] ${log.message}`, log.extra);
    }

    // Optionally show in UI for errors/critical
    if (log.level === 'error' || log.level === 'critical') {
        showErrorNotification({
            message: log.message,
            workflow_id: log.workflow_id,
            task_id: log.task_id
        });
    }
}

function showSystemEvent(event) {
    // Display system event
    console.log(`[SYSTEM] ${event.event_type}: ${event.message}`, event.data);
}
```

**Add CSS for error banners:**

```css
.error-banner {
    background-color: #f8d7da;
    color: #721c24;
    padding: 12px 20px;
    border: 1px solid #f5c6cb;
    border-radius: 4px;
    margin: 10px;
    position: relative;
    animation: slideDown 0.3s ease-out;
}

.validation-error-banner {
    background-color: #fff3cd;
    color: #856404;
    padding: 12px 20px;
    border: 1px solid #ffeeba;
    border-radius: 4px;
    margin: 10px;
    position: relative;
    animation: slideDown 0.3s ease-out;
}

@keyframes slideDown {
    from {
        transform: translateY(-100%);
        opacity: 0;
    }
    to {
        transform: translateY(0);
        opacity: 1;
    }
}
```

## Error Types to Broadcast

### High Priority (Must Broadcast)
1. **Workflow validation errors** - User needs immediate feedback
2. **Task execution errors** - Critical for debugging
3. **Handler not found errors** - Configuration issue
4. **Validation failures** - User action required

### Medium Priority (Should Broadcast)
1. **Unknown task types** - Warning about configuration
2. **Handler initialization failures** - May impact execution
3. **Unknown result statuses** - Unexpected state

### Low Priority (Optional Broadcast)
1. **Redis logging failures** - Internal issue
2. **Worker heartbeat failures** - Internal monitoring

## Filtering and Subscription

Extend the WebSocket subscription model to allow filtering by message type:

```json
{
  "action": "subscribe",
  "workflow_ids": ["workflow-123"],
  "message_types": ["workflow_event", "error_event", "validation_error"],
  "severity_filter": ["error", "critical"]
}
```

Update EventBroadcaster to support message type filtering:

```python
# src/gleitzeit/api/services/event_broadcaster.py

async def broadcast_event(self, event: dict):
    """Broadcast event to subscribed WebSocket clients"""
    if not self.active_connections:
        return

    disconnected = set()
    for websocket in self.active_connections:
        try:
            # Check filters
            filters = self.subscription_filters.get(websocket, {})

            # Filter by workflow/task ID
            if filters.get('ids'):
                workflow_id = event.get('workflow_id')
                task_id = event.get('task_id')
                if not (workflow_id in filters['ids'] or task_id in filters['ids']):
                    continue

            # NEW: Filter by message type
            if filters.get('message_types'):
                if event.get('type') not in filters['message_types']:
                    continue

            # NEW: Filter by severity
            if filters.get('severity_filter'):
                severity = event.get('severity') or event.get('level')
                if severity and severity not in filters['severity_filter']:
                    continue

            await websocket.send_json(event)
        except Exception as e:
            logger.error(f"Error broadcasting to WebSocket: {e}")
            disconnected.add(websocket)

    # Clean up disconnected clients
    for ws in disconnected:
        await self.remove_client(ws)
```

## Performance Considerations

1. **Non-blocking**: All WebSocket publishing must be non-blocking and should not slow down worker processing
2. **Error Handling**: WebSocket publish failures should be logged but not propagate errors
3. **Rate Limiting**: Consider rate limiting for high-frequency errors to prevent flooding
4. **Batching**: For high-volume scenarios, consider batching multiple events

## Testing Strategy

### Unit Tests
- Test WebSocketPublisher methods
- Test error message formatting
- Test filtering logic

### Integration Tests
1. **Validation Error Broadcasting**
   - Submit invalid workflow
   - Verify validation error received via WebSocket

2. **Task Execution Error Broadcasting**
   - Submit workflow with failing task
   - Verify error event received via WebSocket

3. **Warning Event Broadcasting**
   - Submit workflow with unknown task type
   - Verify warning event received via WebSocket

4. **Filtering Tests**
   - Subscribe with message type filters
   - Verify only matching messages received

### Manual Testing
- Monitor UI with browser console open
- Submit various workflows (valid, invalid, failing)
- Verify error notifications appear
- Verify console shows all error/warning events

## Migration Path

1. **Phase 1**: Deploy WebSocketPublisher without broadcasting (infrastructure only)
2. **Phase 2**: Enable validation error broadcasting (high priority)
3. **Phase 3**: Enable task execution error broadcasting (high priority)
4. **Phase 4**: Enable warning broadcasting (medium priority)
5. **Phase 5**: Update UI to display errors (user-facing)

## Configuration

Add configuration options to control error broadcasting:

```yaml
# gleitzeit.yaml

websocket:
  broadcast_errors: true
  broadcast_warnings: true
  broadcast_validation_errors: true
  rate_limit_per_second: 100
  message_types:
    - workflow_event
    - error_event
    - validation_error
    - log_event
```

## Success Metrics

1. **Validation errors visible in UI** - Users see validation failures immediately
2. **Task execution errors visible in UI** - Users see task failures without checking logs
3. **No performance degradation** - WebSocket broadcasting doesn't slow down workers
4. **Reduced time to debug** - Users can identify issues faster

## Future Enhancements

1. **Log aggregation** - Show recent errors in UI dashboard
2. **Error analytics** - Track error frequency and types
3. **Alert thresholds** - Notify on error rate spikes
4. **Error replay** - Ability to replay error scenarios for debugging
5. **Export errors** - Download error logs for analysis

## Summary

This design extends the WebSocket implementation to provide comprehensive visibility into errors, warnings, and validation failures. By broadcasting these events in real-time, users gain immediate feedback on workflow issues without needing to check server logs or poll for status.

The implementation is backwards compatible, non-blocking, and follows the existing pub/sub architecture used by EventStore.
