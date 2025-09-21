# Timer & Scheduler Implementation Guide

## Current Status: ✅ IMPLEMENTED

The timer and scheduler system has been completely redesigned and implemented using a stream-based, stateless architecture that fits properly with Gleitzeit's design principles.

## Architecture Overview

### Core Components

1. **Timer Task Handler** (`src/gleitzeit/timers/handler.py`)
   - Handles timer task requests from workflows
   - Returns immediately with SLEEPING status
   - Registers timers in Redis for later processing

2. **Timer Monitor Service** (`src/gleitzeit/timers/monitor.py`)
   - Background service that monitors expired timers
   - Sends wake events via Redis Streams
   - Can run multiple instances for high availability

3. **Scheduler API** (`src/gleitzeit/scheduler/api.py`)
   - Manages scheduled workflows and cron jobs
   - Non-blocking API operations
   - Full CRUD operations for schedules

4. **Scheduler Monitor** (`src/gleitzeit/scheduler/monitor.py`)
   - Background service that executes scheduled workflows
   - Handles cron job recurrence
   - Automatic cleanup of old schedules

## How It Works

### Timer Flow

1. **Task Submission**
   ```python
   # Workflow includes a timer task
   task = Task(
       protocol="timer/v1",
       method="sleep",
       params={"seconds": 5}
   )
   ```

2. **Task Execution**
   - TaskExecutor detects `timer/v1` protocol
   - Calls `TimerTaskHandler.handle_timer_task()`
   - Timer registered in Redis sorted set
   - Returns TaskResult with SLEEPING status

3. **Timer Monitoring**
   - TimerMonitorService continuously checks for expired timers
   - When timer expires, sends wake event to workflow stream
   - Workflow execution resumes

### Scheduler Flow

1. **Schedule Creation**
   ```python
   # Schedule a workflow for future execution
   POST /scheduler/schedule
   {
       "workflow": {...},
       "run_at": "2024-12-25T09:00:00Z"
   }
   ```

2. **Monitoring & Execution**
   - SchedulerMonitor checks for due schedules
   - Submits workflow via `workflows:submit` stream
   - Updates schedule status to "executed"

3. **Cron Jobs**
   - Creates recurring schedules based on cron expression
   - Automatically schedules next execution after each run
   - Supports pause/resume operations

## API Endpoints

### Timer Endpoints

- `POST /timers/signal/{signal_name}` - Send signal to wake waiting tasks
- `GET /timers/stats` - Get timer system statistics
- `GET /timers/pending` - List pending timers
- `DELETE /timers/timer/{timer_id}` - Cancel a timer
- `GET /timers/signals` - List all signals with waiters

### Scheduler Endpoints

- `POST /scheduler/schedule` - Schedule a workflow
- `POST /scheduler/cron` - Create a cron job
- `DELETE /scheduler/schedule/{schedule_id}` - Cancel schedule
- `POST /scheduler/cron/{job_id}/pause` - Pause cron job
- `POST /scheduler/cron/{job_id}/resume` - Resume cron job
- `DELETE /scheduler/cron/{job_id}` - Delete cron job
- `GET /scheduler/schedules` - List schedules
- `GET /scheduler/cron` - List cron jobs

## Redis Data Structures

### Sorted Sets
- `timers:pending` - Pending timers sorted by wake time
- `timers:completed` - Completed timers (for debugging)
- `scheduler:pending` - Scheduled tasks sorted by run time

### Streams
- `workflow:{id}:events` - Per-workflow event stream
- `workflows:submit` - Workflow submission stream
- `scheduler:events` - Scheduler event stream

### Hashes
- `timer:{id}` - Timer metadata
- `schedule:{id}` - Schedule metadata
- `cronjob:{id}` - Cron job configuration

### Sets
- `cronjobs:active` - Active cron job IDs
- `cronjobs:paused` - Paused cron job IDs
- `signal:{name}:waiters` - Tasks waiting for signal

## Running the Services

### Timer Monitor Service

```bash
# Standalone service
python -m gleitzeit.timers.monitor

# Or via Docker
docker run -e REDIS_URL=redis://redis:6379 gleitzeit:latest \
    python -m gleitzeit.timers.monitor
```

### Scheduler Monitor Service

```bash
# Standalone service
python -m gleitzeit.scheduler.monitor

# Or via Docker
docker run -e REDIS_URL=redis://redis:6379 gleitzeit:latest \
    python -m gleitzeit.scheduler.monitor
```

### Docker Compose Setup

```yaml
version: '3.8'

services:
  gleitzeit-api:
    image: gleitzeit:latest
    ports:
      - "8000:8000"
    environment:
      - REDIS_URL=redis://redis:6379
    depends_on:
      - redis

  timer-monitor:
    image: gleitzeit:latest
    command: ["python", "-m", "gleitzeit.timers.monitor"]
    environment:
      - REDIS_URL=redis://redis:6379
    deploy:
      replicas: 2  # Run 2 instances for HA
    depends_on:
      - redis

  scheduler-monitor:
    image: gleitzeit:latest
    command: ["python", "-m", "gleitzeit.scheduler.monitor"]
    environment:
      - REDIS_URL=redis://redis:6379
    deploy:
      replicas: 2  # Run 2 instances for HA
    depends_on:
      - redis

  redis:
    image: redis:7-alpine
    command: ["redis-server", "--appendonly", "yes"]
    volumes:
      - redis-data:/data

volumes:
  redis-data:
```

## Usage Examples

### Simple Timer Workflow

```python
from gleitzeit.client import GleitzeitClient
from gleitzeit.core.models import Workflow, Task

client = GleitzeitClient(mode="api")
await client.initialize()

workflow = Workflow(
    id="timer-example",
    tasks=[
        Task(
            id="start",
            protocol="python/v1",
            method="exec",
            params={"code": "print('Starting'); return {'started': True}"}
        ),
        Task(
            id="wait",
            protocol="timer/v1",
            method="sleep",
            params={"seconds": 5},
            dependencies=["start"]
        ),
        Task(
            id="done",
            protocol="python/v1",
            method="exec",
            params={"code": "print('Timer completed')"},
            dependencies=["wait"]
        )
    ]
)

result = await client.submit_workflow(workflow)
```

### Schedule a Workflow

```python
import httpx
from datetime import datetime, timedelta

async with httpx.AsyncClient() as client:
    # Schedule to run in 1 hour
    response = await client.post(
        "http://localhost:8000/scheduler/schedule",
        json={
            "workflow": {
                "id": "scheduled-task",
                "tasks": [{
                    "id": "task1",
                    "protocol": "python/v1",
                    "method": "exec",
                    "params": {"code": "print('Scheduled task executed')"}
                }]
            },
            "run_at": (datetime.utcnow() + timedelta(hours=1)).isoformat()
        }
    )
    print(f"Scheduled: {response.json()}")
```

### Create a Cron Job

```python
# Daily at 9 AM
response = await client.post(
    "http://localhost:8000/scheduler/cron",
    json={
        "cron_expression": "0 9 * * *",
        "workflow": {
            "id": "daily-report",
            "tasks": [{
                "id": "generate",
                "protocol": "python/v1",
                "method": "exec",
                "params": {"code": "print('Daily report')"}
            }]
        },
        "job_name": "daily-report",
        "timezone": "UTC"
    }
)
```

### Send a Signal

```python
# Wake all tasks waiting for "data_ready" signal
response = await client.post(
    "http://localhost:8000/timers/signal/data_ready"
)
print(f"Woke {response.json()['tasks_woken']} tasks")
```

## Key Benefits

1. **Fully Stateless**: All state in Redis, services can restart anytime
2. **Horizontally Scalable**: Multiple monitor services can run concurrently
3. **Event-Driven**: Uses Redis Streams for loose coupling
4. **Non-Blocking**: Never blocks execution threads
5. **Fault Tolerant**: Can recover from service failures
6. **Observable**: All events in streams for monitoring

## Troubleshooting

### Timers Not Firing

1. Check timer monitor is running:
   ```bash
   curl http://localhost:8000/timers/stats
   ```

2. Check Redis connectivity:
   ```bash
   redis-cli ping
   ```

3. Check pending timers:
   ```bash
   redis-cli zrange timers:pending 0 -1 WITHSCORES
   ```

### Schedules Not Executing

1. Check scheduler monitor is running
2. Verify workflow submission stream:
   ```bash
   redis-cli xlen workflows:submit
   ```

3. Check scheduler logs for errors

### High Memory Usage

- Set TTL on completed timers/schedules
- Run cleanup task more frequently
- Reduce history retention period

## Migration from Old System

If you had an old timer/scheduler implementation:

1. Stop old timer services
2. Clear old Redis keys (if different namespace)
3. Deploy new monitor services
4. Update workflows to use `timer/v1` protocol
5. Test with simple timer workflow first

## Future Enhancements

- [ ] Timer persistence across Redis restarts
- [ ] Advanced cron expressions (with seconds)
- [ ] Timer metrics and monitoring dashboard
- [ ] Webhook notifications for timer events
- [ ] Timer groups and batch operations
- [ ] Priority-based timer execution
- [ ] Distributed timer coordination

## References

- [Timer Stream Architecture](TIMER-STREAM-ARCHITECTURE.md)
- [Scheduler Detailed Design](SCHEDULER-DETAILED-DESIGN.md)
- [Timer Implementation Status](TIMER-IMPLEMENTATION-STATUS.md)