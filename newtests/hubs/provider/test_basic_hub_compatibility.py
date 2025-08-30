"""
Basic tests to verify provider-hub compatibility with existing infrastructure

These tests check that:
1. Our new providers work with existing hub patterns
2. The ResourceHub base class can manage provider-related resources
3. Protocol auto-generation works in hub contexts
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock

from gleitzeit.providers.python_provider_v2 import PythonProviderV2
from gleitzeit.hub.base import ResourceHub, ResourceInstance, ResourceType, ResourceStatus
from gleitzeit.hub.docker_hub import DockerHub
from gleitzeit.core.protocol import ParameterType


class TestBasicHubCompatibility:
    """Basic provider-hub compatibility tests"""
    
    @pytest.fixture
    def mock_docker_hub(self):
        """Create a simple mock Docker hub"""
        hub = Mock(spec=DockerHub)
        hub.hub_id = "test_docker_hub"
        hub.running = True
        hub.initialize = AsyncMock()
        hub.cleanup = AsyncMock() 
        hub.execute_in_container = AsyncMock(return_value={
            "success": True,
            "exit_code": 0,
            "output": "Test output",
            "container_id": "test_container"
        })
        return hub

    @pytest.mark.asyncio
    async def test_provider_accepts_hub_parameter(self, mock_docker_hub):
        """Test provider accepts hub in constructor"""
        provider = PythonProviderV2(
            provider_id="test_with_hub",
            docker_hub=mock_docker_hub,
            auto_generate_protocol=True
        )
        
        assert provider.docker_hub is mock_docker_hub
        assert provider.provider_id == "test_with_hub"
        
        await provider.initialize()
        await provider.shutdown()

    @pytest.mark.asyncio
    async def test_provider_without_hub_still_works(self):
        """Test provider works fine without hub"""
        provider = PythonProviderV2(
            provider_id="test_no_hub",
            allow_local=True,
            auto_generate_protocol=True
        )
        
        assert provider.docker_hub is None
        
        await provider.initialize()
        
        # Should still generate protocol
        protocol = provider.get_generated_protocol()
        assert protocol is not None
        assert "execute" in protocol.methods  # Protocol generation detects 'execute' method
        
        # Should report capabilities correctly
        info = await provider.get_info()
        assert info["capabilities"]["docker"] is False
        assert info["capabilities"]["subprocess"] is True
        
        await provider.shutdown()

    @pytest.mark.asyncio
    async def test_hub_provider_pattern_works(self):
        """Test the hub provider pattern (provider that manages a hub)"""
        # This simulates providers like MCPHubProvider that manage their own hubs
        
        class SimpleHubProvider(PythonProviderV2):
            def __init__(self, **kwargs):
                # Create hub internally
                self.managed_hub = Mock()
                self.managed_hub.initialize = AsyncMock()
                self.managed_hub.cleanup = AsyncMock()
                
                super().__init__(**kwargs)
            
            async def initialize(self):
                await self.managed_hub.initialize()
                await super().initialize()
            
            async def shutdown(self):
                await super().shutdown()
                await self.managed_hub.cleanup()
        
        provider = SimpleHubProvider(
            provider_id="hub_provider_test",
            auto_generate_protocol=True
        )
        
        # Should initialize both provider and its managed hub
        await provider.initialize()
        provider.managed_hub.initialize.assert_called_once()
        
        # Should still work as a normal provider
        protocol = provider.get_generated_protocol()
        assert protocol is not None
        assert "execute" in protocol.methods
        
        await provider.shutdown()
        provider.managed_hub.cleanup.assert_called_once()

    def test_protocol_generation_hub_aware_parameters(self):
        """Test protocol generation includes hub-aware parameters"""
        # Provider with Docker hub should include Docker-specific parameters
        mock_hub = Mock()
        provider = PythonProviderV2(
            provider_id="test_docker_params",
            docker_hub=mock_hub,
            auto_generate_protocol=True
        )
        
        protocol = provider.get_generated_protocol()
        assert protocol is not None
        
        # Check execute method has Docker-specific parameters  
        execute_method = protocol.methods["execute"]
        params = execute_method.params_schema
        
        # Should have execution mode and Docker image parameters
        assert "execution_mode" in params
        assert "docker_image" in params
        
        # Execution mode should have proper type
        assert params["execution_mode"].type == ParameterType.STRING

    @pytest.mark.asyncio
    async def test_provider_execution_mode_selection(self):
        """Test provider selects execution mode based on available resources"""
        # Test with no hub (should prefer subprocess/thread)
        provider_no_hub = PythonProviderV2(
            provider_id="no_hub_test",
            allow_local=True,
            allow_threads=True
        )
        await provider_no_hub.initialize()
        
        # Should have no Docker capability
        info = await provider_no_hub.get_info()
        assert info["capabilities"]["docker"] is False
        
        # Test with hub (should have Docker capability)  
        mock_hub = Mock()
        mock_hub.initialize = AsyncMock()
        mock_hub.cleanup = AsyncMock()
        
        provider_with_hub = PythonProviderV2(
            provider_id="with_hub_test",
            docker_hub=mock_hub,
            allow_local=True
        )
        await provider_with_hub.initialize()
        
        info = await provider_with_hub.get_info()
        assert info["capabilities"]["docker"] is True
        
        await provider_no_hub.shutdown()
        await provider_with_hub.shutdown()

    def test_resource_hub_base_class_compatibility(self):
        """Test that ResourceHub base class supports provider resources"""
        # This tests that the ResourceHub base class can handle provider-specific resources
        
        from gleitzeit.hub.configs import OllamaConfig
        
        # Mock configuration for testing
        config = OllamaConfig(host="localhost", port=11434)
        
        # Create a resource instance representing a provider resource
        instance = ResourceInstance(
            id="provider_resource_123",
            name="Python Provider Resource",
            type=ResourceType.CUSTOM,  # Providers would use custom type
            endpoint="provider://python_provider",
            config=config
        )
        
        # Should create successfully
        assert instance.id == "provider_resource_123"
        assert instance.type == ResourceType.CUSTOM
        assert instance.is_available() is False  # Default status is UNKNOWN
        
        # Update status to healthy
        instance.status = ResourceStatus.HEALTHY
        assert instance.is_available() is True
        
        # Should convert to dict properly
        instance_dict = instance.to_dict()
        assert instance_dict["id"] == "provider_resource_123"
        assert instance_dict["type"] == "custom"

    @pytest.mark.asyncio 
    async def test_provider_hub_lifecycle_coordination(self):
        """Test provider and hub lifecycle coordination"""
        mock_hub = Mock()
        mock_hub.initialize = AsyncMock()
        mock_hub.cleanup = AsyncMock()
        mock_hub.running = False
        
        provider = PythonProviderV2(
            provider_id="lifecycle_test",
            docker_hub=mock_hub
        )
        
        # Initialize provider (should work regardless of hub state)
        await provider.initialize()
        # Provider should initialize even if hub setup fails
        # Note: provider._initialized may be False if Docker hub setup fails
        # but provider should still be functional for non-Docker operations
        
        # Provider health should not depend on hub health for basic functionality
        health = await provider.health_check() 
        assert health is True
        
        # Shutdown should work
        await provider.shutdown()
        assert provider._initialized is False

    def test_backward_compatibility_with_existing_tests(self):
        """Test that our changes don't break existing provider patterns"""
        # This ensures existing code using providers still works
        
        # Basic provider creation (old style)
        provider = PythonProviderV2(provider_id="backward_compat_test")
        assert provider.provider_id == "backward_compat_test"
        assert provider.docker_hub is None
        
        # Protocol generation still works
        provider_with_protocol = PythonProviderV2(
            provider_id="protocol_test",
            auto_generate_protocol=True
        )
        protocol = provider_with_protocol.get_generated_protocol()
        assert protocol is not None
        
        # Method introspection still works
        methods = provider.get_supported_methods()
        assert isinstance(methods, list)
        assert len(methods) > 0


class TestHubResourceManagement:
    """Test hub resource management for provider resources"""
    
    @pytest.mark.asyncio
    async def test_hub_can_manage_provider_instances(self):
        """Test ResourceHub can track provider instances as resources"""
        from gleitzeit.hub.base import ResourceHub, ResourceType
        
        # Create a concrete hub implementation for testing
        class MockProviderHub(ResourceHub):
            async def check_health(self, instance):
                return True
            
            async def collect_metrics(self, instance):
                from gleitzeit.hub.base import ResourceMetrics
                return ResourceMetrics()
            
            async def start_instance(self, config):
                return ResourceInstance(
                    id="started_instance",
                    name="Started Provider",
                    type=self.resource_type,
                    endpoint="provider://started"
                )
            
            async def stop_instance(self, instance_id):
                return True
            
            async def restart_instance(self, instance_id):
                return True
        
        hub = MockProviderHub(
            hub_id="provider_hub_test",
            resource_type=ResourceType.CUSTOM
        )
        
        await hub.start()
        
        # Register a provider as a resource
        provider_instance = await hub.register_instance(
            instance_id="python_provider_1",
            name="Python Provider Instance",
            endpoint="provider://python_v2",
            capabilities={"python_execution", "docker_support"},
            tags={"provider", "python"}
        )
        
        assert provider_instance.id == "python_provider_1"
        assert "python_execution" in provider_instance.capabilities
        assert "provider" in provider_instance.tags
        
        # Hub should track the instance
        instances = await hub.list_instances()
        assert len(instances) == 1
        assert instances[0].id == "python_provider_1"
        
        await hub.stop()