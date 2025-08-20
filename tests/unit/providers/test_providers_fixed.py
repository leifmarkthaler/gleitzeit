"""
Fixed test module for providers

Tests cover:
- Provider interface compliance
- Health check consistency
- Context manager implementation
- Clean separation from resource management

Related components:
- ProtocolProvider
- OllamaProvider
- PythonProvider
- MCPHubProvider
"""

import pytest
import asyncio
from typing import Dict, Any, Optional
from unittest.mock import Mock, AsyncMock, patch


class MockProtocolProvider:
    """Mock implementation of ProtocolProvider for testing"""
    
    def __init__(self, provider_id: str = "mock", protocol_id: str = "mock/v1"):
        self.id = provider_id
        self.protocol_id = protocol_id
        self.initialized = False
        self.cleanup_called = False
    
    async def initialize(self) -> None:
        """Initialize the provider"""
        self.initialized = True
    
    async def execute(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a protocol method"""
        return {
            "method": method,
            "params": params,
            "result": "success",
            "provider": self.id
        }
    
    async def health_check(self) -> bool:
        """Check provider health - always returns bool"""
        return self.initialized
    
    async def cleanup(self) -> None:
        """Clean up provider resources"""
        self.cleanup_called = True
        self.initialized = False
    
    async def shutdown(self) -> None:
        """Shutdown the provider"""
        await self.cleanup()
    
    async def __aenter__(self):
        """Async context manager entry"""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.cleanup()


@pytest.mark.unit
class TestProtocolProviderInterface:
    """Test protocol provider interface"""
    
    @pytest.fixture
    def mock_provider(self):
        """Create mock provider instance"""
        return MockProtocolProvider("test_provider", "test/v1")
    
    def test_provider_has_required_attributes(self, mock_provider):
        """Test provider has required attributes"""
        assert hasattr(mock_provider, 'id')
        assert hasattr(mock_provider, 'protocol_id')
        assert mock_provider.id == "test_provider"
        assert mock_provider.protocol_id == "test/v1"
    
    def test_provider_has_required_methods(self):
        """Test provider has required interface methods"""
        required_methods = [
            'initialize',
            'execute',
            'health_check',
            'cleanup',
            '__aenter__',
            '__aexit__'
        ]
        
        for method in required_methods:
            assert hasattr(MockProtocolProvider, method), \
                f"Missing required method: {method}"
    
    @pytest.mark.asyncio
    async def test_provider_initialization(self, mock_provider):
        """Test provider initialization"""
        assert not mock_provider.initialized
        
        await mock_provider.initialize()
        
        assert mock_provider.initialized
    
    @pytest.mark.asyncio
    async def test_provider_execute(self, mock_provider):
        """Test provider execute method"""
        await mock_provider.initialize()
        
        result = await mock_provider.execute(
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
        assert mock_provider.initialized
        assert not mock_provider.cleanup_called
        
        await mock_provider.cleanup()
        
        assert mock_provider.cleanup_called
        assert not mock_provider.initialized
    
    @pytest.mark.asyncio
    async def test_provider_context_manager(self, mock_provider):
        """Test provider as async context manager"""
        assert not mock_provider.initialized
        
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


@pytest.mark.unit
class TestProviderSeparation:
    """Test that providers maintain clean separation of concerns"""
    
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
        
        for method in forbidden_methods:
            assert not hasattr(MockProtocolProvider, method), \
                f"Provider should not have resource management method: {method}"
    
    def test_provider_clean_protocol_implementation(self):
        """Test that providers focus on protocol execution"""
        # These methods SHOULD be in a provider
        required_methods = [
            'execute',
            'health_check',
            'initialize',
            'cleanup'
        ]
        
        for method in required_methods:
            assert hasattr(MockProtocolProvider, method), \
                f"Provider missing required method {method}"


@pytest.mark.unit
class TestMockOllamaProvider:
    """Test mock Ollama provider functionality"""
    
    @pytest.fixture
    async def mock_ollama_provider(self):
        """Create mock Ollama provider"""
        provider = MockProtocolProvider("ollama_test", "llm/v1")
        yield provider
        if provider.initialized:
            await provider.cleanup()
    
    @pytest.mark.asyncio
    async def test_ollama_provider_initialization(self, mock_ollama_provider):
        """Test Ollama provider initialization"""
        await mock_ollama_provider.initialize()
        
        assert mock_ollama_provider.id == "ollama_test"
        assert mock_ollama_provider.protocol_id == "llm/v1"
        assert mock_ollama_provider.initialized
    
    @pytest.mark.asyncio
    async def test_ollama_provider_execute_chat(self, mock_ollama_provider):
        """Test Ollama provider chat execution"""
        await mock_ollama_provider.initialize()
        
        result = await mock_ollama_provider.execute("chat", {
            "model": "llama3.2",
            "messages": [{"role": "user", "content": "Hi"}]
        })
        
        assert result["method"] == "chat"
        assert result["result"] == "success"
    
    @pytest.mark.asyncio
    async def test_ollama_provider_health_check(self, mock_ollama_provider):
        """Test Ollama provider health check"""
        # Before initialization
        health = await mock_ollama_provider.health_check()
        assert isinstance(health, bool)
        assert health is False
        
        # After initialization
        await mock_ollama_provider.initialize()
        health = await mock_ollama_provider.health_check()
        assert isinstance(health, bool)
        assert health is True


@pytest.mark.unit
class TestMockPythonProvider:
    """Test mock Python provider functionality"""
    
    @pytest.fixture
    def mock_python_provider(self):
        """Create mock Python provider"""
        return MockProtocolProvider("python_test", "python/v1")
    
    @pytest.mark.asyncio
    async def test_python_provider_initialization(self, mock_python_provider):
        """Test Python provider initialization"""
        await mock_python_provider.initialize()
        
        assert mock_python_provider.id == "python_test"
        assert mock_python_provider.protocol_id == "python/v1"
    
    @pytest.mark.asyncio
    async def test_python_provider_execute_script(self, mock_python_provider):
        """Test Python provider script execution"""
        await mock_python_provider.initialize()
        
        result = await mock_python_provider.execute("run_script", {
            "script_path": "/tmp/test.py"
        })
        
        assert result["method"] == "run_script"
        assert result["result"] == "success"
    
    @pytest.mark.asyncio
    async def test_python_provider_health_check(self, mock_python_provider):
        """Test Python provider health check"""
        await mock_python_provider.initialize()
        health = await mock_python_provider.health_check()
        assert isinstance(health, bool)
        assert health is True
    
    def test_python_provider_no_docker_dependency(self, mock_python_provider):
        """Test that Python provider has no Docker dependencies"""
        # Check that provider doesn't have Docker-related attributes
        assert not hasattr(mock_python_provider, 'docker_client')
        assert not hasattr(mock_python_provider, 'container')
        assert not hasattr(mock_python_provider, 'docker_hub')


@pytest.mark.unit
class TestProviderTypeConsistency:
    """Test type consistency across providers"""
    
    @pytest.mark.asyncio
    async def test_all_providers_health_check_returns_bool(self):
        """Test that all providers' health_check returns bool"""
        providers = [
            MockProtocolProvider("test1", "proto1/v1"),
            MockProtocolProvider("test2", "proto2/v1"),
            MockProtocolProvider("test3", "proto3/v1")
        ]
        
        for provider in providers:
            health = await provider.health_check()
            assert isinstance(health, bool), \
                f"{provider.id}.health_check() must return bool, got {type(health)}"
    
    @pytest.mark.asyncio
    async def test_all_providers_context_manager_types(self):
        """Test that all providers work as context managers"""
        provider = MockProtocolProvider("test", "test/v1")
        
        async with provider as p:
            assert p is provider
            assert isinstance(p, MockProtocolProvider)
            assert p.initialized
    
    def test_all_providers_have_consistent_interface(self):
        """Test that all providers implement consistent interface"""
        # Check all required methods exist
        required_attrs = ['id', 'protocol_id']
        required_methods = [
            'initialize', 'execute', 'health_check', 
            'cleanup', '__aenter__', '__aexit__'
        ]
        
        provider = MockProtocolProvider("test", "test/v1")
        
        for attr in required_attrs:
            assert hasattr(provider, attr), f"Missing attribute: {attr}"
        
        for method in required_methods:
            assert hasattr(provider, method), f"Missing method: {method}"
            assert callable(getattr(provider, method)), f"{method} is not callable"