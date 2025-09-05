"""
Example test showing direct StatelessEventBus usage for maximum performance.

This demonstrates how to use StatelessEventBus directly instead of going through
the EventBus wrapper, which can be more efficient for tests that need many 
event operations.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock

from gleitzeit.events.stateless_bus import StatelessEventBus
from gleitzeit.core.events import GleitzeitEvent, EventType
from gleitzeit.persistence.unified_persistence import UnifiedInMemoryAdapter


# Example handlers for direct stateless usage
direct_handler_calls = []

async def direct_tracking_handler(event):
    """Handler that tracks calls for direct usage."""
    direct_handler_calls.append(event.data)
    return "handled"

async def priority_handler_high(event):
    """High priority handler."""
    direct_handler_calls.append("high")

async def priority_handler_low(event):
    """Low priority handler.""" 
    direct_handler_calls.append("low")


class TestDirectStatelessUsage:
    """Test direct StatelessEventBus usage patterns."""
    
    @pytest.fixture
    async def persistence(self):
        """Create in-memory persistence with Redis-like interface."""
        persistence = UnifiedInMemoryAdapter()
        
        # Add mock Redis for testing
        class MockRedis:
            def __init__(self):
                self.data = {}
                self.sets = {}
                self.sorted_sets = {}
                self.lists = {}
                
            async def hset(self, key, *args, mapping=None, **kwargs):
                if args:
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
            
            async def zadd(self, key, mapping):
                if key not in self.sorted_sets:
                    self.sorted_sets[key] = []
                for member, score in mapping.items():
                    self.sorted_sets[key] = [
                        (m, s) for m, s in self.sorted_sets[key] if m != member
                    ]
                    self.sorted_sets[key].append((member, score))
                self.sorted_sets[key].sort(key=lambda x: x[1])
                return len(mapping)
            
            async def zrange(self, key, start, stop):
                if key not in self.sorted_sets:
                    return []
                items = self.sorted_sets[key]
                if stop == -1:
                    stop = len(items)
                return [item[0] for item in items[start:stop + 1]]
            
            async def sadd(self, key, *values):
                if key not in self.sets:
                    self.sets[key] = set()
                self.sets[key].update(values)
                return len(values)
            
            async def expire(self, key, seconds):
                return True
            
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
        
        persistence.redis = MockRedis()
        return persistence
    
    @pytest.fixture
    async def stateless_bus(self, persistence):
        """Create StatelessEventBus directly."""
        bus = StatelessEventBus(persistence=persistence)
        await bus.start()
        return bus
    
    @pytest.fixture(autouse=True)
    def reset_globals(self):
        """Reset global test state before each test."""
        direct_handler_calls.clear()
    
    @pytest.mark.asyncio
    async def test_direct_handler_registration(self, stateless_bus):
        """Test direct handler registration with StatelessEventBus."""
        # Register handler directly
        handler_id = await stateless_bus.register_handler(
            EventType.TASK_STARTED,
            direct_tracking_handler,
            priority=1
        )
        
        assert handler_id.startswith("handler_")
        
        # Emit event
        event = GleitzeitEvent(
            event_type=EventType.TASK_STARTED,
            data={"test": "direct"}
        )
        await stateless_bus.emit(event)
        
        # Verify handler was called
        assert len(direct_handler_calls) == 1
        assert direct_handler_calls[0]["test"] == "direct"
    
    @pytest.mark.asyncio
    async def test_direct_priority_handling(self, stateless_bus):
        """Test priority handling with direct StatelessEventBus usage."""
        # Register handlers with different priorities
        await stateless_bus.register_handler(
            EventType.TASK_COMPLETED,
            priority_handler_low,
            priority=3
        )
        await stateless_bus.register_handler(
            EventType.TASK_COMPLETED,
            priority_handler_high,
            priority=1
        )
        
        # Emit event
        event = GleitzeitEvent(event_type=EventType.TASK_COMPLETED)
        await stateless_bus.emit(event)
        
        # Verify execution order (high priority first)
        assert direct_handler_calls == ["high", "low"]
    
    @pytest.mark.asyncio
    async def test_direct_metrics_access(self, stateless_bus):
        """Test direct access to handler metrics."""
        # Register handler
        handler_id = await stateless_bus.register_handler(
            EventType.WORKFLOW_STARTED,
            direct_tracking_handler
        )
        
        # Emit multiple events
        for i in range(3):
            event = GleitzeitEvent(
                event_type=EventType.WORKFLOW_STARTED,
                data={"count": i}
            )
            await stateless_bus.emit(event)
        
        # Get metrics directly
        metrics = await stateless_bus.get_metrics(handler_id)
        
        assert metrics["call_count"] == 3
        assert metrics["success_count"] == 3
        assert "last_activity" in metrics
    
    @pytest.mark.asyncio
    async def test_direct_error_tracking(self, stateless_bus):
        """Test direct error tracking with StatelessEventBus."""
        async def failing_handler(event):
            raise ValueError("Direct test error")
        
        # Register failing handler
        await stateless_bus.register_handler(
            EventType.PROVIDER_ERROR,
            failing_handler
        )
        
        # Emit event (should handle error gracefully)
        event = GleitzeitEvent(event_type=EventType.PROVIDER_ERROR)
        await stateless_bus.emit(event)
        
        # Check error history directly
        errors = await stateless_bus.get_error_history(limit=5)
        assert len(errors) >= 1
        assert "Direct test error" in errors[0]["error_message"]
    
    @pytest.mark.asyncio
    async def test_direct_handler_filters(self, stateless_bus):
        """Test handler filters with direct StatelessEventBus usage."""
        # Register handler with filter
        await stateless_bus.register_handler(
            EventType.TASK_FAILED,
            direct_tracking_handler,
            filter_expr="data.get('severity') == 'critical'"
        )
        
        # Emit non-matching event
        await stateless_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_FAILED,
            data={"severity": "minor"}
        ))
        
        # Emit matching event  
        await stateless_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_FAILED,
            data={"severity": "critical", "message": "filtered"}
        ))
        
        # Only the matching event should have triggered the handler
        assert len(direct_handler_calls) == 1
        assert direct_handler_calls[0]["message"] == "filtered"


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])