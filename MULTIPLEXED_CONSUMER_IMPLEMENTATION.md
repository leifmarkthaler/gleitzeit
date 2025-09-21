# Multiplexed Stream Consumer Implementation Plan

## Overview
Implement a scalable stream consumer that monitors all event-type-specific streams with a single Redis XREADGROUP call.

## Implementation Steps

### Step 1: Create MultiplexedStreamConsumer Class

Location: `src/gleitzeit/events/multiplexed_stream_consumer.py`

**Features:**
- Single consumer monitoring all event streams
- Uses Redis XREADGROUP with multiple streams
- Routes events to registered handlers
- Handles acknowledgments and error recovery

**Key Methods:**
- `discover_streams()` - Find all event streams dynamically
- `consume_streams()` - Single blocking XREADGROUP for all streams
- `route_event()` - Route events to appropriate handlers
- `handle_event()` - Process individual events

### Step 2: Integrate with StreamSystemManager

**Changes to `src/gleitzeit/system/stream_system_manager.py`:**
- Initialize MultiplexedStreamConsumer
- Start consumer task during system startup
- Connect handlers from StatelessTaskOrchestrator

### Step 3: Connect Event Handlers

**Handler Registration Flow:**
1. StatelessTaskOrchestrator registers handlers
2. Handlers stored in central registry
3. MultiplexedStreamConsumer looks up handlers by event type
4. Events routed to appropriate handlers

### Step 4: Ensure Consumer Groups

**For each event stream:**
- Create consumer group if not exists
- Use consistent naming: `gleitzeit-processors`
- Handle BUSYGROUP errors gracefully

## Implementation Details

### MultiplexedStreamConsumer Core Logic

```python
class MultiplexedStreamConsumer:
    def __init__(self, redis, handlers_registry):
        self.redis = redis
        self.handlers = handlers_registry
        self.consumer_group = "gleitzeit-processors"
        self.consumer_id = f"consumer-{uuid.uuid4().hex[:8]}"
        self.running = False

    async def start(self):
        """Start the consumer task."""
        self.running = True
        # Discover all event streams
        self.streams = await self.discover_streams()

        # Ensure consumer groups exist
        for stream in self.streams:
            await self.ensure_consumer_group(stream)

        # Start consuming
        asyncio.create_task(self.consume_streams())

    async def discover_streams(self):
        """Discover all event-type streams."""
        # Get all event stream keys
        pattern = "gleitzeit:events:stream:*"
        streams = []
        cursor = 0

        while True:
            cursor, keys = await self.redis.scan(
                cursor, match=pattern, count=100
            )
            streams.extend(keys)
            if cursor == 0:
                break

        return streams

    async def consume_streams(self):
        """Main consumption loop using blocking XREADGROUP."""
        while self.running:
            try:
                # Build streams dict for XREADGROUP
                streams_dict = {stream: '>' for stream in self.streams}

                # Single call monitors ALL streams (blocking)
                messages = await self.redis.xreadgroup(
                    self.consumer_group,
                    self.consumer_id,
                    streams_dict,
                    count=100,  # Process up to 100 messages
                    block=0     # Block indefinitely
                )

                # Process messages
                for stream_key, stream_messages in messages:
                    for msg_id, data in stream_messages:
                        await self.handle_message(stream_key, msg_id, data)

            except Exception as e:
                logger.error(f"Consumer error: {e}")
                await asyncio.sleep(1)

    async def handle_message(self, stream_key, msg_id, data):
        """Process a single message."""
        try:
            # Extract event type from data
            event_type = data.get(b'event_type', b'').decode()

            # Get handlers for this event type
            handlers = self.handlers.get(event_type, [])

            # Invoke all handlers
            for handler in handlers:
                await handler(self.decode_event(data))

            # Acknowledge message
            await self.redis.xack(stream_key, self.consumer_group, msg_id)

        except Exception as e:
            logger.error(f"Error handling message {msg_id}: {e}")
```

### Integration Points

#### 1. StreamSystemManager Initialization

```python
# In stream_system_manager.py __init__
async def initialize_components(self):
    # ... existing initialization ...

    # Initialize multiplexed consumer
    self.stream_consumer = MultiplexedStreamConsumer(
        redis=self.persistence.redis,
        handlers_registry=self.event_handlers
    )

    # Register existing handlers
    self.register_core_handlers()

    # Start consumer
    await self.stream_consumer.start()
```

#### 2. Handler Registration

```python
# In stream_system_manager.py
def register_event_handler(self, event_type, handler):
    """Register handler for event type."""
    if event_type not in self.event_handlers:
        self.event_handlers[event_type] = []
    self.event_handlers[event_type].append(handler)
```

#### 3. Connect StatelessTaskOrchestrator Handlers

```python
# During orchestrator initialization
def register_orchestrator_handlers(orchestrator):
    system_manager.register_event_handler(
        'workflow:submitted',
        orchestrator._handle_workflow_submitted
    )
    system_manager.register_event_handler(
        'task:completed',
        orchestrator._handle_task_completed
    )
    # ... register other handlers
```

## Testing Plan

### Step 1: Verify Stream Discovery
- Check that all event streams are discovered
- Verify consumer groups are created

### Step 2: Test Event Consumption
- Submit a workflow
- Verify workflow:submitted event is consumed
- Check that handler is invoked

### Step 3: Test Task Execution
- Verify tasks move from pending to executing
- Check task completion events are processed

### Step 4: Load Testing
- Submit multiple workflows
- Verify all events are processed
- Check no events are lost

## Rollback Plan

If issues arise:
1. Consumer can be disabled via environment variable
2. Existing tick-based systems can take over
3. Events remain in streams for later processing

## Success Metrics

- All events in streams are consumed
- Workflows progress from pending to completed
- No polling loops running
- Single Redis connection for all streams
- Latency < 10ms per event

## Timeline

1. **5 minutes**: Create MultiplexedStreamConsumer class
2. **5 minutes**: Integrate with StreamSystemManager
3. **5 minutes**: Connect handlers and test
4. **5 minutes**: Debug and verify

Total: ~20 minutes to working solution