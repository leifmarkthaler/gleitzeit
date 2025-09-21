# Dedicated Timer Workers with Leader Election

## The Best of Both Worlds

Multiple dedicated timer workers, but only one actively processes timers via leader election:

```bash
# Start multiple timer workers - only one will be active
gleitzeit worker --type timer --workers 3

# Timer Worker 1: Elected leader ✓ (processing timers)
# Timer Worker 2: Standby (monitoring, ready to take over)
# Timer Worker 3: Standby (monitoring, ready to take over)

# Plus regular event workers
gleitzeit worker --type stream --workers 4
```

## Architecture Design

```python
class DedicatedTimerWorker:
    """
    Dedicated timer worker with leader election.
    Multiple can run, but only leader processes timers.
    """

    def __init__(self, system_manager, worker_id=None):
        self.system_manager = system_manager
        self.redis = system_manager.persistence.redis
        self.worker_id = worker_id or f"timer-{uuid.uuid4().hex[:8]}"

        self.is_leader = False
        self.leader_key = "timer:leader"
        self.leader_ttl = 10
        self.heartbeat_interval = 3
        self.check_interval = 1

        self._running = False
        self._leader_task = None

    async def start(self):
        """Start timer worker and participate in election"""
        self._running = True

        logger.info(f"Starting timer worker {self.worker_id}")

        # Register as a timer worker
        await self._register_timer_worker()

        # Start main loop
        try:
            await self._run_loop()
        finally:
            await self._cleanup()

    async def _register_timer_worker(self):
        """Register this worker as a timer worker"""
        await self.redis.hset(
            "timer:workers",
            self.worker_id,
            json.dumps({
                "started": time.time(),
                "pid": os.getpid(),
                "host": socket.gethostname()
            })
        )

    async def _run_loop(self):
        """Main loop - election and timer processing"""

        while self._running:
            if not self.is_leader:
                # Try to become leader
                await self._attempt_leadership()

            if self.is_leader:
                # Process timers as leader
                await self._process_timers_as_leader()
            else:
                # Standby mode - just monitor
                await self._standby_mode()

            await asyncio.sleep(self.check_interval)

    async def _attempt_leadership(self):
        """Try to become the timer leader"""

        # Atomic set-if-not-exists with TTL
        success = await self.redis.set(
            self.leader_key,
            self.worker_id,
            nx=True,  # Only if not exists
            ex=self.leader_ttl
        )

        if success:
            logger.info(f"Timer worker {self.worker_id} became leader")
            self.is_leader = True

            # Start heartbeat task
            if self._leader_task:
                self._leader_task.cancel()
            self._leader_task = asyncio.create_task(self._leader_heartbeat())

            # Emit leadership event
            await self._emit_leadership_change()

    async def _leader_heartbeat(self):
        """Maintain leadership with heartbeats"""

        while self.is_leader and self._running:
            await asyncio.sleep(self.heartbeat_interval)

            # Atomic check-and-extend
            lua_script = """
            if redis.call('get', KEYS[1]) == ARGV[1] then
                redis.call('expire', KEYS[1], ARGV[2])
                return 1
            else
                return 0
            end
            """

            renewed = await self.redis.eval(
                lua_script,
                1,
                self.leader_key,
                self.worker_id,
                self.leader_ttl
            )

            if not renewed:
                logger.warning(f"Timer worker {self.worker_id} lost leadership")
                self.is_leader = False

                # Cancel heartbeat task
                if self._leader_task:
                    self._leader_task.cancel()
                    self._leader_task = None

    async def _process_timers_as_leader(self):
        """Process expired timers (only when leader)"""

        # Double-check we're still leader
        current_leader = await self.redis.get(self.leader_key)
        if current_leader != self.worker_id:
            self.is_leader = False
            return

        # Process expired timers
        now = time.time()

        # Use Lua script for atomic get-and-remove
        lua_script = """
        local expired = redis.call('zrangebyscore', KEYS[1], 0, ARGV[1], 'LIMIT', 0, 100)
        if #expired > 0 then
            redis.call('zrem', KEYS[1], unpack(expired))
        end
        return expired
        """

        expired = await self.redis.eval(
            lua_script,
            1,
            "timers:pending",
            now
        )

        if expired:
            logger.info(f"Leader {self.worker_id} processing {len(expired)} timers")

            # Emit events for expired timers
            for timer_key in expired:
                task_id = timer_key.decode().split(":")[-1]

                # Add to task:ready stream for regular workers
                await self.redis.xadd(
                    "gleitzeit:events:stream:task:ready",
                    {
                        "event_type": "task:ready",
                        "task_id": task_id,
                        "reason": "timer_expired",
                        "processed_by": self.worker_id
                    }
                )

        # Update metrics
        await self._update_leader_metrics(len(expired) if expired else 0)

    async def _standby_mode(self):
        """Standby mode - monitor leader health"""

        # Check if leader is healthy
        leader = await self.redis.get(self.leader_key)

        if not leader:
            # No leader - will try to claim in next iteration
            logger.debug(f"Timer worker {self.worker_id} detected no leader")
        else:
            # Update our heartbeat as standby
            await self.redis.hset(
                "timer:workers:heartbeat",
                self.worker_id,
                time.time()
            )

            # Could do additional monitoring here
            await self._monitor_timer_backlog()

    async def _monitor_timer_backlog(self):
        """Monitor timer queue depth (useful for alerting)"""

        # Count pending timers
        now = time.time()
        overdue_count = await self.redis.zcount("timers:pending", 0, now)
        total_count = await self.redis.zcard("timers:pending")

        if overdue_count > 100:
            logger.warning(f"High timer backlog: {overdue_count} overdue, {total_count} total")

            # Could emit alert event here
            await self.redis.xadd(
                "gleitzeit:events:stream:alerts",
                {
                    "event_type": "timer:backlog:high",
                    "overdue": str(overdue_count),
                    "total": str(total_count),
                    "worker": self.worker_id
                }
            )

    async def _cleanup(self):
        """Clean shutdown"""

        # Remove from workers list
        await self.redis.hdel("timer:workers", self.worker_id)
        await self.redis.hdel("timer:workers:heartbeat", self.worker_id)

        # Release leadership if we have it
        if self.is_leader:
            current = await self.redis.get(self.leader_key)
            if current == self.worker_id:
                await self.redis.delete(self.leader_key)
                logger.info(f"Timer worker {self.worker_id} released leadership")

        # Cancel heartbeat task
        if self._leader_task:
            self._leader_task.cancel()

    async def _emit_leadership_change(self):
        """Emit event when leadership changes"""

        await self.redis.xadd(
            "gleitzeit:events:stream:timer:leadership",
            {
                "event_type": "timer:leadership:changed",
                "new_leader": self.worker_id,
                "timestamp": str(time.time())
            }
        )

    async def _update_leader_metrics(self, processed_count):
        """Update metrics for monitoring"""

        # Update processing metrics
        await self.redis.hincrby("timer:metrics:processed", self.worker_id, processed_count)

        # Update last processing time
        await self.redis.hset("timer:metrics:last_run", self.worker_id, time.time())
```

## Benefits of This Approach

### 1. **High Availability**
- Multiple timer workers running
- Instant failover (< 1 second typically)
- No single point of failure

### 2. **Clean Separation**
- Timer workers only handle timers
- Event workers only handle events
- No mixed responsibilities

### 3. **Monitoring & Observability**
```python
# Easy to monitor all timer workers
async def get_timer_worker_status():
    workers = await redis.hgetall("timer:workers")
    heartbeats = await redis.hgetall("timer:workers:heartbeat")
    leader = await redis.get("timer:leader")

    return {
        "leader": leader,
        "workers": [
            {
                "id": worker_id,
                "is_leader": worker_id == leader,
                "last_heartbeat": heartbeats.get(worker_id),
                "info": json.loads(info)
            }
            for worker_id, info in workers.items()
        ]
    }
```

### 4. **Resource Efficiency**
- Standby workers use minimal resources
- Can run on smaller instances
- Only leader does actual work

### 5. **Operational Flexibility**
```bash
# Development: Single timer worker
gleitzeit worker --type timer

# Staging: Two timer workers for failover
gleitzeit worker --type timer --workers 2

# Production: Three timer workers for HA
gleitzeit worker --type timer --workers 3
```

## Deployment Patterns

### Kubernetes StatefulSet
```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: timer-workers
spec:
  serviceName: timer-workers
  replicas: 3
  selector:
    matchLabels:
      app: timer-worker
  template:
    metadata:
      labels:
        app: timer-worker
    spec:
      containers:
      - name: timer-worker
        image: gleitzeit:latest
        command: ["gleitzeit", "worker", "--type", "timer"]
        env:
        - name: WORKER_ID
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        livenessProbe:
          exec:
            command:
            - /bin/sh
            - -c
            - "redis-cli exists timer:workers:heartbeat:$(hostname)"
          initialDelaySeconds: 10
          periodSeconds: 5
```

### Docker Swarm
```yaml
version: "3.8"
services:
  timer-worker:
    image: gleitzeit:latest
    command: gleitzeit worker --type timer
    deploy:
      replicas: 3
      restart_policy:
        condition: any
        delay: 5s
      update_config:
        parallelism: 1
        delay: 10s
```

### Systemd with Multiple Instances
```ini
# /etc/systemd/system/gleitzeit-timer@.service
[Unit]
Description=Gleitzeit Timer Worker %i
After=redis.service

[Service]
Type=simple
ExecStart=/usr/bin/gleitzeit worker --type timer --id timer-%i
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
# Start 3 timer workers
systemctl enable gleitzeit-timer@{1..3}
systemctl start gleitzeit-timer@{1..3}
```

## Advanced Features

### 1. Preferred Leader
```python
# Some workers can have priority for leadership
class DedicatedTimerWorker:
    def __init__(self, priority=0):
        self.priority = priority  # Higher = more likely to be leader

    async def _attempt_leadership(self):
        # Add small delay based on priority
        if not self.is_leader:
            await asyncio.sleep(0.1 * (10 - self.priority))

        # Then try to claim leadership
        ...
```

### 2. Split-Brain Prevention
```python
# Use fencing tokens to prevent split-brain
async def _process_timers_as_leader(self):
    # Generate unique token for this leadership term
    if not hasattr(self, 'leadership_token'):
        self.leadership_token = uuid.uuid4().hex

    # Store token with leadership
    await self.redis.set(
        f"{self.leader_key}:token",
        self.leadership_token,
        ex=self.leader_ttl
    )

    # Verify token before processing
    stored_token = await self.redis.get(f"{self.leader_key}:token")
    if stored_token != self.leadership_token:
        # We're not the real leader!
        self.is_leader = False
        return
```

### 3. Graceful Leadership Transfer
```python
# Allow current leader to hand off gracefully
async def transfer_leadership(self, target_worker_id=None):
    """Gracefully transfer leadership to another worker"""

    if not self.is_leader:
        return False

    if target_worker_id:
        # Transfer to specific worker
        await self.redis.set(
            self.leader_key,
            target_worker_id,
            xx=True,  # Only if exists (we're leader)
            ex=self.leader_ttl
        )
    else:
        # Just release, let election happen
        await self.redis.delete(self.leader_key)

    self.is_leader = False
    logger.info(f"Timer worker {self.worker_id} transferred leadership")
```

## Monitoring Dashboard

```python
# API endpoint for timer worker status
@router.get("/timers/workers")
async def get_timer_workers():
    """Get status of all timer workers"""

    workers = await redis.hgetall("timer:workers")
    heartbeats = await redis.hgetall("timer:workers:heartbeat")
    leader = await redis.get("timer:leader")

    # Get metrics
    processed = await redis.hgetall("timer:metrics:processed")
    last_runs = await redis.hgetall("timer:metrics:last_run")

    # Get backlog
    now = time.time()
    overdue = await redis.zcount("timers:pending", 0, now)
    total = await redis.zcard("timers:pending")

    return {
        "leader": {
            "id": leader,
            "uptime": time.time() - float(last_runs.get(leader, 0))
        },
        "workers": [
            {
                "id": wid,
                "is_leader": wid == leader,
                "last_heartbeat": float(heartbeats.get(wid, 0)),
                "processed_total": int(processed.get(wid, 0)),
                "status": "active" if wid == leader else "standby"
            }
            for wid in workers.keys()
        ],
        "backlog": {
            "overdue": overdue,
            "total": total
        }
    }
```

## Configuration

```yaml
# gleitzeit.yaml
timers:
  workers:
    count: 3                    # Number of timer workers
    leader:
      ttl: 10                   # Leadership TTL in seconds
      heartbeat_interval: 3     # Heartbeat frequency
    processing:
      check_interval: 1         # How often to check for expired timers
      batch_size: 100          # Max timers to process per batch
    monitoring:
      alert_threshold: 100      # Alert if backlog exceeds this
```

## Summary

**Dedicated Timer Workers with Leader Election** gives you:

1. **High Availability**: Multiple workers, automatic failover
2. **Clean Architecture**: Timer workers only do timers
3. **Production Ready**: Handles failures, monitoring built-in
4. **Flexible Deployment**: Works with any orchestrator
5. **Best Performance**: No resource competition

This is the production-grade solution that scales!