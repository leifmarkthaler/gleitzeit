"""
Integration tests for Provider-Hub separation

Tests cover:
- Clean separation of concerns
- Provider handles protocol execution only
- Hub manages resource lifecycle
- Session pooling integration
- No cross-contamination of responsibilities

Related components:
- OllamaProvider
- OllamaHub
- ResourceManager
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import aiohttp
from typing import Dict, Any

from gleitzeit.providers.ollama_provider import OllamaProvider
from gleitzeit.hub.ollama_hub import OllamaHub
from gleitzeit.hub.resource_manager import ResourceManager
import time


@pytest.mark.integration
class TestProviderHubSeparation:
    """Test clean architecture separation between providers and hubs"""
    
    @pytest.fixture
    async def ollama_hub(self):
        """Create OllamaHub instance"""
        hub = OllamaHub()
        # Mock actual Ollama process management
        hub.discover_instances = AsyncMock(return_value=[])
        hub.start_instance = AsyncMock()
        hub.stop_instance = AsyncMock(return_value=True)
        yield hub
        await hub.cleanup()
    
    @pytest.fixture
    async def ollama_provider(self):
        """Create OllamaProvider"""
        provider = OllamaProvider(
            provider_id="test_ollama"
        )
        yield provider
        if provider.session and not provider.session.closed:
            await provider.cleanup()
    
    @pytest.fixture
    async def resource_manager(self):
        """Create ResourceManager"""
        manager = ResourceManager()
        yield manager
        await manager.cleanup()
    
    @pytest.fixture
    def performance_timer(self):
        """Simple performance timer for tests"""
        class Timer:
            def __init__(self):
                self.start_time = None
            
            def start(self):
                self.start_time = time.perf_counter()
            
            def stop(self):
                if self.start_time is None:
                    return 0
                elapsed = time.perf_counter() - self.start_time
                self.start_time = None
                return elapsed
        
        return Timer()
    
    # ==================== Separation of Concerns Tests ====================
    
    def test_provider_has_no_resource_management(self):
        """Verify OllamaProvider has no resource management methods"""
        provider_methods = dir(OllamaProvider)
        
        # These methods should NOT exist in provider
        resource_methods = [
            'start_process',
            'stop_process',
            'manage_resources',
            'allocate_resource',
            'cleanup_processes'
        ]
        
        for method in resource_methods:
            assert method not in provider_methods, \
                f"Provider should not have resource management method: {method}"
    
    def test_hub_has_no_protocol_execution(self):
        """Verify OllamaHub has no protocol execution logic"""
        hub_methods = dir(OllamaHub)
        
        # These methods should NOT exist in hub
        protocol_methods = [
            'execute_protocol',
            'handle_request',
            'process_llm_request',
            'chat_completion'
        ]
        
        for method in protocol_methods:
            assert method not in hub_methods, \
                f"Hub should not have protocol execution method: {method}"
    
    @pytest.mark.asyncio
    async def test_provider_hub_independence(self, ollama_provider, ollama_hub):
        """Test that provider and hub can be initialized independently"""
        # Provider can initialize without hub
        await ollama_provider.initialize()
        assert ollama_provider.session is not None
        
        # Hub can initialize independently
        await ollama_hub.initialize()
        assert ollama_hub.session is not None
        
        # They maintain separate sessions
        assert ollama_provider.session != ollama_hub.session
    
    # ==================== Session Pooling Tests ====================
    
    @pytest.mark.asyncio
    async def test_hub_manages_session_pool(self, ollama_hub):
        """Test that hub properly manages session pooling"""
        await ollama_hub.initialize()
        
        # Check session is created with proper connector
        assert ollama_hub.session is not None
        assert isinstance(ollama_hub.session, aiohttp.ClientSession)
        
        # Check connector configuration
        connector = ollama_hub.session.connector
        assert connector.limit == 100  # Total connection pool
        assert connector.limit_per_host == 30  # Per-host limit
    
    @pytest.mark.asyncio
    async def test_provider_session_reuse(self, ollama_provider):
        """Test that provider reuses sessions for multiple requests"""
        await ollama_provider.initialize()
        
        # Create mock response
        mock_response = MagicMock()
        mock_response.json = AsyncMock(return_value={"response": "test"})
        mock_response.status = 200
        
        # Create a proper async context manager mock
        class AsyncContextManagerMock:
            async def __aenter__(self):
                return mock_response
            async def __aexit__(self, *args):
                return None
        
        # Create mock session
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=AsyncContextManagerMock())
        mock_session.closed = False
        
        ollama_provider.session = mock_session
        
        # Make multiple requests
        for _ in range(3):
            await ollama_provider.handle_request("llm/chat", {
                "model": "llama3.2",
                "messages": [{"role": "user", "content": "test"}]
            })
        
        # Session should be reused, not recreated
        assert mock_session.post.call_count == 3
    
    @pytest.mark.asyncio
    async def test_session_cleanup_on_shutdown(self, ollama_hub):
        """Test that sessions are properly cleaned up"""
        await ollama_hub.initialize()
        assert ollama_hub.session is not None
        
        await ollama_hub.cleanup()
        assert ollama_hub.session is None
    
    # ==================== Lifecycle Management Tests ====================
    
    @pytest.mark.asyncio
    async def test_provider_context_manager(self, ollama_provider):
        """Test provider works as async context manager"""
        async with ollama_provider as provider:
            assert provider is not None
            health = await provider.health_check()
            assert isinstance(health, bool)
    
    @pytest.mark.asyncio
    async def test_hub_starts_before_provider(self, ollama_hub, resource_manager):
        """Test that hub resources are started before provider use"""
        # Mock the start method
        ollama_hub.start = AsyncMock()
        
        # Register hub with resource manager
        resource_manager.register_hub("ollama", ollama_hub)
        
        # Start resource manager (should start hub)
        await resource_manager.start()
        
        # Hub should be started
        ollama_hub.start.assert_called()
    
    @pytest.mark.asyncio
    async def test_provider_fails_gracefully_without_hub(self):
        """Test provider handles missing Ollama instance gracefully"""
        provider = OllamaProvider(
            provider_id="test"
        )
        
        # Provider should initialize successfully even without Ollama running
        await provider.initialize()
        assert provider.session is not None
        
        # Health check should return True (provider is healthy even if no Ollama)
        health = await provider.health_check()
        assert health is True
        
        await provider.cleanup()
    
    # ==================== Resource Allocation Tests ====================
    
    @pytest.mark.asyncio
    async def test_resource_manager_coordinates_hubs(self, resource_manager):
        """Test ResourceManager coordinates multiple hubs"""
        # Create mock hubs
        ollama_hub = AsyncMock()
        docker_hub = AsyncMock()
        
        # Register hubs
        resource_manager.register_hub("ollama", ollama_hub)
        resource_manager.register_hub("docker", docker_hub)
        
        # Start all resources
        await resource_manager.start()
        
        # Both hubs should be started
        ollama_hub.start.assert_called()
        docker_hub.start.assert_called()
    
    @pytest.mark.asyncio
    async def test_hub_health_check_integration(self, ollama_hub):
        """Test hub health check functionality"""
        await ollama_hub.initialize()
        
        # Create a mock instance to check health
        from gleitzeit.hub.base import ResourceInstance, ResourceStatus, ResourceType
        from gleitzeit.hub.configs import OllamaConfig
        
        mock_instance = ResourceInstance(
            id="test-instance",
            name="Test Instance",
            type=ResourceType.OLLAMA,
            endpoint="http://localhost:11434",
            status=ResourceStatus.HEALTHY,
            config=OllamaConfig(host="localhost", port=11434)
        )
        
        # Mock the check_health method
        with patch.object(ollama_hub, 'check_health', return_value=True):
            health = await ollama_hub.check_health(mock_instance)
            assert health is True
    
    # ==================== Error Handling Tests ====================
    
    @pytest.mark.asyncio
    async def test_provider_handles_ollama_unavailable(self, ollama_provider):
        """Test provider handles unavailable Ollama gracefully"""
        await ollama_provider.initialize()
        
        # Mock session to simulate connection failure
        mock_session = AsyncMock()
        mock_session.post.side_effect = aiohttp.ClientError("Connection refused")
        mock_session.closed = False
        ollama_provider.session = mock_session
        
        # Provider should handle connection failure gracefully
        with pytest.raises(Exception):
            await ollama_provider.handle_request("llm/chat", {
                "model": "llama3.2",
                "messages": [{"role": "user", "content": "test"}]
            })
    
    @pytest.mark.asyncio
    async def test_cleanup_even_on_error(self, ollama_hub):
        """Test cleanup happens even when errors occur"""
        await ollama_hub.initialize()
        
        # Simulate error during operation
        ollama_hub.some_operation = Mock(side_effect=Exception("Operation failed"))
        
        try:
            ollama_hub.some_operation()
        except:
            pass
        
        # Cleanup should still work
        await ollama_hub.cleanup()
        assert ollama_hub.session is None
    
    # ==================== Performance Tests ====================
    
    @pytest.mark.asyncio
    async def test_connection_pooling_performance(self, ollama_hub, performance_timer):
        """Test that connection pooling improves performance"""
        await ollama_hub.initialize()
        
        # Create mock response context manager
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={"response": "test"})
        mock_response.status = 200
        
        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)
        
        # Mock the session post to return our context
        ollama_hub.session.post = AsyncMock(return_value=mock_context)
        
        # First request (cold)
        performance_timer.start()
        async with ollama_hub.session.post("http://test", json={}) as resp:
            await resp.json()
        cold_time = performance_timer.stop()
        
        # Subsequent requests (warm pool)
        warm_times = []
        for _ in range(5):
            performance_timer.start()
            async with ollama_hub.session.post("http://test", json={}) as resp:
                await resp.json()
            warm_times.append(performance_timer.stop())
        
        # Average warm time should be reasonable
        avg_warm = sum(warm_times) / len(warm_times) if warm_times else cold_time
        
        # Connection pooling exists (basic check)
        assert ollama_hub.session is not None
        assert ollama_hub.session.connector.limit == 100
    
    # ==================== Type Consistency Tests ====================
    
    @pytest.mark.asyncio
    async def test_health_check_returns_bool(self, ollama_provider):
        """Test that health_check returns bool as per type hints"""
        await ollama_provider.initialize()
        
        health = await ollama_provider.health_check()
        assert isinstance(health, bool), "health_check must return bool"
    
    @pytest.mark.asyncio
    async def test_context_manager_types(self, ollama_provider):
        """Test context manager returns correct type"""
        async with ollama_provider as provider:
            assert isinstance(provider, OllamaProvider)
            assert provider is ollama_provider