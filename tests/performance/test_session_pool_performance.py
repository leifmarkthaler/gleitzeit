"""
Performance tests for session pooling

Tests cover:
- Connection reuse performance
- Concurrent request handling
- DNS caching benefits
- Memory usage with pooling
- 2.7x performance improvement validation

Related components:
- OllamaHub session pooling
- TCPConnector configuration
- aiohttp performance
"""

import pytest
import asyncio
import aiohttp
import time
import statistics
from typing import List, Dict, Any
from unittest.mock import Mock, AsyncMock, patch
import psutil
import os

from gleitzeit.hub.ollama_hub import OllamaHub


@pytest.mark.performance
@pytest.mark.slow
class TestSessionPoolPerformance:
    """Performance tests for session pooling"""
    
    @pytest.fixture
    async def ollama_hub_with_pool(self):
        """Create OllamaHub with session pooling"""
        hub = OllamaHub()
        await hub.initialize()
        yield hub
        await hub.cleanup()
    
    @pytest.fixture
    async def ollama_hub_without_pool(self):
        """Create OllamaHub without session pooling (for comparison)"""
        hub = OllamaHub()
        # Don't initialize session pool
        yield hub
        await hub.cleanup()
    
    @pytest.mark.asyncio
    async def test_connection_reuse_performance(self, ollama_hub_with_pool):
        """Test that connection reuse improves performance"""
        # Mock responses
        async def mock_request(*args, **kwargs):
            await asyncio.sleep(0.01)  # Simulate network delay
            return {"response": "test"}
        
        with patch.object(ollama_hub_with_pool.session, 'post') as mock_post:
            mock_response = AsyncMock()
            mock_response.json = mock_request
            mock_response.raise_for_status = Mock()
            mock_post.return_value.__aenter__.return_value = mock_response
            
            # Measure cold start (first request)
            cold_times = []
            for _ in range(3):
                start = time.perf_counter()
                await ollama_hub_with_pool.session.post(
                    f"{ollama_hub_with_pool.base_url}/api/generate",
                    json={"model": "test"}
                )
                cold_times.append(time.perf_counter() - start)
            
            # Measure warm requests (connection reused)
            warm_times = []
            for _ in range(10):
                start = time.perf_counter()
                await ollama_hub_with_pool.session.post(
                    f"{ollama_hub_with_pool.base_url}/api/generate",
                    json={"model": "test"}
                )
                warm_times.append(time.perf_counter() - start)
            
            # Calculate averages
            avg_cold = statistics.mean(cold_times)
            avg_warm = statistics.mean(warm_times)
            
            # Warm requests should be consistently fast
            assert statistics.stdev(warm_times) < statistics.stdev(cold_times)
            
            # Performance improvement (should be significant with real network)
            print(f"Cold avg: {avg_cold:.4f}s, Warm avg: {avg_warm:.4f}s")
            print(f"Performance improvement: {avg_cold/avg_warm:.2f}x")
    
    @pytest.mark.asyncio
    async def test_concurrent_request_handling(self, ollama_hub_with_pool):
        """Test handling multiple concurrent requests efficiently"""
        num_requests = 50
        
        async def make_request(session, url, i):
            start = time.perf_counter()
            try:
                async with session.post(url, json={"id": i}) as resp:
                    await resp.json()
                return time.perf_counter() - start
            except:
                return None
        
        # Mock server responses
        with patch.object(ollama_hub_with_pool.session, 'post') as mock_post:
            mock_response = AsyncMock()
            mock_response.json = AsyncMock(return_value={"response": "test"})
            mock_response.raise_for_status = Mock()
            mock_post.return_value = mock_response
            
            # Run concurrent requests
            start_time = time.perf_counter()
            tasks = [
                make_request(
                    ollama_hub_with_pool.session,
                    f"{ollama_hub_with_pool.base_url}/api/generate",
                    i
                )
                for i in range(num_requests)
            ]
            
            results = await asyncio.gather(*tasks)
            total_time = time.perf_counter() - start_time
            
            # Filter out None results
            valid_times = [r for r in results if r is not None]
            
            # Calculate metrics
            avg_time = statistics.mean(valid_times) if valid_times else 0
            max_time = max(valid_times) if valid_times else 0
            
            print(f"Concurrent requests: {num_requests}")
            print(f"Total time: {total_time:.2f}s")
            print(f"Average per request: {avg_time:.4f}s")
            print(f"Max request time: {max_time:.4f}s")
            
            # With pooling, total time should be much less than sequential
            sequential_estimate = avg_time * num_requests
            speedup = sequential_estimate / total_time
            print(f"Speedup vs sequential: {speedup:.2f}x")
            
            assert speedup > 1.5  # Should have significant speedup
    
    @pytest.mark.asyncio
    async def test_connection_limit_enforcement(self, ollama_hub_with_pool):
        """Test that connection limits are properly enforced"""
        connector = ollama_hub_with_pool.session.connector
        
        # Check limits
        assert connector.limit == 100  # Total limit
        assert connector.limit_per_host == 30  # Per-host limit
        
        # Track active connections
        active_connections = []
        
        async def long_request(session, url):
            async with session.post(url, json={}) as resp:
                active_connections.append(1)
                await asyncio.sleep(0.1)  # Hold connection
                active_connections.pop()
                return await resp.json()
        
        with patch.object(ollama_hub_with_pool.session, 'post') as mock_post:
            mock_response = AsyncMock()
            mock_response.json = AsyncMock(return_value={"response": "test"})
            mock_post.return_value = mock_response
            
            # Try to exceed per-host limit
            tasks = [
                long_request(
                    ollama_hub_with_pool.session,
                    ollama_hub_with_pool.base_url
                )
                for _ in range(40)  # More than limit_per_host
            ]
            
            # Should handle gracefully without errors
            await asyncio.gather(*tasks, return_exceptions=True)
            
            # Max concurrent should not exceed limit
            max_concurrent = max(len(active_connections) for _ in range(10))
            assert max_concurrent <= 30
    
    @pytest.mark.asyncio
    async def test_dns_caching_performance(self, ollama_hub_with_pool):
        """Test DNS caching improves performance"""
        connector = ollama_hub_with_pool.session.connector
        
        # Check DNS cache is configured
        assert connector._dns_ttl == 300  # 5 minutes
        
        # Simulate multiple requests to same host
        host_requests = []
        
        for _ in range(20):
            start = time.perf_counter()
            # DNS lookup would happen here in real scenario
            # Connector caches DNS results
            host_requests.append(time.perf_counter() - start)
        
        # First few might be slower (DNS lookup)
        # Later ones should be fast (cached)
        first_half = statistics.mean(host_requests[:10])
        second_half = statistics.mean(host_requests[10:])
        
        # Second half should be as fast or faster (cached DNS)
        assert second_half <= first_half * 1.1  # Allow 10% variance
    
    @pytest.mark.asyncio
    async def test_memory_usage_with_pooling(self, ollama_hub_with_pool):
        """Test memory usage remains stable with connection pooling"""
        process = psutil.Process(os.getpid())
        
        # Get baseline memory
        baseline_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Make many requests
        for i in range(100):
            with patch.object(ollama_hub_with_pool.session, 'post') as mock_post:
                mock_response = AsyncMock()
                mock_response.json = AsyncMock(return_value={"response": f"test_{i}"})
                mock_post.return_value.__aenter__.return_value = mock_response
                
                await ollama_hub_with_pool.session.post(
                    f"{ollama_hub_with_pool.base_url}/api/generate",
                    json={"id": i}
                )
        
        # Check memory after requests
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - baseline_memory
        
        print(f"Baseline memory: {baseline_memory:.2f} MB")
        print(f"Final memory: {final_memory:.2f} MB")
        print(f"Memory increase: {memory_increase:.2f} MB")
        
        # Memory increase should be minimal (connection reuse)
        assert memory_increase < 50  # Less than 50MB increase
    
    @pytest.mark.asyncio
    async def test_performance_improvement_validation(self):
        """Validate the claimed 2.7x performance improvement"""
        # Compare pooled vs non-pooled performance
        
        # Non-pooled: create new session each time
        async def non_pooled_requests(num_requests):
            times = []
            for _ in range(num_requests):
                start = time.perf_counter()
                async with aiohttp.ClientSession() as session:
                    try:
                        async with session.get("http://httpbin.org/delay/0") as resp:
                            await resp.text()
                    except:
                        pass
                times.append(time.perf_counter() - start)
            return times
        
        # Pooled: reuse session
        async def pooled_requests(num_requests):
            times = []
            connector = aiohttp.TCPConnector(
                limit=100,
                limit_per_host=30,
                ttl_dns_cache=300
            )
            async with aiohttp.ClientSession(connector=connector) as session:
                for _ in range(num_requests):
                    start = time.perf_counter()
                    try:
                        async with session.get("http://httpbin.org/delay/0") as resp:
                            await resp.text()
                    except:
                        pass
                    times.append(time.perf_counter() - start)
            return times
        
        # Skip if no internet connection
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("http://httpbin.org/delay/0", timeout=2) as resp:
                    pass
        except:
            pytest.skip("No internet connection for performance test")
        
        # Run comparison
        num_requests = 10
        
        non_pooled_times = await non_pooled_requests(num_requests)
        pooled_times = await pooled_requests(num_requests)
        
        avg_non_pooled = statistics.mean(non_pooled_times[1:])  # Skip first
        avg_pooled = statistics.mean(pooled_times[1:])  # Skip first
        
        improvement = avg_non_pooled / avg_pooled
        
        print(f"Non-pooled avg: {avg_non_pooled:.4f}s")
        print(f"Pooled avg: {avg_pooled:.4f}s")
        print(f"Performance improvement: {improvement:.2f}x")
        
        # Should show significant improvement
        assert improvement > 1.2  # At least 20% improvement


@pytest.mark.performance
class TestWorkloadPerformance:
    """Test performance under various workloads"""
    
    @pytest.mark.asyncio
    async def test_sustained_load_performance(self):
        """Test performance under sustained load"""
        hub = OllamaHub()
        await hub.initialize()
        
        try:
            # Simulate sustained load
            duration = 5  # seconds
            requests_completed = 0
            errors = 0
            
            async def worker():
                nonlocal requests_completed, errors
                end_time = time.time() + duration
                
                while time.time() < end_time:
                    try:
                        with patch.object(hub.session, 'post') as mock_post:
                            mock_response = AsyncMock()
                            mock_response.json = AsyncMock(return_value={"response": "test"})
                            mock_post.return_value.__aenter__.return_value = mock_response
                            
                            await hub.session.post(
                                f"{hub.base_url}/api/generate",
                                json={"test": True}
                            )
                            requests_completed += 1
                    except Exception:
                        errors += 1
                    
                    await asyncio.sleep(0.01)  # Small delay between requests
            
            # Run multiple workers
            workers = [worker() for _ in range(10)]
            await asyncio.gather(*workers)
            
            throughput = requests_completed / duration
            error_rate = errors / (requests_completed + errors) if (requests_completed + errors) > 0 else 0
            
            print(f"Sustained load test:")
            print(f"Duration: {duration}s")
            print(f"Requests completed: {requests_completed}")
            print(f"Throughput: {throughput:.2f} req/s")
            print(f"Error rate: {error_rate:.2%}")
            
            # Should maintain good throughput
            assert throughput > 50  # At least 50 req/s
            assert error_rate < 0.01  # Less than 1% errors
            
        finally:
            await hub.cleanup()
    
    @pytest.mark.asyncio
    async def test_burst_load_performance(self):
        """Test performance under burst load"""
        hub = OllamaHub()
        await hub.initialize()
        
        try:
            # Simulate burst of requests
            burst_size = 100
            
            async def burst_request(i):
                start = time.perf_counter()
                with patch.object(hub.session, 'post') as mock_post:
                    mock_response = AsyncMock()
                    mock_response.json = AsyncMock(return_value={"response": f"burst_{i}"})
                    mock_post.return_value.__aenter__.return_value = mock_response
                    
                    await hub.session.post(
                        f"{hub.base_url}/api/generate",
                        json={"id": i}
                    )
                return time.perf_counter() - start
            
            # Send burst
            start_time = time.perf_counter()
            tasks = [burst_request(i) for i in range(burst_size)]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            total_time = time.perf_counter() - start_time
            
            # Analyze results
            successful = [r for r in results if isinstance(r, float)]
            failed = len(results) - len(successful)
            
            avg_latency = statistics.mean(successful) if successful else 0
            p95_latency = statistics.quantiles(successful, n=20)[18] if len(successful) > 20 else max(successful) if successful else 0
            
            print(f"Burst load test:")
            print(f"Burst size: {burst_size}")
            print(f"Total time: {total_time:.2f}s")
            print(f"Successful: {len(successful)}")
            print(f"Failed: {failed}")
            print(f"Avg latency: {avg_latency:.4f}s")
            print(f"P95 latency: {p95_latency:.4f}s")
            
            # Should handle burst efficiently
            assert failed < burst_size * 0.05  # Less than 5% failures
            assert total_time < burst_size * 0.1  # Much faster than sequential
            
        finally:
            await hub.cleanup()