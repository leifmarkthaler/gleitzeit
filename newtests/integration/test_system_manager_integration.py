"""
Integration tests for SystemManager with API and all managed resources.

Tests that SystemManager properly manages:
- ProviderHub HTTP server
- SharedClientPool for APIs
- Worker processes
- All distributed resources
"""

import asyncio
import pytest
import aiohttp
import logging
import socket
from typing import Optional

from gleitzeit.system.system_manager import SystemManager, SystemConfig
from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.persistence.factory import PersistenceFactory

logger = logging.getLogger(__name__)


def get_free_port():
    """Get a free port for testing."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


@pytest.mark.asyncio
async def test_system_manager_starts_provider_hub():
    """Test that SystemManager starts the ProviderHub HTTP server."""
    port = get_free_port()
    config = SystemConfig(
        num_workers=0, 
        environment='test',
        provider_hub_port=port  # Use dynamic port
    )
    manager = SystemManager(config=config)
    
    try:
        # Initialize and start SystemManager
        await manager.initialize()
        await manager.start_system()
        
        # Give it a moment to start the HTTP server
        await asyncio.sleep(1)
        
        # Check if ProviderHub is accessible
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://localhost:{port}/health") as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["status"] == "healthy"
                
    finally:
        await manager.shutdown_system()


@pytest.mark.asyncio
async def test_system_manager_shared_client_pool():
    """Test that SystemManager initializes SharedClientPool for APIs."""
    config = SystemConfig(num_workers=0, environment='test')
    manager = SystemManager(config=config)
    
    try:
        # Initialize and start SystemManager
        await manager.initialize()
        await manager.start_system()
        
        # Verify SharedClientPool was initialized
        assert manager.shared_client_pool is not None
        assert manager.shared_client_pool._initialized
        
        # Test acquiring a client from the pool
        client = await manager.shared_client_pool.acquire()
        assert client is not None
        assert client.is_initialized()
        
        # Release the client back to pool
        await manager.shared_client_pool.release(client)
        
    finally:
        await manager.shutdown_system()


@pytest.mark.asyncio
async def test_api_uses_shared_pool():
    """Test that API can connect to SystemManager's SharedClientPool."""
    config = SystemConfig(num_workers=0, environment='test')
    manager = SystemManager(config=config)
    
    try:
        # Initialize and start SystemManager first
        await manager.initialize()
        await manager.start_system()
        await asyncio.sleep(1)
        
        # Now import and start API (after SystemManager is running)
        from gleitzeit.api.main import create_modular_app
        from gleitzeit.api.dependencies import get_shared_client_pool
        
        # Get the shared pool (should connect to SystemManager's pool)
        pool = await get_shared_client_pool()
        assert pool is not None
        
        # Acquire a client through the shared pool
        client = await pool.acquire()
        assert client is not None
        assert client.is_initialized()
        
        await pool.release(client)
        
    finally:
        await manager.shutdown_system()


@pytest.mark.asyncio
async def test_client_connects_to_provider_hub():
    """Test that clients can connect to the ProviderHub started by SystemManager."""
    port = get_free_port()
    config = SystemConfig(
        num_workers=0, 
        environment='test',
        provider_hub_port=port
    )
    manager = SystemManager(config=config)
    
    try:
        # Initialize and start SystemManager (which starts ProviderHub)
        await manager.initialize()
        await manager.start_system()
        await asyncio.sleep(1)
        
        # Set environment variable for client to find the hub on custom port
        import os
        os.environ['GLEITZEIT_HUB_URL'] = f'http://localhost:{port}'
        
        # Create a client that will try to connect to ProviderHub
        client = GleitzeitClient(mode=ClientMode.NATIVE)
        await client.initialize()
        
        # Check if client's hub connector is connected
        if hasattr(client, '_adapter') and hasattr(client._adapter, 'execution_engine'):
            engine = client._adapter.execution_engine
            if hasattr(engine, 'registry') and hasattr(engine.registry, 'hub_connector'):
                hub = engine.registry.hub_connector
                if hub:
                    # Try to get stats from hub
                    stats = await hub.get_stats()
                    assert stats is not None
        
        await client.shutdown()
        
    finally:
        # Clean up environment variable
        os.environ.pop('GLEITZEIT_HUB_URL', None)
        await manager.shutdown_system()


@pytest.mark.asyncio
async def test_full_integration_workflow():
    """Test a complete workflow through the integrated system."""
    config = SystemConfig(num_workers=1, environment='test')  # Start with one worker
    manager = SystemManager(config=config)
    
    try:
        # Initialize and start SystemManager with all components
        await manager.initialize()
        await manager.start_system()
        await asyncio.sleep(2)  # Give everything time to start
        
        # Create a client
        client = GleitzeitClient(mode=ClientMode.NATIVE)
        await client.initialize()
        
        # Submit a simple workflow
        workflow_def = {
            "name": "test_integration",
            "tasks": [
                {
                    "id": "task1",
                    "type": "python",
                    "config": {
                        "code": "result = 'Hello from integrated system'"
                    }
                }
            ]
        }
        
        workflow_id = await client.submit_workflow(workflow_def)
        assert workflow_id is not None
        
        # Wait for completion
        max_wait = 10
        for _ in range(max_wait):
            status = await client.get_workflow_status(workflow_id)
            if status and status.get("status") == "completed":
                break
            await asyncio.sleep(1)
        
        # Check results
        status = await client.get_workflow_status(workflow_id)
        assert status["status"] == "completed"
        
        await client.shutdown()
        
    finally:
        await manager.shutdown_system()


@pytest.mark.asyncio
async def test_distributed_client_pool_sharing():
    """Test that multiple API instances share the same client pool."""
    config = SystemConfig(num_workers=0, environment='test')
    manager = SystemManager(config=config)
    
    try:
        # Initialize and start SystemManager
        await manager.initialize()
        await manager.start_system()
        await asyncio.sleep(1)
        
        # Create two "API instances" (simulated by getting pool twice)
        from gleitzeit.api.shared_dependencies import SharedClientPool
        persistence = await PersistenceFactory.create()
        
        # First API instance
        pool1 = SharedClientPool(
            persistence=persistence,
            instance_id="api_instance_1",
            max_size=20,
            mode=ClientMode.NATIVE
        )
        await pool1.initialize()
        
        # Second API instance
        pool2 = SharedClientPool(
            persistence=persistence,
            instance_id="api_instance_2",
            max_size=20,
            mode=ClientMode.NATIVE
        )
        await pool2.initialize()
        
        # Both should see the same total count in persistence
        total_key = pool1._key("total_count")
        
        # Acquire clients from both pools
        client1 = await pool1.acquire()
        client2 = await pool2.acquire()
        
        # Check they're tracked in the shared state
        count = await persistence.get(total_key)
        assert int(count) >= 2  # At least 2 clients created
        
        # Release clients
        await pool1.release(client1)
        await pool2.release(client2)
        
        # Cleanup
        await pool1.shutdown()
        await pool2.shutdown()
        
    finally:
        await manager.shutdown_system()


@pytest.mark.asyncio
async def test_system_manager_graceful_shutdown():
    """Test that SystemManager properly shuts down all managed resources."""
    port = get_free_port()
    config = SystemConfig(
        num_workers=1, 
        environment='test',
        provider_hub_port=port
    )
    manager = SystemManager(config=config)
    
    try:
        # Initialize and start everything
        await manager.initialize()
        await manager.start_system()
        await asyncio.sleep(2)
        
        # Verify components are running
        assert manager.provider_hub is not None
        assert manager.shared_client_pool is not None
        assert len(manager.workers) == 1
        
        # Stop SystemManager
        await manager.shutdown_system()
        
        # Verify everything is cleaned up
        assert manager.provider_hub is None
        assert manager.shared_client_pool is None
        assert len(manager.workers) == 0
        
        # Verify ProviderHub is no longer accessible
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=1)
            ) as session:
                async with session.get(f"http://localhost:{port}/health") as resp:
                    # Should fail to connect
                    assert False, "ProviderHub should not be accessible after shutdown"
        except (aiohttp.ClientError, asyncio.TimeoutError):
            # Expected - hub is down
            pass
            
    finally:
        # Make sure it's stopped even if test fails
        if manager._running:
            await manager.shutdown_system()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(test_full_integration_workflow())