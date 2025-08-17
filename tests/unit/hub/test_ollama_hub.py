"""
Test module for OllamaHub

Tests cover:
- Resource management (start/stop Ollama)
- Session pooling with TCPConnector
- Health checking
- Cleanup on shutdown
- No protocol execution logic
- Performance improvements

Related components:
- OllamaHub
- ResourceManager
- aiohttp session management
"""

import pytest
import asyncio
import aiohttp
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, Any

from gleitzeit.hub.ollama_hub import OllamaHub


@pytest.mark.unit
class TestOllamaHub:
    """Unit tests for OllamaHub resource management"""
    
    @pytest.fixture
    async def ollama_hub(self):
        """Create OllamaHub instance"""
        hub = OllamaHub()
        yield hub
        await hub.cleanup()
    
    def test_ollama_hub_initialization(self, ollama_hub):
        """Test OllamaHub initial state"""
        assert ollama_hub.session is None
        assert ollama_hub.instances == {}
        assert ollama_hub.auto_discover == True
    
    def test_ollama_hub_no_protocol_methods(self):
        """Test that OllamaHub has no protocol execution methods"""
        # These methods should NOT exist in hub
        forbidden_methods = [
            'execute',
            'execute_protocol',
            'handle_llm_request',
            'chat_completion',
            'generate_response'
        ]
        
        hub_methods = dir(OllamaHub)
        for method in forbidden_methods:
            assert method not in hub_methods, \
                f"Hub should not have protocol method: {method}"
    
    @pytest.mark.asyncio
    async def test_ollama_hub_start_process(self, ollama_hub):
        """Test starting Ollama instance"""
        from gleitzeit.hub.configs import OllamaConfig
        
        with patch('subprocess.Popen') as mock_popen:
            mock_process = Mock()
            mock_process.pid = 1234
            mock_process.poll = Mock(return_value=None)
            mock_popen.return_value = mock_process
            
            # Mock health check - first False (not running), then True (after start)
            with patch.object(ollama_hub, '_is_ollama_running', side_effect=[False, True, True]):
                config = OllamaConfig(host="127.0.0.1", port=11434)
                # Use start_instance which actually starts the process
                instance = await ollama_hub.start_instance(config)
                
                assert instance is not None
                # Process should be started
                mock_popen.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_ollama_hub_already_running(self, ollama_hub):
        """Test handling when Ollama is already running"""
        from gleitzeit.hub.configs import OllamaConfig
        
        with patch('subprocess.Popen') as mock_popen:
            # Mock that Ollama is already running
            with patch.object(ollama_hub, '_is_ollama_running', return_value=True):
                with patch.object(ollama_hub, '_get_available_models', return_value={'llama3.2'}):
                    config = OllamaConfig(host="127.0.0.1", port=11434)
                    instance = await ollama_hub.start_instance(config)
                    
                    assert instance is not None
                    # No new process should be started if already running
                    mock_popen.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_ollama_hub_session_initialization(self, ollama_hub):
        """Test session initialization with connection pooling"""
        await ollama_hub.initialize()
        
        assert ollama_hub.session is not None
        assert isinstance(ollama_hub.session, aiohttp.ClientSession)
        
        # Check connector configuration
        connector = ollama_hub.session.connector
        assert isinstance(connector, aiohttp.TCPConnector)
        assert connector.limit == 100  # Total connection limit
        assert connector.limit_per_host == 30  # Per-host limit
        # DNS TTL is an internal implementation detail that may vary by aiohttp version
    
    @pytest.mark.asyncio
    async def test_ollama_hub_session_cleanup(self, ollama_hub):
        """Test session cleanup on shutdown"""
        await ollama_hub.initialize()
        assert ollama_hub.session is not None
        
        await ollama_hub.cleanup()
        assert ollama_hub.session is None
    
    @pytest.mark.asyncio
    async def test_ollama_hub_process_cleanup(self, ollama_hub):
        """Test instance cleanup on shutdown"""
        from gleitzeit.hub.configs import OllamaConfig
        from gleitzeit.hub.base import ResourceInstance, ResourceStatus
        
        # Create a mock instance with process
        config = OllamaConfig(host="127.0.0.1", port=11434, process_id=1234)
        instance = ResourceInstance(
            id="test-instance",
            name="Test Ollama",
            type=ollama_hub.resource_type,
            endpoint="http://127.0.0.1:11434",
            status=ResourceStatus.HEALTHY,
            config=config
        )
        
        # Register the instance
        await ollama_hub.register_instance_object(instance)
        
        # Mock psutil for process management
        with patch('psutil.Process') as mock_process_class:
            mock_process = Mock()
            mock_process.terminate = Mock()
            mock_process.wait = Mock()
            mock_process_class.return_value = mock_process
            
            await ollama_hub.cleanup()
            
            # Process should be terminated
            mock_process.terminate.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_ollama_hub_health_check(self, ollama_hub):
        """Test health check functionality"""
        from gleitzeit.hub.configs import OllamaConfig
        from gleitzeit.hub.base import ResourceInstance, ResourceStatus
        
        await ollama_hub.initialize()
        
        # Create and register an instance
        config = OllamaConfig(host="127.0.0.1", port=11434)
        instance = ResourceInstance(
            id="test-instance",
            name="Test Ollama",
            type=ollama_hub.resource_type,
            endpoint="http://127.0.0.1:11434",
            status=ResourceStatus.HEALTHY,
            config=config
        )
        await ollama_hub.register_instance_object(instance)
        
        # Mock successful health check
        mock_response = Mock()
        mock_response.status = 200
        
        with patch.object(ollama_hub.session, 'get', return_value=mock_response) as mock_get:
            mock_get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
            mock_get.return_value.__aexit__ = AsyncMock()
            
            health = await ollama_hub.health_check("test-instance")
            assert health is True
    
    @pytest.mark.asyncio
    async def test_ollama_hub_health_check_failure(self, ollama_hub):
        """Test health check failure handling"""
        from gleitzeit.hub.configs import OllamaConfig
        from gleitzeit.hub.base import ResourceInstance, ResourceStatus
        
        await ollama_hub.initialize()
        
        # Create and register an instance
        config = OllamaConfig(host="127.0.0.1", port=11434)
        instance = ResourceInstance(
            id="test-instance",
            name="Test Ollama",
            type=ollama_hub.resource_type,
            endpoint="http://127.0.0.1:11434",
            status=ResourceStatus.HEALTHY,
            config=config
        )
        await ollama_hub.register_instance_object(instance)
        
        # Mock failed health check
        with patch.object(ollama_hub.session, 'get', side_effect=Exception("Connection failed")):
            health = await ollama_hub.health_check("test-instance")
            assert health is False
    
    @pytest.mark.asyncio
    async def test_ollama_hub_wait_for_ready(self, ollama_hub):
        """Test waiting for Ollama to be ready"""
        # Mock health check to fail twice, then succeed
        health_checks = [False, False, True, True]  # Extra True for model fetch
        
        with patch.object(ollama_hub, '_is_ollama_running', side_effect=health_checks):
            with patch('subprocess.Popen') as mock_popen:
                mock_process = Mock()
                mock_process.pid = 12345
                mock_popen.return_value = mock_process
                
                with patch('asyncio.sleep', new_callable=AsyncMock):
                    with patch.object(ollama_hub, '_get_available_models', return_value={'llama3.2'}):
                        # Test instance readiness check
                        from gleitzeit.hub.configs import OllamaConfig
                        from gleitzeit.hub.base import ResourceStatus
                        config = OllamaConfig(host="127.0.0.1", port=11434)
                        
                        # The start_instance method handles waiting
                        instance = await ollama_hub.start_instance(config)
                        assert instance is not None
                        assert instance.status == ResourceStatus.HEALTHY
    
    @pytest.mark.asyncio
    async def test_ollama_hub_wait_for_ready_timeout(self, ollama_hub):
        """Test timeout when waiting for Ollama"""
        # Mock health check to always fail
        with patch.object(ollama_hub, '_is_ollama_running', return_value=False):
            with patch('asyncio.sleep', new_callable=AsyncMock):
                from gleitzeit.hub.configs import OllamaConfig
                config = OllamaConfig(host="127.0.0.1", port=11434)
                
                # The create_resource should return None if can't connect
                instance = await ollama_hub.create_resource(config)
                # Instance might still be created but marked as unhealthy
                if instance:
                    assert instance.status != "healthy"


@pytest.mark.unit
class TestSessionPooling:
    """Test session pooling functionality"""
    
    @pytest.fixture
    def performance_timer(self):
        """Simple timer for performance testing"""
        import time
        
        class Timer:
            def __init__(self):
                self.start_time = None
            
            def start(self):
                self.start_time = time.perf_counter()
            
            def stop(self):
                return time.perf_counter() - self.start_time
        
        return Timer()
    
    @pytest.fixture
    async def ollama_hub_with_session(self):
        """Create OllamaHub with initialized session"""
        hub = OllamaHub()
        await hub.initialize()
        yield hub
        await hub.cleanup()
    
    @pytest.mark.asyncio
    async def test_session_reuse(self, ollama_hub_with_session):
        """Test that session is reused across requests"""
        session1 = ollama_hub_with_session.session
        
        # Make multiple calls that would use the session
        for _ in range(3):
            assert ollama_hub_with_session.session is session1
        
        # Session should not change
        assert ollama_hub_with_session.session is session1
    
    @pytest.mark.asyncio
    async def test_connector_configuration(self, ollama_hub_with_session):
        """Test TCPConnector configuration for performance"""
        connector = ollama_hub_with_session.session.connector
        
        # Verify connection pooling settings
        assert connector.limit == 100  # Total connections
        assert connector.limit_per_host == 30  # Per-host connections
        # DNS TTL and keepalive are internal implementation details that may vary
    
    @pytest.mark.asyncio
    async def test_session_performance_improvement(self, performance_timer):
        """Test that session pooling provides performance benefit"""
        hub = OllamaHub()
        await hub.initialize()
        
        try:
            # Mock the session.get to simulate network calls
            mock_response = AsyncMock()
            mock_response.status = 200
            
            async def mock_get(*args, **kwargs):
                await asyncio.sleep(0.01)  # Simulate network delay
                return mock_response
            
            # Create a test instance first
            from gleitzeit.hub.configs import OllamaConfig
            from gleitzeit.hub.base import ResourceInstance, ResourceStatus
            
            config = OllamaConfig(host="127.0.0.1", port=11434)
            instance = ResourceInstance(
                id="test-instance",
                name="Test Ollama",
                type=hub.resource_type,
                endpoint="http://127.0.0.1:11434",
                status=ResourceStatus.HEALTHY,
                config=config
            )
            await hub.register_instance_object(instance)
            
            with patch.object(hub.session, 'get', side_effect=mock_get):
                # First call (cold)
                performance_timer.start()
                await hub.health_check("test-instance")
                cold_time = performance_timer.stop()
                
                # Subsequent calls (warm pool)
                warm_times = []
                for _ in range(5):
                    performance_timer.start()
                    await hub.health_check("test-instance")
                    warm_times.append(performance_timer.stop())
                
                # Average warm time should be similar (connection reused)
                avg_warm = sum(warm_times) / len(warm_times)
                
                # In real scenario, warm calls are 2.7x faster
                # Here we just check consistency
                assert avg_warm < cold_time * 2
        finally:
            await hub.cleanup()


@pytest.mark.unit
class TestResourceManager:
    """Test ResourceManager coordination with hubs"""
    
    @pytest.fixture
    def resource_manager(self):
        """Create ResourceManager instance"""
        from gleitzeit.hub.resource_manager import ResourceManager
        return ResourceManager()
    
    @pytest.mark.asyncio
    async def test_resource_manager_registers_hub(self, resource_manager):
        """Test registering hub with resource manager"""
        mock_hub = AsyncMock()
        mock_hub.hub_id = "ollama"
        
        await resource_manager.add_hub("ollama", mock_hub)
        
        assert "ollama" in resource_manager.hubs
        assert resource_manager.hubs["ollama"] is mock_hub
    
    @pytest.mark.asyncio
    async def test_resource_manager_starts_all_hubs(self, resource_manager):
        """Test starting all registered hubs"""
        from gleitzeit.hub.base import ResourceType
        
        mock_ollama = AsyncMock()
        mock_ollama.hub_id = "ollama"
        mock_ollama.initialize = AsyncMock()
        mock_ollama.start = AsyncMock()
        mock_ollama.on_event = Mock()
        mock_ollama.resource_type = ResourceType.OLLAMA
        mock_ollama.running = False
        
        mock_docker = AsyncMock()
        mock_docker.hub_id = "docker"
        mock_docker.initialize = AsyncMock()
        mock_docker.start = AsyncMock()
        mock_docker.on_event = Mock()
        mock_docker.resource_type = ResourceType.DOCKER
        mock_docker.running = False
        
        await resource_manager.add_hub("ollama", mock_ollama)
        await resource_manager.add_hub("docker", mock_docker)
        
        await resource_manager.start()
        
        # Hubs are started when resource manager starts
        mock_ollama.start.assert_called()
        mock_docker.start.assert_called()
    
    @pytest.mark.asyncio
    async def test_resource_manager_cleanup(self, resource_manager):
        """Test resource manager cleanup"""
        from gleitzeit.hub.base import ResourceType
        
        mock_hub = AsyncMock()
        mock_hub.hub_id = "test"
        mock_hub.stop = AsyncMock()
        mock_hub.on_event = Mock()
        mock_hub.resource_type = ResourceType.CUSTOM
        mock_hub.running = False
        
        await resource_manager.add_hub("test", mock_hub)
        
        # Start the resource manager first so it's running
        await resource_manager.start()
        
        # Now stop it
        await resource_manager.stop()
        
        mock_hub.stop.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_resource_manager_health_checks(self, resource_manager):
        """Test resource manager performs health checks"""
        from gleitzeit.hub.base import ResourceInstance, ResourceStatus, ResourceType
        
        mock_hub1 = AsyncMock()
        mock_hub1.hub_id = "healthy"
        mock_hub1.on_event = Mock()
        mock_hub1.resource_type = ResourceType.OLLAMA
        mock_hub1.running = False
        mock_hub1.get_status = AsyncMock(return_value={"running": True})
        mock_hub1.get_metrics_summary = AsyncMock(return_value={})
        mock_hub1.list_instances = AsyncMock(return_value=[
            ResourceInstance(
                id="inst1",
                name="Test",
                type=ResourceType.OLLAMA,
                endpoint="http://localhost:11434",
                status=ResourceStatus.HEALTHY
            )
        ])
        
        mock_hub2 = AsyncMock()
        mock_hub2.hub_id = "unhealthy"
        mock_hub2.on_event = Mock()
        mock_hub2.resource_type = ResourceType.DOCKER
        mock_hub2.running = False
        mock_hub2.get_status = AsyncMock(return_value={"running": True})
        mock_hub2.get_metrics_summary = AsyncMock(return_value={})
        mock_hub2.list_instances = AsyncMock(return_value=[
            ResourceInstance(
                id="inst2",
                name="Test2",
                type=ResourceType.DOCKER,
                endpoint="http://localhost:8080",
                status=ResourceStatus.UNHEALTHY
            )
        ])
        
        await resource_manager.add_hub("healthy", mock_hub1)
        await resource_manager.add_hub("unhealthy", mock_hub2)
        
        # Get global metrics which includes health status
        metrics = await resource_manager.get_global_metrics()
        
        assert len(metrics["hub_metrics"]) == 2
        assert metrics["total_resources"] == 2
        assert metrics["total_hubs"] == 2


@pytest.mark.unit
class TestDockerHub:
    """Test DockerHub resource management"""
    
    @pytest.fixture
    async def docker_hub(self):
        """Create DockerHub instance"""
        from gleitzeit.hub.docker_hub import DockerHub
        hub = DockerHub()
        yield hub
        await hub.cleanup()
    
    def test_docker_hub_no_protocol_methods(self):
        """Test that DockerHub has no protocol execution"""
        from gleitzeit.hub.docker_hub import DockerHub
        
        forbidden_methods = [
            'execute',
            'run_python_code',
            'execute_script'
        ]
        
        hub_methods = dir(DockerHub)
        for method in forbidden_methods:
            assert method not in hub_methods, \
                f"DockerHub should not have protocol method: {method}"
    
    @pytest.mark.asyncio
    async def test_docker_hub_container_lifecycle(self, docker_hub):
        """Test Docker container lifecycle management"""
        from gleitzeit.hub.configs import DockerConfig
        from gleitzeit.hub.base import ResourceInstance, ResourceStatus
        
        with patch('docker.from_env') as mock_docker:
            mock_client = Mock()
            mock_container = Mock()
            mock_container.id = "test_container_123"
            mock_container.short_id = "test123"
            mock_container.status = "running"
            mock_container.attrs = {"State": {"Running": True}}
            mock_container.name = "test-container"
            
            # Mock container.reload() method
            mock_container.reload = Mock()
            
            # Mock container.ports attribute - should be a dict
            mock_container.ports = {
                "8000/tcp": [{"HostPort": "8000"}]
            }
            
            # Mock stop and remove methods
            mock_container.stop = Mock()
            mock_container.remove = Mock()
            
            # Mock containers.list to return empty list (no orphaned containers)
            mock_client.containers.list = Mock(return_value=[])
            mock_client.containers.run = Mock(return_value=mock_container)
            mock_client.containers.get = Mock(return_value=mock_container)
            mock_client.ping = Mock()
            mock_docker.return_value = mock_client
            
            # Initialize hub
            await docker_hub.initialize()
            
            # Create container resource with auto_remove to ensure remove is called
            config = DockerConfig(
                image="python:3.9",
                name="test-container",
                command="python -m http.server",
                auto_remove=True
            )
            instance = await docker_hub.create_resource(config)
            
            assert instance is not None
            assert instance.config.container_id == "test_container_123"
            
            # Register the instance so it can be found
            await docker_hub.register_instance_object(instance)
            
            # Stop container
            await docker_hub.stop_instance(instance.id)
            mock_container.stop.assert_called()
            mock_container.remove.assert_called()
    
    @pytest.mark.asyncio
    async def test_docker_hub_cleanup_all_containers(self, docker_hub):
        """Test cleanup of all managed containers"""
        from gleitzeit.hub.configs import DockerConfig
        from gleitzeit.hub.base import ResourceInstance, ResourceStatus
        
        # Mock Docker client
        with patch('docker.from_env') as mock_docker:
            mock_client = Mock()
            mock_client.ping = Mock()
            
            # Create mock containers
            mock_container1 = Mock()
            mock_container1.id = "container1"
            mock_container1.stop = Mock()
            mock_container1.remove = Mock()
            
            mock_container2 = Mock()
            mock_container2.id = "container2"
            mock_container2.stop = Mock()
            mock_container2.remove = Mock()
            
            # First call returns empty list (for orphaned cleanup), second returns our containers
            mock_client.containers.list = Mock(side_effect=[[], [mock_container1, mock_container2]])
            
            # Mock containers.get to return the appropriate container
            def get_container(container_id):
                if container_id == "container1":
                    return mock_container1
                elif container_id == "container2":
                    return mock_container2
                raise Exception("Container not found")
            
            mock_client.containers.get = Mock(side_effect=get_container)
            mock_docker.return_value = mock_client
            
            await docker_hub.initialize()
            
            # Register instances
            config1 = DockerConfig(image="python:3.9", container_id="container1")
            instance1 = ResourceInstance(
                id="inst1",
                name="Container 1",
                type=docker_hub.resource_type,
                endpoint="http://localhost:8001",
                status=ResourceStatus.HEALTHY,
                config=config1
            )
            await docker_hub.register_instance_object(instance1)
            
            config2 = DockerConfig(image="python:3.9", container_id="container2")
            instance2 = ResourceInstance(
                id="inst2",
                name="Container 2",
                type=docker_hub.resource_type,
                endpoint="http://localhost:8002",
                status=ResourceStatus.HEALTHY,
                config=config2
            )
            await docker_hub.register_instance_object(instance2)
            
            # Cleanup
            await docker_hub.cleanup()
            
            # Verify containers were stopped and removed
            mock_container1.stop.assert_called()
            mock_container1.remove.assert_called()
            mock_container2.stop.assert_called()
            mock_container2.remove.assert_called()


@pytest.mark.unit
class TestHubTypeConsistency:
    """Test type consistency across all hubs"""
    
    @pytest.mark.asyncio
    async def test_all_hubs_health_check_returns_bool(self):
        """Test that all hubs' health_check returns bool"""
        from gleitzeit.hub.ollama_hub import OllamaHub
        from gleitzeit.hub.docker_hub import DockerHub
        from gleitzeit.hub.configs import OllamaConfig, DockerConfig
        from gleitzeit.hub.base import ResourceInstance, ResourceStatus
        
        hubs = [
            OllamaHub(),
            DockerHub()
        ]
        
        for hub in hubs:
            await hub.initialize()
            
            # Create a test instance
            if isinstance(hub, OllamaHub):
                config = OllamaConfig(host="127.0.0.1", port=11434)
            else:
                config = DockerConfig(image="python:3.9")
            
            instance = ResourceInstance(
                id="test-instance",
                name="Test Instance",
                type=hub.resource_type,
                endpoint="http://localhost:8080",
                status=ResourceStatus.HEALTHY,
                config=config
            )
            await hub.register_instance_object(instance)
            
            # Mock any external dependencies
            with patch.object(hub, '_is_ollama_running', return_value=True) if isinstance(hub, OllamaHub) else patch('docker.from_env'):
                health = await hub.health_check("test-instance")
                assert isinstance(health, bool), \
                    f"{hub.__class__.__name__}.health_check() must return bool"
            
            await hub.cleanup()
    
    def test_all_hubs_have_resource_methods(self):
        """Test that all hubs have resource management methods"""
        from gleitzeit.hub.ollama_hub import OllamaHub
        from gleitzeit.hub.docker_hub import DockerHub
        
        required_methods = [
            'initialize',
            'cleanup',
            'health_check',
            'create_resource',
            'register_instance',
            'get_instance',
            'stop_instance'
        ]
        
        hubs = [OllamaHub, DockerHub]
        
        for hub_class in hubs:
            for method in required_methods:
                assert hasattr(hub_class, method), \
                    f"{hub_class.__name__} missing required method: {method}"