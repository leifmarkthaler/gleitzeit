"""
Pytest configuration for persistence tests

Provides common fixtures and test configuration.
"""

import pytest
import asyncio
import logging
import os
from typing import Generator

# Configure logging for tests
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Suppress some verbose loggers during tests
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
logging.getLogger('aioredis').setLevel(logging.WARNING)


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def reset_environment():
    """Reset environment variables for each test"""
    # Store original environment
    original_env = os.environ.copy()
    
    yield
    
    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


@pytest.fixture
def redis_available():
    """Check if Redis is available for testing"""
    import socket
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('localhost', 6379))
        sock.close()
        
        if result != 0:
            pytest.skip("Redis not available on localhost:6379")
    except Exception as e:
        pytest.skip(f"Cannot check Redis availability: {e}")


# Mark slow tests
def pytest_configure(config):
    """Configure custom pytest markers"""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "redis: marks tests that require Redis"
    )
    config.addinivalue_line(
        "markers", "integration: marks integration tests"
    )


# Test collection hooks
def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers"""
    for item in items:
        # Mark Redis tests
        if 'redis' in item.nodeid.lower():
            item.add_marker(pytest.mark.redis)
        
        # Mark integration tests
        if 'integration' in item.nodeid.lower():
            item.add_marker(pytest.mark.integration)
        
        # Mark performance tests as slow
        if 'performance' in item.nodeid.lower():
            item.add_marker(pytest.mark.slow)