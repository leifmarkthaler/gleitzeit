"""
Test SystemManager core functionality.
"""

import pytest
import asyncio
from datetime import datetime

from gleitzeit.system.system_manager import SystemManager
from gleitzeit.system.models import SystemConfig, DeploymentMode
from gleitzeit.persistence.unified_persistence import UnifiedInMemoryAdapter
from gleitzeit.events.stateless_bus import StatelessEventBus


@pytest.mark.asyncio
async def test_system_manager_initialization():
    """Test SystemManager initialization in development mode."""
    # Create in-memory persistence for development
    persistence = UnifiedInMemoryAdapter()
    await persistence.initialize()
    
    # Create development config
    config = SystemConfig(
        deployment_mode=DeploymentMode.DEVELOPMENT,
        environment="test"
    )
    
    # Create SystemManager
    manager = SystemManager(
        config=config,
        persistence=persistence,
        event_bus=StatelessEventBus(persistence=persistence)
    )
    
    # Initialize
    await manager.initialize()
    
    # Verify initialization
    assert manager._initialized is True
    assert manager.instance_id is not None
    assert manager.component_registry is not None
    assert manager.service_registry is not None
    
    # In development mode, no leader election
    assert manager.leader_election is None
    
    # Cleanup
    await manager.shutdown()


@pytest.mark.asyncio
async def test_component_registration():
    """Test component registration in distributed registry."""
    persistence = UnifiedInMemoryAdapter()
    await persistence.initialize()
    
    config = SystemConfig(
        deployment_mode=DeploymentMode.DEVELOPMENT,
        environment="test"
    )
    
    manager = SystemManager(
        config=config,
        persistence=persistence,
        instance_id="test_manager"
    )
    
    await manager.initialize()
    
    # Register a test provider with proper init
    class TestProvider:
        def __init__(self, provider_id=None, protocol_id=None, **kwargs):
            self.provider_id = provider_id
            self.protocol_id = protocol_id
            self.config = kwargs
        
        async def initialize(self):
            pass
        
        def get_supported_methods(self):
            return ["test_method"]
    
    success = await manager.register_provider(
        provider_class=TestProvider,
        provider_id="test_provider",
        protocol_id="test/v1",
        config={"test": True}
    )
    
    assert success is True
    
    # Verify it's in the registry
    components = await manager.component_registry.list_components(
        component_type="provider"
    )
    
    assert len(components) == 1
    assert components[0].component_id == "test_provider"
    assert components[0].instance_id == "test_manager"
    
    # Cleanup
    await manager.shutdown()


@pytest.mark.asyncio
async def test_system_status():
    """Test getting system status."""
    persistence = UnifiedInMemoryAdapter()
    await persistence.initialize()
    
    config = SystemConfig(
        deployment_mode=DeploymentMode.DEVELOPMENT,
        environment="test"
    )
    
    manager = SystemManager(
        config=config,
        persistence=persistence
    )
    
    await manager.initialize()
    await manager.start_system()
    
    # Get status
    status = await manager.get_system_status()
    
    assert status["status"] == "running"
    assert status["deployment_mode"] == "development"
    assert status["environment"] == "test"
    assert "uptime_seconds" in status
    assert "health" in status
    assert "services" in status
    assert "resources" in status
    
    # Cleanup
    await manager.shutdown_system()
    await manager.shutdown()


@pytest.mark.asyncio
async def test_production_mode_requires_distributed_backend():
    """Test that production mode rejects in-memory persistence."""
    persistence = UnifiedInMemoryAdapter()
    await persistence.initialize()
    
    config = SystemConfig(
        deployment_mode=DeploymentMode.PRODUCTION,
        environment="production"
    )
    
    manager = SystemManager(
        config=config,
        persistence=persistence
    )
    
    # Should raise error during initialization
    with pytest.raises(Exception) as exc_info:
        await manager.initialize()
    
    assert "distributed persistence backend" in str(exc_info.value)


@pytest.mark.asyncio
async def test_heartbeat_mechanism():
    """Test component heartbeat updates."""
    persistence = UnifiedInMemoryAdapter()
    await persistence.initialize()
    
    config = SystemConfig(
        deployment_mode=DeploymentMode.DEVELOPMENT,
        environment="test"
    )
    
    manager = SystemManager(
        config=config,
        persistence=persistence
    )
    
    await manager.initialize()
    
    # Register a component
    await manager.register_hub(
        hub_id="test_hub",
        hub_instance=type("TestHub", (), {"resource_type": "test"})()
    )
    
    # Update heartbeats
    count = await manager.component_registry.update_all_heartbeats()
    assert count == 1
    
    # Get component and check heartbeat
    component = await manager.component_registry.get_component("test_hub")
    assert component is not None
    assert component.last_heartbeat is not None
    
    # Cleanup
    await manager.shutdown()