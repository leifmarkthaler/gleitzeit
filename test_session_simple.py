#!/usr/bin/env python3
"""
Simple test to verify session management works.
"""

import asyncio
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    """Test basic session operations."""
    from gleitzeit.persistence.factory import PersistenceFactory
    from gleitzeit.auth.auth_manager import AuthManager
    from gleitzeit.events.stateless_bus import StatelessEventBus
    
    logger.info("=== Testing Session Management ===")
    
    # Create infrastructure
    persistence = await PersistenceFactory.create()
    event_bus = StatelessEventBus(persistence=persistence)
    auth_manager = AuthManager(persistence, event_bus)
    
    # Test in basic mode first (should always work)
    logger.info("\n1. Testing Basic Mode")
    auth_manager.auth_mode = "basic"
    
    # Login with basic mode
    result = await auth_manager.login(
        username="test",
        password="test",
        request_data={"ip_address": "127.0.0.1"}
    )
    
    logger.info(f"Basic login result: {result.get('success')}")
    logger.info(f"Session ID: {result.get('session_id')}")
    
    # Check session exists
    session = await auth_manager._get_session(result.get('session_id'))
    if session:
        logger.info("✓ Session stored in persistence")
    else:
        logger.error("✗ Session not found in persistence")
    
    # Check session index
    active_sessions = await auth_manager.get_all_active_sessions()
    logger.info(f"Active sessions in index: {len(active_sessions)}")
    
    # Logout
    logout_result = await auth_manager.logout(result.get('session_id'))
    logger.info(f"Logout result: {logout_result.get('success')}")
    
    # Verify session deleted
    session_after = await auth_manager._get_session(result.get('session_id'))
    if session_after is None:
        logger.info("✓ Session deleted after logout")
    else:
        logger.error("✗ Session still exists after logout")
    
    # Test advanced mode with actual user
    logger.info("\n2. Testing Advanced Mode")
    auth_manager.auth_mode = "advanced"
    
    # Create a test user
    try:
        user = await auth_manager.create_user(
            username="testuser",
            email="test@example.com",
            password="TestPass123!",
            role="user"
        )
        logger.info(f"Created user: {user.get('username')}")
    except Exception as e:
        if "already exists" in str(e):
            logger.info("User already exists, continuing...")
        else:
            logger.error(f"Failed to create user: {e}")
            return
    
    # Login with the created user
    try:
        result2 = await auth_manager.login(
            username="testuser",
            password="TestPass123!",
            request_data={
                "ip_address": "127.0.0.1",
                "user_agent": "TestClient/1.0"
            }
        )
        logger.info(f"Advanced login successful: {result2.get('success')}")
        logger.info(f"Session ID: {result2.get('session_id')}")
        
        # Check session with fingerprint
        session2 = await auth_manager._get_session(result2.get('session_id'))
        if session2 and session2.get('fingerprint'):
            logger.info("✓ Session includes fingerprint")
        else:
            logger.warning("✗ Session missing fingerprint")
        
        # Test concurrent login (should work with session limit)
        result3 = await auth_manager.login(
            username="testuser",
            password="TestPass123!",
            request_data={
                "ip_address": "192.168.1.1",
                "user_agent": "TestClient/2.0"
            }
        )
        logger.info(f"Second login successful: {result3.get('success')}")
        
        # Check total sessions for user
        user_sessions = await auth_manager.get_active_sessions(user.get('id'))
        logger.info(f"User has {len(user_sessions)} active sessions")
        
        # Cleanup
        await auth_manager.logout(result2.get('session_id'))
        await auth_manager.logout(result3.get('session_id'))
        
    except Exception as e:
        logger.error(f"Advanced mode test failed: {e}")
        import traceback
        traceback.print_exc()
    
    logger.info("\n=== Test Complete ===")

if __name__ == "__main__":
    asyncio.run(main())