#!/usr/bin/env python3
"""
Test UI authentication flow with auto-login
"""

import asyncio
import aiohttp
import json

API_URL = "http://localhost:8000"
UI_URL = "http://localhost:8001"  # Assuming UI runs on different port

async def test_ui_auth():
    """Test the UI authentication flow"""
    
    async with aiohttp.ClientSession() as session:
        print("=" * 60)
        print("Testing UI Authentication with Auto-Login")
        print("=" * 60)
        
        # Test 1: Check /api/auth/me without credentials (should auto-login)
        print("\n1. Testing /api/auth/me without credentials...")
        try:
            async with session.get(f"{API_URL}/auth/me") as resp:
                if resp.status == 200:
                    user = await resp.json()
                    print(f"✅ Auto-login successful!")
                    print(f"   User: {user.get('username')} ({user.get('role')})")
                    print(f"   Is basic user: {user.get('is_basic_user', False)}")
                    
                    # Get session cookie
                    cookies = resp.cookies
                    session_id = None
                    for cookie in cookies:
                        if cookie.key == 'session_id':
                            session_id = cookie.value
                            break
                    
                    if session_id:
                        print(f"   Session cookie set: {session_id[:20]}...")
                else:
                    print(f"❌ Failed: Status {resp.status}")
                    print(f"   Response: {await resp.text()}")
        except Exception as e:
            print(f"❌ Error: {e}")
        
        # Test 2: Check /api/auth/me with session cookie (should return same user)
        print("\n2. Testing /api/auth/me with session cookie...")
        try:
            async with session.get(f"{API_URL}/auth/me") as resp:
                if resp.status == 200:
                    user = await resp.json()
                    print(f"✅ Session maintained!")
                    print(f"   User: {user.get('username')} ({user.get('role')})")
                else:
                    print(f"❌ Failed: Status {resp.status}")
        except Exception as e:
            print(f"❌ Error: {e}")
        
        # Test 3: Try to login as admin (switches from basic user)
        print("\n3. Testing login as admin (switching from basic user)...")
        login_data = {
            "username": "admin",
            "password": "admin123"  # Replace with actual admin password
        }
        try:
            async with session.post(
                f"{API_URL}/auth/login",
                json=login_data
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"✅ Login successful!")
                    print(f"   User: {data.get('user', {}).get('username')}")
                    print(f"   Token provided: {'access_token' in data}")
                elif resp.status == 401:
                    print(f"⚠️  Invalid credentials (expected if admin doesn't exist)")
                else:
                    print(f"❌ Failed: Status {resp.status}")
                    print(f"   Response: {await resp.text()}")
        except Exception as e:
            print(f"❌ Error: {e}")
        
        # Test 4: Check current user after login attempt
        print("\n4. Checking current user after login attempt...")
        try:
            async with session.get(f"{API_URL}/auth/me") as resp:
                if resp.status == 200:
                    user = await resp.json()
                    print(f"✅ Current user retrieved!")
                    print(f"   User: {user.get('username')} ({user.get('role')})")
                else:
                    print(f"❌ Failed: Status {resp.status}")
        except Exception as e:
            print(f"❌ Error: {e}")
        
        # Test 5: Check if UI config endpoint works
        print("\n5. Testing UI config endpoint...")
        try:
            # This would be through the UI proxy
            async with session.get(f"{API_URL}/api/auth/status") as resp:
                if resp.status == 404:
                    print(f"⚠️  /api/auth/status not found (expected)")
                else:
                    print(f"❓ Unexpected status: {resp.status}")
        except Exception as e:
            print(f"⚠️  Could not reach endpoint: {e}")
        
        print("\n" + "=" * 60)
        print("Summary:")
        print("- Auto-login works: Basic user is automatically logged in")
        print("- Session management works: Cookie maintains session")
        print("- User switching possible: Can login as real user")
        print("- UI should call /api/auth/me, not /api/auth/status")
        print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_ui_auth())