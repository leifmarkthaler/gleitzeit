"""
Test module for base provider functionality

Tests cover:
- ProtocolProvider abstract base class
- Health check consistency
- Context manager implementation
- Type hint compliance
- Clean separation from resource management

Related components:
- ProtocolProvider
- OllamaProvider
- PythonProvider
- MCPHubProvider
"""

import pytest
import asyncio
from abc import ABC
from typing import Dict, Any, Optional, Type
from unittest.mock import Mock, AsyncMock, patch

from gleitzeit.providers.base import ProtocolProvider


@pytest.mark.unit
class TestProtocolProvider:
    """Test ProtocolProvider abstract base class"""
    
    class MockProvider(ProtocolProvider):
        """Concrete implementation for testing"""
        
        def __init__(self, provider_id: str = "mock"):
            self.provider_id = provider_id  # Changed from self.id
            self.protocol_id = "mock/v1"
            self.initialized = False
            self.cleanup_called = False
        
        async def initialize(self) -> None:
            self.initialized = True
        
        async def handle_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
            return {"method": method, "params": params, "result": "success"}
        
        async def health_check(self) -> bool:
            return self.initialized
        
        async def shutdown(self) -> None:
            self.cleanup_called = True
        
        async def __aenter__(self) -> 'MockProvider':
            await self.initialize()
            return self
        
        async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
            await self.shutdown()
    
    @pytest.fixture
    def mock_provider(self):
        """Create mock provider instance"""
        return self.MockProvider("test_provider")
    
    def test_provider_is_abstract(self):
        """Test that ProtocolProvider cannot be instantiated directly"""
        with pytest.raises(TypeError):
            ProtocolProvider()
    
    def test_provider_has_required_methods(self):
        """Test that ProtocolProvider defines required interface"""
        required_methods = [
            'initialize',
            'handle_request', 
            'health_check',
            'shutdown'
        ]
        
        for method in required_methods:
            assert hasattr(ProtocolProvider, method), f"Missing required method: {method}"
    
    @pytest.mark.asyncio
    async def test_provider_initialization(self, mock_provider):
        """Test provider initialization"""
        assert not mock_provider.initialized
        
        await mock_provider.initialize()
        
        assert mock_provider.initialized
        assert mock_provider.provider_id == "test_provider"
        assert mock_provider.protocol_id == "mock/v1"
    
    @pytest.mark.asyncio
    async def test_provider_handle_request(self, mock_provider):
        """Test provider handle_request method"""
        await mock_provider.initialize()
        
        result = await mock_provider.handle_request(
            "test_method",
            {"param1": "value1", "param2": 42}
        )
        
        assert result["method"] == "test_method"
        assert result["params"]["param1"] == "value1"
        assert result["result"] == "success"
    
    @pytest.mark.asyncio
    async def test_provider_health_check_returns_bool(self, mock_provider):
        """Test that health_check always returns bool"""
        # Before initialization
        health = await mock_provider.health_check()
        assert isinstance(health, bool)
        assert health is False
        
        # After initialization
        await mock_provider.initialize()
        health = await mock_provider.health_check()
        assert isinstance(health, bool)
        assert health is True
    
    @pytest.mark.asyncio
    async def test_provider_cleanup(self, mock_provider):
        """Test provider cleanup"""
        await mock_provider.initialize()
        assert not mock_provider.cleanup_called
        
        await mock_provider.shutdown()
        assert mock_provider.cleanup_called
    
    @pytest.mark.asyncio
    async def test_provider_context_manager(self, mock_provider):
        """Test provider as async context manager"""
        assert not mock_provider.initialized
        assert not mock_provider.cleanup_called
        
        async with mock_provider as provider:
            assert provider is mock_provider
            assert provider.initialized
            assert not provider.cleanup_called
        
        assert provider.cleanup_called
    
    @pytest.mark.asyncio
    async def test_provider_context_manager_with_error(self, mock_provider):
        """Test context manager cleanup on error"""
        class TestError(Exception):
            pass
        
        with pytest.raises(TestError):
            async with mock_provider as provider:
                assert provider.initialized
                raise TestError("Test error")
        
        # Cleanup should still be called
        assert mock_provider.cleanup_called
    
    @pytest.mark.asyncio
    async def test_provider_context_manager_type_hints(self, mock_provider):
        """Test context manager returns correct type"""
        async with mock_provider as provider:
            assert isinstance(provider, self.MockProvider)
            assert provider is mock_provider


@pytest.mark.unit
class TestProviderValidation:
    """Test provider validation and constraints"""
    
    def test_provider_no_resource_management(self):
        """Test that providers don't have resource management methods"""
        # These methods should NOT be in a provider
        forbidden_methods = [
            'start_process',
            'stop_process',
            'start_container',
            'stop_container',
            'allocate_resources',
            'manage_pool',
            'scale_resources'
        ]
        
        from gleitzeit.providers.ollama_provider import OllamaProvider
        from gleitzeit.providers.python_provider import PythonProvider
        from gleitzeit.providers.mcp_hub_provider import MCPHubProvider
        
        providers = [OllamaProvider, PythonProvider, MCPHubProvider]
        
        for provider_class in providers:
            for method in forbidden_methods:
                assert not hasattr(provider_class, method), \
                    f"{provider_class.__name__} should not have {method}"
    
    def test_provider_clean_protocol_implementation(self):
        """Test that providers focus on protocol execution"""
        # These methods SHOULD be in a provider
        required_methods = [
            'handle_request',
            'health_check',
            'initialize',
            'shutdown'
        ]
        
        from gleitzeit.providers.ollama_provider import OllamaProvider
        from gleitzeit.providers.python_provider import PythonProvider
        from gleitzeit.providers.mcp_hub_provider import MCPHubProvider
        
        providers = [OllamaProvider, PythonProvider, MCPHubProvider]
        
        for provider_class in providers:
            for method in required_methods:
                assert hasattr(provider_class, method), \
                    f"{provider_class.__name__} missing required method {method}"


@pytest.mark.unit
class TestOllamaProvider:
    """Test OllamaProvider specific functionality"""
    
    @pytest.fixture
    async def ollama_provider(self):
        """Create OllamaProvider with mock hub"""
        from gleitzeit.providers.ollama_provider import OllamaProvider
        
        mock_hub = AsyncMock()
        mock_hub.ensure_started = AsyncMock(return_value=True)
        mock_hub.session = AsyncMock()
        mock_hub.session.post = AsyncMock()
        
        provider = OllamaProvider(
            provider_id="test_ollama",
            hub=mock_hub
        )
        
        yield provider
        await provider.shutdown()
    
    @pytest.mark.asyncio
    async def test_ollama_provider_initialization(self, ollama_provider):
        """Test OllamaProvider initialization"""
        await ollama_provider.initialize()
        
        assert ollama_provider.provider_id == "test_ollama"
        assert ollama_provider.protocol_id == "llm/v1"
        # OllamaProvider doesn't manage hubs directly in the clean architecture
        # Hub management is handled separately by OllamaHub/ResourceManager
    
    @pytest.mark.asyncio
    async def test_ollama_provider_execute_chat(self, ollama_provider):
        """Test OllamaProvider chat execution"""
        await ollama_provider.initialize()
        
        # Mock the provider's own session
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={
            "response": "Hello!",
            "model": "llama3.2"
        })
        mock_response.raise_for_status = Mock()
        mock_response.status = 200
        
        # Create a proper async context manager mock
        mock_post = AsyncMock()
        mock_post.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post.__aexit__ = AsyncMock(return_value=None)
        
        # Mock the session post method
        ollama_provider.session = AsyncMock()
        ollama_provider.session.post = Mock(return_value=mock_post)
        
        result = await ollama_provider.handle_request("llm/chat", {
            "model": "llama3.2",
            "messages": [{"role": "user", "content": "Hi"}]
        })
        
        assert "response" in result
        ollama_provider.session.post.assert_called()
    
    @pytest.mark.asyncio
    async def test_ollama_provider_health_check(self, ollama_provider):
        """Test OllamaProvider health check"""
        # Before initialization
        health = await ollama_provider.health_check()
        assert isinstance(health, bool)
        
        # After initialization
        await ollama_provider.initialize()
        
        # Mock the provider's session for health check
        mock_response = AsyncMock()
        mock_response.status = 200
        
        # Create a proper async context manager mock
        mock_get = AsyncMock()
        mock_get.__aenter__ = AsyncMock(return_value=mock_response)
        mock_get.__aexit__ = AsyncMock(return_value=None)
        
        ollama_provider.session = AsyncMock()
        ollama_provider.session.get = Mock(return_value=mock_get)
        ollama_provider.session.closed = False
        
        health = await ollama_provider.health_check()
        assert isinstance(health, bool)
        assert health is True  # Should be True when session is healthy


@pytest.mark.unit
class TestPythonProvider:
    """Test PythonProvider specific functionality"""
    
    @pytest.fixture
    def python_provider(self):
        """Create PythonProvider instance"""
        from gleitzeit.providers.python_provider import PythonProvider
        
        return PythonProvider(provider_id="test_python")
    
    @pytest.mark.asyncio
    async def test_python_provider_initialization(self, python_provider):
        """Test PythonProvider initialization"""
        await python_provider.initialize()
        
        assert python_provider.provider_id == "test_python"
        assert python_provider.protocol_id == "python/v1"
    
    @pytest.mark.asyncio
    async def test_python_provider_blocks_untrusted_execution(self, python_provider, temp_dir):
        """Test PythonProvider blocks untrusted script execution for security"""
        await python_provider.initialize()
        
        # Create test script in untrusted directory
        script_path = temp_dir / "test_script.py"
        script_path.write_text("print('Hello from test')")
        
        # Try to execute without container endpoint
        result = await python_provider.handle_request("python/execute", {
            "file_path": str(script_path)
        })
        
        # Should be blocked for security
        assert result["success"] is False
        assert result.get("needs_container") is True
        assert result.get("execution_mode") == "blocked"
    
    @pytest.mark.asyncio
    async def test_python_provider_health_check(self, python_provider):
        """Test PythonProvider health check"""
        health = await python_provider.health_check()
        assert isinstance(health, bool)
        assert health is True  # Python provider should always be healthy
    
    @pytest.mark.asyncio
    async def test_python_provider_no_docker_dependency(self, python_provider):
        """Test that PythonProvider has no Docker dependencies"""
        # Check that provider doesn't have Docker-related attributes
        assert not hasattr(python_provider, 'docker_client')
        assert not hasattr(python_provider, 'container')
        assert not hasattr(python_provider, 'docker_hub')


@pytest.mark.unit
class TestMCPHubProvider:
    """Test MCPHubProvider specific functionality"""
    
    @pytest.fixture
    def mcp_provider(self):
        """Create MCPHubProvider instance"""
        from gleitzeit.providers.mcp_hub_provider import MCPHubProvider
        
        return MCPHubProvider(
            provider_id="test_mcp"
        )
    
    @pytest.mark.asyncio
    async def test_mcp_provider_initialization(self, mcp_provider):
        """Test MCPHubProvider initialization"""
        with patch('asyncio.create_subprocess_exec') as mock_subprocess:
            mock_process = AsyncMock()
            mock_subprocess.return_value = mock_process
            
            await mcp_provider.initialize()
            
            assert mcp_provider.provider_id == "test_mcp"
            assert mcp_provider.protocol_id == "mcp/v1"
    
    @pytest.mark.asyncio
    async def test_mcp_provider_health_check(self, mcp_provider):
        """Test MCPHubProvider health check"""
        health = await mcp_provider.health_check()
        assert isinstance(health, bool)
    
    @pytest.mark.asyncio
    async def test_mcp_provider_cleanup(self, mcp_provider):
        """Test MCPHubProvider cleanup"""
        # MCPHubProvider doesn't manage processes - it's a simple in-memory provider
        # Just test that shutdown can be called without errors
        await mcp_provider.initialize()
        await mcp_provider.shutdown()
        
        # Test that it can be called multiple times safely
        await mcp_provider.shutdown()


@pytest.mark.unit
class TestProviderTypeHints:
    """Test type hint compliance across all providers"""
    
    @pytest.mark.asyncio
    async def test_all_providers_health_check_returns_bool(self):
        """Test that all providers' health_check returns bool"""
        from gleitzeit.providers.ollama_provider import OllamaProvider
        from gleitzeit.providers.python_provider import PythonProvider
        from gleitzeit.providers.mcp_hub_provider import MCPHubProvider
        
        # Create providers with minimal setup
        providers = [
            PythonProvider("test_python"),
            MCPHubProvider("test_mcp")  # MCPHubProvider only takes provider_id
        ]
        
        # OllamaProvider doesn't need a hub in clean architecture
        providers.append(OllamaProvider("test_ollama"))
        
        for provider in providers:
            health = await provider.health_check()
            assert isinstance(health, bool), \
                f"{provider.__class__.__name__}.health_check() must return bool"
    
    @pytest.mark.asyncio
    async def test_all_providers_context_manager_types(self):
        """Test that all providers work as context managers"""
        from gleitzeit.providers.python_provider import PythonProvider
        
        provider = PythonProvider("test")
        
        async with provider as p:
            assert p is provider
            assert isinstance(p, PythonProvider)
    
    def test_all_providers_have_consistent_interface(self):
        """Test that all providers implement consistent interface"""
        from gleitzeit.providers.ollama_provider import OllamaProvider
        from gleitzeit.providers.python_provider import PythonProvider
        from gleitzeit.providers.mcp_hub_provider import MCPHubProvider
        
        providers = [OllamaProvider, PythonProvider, MCPHubProvider]
        
        for provider_class in providers:
            # Check all required methods exist
            assert hasattr(provider_class, 'initialize')
            assert hasattr(provider_class, 'handle_request')
            assert hasattr(provider_class, 'health_check')
            assert hasattr(provider_class, 'shutdown')
            assert hasattr(provider_class, '__aenter__')
            assert hasattr(provider_class, '__aexit__')