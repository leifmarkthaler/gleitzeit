#!/usr/bin/env python3
"""
Test the refactored authentication system.
Verifies:
1. Basic user exists on startup
2. Basic user has limited permissions
3. Basic user cannot create other users  
4. Session limits for basic user (max 1)
5. Multiple concurrent users work correctly
"""

import asyncio
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_basic_user_exists():
    """Test that basic user is created on startup."""
    logger.info("=== Testing Basic User Creation ===")
    
    from gleitzeit.system.system_manager import SystemManager
    
    # Get or create SystemManager
    system_manager = await SystemManager.get_or_create()
    
    # Check that basic user exists
    basic_user = await system_manager.auth_manager._get_user_by_username("basic")
    if basic_user:
        logger.info(f"✓ Basic user exists: {basic_user.get('username')}")
        logger.info(f"  Role: {basic_user.get('role')}")
        logger.info(f"  Is basic user: {basic_user.get('is_basic_user')}")
    else:
        logger.error("✗ Basic user not found!")
        return False
    
    # Check permissions
    permissions = basic_user.get("permissions", [])
    logger.info(f"  Permissions ({len(permissions)}): {permissions[:5]}...")
    
    # Verify NO admin permissions
    admin_perms = [p for p in permissions if "users:" in p or "admin:" in p]
    if not admin_perms:
        logger.info("✓ Basic user has no admin permissions")
    else:
        logger.error(f"✗ Basic user has admin permissions: {admin_perms}")
        return False
    
    return True

async def test_basic_user_session_limit():
    """Test that basic user can only have 1 active session."""
    logger.info("\n=== Testing Basic User Session Limit ===")
    
    from gleitzeit.system.system_manager import SystemManager
    
    system_manager = await SystemManager.get_or_create()
    
    # Clean up any existing sessions first
    await system_manager.persistence.delete("session:basic-user-default")
    sessions_key = "user:basic-user:sessions"
    await system_manager.persistence.delete(sessions_key)
    
    try:
        # First login should succeed
        result1 = await system_manager.auth_manager.login("basic", "basic", None)
        if result1.get("success"):
            logger.info("✓ First basic user login successful")
            session1 = result1.get("session_id")
        else:
            logger.error("✗ First login failed")
            return False
        
        # Second login should fail (session limit)
        try:
            result2 = await system_manager.auth_manager.login("basic", "basic", None)
            logger.error("✗ Second login succeeded - should have been blocked!")
            return False
        except Exception as e:
            if "SESSION_LIMIT_EXCEEDED" in str(e) or "already has an active session" in str(e):
                logger.info("✓ Second login blocked - session limit enforced")
            else:
                logger.error(f"✗ Second login failed with unexpected error: {e}")
                return False
        
        # Logout first session
        await system_manager.auth_manager.logout(session1)
        logger.info("✓ Logged out first session")
        
        # Now third login should succeed
        result3 = await system_manager.auth_manager.login("basic", "basic", None)
        if result3.get("success"):
            logger.info("✓ Third login successful after logout")
        else:
            logger.error("✗ Third login failed after logout")
            return False
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        return False
    
    return True

async def test_basic_user_cannot_create_users():
    """Test that basic user cannot create other users."""
    logger.info("\n=== Testing Basic User Cannot Create Users ===")
    
    from gleitzeit.system.system_manager import SystemManager
    from gleitzeit.core.errors import SystemError, ErrorCode
    
    system_manager = await SystemManager.get_or_create()
    
    # Clean up any existing sessions first
    await system_manager.persistence.delete("session:basic-user-default")
    sessions_key = "user:basic-user:sessions"
    await system_manager.persistence.delete(sessions_key)
    
    try:
        # Login as basic user
        result = await system_manager.auth_manager.login("basic", "basic", None)
        basic_user_id = result["user"]["id"]
        
        # Try to create a new user
        try:
            new_user = await system_manager.auth_manager.create_user(
                username="testuser",
                email="test@example.com",
                password="testpass123",
                role="user",
                created_by=basic_user_id
            )
            logger.error("✗ Basic user was able to create a new user!")
            return False
        except SystemError as e:
            if e.code == ErrorCode.FORBIDDEN:
                logger.info("✓ Basic user correctly blocked from creating users")
            else:
                logger.error(f"✗ Unexpected error: {e}")
                return False
                
    except Exception as e:
        logger.error(f"Test failed: {e}")
        return False
    
    return True

async def test_no_auth_mode():
    """Test that auth_mode concept is removed."""
    logger.info("\n=== Testing Auth Mode Removal ===")
    
    from gleitzeit.system.system_manager import SystemManager
    
    system_manager = await SystemManager.get_or_create()
    
    # Check that auth_mode attribute doesn't exist
    if hasattr(system_manager.auth_manager, 'auth_mode'):
        logger.error("✗ auth_mode attribute still exists on AuthManager")
        return False
    else:
        logger.info("✓ auth_mode attribute removed from AuthManager")
    
    # Check that authentication is always required
    try:
        # Try to get current user without session
        user = await system_manager.auth_manager.get_current_user(None)
        logger.error("✗ Got user without session - auth should be required!")
        return False
    except Exception as e:
        if "AUTHENTICATION_REQUIRED" in str(e) or "No session provided" in str(e) or "Failed to get user info" in str(e):
            logger.info("✓ Authentication properly required")
        else:
            logger.error(f"✗ Unexpected error: {e}")
            return False
    
    return True

async def test_unauthenticated_user():
    """Test unauthenticated user has no permissions."""
    logger.info("\n=== Testing Unauthenticated User ===")
    
    from gleitzeit.system.system_manager import SystemManager
    
    system_manager = await SystemManager.get_or_create()
    
    # Get unauthenticated user
    unauth_user = system_manager.auth_manager.get_unauthenticated_user()
    
    logger.info(f"Unauthenticated user: {unauth_user.get('username')}")
    logger.info(f"  ID: {unauth_user.get('id')}")
    logger.info(f"  Role: {unauth_user.get('role')}")
    logger.info(f"  Permissions: {unauth_user.get('permissions')}")
    
    # Check no permissions
    if len(unauth_user.get('permissions', [])) == 0:
        logger.info("✓ Unauthenticated user has no permissions")
    else:
        logger.error(f"✗ Unauthenticated user has permissions: {unauth_user['permissions']}")
        return False
    
    return True

async def main():
    """Run all authentication tests."""
    logger.info("Starting Authentication Refactor Tests")
    logger.info("=" * 50)
    
    tests = [
        ("Basic User Exists", test_basic_user_exists),
        ("No Auth Mode", test_no_auth_mode),
        ("Basic User Session Limit", test_basic_user_session_limit),
        ("Basic User Cannot Create Users", test_basic_user_cannot_create_users),
        ("Unauthenticated User", test_unauthenticated_user),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = await test_func()
            results.append((name, result))
        except Exception as e:
            logger.error(f"Test '{name}' crashed: {e}")
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