"""
Tests for Circuit Breaker implementation
"""

import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

from gleitzeit.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    CircuitOpenError
)


@pytest.mark.asyncio
async def test_circuit_breaker_closed_state():
    """Test circuit breaker in closed state (normal operation)"""
    config = CircuitBreakerConfig(failure_threshold=3)
    breaker = CircuitBreaker("test_service", config)

    # Successful calls should work normally
    async def success_func(x):
        return x * 2

    result = await breaker.call(success_func, 5)
    assert result == 10
    assert breaker.state == CircuitState.CLOSED
    assert breaker.stats.successful_calls == 1
    assert breaker.stats.failed_calls == 0


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_failures():
    """Test circuit breaker opens after threshold failures"""
    config = CircuitBreakerConfig(failure_threshold=3, reset_timeout=1)
    breaker = CircuitBreaker("test_service", config)

    # Function that always fails
    async def failing_func():
        raise Exception("Service error")

    # First failures should be allowed through
    for i in range(3):
        with pytest.raises(Exception, match="Service error"):
            await breaker.call(failing_func)

    # Circuit should now be open
    assert breaker.state == CircuitState.OPEN
    assert breaker.stats.failed_calls == 3

    # Next call should fail immediately with CircuitOpenError
    with pytest.raises(CircuitOpenError) as exc_info:
        await breaker.call(failing_func)

    assert "Circuit breaker for 'test_service' is OPEN" in str(exc_info.value)
    assert breaker.stats.rejected_calls == 1


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_recovery():
    """Test circuit breaker transitions to half-open and recovers"""
    config = CircuitBreakerConfig(
        failure_threshold=2,
        success_threshold=2,
        reset_timeout=0.1  # 100ms for faster testing
    )
    breaker = CircuitBreaker("test_service", config)

    # Open the circuit
    async def failing_func():
        raise Exception("Service error")

    for _ in range(2):
        with pytest.raises(Exception):
            await breaker.call(failing_func)

    assert breaker.state == CircuitState.OPEN

    # Wait for reset timeout
    await asyncio.sleep(0.15)

    # Circuit should transition to half-open on next check
    call_count = 0

    async def recovering_func():
        nonlocal call_count
        call_count += 1
        return f"success_{call_count}"

    # First successful call in half-open
    result = await breaker.call(recovering_func)
    assert result == "success_1"
    assert breaker.state == CircuitState.HALF_OPEN

    # Second successful call should close the circuit
    result = await breaker.call(recovering_func)
    assert result == "success_2"
    assert breaker.state == CircuitState.CLOSED
    assert breaker.stats.successful_calls == 2


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_failure_reopens():
    """Test failure in half-open state reopens circuit"""
    config = CircuitBreakerConfig(
        failure_threshold=2,
        success_threshold=2,
        reset_timeout=0.1
    )
    breaker = CircuitBreaker("test_service", config)

    # Open the circuit
    async def failing_func():
        raise Exception("Service error")

    for _ in range(2):
        with pytest.raises(Exception):
            await breaker.call(failing_func)

    assert breaker.state == CircuitState.OPEN

    # Wait for reset timeout
    await asyncio.sleep(0.15)

    # Failure in half-open should reopen immediately
    with pytest.raises(Exception):
        await breaker.call(failing_func)

    assert breaker.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_max_calls():
    """Test half-open state limits concurrent calls"""
    config = CircuitBreakerConfig(
        failure_threshold=2,
        success_threshold=3,
        reset_timeout=0.1,
        half_open_max_calls=2  # Only allow 2 concurrent calls in half-open
    )
    breaker = CircuitBreaker("test_service", config)

    # Open the circuit
    async def failing_func():
        raise Exception("Service error")

    for _ in range(2):
        with pytest.raises(Exception):
            await breaker.call(failing_func)

    # Wait for reset timeout
    await asyncio.sleep(0.15)

    # Slow function to hold calls
    async def slow_func():
        await asyncio.sleep(0.5)
        return "success"

    # Start concurrent calls
    tasks = [
        asyncio.create_task(breaker.call(slow_func)),
        asyncio.create_task(breaker.call(slow_func)),
    ]

    # Third call should be rejected
    await asyncio.sleep(0.01)  # Let first two start
    with pytest.raises(CircuitOpenError):
        await breaker.call(slow_func)

    # Clean up
    for task in tasks:
        await task


@pytest.mark.asyncio
async def test_circuit_breaker_exclude_exceptions():
    """Test that excluded exceptions don't trigger circuit breaker"""
    config = CircuitBreakerConfig(
        failure_threshold=2,
        exclude_exceptions=(ValueError,)
    )
    breaker = CircuitBreaker("test_service", config)

    async def func_with_value_error():
        raise ValueError("Invalid input")

    # ValueError should not count as failure
    for _ in range(5):
        with pytest.raises(ValueError):
            await breaker.call(func_with_value_error)

    # Circuit should still be closed
    assert breaker.state == CircuitState.CLOSED
    assert breaker.stats.failed_calls == 0  # No failures recorded


@pytest.mark.asyncio
async def test_circuit_breaker_statistics():
    """Test circuit breaker statistics tracking"""
    config = CircuitBreakerConfig(failure_threshold=3)
    breaker = CircuitBreaker("test_service", config)

    async def sometimes_failing_func(should_fail):
        if should_fail:
            raise Exception("Error")
        return "success"

    # Mix of successes and failures
    await breaker.call(sometimes_failing_func, False)
    assert breaker.stats.consecutive_successes == 1

    with pytest.raises(Exception):
        await breaker.call(sometimes_failing_func, True)
    assert breaker.stats.consecutive_failures == 1
    assert breaker.stats.consecutive_successes == 0

    await breaker.call(sometimes_failing_func, False)
    assert breaker.stats.consecutive_successes == 1
    assert breaker.stats.consecutive_failures == 0

    # Check status
    status = breaker.get_status()
    assert status['name'] == 'test_service'
    assert status['state'] == 'closed'
    assert status['stats']['total_calls'] == 3
    assert status['stats']['successful_calls'] == 2
    assert status['stats']['failed_calls'] == 1


@pytest.mark.asyncio
async def test_circuit_breaker_manual_reset():
    """Test manual reset of circuit breaker"""
    config = CircuitBreakerConfig(failure_threshold=2)
    breaker = CircuitBreaker("test_service", config)

    async def failing_func():
        raise Exception("Error")

    # Open the circuit
    for _ in range(2):
        with pytest.raises(Exception):
            await breaker.call(failing_func)

    assert breaker.state == CircuitState.OPEN

    # Manual reset
    breaker.reset()
    assert breaker.state == CircuitState.CLOSED
    assert breaker._failure_count == 0
    assert breaker._success_count == 0


@pytest.mark.asyncio
async def test_circuit_breaker_with_sync_function():
    """Test circuit breaker with synchronous functions"""
    config = CircuitBreakerConfig(failure_threshold=3)
    breaker = CircuitBreaker("test_service", config)

    # Sync function
    def sync_func(x):
        return x + 1

    result = await breaker.call(sync_func, 5)
    assert result == 6
    assert breaker.stats.successful_calls == 1


@pytest.mark.asyncio
async def test_circuit_breaker_error_propagation():
    """Test that original exceptions are propagated correctly"""
    config = CircuitBreakerConfig(failure_threshold=5)
    breaker = CircuitBreaker("test_service", config)

    class CustomError(Exception):
        pass

    async def custom_error_func():
        raise CustomError("Custom message")

    # Original exception should be raised
    with pytest.raises(CustomError, match="Custom message"):
        await breaker.call(custom_error_func)

    assert breaker.stats.failed_calls == 1


@pytest.mark.asyncio
async def test_circuit_breaker_state_transitions():
    """Test state transition recording"""
    config = CircuitBreakerConfig(
        failure_threshold=2,
        reset_timeout=0.1
    )
    breaker = CircuitBreaker("test_service", config)

    async def failing_func():
        raise Exception("Error")

    # Open the circuit
    for _ in range(2):
        with pytest.raises(Exception):
            await breaker.call(failing_func)

    # Check state changes were recorded
    assert len(breaker.stats.state_changes) > 0
    last_change = breaker.stats.state_changes[-1]
    assert last_change['from'] == 'closed'
    assert last_change['to'] == 'open'


if __name__ == "__main__":
    asyncio.run(pytest.main([__file__, "-v"]))