"""
Test distributed SystemManager features.

Note: These tests require Redis to be running for full functionality.
They will be skipped if Redis is not available.
"""

import pytest
import asyncio
from datetime import datetime

from gleitzeit.system.system_manager import SystemManager
from gleitzeit.system.models import SystemConfig, DeploymentMode
from gleitzeit.persistence.factory import PersistenceFactory
from gleitzeit.persistence.unified_persistence import UnifiedInMemoryAdapter
from gleitzeit.events.stateless_bus import StatelessEventBus


def check_redis_available():
    """Check if Redis is available for testing."""
    import os
    # Check if Redis URL is configured
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    # Try to import redis
    try:
        import redis
        # Try to connect
        client = redis.from_url(redis_url)
        client.ping()
        return True
    except:
        return False


pytest_redis_available = check_redis_available()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not pytest_redis_available,
    reason="Redis not available for distributed tests"
)
async def test_leader_election_with_redis():
    """Test leader election with Redis backend."""
    # Create Redis persistence
    persistence = await PersistenceFactory.create()
    
    # Verify it's Redis
    assert "Redis" in type(persistence).__name__
    assert persistence.supports_atomic_operations()
    
    # Create production config
    config = SystemConfig(
        deployment_mode=DeploymentMode.PRODUCTION,
        environment="production"
    )
    
    # Create multiple managers
    managers = []
    for i in range(3):
        manager = SystemManager(
            config=config,
            persistence=persistence,
            event_bus=StatelessEventBus(persistence=persistence),
            instance_id=f"manager_{i}"
        )
        await manager.initialize()
        managers.append(manager)
    
    # Wait for leader election (election_check_interval is 1 second)
    await asyncio.sleep(2)
    
    # Check that exactly one is leader
    leaders = [m for m in managers if m.leader_election and m.leader_election.is_leader()]
    assert len(leaders) == 1, f"Expected 1 leader, got {len(leaders)}"
    
    # Cleanup
    for manager in managers:
        await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not pytest_redis_available,
    reason="Redis not available for distributed tests"
)
async def test_distributed_component_registry():
    """Test that components are visible across instances."""
    persistence = await PersistenceFactory.create()
    
    config = SystemConfig(
        deployment_mode=DeploymentMode.PRODUCTION,
        environment="production"
    )
    
    # Create two managers
    manager1 = SystemManager(
        config=config,
        persistence=persistence,
        event_bus=StatelessEventBus(persistence=persistence),
        instance_id="manager_1"
    )
    
    manager2 = SystemManager(
        config=config,
        persistence=persistence,
        event_bus=StatelessEventBus(persistence=persistence),
        instance_id="manager_2"
    )
    
    await manager1.initialize()
    await manager2.initialize()
    
    # Create a simple test provider class
    class TestProvider:
        def __init__(self, provider_id=None, protocol_id=None, **kwargs):
            self.provider_id = provider_id
            self.protocol_id = protocol_id or "test/v1"
        
        async def initialize(self):
            """Initialize the provider."""
            pass
        
        def get_supported_methods(self):
            """Return supported methods."""
            return ["test_method"]
    
    # Register component on manager1
    result = await manager1.register_provider(
        provider_class=TestProvider,
        provider_id="shared_provider",
        protocol_id="test/v1"
    )
    print(f"Registration result: {result}")
    
    # Check if manager1 can see its own component
    components_m1 = await manager1.component_registry.list_components()
    print(f"Components on manager1: {[c.component_id for c in components_m1]}")
    
    # Check visibility from manager2
    components = await manager2.component_registry.list_components()
    print(f"Components found: {[c.component_id for c in components]}")
    provider_found = any(c.component_id == "shared_provider" for c in components)
    assert provider_found, f"Component registered on manager1 should be visible on manager2. Found: {[c.component_id for c in components]}"
    
    # Cleanup
    await manager1.shutdown()
    await manager2.shutdown()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not pytest_redis_available,
    reason="Redis not available for distributed tests"
)
async def test_leader_failover():
    """Test leader failover when current leader stops."""
    persistence = await PersistenceFactory.create()
    
    config = SystemConfig(
        deployment_mode=DeploymentMode.PRODUCTION,
        environment="production"
    )
    
    # Create managers
    managers = []
    for i in range(3):
        manager = SystemManager(
            config=config,
            persistence=persistence,
            event_bus=StatelessEventBus(persistence=persistence),
            instance_id=f"failover_{i}"
        )
        await manager.initialize()
        managers.append(manager)
    
    # Wait for initial election
    await asyncio.sleep(2)
    
    # Find current leader
    current_leader = None
    for manager in managers:
        if manager.leader_election and manager.leader_election.is_leader():
            current_leader = manager
            break
    
    assert current_leader is not None, "Should have a leader"
    leader_id = current_leader.instance_id
    
    # Stop current leader
    await current_leader.leader_election.stop()
    
    # Wait for new election (election_check_interval is 1 second)
    await asyncio.sleep(3)  # A bit longer for failover detection + election
    
    # Check for new leader
    new_leaders = []
    for manager in managers:
        if manager != current_leader and manager.leader_election and manager.leader_election.is_leader():
            new_leaders.append(manager)
    
    assert len(new_leaders) == 1, f"Expected 1 new leader after failover, got {len(new_leaders)}"
    assert new_leaders[0].instance_id != leader_id, "New leader should be different instance"
    
    # Cleanup
    for manager in managers:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_development_mode_single_instance():
    """Test that development mode works without distributed features."""
    persistence = UnifiedInMemoryAdapter()
    await persistence.initialize()
    
    config = SystemConfig(
        deployment_mode=DeploymentMode.DEVELOPMENT,
        environment="development"
    )
    
    manager = SystemManager(
        config=config,
        persistence=persistence
    )
    
    await manager.initialize()
    
    # No leader election in development mode
    assert manager.leader_election is None
    
    # Can still use all features
    await manager.start_system()
    
    # Register components
    await manager.register_hub(
        hub_id="dev_hub",
        hub_instance=type("DevHub", (), {"resource_type": "dev"})()
    )
    
    # Get status
    status = await manager.get_system_status()
    assert status["status"] == "running"
    assert status["deployment_mode"] == "development"
    
    # Cleanup
    await manager.shutdown_system()
    await manager.shutdown()