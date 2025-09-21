#!/usr/bin/env python3
"""
Test unified authentication through SystemManager and AuthManager.
Verifies that API, Client, and CLI all use the same auth system.
"""

import asyncio
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_native_mode_auth():
    """Test that Native mode uses AuthManager properly."""
    logger.info("=== Testing Native Mode Authentication ===")
    
    from gleitzeit.client import GleitzeitClient, ClientMode
    from gleitzeit.system.system_manager import SystemManager
    
    # Get or create SystemManager
    system_manager = await SystemManager.get_or_create()
    
    # Create Native mode client (no service token!)
    client = GleitzeitClient(
        mode=ClientMode.NATIVE,
        system_manager=system_manager
    )
    
    await client.initialize()
    
    # In basic mode, should automatically get basic user
    if system_manager.auth_manager.auth_mode == "basic":
        logger.info("Testing basic mode authentication...")
        
        # Should be able to access without explicit login
        user = await client.get_current_user()
        logger.info(f"Current user: {user.get('username')} (id: {user.get('id')})")
        
        # Verify it's the basic user
        if user.get('id') == 'basic-user':
            logger.info("✓ Native mode correctly uses basic user")
        else:
            logger.error(f"✗ Expected basic-user, got {user.get('id')}")
    
    await client.shutdown()


async def test_api_mode_auth():
    """Test that API mode uses AuthManager through API routes."""
    logger.info("\n=== Testing API Mode Authentication ===")
    
    from gleitzeit.client import GleitzeitClient, ClientMode
    
    # Create API mode client
    client = GleitzeitClient(
        mode=ClientMode.API,
        api_host="localhost",
        api_port=8000
    )
    
    try:
        await client.initialize()
        
        # Get current user (should work in basic mode)
        user = await client.get_current_user()
        logger.info(f"Current user via API: {user.get('username')} (id: {user.get('id')})")
        
        # Try login (if in advanced mode)
        try:
            result = await client.login("test", "test")
            if result.get('success'):
                logger.info("✓ Login successful via API")
            else:
                logger.info("Login not available (basic mode)")
        except Exception as e:
            logger.info(f"Login test skipped: {e}")
        
    except Exception as e:
        logger.warning(f"API mode test skipped (server not running): {e}")
    finally:
        await client.shutdown()


async def test_auth_manager_consistency():
    """Test that AuthManager provides consistent behavior."""
    logger.info("\n=== Testing AuthManager Consistency ===")
    
    from gleitzeit.persistence.factory import PersistenceFactory
    from gleitzeit.auth.auth_manager import AuthManager
    from gleitzeit.events.stateless_bus import StatelessEventBus
    
    # Create AuthManager
    persistence = await PersistenceFactory.create()
    event_bus = StatelessEventBus(persistence=persistence)
    auth_manager = AuthManager(persistence, event_bus)
    
    logger.info(f"Auth mode: {auth_manager.auth_mode}")
    
    # Test unauthenticated user
    unauth_user = auth_manager.get_unauthenticated_user()
    logger.info(f"Unauthenticated user: {unauth_user.get('username')}")
    
    if auth_manager.auth_mode == "basic":
        # Should return basic user with permissions
        if unauth_user.get('id') == 'basic-user':
            logger.info("✓ Basic mode returns basic user for unauthenticated")
        if len(unauth_user.get('permissions', [])) > 0:
            logger.info(f"✓ Basic user has {len(unauth_user['permissions'])} permissions")
    else:
        # Should return user with no permissions
        if unauth_user.get('id') == 'unauthenticated':
            logger.info("✓ Advanced mode returns unauthenticated user")
        if len(unauth_user.get('permissions', [])) == 0:
            logger.info("✓ Unauthenticated user has no permissions")
    
    # Test basic session creation
    if auth_manager.auth_mode == "basic":
        session_id, user = await auth_manager.get_or_create_basic_session()
        logger.info(f"Basic session created: {session_id}")
        
        # Verify session exists
        session = await auth_manager._get_session(session_id)
        if session:
            logger.info("✓ Basic session stored in persistence")
        else:
            logger.error("✗ Basic session not found")


async def test_no_service_token():
    """Verify service token pattern is completely removed."""
    logger.info("\n=== Verifying Service Token Removal ===")
    
    from gleitzeit.client import GleitzeitClient
    
    # Check that _SERVICE_TOKEN is gone
    if hasattr(GleitzeitClient, '_SERVICE_TOKEN'):
        logger.error("✗ _SERVICE_TOKEN still exists on GleitzeitClient!")
    else:
        logger.info("✓ _SERVICE_TOKEN removed from GleitzeitClient")
    
    # Check that set_service_token is gone
    if hasattr(GleitzeitClient, 'set_service_token'):
        logger.error("✗ set_service_token method still exists!")
    else:
        logger.info("✓ set_service_token method removed")
    
    # Try to create Native client without service_token
    try:
        from gleitzeit.system.system_manager import SystemManager
        system_manager = await SystemManager.get_or_create()
        
        # This should work now (no service_token needed)
        client = GleitzeitClient(
            mode='native',
            system_manager=system_manager
        )
        await client.initialize()
        logger.info("✓ Native mode works without service_token")
        await client.shutdown()
    except Exception as e:
        if "service_token" in str(e):
            logger.error(f"✗ Still requires service_token: {e}")
        else:
            logger.warning(f"Other error: {e}")


async def main():
    """Run all authentication tests."""
    logger.info("Starting Unified Authentication Tests")
    logger.info("=" * 50)
    
    try:
        # Test Native mode
        await test_native_mode_auth()
        
        # Test API mode (if server running)
        await test_api_mode_auth()
        
        # Test AuthManager consistency
        await test_auth_manager_consistency()
        
        # Verify service token removal
        await test_no_service_token()
        
        logger.info("\n" + "=" * 50)
        logger.info("Authentication tests completed!")
        
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())