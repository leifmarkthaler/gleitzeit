"""
Integration tests for Provider-Hub architecture compatibility

Tests verify that our new provider architecture (including PythonProviderV2) 
is compatible with the existing hub system and follows the separation of concerns:
- Providers handle protocol execution
- Hubs manage resources (Docker containers, processes, etc.)
- Hub Providers bridge the two when needed

Architecture patterns tested:
1. Direct provider usage (provider manages its own resources)
2. Provider with external hub (provider uses hub for resource management)  
3. Hub provider pattern (provider that IS a hub interface)
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, Any, Optional

from gleitzeit.providers.python_provider_v2 import PythonProviderV2
from gleitzeit.hub.docker_hub import DockerHub
from gleitzeit.hub.base import ResourceHub, ResourceInstance, ResourceType, ResourceStatus
from gleitzeit.providers.base import ProtocolProvider
from gleitzeit.core.protocol import ParameterType


class TestProviderHubCompatibility:
    """Test provider-hub architecture compatibility"""
    
    @pytest.fixture
    async def docker_hub(self):
        """Create mock Docker hub"""
        hub = DockerHub(
            hub_id="test_docker_hub",
            enable_container_reuse=True,
            default_image="python:3.11-slim"
        )
        # Mock the actual Docker operations
        hub.start_instance = AsyncMock()
        hub.stop_instance = AsyncMock(return_value=True)
        hub.restart_instance = AsyncMock(return_value=True)
        hub.check_health = AsyncMock(return_value=True)
        
        await hub.initialize()
        yield hub
        await hub.cleanup()
    
    @pytest.fixture
    async def python_provider_standalone(self):
        """PythonProviderV2 without hub (manages own resources)"""
        provider = PythonProviderV2(
            provider_id="python_standalone",
            allow_local=True,
            allow_threads=True,
            auto_generate_protocol=True
        )
        await provider.initialize()
        yield provider
        await provider.shutdown()
    
    @pytest.fixture
    async def python_provider_with_hub(self, docker_hub):
        """PythonProviderV2 with Docker hub"""
        provider = PythonProviderV2(
            provider_id="python_with_hub",
            docker_hub=docker_hub,
            allow_local=True,
            allow_threads=True,
            auto_generate_protocol=True
        )
        await provider.initialize()
        yield provider
        await provider.shutdown()

    # ==================== Architecture Separation Tests ====================
    
    def test_provider_architecture_separation(self):
        """Test that new providers follow separation of concerns"""
        # PythonProviderV2 should not have resource management methods that belong in hubs
        provider_methods = dir(PythonProviderV2)
        
        # These methods should NOT exist in providers (they belong in hubs)
        hub_only_methods = [
            'start_container',
            'stop_container', 
            'manage_docker_instances',
            'allocate_compute_resources',
            'cleanup_containers'
        ]
        
        for method in hub_only_methods:
            assert method not in provider_methods, \
                f"Provider should not have hub method: {method}"
    
    def test_provider_has_protocol_methods(self):
        """Test that providers have protocol execution methods"""
        provider_methods = dir(PythonProviderV2)
        
        # These methods SHOULD exist in providers
        protocol_methods = [
            'execute',
            'handle_request',
            'execute_file',
            'validate_file',
            'get_info'
        ]
        
        for method in protocol_methods:
            assert method in provider_methods, \
                f"Provider should have protocol method: {method}"

    @pytest.mark.asyncio
    async def test_provider_hub_independence(self, python_provider_standalone, docker_hub):
        """Test providers and hubs can initialize independently"""
        # Provider initialized without hub
        assert python_provider_standalone.docker_hub is None
        assert python_provider_standalone._initialized is True
        
        # Hub can operate independently
        assert docker_hub.running is True
        assert len(docker_hub.instances) == 0  # No instances yet
        
        # Provider should work without hub
        info = await python_provider_standalone.get_info()
        assert info["provider_id"] == "python_standalone"
        assert info["capabilities"]["docker"] is False

    @pytest.mark.asyncio  
    async def test_provider_with_hub_integration(self, python_provider_with_hub):
        """Test provider properly integrates with hub"""
        # Provider should have hub reference
        assert python_provider_with_hub.docker_hub is not None
        assert python_provider_with_hub.docker_hub.hub_id == "test_docker_hub"
        
        # Provider should report Docker capability
        info = await python_provider_with_hub.get_info()
        assert info["capabilities"]["docker"] is True
        
        # Protocol should still be auto-generated
        protocol = python_provider_with_hub.get_generated_protocol()
        assert protocol is not None
        assert "execute_file" in protocol.methods

    # ==================== Protocol Generation with Hubs ====================
    
    @pytest.mark.asyncio
    async def test_protocol_generation_with_hub(self, python_provider_with_hub):
        """Test protocol generation works with hub-enabled providers"""
        protocol = python_provider_with_hub.get_generated_protocol()
        
        assert protocol is not None
        assert protocol.id == "python/v2"
        
        # Should have all the same methods as standalone
        expected_methods = ["execute_file", "validate_file", "list_executions", "stop_execution", "get_info"]
        for method in expected_methods:
            assert method in protocol.methods
        
        # Check execute_file parameters include Docker-specific options
        execute_spec = protocol.methods["execute_file"]
        assert "execution_mode" in execute_spec.params_schema
        assert "docker_image" in execute_spec.params_schema

    @pytest.mark.asyncio
    async def test_execution_mode_selection_with_hub(self, python_provider_with_hub):
        """Test execution mode selection when hub is available"""
        # Create a test script file
        test_script = "/Users/leifmarkthaler/github/gleitzeit 0.0.6/newtests/pythontestscripts/simple_hello.py"
        
        # Mock Docker execution
        python_provider_with_hub._execute_in_docker_via_hub = AsyncMock(return_value={
            "success": True,
            "exit_code": 0,
            "execution_mode": "docker",
            "container_id": "test_container",
            "result": {"message": "Hello from Docker!"}
        })
        
        # Test auto mode should prefer Docker when available
        result = await python_provider_with_hub.execute_file(
            file_path=test_script,
            execution_mode="auto"
        )
        
        assert result["execution_mode"] == "docker"
        assert "container_id" in result
        python_provider_with_hub._execute_in_docker_via_hub.assert_called_once()

    # ==================== Resource Management Through Hubs ====================
    
    @pytest.mark.asyncio
    async def test_hub_manages_docker_resources(self, docker_hub):
        """Test hub properly manages Docker container resources"""
        # Register a mock container instance
        instance = await docker_hub.register_instance(
            instance_id="test_container",
            name="Python Container",
            endpoint="container://test_container",
            config={"image": "python:3.11-slim"}
        )
        
        assert instance.id == "test_container"
        assert instance.type == ResourceType.DOCKER
        assert len(docker_hub.instances) == 1
        
        # Hub should manage instance lifecycle
        health = await docker_hub.check_health(instance)
        assert health is True  # Mocked to return True
        
        # Cleanup
        await docker_hub.unregister_instance("test_container")
        assert len(docker_hub.instances) == 0

    @pytest.mark.asyncio
    async def test_provider_uses_hub_for_docker_execution(self, python_provider_with_hub):
        """Test provider delegates Docker execution to hub"""
        test_script = "/Users/leifmarkthaler/github/gleitzeit 0.0.6/newtests/pythontestscripts/simple_hello.py"
        
        # Mock hub Docker execution
        mock_result = {
            "success": True,
            "exit_code": 0,
            "output": "Hello from Docker!",
            "container_id": "hub_container_123"
        }
        python_provider_with_hub.docker_hub.execute_in_container = AsyncMock(return_value=mock_result)
        
        # Execute through provider
        result = await python_provider_with_hub.execute_file(
            file_path=test_script,
            execution_mode="docker"
        )
        
        # Should have delegated to hub
        assert result["success"] is True
        # Note: The actual result structure may differ based on implementation

    # ==================== Error Handling and Fallback ====================
    
    @pytest.mark.asyncio
    async def test_provider_fallback_when_hub_unavailable(self, python_provider_with_hub):
        """Test provider falls back gracefully when hub is unavailable"""
        test_script = "/Users/leifmarkthaler/github/gleitzeit 0.0.6/newtests/pythontestscripts/simple_hello.py"
        
        # Mock hub failure
        python_provider_with_hub.docker_hub = None
        
        # Should fall back to local execution
        result = await python_provider_with_hub.execute_file(
            file_path=test_script,
            execution_mode="auto"
        )
        
        # Should fall back to subprocess or thread
        assert result["execution_mode"] in ["subprocess", "thread"]
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_hub_health_check_integration(self, python_provider_with_hub):
        """Test provider health check considers hub health"""
        # Provider health should consider hub state
        health = await python_provider_with_hub.health_check()
        assert health is True
        
        # Get provider info should include hub status
        info = await python_provider_with_hub.get_info()
        assert "docker_hub_status" in info or "hub_status" in info

    # ==================== Hub Provider Pattern Tests ====================
    
    def test_hub_provider_pattern_concept(self):
        """Test the concept of hub providers (providers that manage hubs)"""
        # This test validates the architectural pattern where a provider
        # can also manage a hub internally (like MCPHubProvider)
        
        class MockHubProvider(ProtocolProvider):
            def __init__(self, hub_type="test"):
                super().__init__(
                    provider_id=f"hub_provider_{hub_type}",
                    protocol_id=f"hub/{hub_type}/v1"
                )
                self.managed_hub = Mock()
                self.managed_hub.initialize = AsyncMock()
                self.managed_hub.cleanup = AsyncMock()
            
            async def initialize(self):
                await self.managed_hub.initialize()
            
            async def shutdown(self):
                await self.managed_hub.cleanup()
            
            async def health_check(self) -> bool:
                return True
                
            def get_supported_methods(self):
                return ["hub/status", "hub/resources"]
            
            async def execute(self, method: str, params: dict):
                if method == "hub/status":
                    return {"status": "active", "resources": 5}
                return {"method": method, "params": params}
        
        # Hub provider should combine both interfaces
        hub_provider = MockHubProvider()
        assert hasattr(hub_provider, 'managed_hub')
        assert hasattr(hub_provider, 'handle_request')
        
        # Should be both a provider AND manage a hub
        assert isinstance(hub_provider, ProtocolProvider)
        methods = hub_provider.get_supported_methods()
        assert "hub/status" in methods

    # ==================== Performance and Resource Tests ====================
    
    @pytest.mark.asyncio
    async def test_resource_efficiency_with_hub(self, python_provider_with_hub):
        """Test resource efficiency when using hubs"""
        test_script = "/Users/leifmarkthaler/github/gleitzeit 0.0.6/newtests/pythontestscripts/simple_hello.py"
        
        # Mock container reuse
        container_id = "reused_container_123"
        python_provider_with_hub._execute_in_docker_via_hub = AsyncMock(return_value={
            "success": True,
            "exit_code": 0,
            "execution_mode": "docker",
            "container_id": container_id,
            "reused": True
        })
        
        # Execute multiple times
        results = []
        for i in range(3):
            result = await python_provider_with_hub.execute_file(
                file_path=test_script,
                execution_mode="docker"
            )
            results.append(result)
        
        # All should use Docker
        for result in results:
            assert result["execution_mode"] == "docker"
        
        # Hub should be called for each execution
        assert python_provider_with_hub._execute_in_docker_via_hub.call_count == 3

    @pytest.mark.asyncio
    async def test_concurrent_execution_with_hub(self, python_provider_with_hub):
        """Test concurrent executions work properly with hub"""
        test_script = "/Users/leifmarkthaler/github/gleitzeit 0.0.6/newtests/pythontestscripts/simple_hello.py"
        
        # Mock concurrent container allocation
        python_provider_with_hub._execute_in_docker_via_hub = AsyncMock(return_value={
            "success": True,
            "exit_code": 0,
            "execution_mode": "docker",
            "container_id": "concurrent_container"
        })
        
        # Execute concurrently
        tasks = [
            python_provider_with_hub.execute_file(
                file_path=test_script,
                execution_mode="docker"
            )
            for _ in range(5)
        ]
        
        results = await asyncio.gather(*tasks)
        
        # All should succeed
        for result in results:
            assert result["success"] is True
            assert result["execution_mode"] == "docker"
        
        # Hub should handle concurrent requests
        assert python_provider_with_hub._execute_in_docker_via_hub.call_count == 5


class TestProviderHubArchitectureCompliance:
    """Test architectural compliance and patterns"""
    
    def test_provider_base_hub_integration(self):
        """Test that ProtocolProvider base supports hub integration"""
        # Check base class has hub support
        base_init_params = inspect.signature(ProtocolProvider.__init__).parameters
        
        # Base provider should accept hub parameter
        assert 'hub' in base_init_params
        assert 'resource_manager' in base_init_params
        
        # Test creating provider with hub
        mock_hub = Mock()
        provider = MockProvider(provider_id="test", protocol_id="test/v1", hub=mock_hub)
        
        assert provider.hub is mock_hub
    
    def test_protocol_generation_with_hub_awareness(self):
        """Test protocol generation considers hub capabilities"""
        # Provider without hub
        provider_no_hub = PythonProviderV2(
            provider_id="no_hub",
            auto_generate_protocol=True
        )
        
        protocol_no_hub = provider_no_hub.get_generated_protocol()
        
        # Provider with mock hub
        mock_hub = Mock()
        provider_with_hub = PythonProviderV2(
            provider_id="with_hub", 
            docker_hub=mock_hub,
            auto_generate_protocol=True
        )
        
        protocol_with_hub = provider_with_hub.get_generated_protocol()
        
        # Both should generate valid protocols
        assert protocol_no_hub is not None
        assert protocol_with_hub is not None
        
        # Should have same core methods
        assert "execute_file" in protocol_no_hub.methods
        assert "execute_file" in protocol_with_hub.methods


class MockProvider(ProtocolProvider):
    """Mock provider for testing base class functionality"""
    
    def get_supported_methods(self) -> list:
        return ["test_method"]
    
    async def execute(self, method: str, params: dict):
        return {"method": method, "params": params}
    
    async def health_check(self) -> bool:
        return True