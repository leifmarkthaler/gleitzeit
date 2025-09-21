# Stream-Only Architecture Design

## Problem Statement
- Events are being written to Redis Streams (e.g., `gleitzeit:events:stream:workflow:submitted`)
- Handlers are registered in StatelessTaskOrchestrator for these events
- But nothing is consuming the events from the streams
- We need a pure stream-based solution without polling loops (stateless)

## Current State Analysis

### What's Working
1. **Event Emission**: Events are correctly written to Redis Streams
   - WorkflowManager emits `WORKFLOW_SUBMITTED` event
   - StatelessEventBusAdapter writes to stream: `gleitzeit:events:stream:workflow:submitted`
   - 150+ events are sitting in the stream unprocessed

2. **Handler Registration**: StatelessTaskOrchestrator registers handlers
   - `_handle_workflow_submitted`
   - `_handle_task_completed`
   - `_handle_task_failed`

3. **Stream Infrastructure**: StreamEventScheduler exists and has processing loop
   - But it processes different streams (`events:immediate`, `events:scheduled`)
   - Not consuming from the event-type-specific streams

### What's Broken
1. **No Active Consumer**: The streams have events but no consumer is reading them
2. **Stream Mismatch**: StreamEventScheduler reads from different streams than where events are written
3. **Missing Connection**: No trigger to consume events when they're added to streams

## Proposed Solution: Redis Stream Consumer Workers

### Design Principles
1. **No Polling Loops**: Use Redis XREADGROUP with blocking to wait for messages
2. **Event-Driven**: Consumers block on Redis, wake up when messages arrive
3. **Stateless**: Each message consumption is independent
4. **Distributed**: Multiple consumers can share work via consumer groups

### Architecture

```
┌─────────────────┐
│ Workflow Submit │
└────────┬────────┘
         │
         v
┌─────────────────┐
│ WorkflowManager │
└────────┬────────┘
         │ emit event
         v
┌─────────────────────┐
│StatelessEventBusAdap│
└────────┬────────────┘
         │ XADD
         v
┌─────────────────────────┐
│   Redis Stream:         │
│   workflow:submitted    │
└────────┬────────────────┘
         │ XREADGROUP (blocking)
         v
┌─────────────────────────┐
│  Stream Worker Process  │
│  (Separate from API)    │
└────────┬────────────────┘
         │ invoke handler
         v
┌─────────────────────────┐
│ StatelessTaskOrchestrator│
│ _handle_workflow_submitted│
└─────────────────────────┘
```

### Implementation Options

#### Option 1: Dedicated Stream Workers (Recommended)
- Create separate worker processes that consume from streams
- Workers use `XREADGROUP` with blocking to wait for messages
- When message arrives, worker invokes the registered handler
- Multiple workers can run for scalability

**Pros:**
- True stream-based architecture
- Scales horizontally
- No polling, pure event-driven
- Clean separation of concerns

**Cons:**
- Requires separate worker processes

#### Option 2: Unified Stream Routing
- Modify event emission to route ALL events to StreamEventScheduler's streams
- Instead of `gleitzeit:events:stream:workflow:submitted`
- Write to `events:immediate` with event type in payload
- StreamEventScheduler already has processing loop for these streams

**Pros:**
- Uses existing StreamEventScheduler infrastructure
- No new components needed

**Cons:**
- Loses event-type-specific stream isolation
- All events go through same streams

#### Option 3: API-Triggered Processing
- After emitting event, API triggers a single consumption
- Use Redis XREADGROUP with timeout=0 (non-blocking)
- Process available messages immediately

**Pros:**
- No separate workers needed
- Immediate processing

**Cons:**
- Couples API request handling with event processing
- Could slow down API responses

## Recommended Implementation Plan

### Phase 1: Stream Worker Implementation
1. Create a `StreamWorker` class that:
   - Accepts a list of stream patterns to consume
   - Uses XREADGROUP with blocking
   - Routes messages to registered handlers
   - Handles acknowledgments and error recovery

2. Create a `gleitzeit worker` CLI command that:
   - Starts StreamWorker processes
   - Configures which streams to consume
   - Manages worker lifecycle

### Phase 2: Connect Handlers
1. StreamWorker discovers registered handlers from:
   - StatelessTaskOrchestrator handlers
   - QueueManager handlers
   - Other registered components

2. Worker invokes handlers when messages arrive

### Phase 3: Update Stream System Manager
1. StreamSystemManager spawns worker tasks
2. Workers run as background tasks (using asyncio)
3. Each worker blocks on XREADGROUP
4. No polling loops - pure Redis blocking operations

### Example Worker Code Structure

```python
class StreamWorker:
    async def consume_stream(self, stream_key: str):
        """Consume from a single stream using blocking XREADGROUP."""
        while self.running:
            try:
                # Block waiting for messages (no polling!)
                messages = await self.redis.xreadgroup(
                    self.consumer_group,
                    self.consumer_name,
                    {stream_key: '>'},
                    block=0  # Block indefinitely
                )

                for stream, stream_messages in messages:
                    for msg_id, data in stream_messages:
                        await self.process_message(stream, msg_id, data)
                        await self.redis.xack(stream, self.consumer_group, msg_id)

            except Exception as e:
                logger.error(f"Error consuming from {stream_key}: {e}")
```

### Integration Points

1. **StreamSystemManager**:
   - Starts StreamWorkers as background tasks
   - Each worker consumes specific stream patterns
   - No polling loops, just blocking Redis operations

2. **StatelessEventBusAdapter**:
   - Continues to write events to streams
   - No changes needed

3. **Handler Registration**:
   - Handlers stay registered as-is
   - StreamWorker looks up handlers by event type
   - Invokes appropriate handler when message consumed

## Benefits of This Approach

1. **True Stream Architecture**: Pure Redis Streams with blocking operations
2. **No Polling**: Workers block on XREADGROUP, wake on message arrival
3. **Stateless**: Each message processing is independent
4. **Scalable**: Add more workers for higher throughput
5. **Clean**: No hacky process_once() calls or trigger mechanisms
6. **Distributed**: Multiple instances can share work via consumer groups

## Migration Path

1. Implement StreamWorker class
2. Add worker startup to StreamSystemManager
3. Test with single stream (workflow:submitted)
4. Expand to all event streams
5. Remove any tick-based or polling mechanisms

This design provides a clean, scalable, stream-only architecture that maintains the stateless principles while ensuring events are processed.