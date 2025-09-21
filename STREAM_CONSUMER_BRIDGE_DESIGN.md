# Stream Consumer Bridge Design
## Keeping Event-Type-Specific Streams

### Core Idea: Stream Consumer Bridge
Instead of changing how events are written, we create a bridge that connects event-type-specific streams to the StreamEventScheduler.

### Architecture

```
Event-Type Streams                    Processing Infrastructure
─────────────────                     ───────────────────────

workflow:submitted ──┐
                     │
task:completed ──────┼──> Stream Bridge ──> events:immediate ──> StreamEventScheduler
                     │     (XREAD/XADD)                           (already working!)
task:failed ─────────┘
```

### Solution: Stream Aggregator Pattern

#### Design
1. **Keep event-type-specific streams** for better organization and debugging
2. **StreamEventScheduler** continues processing `events:immediate`
3. **Add a Stream Bridge** that:
   - Monitors all event-type streams using XREAD
   - Forwards events to `events:immediate` with metadata
   - Preserves event type information in the payload

### Implementation Approach

#### Option A: Stream Fanout Consumer
Create a lightweight consumer that reads from multiple streams and writes to a single stream:

```python
class StreamFanoutConsumer:
    """
    Bridges event-type-specific streams to the main processing stream.
    Uses Redis XREAD to monitor multiple streams simultaneously.
    """

    async def bridge_streams(self):
        # Monitor all event streams at once
        streams = {
            'gleitzeit:events:stream:workflow:submitted': '>',
            'gleitzeit:events:stream:task:completed': '>',
            'gleitzeit:events:stream:task:failed': '>',
            # ... other streams
        }

        while True:
            # XREAD blocks until ANY stream has messages
            messages = await redis.xread(streams, block=0)

            for stream, stream_messages in messages:
                for msg_id, data in stream_messages:
                    # Forward to events:immediate
                    await redis.xadd('events:immediate', {
                        'source_stream': stream,
                        'original_id': msg_id,
                        **data
                    })
```

#### Option B: Redis Streams Rules (if using Redis 7.0+)
Use Redis Streams consumer group with XREADGROUP and automatic forwarding:

```lua
-- Redis Lua script to forward events
local source_stream = KEYS[1]
local target_stream = KEYS[2]
local messages = redis.call('XREAD', 'COUNT', 100, 'STREAMS', source_stream, '$')
for _, msg in ipairs(messages) do
    redis.call('XADD', target_stream, '*', unpack(msg[2]))
end
```

#### Option C: Stream Multiplexer with Consumer Groups
Enhance StatelessEventConsumer to handle multiple streams:

```python
class EnhancedStatelessEventConsumer:
    """
    Consumes from multiple event-type streams and routes to handlers.
    """

    async def consume_all_streams(self):
        # Get all registered event types
        stream_keys = self._get_all_stream_keys()

        # Create consumer groups for each stream
        for stream in stream_keys:
            await self._ensure_consumer_group(stream)

        # Use XREADGROUP on multiple streams
        streams = {stream: '>' for stream in stream_keys}

        messages = await redis.xreadgroup(
            self.consumer_group,
            self.consumer_id,
            streams,
            block=0  # Block indefinitely
        )

        # Process messages and invoke handlers
        for stream, messages in messages:
            for msg_id, data in messages:
                await self._process_message(stream, msg_id, data)
```

### Recommended Solution: Multi-Stream Consumer

#### Why This Works Best
1. **Preserves event-type streams** - Better debugging and organization
2. **No new infrastructure** - Uses existing Redis Streams features
3. **Efficient** - Single XREADGROUP call monitors all streams
4. **Scalable** - Consumer groups handle distribution

#### Implementation Plan

1. **Modify StreamEventScheduler** to monitor multiple streams:

```python
class StreamEventScheduler:
    def __init__(self, ...):
        # Add event-type streams to monitored streams
        self.event_streams = [
            'gleitzeit:events:stream:workflow:submitted',
            'gleitzeit:events:stream:task:completed',
            'gleitzeit:events:stream:task:failed',
            # ... more event types
        ]

    async def _process_events_loop(self):
        while self._running:
            # Process immediate events
            await self._process_stream_events(self.immediate_stream)

            # Process event-type streams
            for stream in self.event_streams:
                await self._process_stream_events(stream)

            # Process scheduled events
            await self._process_scheduled_events()
```

2. **Register handlers with StreamEventScheduler**:
   - When StatelessTaskOrchestrator registers handlers
   - Also register them with StreamEventScheduler
   - StreamEventScheduler routes events to appropriate handlers

3. **Connect the dots**:
   - StatelessEventBusAdapter continues writing to event-type streams
   - StreamEventScheduler consumes from these streams
   - Handlers get invoked when events arrive

### Alternative: Stream Processor Tasks

Create lightweight tasks that process specific streams:

```python
class StreamProcessorTask:
    """
    Processes a specific event stream.
    Runs as an asyncio task, blocks on XREADGROUP.
    """

    def __init__(self, stream_key, handlers):
        self.stream_key = stream_key
        self.handlers = handlers

    async def run(self):
        while True:
            # Block waiting for messages
            messages = await redis.xreadgroup(
                self.consumer_group,
                self.consumer_id,
                {self.stream_key: '>'},
                block=0
            )

            for msg_id, data in messages[0][1]:
                # Invoke handlers
                for handler in self.handlers:
                    await handler(data)

                # Acknowledge
                await redis.xack(self.stream_key, self.consumer_group, msg_id)
```

Then in StreamSystemManager:

```python
# Start processor tasks for each event type
for event_type in ['workflow:submitted', 'task:completed', 'task:failed']:
    stream_key = f'gleitzeit:events:stream:{event_type}'
    handlers = self.get_handlers_for_event(event_type)

    processor = StreamProcessorTask(stream_key, handlers)
    asyncio.create_task(processor.run())
```

### Benefits of This Approach

1. **Maintains event isolation** - Each event type has its own stream
2. **No polling** - Uses Redis blocking operations
3. **Parallel processing** - Multiple streams processed concurrently
4. **Clean architecture** - Clear separation of concerns
5. **Debugging friendly** - Can inspect individual event streams
6. **Backward compatible** - No changes to event emission

### Quick Implementation Path

1. Add event stream monitoring to StreamEventScheduler
2. Register StatelessTaskOrchestrator handlers with StreamEventScheduler
3. Ensure consumer groups are created for event streams
4. Test with existing workflow submission

This approach requires minimal changes while maintaining the benefits of event-type-specific streams.