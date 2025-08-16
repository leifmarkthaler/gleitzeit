"""
Test suite for ProtocolProvider base class
Tests the core provider interface that all providers must implement
"""

import asyncio
import pytest
from typing import List, Dict, Any
from unittest.mock import Mock, AsyncMock

from gleitzeit.providers.base import ProtocolProvider
from gleitzeit.providers.ollama_provider import OllamaProvider
from gleitzeit.providers.python_provider import PythonProvider
from gleitzeit.providers.simple_mcp_provider import SimpleMCPProvider
from gleitzeit.core.errors import ProviderError, MethodNotSupportedError


class MockProvider(ProtocolProvider):
    """Mock provider for testing base class functionality"""
    
    def __init__(self, provider_id="mock", protocol_id="test/v1"):
        super().__init__(
            provider_id=provider_id,
            protocol_id=protocol_id,
            name="Mock Provider",
            description="Test mock provider"
        )
        self.init_called = False
        self.shutdown_called = False
        self.execute_calls = []
    
    async def initialize(self):
        self.init_called = True
    
    async def shutdown(self):
        self.shutdown_called = True
    
    async def execute(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self.execute_calls.append((method, params))
        if method == "test/echo":
            return {"echo": params.get("message", "")}
        elif method == "test/error":
            raise ProviderError(message="Test error", provider_id=self.provider_id)
        else:
            raise MethodNotSupportedError(method=method, provider_id=self.provider_id)
    
    def get_supported_methods(self) -> List[str]:
        return ["test/echo", "test/error"]
    
    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle JSON-RPC style request"""
        method = request.get("method", "")
        params = request.get("params", {})
        return await self.execute(method, params)
    
    async def health_check(self) -> bool:
        """Check provider health"""
        return self.init_called and not self.shutdown_called


class TestProtocolProviderBase:
    """Test the ProtocolProvider base class"""
    
    def test_provider_creation(self):
        """Test creating a provider instance"""
        provider = MockProvider("test-1", "test/v1")
        assert provider.provider_id == "test-1"
        assert provider.protocol_id == "test/v1"
        assert provider.name == "Mock Provider"
        assert provider.description == "Test mock provider"
    
    @pytest.mark.asyncio
    async def test_provider_lifecycle(self):
        """Test provider initialization and shutdown lifecycle"""
        provider = MockProvider()
        
        # Initially not running
        assert not provider.is_running()
        assert not provider.init_called
        
        # Start provider
        await provider.start()
        assert provider.is_running()
        assert provider.init_called
        
        # Starting again should be idempotent
        await provider.start()
        assert provider.is_running()
        
        # Stop provider
        await provider.stop()
        assert not provider.is_running()
        assert provider.shutdown_called
    
    @pytest.mark.asyncio
    async def test_provider_execution(self):
        """Test executing methods on provider"""
        provider = MockProvider()
        await provider.start()
        
        # Test successful execution
        result = await provider.execute("test/echo", {"message": "hello"})
        assert result == {"echo": "hello"}
        assert len(provider.execute_calls) == 1
        assert provider.execute_calls[0] == ("test/echo", {"message": "hello"})
        
        # Test error method
        with pytest.raises(ProviderError) as exc_info:
            await provider.execute("test/error", {})
        assert "Test error" in str(exc_info.value)
        
        # Test unsupported method
        with pytest.raises(MethodNotSupportedError) as exc_info:
            await provider.execute("test/unknown", {})
        assert "test/unknown" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_provider_methods(self):
        """Test getting supported methods"""
        provider = MockProvider()
        methods = provider.get_supported_methods()
        
        assert isinstance(methods, list)
        assert "test/echo" in methods
        assert "test/error" in methods
        assert len(methods) == 2
    
    @pytest.mark.asyncio
    async def test_provider_health_check(self):
        """Test provider health checking"""
        provider = MockProvider()
        
        # Not healthy before initialization
        assert not await provider.health_check()
        
        # Healthy after start
        await provider.start()
        assert await provider.health_check()
        
        # Not healthy after shutdown
        await provider.stop()
        assert not await provider.health_check()
    
    @pytest.mark.asyncio
    async def test_provider_status(self):
        """Test provider status reporting"""
        provider = MockProvider()
        
        # Get status before start
        status = await provider.get_status()
        assert "status" in status
        assert status["status"] == "ready"
        
        # Get status after start
        await provider.start()
        status = await provider.get_status()
        assert status["status"] in ["ready", "running"]


class TestConcreteProviders:
    """Test that concrete providers implement the interface correctly"""
    
    def test_ollama_provider_interface(self):
        """Test OllamaProvider has required interface"""
        provider = OllamaProvider("test-ollama", default_model="llama3.2")
        
        # Check it's a ProtocolProvider
        assert isinstance(provider, ProtocolProvider)
        
        # Check required methods exist
        assert hasattr(provider, 'initialize')
        assert hasattr(provider, 'shutdown')
        assert hasattr(provider, 'execute')
        assert hasattr(provider, 'get_supported_methods')
        
        # Check methods are returned
        methods = provider.get_supported_methods()
        assert isinstance(methods, list)
        assert len(methods) > 0
        assert any("llm/" in m for m in methods)
        
        # Check metadata
        assert provider.provider_id == "test-ollama"
        assert provider.protocol_id == "llm/v1"
    
    def test_python_provider_interface(self):
        """Test PythonProvider has required interface"""
        provider = PythonProvider("test-python")
        
        # Check it's a ProtocolProvider
        assert isinstance(provider, ProtocolProvider)
        
        # Check methods
        methods = provider.get_supported_methods()
        assert isinstance(methods, list)
        assert "python/execute" in methods
        assert "python/validate" in methods
        assert "python/info" in methods
        
        # Security: No eval/exec methods
        assert "python/eval" not in methods
        assert "python/exec" not in methods
        
        # Check metadata
        assert provider.provider_id == "test-python"
        assert provider.protocol_id == "python/v1"
    
    def test_mcp_provider_interface(self):
        """Test SimpleMCPProvider has required interface"""
        provider = SimpleMCPProvider("test-mcp")
        
        # Check it's a ProtocolProvider
        assert isinstance(provider, ProtocolProvider)
        
        # Check methods
        methods = provider.get_supported_methods()
        assert isinstance(methods, list)
        assert len(methods) > 0
        assert any("mcp/" in m for m in methods)
        
        # Check metadata
        assert provider.provider_id == "test-mcp"
        assert provider.protocol_id == "mcp/v1"
    
    def test_all_providers_follow_convention(self):
        """Test that all providers follow naming conventions"""
        providers = [
            OllamaProvider("test-1", default_model="llama3.2"),
            PythonProvider("test-2"),
            SimpleMCPProvider("test-3")
        ]
        
        for provider in providers:
            # Check method naming convention
            methods = provider.get_supported_methods()
            for method in methods:
                assert isinstance(method, str)
                assert "/" in method, f"Method '{method}' doesn't follow namespace/method format"
                
                # Check it starts with protocol namespace
                parts = method.split("/")
                assert len(parts) >= 2, f"Method '{method}' should have namespace/name"


def test_provider_interface_sync():
    """Synchronous test for provider interface"""
    
    async def run_test():
        provider = MockProvider("sync-test", "test/v1")
        
        # Test basic interface
        assert provider.provider_id == "sync-test"
        assert provider.protocol_id == "test/v1"
        
        # Test lifecycle
        await provider.start()
        assert provider.is_running()
        
        # Test execution
        result = await provider.execute("test/echo", {"message": "sync test"})
        assert result["echo"] == "sync test"
        
        # Test shutdown
        await provider.stop()
        assert not provider.is_running()
        
        return True
    
    result = asyncio.run(run_test())
    assert result == True


if __name__ == '__main__':
    print("Testing ProtocolProvider base class...")
    
    # Run sync test
    test_provider_interface_sync()
    print("✓ Basic interface test passed")
    
    # Test concrete providers
    print("\nTesting concrete provider interfaces...")
    test = TestConcreteProviders()
    
    test.test_ollama_provider_interface()
    print("✓ OllamaProvider interface OK")
    
    test.test_python_provider_interface()
    print("✓ PythonProvider interface OK")
    
    test.test_mcp_provider_interface()
    print("✓ SimpleMCPProvider interface OK")
    
    test.test_all_providers_follow_convention()
    print("✓ All providers follow conventions")
    
    print("\n✅ All ProtocolProvider tests passed!")