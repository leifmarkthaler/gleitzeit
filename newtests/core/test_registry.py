"""
Test the Protocol Provider Registry
"""
import pytest
import asyncio
from unittest.mock import Mock, MagicMock, AsyncMock

from gleitzeit.registry import ProtocolProviderRegistry, ProviderStatus
from gleitzeit.core.protocol import ProtocolSpec, MethodSpec, ParameterSpec, ParameterType
from gleitzeit.core.jsonrpc import JSONRPCRequest, JSONRPCResponse
from gleitzeit.core.errors import ProtocolError


@pytest.fixture
def registry():
    """Create a fresh registry for each test"""
    return ProtocolProviderRegistry()


@pytest.fixture
def sample_protocol():
    """Create a sample protocol specification"""
    return ProtocolSpec(
        name="test",
        version="v1",
        description="Test protocol",
        methods={
            "test/method1": MethodSpec(
                name="test/method1",
                description="Test method 1",
                params_schema={
                    "param1": ParameterSpec(
                        type=ParameterType.STRING,
                        description="Test parameter",
                        required=True
                    )
                }
            ),
            "test/method2": MethodSpec(
                name="test/method2",
                description="Test method 2",
                params_schema={}
            )
        }
    )


@pytest.fixture
def mock_provider():
    """Create a mock provider"""
    provider = Mock()  # Back to regular Mock
    provider.__class__.__name__ = "MockProvider"
    provider.get_supported_methods = Mock(return_value=["test/method1", "test/method2"])
    # handle_request takes (method, params) as arguments
    provider.handle_request = AsyncMock(return_value={"result": "success"})
    # _preprocess_params should return params unchanged
    provider._preprocess_params = AsyncMock(side_effect=lambda method, params: params)
    # Make sure execute_with_stats is not present
    delattr(provider, 'execute_with_stats') if hasattr(provider, 'execute_with_stats') else None
    return provider


class TestProtocolRegistration:
    """Test protocol registration functionality"""
    
    def test_register_protocol(self, registry, sample_protocol):
        """Test registering a protocol"""
        registry.register_protocol(sample_protocol)
        
        # Verify protocol is registered
        assert "test/v1" in registry.list_protocols()
        # Check that protocol is in internal registry
        retrieved = registry.protocol_registry.get("test/v1")
        assert retrieved == sample_protocol
    
    def test_register_duplicate_protocol(self, registry, sample_protocol):
        """Test that duplicate protocol registration is handled"""
        registry.register_protocol(sample_protocol)
        
        # Try to register again - should update, not error
        registry.register_protocol(sample_protocol)
        assert registry.list_protocols().count("test/v1") == 1
    
    def test_get_nonexistent_protocol(self, registry):
        """Test getting a protocol that doesn't exist"""
        # Check that protocol is not in registry
        assert "nonexistent/v1" not in registry.list_protocols()
        retrieved = registry.protocol_registry.get("nonexistent/v1")
        assert retrieved is None


class TestProviderRegistration:
    """Test provider registration functionality"""
    
    def test_register_provider(self, registry, sample_protocol, mock_provider):
        """Test registering a provider"""
        registry.register_protocol(sample_protocol)
        registry.register_provider("provider1", "test/v1", mock_provider)
        
        # Verify provider is registered
        provider_info = registry.providers.get("provider1")
        assert provider_info is not None
        assert provider_info.protocol_id == "test/v1"
        assert provider_info.provider_class == "MockProvider"
    
    def test_register_provider_without_protocol(self, registry, mock_provider):
        """Test that registering provider without protocol fails"""
        with pytest.raises(ProtocolError, match="Protocol not registered"):
            registry.register_provider("provider1", "nonexistent/v1", mock_provider)
    
    def test_auto_detect_supported_methods(self, registry, sample_protocol):
        """Test auto-detection of supported methods"""
        registry.register_protocol(sample_protocol)
        
        # Provider with get_supported_methods
        provider_with_methods = Mock()
        provider_with_methods.__class__.__name__ = "TestProvider"
        provider_with_methods.get_supported_methods = Mock(return_value=["test/method1"])
        
        registry.register_provider("provider1", "test/v1", provider_with_methods)
        
        provider_info = registry.providers["provider1"]
        assert "test/method1" in provider_info.supported_methods
        assert "test/method2" not in provider_info.supported_methods
    
    def test_default_to_all_methods(self, registry, sample_protocol):
        """Test defaulting to all protocol methods when not specified"""
        registry.register_protocol(sample_protocol)
        
        # Provider without get_supported_methods attribute
        provider_without_methods = Mock(spec=[])  # Empty spec means no methods
        provider_without_methods.__class__.__name__ = "TestProvider"
        
        registry.register_provider("provider2", "test/v1", provider_without_methods)
        
        provider_info = registry.providers["provider2"]
        assert "test/method1" in provider_info.supported_methods
        assert "test/method2" in provider_info.supported_methods


class TestProviderSelection:
    """Test provider selection logic"""
    
    def test_select_healthy_provider(self, registry, sample_protocol, mock_provider):
        """Test selecting a healthy provider"""
        registry.register_protocol(sample_protocol)
        registry.register_provider("provider1", "test/v1", mock_provider)
        
        provider_info = registry.select_provider("test/v1", "test/method1")
        assert provider_info is not None
        assert provider_info.provider_id == "provider1"
    
    def test_no_provider_for_method(self, registry, sample_protocol):
        """Test when no provider supports the method"""
        registry.register_protocol(sample_protocol)
        
        # Provider that only supports method1
        limited_provider = Mock()
        limited_provider.__class__.__name__ = "LimitedProvider"
        limited_provider.get_supported_methods = Mock(return_value=["test/method1"])
        
        registry.register_provider("limited", "test/v1", limited_provider)
        
        # Try to get provider for method2
        provider_info = registry.select_provider("test/v1", "test/method2")
        assert provider_info is None
    
    def test_select_from_multiple_providers(self, registry, sample_protocol):
        """Test selection when multiple providers are available"""
        registry.register_protocol(sample_protocol)
        
        # Register multiple providers
        for i in range(3):
            provider = Mock()
            provider.__class__.__name__ = f"Provider{i}"
            provider.get_supported_methods = Mock(return_value=["test/method1", "test/method2"])
            registry.register_provider(f"provider{i}", "test/v1", provider)
        
        # Should get one of them
        provider_info = registry.select_provider("test/v1", "test/method1")
        assert provider_info is not None
        assert provider_info.provider_id in ["provider0", "provider1", "provider2"]


class TestRequestExecution:
    """Test request execution through the registry"""
    
    @pytest.mark.asyncio
    async def test_execute_request_success(self, registry, sample_protocol, mock_provider):
        """Test successful request execution"""
        registry.register_protocol(sample_protocol)
        registry.register_provider("provider1", "test/v1", mock_provider)
        
        request = JSONRPCRequest(
            method="test/method1",
            params={"param1": "value1"},
            id="req1"
        )
        
        response = await registry.execute_request("test/v1", request)
        
        assert response.result == {"result": "success"}
        assert response.error is None
        mock_provider.handle_request.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_execute_request_no_provider(self, registry, sample_protocol):
        """Test request execution when no provider is available"""
        registry.register_protocol(sample_protocol)
        # No provider registered
        
        request = JSONRPCRequest(
            method="test/method1",
            params={"param1": "value1"},
            id="req1"
        )
        
        response = await registry.execute_request("test/v1", request)
        
        assert response.result is None
        assert response.error is not None
        assert "No providers available" in response.error.message
    
    @pytest.mark.asyncio
    async def test_execute_request_provider_error(self, registry, sample_protocol):
        """Test request execution when provider raises an error"""
        registry.register_protocol(sample_protocol)
        
        # Provider that raises an error
        error_provider = Mock(spec=['get_supported_methods', 'handle_request', '_preprocess_params'])
        error_provider.__class__.__name__ = "ErrorProvider"
        error_provider.get_supported_methods = Mock(return_value=["test/method1"])
        error_provider.handle_request = AsyncMock(side_effect=Exception("Provider failed"))
        error_provider._preprocess_params = AsyncMock(side_effect=lambda method, params: params)
        
        registry.register_provider("error_provider", "test/v1", error_provider)
        
        request = JSONRPCRequest(
            method="test/method1",
            params={"param1": "value1"},
            id="req1"
        )
        
        response = await registry.execute_request("test/v1", request)
        
        assert response.result is None
        assert response.error is not None
        assert "Provider failed" in response.error.message


class TestProviderHealth:
    """Test provider health tracking"""
    
    def test_unhealthy_provider_not_selected(self, registry, sample_protocol, mock_provider):
        """Test that unhealthy providers are not selected"""
        registry.register_protocol(sample_protocol)
        registry.register_provider("provider1", "test/v1", mock_provider)
        
        # Mark provider as unhealthy
        provider_info = registry.providers["provider1"]
        provider_info.status = ProviderStatus.UNHEALTHY
        
        # Should not be selected
        selected = registry.select_provider("test/v1", "test/method1")
        assert selected is None
    
    def test_provider_performance_tracking(self, registry, sample_protocol, mock_provider):
        """Test that provider performance is tracked"""
        registry.register_protocol(sample_protocol)
        registry.register_provider("provider1", "test/v1", mock_provider)
        
        provider_info = registry.providers["provider1"]
        initial_count = provider_info.total_requests
        
        # Record some metrics
        provider_info.update_stats(success=True, response_time=0.5)
        
        assert provider_info.total_requests == initial_count + 1
        assert provider_info.successful_requests == 1
        assert provider_info.average_response_time > 0


class TestProtocolMethodSplit:
    """Test handling of protocol/method splitting"""
    
    def test_method_with_protocol_prefix(self, registry, sample_protocol, mock_provider):
        """Test that methods work with protocol prefix"""
        registry.register_protocol(sample_protocol)
        registry.register_provider("provider1", "test/v1", mock_provider)
        
        # Method includes protocol prefix
        provider_info = registry.select_provider("test/v1", "test/method1")
        assert provider_info is not None
    
    def test_method_without_protocol_prefix(self, registry, mock_provider):
        """Test handling of methods without protocol prefix"""
        # Create protocol with methods that don't include prefix
        protocol = ProtocolSpec(
            name="simple",
            version="v1",
            description="Simple protocol",
            methods={
                "execute": MethodSpec(
                    name="execute",
                    description="Execute method",
                    params_schema={}
                )
            }
        )
        
        registry.register_protocol(protocol)
        
        # Provider that supports just "execute"
        provider = Mock()
        provider.__class__.__name__ = "SimpleProvider"
        provider.get_supported_methods = Mock(return_value=["execute"])
        
        registry.register_provider("simple_provider", "simple/v1", provider)
        
        # Should find provider for "execute"
        provider_info = registry.select_provider("simple/v1", "execute")
        assert provider_info is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])