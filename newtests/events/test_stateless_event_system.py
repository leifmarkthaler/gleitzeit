"""
Tests for the stateless event system.

Verifies that handlers are persisted, events are processed correctly,
and the system can recover from restarts.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from gleitzeit.events.stateless_bus import StatelessEventBus, HandlerConfig
from gleitzeit.events.base import EventBus
from gleitzeit.core.events import GleitzeitEvent, EventType
from gleitzeit.persistence.unified_persistence import UnifiedInMemoryAdapter


# Global handlers that can be imported (avoid test_ prefix to prevent pytest from treating as tests)
async def global_handler(event):
    """Global test handler that can be imported."""
    return f"Handled {event.event_type}"

handler_calls = []

async def tracking_handler(event):
    """Global handler that tracks calls."""
    handler_calls.append(event.data)
    return "success"

execution_order = []

async def high_priority_handler(event):
    """High priority test handler."""
    execution_order.append("high")

async def low_priority_handler(event):
    """Low priority test handler."""
    execution_order.append("low")

filtered_calls = []
unfiltered_calls = []

async def filtered_handler(event):
    """Handler for filter testing."""
    filtered_calls.append(event.data)

async def unfiltered_handler(event):
    """Handler for filter testing."""
    unfiltered_calls.append(event.data)

call_count = 0

async def once_handler(event):
    """One-time handler for testing."""
    global call_count
    call_count += 1

async def failing_handler(event):
    """Handler that always fails."""
    raise ValueError("Test error")

async def persistent_handler(event):
    """Handler for persistence testing."""
    return "persistent"


class TestStatelessEventBus:
    """Test the StatelessEventBus implementation."""
    
    @pytest.fixture
    async def persistence(self):
        """Create in-memory persistence with Redis-like interface."""
        persistence = UnifiedInMemoryAdapter()
        
        # Add Redis-like interface for testing
        class MockRedis:
            def __init__(self):
                self.data = {}
                self.sets = {}
                self.sorted_sets = {}
                self.lists = {}
            
            async def hset(self, key, *args, mapping=None, **kwargs):
                # Handle different call patterns: hset(key, field, value) or hset(key, mapping=dict)
                if args:
                    # Called as hset(key, field, value, field2, value2, ...)
                    if len(args) % 2 != 0:
                        raise ValueError("hset requires an even number of field/value pairs")
                    for i in range(0, len(args), 2):
                        kwargs[args[i]] = args[i + 1]
                
                if mapping:
                    kwargs.update(mapping)
                
                if key not in self.data:
                    self.data[key] = {}
                self.data[key].update(kwargs)
                return len(kwargs)
            
            async def hgetall(self, key):
                return self.data.get(key, {})
            
            async def hincrby(self, key, field, amount=1):
                if key not in self.data:
                    self.data[key] = {}
                current = int(self.data[key].get(field, 0))
                self.data[key][field] = str(current + amount)
                return current + amount
            
            async def sadd(self, key, *values):
                if key not in self.sets:
                    self.sets[key] = set()
                self.sets[key].update(values)
                return len(values)
            
            async def smembers(self, key):
                return list(self.sets.get(key, set()))
            
            async def srem(self, key, *values):
                if key in self.sets:
                    removed = len(self.sets[key].intersection(values))
                    self.sets[key] -= set(values)
                    return removed
                return 0
            
            async def zadd(self, key, mapping):
                if key not in self.sorted_sets:
                    self.sorted_sets[key] = []
                for member, score in mapping.items():
                    # Remove existing and add with new score
                    self.sorted_sets[key] = [
                        (m, s) for m, s in self.sorted_sets[key] if m != member
                    ]
                    self.sorted_sets[key].append((member, score))
                # Sort by score
                self.sorted_sets[key].sort(key=lambda x: x[1])
                return len(mapping)
            
            async def zrange(self, key, start, stop):
                if key not in self.sorted_sets:
                    return []
                items = self.sorted_sets[key]
                if stop == -1:
                    stop = len(items)
                return [item[0] for item in items[start:stop + 1]]
            
            async def zrem(self, key, *members):
                if key in self.sorted_sets:
                    before = len(self.sorted_sets[key])
                    self.sorted_sets[key] = [
                        (m, s) for m, s in self.sorted_sets[key] 
                        if m not in members
                    ]
                    return before - len(self.sorted_sets[key])
                return 0
            
            async def lpush(self, key, *values):
                if key not in self.lists:
                    self.lists[key] = []
                for value in values:
                    self.lists[key].insert(0, value)
                return len(self.lists[key])
            
            async def lrange(self, key, start, stop):
                if key not in self.lists:
                    return []
                items = self.lists[key]
                if stop == -1:
                    stop = len(items)
                return items[start:stop + 1]
            
            async def ltrim(self, key, start, stop):
                if key in self.lists:
                    items = self.lists[key]
                    if stop == -1:
                        stop = len(items)
                    self.lists[key] = items[start:stop + 1]
                return True
            
            async def delete(self, *keys):
                count = 0
                for key in keys:
                    if key in self.data:
                        del self.data[key]
                        count += 1
                    if key in self.sets:
                        del self.sets[key]
                        count += 1
                    if key in self.sorted_sets:
                        del self.sorted_sets[key]
                        count += 1
                    if key in self.lists:
                        del self.lists[key]
                        count += 1
                return count
            
            async def expire(self, key, seconds):
                # Mock implementation - just return True
                return True
            
            async def scan(self, cursor, match=None, count=100):
                # Simple scan implementation
                all_keys = list(self.data.keys())
                if match:
                    import fnmatch
                    all_keys = [k for k in all_keys if fnmatch.fnmatch(k, match)]
                
                # Return all keys in one batch for testing
                return 0, all_keys
        
        persistence.redis = MockRedis()
        return persistence
    
    @pytest.fixture
    async def event_bus(self, persistence):
        """Create stateless event bus."""
        bus = StatelessEventBus(persistence=persistence)
        await bus.start()
        return bus
    
    @pytest.fixture(autouse=True)
    async def reset_globals(self):
        """Reset global test state before each test."""
        global handler_calls, execution_order, filtered_calls, unfiltered_calls, call_count
        handler_calls.clear()
        execution_order.clear()
        filtered_calls.clear()
        unfiltered_calls.clear()
        call_count = 0

    @pytest.mark.asyncio
    async def test_handler_registration(self, event_bus):
        """Test that handlers can be registered and retrieved."""        
        # Register handler using centralized EventType
        handler_id = await event_bus.register_handler(
            EventType.TASK_STARTED, 
            global_handler, 
            priority=1
        )
        
        assert handler_id.startswith("handler_")
        
        # Retrieve handlers
        handlers = await event_bus.get_handlers(EventType.TASK_STARTED.value)
        assert len(handlers) == 1
        assert handlers[0].handler_id == handler_id
        assert handlers[0].event_type == EventType.TASK_STARTED.value
        assert handlers[0].priority == 1
    
    @pytest.mark.asyncio
    async def test_event_emission(self, event_bus):
        """Test that events are emitted to registered handlers."""        
        # Register handler using centralized EventType
        await event_bus.register_handler(EventType.TASK_COMPLETED, tracking_handler)
        
        # Emit event
        event = GleitzeitEvent(
            event_type=EventType.TASK_COMPLETED,
            data={"message": "test"}
        )
        await event_bus.emit(event)
        
        # Verify handler was called
        assert len(handler_calls) == 1
        assert handler_calls[0]["message"] == "test"
    
    @pytest.mark.asyncio
    async def test_handler_priority(self, event_bus):
        """Test that handlers are executed in priority order."""
        # Register handlers with different priorities
        await event_bus.register_handler(EventType.TASK_FAILED, low_priority_handler, priority=3)
        await event_bus.register_handler(EventType.TASK_FAILED, high_priority_handler, priority=1)
        
        # Emit event
        event = GleitzeitEvent(event_type=EventType.TASK_FAILED)
        await event_bus.emit(event)
        
        # High priority should execute first
        assert execution_order == ["high", "low"]
    
    @pytest.mark.asyncio
    async def test_handler_filter(self, event_bus):
        """Test that handler filters work correctly."""
        # Register handlers - one with filter
        await event_bus.register_handler(EventType.TASK_STARTED, unfiltered_handler)
        await event_bus.register_handler(
            EventType.TASK_STARTED, 
            filtered_handler,
            filter_expr="data.get('filtered') == True"
        )
        
        # Emit events
        await event_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_STARTED,
            data={"filtered": False}
        ))
        
        await event_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_STARTED, 
            data={"filtered": True}
        ))
        
        # Check results
        assert len(unfiltered_calls) == 2
        assert len(filtered_calls) == 1
        assert filtered_calls[0]["filtered"] is True
    
    @pytest.mark.asyncio
    async def test_one_time_handlers(self, event_bus):
        """Test that one-time handlers are removed after execution."""        
        # Register one-time handler
        handler_id = await event_bus.register_handler(
            EventType.TASK_CANCELLED, 
            once_handler, 
            once=True
        )
        
        # Emit event twice
        event = GleitzeitEvent(event_type=EventType.TASK_CANCELLED)
        await event_bus.emit(event)
        await event_bus.emit(event)
        
        # Handler should only be called once
        assert call_count == 1
        
        # Handler should be unregistered
        handlers = await event_bus.get_handlers(EventType.TASK_CANCELLED.value)
        assert len(handlers) == 0
    
    @pytest.mark.asyncio
    async def test_error_tracking(self, event_bus):
        """Test that handler errors are tracked."""
        # Register failing handler
        await event_bus.register_handler(EventType.HEALTH_CHECK_STARTED, failing_handler)
        
        # Emit event (should handle error gracefully)
        event = GleitzeitEvent(event_type=EventType.HEALTH_CHECK_STARTED)
        
        # Should not raise exception (error isolation)
        await event_bus.emit(event)
        
        # Check error history
        errors = await event_bus.get_error_history(limit=10)
        assert len(errors) == 1
        assert "Test error" in errors[0]["error_message"]
    
    @pytest.mark.asyncio
    async def test_metrics_collection(self, event_bus):
        """Test that metrics are collected properly."""
        # Register handler
        handler_id = await event_bus.register_handler(EventType.PROVIDER_STARTED, tracking_handler)
        
        # Emit events
        event = GleitzeitEvent(event_type=EventType.PROVIDER_STARTED)
        await event_bus.emit(event)
        await event_bus.emit(event)
        
        # Check metrics
        metrics = await event_bus.get_metrics(handler_id)
        assert metrics["call_count"] == 2
        assert metrics["success_count"] == 2
        assert "last_activity" in metrics
    
    @pytest.mark.asyncio
    async def test_handler_persistence(self, event_bus, persistence):
        """Test that handlers persist and can be recovered."""
        # Register handler
        handler_id = await event_bus.register_handler(EventType.WORKFLOW_STARTED, persistent_handler)
        
        # Create new event bus instance (simulating restart)
        new_bus = StatelessEventBus(persistence=persistence)
        await new_bus.start()
        
        # Should be able to retrieve handlers from persistence
        handlers = await new_bus.get_handlers(EventType.WORKFLOW_STARTED.value) 
        assert len(handlers) == 1
        assert handlers[0].handler_id == handler_id


class TestEventBusStatelessMode:
    """Test the EventBus in stateless mode."""
    
    @pytest.fixture
    async def persistence(self):
        """Create mock persistence with Redis interface."""
        persistence = UnifiedInMemoryAdapter()
        
        # Add mock Redis
        class MockRedis:
            def __init__(self):
                self.connected = True
                
        persistence.redis = MockRedis()
        return persistence
    
    @pytest.mark.asyncio
    async def test_auto_detection_stateless_mode(self, persistence):
        """Test that EventBus auto-detects stateless mode when Redis is available."""
        # Create EventBus with persistence
        bus = EventBus(persistence=persistence)
        
        # Should auto-detect stateless mode
        assert bus.stateless is True
        assert bus._stateless_bus is not None
    
    @pytest.mark.asyncio
    async def test_always_stateless_mode(self, persistence):
        """Test that EventBus is always stateless now."""
        # EventBus is always stateless now
        bus = EventBus(persistence=persistence)
        
        assert bus.stateless is True
        assert bus._stateless_bus is not None
    
    @pytest.mark.asyncio
    async def test_stateless_event_emission(self, persistence):
        """Test event emission in stateless mode."""
        # Mock the stateless bus
        mock_stateless_bus = AsyncMock()
        
        bus = EventBus(persistence=persistence)
        bus._stateless_bus = mock_stateless_bus
        # Note: bus.stateless is always True now (property)
        
        # Emit event
        event = GleitzeitEvent(event_type=EventType.ENGINE_STARTED)
        await bus.emit(event)
        
        # Should delegate to stateless bus
        mock_stateless_bus.emit.assert_called_once_with(event)


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])