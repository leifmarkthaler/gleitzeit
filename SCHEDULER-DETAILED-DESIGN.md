# Scheduler Service - Detailed Design

## Overview

The Scheduler Service is a stateless, stream-based component that handles:
- One-time scheduled task execution
- Recurring cron jobs
- Workflow scheduling
- Time-based workflow triggers

## Core Components

### 1. Scheduler API (Non-Blocking)

```python
class SchedulerAPI:
    """API endpoints for scheduler operations."""
    
    async def schedule_workflow(
        self,
        workflow: dict,
        run_at: datetime,
        metadata: dict = None
    ) -> dict:
        """Schedule a workflow to run at a specific time."""
        schedule_id = f"sched:{uuid.uuid4().hex}"
        
        # Store in Redis sorted set (sorted by timestamp)
        await redis.zadd(
            "scheduler:pending",
            {schedule_id: run_at.timestamp()}
        )
        
        # Store schedule details
        await redis.hset(f"schedule:{schedule_id}", mapping={
            "workflow": json.dumps(workflow),
            "run_at": run_at.isoformat(),
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
            "metadata": json.dumps(metadata or {})
        })
        
        # Send event to stream
        await redis.xadd("scheduler:events", {
            "event": "schedule_created",
            "schedule_id": schedule_id,
            "run_at": run_at.isoformat()
        })
        
        return {
            "schedule_id": schedule_id,
            "run_at": run_at.isoformat(),
            "status": "scheduled"
        }
    
    async def create_cron_job(
        self,
        cron_expression: str,
        workflow: dict,
        job_name: str = None,
        timezone: str = "UTC"
    ) -> dict:
        """Create a recurring cron job."""
        from croniter import croniter
        import pytz
        
        job_id = f"cron:{job_name or uuid.uuid4().hex}"
        tz = pytz.timezone(timezone)
        
        # Validate cron expression
        try:
            cron = croniter(cron_expression, datetime.now(tz))
            next_run = cron.get_next(datetime)
        except Exception as e:
            raise ValueError(f"Invalid cron expression: {e}")
        
        # Store cron job
        await redis.hset(f"cronjob:{job_id}", mapping={
            "id": job_id,
            "name": job_name or job_id,
            "expression": cron_expression,
            "workflow": json.dumps(workflow),
            "timezone": timezone,
            "next_run": next_run.isoformat(),
            "status": "active",
            "created_at": datetime.utcnow().isoformat(),
            "execution_count": 0
        })
        
        # Add to active cron jobs set
        await redis.sadd("cronjobs:active", job_id)
        
        # Schedule first execution
        await self.schedule_workflow(
            workflow=workflow,
            run_at=next_run,
            metadata={"cron_job_id": job_id, "cron_execution": 1}
        )
        
        return {
            "job_id": job_id,
            "cron": cron_expression,
            "next_run": next_run.isoformat(),
            "timezone": timezone,
            "status": "active"
        }
    
    async def cancel_schedule(self, schedule_id: str) -> dict:
        """Cancel a scheduled execution."""
        # Remove from pending
        removed = await redis.zrem("scheduler:pending", schedule_id)
        
        if removed:
            # Update status
            await redis.hset(f"schedule:{schedule_id}", "status", "cancelled")
            
            # Send cancellation event
            await redis.xadd("scheduler:events", {
                "event": "schedule_cancelled",
                "schedule_id": schedule_id
            })
            
            return {"cancelled": True, "schedule_id": schedule_id}
        
        return {"cancelled": False, "reason": "Schedule not found or already executed"}
    
    async def pause_cron_job(self, job_id: str) -> dict:
        """Pause a cron job."""
        # Check if exists
        exists = await redis.exists(f"cronjob:{job_id}")
        if not exists:
            return {"paused": False, "reason": "Job not found"}
        
        # Update status
        await redis.hset(f"cronjob:{job_id}", "status", "paused")
        
        # Remove from active set
        await redis.srem("cronjobs:active", job_id)
        
        # Add to paused set
        await redis.sadd("cronjobs:paused", job_id)
        
        return {"paused": True, "job_id": job_id}
    
    async def resume_cron_job(self, job_id: str) -> dict:
        """Resume a paused cron job."""
        # Get job data
        job_data = await redis.hgetall(f"cronjob:{job_id}")
        
        if not job_data or job_data.get("status") != "paused":
            return {"resumed": False, "reason": "Job not found or not paused"}
        
        # Calculate next run
        from croniter import croniter
        import pytz
        
        tz = pytz.timezone(job_data.get("timezone", "UTC"))
        cron = croniter(job_data["expression"], datetime.now(tz))
        next_run = cron.get_next(datetime)
        
        # Update job
        await redis.hset(f"cronjob:{job_id}", mapping={
            "status": "active",
            "next_run": next_run.isoformat()
        })
        
        # Move between sets
        await redis.srem("cronjobs:paused", job_id)
        await redis.sadd("cronjobs:active", job_id)
        
        # Schedule next execution
        workflow = json.loads(job_data["workflow"])
        await self.schedule_workflow(
            workflow=workflow,
            run_at=next_run,
            metadata={"cron_job_id": job_id}
        )
        
        return {
            "resumed": True,
            "job_id": job_id,
            "next_run": next_run.isoformat()
        }
```

### 2. Scheduler Monitor Service

```python
class SchedulerMonitor:
    """Background service that triggers scheduled executions."""
    
    def __init__(self):
        self.running = True
        self.check_interval = 1.0  # Check every second
    
    async def start(self):
        """Start the monitor service."""
        # Start multiple coroutines for different responsibilities
        await asyncio.gather(
            self.monitor_schedules(),
            self.monitor_cron_jobs(),
            self.process_events(),
            self.cleanup_expired()
        )
    
    async def monitor_schedules(self):
        """Monitor and execute due schedules."""
        while self.running:
            try:
                now = time.time()
                
                # Get schedules due for execution (with limit for batching)
                due_schedules = await redis.zrangebyscore(
                    "scheduler:pending",
                    "-inf",
                    now,
                    start=0,
                    num=100
                )
                
                # Process each due schedule
                for schedule_id in due_schedules:
                    asyncio.create_task(self.execute_schedule(schedule_id))
                
                await asyncio.sleep(self.check_interval)
                
            except Exception as e:
                logger.error(f"Schedule monitor error: {e}")
                await asyncio.sleep(5)
    
    async def execute_schedule(self, schedule_id: str):
        """Execute a scheduled workflow."""
        try:
            # Atomic operation: get and remove
            pipe = redis.pipeline()
            pipe.hgetall(f"schedule:{schedule_id}")
            pipe.zrem("scheduler:pending", schedule_id)
            schedule_data, removed = await pipe.execute()
            
            if not removed or not schedule_data:
                return  # Already processed
            
            # Parse workflow
            workflow = json.loads(schedule_data["workflow"])
            metadata = json.loads(schedule_data.get("metadata", "{}"))
            
            # Generate workflow instance ID
            workflow_id = f"{workflow.get('id', 'scheduled')}_{uuid.uuid4().hex[:8]}"
            workflow["id"] = workflow_id
            
            # Submit workflow via stream
            await redis.xadd("workflows:submit", {
                "workflow": json.dumps(workflow),
                "source": "scheduler",
                "schedule_id": schedule_id,
                "scheduled_at": schedule_data.get("run_at", "")
            })
            
            # Update schedule status
            await redis.hset(f"schedule:{schedule_id}", mapping={
                "status": "executed",
                "executed_at": datetime.utcnow().isoformat(),
                "workflow_id": workflow_id
            })
            
            # If this is from a cron job, schedule next execution
            if metadata.get("cron_job_id"):
                await self.schedule_next_cron_execution(metadata["cron_job_id"])
            
            # Log execution
            logger.info(f"Executed schedule {schedule_id} -> workflow {workflow_id}")
            
            # Set TTL for cleanup
            await redis.expire(f"schedule:{schedule_id}", 86400)  # 24 hours
            
        except Exception as e:
            logger.error(f"Failed to execute schedule {schedule_id}: {e}")
            
            # Re-add to pending if retriable
            await redis.zadd(
                "scheduler:pending",
                {schedule_id: time.time() + 60}  # Retry in 1 minute
            )
    
    async def schedule_next_cron_execution(self, job_id: str):
        """Schedule the next execution of a cron job."""
        try:
            # Get cron job data
            job_data = await redis.hgetall(f"cronjob:{job_id}")
            
            if not job_data or job_data.get("status") != "active":
                return
            
            # Calculate next run time
            from croniter import croniter
            import pytz
            
            tz = pytz.timezone(job_data.get("timezone", "UTC"))
            cron = croniter(job_data["expression"], datetime.now(tz))
            next_run = cron.get_next(datetime)
            
            # Update execution count
            exec_count = int(job_data.get("execution_count", 0)) + 1
            
            # Update cron job
            await redis.hset(f"cronjob:{job_id}", mapping={
                "next_run": next_run.isoformat(),
                "last_executed": datetime.utcnow().isoformat(),
                "execution_count": exec_count
            })
            
            # Schedule next execution
            workflow = json.loads(job_data["workflow"])
            
            schedule_id = f"cron:{job_id}:{exec_count}"
            await redis.zadd(
                "scheduler:pending",
                {schedule_id: next_run.timestamp()}
            )
            
            await redis.hset(f"schedule:{schedule_id}", mapping={
                "workflow": job_data["workflow"],
                "run_at": next_run.isoformat(),
                "status": "pending",
                "metadata": json.dumps({
                    "cron_job_id": job_id,
                    "cron_execution": exec_count
                })
            })
            
            logger.info(f"Scheduled next cron execution for {job_id} at {next_run}")
            
        except Exception as e:
            logger.error(f"Failed to schedule next cron execution for {job_id}: {e}")
    
    async def monitor_cron_jobs(self):
        """Ensure all active cron jobs have scheduled executions."""
        while self.running:
            try:
                # Get all active cron jobs
                active_jobs = await redis.smembers("cronjobs:active")
                
                for job_id in active_jobs:
                    job_data = await redis.hgetall(f"cronjob:{job_id}")
                    
                    if not job_data:
                        # Remove from active if doesn't exist
                        await redis.srem("cronjobs:active", job_id)
                        continue
                    
                    # Check if has pending execution
                    next_run = job_data.get("next_run")
                    if not next_run:
                        # Schedule if missing
                        await self.schedule_next_cron_execution(job_id)
                
                # Check less frequently
                await asyncio.sleep(60)  # Every minute
                
            except Exception as e:
                logger.error(f"Cron monitor error: {e}")
                await asyncio.sleep(60)
    
    async def process_events(self):
        """Process scheduler events stream."""
        last_id = "$"
        
        while self.running:
            try:
                # Read events from stream
                events = await redis.xread(
                    {"scheduler:events": last_id},
                    block=1000,  # Block for 1 second
                    count=10
                )
                
                for stream_name, messages in events:
                    for msg_id, data in messages:
                        await self.handle_event(data)
                        last_id = msg_id
                        
            except Exception as e:
                logger.error(f"Event processing error: {e}")
                await asyncio.sleep(5)
    
    async def handle_event(self, event_data: dict):
        """Handle scheduler events."""
        event_type = event_data.get("event")
        
        if event_type == "schedule_created":
            logger.info(f"New schedule created: {event_data.get('schedule_id')}")
            
        elif event_type == "schedule_cancelled":
            logger.info(f"Schedule cancelled: {event_data.get('schedule_id')}")
    
    async def cleanup_expired(self):
        """Clean up old executed schedules."""
        while self.running:
            try:
                # Clean up old schedule data (older than 7 days)
                cutoff = time.time() - (7 * 86400)
                
                # Get old executed schedules
                cursor = "0"
                while cursor != 0:
                    cursor, keys = await redis.scan(
                        cursor,
                        match="schedule:*",
                        count=100
                    )
                    
                    for key in keys:
                        data = await redis.hget(key, "executed_at")
                        if data:
                            exec_time = datetime.fromisoformat(data).timestamp()
                            if exec_time < cutoff:
                                await redis.delete(key)
                
                # Run cleanup daily
                await asyncio.sleep(86400)
                
            except Exception as e:
                logger.error(f"Cleanup error: {e}")
                await asyncio.sleep(86400)
```

### 3. Integration with API

```python
# In API routes
from fastapi import APIRouter, HTTPException
from datetime import datetime

router = APIRouter(prefix="/scheduler", tags=["scheduler"])
scheduler_api = SchedulerAPI()

@router.post("/schedule")
async def schedule_workflow(
    workflow: dict,
    run_at: datetime,
    metadata: dict = None
):
    """Schedule a workflow to run at a specific time."""
    try:
        result = await scheduler_api.schedule_workflow(
            workflow=workflow,
            run_at=run_at,
            metadata=metadata
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/cron")
async def create_cron_job(
    cron_expression: str,
    workflow: dict,
    job_name: str = None,
    timezone: str = "UTC"
):
    """Create a recurring cron job."""
    try:
        result = await scheduler_api.create_cron_job(
            cron_expression=cron_expression,
            workflow=workflow,
            job_name=job_name,
            timezone=timezone
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/schedule/{schedule_id}")
async def cancel_schedule(schedule_id: str):
    """Cancel a scheduled execution."""
    result = await scheduler_api.cancel_schedule(schedule_id)
    if not result["cancelled"]:
        raise HTTPException(status_code=404, detail=result["reason"])
    return result

@router.post("/cron/{job_id}/pause")
async def pause_cron_job(job_id: str):
    """Pause a cron job."""
    result = await scheduler_api.pause_cron_job(job_id)
    if not result["paused"]:
        raise HTTPException(status_code=404, detail=result["reason"])
    return result

@router.post("/cron/{job_id}/resume")
async def resume_cron_job(job_id: str):
    """Resume a paused cron job."""
    result = await scheduler_api.resume_cron_job(job_id)
    if not result["resumed"]:
        raise HTTPException(status_code=404, detail=result["reason"])
    return result

@router.get("/schedules")
async def list_schedules(status: str = "pending", limit: int = 100):
    """List scheduled executions."""
    if status == "pending":
        # Get from sorted set with scores (timestamps)
        schedules = await redis.zrange(
            "scheduler:pending",
            0,
            limit - 1,
            withscores=True
        )
        
        result = []
        for schedule_id, timestamp in schedules:
            data = await redis.hgetall(f"schedule:{schedule_id}")
            if data:
                result.append({
                    "schedule_id": schedule_id,
                    "run_at": datetime.fromtimestamp(timestamp).isoformat(),
                    "status": data.get("status", "pending")
                })
        
        return {"schedules": result, "count": len(result)}
    
    # For other statuses, would need to scan keys
    return {"schedules": [], "count": 0}

@router.get("/cron")
async def list_cron_jobs(status: str = "active"):
    """List cron jobs."""
    if status == "active":
        job_ids = await redis.smembers("cronjobs:active")
    elif status == "paused":
        job_ids = await redis.smembers("cronjobs:paused")
    else:
        # Get all
        active = await redis.smembers("cronjobs:active")
        paused = await redis.smembers("cronjobs:paused")
        job_ids = active.union(paused)
    
    jobs = []
    for job_id in job_ids:
        data = await redis.hgetall(f"cronjob:{job_id}")
        if data:
            jobs.append({
                "job_id": job_id,
                "name": data.get("name", job_id),
                "cron": data.get("expression"),
                "next_run": data.get("next_run"),
                "status": data.get("status"),
                "execution_count": int(data.get("execution_count", 0))
            })
    
    return {"jobs": jobs, "count": len(jobs)}
```

## Usage Examples

### Schedule a One-Time Workflow

```python
# Via API
import httpx
from datetime import datetime, timedelta

async with httpx.AsyncClient() as client:
    response = await client.post(
        "http://localhost:8000/scheduler/schedule",
        json={
            "workflow": {
                "id": "data-backup",
                "tasks": [
                    {
                        "id": "backup",
                        "protocol": "shell/v1",
                        "method": "exec",
                        "params": {
                            "command": "pg_dump mydb > backup.sql"
                        }
                    }
                ]
            },
            "run_at": (datetime.utcnow() + timedelta(hours=2)).isoformat(),
            "metadata": {"type": "backup", "database": "mydb"}
        }
    )
    print(f"Scheduled: {response.json()}")
```

### Create a Cron Job

```python
# Daily report at 9 AM
response = await client.post(
    "http://localhost:8000/scheduler/cron",
    json={
        "cron_expression": "0 9 * * *",
        "workflow": {
            "id": "daily-report",
            "tasks": [
                {
                    "id": "generate",
                    "protocol": "python/v1",
                    "method": "exec",
                    "params": {
                        "code": """
import datetime
print(f"Daily report for {datetime.date.today()}")
# Generate and send report
"""
                    }
                }
            ]
        },
        "job_name": "daily-sales-report",
        "timezone": "America/New_York"
    }
)
```

### Complex Scheduling Patterns

```python
# Every 30 minutes during business hours (9-5 Mon-Fri)
await client.post(
    "http://localhost:8000/scheduler/cron",
    json={
        "cron_expression": "*/30 9-17 * * 1-5",
        "workflow": {
            "id": "health-check",
            "tasks": [
                {
                    "id": "check",
                    "protocol": "python/v1",
                    "method": "exec",
                    "params": {
                        "code": "# Check system health"
                    }
                }
            ]
        },
        "job_name": "business-hours-health-check"
    }
)

# First Monday of every month at 10 AM
await client.post(
    "http://localhost:8000/scheduler/cron",
    json={
        "cron_expression": "0 10 1-7 * 1",
        "workflow": {
            "id": "monthly-cleanup",
            "tasks": [
                {
                    "id": "cleanup",
                    "protocol": "shell/v1",
                    "method": "exec",
                    "params": {
                        "command": "find /tmp -mtime +30 -delete"
                    }
                }
            ]
        },
        "job_name": "monthly-temp-cleanup"
    }
)
```

## Deployment

```yaml
# docker-compose.yml
version: '3.8'

services:
  scheduler-monitor:
    image: gleitzeit:latest
    command: ["python", "-m", "gleitzeit.scheduler.monitor"]
    environment:
      - REDIS_URL=redis://redis:6379
      - LOG_LEVEL=INFO
    deploy:
      replicas: 2  # Run 2 instances for HA
    restart: unless-stopped
    depends_on:
      - redis
```

## Benefits

1. **Fully Stateless**: Can restart anytime without losing schedules
2. **Scalable**: Multiple scheduler monitors can run concurrently
3. **Reliable**: Uses Redis persistence for durability
4. **Flexible**: Supports both one-time and recurring schedules
5. **Time Zone Aware**: Handles different time zones correctly
6. **Observable**: All operations logged and trackable via streams

This scheduler integrates seamlessly with the timer system to provide complete time-based workflow control in Gleitzeit.