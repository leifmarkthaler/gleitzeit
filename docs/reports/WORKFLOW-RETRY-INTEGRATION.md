# Workflow Management & Retry Manager Integration
## Architectural Placement for Horizontal Scaling

**Date:** 2025-08-30  
**Context:** Integration with scaled client-engine architecture

---

## Executive Summary

For horizontal scaling, **workflow management** and **retry management** should be:

1. **Workflow Manager:** Separate stateless service with leader election per workflow
2. **Retry Manager:** Embedded in each ExecutionEngine as stateless component

This separation enables:
- Multiple workflow coordinators with workflow-level partitioning
- Distributed retry handling without centralized bottleneck
- Event-driven coordination across all components

---

## Current Architecture Review

### Workflow Management (Currently)
- Mixed between ExecutionEngine and QueueManager
- Workflow state tracking in multiple places
- Completion detection logic duplicated
- Dependencies resolved locally

### Retry Management (Currently)
- Event-driven retry manager listens to TASK_FAILED events
- Schedules retries via events
- Uses persistence for retry state
- Already fairly stateless design ✅

---

## Proposed Distributed Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Distributed Architecture                   │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────┐       │
│  │         Workflow Coordinator Service              │       │
│  │  ┌─────────────┐  ┌─────────────┐               │       │
│  │  │Coordinator 1│  │Coordinator 2│  ...          │       │
│  │  └─────────────┘  └─────────────┘               │       │
│  │  - Leader election per workflow                  │       │
│  │  - Workflow state management                     │       │
│  │  - Dependency resolution                         │       │
│  │  - Completion detection                          │       │
│  └──────────────────────────────────────────────────┘       │
│                           ↓                                  │
│            Redis Event Bus (Pub/Sub + Streams)              │
│                           ↓                                  │
│  ┌──────────────────────────────────────────────────┐       │
│  │           Execution Engine Cluster                │       │
│  │  ┌─────────────────────────────────┐            │       │
│  │  │   ExecutionEngine Instance 1     │            │       │
│  │  │   ├── Stateless Task Executor    │            │       │
│  │  │   ├── Embedded Retry Handler     │ ←──┐      │       │
│  │  │   └── Local Work Queue           │    │      │       │
│  │  └─────────────────────────────────┘     │      │       │
│  │  ┌─────────────────────────────────┐     │      │       │
│  │  │   ExecutionEngine Instance 2     │     │      │       │
│  │  │   ├── Stateless Task Executor    │     │      │       │
│  │  │   ├── Embedded Retry Handler     │ ←──┤      │       │
│  │  │   └── Local Work Queue           │    │      │       │
│  │  └─────────────────────────────────┘     │      │       │
│  │                                           │      │       │
│  │  Retry decisions made locally ───────────┘      │       │
│  └──────────────────────────────────────────────────┘       │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 1. Workflow Management Integration

### Option A: Dedicated Workflow Coordinator Service (Recommended) ✅

```python
class WorkflowCoordinator:
    """Separate service for workflow orchestration"""
    
    def __init__(self, coordinator_id: str, redis: Redis):
        self.coordinator_id = coordinator_id
        self.redis = redis
        self.leader_manager = LeaderElectionManager(redis)
        self.workflow_states = {}  # Cache, truth in Redis
        
    async def run(self):
        """Main coordinator loop"""
        # Subscribe to workflow events
        await self.subscribe_to_events([
            'WORKFLOW_SUBMITTED',
            'TASK_COMPLETED',
            'TASK_FAILED',
            'TASK_READY'
        ])
        
        while True:
            # Process workflows where we're the leader
            owned_workflows = await self.get_owned_workflows()
            for workflow_id in owned_workflows:
                await self.coordinate_workflow(workflow_id)
            await asyncio.sleep(1)
    
    async def coordinate_workflow(self, workflow_id: str):
        """Coordinate a single workflow"""
        # 1. Check if we're still the leader
        if not await self.leader_manager.is_leader(workflow_id, self.coordinator_id):
            return
            
        # 2. Get workflow state from Redis
        state = await self.get_workflow_state(workflow_id)
        
        # 3. Check for ready tasks
        ready_tasks = await self.find_ready_tasks(workflow_id, state)
        
        # 4. Submit ready tasks to queue
        for task in ready_tasks:
            await self.submit_task_to_queue(task)
            
        # 5. Check for workflow completion
        if await self.is_workflow_complete(workflow_id, state):
            await self.complete_workflow(workflow_id)
```

**Leader Election per Workflow:**
```python
class LeaderElectionManager:
    """Manage leader election for workflows"""
    
    def __init__(self, redis: Redis):
        self.redis = redis
        self.lease_duration = 30  # seconds
        
    async def elect_leader(self, workflow_id: str, coordinator_id: str) -> bool:
        """Try to become leader for workflow"""
        key = f"workflow:{workflow_id}:leader"
        
        # Try to acquire leadership with lease
        acquired = await self.redis.set(
            key,
            coordinator_id,
            nx=True,  # Only if not exists
            ex=self.lease_duration
        )
        
        if acquired:
            # Start lease renewal
            asyncio.create_task(self.renew_lease(workflow_id, coordinator_id))
            
        return acquired
    
    async def renew_lease(self, workflow_id: str, coordinator_id: str):
        """Renew leadership lease"""
        key = f"workflow:{workflow_id}:leader"
        while True:
            await asyncio.sleep(self.lease_duration / 2)
            
            # Check if still leader
            current = await self.redis.get(key)
            if current != coordinator_id:
                break
                
            # Renew lease
            await self.redis.expire(key, self.lease_duration)
```

**Workflow State Management:**
```python
class DistributedWorkflowState:
    """Workflow state in Redis for coordination"""
    
    def __init__(self, redis: Redis):
        self.redis = redis
        
    async def get_state(self, workflow_id: str) -> WorkflowState:
        """Get complete workflow state"""
        key = f"workflow:{workflow_id}:state"
        data = await self.redis.hgetall(key)
        
        return WorkflowState(
            workflow_id=workflow_id,
            status=data['status'],
            tasks_total=int(data['tasks_total']),
            tasks_completed=int(data['tasks_completed']),
            tasks_failed=int(data['tasks_failed']),
            task_states=json.loads(data['task_states'])
        )
    
    async def update_task_state(
        self, 
        workflow_id: str,
        task_id: str,
        status: str
    ):
        """Update individual task state"""
        # Use Lua script for atomic update
        lua_script = """
        local workflow_key = KEYS[1]
        local task_id = ARGV[1]
        local status = ARGV[2]
        
        -- Update task states
        local task_states = redis.call('hget', workflow_key, 'task_states')
        local states = cjson.decode(task_states)
        states[task_id] = status
        redis.call('hset', workflow_key, 'task_states', cjson.encode(states))
        
        -- Update counters
        if status == 'completed' then
            redis.call('hincrby', workflow_key, 'tasks_completed', 1)
        elseif status == 'failed' then
            redis.call('hincrby', workflow_key, 'tasks_failed', 1)
        end
        
        return 1
        """
        
        await self.redis.eval(
            lua_script,
            1,
            f"workflow:{workflow_id}:state",
            task_id,
            status
        )
```

### Option B: Embedded in ExecutionEngine (Not Recommended) ❌
- Would require complex coordination between engines
- Workflow state would be fragmented
- Difficult to track workflow completion

---

## 2. Retry Manager Integration

### Recommended: Embedded Stateless Component ✅

```python
class StatelessExecutionEngine:
    def __init__(self, engine_id: str, redis: Redis):
        self.engine_id = engine_id
        self.redis = redis
        
        # Embed retry manager as stateless component
        self.retry_manager = DistributedRetryManager(redis, engine_id)
        
        # Subscribe to retry events
        self.event_subscriptions = [
            ('TASK_FAILED', self.handle_task_failed),
            ('TASK_READY_FOR_RETRY', self.handle_retry_ready)
        ]
    
    async def handle_task_failed(self, event: GleitzeitEvent):
        """Handle task failure locally"""
        task_id = event.data['task_id']
        
        # Check if this engine executed the task
        if not await self.did_execute_task(task_id):
            return  # Let the executing engine handle it
            
        # Delegate to retry manager
        await self.retry_manager.handle_failure(event)
    
    async def handle_retry_ready(self, event: GleitzeitEvent):
        """Handle retry ready event"""
        task_id = event.data['task_id']
        
        # Any engine can pick up the retry
        # This enables load balancing of retries
        await self.enqueue_for_execution(task_id)
```

**Distributed Retry Manager:**
```python
class DistributedRetryManager:
    """Stateless retry manager using Redis"""
    
    def __init__(self, redis: Redis, engine_id: str):
        self.redis = redis
        self.engine_id = engine_id
        
    async def handle_failure(self, event: GleitzeitEvent):
        """Handle task failure with retry logic"""
        task_id = event.data['task_id']
        error = event.data.get('error')
        
        # 1. Get retry state from Redis
        retry_state = await self.get_retry_state(task_id)
        
        # 2. Check if retryable
        if not self.is_retryable(error, retry_state):
            await self.mark_permanently_failed(task_id)
            return
            
        # 3. Calculate backoff
        delay = self.calculate_backoff(retry_state)
        
        # 4. Schedule retry (via Redis sorted set)
        retry_time = time.time() + delay
        await self.redis.zadd(
            "retry_schedule",
            {task_id: retry_time}
        )
        
        # 5. Update retry state
        await self.update_retry_state(task_id, retry_state)
        
        # 6. Emit retry scheduled event
        await self.emit_event(RetryScheduledEvent(
            task_id=task_id,
            retry_at=retry_time,
            attempt=retry_state['attempts'] + 1
        ))
    
    async def get_retry_state(self, task_id: str) -> Dict:
        """Get retry state from Redis"""
        key = f"task:{task_id}:retry"
        state = await self.redis.hgetall(key)
        
        return {
            'attempts': int(state.get('attempts', 0)),
            'last_error': state.get('last_error'),
            'last_retry': float(state.get('last_retry', 0)),
            'strategy': state.get('strategy', 'exponential')
        }
    
    def calculate_backoff(self, retry_state: Dict) -> float:
        """Calculate backoff delay"""
        attempts = retry_state['attempts']
        strategy = retry_state['strategy']
        
        if strategy == 'exponential':
            base_delay = 2
            max_delay = 300
            delay = min(base_delay ** attempts, max_delay)
        elif strategy == 'linear':
            delay = attempts * 10
        else:  # fixed
            delay = 10
            
        # Add jitter
        jitter = random.uniform(0, delay * 0.1)
        return delay + jitter
```

**Retry Processor (Separate Component):**
```python
class RetryProcessor:
    """Process scheduled retries from sorted set"""
    
    def __init__(self, redis: Redis):
        self.redis = redis
        
    async def run(self):
        """Main retry processing loop"""
        while True:
            # Get due retries from sorted set
            now = time.time()
            due_retries = await self.redis.zrangebyscore(
                "retry_schedule",
                0,
                now,
                start=0,
                num=10
            )
            
            for task_id in due_retries:
                # Remove from schedule
                await self.redis.zrem("retry_schedule", task_id)
                
                # Emit retry ready event
                await self.emit_event(TaskReadyForRetryEvent(
                    task_id=task_id,
                    timestamp=now
                ))
                
            await asyncio.sleep(1)
```

---

## 3. Integration Points

### Event Flow with All Components

```
1. Task Submission:
   Client → ExecutionEngine → TASK_SUBMITTED → WorkflowCoordinator
                                              ↓
                                    Updates workflow state

2. Task Execution:
   WorkflowCoordinator → TASK_READY → ExecutionEngine
                                    ↓
                               Executes task

3. Task Failure:
   ExecutionEngine → TASK_FAILED → RetryManager (embedded)
                                 ↓
                        Schedules retry if applicable
                                 ↓
   RetryProcessor → TASK_READY_FOR_RETRY → ExecutionEngine

4. Task Completion:
   ExecutionEngine → TASK_COMPLETED → WorkflowCoordinator
                                    ↓
                          Checks dependencies
                                    ↓
                    Submits next ready tasks

5. Workflow Completion:
   WorkflowCoordinator → WORKFLOW_COMPLETED → Client
```

### Redis Data Structure Organization

```yaml
# Workflow Coordination
workflow:{id}:leader        # Current leader coordinator
workflow:{id}:state         # Workflow state hash
workflow:{id}:tasks         # Task list
workflow:{id}:dependencies  # Dependency graph

# Task Management  
task:{id}:state            # Task state
task:{id}:retry            # Retry state
task:{id}:results          # Task results
task:{id}:lock             # Execution lock

# Scheduling
retry_schedule             # Sorted set of retry times
task_queue:global          # Global task queue
task_queue:engine:{id}     # Engine-specific queues

# Coordination
engines:registry           # Available engines
coordinators:registry      # Available coordinators
```

---

## 4. Scaling Characteristics

### Workflow Coordinator Scaling

**Horizontal Scaling Pattern:**
```
Workflows: W1, W2, W3, W4, W5, W6

Coordinator 1: Leader for W1, W3, W5
Coordinator 2: Leader for W2, W4, W6

If Coordinator 1 fails:
- Coordinator 2 takes over W1, W3, W5
- New Coordinator 3 can be added
```

**Benefits:**
- Workflows partitioned across coordinators
- Automatic failover via leader election
- Can scale coordinators based on workflow count

### Retry Manager Scaling

**Distributed Retry Pattern:**
```
Engine 1: Handles failures for its executed tasks
Engine 2: Handles failures for its executed tasks
Engine N: ...

RetryProcessor: Monitors global retry schedule
              → Emits events for due retries
              → Any engine can execute retry
```

**Benefits:**
- No centralized retry bottleneck
- Retry logic stays close to execution
- Load balancing of retry execution

---

## 5. Implementation Recommendations

### Phase 1: Workflow Coordinator Service
1. **Create WorkflowCoordinator class**
   - Leader election per workflow
   - State management in Redis
   - Dependency resolution

2. **Extract from ExecutionEngine**
   - Remove workflow tracking
   - Remove completion detection
   - Focus on pure task execution

### Phase 2: Distributed Retry Manager
1. **Embed in ExecutionEngine**
   - Stateless retry decisions
   - Redis-based retry state
   - Event-driven coordination

2. **Create RetryProcessor**
   - Monitor retry schedule
   - Emit retry events
   - Run as separate service

### Phase 3: Integration Testing
1. **Multi-coordinator testing**
   - Leader failover
   - Workflow partitioning
   - State consistency

2. **Retry distribution testing**
   - Cross-engine retries
   - Backoff calculations
   - Failure scenarios

---

## 6. Configuration Examples

### Docker Compose for Development
```yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    
  coordinator-1:
    image: gleitzeit:latest
    command: workflow-coordinator --id coord-1
    environment:
      REDIS_URL: redis://redis:6379
      
  coordinator-2:
    image: gleitzeit:latest
    command: workflow-coordinator --id coord-2
    environment:
      REDIS_URL: redis://redis:6379
      
  engine-1:
    image: gleitzeit:latest
    command: execution-engine --id engine-1
    environment:
      REDIS_URL: redis://redis:6379
      
  engine-2:
    image: gleitzeit:latest
    command: execution-engine --id engine-2
    environment:
      REDIS_URL: redis://redis:6379
      
  retry-processor:
    image: gleitzeit:latest
    command: retry-processor
    environment:
      REDIS_URL: redis://redis:6379
```

### Kubernetes Deployment
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: workflow-coordinator
spec:
  replicas: 3  # Multiple coordinators
  selector:
    matchLabels:
      app: workflow-coordinator
  template:
    spec:
      containers:
      - name: coordinator
        image: gleitzeit:latest
        command: ["workflow-coordinator"]
        env:
        - name: COORDINATOR_ID
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: execution-engine
spec:
  replicas: 5  # Multiple engines
  selector:
    matchLabels:
      app: execution-engine
  template:
    spec:
      containers:
      - name: engine
        image: gleitzeit:latest
        command: ["execution-engine"]
        env:
        - name: ENGINE_ID
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
```

---

## Conclusion

For horizontal scaling:

1. **Workflow Manager** → Separate coordinator service with leader election
   - Enables workflow partitioning across coordinators
   - Clean separation of concerns
   - Automatic failover

2. **Retry Manager** → Embedded in ExecutionEngine as stateless component
   - Distributed retry handling
   - No central bottleneck
   - Load balanced retry execution

This architecture provides:
- **True horizontal scaling** for both components
- **Fault tolerance** with automatic failover
- **Clean boundaries** between services
- **Event-driven coordination** across all components

The separation allows each component to scale independently based on workload characteristics.

---

**Document Status:** Complete  
**Implementation Complexity:** Medium  
**Estimated Effort:** 2-3 weeks for both components