# Solutions for Streaming Event Integration

## Problem Summary
ScalableRedisAdapter emits to single stream while StreamEventBus expects per-type streams.

## Solution 1: Fix ScalableRedisAdapter (RECOMMENDED)

### Implementation

```python
# src/gleitzeit/persistence/scalable_redis.py

class ScalableRedisAdapter:
    
    async def _emit_event(self, event_type: str, data: dict):
        """Emit event to type-specific Redis Stream."""
        if not self.enable_events:
            return
        
        # Match StreamEventBus pattern
        stream_key = f"gleitzeit:events:stream:{event_type}"
        
        event_data = {
            "event_type": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            "source": "persistence",
            "correlation_id": data.get("workflow_id", ""),
            "severity": "INFO",
            "data": json.dumps(data),
            "metadata": json.dumps({})
        }
        
        try:
            await self._execute(
                "xadd",
                stream_key,
                event_data,
                id="*"
            )
            logger.debug(f"Emitted {event_type} to {stream_key}")
        except Exception as e:
            logger.warning(f"Failed to emit event {event_type}: {e}")
    
    async def save_task(self, task: Task) -> None:
        """Save task with proper event emission."""
        # Existing save logic
        await self._save_task_data(task)
        
        # Emit appropriate event based on status
        event_map = {
            TaskStatus.PENDING: EventType.TASK_SUBMITTED,
            TaskStatus.QUEUED: EventType.TASK_QUEUED,
            TaskStatus.EXECUTING: EventType.TASK_STARTED,
            TaskStatus.COMPLETED: EventType.TASK_COMPLETED,
            TaskStatus.FAILED: EventType.TASK_FAILED,
            TaskStatus.CANCELLED: EventType.TASK_CANCELLED,
        }
        
        event_type = event_map.get(task.status)
        if event_type:
            await self._emit_event(
                event_type,
                {
                    "task_id": task.id,
                    "workflow_id": task.workflow_id,
                    "status": str(task.status),
                    "provider": task.provider,
                }
            )
    
    async def save_workflow(self, workflow: Workflow) -> None:
        """Save workflow with proper event emission."""
        # Existing save logic
        await self._save_workflow_data(workflow)
        
        # Emit appropriate event
        event_map = {
            WorkflowStatus.PENDING: EventType.WORKFLOW_SUBMITTED,
            WorkflowStatus.RUNNING: EventType.WORKFLOW_STARTED,
            WorkflowStatus.COMPLETED: EventType.WORKFLOW_COMPLETED,
            WorkflowStatus.FAILED: EventType.WORKFLOW_FAILED,
            WorkflowStatus.CANCELLED: EventType.WORKFLOW_CANCELLED,
            WorkflowStatus.PAUSED: EventType.WORKFLOW_PAUSED,
        }
        
        event_type = event_map.get(workflow.status)
        if event_type:
            await self._emit_event(
                event_type,
                {
                    "workflow_id": workflow.id,
                    "status": str(workflow.status),
                    "task_count": len(workflow.tasks),
                }
            )
```

### Pros
✅ Clean, straightforward fix
✅ Maintains StreamEventBus architecture
✅ No additional components needed
✅ Events immediately available to consumers
✅ Preserves per-type scalability

### Cons
❌ Requires changes to persistence layer
❌ More Redis keys to manage
❌ Slightly more complex event emission

### Migration Path
1. Deploy with dual emission (both patterns)
2. Verify StreamEventBus consumption
3. Remove old single-stream emission

---

## Solution 2: Event Router Service

### Implementation

```python
# src/gleitzeit/events/stream_router.py

class StreamRouter:
    """Routes events from single stream to type-specific streams."""
    
    def __init__(self, redis_client, source_prefix="gleitzeit"):
        self.redis = redis_client
        self.source_stream = f"{source_prefix}:events:stream"
        self.consumer_group = "stream_router"
        self.consumer_id = f"router_{uuid.uuid4().hex[:8]}"
        self._running = False
        
    async def start(self):
        """Start routing events."""
        self._running = True
        
        # Create consumer group
        try:
            await self.redis.xgroup_create(
                self.source_stream,
                self.consumer_group,
                id="0",
                mkstream=True
            )
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                raise
        
        # Start routing
        await self._route_events()
    
    async def _route_events(self):
        """Main routing loop."""
        while self._running:
            try:
                # Read from source stream
                messages = await self.redis.xreadgroup(
                    self.consumer_group,
                    self.consumer_id,
                    {self.source_stream: ">"},
                    block=1000,
                    count=10
                )
                
                if not messages:
                    continue
                
                for stream_key, entries in messages:
                    for msg_id, data in entries:
                        # Route to type-specific stream
                        await self._route_message(data, msg_id)
                        
                        # ACK original message
                        await self.redis.xack(
                            self.source_stream,
                            self.consumer_group,
                            msg_id
                        )
                        
            except Exception as e:
                logger.error(f"Router error: {e}")
                await asyncio.sleep(1)
    
    async def _route_message(self, data: dict, msg_id: str):
        """Route single message to type-specific stream."""
        # Decode if needed
        if isinstance(data.get("event_type"), bytes):
            event_type = data["event_type"].decode()
        else:
            event_type = data.get("event_type", "unknown")
        
        # Build target stream key
        target_stream = f"gleitzeit:events:stream:{event_type}"
        
        # Forward to target stream
        await self.redis.xadd(target_stream, data)
        
        logger.debug(f"Routed {event_type} from {msg_id} to {target_stream}")

# Integration in SystemManager
class SystemManager:
    async def _initialize_event_system(self):
        # ... existing code ...
        
        # Start stream router if using single stream
        if self.config.use_stream_router:
            self.stream_router = StreamRouter(self.persistence.redis)
            asyncio.create_task(self.stream_router.start())
            logger.info("Started stream router for event routing")
```

### Pros
✅ No changes to existing components
✅ Can be deployed independently
✅ Provides migration path
✅ Can add filtering/transformation

### Cons
❌ Additional service to maintain
❌ Extra hop adds latency
❌ Potential bottleneck
❌ Duplicates data in Redis

---

## Solution 3: Unified Stream with Smart Consumer

### Implementation

```python
# src/gleitzeit/events/unified_stream_bus.py

class UnifiedStreamEventBus(StreamEventBus):
    """Event bus that can consume from both patterns."""
    
    def __init__(self, redis_client, use_unified_stream=False, **kwargs):
        super().__init__(redis_client, **kwargs)
        self.use_unified_stream = use_unified_stream
        self.unified_stream_key = f"{kwargs.get('key_prefix', 'gleitzeit')}:events:stream"
    
    async def _consume_events(self):
        """Consume from either unified or type-specific streams."""
        if self.use_unified_stream:
            await self._consume_unified_stream()
        else:
            await super()._consume_events()
    
    async def _consume_unified_stream(self):
        """Consume all events from single stream."""
        logger.info(f"Starting unified stream consumer for {self.consumer_id}")
        
        while self._running:
            try:
                messages = await self.redis.xreadgroup(
                    self.consumer_group,
                    self.consumer_id,
                    {self.unified_stream_key: ">"},
                    block=1000,
                    count=10
                )
                
                if not messages:
                    continue
                
                for stream_key, entries in messages:
                    for msg_id, data in entries:
                        # Extract event type from data
                        event_type = self._extract_event_type(data)
                        
                        # Check if we have handlers
                        if event_type not in self._handlers:
                            # ACK but don't process
                            await self.redis.xack(
                                self.unified_stream_key,
                                self.consumer_group,
                                msg_id
                            )
                            continue
                        
                        # Process the event
                        success = await self._process_event(
                            event_type, data, msg_id, self.unified_stream_key
                        )
                        
                        if success:
                            await self.redis.xack(
                                self.unified_stream_key,
                                self.consumer_group,
                                msg_id
                            )
                            
            except Exception as e:
                logger.error(f"Unified consumer error: {e}")
                await asyncio.sleep(1)
    
    def _extract_event_type(self, data: dict) -> str:
        """Extract event type from message data."""
        if isinstance(data.get("event_type"), bytes):
            return data["event_type"].decode()
        return data.get("event_type", "unknown")
```

### Pros
✅ Works with both patterns
✅ Smooth migration path
✅ Backward compatible

### Cons
❌ Loses per-type scalability
❌ All consumers see all events
❌ More complex consumer logic
❌ Performance impact from filtering

---

## Solution 4: Adapter Pattern with Factory

### Implementation

```python
# src/gleitzeit/events/stream_adapter.py

class StreamAdapter(ABC):
    """Abstract adapter for stream operations."""
    
    @abstractmethod
    async def emit(self, event_type: str, data: dict) -> str:
        pass
    
    @abstractmethod
    async def consume(self, event_types: List[str]) -> AsyncIterator[dict]:
        pass

class TypeSpecificStreamAdapter(StreamAdapter):
    """Adapter for type-specific streams."""
    
    def __init__(self, redis_client, prefix="gleitzeit"):
        self.redis = redis_client
        self.prefix = prefix
    
    async def emit(self, event_type: str, data: dict) -> str:
        stream_key = f"{self.prefix}:events:stream:{event_type}"
        return await self.redis.xadd(stream_key, data)
    
    async def consume(self, event_types: List[str]):
        streams = {
            f"{self.prefix}:events:stream:{et}": ">" 
            for et in event_types
        }
        # ... consumption logic ...

class UnifiedStreamAdapter(StreamAdapter):
    """Adapter for single unified stream."""
    
    def __init__(self, redis_client, prefix="gleitzeit"):
        self.redis = redis_client
        self.stream_key = f"{prefix}:events:stream"
    
    async def emit(self, event_type: str, data: dict) -> str:
        data["event_type"] = event_type
        return await self.redis.xadd(self.stream_key, data)
    
    async def consume(self, event_types: List[str]):
        # Read from single stream and filter
        # ... consumption logic ...

class StreamAdapterFactory:
    """Factory for creating appropriate stream adapter."""
    
    @staticmethod
    def create(mode: str, redis_client) -> StreamAdapter:
        if mode == "type_specific":
            return TypeSpecificStreamAdapter(redis_client)
        elif mode == "unified":
            return UnifiedStreamAdapter(redis_client)
        else:
            raise ValueError(f"Unknown mode: {mode}")

# Usage in both persistence and event bus
class ScalableRedisAdapter:
    def __init__(self, stream_mode="type_specific", ...):
        self.stream_adapter = StreamAdapterFactory.create(
            stream_mode, self.redis
        )
    
    async def _emit_event(self, event_type: str, data: dict):
        await self.stream_adapter.emit(event_type, data)

class StreamEventBus:
    def __init__(self, redis_client, stream_mode="type_specific", ...):
        self.stream_adapter = StreamAdapterFactory.create(
            stream_mode, redis_client
        )
```

### Pros
✅ Clean abstraction
✅ Both components use same pattern
✅ Easy to switch modes
✅ Testable

### Cons
❌ More code complexity
❌ Requires changes to both components
❌ Additional abstraction layer

---

## Solution 5: Configuration-Based Routing

### Implementation

```python
# src/gleitzeit/events/configurable_streams.py

class StreamConfig:
    """Configuration for stream behavior."""
    
    def __init__(self, config_dict: dict):
        self.mode = config_dict.get("mode", "type_specific")
        self.prefix = config_dict.get("prefix", "gleitzeit")
        self.routing_rules = config_dict.get("routing_rules", {})
    
    def get_stream_key(self, event_type: str) -> str:
        """Get stream key based on configuration."""
        if self.mode == "unified":
            return f"{self.prefix}:events:stream"
        elif self.mode == "type_specific":
            return f"{self.prefix}:events:stream:{event_type}"
        elif self.mode == "custom":
            # Use routing rules
            for pattern, key_template in self.routing_rules.items():
                if fnmatch.fnmatch(event_type, pattern):
                    return key_template.format(
                        prefix=self.prefix,
                        event_type=event_type
                    )
            # Default
            return f"{self.prefix}:events:stream:default"

# Example configuration
config = {
    "mode": "custom",
    "prefix": "gleitzeit",
    "routing_rules": {
        "task.*": "{prefix}:events:stream:tasks",
        "workflow.*": "{prefix}:events:stream:workflows",
        "system.*": "{prefix}:events:stream:system",
        "*": "{prefix}:events:stream:misc"
    }
}
```

### Pros
✅ Highly flexible
✅ No code changes for new patterns
✅ Can group related events

### Cons
❌ Configuration complexity
❌ Harder to debug
❌ Potential misconfiguration

---

## Recommended Approach

### Primary: Solution 1 (Fix ScalableRedisAdapter)
**Why:**
- Cleanest long-term solution
- Maintains architectural intent
- Best performance and scalability
- Least complexity

### Migration Strategy:
1. **Phase 1**: Deploy Solution 2 (Router) as temporary bridge
2. **Phase 2**: Update ScalableRedisAdapter with Solution 1
3. **Phase 3**: Remove router once migration complete

### Implementation Timeline:
- Day 1-2: Deploy router service
- Day 3-4: Update ScalableRedisAdapter
- Day 5: Testing and validation
- Day 6-7: Migration and cleanup

## Decision Matrix

| Solution | Complexity | Performance | Scalability | Migration | Maintenance |
|----------|------------|-------------|-------------|-----------|-------------|
| Fix Adapter | Low | High | High | Medium | Low |
| Router Service | Medium | Medium | Medium | Easy | Medium |
| Unified Consumer | Medium | Low | Low | Easy | Medium |
| Adapter Pattern | High | High | High | Hard | High |
| Config-Based | High | Medium | Medium | Medium | High |

## Conclusion

**Recommended: Fix ScalableRedisAdapter to emit to type-specific streams**

This maintains the scalable architecture while being the simplest solution. Use the router service as a temporary bridge during migration to ensure zero downtime.