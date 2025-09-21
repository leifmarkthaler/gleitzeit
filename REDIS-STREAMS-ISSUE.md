# Redis Streams Task Execution Issue

## Problem Description

The Gleitzeit system has been successfully migrated to a pure Redis Streams architecture using `XREADGROUP` with blocking operations (no polling loops), maintaining a stateless design. However, **tasks are not executing** - they remain stuck in "queued" state indefinitely.

### Architecture Overview

The system uses:
- **MultiplexedStreamConsumer**: A single consumer that monitors all event-type-specific streams using Redis `XREADGROUP` with `block=0` (indefinite blocking)
- **Event-type-specific streams**: Each event type has its own stream (e.g., `gleitzeit:events:stream:task:ready`)
- **Consumer Groups**: For reliable, distributed message processing
- **Self-registration pattern**: Components register their own event handlers dynamically

### Root Cause Analysis

The issue stems from a **race condition** in the handler registration timing:

1. **System Startup Sequence**:
   ```
   1. StreamSystemManager initializes
   2. MultiplexedStreamConsumer starts (begins consuming immediately)
   3. Base system components initialize
   4. ExecutionEngine creates StatelessTaskOrchestrator
   5. StatelessTaskOrchestrator registers handlers
   6. Handler registration happens AFTER consumer has started
   ```

2. **The Problem**:
   - When a workflow is submitted, `TASK_READY` events are emitted to the stream
   - The MultiplexedStreamConsumer's `XREADGROUP` consumes these messages immediately
   - But handlers aren't registered yet, so messages are consumed but not processed
   - Redis consumer groups guarantee each message is delivered only once per group
   - Once consumed, the messages are gone from the pending queue

3. **Evidence**:
   ```
   - TASK_READY events are being emitted (confirmed in logs)
   - Handlers are registered (confirmed: "Registered handler for event type: task:ready")
   - But tasks remain in "queued" state
   - No "Processing event task:ready" messages in logs
   ```

## Proposed Solutions

### Solution 1: Defer Consumer Start (Recommended)
**Approach**: Start the MultiplexedStreamConsumer AFTER all handlers are registered

**Implementation**:
```python
class StreamSystemManager:
    async def initialize(self):
        # Initialize consumer but DON'T start it
        self.stream_consumer = MultiplexedStreamConsumer(...)
        # Don't call self.stream_consumer.start() here

    async def start_system(self):
        # Initialize all components first
        await super().start_system()

        # NOW start the consumer after all handlers are registered
        if hasattr(self, 'stream_consumer'):
            await self.stream_consumer.start()
```

**Pros**:
- Simple, clean solution
- Guarantees no messages are consumed before handlers are ready
- No complex recovery logic needed

**Cons**:
- Brief window where events could accumulate in streams
- Requires careful orchestration of startup sequence

### Solution 2: Pending Message Recovery (Current Attempt)
**Approach**: Check for pending messages when handlers register

**Implementation**:
```python
def register_handler(self, event_type: str, handler: Callable):
    # Register handler
    self.handlers[event_type].append(handler)

    # Process any pending messages
    if self.running:
        asyncio.create_task(self._process_pending_for_type(event_type))
```

**Issue with Current Implementation**:
- `xpending_range` returns messages that were delivered but not acknowledged
- But our consumer auto-acknowledges messages even when no handler exists
- Need to change to NOT acknowledge messages when no handler is found

**Pros**:
- Handles dynamic handler registration
- Can recover from missed messages

**Cons**:
- More complex
- Requires careful handling of acknowledgments
- Race conditions still possible

### Solution 3: Handler Pre-Registration
**Approach**: Register all handlers before any component initialization

**Implementation**:
```python
class StreamSystemManager:
    async def initialize(self):
        # Pre-register all known handlers
        self._pre_register_handlers()

        # Then initialize consumer
        await self._initialize_multiplexed_consumer()

    def _pre_register_handlers(self):
        # Register handler stubs for all known event types
        for event_type in KNOWN_EVENT_TYPES:
            self.register_event_handler(event_type, self._queue_for_later)
```

**Pros**:
- No missed messages
- Consumer can start immediately

**Cons**:
- Requires maintaining list of all event types
- Need temporary queueing mechanism
- More complex handler management

### Solution 4: Two-Phase Acknowledgment
**Approach**: Only acknowledge messages after successful processing

**Implementation**:
```python
async def handle_message(self, stream_key: str, msg_id: str, data: Dict):
    try:
        handlers = self.handlers.get(event_type, [])

        if not handlers:
            # DON'T acknowledge - leave in pending
            logger.warning(f"No handlers for {event_type}, leaving in pending")
            return

        # Process with handlers
        for handler in handlers:
            await handler(event)

        # Only acknowledge after successful processing
        await self.redis.xack(stream_key, self.consumer_group, msg_id)
```

**Pros**:
- Messages aren't lost if no handler exists
- Natural retry mechanism via pending list
- Handles dynamic handler registration

**Cons**:
- Pending messages accumulate if handlers are never registered
- Need periodic pending message cleanup
- More complex error handling

## Recommendation

**Implement Solution 1 (Defer Consumer Start)** as the primary fix, combined with **Solution 4 (Two-Phase Acknowledgment)** for robustness.

This combination:
1. Prevents the race condition during startup
2. Handles any edge cases where handlers might be temporarily unavailable
3. Maintains the pure Redis Streams architecture with no polling
4. Keeps the stateless design intact

## Implementation Steps

1. Modify `StreamSystemManager` to defer consumer start
2. Update `MultiplexedStreamConsumer.handle_message()` to only acknowledge after successful processing
3. Add periodic cleanup for old pending messages (via Redis XPENDING and XCLAIM)
4. Test with workflow execution to verify tasks actually run
5. Add startup sequencing logs for debugging

## Testing Strategy

1. Start server fresh (no existing messages)
2. Submit a workflow
3. Verify tasks transition from "queued" → "running" → "completed"
4. Check logs for "Processing event task:ready" messages
5. Verify no "No handlers registered" warnings for critical events