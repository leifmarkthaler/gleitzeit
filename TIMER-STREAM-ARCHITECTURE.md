# Stream-Based Timer & Scheduler Architecture

## Overview

A fully stateless, scalable timer and scheduler system for Gleitzeit that uses Redis Streams and sorted sets for event-driven timer management. No blocking operations, fully distributed, and horizontally scalable.

## Core Principles

1. **Stateless**: No in-memory state, everything persisted in Redis
2. **Stream-Based**: Uses Redis Streams for event communication
3. **Non-Blocking**: Never blocks execution, always returns immediately
4. **Scalable**: Multiple timer services can run concurrently
5. **Event-Driven**: Timer expiry triggers events, not direct execution

## Architecture Components

### 1. Timer Task Handler (Immediate Return)

When a workflow task requests a timer operation, it immediately returns a "WAITING" status:

```python
class TimerTaskHandler:
    """Handles timer task requests from workflows."""
    
    async def handle_sleep(self, workflow_id: str, task_id: str, seconds: int) -> dict:
        """Register a sleep timer and return immediately."""
        wake_at = time.time() + seconds
        timer_id = f"{workflow_id}:{task_id}:{uuid.uuid4().hex[:8]}"
        
        # Store in Redis sorted set (sorted by wake time)
        await redis.zadd("timers:pending", {timer_id: wake_at})
        
        # Store timer metadata
        await redis.hset(f"timer:{timer_id}", mapping={
            "workflow_id": workflow_id,
            "task_id": task_id,
            "type": "sleep",
            "wake_at": wake_at,
            "created_at": time.time()
        })
        
        # Mark task as waiting
        await redis.xadd(f"workflow:{workflow_id}:events", {
            "event": "task_waiting",
            "task_id": task_id,
            "timer_id": timer_id,
            "wake_at": wake_at
        })
        
        # Return immediately with waiting status
        return {
            "status": "waiting",
            "timer_id": timer_id,
            "wake_at": wake_at
        }
```

### 2. Timer Monitor Service (Background Process)

Continuously monitors pending timers and triggers wake events:

```python
class TimerMonitorService:
    """Background service that monitors and triggers timers."""
    
    async def run(self):
        """Main monitoring loop."""
        while True:
            try:
                # Get all expired timers
                now = time.time()
                expired = await redis.zrangebyscore(
                    "timers:pending", 
                    0, 
                    now,
                    withscores=False,
                    start=0,
                    num=100  # Process in batches
                )
                
                for timer_id in expired:
                    await self.trigger_timer(timer_id)
                    
                # Small sleep to prevent tight loop
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Timer monitor error: {e}")
                await asyncio.sleep(1)
    
    async def trigger_timer(self, timer_id: str):
        """Trigger a timer wake event."""
        # Get timer metadata
        timer_data = await redis.hgetall(f"timer:{timer_id}")
        
        if not timer_data:
            # Timer already processed
            await redis.zrem("timers:pending", timer_id)
            return
        
        # Send wake event to workflow stream
        workflow_id = timer_data["workflow_id"]
        await redis.xadd(f"workflow:{workflow_id}:events", {
            "event": "timer_wake",
            "timer_id": timer_id,
            "task_id": timer_data["task_id"],
            "type": timer_data["type"]
        })
        
        # Move to completed set (for history/debugging)
        await redis.zadd("timers:completed", {timer_id: time.time()})
        
        # Remove from pending
        await redis.zrem("timers:pending", timer_id)
        
        # Cleanup metadata after TTL
        await redis.expire(f"timer:{timer_id}", 3600)  # 1 hour TTL
```

### 3. Workflow Event Processor

Handles timer wake events and resumes workflow execution:

```python
class WorkflowEventProcessor:
    """Processes events for workflows including timer wakes."""
    
    async def process_workflow_events(self, workflow_id: str):
        """Process events for a specific workflow."""
        stream_key = f"workflow:{workflow_id}:events"
        last_id = "0"
        
        while True:
            # Read events from stream
            events = await redis.xread(
                {stream_key: last_id},
                block=100,  # Block for 100ms max
                count=10
            )
            
            for stream, messages in events:
                for msg_id, data in messages:
                    await self.handle_event(workflow_id, data)
                    last_id = msg_id
    
    async def handle_event(self, workflow_id: str, event_data: dict):
        """Handle a workflow event."""
        event_type = event_data.get("event")
        
        if event_type == "timer_wake":
            task_id = event_data["task_id"]
            
            # Resume task execution
            await redis.xadd(f"tasks:ready", {
                "workflow_id": workflow_id,
                "task_id": task_id,
                "resume_from": "timer",
                "timer_id": event_data["timer_id"]
            })
            
            # Update task status
            await redis.hset(
                f"workflow:{workflow_id}:task:{task_id}",
                "status", "ready"
            )
```

### 4. Scheduler Service

Handles cron-based and scheduled task execution:

```python
class SchedulerService:
    """Manages scheduled and recurring tasks."""
    
    async def schedule_task(
        self, 
        run_at: datetime,
        workflow_template: dict,
        schedule_id: str = None
    ) -> str:
        """Schedule a one-time task execution."""
        schedule_id = schedule_id or f"schedule:{uuid.uuid4().hex}"
        
        # Store in sorted set by run time
        await redis.zadd(
            "scheduler:pending",
            {schedule_id: run_at.timestamp()}
        )
        
        # Store schedule metadata
        await redis.hset(f"schedule:{schedule_id}", mapping={
            "workflow_template": json.dumps(workflow_template),
            "run_at": run_at.isoformat(),
            "status": "pending"
        })
        
        return schedule_id
    
    async def create_cron_job(
        self,
        cron_expression: str,
        workflow_template: dict,
        job_id: str = None
    ) -> str:
        """Create a recurring cron job."""
        from croniter import croniter
        
        job_id = job_id or f"cron:{uuid.uuid4().hex}"
        cron = croniter(cron_expression)
        next_run = cron.get_next(datetime)
        
        # Store cron job
        await redis.hset(f"cron:{job_id}", mapping={
            "expression": cron_expression,
            "workflow_template": json.dumps(workflow_template),
            "next_run": next_run.isoformat(),
            "status": "active"
        })
        
        # Schedule next execution
        await self.schedule_task(
            next_run,
            workflow_template,
            f"{job_id}:run:{next_run.timestamp()}"
        )
        
        # Add to active cron jobs
        await redis.sadd("cron:active", job_id)
        
        return job_id
    
    async def monitor_schedules(self):
        """Monitor and trigger scheduled tasks."""
        while True:
            now = time.time()
            
            # Get due schedules
            due = await redis.zrangebyscore(
                "scheduler:pending",
                0,
                now,
                start=0,
                num=10
            )
            
            for schedule_id in due:
                await self.execute_schedule(schedule_id)
            
            await asyncio.sleep(1)
    
    async def execute_schedule(self, schedule_id: str):
        """Execute a scheduled task."""
        # Get schedule data
        schedule_data = await redis.hgetall(f"schedule:{schedule_id}")
        
        if not schedule_data:
            await redis.zrem("scheduler:pending", schedule_id)
            return
        
        # Submit workflow
        workflow_template = json.loads(schedule_data["workflow_template"])
        
        # Create workflow submission event
        await redis.xadd("workflows:submit", {
            "workflow": json.dumps(workflow_template),
            "source": "scheduler",
            "schedule_id": schedule_id
        })
        
        # Check if this is from a cron job
        if schedule_id.startswith("cron:"):
            job_id = schedule_id.split(":")[1]
            await self.schedule_next_cron_run(job_id)
        
        # Clean up
        await redis.zrem("scheduler:pending", schedule_id)
        await redis.expire(f"schedule:{schedule_id}", 86400)  # 24h TTL
```

## Integration with Workflow System

### Modified Task Execution

```python
class TaskExecutor:
    """Enhanced task executor with timer support."""
    
    async def execute_task(self, task: Task) -> TaskResult:
        """Execute a task with timer support."""
        
        # Check if this is a timer protocol
        if task.protocol == "timer/v1":
            return await self.handle_timer_task(task)
        
        # Normal task execution
        return await self.execute_normal_task(task)
    
    async def handle_timer_task(self, task: Task) -> TaskResult:
        """Handle timer tasks."""
        handler = TimerTaskHandler()
        
        if task.method == "sleep":
            result = await handler.handle_sleep(
                task.workflow_id,
                task.id,
                task.params.get("seconds", 0)
            )
            
            # Return waiting status
            return TaskResult(
                task_id=task.id,
                status=TaskStatus.WAITING,
                result=result,
                metadata={"timer_id": result["timer_id"]}
            )
```

## Redis Data Structures

### Sorted Sets
- `timers:pending` - Pending timers sorted by wake time
- `timers:completed` - Completed timers (for debugging)
- `scheduler:pending` - Scheduled tasks sorted by run time

### Streams
- `workflow:{id}:events` - Per-workflow event stream
- `workflows:submit` - Workflow submission stream
- `tasks:ready` - Ready tasks queue

### Hashes
- `timer:{id}` - Timer metadata
- `schedule:{id}` - Schedule metadata
- `cron:{id}` - Cron job configuration

### Sets
- `cron:active` - Active cron job IDs

## Deployment Architecture

```yaml
version: '3.8'
services:
  # Main Gleitzeit API
  gleitzeit-api:
    image: gleitzeit:latest
    environment:
      - REDIS_URL=redis://redis:6379
    depends_on:
      - redis
  
  # Timer Monitor Service (can scale horizontally)
  timer-monitor:
    image: gleitzeit:latest
    command: ["python", "-m", "gleitzeit.timers.monitor"]
    environment:
      - REDIS_URL=redis://redis:6379
    deploy:
      replicas: 2  # Multiple monitors for HA
    depends_on:
      - redis
  
  # Scheduler Service
  scheduler:
    image: gleitzeit:latest
    command: ["python", "-m", "gleitzeit.scheduler.service"]
    environment:
      - REDIS_URL=redis://redis:6379
    deploy:
      replicas: 2  # Multiple schedulers for HA
    depends_on:
      - redis
  
  # Redis with persistence
  redis:
    image: redis:7-alpine
    command: ["redis-server", "--appendonly", "yes"]
    volumes:
      - redis-data:/data
```

## Benefits

1. **Fully Stateless**: All state in Redis, services can restart anytime
2. **Horizontally Scalable**: Multiple timer/scheduler services can run
3. **Event-Driven**: Uses streams for loose coupling
4. **Non-Blocking**: Never blocks execution threads
5. **Fault Tolerant**: Can recover from service failures
6. **Observable**: All events in streams for monitoring

## Usage Examples

### Simple Timer in Workflow

```yaml
id: timer-example
tasks:
  - id: start
    protocol: python/v1
    method: exec
    params:
      code: "print('Starting'); return {'start': True}"
  
  - id: wait
    protocol: timer/v1
    method: sleep
    params:
      seconds: 5
    dependencies: [start]
  
  - id: done
    protocol: python/v1
    method: exec
    params:
      code: "print('Timer completed'); return {'done': True}"
    dependencies: [wait]
```

### Scheduled Task

```python
# Schedule a workflow to run at specific time
scheduler = SchedulerService()
schedule_id = await scheduler.schedule_task(
    run_at=datetime(2024, 12, 25, 9, 0),  # Christmas morning
    workflow_template={
        "id": "holiday-greeting",
        "tasks": [{
            "id": "greet",
            "protocol": "python/v1",
            "method": "exec",
            "params": {"code": "print('Merry Christmas!')"}
        }]
    }
)
```

### Cron Job

```python
# Run workflow every hour
job_id = await scheduler.create_cron_job(
    cron_expression="0 * * * *",  # Every hour
    workflow_template={
        "id": "hourly-check",
        "tasks": [{
            "id": "check",
            "protocol": "python/v1",
            "method": "exec",
            "params": {"code": "print('Hourly check')"}
        }]
    }
)
```

## Implementation Plan

1. **Phase 1**: Timer infrastructure
   - Timer task handler
   - Timer monitor service
   - Event integration

2. **Phase 2**: Scheduler
   - One-time scheduling
   - Cron job support
   - Schedule management API

3. **Phase 3**: Advanced Features
   - Timer signals/interrupts
   - SLA monitoring
   - Timer analytics

This architecture provides a robust, scalable timer and scheduler system that fits perfectly with Gleitzeit's stateless, stream-based design.