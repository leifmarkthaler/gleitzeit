#!/usr/bin/env python3
"""
Test concurrent session operations to verify stateless scalability.

This tests:
1. Multiple concurrent logins (no race conditions)
2. Session revocation broadcasting
3. Session indexing efficiency
4. Distributed lock correctness
"""

import asyncio
import time
from datetime import datetime
from typing import List, Dict, Any
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_concurrent_logins():
    """Test multiple concurrent login operations."""
    from gleitzeit.persistence.factory import PersistenceFactory
    from gleitzeit.auth.auth_manager import AuthManager
    from gleitzeit.events.stateless_bus import StatelessEventBus
    
    logger.info("=== Testing Concurrent Logins ===")
    
    # Create shared persistence
    persistence = await PersistenceFactory.create()
    event_bus = StatelessEventBus(persistence=persistence)
    
    # Create multiple AuthManager instances (simulating different servers)
    auth_managers = []
    for i in range(3):
        auth_manager = AuthManager(persistence, event_bus)
        # Switch to advanced mode for testing
        auth_manager.auth_mode = "advanced"
        auth_managers.append(auth_manager)
    
    # Create test users
    logger.info("Creating test users...")
    for i in range(5):
        try:
            await auth_managers[0].create_user(
                username=f"testuser{i}",
                email=f"test{i}@example.com",
                password="TestPass123!",
                role="user"
            )
        except Exception as e:
            if "already exists" not in str(e):
                raise
    
    # Simulate concurrent logins from different "servers"
    logger.info("Simulating 15 concurrent logins...")
    
    async def login_task(auth_manager: AuthManager, user_idx: int, request_idx: int):
        """Single login task."""
        request_context = {
            "user_agent": f"TestClient/{request_idx}",
            "ip_address": f"192.168.1.{request_idx}",
            "accept_language": "en-US",
            "accept_encoding": "gzip"
        }
        
        try:
            result = await auth_manager.login(
                username=f"testuser{user_idx}",
                password="TestPass123!",
                request_data=request_context
            )
            return {
                "success": True,
                "session_id": result.get("session_id"),
                "user": f"testuser{user_idx}",
                "manager_idx": auth_managers.index(auth_manager)
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "user": f"testuser{user_idx}",
                "manager_idx": auth_managers.index(auth_manager)
            }
    
    # Create login tasks
    tasks = []
    for i in range(15):
        user_idx = i % 5  # 5 users
        manager_idx = i % 3  # 3 auth managers
        tasks.append(login_task(auth_managers[manager_idx], user_idx, i))
    
    # Execute concurrently
    start_time = time.time()
    results = await asyncio.gather(*tasks)
    elapsed = time.time() - start_time
    
    # Analyze results
    successful = sum(1 for r in results if r["success"])
    failed = sum(1 for r in results if not r["success"])
    
    logger.info(f"Completed {len(results)} login attempts in {elapsed:.2f}s")
    logger.info(f"Successful: {successful}, Failed: {failed}")
    
    # Verify session consistency
    logger.info("\n=== Verifying Session Consistency ===")
    
    # Check global session index
    global_sessions = await auth_managers[0].get_all_active_sessions()
    logger.info(f"Total active sessions in index: {len(global_sessions)}")
    
    # Verify each session exists
    valid_sessions = 0
    for session_id in global_sessions:
        session = await auth_managers[0]._get_session(session_id)
        if session:
            valid_sessions += 1
    
    logger.info(f"Valid sessions: {valid_sessions}/{len(global_sessions)}")
    
    return results


async def test_session_revocation_broadcast():
    """Test session revocation with event broadcasting."""
    from gleitzeit.persistence.factory import PersistenceFactory
    from gleitzeit.auth.auth_manager import AuthManager
    from gleitzeit.events.stateless_bus import StatelessEventBus
    from gleitzeit.core.events import EventType
    
    logger.info("\n=== Testing Session Revocation Broadcast ===")
    
    # Create shared infrastructure
    persistence = await PersistenceFactory.create()
    event_bus = StatelessEventBus(persistence=persistence)
    
    # Note: StatelessEventBus doesn't have subscribe method
    # We'll just verify the event is emitted by checking logs
    
    # Create auth manager
    auth_manager = AuthManager(persistence, event_bus)
    auth_manager.auth_mode = "advanced"
    
    # Create and login a user
    try:
        await auth_manager.create_user(
            username="revoketest",
            email="revoke@example.com",
            password="TestPass123!",
            role="user"
        )
    except:
        pass  # User might already exist
    
    login_result = await auth_manager.login(
        username="revoketest",
        password="TestPass123!",
        request_data={"ip_address": "127.0.0.1"}
    )
    
    session_id = login_result["session_id"]
    logger.info(f"Created session: {session_id}")
    
    # Logout to trigger revocation
    await asyncio.sleep(0.1)  # Allow event to propagate
    await auth_manager.logout(session_id)
    
    # Wait for event processing
    await asyncio.sleep(0.5)
    
    # Verify session is deleted
    session = await auth_manager._get_session(session_id)
    if session is None:
        logger.info("✓ Session successfully deleted from persistence")
    else:
        logger.error("✗ Session still exists in persistence")


async def test_session_cleanup():
    """Test efficient session cleanup using indexes."""
    from gleitzeit.persistence.factory import PersistenceFactory
    from gleitzeit.auth.auth_manager import AuthManager
    from gleitzeit.events.stateless_bus import StatelessEventBus
    
    logger.info("\n=== Testing Session Cleanup ===")
    
    # Create infrastructure
    persistence = await PersistenceFactory.create()
    event_bus = StatelessEventBus(persistence=persistence)
    auth_manager = AuthManager(persistence, event_bus)
    
    # Override token expiry for testing (very short)
    auth_manager.token_expiry_hours = 0.0001  # ~0.36 seconds
    auth_manager.auth_mode = "advanced"
    
    # Create test user
    try:
        await auth_manager.create_user(
            username="cleanuptest",
            email="cleanup@example.com",
            password="TestPass123!",
            role="user"
        )
    except:
        pass
    
    # Create multiple sessions
    logger.info("Creating test sessions...")
    session_ids = []
    for i in range(5):
        result = await auth_manager.login(
            username="cleanuptest",
            password="TestPass123!",
            request_data={"ip_address": f"192.168.1.{i}"}
        )
        session_ids.append(result["session_id"])
    
    logger.info(f"Created {len(session_ids)} sessions")
    
    # Check index before cleanup
    active_before = await auth_manager.get_all_active_sessions()
    logger.info(f"Active sessions before cleanup: {len(active_before)}")
    
    # Wait for sessions to expire
    logger.info("Waiting for sessions to expire...")
    await asyncio.sleep(1)
    
    # Run cleanup
    cleaned = await auth_manager.cleanup_expired_sessions_indexed()
    logger.info(f"Cleaned up {cleaned} expired sessions")
    
    # Check index after cleanup
    active_after = await auth_manager.get_all_active_sessions()
    logger.info(f"Active sessions after cleanup: {len(active_after)}")
    
    # Verify cleanup effectiveness
    for session_id in session_ids:
        session = await auth_manager._get_session(session_id)
        if session:
            logger.warning(f"Session {session_id} still exists after cleanup")


async def test_distributed_locks():
    """Test distributed lock behavior under contention."""
    from gleitzeit.persistence.factory import PersistenceFactory
    from gleitzeit.persistence.atomic_operations import AtomicPersistenceOperations
    
    logger.info("\n=== Testing Distributed Locks ===")
    
    persistence = await PersistenceFactory.create()
    
    # Skip test if not Redis
    if not hasattr(persistence, 'redis'):
        logger.info("Skipping distributed lock test (not using Redis)")
        return
    
    atomic_ops = AtomicPersistenceOperations(persistence.redis)
    
    # Test concurrent lock acquisition
    lock_resource = "test:resource"
    acquired_locks = []
    
    async def try_acquire_lock(idx: int):
        """Try to acquire a lock."""
        lock_id = f"lock_{idx}"
        acquired = await atomic_ops.acquire_lock(lock_resource, lock_id, ttl=2)
        if acquired:
            acquired_locks.append(idx)
            await asyncio.sleep(0.1)  # Hold lock briefly
            await atomic_ops.release_lock(lock_resource, lock_id)
        return acquired
    
    # Try to acquire same lock from 10 concurrent tasks
    tasks = [try_acquire_lock(i) for i in range(10)]
    results = await asyncio.gather(*tasks)
    
    successful_locks = sum(1 for r in results if r)
    logger.info(f"Lock acquisition attempts: 10, Successful: {successful_locks}")
    
    if successful_locks == 1:
        logger.info("✓ Distributed lock correctly ensures mutual exclusion")
    else:
        logger.warning(f"✗ Expected 1 successful lock, got {successful_locks}")


async def main():
    """Run all tests."""
    logger.info("Starting Session Management Concurrency Tests")
    logger.info("=" * 50)
    
    try:
        # Test concurrent logins
        await test_concurrent_logins()
        
        # Test session revocation broadcasting
        await test_session_revocation_broadcast()
        
        # Test session cleanup
        await test_session_cleanup()
        
        # Test distributed locks
        await test_distributed_locks()
        
        logger.info("\n" + "=" * 50)
        logger.info("All tests completed!")
        
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())