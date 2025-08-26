# Gleitzeit Log System Documentation

## Overview

The Gleitzeit log system provides centralized, real-time logging for all platform components with persistent storage and WebSocket streaming capabilities. The system is designed to capture detailed execution information while maintaining high performance through buffering and batch operations.

## Architecture

### Core Components

1. **LogCollector** (`/src/gleitzeit/core/log_collector.py`)
   - Centralized service for collecting logs from all components
   - Buffers logs for efficient batch persistence
   - Supports both Redis and SQL backends with automatic fallback
   - Provides context managers for task/workflow correlation
   - Configurable buffer size (default: 100 logs) and flush interval (default: 1 second)

2. **LogStreamManager** (`/src/gleitzeit/core/log_stream.py`)
   - Manages WebSocket subscriptions for real-time log streaming
   - Maintains per-stream buffers for replay capability
   - Handles client connection lifecycle
   - Supports filtered subscriptions by task or workflow

3. **Log Data Models** (`/src/gleitzeit/core/logs.py`)
   - Structured log entry format with metadata support
   - Defined log levels and sources
   - Event data structures for log-related events

4. **Persistence Backends**
   
   **Redis Backend** (`/src/gleitzeit/persistence/log_redis_adapter.py`) - **Preferred**
   - Uses Redis Streams for time-series log storage
   - Automatic log expiration with configurable TTL (default: 7 days)
   - High-performance batch operations
   - Multiple access patterns (global, task, workflow)
   - FIFO eviction with configurable stream length
   
   **SQL Backend** (`/src/gleitzeit/persistence/unified_sqlalchemy.py`)
   - SQLAlchemy models for persistent log storage
   - Indexes for efficient querying by task/workflow
   - JSON metadata field for extensibility
   - Fallback option when Redis is unavailable

## Log Levels

```python
class LogLevel(str, Enum):
    DEBUG = "debug"      # Detailed diagnostic information
    INFO = "info"        # General informational messages
    WARNING = "warning"  # Warning messages for potential issues
    ERROR = "error"      # Error messages for failures
    CRITICAL = "critical" # Critical errors requiring immediate attention
```

## Log Sources

```python
class LogSource(str, Enum):
    PROVIDER = "provider"  # Protocol provider logs (future)
    ENGINE = "engine"      # Execution engine logs
    QUEUE = "queue"        # Task queue logs (future)
    DOCKER = "docker"      # Docker container logs (future)
    SYSTEM = "system"      # System-level logs
```

## API Endpoints

### WebSocket Endpoints

#### Stream Task Logs
```
WebSocket: /ws/logs/task/{task_id}
```

Subscribes to real-time logs for a specific task.

**Connection Example:**
```javascript
const ws = new WebSocket('ws://localhost:8000/ws/logs/task/abc-123');

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log(`[${data.data.level}] ${data.data.message}`);
};
```

**Message Types:**
- `log:subscribed` - Confirmation of subscription
- `log:history` - Historical log entries (buffered)
- `log:message` - Real-time log entry
- `log:stream_start` - Stream started notification
- `log:stream_end` - Stream ended notification

#### Stream Workflow Logs
```
WebSocket: /ws/logs/workflow/{workflow_id}
```

Subscribes to real-time logs for all tasks in a workflow.

### REST Endpoints

#### Get Task Logs
```
GET /logs/task/{task_id}
```

Retrieves historical logs for a task.

**Query Parameters:**
- `level`: Minimum log level to return (optional)
- `limit`: Maximum number of logs to return (optional)
- `offset`: Pagination offset (optional)

#### Get Workflow Logs
```
GET /logs/workflow/{workflow_id}
```

Retrieves historical logs for all tasks in a workflow.

## Usage Examples

### Python Client Example

```python
import asyncio
import json
import websockets

async def stream_task_logs(task_id):
    """Connect to WebSocket and stream logs for a task"""
    uri = f"ws://localhost:8000/ws/logs/task/{task_id}"
    
    async with websockets.connect(uri) as websocket:
        print("Connected to log stream!")
        
        while True:
            message = await websocket.recv()
            data = json.loads(message)
            
            if data['type'] == 'log:message':
                log = data['data']
                print(f"[{log['level']}][{log['source']}] {log['message']}")
            elif data['type'] == 'log:stream_end':
                break

# Run the client
asyncio.run(stream_task_logs("your-task-id"))
```

### JavaScript Client Example

```javascript
class LogStreamClient {
    constructor(baseUrl = 'ws://localhost:8000') {
        this.baseUrl = baseUrl;
    }

    streamTaskLogs(taskId, onLog) {
        const ws = new WebSocket(`${this.baseUrl}/ws/logs/task/${taskId}`);
        
        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            
            switch(data.type) {
                case 'log:subscribed':
                    console.log('Subscribed to log stream');
                    break;
                case 'log:message':
                    onLog(data.data);
                    break;
                case 'log:stream_end':
                    ws.close();
                    break;
            }
        };
        
        ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
        
        return ws;
    }
}

// Usage
const client = new LogStreamClient();
const ws = client.streamTaskLogs('task-123', (log) => {
    console.log(`[${log.level}] ${log.message}`);
});
```

## Log Entry Structure

Each log entry contains the following fields:

```json
{
    "timestamp": "2024-08-26T17:20:05.787144",
    "level": "info",
    "message": "Task submitted: Test Log Streaming Task",
    "source": "engine",
    "task_id": "6ac98dc6-9b41-4439-88a5-7835ec58bd16",
    "workflow_id": "wf-123",
    "provider_id": null,
    "stream_type": null,
    "line_number": null,
    "metadata": {
        "protocol": "python/v1",
        "method": "python/execute",
        "queue": "default"
    }
}
```

## Configuration

### LogCollector Configuration

```python
LogCollector(
    event_bus=event_bus,           # Event bus for streaming
    persistence=persistence,        # SQL persistence adapter
    redis_adapter=redis_adapter,    # Redis adapter (preferred)
    buffer_size=100,                # Logs to buffer before flush
    flush_interval=1.0,             # Seconds between flushes
    enable_persistence=True,        # Enable database storage
    enable_streaming=True,          # Enable WebSocket streaming
    prefer_redis=True              # Use Redis when available
)
```

### Redis Log Adapter Configuration

```python
LogRedisAdapter(
    redis_adapter=redis_adapter,    # Existing Redis connection
    log_ttl_days=7,                 # Days to retain logs
    max_stream_length=10000         # Max entries per stream
)
```

### LogStreamManager Configuration

```python
LogStreamManager(
    event_bus=event_bus,            # Event bus for receiving logs
    buffer_size=1000,               # Per-stream buffer size
    buffer_ttl=3600                 # Buffer retention (seconds)
)
```

## Current Implementation Status

### ✅ Implemented
- Core log collection and buffering system
- Real-time WebSocket streaming
- Database persistence with SQLAlchemy
- Engine-level logging (task lifecycle events)
- Task/workflow correlation
- Structured log entries with metadata
- Buffer management and cleanup
- Event-driven architecture integration

### 🔄 Future Enhancements
- Provider output streaming (stdout/stderr capture)
- Queue operation logging
- Docker container log integration
- Log aggregation and search API
- Log retention policies
- Log export functionality
- Performance metrics dashboard
- Log filtering and query language

## Performance Considerations

1. **Redis Streams**: When using Redis, logs are stored in high-performance streams with automatic trimming
2. **Buffering**: Logs are buffered in memory (100 logs or 1 second) before persistence to reduce I/O operations
3. **Async Operations**: All logging operations are asynchronous to prevent blocking
4. **Selective Streaming**: Clients can subscribe to specific tasks/workflows to reduce bandwidth
5. **Automatic Cleanup**: Redis TTL and stream trimming automatically manage storage
6. **Fallback Strategy**: Automatic fallback from Redis to SQL ensures reliability
7. **Event-Driven**: Uses existing EventBus for minimal overhead

### Backend Performance Comparison

| Backend | Write Speed | Query Speed | Storage Efficiency | Auto-Cleanup |
|---------|------------|-------------|-------------------|--------------|
| Redis   | Very Fast  | Very Fast   | High (streams)    | Yes (TTL)    |
| SQL     | Moderate   | Moderate    | Moderate          | Manual       |

## Migration Notes

The log system is designed with zero breaking changes:
- All existing functionality remains intact
- Logging is additive - doesn't interfere with existing operations
- Can be disabled via configuration if needed
- Backward compatible with existing API

## Security Considerations

1. **Access Control**: WebSocket endpoints should be protected with authentication (future)
2. **Data Sanitization**: Log messages are sanitized to prevent XSS attacks
3. **Rate Limiting**: Consider implementing rate limits for WebSocket connections
4. **Sensitive Data**: Avoid logging sensitive information like passwords or API keys

## Troubleshooting

### Common Issues

1. **No logs appearing**: Check that LogCollector and LogStreamManager are initialized
2. **WebSocket connection fails**: Verify the server is running and accessible
3. **Missing historical logs**: Ensure persistence is enabled in LogCollector
4. **High memory usage**: Reduce buffer_size or buffer_ttl settings

### Debug Mode

Enable debug logging for the log system itself:

```python
import logging
logging.getLogger('gleitzeit.core.log_collector').setLevel(logging.DEBUG)
logging.getLogger('gleitzeit.core.log_stream').setLevel(logging.DEBUG)
```

## Example Integration

### Adding Logging to a New Component

```python
from gleitzeit.core.log_collector import get_log_collector
from gleitzeit.core.logs import LogLevel, LogSource

async def my_component_function(task_id):
    log_collector = get_log_collector()
    
    if log_collector:
        await log_collector.log(
            LogLevel.INFO,
            "Starting component operation",
            LogSource.SYSTEM,
            task_id=task_id,
            metadata={"component": "my_component"}
        )
    
    # Component logic here
    
    if log_collector:
        await log_collector.log(
            LogLevel.INFO,
            "Component operation completed",
            LogSource.SYSTEM,
            task_id=task_id
        )
```

### Using Context Managers

```python
async def process_task(task_id, workflow_id):
    log_collector = get_log_collector()
    
    # All logs within this context will have task/workflow correlation
    async with log_collector.stream_context(task_id, workflow_id):
        await log_collector.log(LogLevel.INFO, "Processing started", LogSource.ENGINE)
        # ... task processing ...
        await log_collector.log(LogLevel.INFO, "Processing completed", LogSource.ENGINE)
```

## Testing

### Unit Test Example

```python
import pytest
from gleitzeit.core.log_collector import LogCollector
from gleitzeit.core.logs import LogLevel, LogSource

@pytest.mark.asyncio
async def test_log_collection():
    collector = LogCollector(
        enable_persistence=False,
        enable_streaming=False
    )
    
    await collector.start()
    
    await collector.log(
        LogLevel.INFO,
        "Test message",
        LogSource.SYSTEM,
        task_id="test-123"
    )
    
    stats = collector.get_collector_stats()
    assert stats['total_logged'] == 1
    
    await collector.stop()
```

### Integration Test Example

See `/test_log_streaming.py` for a complete end-to-end test that:
1. Submits a task to Gleitzeit
2. Connects to the WebSocket endpoint
3. Receives and validates log messages
4. Verifies task completion

## Contact & Support

For questions or issues with the log system, please refer to:
- GitHub Issues: https://github.com/anthropics/gleitzeit/issues
- Documentation: This file and related docs in `/docs`
- Source Code: `/src/gleitzeit/core/log_*.py`