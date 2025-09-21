# Timers and Schedulers for Gleitzeit

## Executive Summary

Timers and schedulers enable workflows to wait, delay, schedule future work, and handle time-based logic. This design shows how to implement Temporal-style timers using Redis sorted sets and key expiration, maintaining our stateless architecture while adding critical time-based capabilities.

**Key Benefits:**
- **Zero polling** - Redis keyspace notifications for efficiency
- **Millisecond precision** - Fine-grained timing control
- **Scalable to millions** - Redis sorted sets handle massive scale
- **Stateless execution** - No in-memory state required
- **Crash resilient** - Survives worker restarts

## Core Timer Patterns

### 1. Simple Sleep/Wait
```python
# Sleep for fixed duration
t("wait_before_retry", "timer/v1:sleep")
    .with_(seconds=60)

# Wait until specific time
t("wait_until_midnight", "timer/v1:wait_until")
    .with_(timestamp="2024-12-25T00:00:00Z")

# Wait with jitter (for load distribution)
t("wait_with_jitter", "timer/v1:sleep")
    .with_(seconds=60, jitter=10)  # 50-70 seconds
```

### 2. Inline Timer Syntax
```python
# Inline wait between tasks
t("send_email", "email/v1:send")
    .wait(60)  # Wait 60 seconds
    .run("send_followup", "email/v1:send")

# Conditional wait
t("process_order", "order/v1:process")
    .on_success()
        .wait(3600)  # Wait 1 hour
        .run("send_review_request", "email/v1:send")
```

### 3. Scheduled Tasks
```python
# Schedule future task
t("schedule_reminder", "scheduler/v1:schedule")
    .with_(
        run_at="2024-12-25T09:00:00Z",
        task="send_reminder",
        protocol="email/v1:send",
        params={"template": "holiday_greeting"}
    )

# Recurring schedules (cron-like)
t("schedule_daily_report", "scheduler/v1:cron")
    .with_(
        cron="0 9 * * *",  # Daily at 9 AM
        task="generate_report",
        protocol="reporting/v1:daily"
    )
```

### 4. Timeout Patterns
```python
# Task with timeout
t("call_external_api", "http/v1:get")
    .timeout(30)  # 30 second timeout
    .on_timeout()
        .run("use_cached_data", "cache/v1:get")

# Wait with timeout
t("wait_for_payment", "timer/v1:wait")
    .with_(seconds=3600)
    .or_signal("payment_received")  # Wake on signal OR timeout
    .on_timeout()
        .run("cancel_order", "order/v1:cancel")
```

### 5. Deadline Management
```python
# Workflow with deadline
workflow = w(
    t("process_application", "application/v1:process")
        .deadline("2024-12-31T23:59:59Z")  # Must complete by year end
        .on_deadline_exceeded()
            .run("escalate", "escalation/v1:create")
)

# SLA tracking
t("handle_support_ticket", "support/v1:process")
    .sla(hours=4)  # 4-hour SLA
    .on_sla_warning(percent=75)  # At 3 hours
        .run("notify_manager", "slack/v1:send")
    .on_sla_breach()
        .run("escalate_critical", "pagerduty/v1:alert")
```

## Implementation Architecture

### Timer Storage in Redis

```python
# Sorted set for scheduled tasks (score = timestamp)
timers:scheduled = ZSET {
    "workflow:123:task:456": 1704096000,  # Unix timestamp
    "workflow:789:task:012": 1704096060,
}

# Timer metadata
timer:workflow:123:task:456 = HASH {
    "workflow_id": "123",
    "task_id": "456", 
    "type": "sleep",
    "duration": 60,
    "created_at": "2024-01-01T11:59:00Z",
    "wake_at": "2024-01-01T12:00:00Z",
    "jitter": 0
}

# Recurring schedules
scheduler:cron = HASH {
    "daily_report": {
        "cron": "0 9 * * *",
        "task": "generate_report",
        "protocol": "reporting/v1:daily",
        "last_run": "2024-01-01T09:00:00Z",
        "next_run": "2024-01-02T09:00:00Z"
    }
}
```

### Timer Processing Approaches

#### Option 1: Redis Keyspace Notifications (Recommended)
```python
# Use Redis key expiration for timer events
async def setup_timer(task_id: str, seconds: int):
    # Set expiring key
    await redis.setex(
        f"timer:expire:{task_id}",
        seconds,
        "1"
    )
    
    # Also add to sorted set for recovery
    await redis.zadd(
        "timers:scheduled",
        {task_id: time.time() + seconds}
    )

# Subscribe to expiration events
async def timer_processor():
    pubsub = redis.pubsub()
    await pubsub.subscribe("__keyevent@0__:expired")
    
    async for message in pubsub.listen():
        if message["channel"] == "__keyevent@0__:expired":
            key = message["data"]
            if key.startswith("timer:expire:"):
                task_id = key.replace("timer:expire:", "")
                await wake_task(task_id)
```

#### Option 2: Sorted Set Polling (Fallback)
```python
# Efficient polling using sorted sets
async def timer_poller():
    while True:
        # Get all timers due in next second
        now = time.time()
        due_timers = await redis.zrangebyscore(
            "timers:scheduled",
            0,
            now,
            withscores=True
        )
        
        for task_id, score in due_timers:
            # Process timer
            await wake_task(task_id)
            
            # Remove from set
            await redis.zrem("timers:scheduled", task_id)
        
        # Sleep briefly (100ms for responsiveness)
        await asyncio.sleep(0.1)
```

#### Option 3: Hybrid Approach (Best of Both)
```python
class TimerService:
    """Hybrid timer using both notifications and polling"""
    
    async def start(self):
        # Primary: Keyspace notifications
        asyncio.create_task(self.notification_processor())
        
        # Backup: Periodic sweep for missed timers
        asyncio.create_task(self.recovery_poller())
    
    async def notification_processor(self):
        """Primary timer mechanism"""
        # Subscribe to Redis expiration events
        # Process immediately when keys expire
    
    async def recovery_poller(self):
        """Backup mechanism for missed timers"""
        while True:
            # Check every 5 seconds for overdue timers
            await self.process_overdue_timers()
            await asyncio.sleep(5)
    
    async def schedule_timer(self, task_id: str, wake_at: float):
        """Schedule a timer"""
        seconds = max(1, int(wake_at - time.time()))
        
        # Set expiring key (primary)
        await redis.setex(f"timer:expire:{task_id}", seconds, "1")
        
        # Add to sorted set (backup)
        await redis.zadd("timers:scheduled", {task_id: wake_at})
        
        # Store metadata
        await redis.hset(f"timer:{task_id}", {
            "wake_at": wake_at,
            "task_id": task_id,
            "status": "waiting"
        })
```

## Timer Task Protocol

```python
class TimerProtocol:
    """timer/v1 protocol for time operations"""
    
    async def sleep(self, seconds: int, jitter: int = 0) -> None:
        """Sleep for specified duration"""
        actual_seconds = seconds
        if jitter:
            actual_seconds += random.randint(-jitter, jitter)
        
        task_id = context.current_task_id
        wake_at = time.time() + actual_seconds
        
        # Schedule wake-up
        await timer_service.schedule_timer(task_id, wake_at)
        
        # Mark task as sleeping
        await redis.hset(f"task:{task_id}", "status", "sleeping")
        
        # Suspend execution (will resume when timer fires)
        raise TaskSleeping(wake_at)
    
    async def wait_until(self, timestamp: str) -> None:
        """Wait until specific time"""
        target = datetime.fromisoformat(timestamp)
        seconds = (target - datetime.utcnow()).total_seconds()
        
        if seconds <= 0:
            return  # Already past
        
        await self.sleep(int(seconds))
    
    async def wait_or_signal(self, seconds: int, signal: str) -> str:
        """Wait for timer OR signal, whichever comes first"""
        task_id = context.current_task_id
        
        # Set up timer
        await self.sleep(seconds)
        
        # Also listen for signal
        await redis.lpush(f"signal:waiters:{signal}", task_id)
        
        # Return what woke us
        return await redis.hget(f"task:{task_id}", "wake_reason")
```

## Scheduler Implementation

```python
class SchedulerProtocol:
    """scheduler/v1 protocol for scheduled tasks"""
    
    async def schedule(
        self,
        run_at: str,
        task: str,
        protocol: str,
        params: Dict = None
    ) -> str:
        """Schedule future task execution"""
        scheduled_id = f"scheduled_{uuid.uuid4()}"
        timestamp = datetime.fromisoformat(run_at).timestamp()
        
        # Store scheduled task
        await redis.hset(f"scheduled:{scheduled_id}", {
            "task": task,
            "protocol": protocol,
            "params": json.dumps(params or {}),
            "run_at": run_at,
            "workflow_id": context.workflow_id
        })
        
        # Add to timer queue
        await redis.zadd("timers:scheduled", {scheduled_id: timestamp})
        
        return scheduled_id
    
    async def cron(
        self,
        cron: str,
        task: str,
        protocol: str,
        params: Dict = None
    ) -> str:
        """Schedule recurring task"""
        cron_id = f"cron_{uuid.uuid4()}"
        
        # Parse cron expression
        cron_schedule = croniter(cron)
        next_run = cron_schedule.get_next(datetime)
        
        # Store cron job
        await redis.hset(f"cron:{cron_id}", {
            "cron": cron,
            "task": task,
            "protocol": protocol,
            "params": json.dumps(params or {}),
            "next_run": next_run.isoformat(),
            "workflow_id": context.workflow_id
        })
        
        # Schedule next execution
        await self.schedule(
            run_at=next_run.isoformat(),
            task=f"cron_executor_{cron_id}",
            protocol="scheduler/v1:execute_cron",
            params={"cron_id": cron_id}
        )
        
        return cron_id
    
    async def cancel(self, scheduled_id: str) -> bool:
        """Cancel scheduled task"""
        # Remove from timer queue
        removed = await redis.zrem("timers:scheduled", scheduled_id)
        
        # Delete metadata
        await redis.delete(f"scheduled:{scheduled_id}")
        
        return removed > 0
```

## Real-World Examples

### 1. Retry with Exponential Backoff
```python
retry_workflow = w(
    t("api_call", "http/v1:post")
        .with_(url="${config.api_url}")
        .on_error("RATE_LIMITED")
            .wait("${2 ** retry_count}")  # Exponential backoff
            .retry_self()
        .max_retries(5)
)
```

### 2. Payment Processing with Grace Period
```python
payment_workflow = w(
    t("charge_payment", "payment/v1:charge")
        .with_(amount="${order.total}")
        .on_error("INSUFFICIENT_FUNDS")
            .run("notify_customer", "email/v1:send")
            .wait(86400)  # 24 hour grace period
            .run("retry_payment", "payment/v1:charge")
            .on_error()
                .run("suspend_account", "account/v1:suspend")
)
```

### 3. Scheduled Reports
```python
reporting_workflow = w(
    t("schedule_reports", "scheduler/v1:setup")
        .run("daily_report", "scheduler/v1:cron")
            .with_(
                cron="0 9 * * *",
                task="generate_daily",
                protocol="reports/v1:daily"
            )
        .run("weekly_summary", "scheduler/v1:cron")
            .with_(
                cron="0 9 * * MON",
                task="generate_weekly",
                protocol="reports/v1:weekly"
            )
        .run("monthly_analysis", "scheduler/v1:cron")
            .with_(
                cron="0 9 1 * *",
                task="generate_monthly",
                protocol="reports/v1:monthly"
            )
)
```

### 4. SLA Management
```python
sla_workflow = w(
    t("receive_ticket", "support/v1:create")
        .with_(ticket="${input.ticket}"),
    
    t("start_sla_timer", "timer/v1:start_sla")
        .needs("receive_ticket")
        .with_(sla_hours=4),
    
    t("process_ticket", "support/v1:process")
        .needs("receive_ticket")
        .deadline_from("start_sla_timer", hours=4)
        .on_deadline_warning(percent=50)  # At 2 hours
            .run("notify_agent", "slack/v1:send")
            .with_(message="SLA 50% consumed")
        .on_deadline_warning(percent=75)  # At 3 hours
            .run("notify_manager", "slack/v1:send")
            .with_(message="SLA 75% consumed")
        .on_deadline_exceeded()
            .run("escalate", "pagerduty/v1:alert")
            .with_(priority="critical")
)
```

### 5. Timeout with Fallback
```python
resilient_workflow = w(
    t("call_primary_api", "http/v1:get")
        .with_(url="${config.primary_url}")
        .timeout(5)  # 5 second timeout
        .on_timeout()
            .run("call_backup_api", "http/v1:get")
            .with_(url="${config.backup_url}")
            .timeout(5)
            .on_timeout()
                .run("use_cached_data", "cache/v1:get")
                .with_(key="${cache.key}")
)
```

## Scalability Considerations

### 1. Timer Distribution
```python
class DistributedTimerService:
    """Distributed timer processing across workers"""
    
    def __init__(self, worker_id: str, total_workers: int):
        self.worker_id = worker_id
        self.total_workers = total_workers
    
    async def should_process(self, timer_id: str) -> bool:
        """Consistent hashing for timer distribution"""
        hash_value = hashlib.md5(timer_id.encode()).hexdigest()
        assigned_worker = int(hash_value, 16) % self.total_workers
        return assigned_worker == self.worker_id
    
    async def process_timers(self):
        """Process only assigned timers"""
        while True:
            timers = await redis.zrangebyscore(
                "timers:scheduled",
                0,
                time.time()
            )
            
            for timer_id in timers:
                if await self.should_process(timer_id):
                    await self.wake_task(timer_id)
```

### 2. Batch Timer Processing
```python
async def batch_timer_processor():
    """Process timers in batches for efficiency"""
    while True:
        # Get batch of due timers
        pipe = redis.pipeline()
        now = time.time()
        
        # Atomic get and remove
        timers = await redis.eval("""
            local timers = redis.call('zrangebyscore', 
                'timers:scheduled', 0, ARGV[1], 'LIMIT', 0, 100)
            if #timers > 0 then
                redis.call('zrem', 'timers:scheduled', unpack(timers))
            end
            return timers
        """, 0, now)
        
        # Process batch
        if timers:
            tasks = []
            for timer_id in timers:
                tasks.append(wake_task(timer_id))
            await asyncio.gather(*tasks)
        
        await asyncio.sleep(0.1)
```

### 3. Timer Sharding
```python
# Shard timers across multiple Redis sorted sets
def get_timer_shard(timer_id: str, num_shards: int = 16) -> str:
    shard = hashlib.md5(timer_id.encode()).hexdigest()
    shard_num = int(shard, 16) % num_shards
    return f"timers:scheduled:{shard_num}"

# Each worker processes subset of shards
async def process_timer_shards(worker_id: int, total_workers: int):
    num_shards = 16
    my_shards = [
        s for s in range(num_shards) 
        if s % total_workers == worker_id
    ]
    
    for shard in my_shards:
        asyncio.create_task(
            process_timer_shard(f"timers:scheduled:{shard}")
        )
```

## Performance Optimization

### 1. Near-term Timer Caching
```python
class TimerCache:
    """Cache near-term timers in memory"""
    
    def __init__(self, horizon_seconds: int = 60):
        self.horizon = horizon_seconds
        self.cached_timers = []
        self.last_fetch = 0
    
    async def get_due_timers(self) -> List[str]:
        now = time.time()
        
        # Refresh cache if needed
        if now - self.last_fetch > 10:  # Refresh every 10s
            future = now + self.horizon
            self.cached_timers = await redis.zrangebyscore(
                "timers:scheduled",
                now,
                future,
                withscores=True
            )
            self.last_fetch = now
        
        # Return due timers from cache
        due = []
        for timer_id, wake_at in self.cached_timers:
            if wake_at <= now:
                due.append(timer_id)
        
        return due
```

### 2. Coalescing Similar Timers
```python
async def coalesce_timers(timers: List[Dict], window: int = 1):
    """Coalesce timers within window to reduce wake-ups"""
    buckets = {}
    
    for timer in timers:
        # Round to nearest window
        bucket = (timer["wake_at"] // window) * window
        if bucket not in buckets:
            buckets[bucket] = []
        buckets[bucket].append(timer)
    
    # Schedule one wake-up per bucket
    for bucket_time, bucket_timers in buckets.items():
        await redis.zadd(
            "timers:coalesced",
            {json.dumps(bucket_timers): bucket_time}
        )
```

## Monitoring and Observability

```python
# Timer metrics
timer_metrics = {
    "timers.scheduled": "gauge",     # Number of pending timers
    "timers.fired": "counter",       # Timers that fired
    "timers.late": "counter",        # Timers fired late
    "timers.latency": "histogram",   # Timer accuracy
    "scheduler.jobs": "gauge",       # Scheduled jobs
    "scheduler.cron": "gauge",       # Active cron jobs
}

async def emit_timer_metrics():
    """Emit timer metrics"""
    pending = await redis.zcard("timers:scheduled")
    metrics.gauge("timers.scheduled", pending)
    
    # Check timer accuracy
    for timer_id in recently_fired:
        scheduled = await redis.hget(f"timer:{timer_id}", "wake_at")
        actual = time.time()
        latency = actual - float(scheduled)
        metrics.histogram("timers.latency", latency)
        
        if latency > 1:  # More than 1s late
            metrics.increment("timers.late")
```

## Comparison with Temporal

| Feature | Temporal | Gleitzeit (with Timers) |
|---------|----------|------------------------|
| Sleep/Wait | ✅ workflow.Sleep() | ✅ timer/v1:sleep |
| Timers | ✅ workflow.NewTimer() | ✅ timer/v1:wait |
| Scheduled Actions | ✅ StartWorkflowOptions.CronSchedule | ✅ scheduler/v1:cron |
| Timeout | ✅ Context timeout | ✅ .timeout() |
| Deadline | ✅ WorkflowOptions.WorkflowRunTimeout | ✅ .deadline() |
| Timer Cancellation | ✅ timer.Cancel() | ✅ scheduler/v1:cancel |
| Timer Queries | ✅ Via workflow state | ✅ Via Redis |
| Durable Timers | ✅ Yes | ✅ Yes (Redis) |
| Sub-second Precision | ✅ Yes | ✅ Yes (ms precision) |
| Scale | ✅ Millions | ✅ Millions (Redis sorted sets) |

## Implementation Timeline

### Day 1: Core Timer Infrastructure (8 hours)
- Timer protocol implementation
- Redis keyspace notification setup
- Basic sleep/wait functionality
- Timer service with hybrid approach

### Day 2: Scheduler & Advanced Features (8 hours)
- Scheduler protocol
- Cron support
- SLA/deadline tracking
- Timer coalescing and optimization

### Day 3: Integration & Testing (8 hours)
- Inline syntax support
- Timeout handlers
- Scale testing
- Monitoring setup

## Conclusion

Timers and schedulers can be efficiently implemented in Gleitzeit using:
- **Redis sorted sets** for scalable timer storage
- **Keyspace notifications** for efficient wake-ups
- **Hybrid approach** for reliability
- **Sharding** for horizontal scale
- **Stateless design** maintained throughout

This adds critical time-based capabilities while preserving our core architectural principles. The implementation is efficient, scalable to millions of timers, and provides all the timer features needed for enterprise workflows.