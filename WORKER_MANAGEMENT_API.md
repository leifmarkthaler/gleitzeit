# Worker Management API

API endpoints for managing workers remotely without manual process restarts.

## Quick Start

```bash
# Restart timer worker to apply fixes
curl -X POST "http://localhost:8000/system/workers/timer-async/restart?reason=Apply+timer+fixes"

# List all workers
curl http://localhost:8000/system/workers

# Stop a worker
curl -X POST "http://localhost:8000/system/workers/worker-id/stop"

# Reload configuration
curl -X POST "http://localhost:8000/system/workers/worker-id/reload"
```

## Endpoints

### List Workers

**GET** `/system/workers`

Returns list of all registered workers with their metadata.

**Example Response:**
```json
{
  "count": 5,
  "workers": [
    {
      "worker_id": "timer-async",
      "worker_type": "timer",
      "status": "running",
      "started_at": "2025-10-12T10:00:00",
      "shards": "[0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15]"
    }
  ]
}
```

### Restart Worker

**POST** `/system/workers/{worker_id}/restart`

Gracefully restarts a specific worker. The worker will:
1. Finish processing current messages
2. Shut down gracefully
3. Be restarted by the process orchestrator

**Parameters:**
- `worker_id` (path): Worker identifier (e.g., "timer-async")
- `reason` (query, optional): Reason for restart

**Example Request:**
```bash
curl -X POST "http://localhost:8000/system/workers/timer-async/restart?reason=Apply+timer+fixes"
```

**Example Response:**
```json
{
  "worker_id": "timer-async",
  "command": "restart",
  "status": "sent",
  "reason": "Apply timer fixes",
  "timestamp": 1760259123.456
}
```

### Stop Worker

**POST** `/system/workers/{worker_id}/stop`

Gracefully stops a specific worker (without restart).

**Parameters:**
- `worker_id` (path): Worker identifier
- `reason` (query, optional): Reason for stopping

**Example Request:**
```bash
curl -X POST "http://localhost:8000/system/workers/timer-async/stop?reason=Maintenance"
```

### Reload Worker Configuration

**POST** `/system/workers/{worker_id}/reload`

Reloads worker configuration without restart (hot reload).

**Parameters:**
- `worker_id` (path): Worker identifier

**Example Request:**
```bash
curl -X POST "http://localhost:8000/system/workers/timer-async/reload"
```

## How It Works

### Command Flow

1. **API receives request** → Stores command in Redis with 60s TTL
   ```
   Key: {shard:0}:worker:command:{worker_id}
   Value: {"command": "restart", "timestamp": 1234567890, "reason": "..."}
   ```

2. **Worker checks for commands** → Every heartbeat interval (default 10s)
   - Reads command from Redis key
   - Validates timestamp (must be < 60s old)
   - Deletes command to prevent reprocessing

3. **Worker executes command**:
   - **restart**: Updates status to "restarting" → Triggers shutdown → Orchestrator restarts
   - **stop**: Updates status to "stopping" → Triggers shutdown (no restart)
   - **reload**: Reloads configuration from Redis (implementation-specific)

### Worker State Updates

Workers update their registry during command execution:

```python
# Restart command
await redis.hset(
    "{shard:0}:worker:registry:{worker_id}",
    mapping={
        "status": "restarting",
        "restart_reason": "API restart request",
        "restart_requested_at": "2025-10-12T11:00:00"
    }
)
```

### Error Handling

- **Worker not found**: Returns 404
- **Command timeout**: Commands expire after 60 seconds
- **Stale commands**: Ignored if timestamp > 60s old
- **Unknown commands**: Logged as warning, not executed

## Use Cases

### Apply Hot Fixes

```bash
# After deploying timer fix, restart timer worker to pick up changes
curl -X POST "http://localhost:8000/system/workers/timer-async/restart?reason=Apply+timezone+fix"
```

### Maintenance

```bash
# Stop specific worker for maintenance
curl -X POST "http://localhost:8000/system/workers/python_specialist-async/stop?reason=System+maintenance"
```

### Configuration Changes

```bash
# Reload configuration without downtime
curl -X POST "http://localhost:8000/system/workers/task_execution-async/reload"
```

## Security Considerations

1. **Command Expiry**: Commands expire after 60 seconds to prevent replay attacks
2. **Single Execution**: Commands are deleted immediately after processing
3. **Worker Validation**: Checks worker exists before sending command
4. **Graceful Shutdown**: Workers finish current work before stopping

## Monitoring

Check worker status after sending commands:

```bash
# Check if worker restarted
curl "http://localhost:8000/system/workers" | jq '.workers[] | select(.worker_id == "timer-async")'
```

## Implementation Details

### BaseWorker Changes

- Added `_check_worker_commands()` method (called every heartbeat)
- Added `_handle_restart_command()`
- Added `_handle_stop_command()`
- Added `_handle_reload_command()`

### API Routes

- `POST /system/workers/{worker_id}/restart`
- `POST /system/workers/{worker_id}/stop`
- `POST /system/workers/{worker_id}/reload`

All endpoints:
- Validate worker exists
- Store command in Redis with TTL
- Return command confirmation
