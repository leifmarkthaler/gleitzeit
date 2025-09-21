# Stateless Event System with Persistence

## The Challenge

Events must work with:
1. **Stateless execution** - No in-memory state between tasks
2. **Redis persistence** - All state in Redis
3. **Event listeners** - Must be persisted and retrievable
4. **Distributed workers** - Any worker can handle events

## Solution: Event Tasks in Redis

### Core Concept: Events Create Tasks

When a provider emits an event, it creates **event-triggered tasks** in Redis:

```python
# Provider emits event
await self.emit("llm.token_limit_exceeded", {"tokens": 5000})

# This creates entries in Redis:
# 1. Event in stream
# 2. Triggered tasks in queue
```

## Implementation Architecture

### 1. Event Registration (At Workflow Start)

```python
class WorkflowLoader:
    async def load_workflow(self, workflow: dict, persistence: ScalableRedisAdapter):
        """Load workflow and register event listeners"""
        
        workflow_id = workflow["id"]
        expanded_tasks = []
        
        for task in workflow["tasks"]:
            # Regular task expansion
            if "if" in task or "events" in task:
                expanded = self.expand_task(task)
                expanded_tasks.extend(expanded)
            else:
                expanded_tasks.append(task)
            
            # Register event listeners in Redis
            if task.get("type") == "listener" or task.get("listens_to"):
                await self.register_event_listener(
                    workflow_id,
                    task,
                    persistence
                )
        
        return expanded_tasks
    
    async def register_event_listener(
        self,
        workflow_id: str,
        listener_task: dict,
        persistence: ScalableRedisAdapter
    ):
        """Store event listener in Redis for stateless execution"""
        
        event_pattern = listener_task.get("listens_to")
        
        # Store in Redis hash for fast lookup
        key = f"event_listeners:{event_pattern}"
        listener_data = {
            "workflow_id": workflow_id,
            "task_template": json.dumps(listener_task),
            "filter": listener_task.get("filter"),
            "throttle": listener_task.get("throttle")
        }
        
        await persistence.redis.hset(
            key,
            f"{workflow_id}:{listener_task['id']}",
            json.dumps(listener_data)
        )
        
        # Also store reverse mapping for cleanup
        await persistence.redis.sadd(
            f"workflow_listeners:{workflow_id}",
            f"{event_pattern}:{listener_task['id']}"
        )
```

### 2. Provider Event Emission (Stateless)

```python
class BaseProvider:
    """Enhanced base provider with stateless event support"""
    
    def __init__(self, persistence: ScalableRedisAdapter):
        self.persistence = persistence
        self.task_context = None  # Set by executor
    
    async def emit(self, event_name: str, data: dict = None):
        """Emit event through Redis for stateless processing"""
        
        if not self.task_context:
            return
        
        event_data = {
            "event": f"{self.protocol}.{event_name}",
            "task_id": self.task_context.get("task_id"),
            "workflow_id": self.task_context.get("workflow_id"),
            "timestamp": datetime.utcnow().isoformat(),
            "data": data or {}
        }
        
        # 1. Add to Redis Stream (for audit/replay)
        await self.persistence.redis.xadd(
            f"events:{self.task_context['workflow_id']}",
            event_data,
            maxlen=10000  # Keep last 10k events
        )
        
        # 2. Find and trigger listeners (stateless)
        await self.trigger_event_listeners(event_data)
    
    async def trigger_event_listeners(self, event_data: dict):
        """Find matching listeners and create tasks"""
        
        event_name = event_data["event"]
        workflow_id = event_data["workflow_id"]
        
        # Check exact match listeners
        exact_key = f"event_listeners:{event_name}"
        exact_listeners = await self.persistence.redis.hgetall(exact_key)
        
        # Check wildcard listeners
        wildcard_key = "event_listeners:*"
        wildcard_listeners = await self.persistence.redis.hgetall(wildcard_key)
        
        # Check pattern listeners (e.g., "llm.*")
        pattern_keys = await self.find_pattern_listeners(event_name)
        
        all_listeners = {**exact_listeners, **wildcard_listeners}
        for key in pattern_keys:
            pattern_listeners = await self.persistence.redis.hgetall(key)
            all_listeners.update(pattern_listeners)
        
        # Create tasks for each matching listener
        for listener_id, listener_json in all_listeners.items():
            listener = json.loads(listener_json)
            
            # Check if listener belongs to this workflow
            if listener["workflow_id"] != workflow_id:
                continue
            
            # Check filter condition
            if listener.get("filter"):
                if not await self.evaluate_filter(listener["filter"], event_data):
                    continue
            
            # Check throttle
            if listener.get("throttle"):
                if not await self.check_throttle(listener_id, listener["throttle"]):
                    continue
            
            # Create triggered task
            await self.create_event_task(listener, event_data)
    
    async def create_event_task(self, listener: dict, event_data: dict):
        """Create a task triggered by event"""
        
        task_template = json.loads(listener["task_template"])
        
        # Create new task with event data
        triggered_task = {
            **task_template,
            "id": f"{task_template['id']}_{uuid.uuid4().hex[:8]}",
            "triggered_by": event_data["event"],
            "event_data": event_data,
            "params": {
                **task_template.get("params", {}),
                "event": event_data  # Make event data available to task
            }
        }
        
        # Add to task queue
        await self.persistence.add_task_to_queue(
            event_data["workflow_id"],
            triggered_task
        )
```

### 3. Stateless Event Listener Tasks

```python
# In workflow definition
workflow = {
    "tasks": [
        {
            "id": "generate_content",
            "run": "llm/v1:generate",
            "with": {"prompt": "${input.prompt}"}
        },
        {
            "id": "handle_token_limit",
            "type": "listener",
            "listens_to": "llm.token_limit_exceeded",
            "run": "llm/v1:generate",
            "with": {
                "prompt": "${event.data.prompt}",
                "model": "gpt-3.5-turbo"  # Smaller model
            }
        }
    ]
}

# Expands to:
{
    "tasks": [
        {
            "id": "generate_content",
            "protocol": "llm/v1",
            "method": "generate",
            "params": {"prompt": "${input.prompt}"}
        }
    ],
    "event_listeners": [
        {
            "id": "handle_token_limit",
            "listens_to": "llm.token_limit_exceeded",
            "creates_task": {
                "protocol": "llm/v1",
                "method": "generate",
                "params": {
                    "prompt": "${event.data.prompt}",
                    "model": "gpt-3.5-turbo"
                }
            }
        }
    ]
}
```

### 4. Redis Structure for Events

```python
# Event listeners registry (persistent)
event_listeners:llm.token_limit_exceeded = {
    "workflow_123:handle_limit": {
        "workflow_id": "workflow_123",
        "task_template": {...},
        "filter": "${event.data.tokens} > 4000"
    }
}

# Event stream (for audit/replay)
events:workflow_123 = [
    {"event": "llm.started", "timestamp": "...", "data": {}},
    {"event": "llm.token_limit_exceeded", "timestamp": "...", "data": {"tokens": 5000}}
]

# Throttle tracking
event_throttle:handle_limit = {
    "last_triggered": "2024-01-01T12:00:00",
    "count": 5
}

# Task queue (triggered tasks added here)
tasks:workflow_123:pending = [
    {"id": "handle_limit_abc123", "triggered_by": "llm.token_limit_exceeded", ...}
]
```

### 5. Integration with Execution Engine

```python
class TaskExecutor:
    """Stateless task executor with event support"""
    
    async def execute_task(self, task_id: str, workflow_id: str):
        """Execute task with event context"""
        
        # Load task from Redis
        task = await self.persistence.get_task(workflow_id, task_id)
        
        # Create event context for provider
        event_context = {
            "task_id": task_id,
            "workflow_id": workflow_id,
            "persistence": self.persistence
        }
        
        # Get provider
        provider = self.get_provider(task["protocol"])
        
        # Inject context for event emission
        provider.task_context = event_context
        
        # Execute task
        try:
            # Emit standard started event
            await provider.emit("started", {"task": task_id})
            
            result = await provider.execute(
                task["method"],
                task["params"]
            )
            
            # Emit standard completed event
            await provider.emit("completed", {"result": result})
            
            # Store result in Redis
            await self.persistence.set_task_result(
                workflow_id,
                task_id,
                result
            )
            
        except Exception as e:
            await provider.emit("failed", {"error": str(e)})
            raise
```

## Real-World Example: Stateless LLM Workflow

```python
from gleitzeit.easy import t, w, on

workflow = w(
    t("generate", "llm/v1:generate")
        .with_(prompt="${input.prompt}", model="gpt-4"),
    
    # These listeners are stored in Redis at workflow load
    on("llm.token_limit_exceeded")
        .run("retry_smaller", "llm/v1:generate")
        .with_(model="gpt-3.5-turbo", prompt="${event.data.prompt}")
        .throttle(60),  # Max once per minute
    
    on("llm.rate_limited")
        .run("wait", "timer/v1:sleep")
        .with_(seconds="${event.data.retry_after}")
        .then("retry_original", "llm/v1:generate")
        .with_(prompt="${event.data.original_prompt}"),
    
    on("*.failed")
        .run("alert", "monitoring/v1:alert")
        .with_(
            task="${event.task_id}",
            error="${event.data.error}"
        )
        .filter("${event.data.severity} == 'high'")
)

# This creates in Redis:
# 1. Task definitions
# 2. Event listener mappings
# 3. Event filters and throttles
```

## Benefits of Stateless Event System

1. **Scalability** - Any worker can handle events
2. **Reliability** - Events persisted in Redis
3. **Replayability** - Event stream in Redis
4. **No Memory State** - Everything in Redis
5. **Distributed** - Works across multiple servers

## Performance Considerations

```python
class OptimizedEventSystem:
    """Performance optimizations for high-volume events"""
    
    async def emit_batch(self, events: List[dict]):
        """Batch event emission for performance"""
        pipeline = self.redis.pipeline()
        
        for event in events:
            pipeline.xadd(f"events:{event['workflow_id']}", event)
        
        await pipeline.execute()
    
    async def use_lua_scripts(self):
        """Use Lua for atomic operations"""
        lua_script = """
        -- Check throttle and create task atomically
        local throttle_key = KEYS[1]
        local task_queue = KEYS[2]
        local throttle_seconds = ARGV[1]
        local task_data = ARGV[2]
        
        local last_run = redis.call('GET', throttle_key)
        local now = redis.call('TIME')[1]
        
        if not last_run or (now - last_run) > throttle_seconds then
            redis.call('SET', throttle_key, now)
            redis.call('LPUSH', task_queue, task_data)
            return 1
        end
        return 0
        """
        
        return await self.redis.eval(lua_script, ...)
```

## Migration Path

### Phase 1: Add event context to providers
```python
# Just pass persistence to providers
provider.persistence = self.persistence
```

### Phase 2: Store listeners in Redis
```python
# On workflow load, register listeners
await register_event_listeners(workflow, persistence)
```

### Phase 3: Enable event emission
```python
# Providers start emitting events
await self.emit("custom_event", data)
```

This gives us a **fully stateless, Redis-backed event system** that scales horizontally and maintains persistence!