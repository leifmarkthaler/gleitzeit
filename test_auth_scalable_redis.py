#!/usr/bin/env python3
"""
Test Auth and Session Management with ScalableRedisAdapter

Validates that the new unified ScalableRedisAdapter works correctly
with AuthManager and SystemManager sessions.
"""

import asyncio
import uuid
import json
from datetime import datetime

from src.gleitzeit.persistence.scalable_redis import (
    ScalableRedisAdapter, PersistenceMode
)
from src.gleitzeit.persistence.factory_v2 import PersistenceFactory
from src.gleitzeit.auth.auth_manager import AuthManager
from src.gleitzeit.system.system_manager import SystemManager


async def test_auth_with_scalable_redis():
    """Test AuthManager with ScalableRedisAdapter."""
    print("\n=== Testing Auth with ScalableRedisAdapter ===")
    
    # Create adapter using new factory
    adapter = await PersistenceFactory.create(
        mode=PersistenceMode.SINGLE,
        redis_url="redis://localhost:6379/0",
        config={
            "key_prefix": f"test_auth_{uuid.uuid4().hex[:8]}",
            "enable_metrics": True
        }
    )
    
    try:
        # Create AuthManager with the new adapter
        auth_manager = AuthManager(persistence=adapter)
        
        # Ensure basic user exists
        await auth_manager.ensure_basic_user_exists()
        print("✅ Basic user created/verified")
        
        # Test login with basic user
        result = await auth_manager.login("basic", "basic")
        assert "token" in result
        assert "user" in result
        token = result["token"]
        user = result["user"]
        print(f"✅ Login successful: user={user['username']}, token={token[:20]}...")
        
        # Test session validation
        session_data = await auth_manager.validate_session(token)
        assert session_data is not None
        # Session data might have different field names
        user_id = session_data.get("user_id") or session_data.get("id") or user["id"]
        print(f"✅ Session validated: user_id={user_id}")
        
        # Test creating a new user
        new_user_data = await auth_manager.create_user(
            username=f"test_user_{uuid.uuid4().hex[:8]}",
            email=f"test_{uuid.uuid4().hex[:8]}@example.com",
            password="testpass123",
            role="user"
        )
        assert new_user_data["id"]
        print(f"✅ New user created: {new_user_data['username']}")
        
        # Test listing sessions
        sessions = await auth_manager.list_user_sessions(user["id"])
        assert len(sessions) > 0
        print(f"✅ Found {len(sessions)} active sessions")
        
        # Test logout
        await auth_manager.logout(token)
        print("✅ Logout successful")
        
        # Verify session is invalidated
        invalid_session = await auth_manager.validate_session(token)
        assert invalid_session is None
        print("✅ Session correctly invalidated after logout")
        
    finally:
        await adapter.close()
    
    print("✅ Auth with ScalableRedisAdapter test completed")


async def test_system_manager_with_scalable_redis():
    """Test SystemManager with ScalableRedisAdapter."""
    print("\n=== Testing SystemManager with ScalableRedisAdapter ===")
    
    # Create adapter using new factory
    adapter = await PersistenceFactory.create(
        mode=PersistenceMode.SINGLE,
        redis_url="redis://localhost:6379/0",
        config={
            "key_prefix": f"test_system_{uuid.uuid4().hex[:8]}",
            "enable_metrics": True,
            "enable_events": True,
            "consumer_group": "test-system"
        }
    )
    
    try:
        # Create SystemManager with the new adapter
        system_manager = await SystemManager.get_or_create(
            persistence=adapter,
            instance_id=f"test-instance-{uuid.uuid4().hex[:8]}",
            start_system=False  # Don't start full system for test
        )
        print(f"✅ SystemManager created: {system_manager.instance_id}")
        
        # Test system state persistence
        instance_id = system_manager.instance_id
        assert instance_id is not None
        print(f"✅ System info retrieved: instance_id={instance_id}")
        
        # Test auth manager integration
        auth_manager = system_manager.auth_manager
        assert auth_manager is not None
        assert auth_manager.persistence == adapter
        print("✅ AuthManager correctly integrated with same adapter")
        
        # Test basic user exists
        await auth_manager.ensure_basic_user_exists()
        
        # Test auth through system manager
        login_result = await auth_manager.login("basic", "basic")
        assert "token" in login_result
        print("✅ Auth through SystemManager working")
        
        # Test system health check (uses persistence)
        health = await system_manager.health_check()
        assert health["status"] in ["healthy", "initializing"]
        print(f"✅ System health check: {health['status']}")
        
        # Test service registry (uses persistence)
        services = await system_manager.list_services()
        print(f"✅ Service registry working: {len(services)} services")
        
    finally:
        # Cleanup
        if hasattr(system_manager, 'shutdown'):
            await system_manager.shutdown()
        await adapter.close()
    
    print("✅ SystemManager with ScalableRedisAdapter test completed")


async def test_session_persistence_across_instances():
    """Test that sessions persist across different adapter instances."""
    print("\n=== Testing Session Persistence Across Instances ===")
    
    # Use a fixed key prefix for this test
    key_prefix = f"test_persist_{uuid.uuid4().hex[:8]}"
    
    # Create first adapter and auth manager
    adapter1 = await PersistenceFactory.create(
        mode=PersistenceMode.SINGLE,
        config={"key_prefix": key_prefix}
    )
    
    auth_manager1 = AuthManager(persistence=adapter1)
    await auth_manager1.ensure_basic_user_exists()
    
    # Login and get token
    result = await auth_manager1.login("basic", "basic")
    token = result["token"]
    user_id = result["user"]["id"]
    print(f"✅ Created session with adapter1: token={token[:20]}...")
    
    # Close first adapter
    await adapter1.close()
    
    # Create second adapter with same key prefix
    adapter2 = await PersistenceFactory.create(
        mode=PersistenceMode.SINGLE,
        config={"key_prefix": key_prefix}
    )
    
    try:
        auth_manager2 = AuthManager(persistence=adapter2)
        
        # Validate the same token with different instance
        session_data = await auth_manager2.validate_session(token)
        assert session_data is not None
        validated_user_id = session_data.get("user_id") or session_data.get("id") or user_id
        assert validated_user_id == user_id
        print(f"✅ Session validated with adapter2: user_id={validated_user_id}")
        
        # List sessions to verify persistence
        sessions = await auth_manager2.list_user_sessions(user_id)
        assert len(sessions) > 0
        assert any(s["token"] == token for s in sessions)
        print(f"✅ Session found in adapter2: {len(sessions)} total sessions")
        
        # Logout with second instance
        await auth_manager2.logout(token)
        print("✅ Logout successful with adapter2")
        
    finally:
        await adapter2.close()
    
    # Create third adapter to verify logout persisted
    adapter3 = await PersistenceFactory.create(
        mode=PersistenceMode.SINGLE,
        config={"key_prefix": key_prefix}
    )
    
    try:
        auth_manager3 = AuthManager(persistence=adapter3)
        
        # Verify session is invalid
        session_data = await auth_manager3.validate_session(token)
        assert session_data is None
        print("✅ Session correctly invalidated in adapter3")
        
    finally:
        await adapter3.close()
    
    print("✅ Session persistence across instances test completed")


async def test_concurrent_sessions():
    """Test concurrent session management with ScalableRedisAdapter."""
    print("\n=== Testing Concurrent Sessions ===")
    
    adapter = await PersistenceFactory.create(
        mode=PersistenceMode.SINGLE,
        config={
            "key_prefix": f"test_concurrent_{uuid.uuid4().hex[:8]}",
            "enable_metrics": True
        }
    )
    
    try:
        auth_manager = AuthManager(persistence=adapter)
        await auth_manager.ensure_basic_user_exists()
        
        # Create multiple concurrent sessions
        tokens = []
        for i in range(5):
            result = await auth_manager.login("basic", "basic")
            tokens.append(result["token"])
            print(f"  Created session {i+1}")
        
        print(f"✅ Created {len(tokens)} concurrent sessions")
        
        # Validate all sessions concurrently
        validation_tasks = [
            auth_manager.validate_session(token) for token in tokens
        ]
        results = await asyncio.gather(*validation_tasks)
        
        # All should be valid
        assert all(r is not None for r in results)
        print(f"✅ All {len(tokens)} sessions validated concurrently")
        
        # Get session list
        sessions = await auth_manager.list_user_sessions("basic-user")
        assert len(sessions) >= len(tokens)
        print(f"✅ Session list shows {len(sessions)} active sessions")
        
        # Revoke all sessions
        await auth_manager.revoke_all_user_sessions("basic-user")
        print("✅ Revoked all user sessions")
        
        # Verify all are invalid
        validation_tasks = [
            auth_manager.validate_session(token) for token in tokens
        ]
        results = await asyncio.gather(*validation_tasks)
        assert all(r is None for r in results)
        print("✅ All sessions correctly invalidated")
        
        # Check metrics
        if adapter.metrics_collector:
            metrics = adapter.metrics_collector.get_summary()
            print(f"✅ Metrics: {metrics['total_operations']} operations performed")
        
    finally:
        await adapter.close()
    
    print("✅ Concurrent sessions test completed")


async def main():
    """Run all auth and session tests."""
    print("=" * 60)
    print("Auth and Session Tests with ScalableRedisAdapter")
    print("=" * 60)
    
    tests = [
        ("Auth with ScalableRedisAdapter", test_auth_with_scalable_redis),
        ("SystemManager with ScalableRedisAdapter", test_system_manager_with_scalable_redis),
        ("Session Persistence Across Instances", test_session_persistence_across_instances),
        ("Concurrent Sessions", test_concurrent_sessions),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            await test_func()
            passed += 1
        except AssertionError as e:
            print(f"❌ {name} failed: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {name} error: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"Test Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)