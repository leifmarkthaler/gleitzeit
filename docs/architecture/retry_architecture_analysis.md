# Retry Architecture Analysis - Worker/Handler Alignment

## Current Architecture Overview

### Gleitzeit's Core Principles

1. **Workers**: Stateless, horizontally scalable processors
   - TaskExecutionWorker: Executes tasks
   - DependencyWorker: Resolves dependencies
   - TimerWorker: Handles scheduled retries

2. **Handlers**: Lightweight, stateless executors
   - "They do NOT: Handle dependencies, Manage state, Know about workflows"
   - All state is in Redis
   - Work directly with Task objects

3. **State Management**: All state in Redis
   - Task state: Redis hashes
   - Workflow state: Redis hashes/sets
   - Events: Redis streams
   - Timers: Redis sorted sets

## Current Retry Implementation Location

### Where Retry Logic Lives Now

```
TaskExecutionWorker.handle_task_failure()
    ├── Creates RetryManager (in-memory) ❌
    ├── Checks should_retry()
    ├── Calculates delay
    └── Schedules via Redis timer ✅
```

**Problems**:
1. RetryManager created per failure (no state persistence)
2. Each worker has independent retry logic
3. Advanced features use in-memory state ❌

## Architectural Misalignment

### 1. Stateful Components in Stateless System ❌

**Current Implementation**:
```python
class RetryMetrics:
    def __init__(self):
        self._metrics: deque = deque(maxlen=10000)  # IN-MEMORY!
        self._error_counts: Dict = defaultdict(int)  # IN-MEMORY!

class RetryBudget:
    def __init__(self):
        self._tokens = float(max_tokens)  # IN-MEMORY!
        self._hourly_window: deque = deque()  # IN-MEMORY!
```

**Violations**:
- Breaks horizontal scaling (each worker has separate state)
- Loses data on worker restart
- No coordination between workers

### 2. Wrong Layer for Retry Logic ⚠️

**Current**: Retry logic in TaskExecutionWorker
**Better**: Retry as a separate concern

Options:
1. **RetryWorker** (new specialized worker)
2. **Redis-based retry service** (stateless functions)
3. **Handler enhancement** (retry at handler level)

### 3. Handler Pattern Violation ❌

Handlers should be stateless, but:
- OllamaHandler has CircuitBreaker (somewhat stateful)
- Handlers don't coordinate retry state
- No shared retry configuration

## Proposed Architecture

### Option 1: Dedicated RetryWorker (RECOMMENDED) ✅

```
Architecture:
    TaskExecutionWorker
        ↓ (task fails)
    Redis Stream: "task:failed"
        ↓
    RetryWorker (NEW)
        ├── Checks Redis-based budget
        ├── Consults Redis-based metrics
        ├── Applies Redis-based adaptive config
        └── Schedules retry via timer
```

**Benefits**:
- Centralized retry logic
- Single source of truth
- Easy to monitor/debug
- Follows worker pattern

### Option 2: Redis-Based Retry Service ✅

```python
class StatelessRetryService:
    """All operations use Redis, no in-memory state"""

    async def should_retry(self, redis, task_id, workflow_id, error):
        # Check budget in Redis
        budget_key = f"retry:budget:{workflow_id}"
        tokens = await redis.get(budget_key)

        # Check metrics in Redis
        metrics_key = f"retry:metrics:{workflow_id}"

        # Get adaptive config from Redis
        config_key = f"retry:config:{workflow_id}"

        # All decisions based on Redis state
        return decision
```

**Benefits**:
- Truly stateless
- Can be called from any worker
- Consistent across system

### Option 3: Enhanced Handler Pattern ⚠️

```python
class RetryAwareHandler(BaseHandler):
    async def execute_with_retry(self, task):
        # Handlers manage their own retry
        pass
```

**Problems**:
- Violates handler simplicity
- Duplicates logic across handlers
- Hard to coordinate globally

## Recommended Implementation Plan

### Phase 1: Make Current Implementation Stateless

1. **Replace in-memory with Redis**:
```python
class StatelessRetryMetrics:
    async def record_retry_attempt(self, redis, ...):
        # Use Redis counters
        await redis.hincrby(f"retry:metrics:{wf_id}:attempts", task_id, 1)

        # Use Redis streams for timeline
        await redis.xadd(f"retry:metrics:stream", {...})

        # Use Redis sorted sets for windows
        await redis.zadd(f"retry:metrics:window", {task_id: timestamp})

class StatelessRetryBudget:
    async def can_retry(self, redis, ...):
        # Use Redis for distributed token bucket
        lua_script = """
        local key = KEYS[1]
        local tokens = redis.call('get', key) or 100
        if tonumber(tokens) > 0 then
            redis.call('decr', key)
            return 1
        end
        return 0
        """
        return await redis.eval(lua_script, ...)
```

### Phase 2: Create RetryWorker

```python
class RetryWorker(BaseWorker):
    """Specialized worker for retry decisions"""

    def get_base_streams(self):
        return ["task:failed", "retry:check"]

    async def process_message(self, stream, msg_id, data):
        task_id = data['task_id']
        workflow_id = data['workflow_id']
        error = data['error']

        # All operations use Redis
        retry_service = StatelessRetryService(self.redis)

        if await retry_service.should_retry(task_id, workflow_id, error):
            delay = await retry_service.calculate_delay(task_id)
            await self.schedule_retry(task_id, workflow_id, delay)
        else:
            await self.mark_permanently_failed(task_id, workflow_id)
```

### Phase 3: Update TaskExecutionWorker

```python
async def handle_task_failure(self, task_id, workflow_id, error):
    # Just emit to stream for RetryWorker
    await self.redis.xadd(
        "task:failed",
        {
            'task_id': task_id,
            'workflow_id': workflow_id,
            'error': error,
            'timestamp': time.time()
        }
    )
    # RetryWorker handles the rest
```

## Integration Points

### 1. With Existing Workers
- **TaskExecutionWorker**: Emits failures to RetryWorker
- **TimerWorker**: Still handles retry timers
- **DependencyWorker**: Still handles final failures

### 2. With Handlers
- Handlers remain simple (no retry logic)
- Circuit breaker can stay (it's fail-fast, not retry)

### 3. With Configuration
```yaml
workers:
  - worker_type: retry
    count: 2  # Lightweight, don't need many
    config:
      default_budget:
        max_retries_per_minute: 100
      default_adaptive:
        mode: balanced
```

## Benefits of Aligned Architecture

1. **True Horizontal Scaling**: All workers share same retry state
2. **Resilience**: Retry state survives worker failures
3. **Consistency**: Single retry decision point
4. **Observability**: Central place to monitor retries
5. **Simplicity**: Each component has single responsibility

## Migration Path

1. **Step 1**: Create stateless retry service (Redis-based)
2. **Step 2**: Update TaskExecutionWorker to use service
3. **Step 3**: Create RetryWorker (optional but recommended)
4. **Step 4**: Migrate existing retry config to Redis
5. **Step 5**: Add monitoring/metrics

## Conclusion

The current retry implementation violates Gleitzeit's stateless architecture. The recommended approach is:

1. **Immediate**: Refactor to use Redis for all state
2. **Next**: Create RetryWorker for centralized retry management
3. **Future**: Enhanced monitoring and cross-workflow coordination

This maintains the worker/handler separation, preserves statelessness, and enables true horizontal scaling.