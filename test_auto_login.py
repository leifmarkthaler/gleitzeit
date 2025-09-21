#!/usr/bin/env python3
"""
Test auto-login functionality for basic user.

Verifies:
1. Auto-login on first use (no credentials)
2. User switching when logging in with different credentials
3. Session persistence across requests
4. Basic user session limit still enforced
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_auto_login():
    """Test that basic user is auto-logged in on first use."""
    logger.info("=== Testing Auto-Login ===")
    
    from gleitzeit.client import GleitzeitClient, ClientMode
    from gleitzeit.system.system_manager import SystemManager
    
    # Clean up any existing sessions
    system_manager = await SystemManager.get_or_create()
    await system_manager.persistence.delete("session:basic-user-default")
    await system_manager.persistence.delete("user:basic-user:sessions")
    
    # Create client without any credentials
    client = GleitzeitClient(
        mode=ClientMode.NATIVE,
        system_manager=system_manager
    )
    await client.initialize()
    
    # This should auto-login as basic user
    from gleitzeit.api.auth_dependencies import get_current_user_auto
    from fastapi import Request, Response
    
    # Simulate request/response
    class MockRequest:
        def __init__(self):
            self.cookies = {}
    
    class MockResponse:
        def __init__(self):
            self.cookies = {}
        
        def set_cookie(self, key, value, **kwargs):
            self.cookies[key] = value
    
    request = MockRequest()
    response = MockResponse()
    
    # Get current user (should auto-login)
    user = await get_current_user_auto(
        request=request,
        response=response,
        credentials=None,
        system_manager=system_manager
    )
    
    logger.info(f"Auto-logged in as: {user.get('username')} (id: {user.get('id')})")
    
    # Check it's the basic user
    if user.get('id') == 'basic-user':
        logger.info("✓ Successfully auto-logged in as basic user")
    else:
        logger.error(f"✗ Expected basic-user, got {user.get('id')}")
        return False
    
    # Check session cookie was set
    if 'session_id' in response.cookies:
        logger.info(f"✓ Session cookie set: {response.cookies['session_id']}")
    else:
        logger.error("✗ No session cookie set")
        return False
    
    await client.shutdown()
    return True


async def test_user_switching():
    """Test switching from basic user to real user."""
    logger.info("\n=== Testing User Switching ===")
    
    from gleitzeit.system.system_manager import SystemManager
    from gleitzeit.core.errors import SystemError
    
    system_manager = await SystemManager.get_or_create()
    
    # Clean up sessions
    await system_manager.persistence.delete("session:basic-user-default")
    await system_manager.persistence.delete("user:basic-user:sessions")
    
    # First, auto-login as basic user
    result1 = await system_manager.auth_manager.get_or_create_basic_session()
    session1 = result1[0]
    user1 = result1[1]
    logger.info(f"Auto-logged in as: {user1.get('username')}")
    
    # Create a real user
    try:
        await system_manager.auth_manager.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
            role="user"
        )
        logger.info("Created test user")
    except SystemError as e:
        if "already exists" in str(e):
            logger.info("Test user already exists")
        else:
            raise
    
    # Now login as the real user (should switch)
    result2 = await system_manager.auth_manager.login("testuser", "testpass123", None)
    
    if result2.get("success"):
        user2 = result2.get("user")
        logger.info(f"Switched to user: {user2.get('username')} (id: {user2.get('id')})")
        
        if user2.get('id') != 'basic-user':
            logger.info("✓ Successfully switched from basic user to real user")
        else:
            logger.error("✗ Still logged in as basic user")
            return False
    else:
        logger.error("✗ Failed to login as real user")
        return False
    
    # Check that basic user session was cleaned up
    basic_session = await system_manager.auth_manager._get_session("basic-user-default")
    if not basic_session:
        logger.info("✓ Basic user session cleaned up after switching")
    else:
        logger.info("Note: Basic user session still exists (may be by design)")
    
    return True


async def test_session_persistence():
    """Test that auto-login session persists across requests."""
    logger.info("\n=== Testing Session Persistence ===")
    
    from gleitzeit.system.system_manager import SystemManager
    from gleitzeit.api.auth_dependencies import get_current_user_auto
    from fastapi import Request, Response
    
    system_manager = await SystemManager.get_or_create()
    
    # Clean up sessions
    await system_manager.persistence.delete("session:basic-user-default")
    await system_manager.persistence.delete("user:basic-user:sessions")
    
    # First request - auto-login
    class MockRequest:
        def __init__(self, cookies=None):
            self.cookies = cookies or {}
    
    class MockResponse:
        def __init__(self):
            self.cookies = {}
        
        def set_cookie(self, key, value, **kwargs):
            self.cookies[key] = value
    
    request1 = MockRequest()
    response1 = MockResponse()
    
    user1 = await get_current_user_auto(
        request=request1,
        response=response1,
        credentials=None,
        system_manager=system_manager
    )
    
    session_id = response1.cookies.get('session_id')
    logger.info(f"First request - user: {user1.get('username')}, session: {session_id}")
    
    # Second request - use existing session
    request2 = MockRequest(cookies={'session_id': session_id})
    response2 = MockResponse()
    
    user2 = await get_current_user_auto(
        request=request2,
        response=response2,
        credentials=None,
        system_manager=system_manager
    )
    
    logger.info(f"Second request - user: {user2.get('username')}")
    
    # Should be same user
    if user1.get('id') == user2.get('id'):
        logger.info("✓ Session persisted across requests")
    else:
        logger.error(f"✗ Different users: {user1.get('id')} vs {user2.get('id')}")
        return False
    
    # Should not create new session
    if 'session_id' not in response2.cookies:
        logger.info("✓ No new session created (reused existing)")
    else:
        logger.error("✗ New session created instead of reusing")
        return False
    
    return True


async def test_basic_user_limit_with_auto_login():
    """Test that basic user session limit is still enforced."""
    logger.info("\n=== Testing Basic User Session Limit with Auto-Login ===")
    
    from gleitzeit.system.system_manager import SystemManager
    from gleitzeit.core.errors import SystemError
    
    system_manager = await SystemManager.get_or_create()
    
    # Clean up sessions
    await system_manager.persistence.delete("session:basic-user-default")
    await system_manager.persistence.delete("user:basic-user:sessions")
    
    # First auto-login should work
    session1, user1 = await system_manager.auth_manager.get_or_create_basic_session()
    logger.info(f"First auto-login: {session1}")
    
    # Try to create another session (should fail)
    try:
        # Manual login as basic user
        result = await system_manager.auth_manager.login("basic", "basic", None)
        logger.error("✗ Second basic user login succeeded - should have been blocked!")
        return False
    except SystemError as e:
        if "SESSION_LIMIT_EXCEEDED" in str(e) or "already has an active session" in str(e):
            logger.info("✓ Session limit enforced - second login blocked")
        else:
            logger.error(f"✗ Unexpected error: {e}")
            return False
    
    return True


async def main():
    """Run all auto-login tests."""
    logger.info("Starting Auto-Login Tests")
    logger.info("=" * 50)
    
    tests = [
        ("Auto-Login", test_auto_login),
        ("User Switching", test_user_switching),
        ("Session Persistence", test_session_persistence),
        ("Basic User Limit", test_basic_user_limit_with_auto_login),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = await test_func()
            results.append((name, result))
        except Exception as e:
            logger.error(f"Test '{name}' crashed: {e}", exc_info=True)
            results.append((name, False))
    
    # Summary
    logger.info("\n" + "=" * 50)
    logger.info("Test Summary:")
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASSED" if result else "✗ FAILED"
        logger.info(f"  {name}: {status}")
    
    logger.info(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("🎉 All tests passed!")
    else:
        logger.error("❌ Some tests failed")
        exit(1)


if __name__ == "__main__":
    asyncio.run(main())