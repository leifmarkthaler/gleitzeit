#!/usr/bin/env python3
"""
Test auto-login functionality across all API endpoints.

Verifies that endpoints auto-login as basic user when no credentials provided.
"""

import asyncio
import aiohttp
import logging
from typing import Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "http://localhost:8000"

async def test_endpoint(session: aiohttp.ClientSession, method: str, path: str, 
                       expected_status: int = 200, json_data: Dict[str, Any] = None) -> bool:
    """Test a single endpoint."""
    url = f"{BASE_URL}{path}"
    try:
        async with session.request(method, url, json=json_data) as response:
            status = response.status
            
            # Try to get response body
            try:
                data = await response.json()
            except:
                data = await response.text()
            
            if status == expected_status:
                logger.info(f"✓ {method} {path} - Status: {status}")
                return True
            else:
                logger.error(f"✗ {method} {path} - Expected: {expected_status}, Got: {status}")
                logger.error(f"  Response: {data}")
                return False
                
    except Exception as e:
        logger.error(f"✗ {method} {path} - Error: {e}")
        return False


async def main():
    """Test all endpoints with auto-login."""
    logger.info("=== Testing Auto-Login Across All Endpoints ===\n")
    
    # Start the server first
    logger.info("Note: Make sure the server is running with: gleitzeit serve\n")
    
    async with aiohttp.ClientSession() as session:
        results = []
        
        # Test workflow endpoints (should auto-login)
        logger.info("--- Testing Workflow Endpoints ---")
        results.append(("GET /workflows", await test_endpoint(session, "GET", "/workflows")))
        
        # Test task endpoints (should auto-login)
        logger.info("\n--- Testing Task Endpoints ---")
        results.append(("GET /tasks", await test_endpoint(session, "GET", "/tasks")))
        
        # Test system endpoints (should auto-login)
        logger.info("\n--- Testing System Endpoints ---")
        results.append(("GET /system/health", await test_endpoint(session, "GET", "/system/health")))
        results.append(("GET /system/status", await test_endpoint(session, "GET", "/system/status")))
        results.append(("GET /system/info", await test_endpoint(session, "GET", "/system/info")))
        results.append(("GET /system/metrics", await test_endpoint(session, "GET", "/system/metrics")))
        results.append(("GET /system/resources", await test_endpoint(session, "GET", "/system/resources")))
        
        # Test log endpoints (should auto-login)
        logger.info("\n--- Testing Log Endpoints ---")
        results.append(("GET /logs", await test_endpoint(session, "GET", "/logs")))
        results.append(("GET /logs/levels", await test_endpoint(session, "GET", "/logs/levels")))
        results.append(("GET /logs/sources", await test_endpoint(session, "GET", "/logs/sources")))
        results.append(("GET /logs/stats", await test_endpoint(session, "GET", "/logs/stats")))
        
        # Test session endpoints (should auto-login)
        logger.info("\n--- Testing Session Endpoints ---")
        results.append(("GET /sessions", await test_endpoint(session, "GET", "/sessions")))
        results.append(("GET /sessions/devices", await test_endpoint(session, "GET", "/sessions/devices")))
        
        # Test admin endpoints (should fail for basic user - 403)
        logger.info("\n--- Testing Admin Endpoints (Should Fail) ---")
        results.append(("GET /admin/users", await test_endpoint(session, "GET", "/admin/users", expected_status=403)))
        results.append(("GET /admin/roles", await test_endpoint(session, "GET", "/admin/roles", expected_status=403)))
        results.append(("GET /admin/audit-logs", await test_endpoint(session, "GET", "/admin/audit-logs", expected_status=403)))
        
        # Test creating user (should fail for basic user - 403)
        logger.info("\n--- Testing Protected Operations ---")
        user_data = {
            "username": "testuser",
            "email": "test@example.com",
            "password": "testpass123"
        }
        results.append(("POST /admin/users", await test_endpoint(session, "POST", "/admin/users", expected_status=403, json_data=user_data)))
        
        # Test auth status endpoint
        logger.info("\n--- Testing Auth Status ---")
        results.append(("GET /auth/me", await test_endpoint(session, "GET", "/auth/me")))
        
        # Check auth status response
        async with session.get(f"{BASE_URL}/auth/me") as response:
            if response.status == 200:
                user_data = await response.json()
                logger.info(f"\nCurrent user: {user_data.get('username')} (id: {user_data.get('id')})")
                if user_data.get('id') == 'basic-user':
                    logger.info("✓ Auto-login working - using basic user")
                else:
                    logger.error("✗ Not using basic user for auto-login")
    
    # Summary
    logger.info("\n" + "=" * 50)
    logger.info("Test Summary:")
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASSED" if result else "✗ FAILED"
        logger.info(f"  {name}: {status}")
    
    logger.info(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("🎉 All auto-login tests passed!")
    else:
        logger.error("❌ Some tests failed")
        exit(1)


if __name__ == "__main__":
    asyncio.run(main())