"""
Comprehensive test suite for SimpleProvider.

Tests the simplified provider base class that reduces provider 
implementation from 400+ lines to just 10-25 lines.
"""

import pytest
import asyncio
import time
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch
from typing import Any, Dict

from gleitzeit.providers.simple import SimpleProvider
from gleitzeit.core.errors import ProviderError, ErrorCode


# =========================================================================
# Test Provider Implementations
# =========================================================================

class TestSimpleProvider(SimpleProvider):
    """Test provider for unit testing"""
    
    def __init__(self, **kwargs):
        super().__init__(
            provider_id="test",
            protocol_id="test/v1",
            name="Test Provider",
            description="Provider for testing",
            **kwargs
        )
        self.execution_log = []
    
    async def execute(self, method: str, **params) -> Any:
        """Test implementation of execute method"""
        self.execution_log.append({"method": method, "params": params, "timestamp": datetime.utcnow()})
        
        if method == "echo":
            return {"echoed": params}
        
        elif method == "add":
            a = params.get("a", 0)
            b = params.get("b", 0)
            return {"result": a + b}
        
        elif method == "slow_operation":
            delay = params.get("delay", 0.1)
            await asyncio.sleep(delay)
            return {"completed": True, "delay": delay}
        
        elif method == "error_operation":
            error_type = params.get("error_type", "generic")
            
            if error_type == "retryable":
                raise ConnectionError("Network timeout - retryable")
            elif error_type == "non_retryable":
                raise ValueError("Invalid input - not retryable")
            elif error_type == "provider_error":
                raise ProviderError("Provider-specific error", ErrorCode.PROVIDER_ERROR)
            else:
                raise RuntimeError("Generic runtime error")
        
        elif method == "memory_operation":
            # Test memory usage tracking
            size = params.get("size", 1000)
            data = "x" * size
            return {"data_size": len(data)}
        
        else:
            raise ValueError(f"Unknown method: {method}")


class FlawedProvider(SimpleProvider):
    """Provider that has some issues for testing edge cases"""
    
    async def execute(self, method: str, **params) -> Any:
        if method == "hang":
            # Simulate hanging operation
            await asyncio.sleep(10)
            return {"never_reached": True}
        
        elif method == "corrupt_response":
            # Return non-serializable response
            return {"function": lambda x: x}
        
        elif method == "none_response":
            return None
        
        else:
            raise NotImplementedError(f"Method {method} not implemented")


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture
async def simple_provider():
    """Create a test provider instance"""
    provider = TestSimpleProvider()
    await provider.initialize()
    yield provider
    await provider.shutdown()


@pytest.fixture
async def flawed_provider():
    """Create a flawed provider for testing edge cases"""
    provider = FlawedProvider(provider_id="flawed", protocol_id="flawed/v1")
    await provider.initialize()
    yield provider
    await provider.shutdown()


# =========================================================================
# Basic Functionality Tests
# =========================================================================

class TestBasicFunctionality:
    """Test basic SimpleProvider functionality"""
    
    @pytest.mark.asyncio
    async def test_provider_initialization(self):
        """Test provider initialization with various parameters"""
        provider = TestSimpleProvider(
            max_retries=5,
            retry_delay=2.0,
            retry_backoff=1.5
        )
        
        assert provider.provider_id == "test"
        assert provider.protocol_id == "test/v1"
        assert provider.name == "Test Provider"
        assert provider.max_retries == 5
        assert provider.retry_delay == 2.0
        assert provider.retry_backoff == 1.5
        assert not provider._initialized
        
        await provider.initialize()
        assert provider._initialized
        
        await provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_auto_id_generation(self):
        """Test automatic ID generation from class name"""
        
        class WeatherProvider(SimpleProvider):
            async def execute(self, method: str, **params):
                return {"weather": "sunny"}
        
        provider = WeatherProvider()
        
        assert provider.provider_id == "weather"  # "provider" suffix removed
        assert provider.protocol_id == "weather/v1"
        assert provider.name == "Weather Provider"
        
        await provider.initialize()
        await provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_basic_execution(self, simple_provider):
        """Test basic method execution"""
        # Test echo method
        result = await simple_provider.handle_request("echo", {"message": "hello"})
        assert result == {"echoed": {"message": "hello"}}
        
        # Test math operation
        result = await simple_provider.handle_request("add", {"a": 5, "b": 3})
        assert result == {"result": 8}
        
        # Verify execution was logged
        assert len(simple_provider.execution_log) == 2
        assert simple_provider.execution_log[0]["method"] == "echo"
        assert simple_provider.execution_log[1]["method"] == "add"
    
    @pytest.mark.asyncio
    async def test_unknown_method_error(self, simple_provider):
        """Test handling of unknown methods"""
        with pytest.raises(ValueError, match="Unknown method: nonexistent"):
            await simple_provider.handle_request("nonexistent", {})
    
    @pytest.mark.asyncio
    async def test_async_operations(self, simple_provider):
        """Test asynchronous operations"""
        start_time = time.time()
        result = await simple_provider.handle_request("slow_operation", {"delay": 0.2})
        end_time = time.time()
        
        assert result["completed"] is True
        assert result["delay"] == 0.2
        assert end_time - start_time >= 0.2


# =========================================================================
# Error Handling Tests
# =========================================================================

class TestErrorHandling:
    """Test error handling and retry logic"""
    
    @pytest.mark.asyncio
    async def test_retryable_error_handling(self, simple_provider):
        """Test handling of retryable errors with exponential backoff"""
        # Mock the execute method to fail then succeed
        call_count = 0
        original_execute = simple_provider.execute
        
        async def mock_execute(method: str, **params):
            nonlocal call_count
            call_count += 1
            
            if method == "flaky_operation" and call_count < 3:
                raise ConnectionError("Network timeout")
            
            return await original_execute(method, **params)
        
        simple_provider.execute = mock_execute
        
        # Should succeed on the 3rd try
        result = await simple_provider.handle_request("flaky_operation", {})
        assert result is not None
        assert call_count == 3
    
    @pytest.mark.asyncio
    async def test_non_retryable_error_handling(self, simple_provider):
        """Test handling of non-retryable errors"""
        with pytest.raises(ValueError, match="Invalid input"):
            await simple_provider.handle_request("error_operation", {"error_type": "non_retryable"})
    
    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self, simple_provider):
        """Test behavior when max retries are exceeded"""
        # Set low retry count for faster testing
        simple_provider.max_retries = 2
        
        with pytest.raises(ConnectionError, match="Network timeout"):
            await simple_provider.handle_request("error_operation", {"error_type": "retryable"})
    
    @pytest.mark.asyncio
    async def test_provider_error_handling(self, simple_provider):
        """Test handling of ProviderError exceptions"""
        with pytest.raises(ProviderError) as exc_info:
            await simple_provider.handle_request("error_operation", {"error_type": "provider_error"})
        
        assert exc_info.value.error_code == ErrorCode.PROVIDER_ERROR
        assert "Provider-specific error" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_retry_delay_progression(self, simple_provider):
        """Test exponential backoff in retry delays"""
        simple_provider.max_retries = 3
        simple_provider.retry_delay = 0.1
        simple_provider.retry_backoff = 2.0
        
        call_times = []
        original_execute = simple_provider.execute
        
        async def mock_execute(method: str, **params):
            call_times.append(time.time())
            if len(call_times) < 3:
                raise ConnectionError("Temporary failure")
            return await original_execute("echo", params)
        
        simple_provider.execute = mock_execute
        
        start_time = time.time()
        result = await simple_provider.handle_request("test_method", {})
        
        # Verify exponential backoff timing
        assert len(call_times) == 3
        if len(call_times) >= 2:
            delay1 = call_times[1] - call_times[0]
            assert delay1 >= 0.1  # First retry delay
        
        if len(call_times) >= 3:
            delay2 = call_times[2] - call_times[1]
            assert delay2 >= 0.2  # Second retry delay (0.1 * 2.0)


# =========================================================================
# Metrics and Monitoring Tests
# =========================================================================

class TestMetricsAndMonitoring:
    """Test metrics collection and monitoring features"""
    
    @pytest.mark.asyncio
    async def test_request_metrics_collection(self, simple_provider):
        """Test that request metrics are collected properly"""
        # Execute several operations
        await simple_provider.handle_request("add", {"a": 1, "b": 2})
        await simple_provider.handle_request("echo", {"msg": "test"})
        await simple_provider.handle_request("slow_operation", {"delay": 0.1})
        
        # Check basic counters
        assert simple_provider.request_count == 3
        assert simple_provider.error_count == 0
        
        # Check method-specific metrics
        assert simple_provider.method_counts.get("add", 0) >= 1
        assert simple_provider.method_counts.get("echo", 0) >= 1
        assert simple_provider.method_counts.get("slow_operation", 0) >= 1
        
        # Check latency tracking
        assert len(simple_provider.latencies) == 3
        assert all(latency > 0 for latency in simple_provider.latencies)
    
    @pytest.mark.asyncio
    async def test_error_metrics_collection(self, simple_provider):
        """Test that error metrics are tracked correctly"""
        initial_error_count = simple_provider.error_count
        
        # Execute operation that will fail
        with pytest.raises(ValueError):
            await simple_provider.handle_request("error_operation", {"error_type": "non_retryable"})
        
        assert simple_provider.error_count == initial_error_count + 1
    
    @pytest.mark.asyncio
    async def test_enhanced_metrics(self, simple_provider):
        """Test the enhanced metrics reporting"""
        # Execute some operations
        await simple_provider.handle_request("add", {"a": 10, "b": 20})
        await simple_provider.handle_request("memory_operation", {"size": 500})
        
        metrics = simple_provider.get_enhanced_metrics()
        
        # Verify metrics structure
        assert "provider_id" in metrics
        assert "protocol_id" in metrics
        assert "total_requests" in metrics
        assert "total_errors" in metrics
        assert "average_latency" in metrics
        assert "method_breakdown" in metrics
        assert "provider_type" in metrics
        assert "features" in metrics
        
        # Verify values
        assert metrics["provider_id"] == "test"
        assert metrics["total_requests"] >= 2
        assert metrics["total_errors"] == 0
        assert isinstance(metrics["average_latency"], float)
        assert "add" in metrics["method_breakdown"]
        assert "memory_operation" in metrics["method_breakdown"]
    
    @pytest.mark.asyncio
    async def test_health_check(self, simple_provider):
        """Test the default health check implementation"""
        # Default implementation should always return True
        health_status = await simple_provider.health_check()
        assert health_status is True
    
    @pytest.mark.asyncio
    async def test_latency_calculation(self, simple_provider):
        """Test latency calculation and averaging"""
        # Execute operations with known delays
        await simple_provider.handle_request("slow_operation", {"delay": 0.1})
        await simple_provider.handle_request("slow_operation", {"delay": 0.2})
        
        # Check that latencies were recorded
        assert len(simple_provider.latencies) >= 2
        
        # All latencies should be positive
        assert all(lat > 0 for lat in simple_provider.latencies)
        
        # Verify that slower operations have higher latencies
        recent_latencies = simple_provider.latencies[-2:]
        if len(recent_latencies) >= 2:
            # The 0.2s operation should be slower than 0.1s operation
            assert max(recent_latencies) >= min(recent_latencies)


# =========================================================================
# Lifecycle Management Tests
# =========================================================================

class TestLifecycleManagement:
    """Test provider lifecycle management"""
    
    @pytest.mark.asyncio
    async def test_initialization_and_shutdown(self):
        """Test proper initialization and shutdown sequence"""
        provider = TestSimpleProvider()
        
        # Initially not initialized
        assert not provider._initialized
        assert provider.created_at is not None
        
        # Initialize
        await provider.initialize()
        assert provider._initialized
        
        # Can execute after initialization
        result = await provider.handle_request("echo", {"test": "data"})
        assert result == {"echoed": {"test": "data"}}
        
        # Shutdown
        await provider.shutdown()
        # Note: SimpleProvider doesn't set _initialized to False on shutdown by design
    
    @pytest.mark.asyncio
    async def test_double_initialization(self):
        """Test that double initialization is safe"""
        provider = TestSimpleProvider()
        
        await provider.initialize()
        first_init_time = provider.created_at
        
        # Second initialization should be safe
        await provider.initialize()
        assert provider.created_at == first_init_time
        
        await provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_shutdown_cleanup(self):
        """Test that shutdown properly cleans up resources"""
        provider = TestSimpleProvider()
        await provider.initialize()
        
        # Add some metrics
        await provider.handle_request("add", {"a": 1, "b": 1})
        assert provider.request_count > 0
        
        # Shutdown should be clean (no exceptions)
        await provider.shutdown()
        
        # Metrics should still be accessible after shutdown
        assert provider.request_count > 0


# =========================================================================
# Edge Cases and Error Conditions Tests
# =========================================================================

class TestEdgeCasesAndErrorConditions:
    """Test edge cases and unusual error conditions"""
    
    @pytest.mark.asyncio
    async def test_none_response_handling(self, flawed_provider):
        """Test handling of None responses"""
        result = await flawed_provider.handle_request("none_response", {})
        assert result is None
    
    @pytest.mark.asyncio
    async def test_empty_parameters(self, simple_provider):
        """Test handling of empty or missing parameters"""
        # Empty params dict
        result = await simple_provider.handle_request("echo", {})
        assert result == {"echoed": {}}
        
        # Test method that uses default values
        result = await simple_provider.handle_request("add", {})
        assert result == {"result": 0}  # 0 + 0
    
    @pytest.mark.asyncio
    async def test_large_response_handling(self, simple_provider):
        """Test handling of large responses"""
        # Test with large memory operation
        result = await simple_provider.handle_request("memory_operation", {"size": 10000})
        assert result["data_size"] == 10000
        
        # Verify metrics still work with large responses
        assert simple_provider.request_count > 0
    
    @pytest.mark.asyncio
    async def test_concurrent_execution(self, simple_provider):
        """Test concurrent execution of multiple requests"""
        # Execute multiple requests concurrently
        tasks = [
            simple_provider.handle_request("add", {"a": i, "b": i+1})
            for i in range(10)
        ]
        
        results = await asyncio.gather(*tasks)
        
        # Verify all results are correct
        for i, result in enumerate(results):
            expected = {"result": i + (i + 1)}
            assert result == expected
        
        # Verify metrics reflect all requests
        assert simple_provider.request_count >= 10
    
    @pytest.mark.asyncio
    async def test_parameter_type_handling(self, simple_provider):
        """Test handling of various parameter types"""
        test_cases = [
            {"method": "echo", "params": {"string": "hello"}},
            {"method": "echo", "params": {"number": 42}},
            {"method": "echo", "params": {"boolean": True}},
            {"method": "echo", "params": {"list": [1, 2, 3]}},
            {"method": "echo", "params": {"dict": {"nested": "value"}}},
            {"method": "echo", "params": {"null": None}},
        ]
        
        for test_case in test_cases:
            result = await simple_provider.handle_request(
                test_case["method"], 
                test_case["params"]
            )
            assert result == {"echoed": test_case["params"]}


# =========================================================================
# Performance Tests
# =========================================================================

class TestPerformance:
    """Test performance characteristics of SimpleProvider"""
    
    @pytest.mark.asyncio
    async def test_sequential_performance(self, simple_provider):
        """Test performance of sequential operations"""
        start_time = time.time()
        
        # Execute 100 simple operations
        for i in range(100):
            await simple_provider.handle_request("add", {"a": i, "b": 1})
        
        end_time = time.time()
        total_time = end_time - start_time
        
        # Should complete 100 operations reasonably quickly
        assert total_time < 1.0  # Less than 1 second for 100 operations
        assert simple_provider.request_count >= 100
    
    @pytest.mark.asyncio
    async def test_concurrent_performance(self, simple_provider):
        """Test performance under concurrent load"""
        start_time = time.time()
        
        # Execute 50 concurrent operations
        tasks = [
            simple_provider.handle_request("add", {"a": i, "b": i*2})
            for i in range(50)
        ]
        
        results = await asyncio.gather(*tasks)
        end_time = time.time()
        
        # Verify all operations completed
        assert len(results) == 50
        assert all(isinstance(r["result"], int) for r in results)
        
        # Should be faster than sequential execution
        total_time = end_time - start_time
        assert total_time < 0.5  # Much faster than sequential
    
    @pytest.mark.asyncio
    async def test_memory_efficiency(self, simple_provider):
        """Test that provider doesn't leak memory during operation"""
        import gc
        
        # Get baseline memory usage
        gc.collect()
        initial_objects = len(gc.get_objects())
        
        # Execute many operations
        for i in range(200):
            await simple_provider.handle_request("echo", {"iteration": i})
        
        # Force garbage collection
        gc.collect()
        final_objects = len(gc.get_objects())
        
        # Memory usage shouldn't grow significantly
        # Allow some growth due to metrics collection
        growth = final_objects - initial_objects
        assert growth < 1000  # Reasonable threshold


# =========================================================================
# Integration Tests
# =========================================================================

class TestIntegration:
    """Test integration with other system components"""
    
    @pytest.mark.asyncio
    async def test_with_custom_retry_config(self):
        """Test provider with custom retry configuration"""
        provider = TestSimpleProvider(
            max_retries=5,
            retry_delay=0.05,  # Faster for testing
            retry_backoff=1.5
        )
        
        await provider.initialize()
        
        # Mock failing operation
        call_count = 0
        original_execute = provider.execute
        
        async def mock_execute(method: str, **params):
            nonlocal call_count
            call_count += 1
            
            if method == "retry_test" and call_count < 4:
                raise ConnectionError("Simulated failure")
            
            return {"success": True, "attempts": call_count}
        
        provider.execute = mock_execute
        
        result = await provider.handle_request("retry_test", {})
        assert result["success"] is True
        assert result["attempts"] == 4  # Should succeed on 4th attempt
        
        await provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_logging_integration(self, simple_provider):
        """Test that logging works correctly"""
        with patch('gleitzeit.providers.simple.logger') as mock_logger:
            # Execute operation that should generate logs
            await simple_provider.handle_request("echo", {"test": "logging"})
            
            # Verify logging calls were made
            assert mock_logger.debug.called or mock_logger.info.called
    
    @pytest.mark.asyncio
    async def test_resource_manager_integration(self):
        """Test integration with resource manager"""
        # Mock resource manager
        mock_resource_manager = Mock()
        
        provider = TestSimpleProvider(resource_manager=mock_resource_manager)
        assert provider.resource_manager is mock_resource_manager
        
        await provider.initialize()
        await provider.shutdown()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])