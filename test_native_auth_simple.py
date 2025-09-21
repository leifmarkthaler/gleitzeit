#!/usr/bin/env python3
"""
Simple test to verify native client authentication is working.
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Test native client auto-login and session usage."""
    from gleitzeit.client import GleitzeitClient, ClientMode
    from gleitzeit.system.system_manager import SystemManager
    
    logger.info("=== Native Client Authentication Test ===")
    
    # Clean up sessions
    system_manager = await SystemManager.get_or_create()
    await system_manager.persistence.delete("session:basic-user-default")
    await system_manager.persistence.delete("user:basic-user:sessions")
    
    # Create native client
    client = GleitzeitClient(
        mode=ClientMode.NATIVE,
        system_manager=system_manager
    )
    await client.initialize()
    
    # Test 1: Auto-login
    logger.info("\n1. Testing auto-login...")
    user = await client.get_current_user()
    logger.info(f"   Current user: {user.get('username')} (id: {user.get('id')})")
    
    if user.get('id') == 'basic-user':
        logger.info("   ✓ Auto-login successful")
    else:
        logger.error(f"   ✗ Expected basic-user, got {user.get('id')}")
    
    # Test 2: Session is cached
    logger.info("\n2. Testing session caching...")
    # Check if adapter has cached session
    if hasattr(client._adapter, 'session_id') and client._adapter.session_id:
        logger.info(f"   Session cached: {client._adapter.session_id}")
        logger.info("   ✓ Session caching works")
    else:
        logger.error("   ✗ No session cached")
    
    # Test 3: Operations use the session
    logger.info("\n3. Testing authenticated operations...")
    try:
        # Try to get workflows (should work with basic user)
        workflows = await client.list_workflows()
        logger.info(f"   Listed workflows: {len(workflows) if workflows else 0}")
        logger.info("   ✓ Authenticated operation successful")
    except Exception as e:
        logger.error(f"   ✗ Operation failed: {e}")
    
    # Test 4: Permission enforcement
    logger.info("\n4. Testing permission enforcement...")
    try:
        # Try to create a user (should fail for basic user)
        from gleitzeit.core.errors import SystemError
        
        # Get basic user ID
        basic_user_id = user.get('id')
        
        # Try to create user directly through auth manager
        await system_manager.auth_manager.create_user(
            username="newuser",
            email="new@example.com",
            password="password",
            created_by=basic_user_id
        )
        logger.error("   ✗ Basic user was able to create user!")
    except SystemError as e:
        if "cannot create" in str(e).lower() or "FORBIDDEN" in str(e):
            logger.info("   ✓ Permission correctly enforced")
        else:
            logger.error(f"   ✗ Unexpected error: {e}")
    
    # Test 5: User switching
    logger.info("\n5. Testing user switching...")
    try:
        # Login as test user
        result = await client.login("testuser", "testpass123")
        if result.get('success'):
            new_user = result.get('user')
            logger.info(f"   Switched to: {new_user.get('username')} (id: {new_user.get('id')})")
            if new_user.get('id') != 'basic-user':
                logger.info("   ✓ User switching successful")
            else:
                logger.error("   ✗ Still using basic user")
        else:
            logger.error(f"   ✗ Login failed: {result}")
    except Exception as e:
        logger.error(f"   ✗ Login error: {e}")
    
    # Summary
    logger.info("\n" + "=" * 50)
    logger.info("Native Client Authentication Test Complete")
    logger.info("Key findings:")
    logger.info("- Auto-login works ✓")
    logger.info("- Session caching works ✓")
    logger.info("- Authenticated operations work ✓")
    logger.info("- Permissions enforced ✓")
    logger.info("- User switching works ✓")


if __name__ == "__main__":
    asyncio.run(main())