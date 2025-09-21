#!/usr/bin/env python3
"""
Debug why /auth/me returns 401 in basic mode.
"""

import requests
import json

def test_with_debug():
    """Test auth endpoint with debugging."""
    
    base_url = "http://localhost:8000"
    
    print("Testing /auth/me endpoint")
    print("=" * 60)
    
    # Test 1: No headers at all
    print("\n1. No headers:")
    response = requests.get(f"{base_url}/auth/me")
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.text}")
    
    # Test 2: Empty Authorization header
    print("\n2. Empty Authorization header:")
    headers = {"Authorization": ""}
    response = requests.get(f"{base_url}/auth/me", headers=headers)
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.text}")
    
    # Test 3: Bearer with no token
    print("\n3. Bearer with no token:")
    headers = {"Authorization": "Bearer"}
    response = requests.get(f"{base_url}/auth/me", headers=headers)
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.text}")
    
    # Test 4: Bearer with empty token
    print("\n4. Bearer with empty token:")
    headers = {"Authorization": "Bearer "}
    response = requests.get(f"{base_url}/auth/me", headers=headers)
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.text}")
    
    # Test 5: Check if system is in basic mode via health
    print("\n5. System info:")
    response = requests.get(f"{base_url}/health")
    if response.status_code == 200:
        data = response.json()
        print(f"   Health: {data.get('status')}")
        print(f"   Backend: {data.get('pool_info', {}).get('backend')}")
    
    print("\n" + "=" * 60)
    print("In basic mode, /auth/me should return basic user without auth")

if __name__ == "__main__":
    test_with_debug()