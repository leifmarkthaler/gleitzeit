"""
Test Event-Driven Retry Manager

Tests the retry functionality with the new event-driven architecture.
"""

import asyncio
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from gleitzeit.core.models import Task, TaskStatus, RetryConfig
from gleitzeit.core.events import EventType, GleitzeitEvent, create_task_failed_event
from gleitzeit.core.event_driven_retry_manager import EventDrivenRetryManager, BackoffStrategy
from gleitzeit.events.base import EventBus
from gleitzeit.persistence.base import InMemoryBackend


@pytest.fixture
async def setup_retry_manager():
    """Set up retry manager with event bus and persistence"""
    persistence = InMemoryBackend()
    event_bus = EventBus()
    scheduler = None  # We'll test without scheduler for simplicity
    
    retry_manager = EventDrivenRetryManager(
        persistence=persistence,
        scheduler=scheduler,
        event_bus=event_bus
    )
    
    return retry_manager, persistence, event_bus


@pytest.mark.asyncio
async def test_retry_on_failure(setup_retry_manager):
    """Test that task failure triggers retry scheduling"""
    retry_manager, persistence, event_bus = setup_retry_manager
    
    # Create a task with retry config
    task = Task(
        id="test-task-1",
        name="Test Task",
        protocol="test",
        method="fail_once",
        retry_config=RetryConfig(
            max_attempts=3,
            backoff_strategy="exponential",
            base_delay=1.0,
            max_delay=10.0,
            jitter=False
        )
    )
    
    # Save task to persistence
    await persistence.save_task(task)
    
    # Track emitted events
    emitted_events = []
    async def capture_event(event):
        emitted_events.append(event)
    
    event_bus.register(EventType.RETRY_SCHEDULED, capture_event)
    
    # Emit TASK_FAILED event
    failed_event = create_task_failed_event(
        task_id=task.id,
        workflow_id=None,
        error_message="Test failure",
        error_type="TestError",
        is_retryable=True,
        attempt_number=1
    )
    
    await event_bus.emit(failed_event)
    
    # Give event handlers time to process
    await asyncio.sleep(0.1)
    
    # Check task was updated to RETRY_PENDING
    updated_task = await persistence.get_task(task.id)
    assert updated_task.status == TaskStatus.RETRY_PENDING
    assert updated_task.metadata['retry_attempt'] == 2
    assert 'retry_at' in updated_task.metadata
    assert updated_task.metadata['last_error'] == "Test failure"
    
    # Check RETRY_SCHEDULED event was emitted
    assert len(emitted_events) == 1
    assert emitted_events[0].event_type == EventType.RETRY_SCHEDULED
    assert emitted_events[0].data['task_id'] == task.id
    assert emitted_events[0].data['attempt_number'] == 2


@pytest.mark.asyncio
async def test_max_retries_exceeded(setup_retry_manager):
    """Test that max retries are enforced"""
    retry_manager, persistence, event_bus = setup_retry_manager
    
    # Create a task with low max attempts
    task = Task(
        id="test-task-2",
        name="Test Task",
        protocol="test",
        method="always_fail",
        retry_config=RetryConfig(
            max_attempts=2,
            backoff_strategy="fixed",
            base_delay=1.0
        )
    )
    
    await persistence.save_task(task)
    
    # Track permanent failure events
    permanent_failures = []
    async def capture_permanent_failure(event):
        if event.data.get('is_permanent'):
            permanent_failures.append(event)
    
    event_bus.register(EventType.TASK_FAILED, capture_permanent_failure)
    
    # Emit TASK_FAILED with attempt_number at max
    failed_event = create_task_failed_event(
        task_id=task.id,
        workflow_id=None,
        error_message="Final failure",
        error_type="TestError",
        is_retryable=True,
        attempt_number=2  # Already at max attempts
    )
    
    await event_bus.emit(failed_event)
    await asyncio.sleep(0.1)
    
    # Check task marked as permanently failed
    updated_task = await persistence.get_task(task.id)
    assert updated_task.status == TaskStatus.FAILED
    assert updated_task.metadata.get('max_retries_reached') == True
    assert updated_task.metadata.get('final_error') == "Final failure"
    
    # Check permanent failure event emitted
    assert len(permanent_failures) == 1
    assert permanent_failures[0].data['is_permanent'] == True


@pytest.mark.asyncio
async def test_non_retryable_error(setup_retry_manager):
    """Test that non-retryable errors don't trigger retry"""
    retry_manager, persistence, event_bus = setup_retry_manager
    
    task = Task(
        id="test-task-3",
        name="Test Task",
        protocol="test",
        method="invalid_params",
        retry_config=RetryConfig(
            max_attempts=3,
            backoff_strategy="exponential",
            base_delay=1.0
        )
    )
    
    await persistence.save_task(task)
    
    # Track events
    retry_events = []
    async def capture_retry(event):
        retry_events.append(event)
    
    event_bus.register(EventType.RETRY_SCHEDULED, capture_retry)
    
    # Emit non-retryable failure
    failed_event = create_task_failed_event(
        task_id=task.id,
        workflow_id=None,
        error_message="Invalid parameters",
        error_type="ValidationError",
        is_retryable=False,  # Non-retryable
        attempt_number=1
    )
    
    await event_bus.emit(failed_event)
    await asyncio.sleep(0.1)
    
    # Check no retry was scheduled
    assert len(retry_events) == 0
    
    # Task should remain in its original state
    updated_task = await persistence.get_task(task.id)
    assert updated_task.status == TaskStatus.PENDING


@pytest.mark.asyncio
async def test_backoff_strategies(setup_retry_manager):
    """Test different backoff strategies"""
    retry_manager, persistence, event_bus = setup_retry_manager
    
    # Test fixed backoff
    delay = retry_manager._calculate_backoff(
        attempt=1,
        strategy="fixed",
        base_delay=2.0,
        max_delay=100.0,
        jitter=False
    )
    assert delay == 2.0
    
    delay = retry_manager._calculate_backoff(
        attempt=3,
        strategy="fixed",
        base_delay=2.0,
        max_delay=100.0,
        jitter=False
    )
    assert delay == 2.0
    
    # Test linear backoff
    delay = retry_manager._calculate_backoff(
        attempt=1,
        strategy="linear",
        base_delay=2.0,
        max_delay=100.0,
        jitter=False
    )
    assert delay == 2.0
    
    delay = retry_manager._calculate_backoff(
        attempt=3,
        strategy="linear",
        base_delay=2.0,
        max_delay=100.0,
        jitter=False
    )
    assert delay == 6.0
    
    # Test exponential backoff
    delay = retry_manager._calculate_backoff(
        attempt=1,
        strategy="exponential",
        base_delay=2.0,
        max_delay=100.0,
        jitter=False
    )
    assert delay == 2.0
    
    delay = retry_manager._calculate_backoff(
        attempt=3,
        strategy="exponential",
        base_delay=2.0,
        max_delay=100.0,
        jitter=False
    )
    assert delay == 8.0  # 2 * (2^2)
    
    # Test max delay cap
    delay = retry_manager._calculate_backoff(
        attempt=10,
        strategy="exponential",
        base_delay=2.0,
        max_delay=100.0,
        jitter=False
    )
    assert delay == 100.0  # Capped at max
    
    # Test jitter
    delay1 = retry_manager._calculate_backoff(
        attempt=2,
        strategy="fixed",
        base_delay=10.0,
        max_delay=100.0,
        jitter=True
    )
    delay2 = retry_manager._calculate_backoff(
        attempt=2,
        strategy="fixed",
        base_delay=10.0,
        max_delay=100.0,
        jitter=True
    )
    # With jitter, delays should vary
    assert 8.0 <= delay1 <= 12.0  # ±20% jitter
    assert 8.0 <= delay2 <= 12.0
    # Very unlikely to be exactly the same with jitter
    # (but not impossible, so we don't assert inequality)


@pytest.mark.asyncio
async def test_retry_trigger(setup_retry_manager):
    """Test that retry trigger updates task status correctly"""
    retry_manager, persistence, event_bus = setup_retry_manager
    
    # Create a task in RETRY_PENDING state
    task = Task(
        id="test-task-4",
        name="Test Task",
        protocol="test",
        method="retry_me",
        status=TaskStatus.RETRY_PENDING,
        metadata={
            'retry_attempt': 2,
            'retry_at': datetime.utcnow().isoformat()
        }
    )
    
    await persistence.save_task(task)
    
    # Track TASK_READY_FOR_RETRY events
    ready_events = []
    async def capture_ready(event):
        ready_events.append(event)
    
    event_bus.register(EventType.TASK_READY_FOR_RETRY, capture_ready)
    
    # Trigger the retry
    await retry_manager._trigger_retry(task.id)
    
    # Check task updated to QUEUED
    updated_task = await persistence.get_task(task.id)
    assert updated_task.status == TaskStatus.QUEUED
    
    # Check TASK_READY_FOR_RETRY event emitted
    assert len(ready_events) == 1
    assert ready_events[0].data['task_id'] == task.id
    assert ready_events[0].data['attempt_number'] == 2


if __name__ == "__main__":
    asyncio.run(pytest.main([__file__, "-v"]))