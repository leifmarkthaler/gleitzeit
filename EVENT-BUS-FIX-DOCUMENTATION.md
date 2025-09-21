# StreamEventBus EventType Handling Fix

## Issue Summary
The StreamEventBus was failing to process events after Redis was flushed because of a mismatch between how EventType enums were being handled during registration vs. consumption.

## Root Cause
1. **EventType Enum String Representation**: When EventType enums were passed to the event bus, they were being converted to their string representation (e.g., "EventType.WORKFLOW_SUBMITTED") instead of their actual value (e.g., "workflow:submitted")
2. **Stream Key Mismatch**: The stream keys were being built using the string representation, creating keys like `gleitzeit:events:stream:EventType.WORKFLOW_SUBMITTED` instead of `gleitzeit:events:stream:workflow:submitted`
3. **Handler Lookup Failure**: Handlers were registered with one format but looked up with another, causing events to be consumed but not processed

## Applied Fixes

### 1. Removed In-Memory Fallbacks
**Files Modified:**
- `src/gleitzeit/task_queue/task_queue.py`
- `src/gleitzeit/core/workflow_manager_factory.py`
- `src/gleitzeit/system/system_manager.py`
- `src/gleitzeit/persistence/factory.py`

**Changes:**
- Removed all UnifiedInMemoryAdapter imports and fallback logic
- Added ConfigurationError when Redis is not available
- Ensured persistence is always passed to components that need it

### 2. Fixed StreamEventBus EventType Handling
**File Modified:** `src/gleitzeit/events/stream_event_bus.py`

**Changes Applied:**
```python
# In register() method:
if hasattr(event_type, 'value'):
    event_type = event_type.value

# In unregister() method:  
if hasattr(event_type, 'value'):
    event_type = event_type.value

# In _ensure_consumer_group() method:
if hasattr(event_type, 'value'):
    event_type = event_type.value
    
# In _get_stream_key() method:
if hasattr(event_type, 'value'):
    event_type = event_type.value

# In _consume_events() and _claim_idle_messages() loops:
normalized_type = event_type.value if hasattr(event_type, 'value') else event_type
```

### 3. Added Consumer Group Recreation
The consume loop now ensures consumer groups exist before attempting to read from streams, handling the case where Redis is flushed after server startup.

## Verification
After applying fixes:
1. Server successfully processes WORKFLOW_SUBMITTED events
2. Tasks progress from PENDING to QUEUED states
3. Consumer groups are recreated automatically after Redis flush
4. Event handlers are properly invoked

## Audit for More Durable Solution

### Current Solution Strengths
1. **Defensive Programming**: Multiple normalization points ensure EventType enums are handled correctly
2. **Backward Compatible**: Works with both string event types and EventType enums
3. **Self-Healing**: Consumer groups are recreated automatically when missing

### Potential Improvements

#### 1. **Type Consistency at API Boundary**
**Issue**: EventType normalization happens at multiple points
**Better Solution**: Normalize once at the public API boundary

```python
class StreamEventBus:
    def register(self, event_type: Union[str, EventType], handler: Callable) -> None:
        event_type = self._normalize_event_type(event_type)
        # Rest of method uses normalized string
        
    def _normalize_event_type(self, event_type: Union[str, EventType]) -> str:
        """Single normalization point for all event types."""
        if isinstance(event_type, EventType):
            return event_type.value
        elif hasattr(event_type, 'value'):  # Duck typing for other enums
            return event_type.value
        return str(event_type)
```

#### 2. **Explicit Type Hints**
**Issue**: Type hints don't reflect that enums are accepted
**Better Solution**: Use Union types in signatures

```python
from typing import Union

async def emit(self, event: GleitzeitEvent) -> str:
    # event.event_type should already be normalized by GleitzeitEvent

def register(self, event_type: Union[str, EventType], handler: Callable) -> None:
    # Clear that both types are accepted
```

#### 3. **Consumer Group Management**
**Issue**: Consumer groups checked/created in multiple places
**Better Solution**: Centralized consumer group lifecycle management

```python
class ConsumerGroupManager:
    """Manages Redis consumer group lifecycle."""
    
    async def ensure_group_exists(self, stream_key: str, group: str):
        """Idempotently ensure consumer group exists."""
        
    async def recreate_all_groups(self, handlers: Dict[str, List]):
        """Recreate all consumer groups after Redis flush."""
```

#### 4. **Event Type Validation**
**Issue**: No validation that event types follow expected format
**Better Solution**: Validate event types match expected patterns

```python
def _validate_event_type(self, event_type: str) -> bool:
    """Validate event type follows component:action format."""
    import re
    pattern = r'^[a-z]+:[a-z_]+$'
    return bool(re.match(pattern, event_type))
```

#### 5. **Stream Key Abstraction**
**Issue**: Stream key generation logic scattered
**Better Solution**: Dedicated stream key builder

```python
class StreamKeyBuilder:
    """Builds Redis stream keys consistently."""
    
    PREFIX = "gleitzeit:events:stream"
    
    @classmethod
    def build(cls, event_type: str) -> str:
        return f"{cls.PREFIX}:{event_type}"
        
    @classmethod
    def extract_event_type(cls, stream_key: str) -> str:
        return stream_key.replace(f"{cls.PREFIX}:", "")
```

## Recommendations

### Immediate Actions (Already Applied)
✅ Fix EventType enum handling in StreamEventBus
✅ Remove in-memory fallbacks
✅ Ensure consumer groups are recreated after Redis flush

### Short-term Improvements (Recommended)
1. **Centralize Normalization**: Create a single `_normalize_event_type()` method used by all public methods
2. **Update Type Hints**: Change signatures to `Union[str, EventType]` for clarity
3. **Add Validation**: Validate event types follow the expected format

### Long-term Improvements (Consider)
1. **Refactor Event System**: Consider making GleitzeitEvent always store event_type as string (the enum value)
2. **Consumer Group Manager**: Extract consumer group management to a dedicated class
3. **Stream Key Builder**: Abstract stream key generation to prevent inconsistencies
4. **Integration Tests**: Add tests that specifically verify behavior after Redis flush

## Testing Recommendations

### Unit Tests Needed
```python
def test_event_type_enum_handling():
    """Test that EventType enums are properly normalized."""
    
def test_consumer_group_recreation():
    """Test that consumer groups are recreated after Redis flush."""
    
def test_event_handler_matching():
    """Test that handlers registered with enums match events."""
```

### Integration Tests Needed
```python
def test_redis_flush_recovery():
    """Test full system recovery after Redis FLUSHALL."""
    
def test_event_processing_after_restart():
    """Test that pending events are processed after restart."""
```

## Conclusion

The current fixes solve the immediate problem and make the system functional. The StreamEventBus now correctly handles EventType enums and recovers from Redis flushes. 

However, for long-term maintainability, consider:
1. Centralizing the EventType normalization logic
2. Making the type system more explicit about accepting both strings and enums
3. Adding comprehensive tests for Redis flush scenarios

The system is now more robust but could benefit from the architectural improvements outlined above to prevent similar issues in the future.