# Embedded vs Leader Election for Timer Checking

## Embedded Timer Checking

Every worker checks timers as part of its normal loop:

```python
class StreamWorker:
    async def _consume_loop(self):
        while self._running:
            # Check timers every second
            now = time.time()
            if now - self.last_timer_check >= 1:
                await self._check_expired_timers()
                self.last_timer_check = now

            # Normal event consumption
            messages = await self.redis.xreadgroup(...)
```

### Pros
- **Dead simple** - just add timer check to existing loop
- **No coordination** - workers are independent
- **Natural failover** - if a worker dies, others continue
- **Load distribution** - each worker handles some timers

### Cons
- **Duplicate processing** - multiple workers might process same timer
- **Inefficient** - all workers polling Redis for timers
- **Inconsistent timing** - depends on worker load
- **Resource waste** - N workers all checking timers

### Duplicate Processing Problem
```
Worker 1: Checks at T=1.00, finds timer-A expired, processes it
Worker 2: Checks at T=1.01, finds timer-A (not yet removed), processes it again!
```

**Solution**: Use Redis transactions or Lua scripts:
```python
# Atomic check-and-remove
async def _check_expired_timers(self):
    lua_script = """
    local expired = redis.call('zrangebyscore', KEYS[1], 0, ARGV[1], 'LIMIT', 0, 10)
    for i, timer in ipairs(expired) do
        redis.call('zrem', KEYS[1], timer)
    end
    return expired
    """
    expired = await self.redis.eval(lua_script, 1, "timers:pending", time.time())
    # Now process without duplicates
```

## Leader Election

One worker becomes the timer leader:

```python
class StreamWorker:
    async def start(self):
        # Try to become timer leader
        await self._attempt_leader_election()

        # Start normal consumption
        await self._consume_loop()

    async def _attempt_leader_election(self):
        # Atomic set-if-not-exists with TTL
        success = await self.redis.set(
            "timer:leader",
            self.worker_id,
            nx=True,  # Only if not exists
            ex=10     # Expire in 10 seconds
        )

        if success:
            self.is_timer_leader = True
            # Start heartbeat to maintain leadership
            asyncio.create_task(self._maintain_leadership())

    async def _maintain_leadership(self):
        while self.is_timer_leader and self._running:
            # Renew lease before expiry
            await asyncio.sleep(5)

            # Atomic check-and-extend
            lua_script = """
            if redis.call('get', KEYS[1]) == ARGV[1] then
                return redis.call('expire', KEYS[1], ARGV[2])
            else
                return 0
            end
            """
            renewed = await self.redis.eval(
                lua_script, 1, "timer:leader", self.worker_id, 10
            )

            if not renewed:
                # Lost leadership
                self.is_timer_leader = False
                # Try to reclaim
                await self._attempt_leader_election()

    async def _consume_loop(self):
        while self._running:
            # Only check timers if we're leader
            if self.is_timer_leader:
                now = time.time()
                if now - self.last_timer_check >= 1:
                    await self._check_all_timers()  # Check ALL timers
                    self.last_timer_check = now

            # Everyone processes events
            messages = await self.redis.xreadgroup(...)
```

### Pros
- **No duplicates** - only leader checks timers
- **Efficient** - single point of timer checking
- **Consistent** - predictable timer processing
- **Automatic failover** - new leader elected on failure

### Cons
- **More complex** - election and heartbeat logic
- **Single point** - all timer load on one worker
- **Election storms** - multiple workers competing
- **Lease renewal overhead** - constant heartbeats

### Leader Failure Scenarios

#### Graceful Shutdown
```
Leader: Releases lock explicitly
Others: One immediately takes over
Downtime: ~0ms
```

#### Crash/Network Partition
```
Leader: Disappears, lock expires after 10s
Others: Detect expired lock, elect new leader
Downtime: Up to 10s (lock TTL)
```

#### Split Brain Prevention
```python
# Use fencing token to prevent split brain
async def _check_all_timers(self):
    # Verify we're still leader before processing
    current_leader = await self.redis.get("timer:leader")
    if current_leader != self.worker_id:
        self.is_timer_leader = False
        return

    # Safe to process timers
    ...
```

## Hybrid Approach: Distributed with Partitioning

Each worker owns a partition of timers:

```python
class StreamWorker:
    def __init__(self, system_manager, worker_id=None):
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.worker_num = self._extract_worker_number()  # 0, 1, 2, 3...
        self.total_workers = self._get_total_workers()

    async def _check_expired_timers(self):
        # Only check timers that hash to our partition
        all_timers = await self.redis.zrangebyscore("timers:pending", 0, time.time())

        my_timers = [
            t for t in all_timers
            if hash(t) % self.total_workers == self.worker_num
        ]

        for timer in my_timers:
            # Process timer
            ...
```

### Pros
- **No duplicates** - partitioned by hash
- **Load balanced** - work distributed evenly
- **No coordination** - workers independent
- **Scalable** - add more workers for more timers

### Cons
- **Fixed partitions** - need to know total workers
- **Rebalancing** - complex when workers join/leave
- **Hash collisions** - possible uneven distribution

## Performance Comparison

| Approach | Timer Check Overhead | Duplicate Risk | Failover Time | Complexity |
|----------|---------------------|----------------|---------------|------------|
| Embedded | N × O(log T) | High (needs Lua) | Instant | Low |
| Leader Election | 1 × O(T) | None | 0-10 seconds | Medium |
| Partitioned | N × O(T/N) | None | Instant | High |

Where:
- N = number of workers
- T = number of pending timers

## Recommendation

**Use Leader Election** for production because:

1. **Correctness**: No duplicate timer processing
2. **Efficiency**: Single worker checks all timers
3. **Simplicity**: Clear ownership model
4. **Reliability**: Automatic failover with bounded delay
5. **Observability**: Easy to monitor who's leader

**Use Embedded** for development/testing because:
1. **Quick setup**: No coordination logic
2. **Simple debugging**: Every worker identical
3. **Instant start**: No election delay

## Implementation Plan

### Phase 1: Embedded (Quick Start)
```python
# Just add to existing StreamWorker
async def _consume_loop(self):
    # Add timer checking with Lua script for atomicity
    ...
```

### Phase 2: Leader Election (Production)
```python
# Add election on startup
# Add heartbeat maintenance
# Add graceful handoff on shutdown
```

### Configuration
```yaml
timers:
  strategy: leader  # embedded | leader | partitioned
  check_interval: 1
  leader:
    ttl: 10
    heartbeat: 5
```

## Code Example: Simple Leader Election

```python
class StreamWorker:
    """StreamWorker with leader election for timer management"""

    LEADER_KEY = "timer:leader"
    LEADER_TTL = 10
    HEARTBEAT_INTERVAL = 5

    async def start(self):
        """Start worker and attempt leadership"""
        self.is_timer_leader = False
        self._heartbeat_task = None

        # Try to become leader
        await self._elect_leader()

        # Start main loop
        try:
            await self._consume_loop()
        finally:
            # Clean shutdown - release leadership
            if self.is_timer_leader:
                await self._release_leadership()

    async def _elect_leader(self):
        """Attempt to become timer leader"""
        success = await self.redis.set(
            self.LEADER_KEY,
            self.worker_id,
            nx=True,
            ex=self.LEADER_TTL
        )

        if success:
            logger.info(f"Worker {self.worker_id} became timer leader")
            self.is_timer_leader = True
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self):
        """Maintain leadership with heartbeats"""
        while self.is_timer_leader and self._running:
            await asyncio.sleep(self.HEARTBEAT_INTERVAL)

            # Extend lease if we're still leader
            current = await self.redis.get(self.LEADER_KEY)
            if current == self.worker_id:
                await self.redis.expire(self.LEADER_KEY, self.LEADER_TTL)
            else:
                # Lost leadership somehow
                logger.warning(f"Worker {self.worker_id} lost timer leadership")
                self.is_timer_leader = False

    async def _consume_loop(self):
        """Main loop - events for everyone, timers for leader"""

        while self._running:
            # Leader checks timers
            if self.is_timer_leader:
                await self._process_expired_timers()

            # Everyone processes events
            messages = await self.redis.xreadgroup(
                self.consumer_group,
                self.worker_id,
                self.streams,
                count=10,
                block=1000  # 1 second
            )

            if messages:
                await self._process_messages(messages)

            # Non-leaders try to become leader periodically
            elif not self.is_timer_leader:
                await self._elect_leader()

    async def _release_leadership(self):
        """Gracefully release leadership on shutdown"""
        if self.is_timer_leader:
            current = await self.redis.get(self.LEADER_KEY)
            if current == self.worker_id:
                await self.redis.delete(self.LEADER_KEY)
                logger.info(f"Worker {self.worker_id} released timer leadership")
```

This provides automatic failover, no duplicates, and clean shutdown!