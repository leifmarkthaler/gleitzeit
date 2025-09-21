#!/usr/bin/env python3
"""Simple test script to test UI logs functionality"""

import requests
import time

API_URL = "http://localhost:8001/api/logs"
API_DIRECT_URL = "http://localhost:8080/logs"  # Direct API server

def test_logs_endpoints():
    """Test all log endpoints"""
    print("Testing UI logs endpoints...")
    
    try:
        # Test main logs endpoint
        print("\n1. Testing GET /api/logs/")
        response = requests.get(f"{API_URL}/", timeout=5)
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            logs = response.json()
            print(f"   Found: {len(logs)} logs" if isinstance(logs, list) else f"   Response: {logs}")
        else:
            print(f"   Error: {response.text}")
    
        # Test log levels endpoint
        print("\n2. Testing GET /api/logs/levels")
        response = requests.get(f"{API_URL}/levels", timeout=5)
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            levels = response.json()
            print(f"   Levels: {levels}")
        else:
            print(f"   Error: {response.text}")
    
        # Test log sources endpoint
        print("\n3. Testing GET /api/logs/sources")
        response = requests.get(f"{API_URL}/sources", timeout=5)
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            sources = response.json()
            print(f"   Sources: {sources}")
        else:
            print(f"   Error: {response.text}")
    
        # Test log stats endpoint
        print("\n4. Testing GET /api/logs/stats")
        response = requests.get(f"{API_URL}/stats", timeout=5)
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            stats = response.json()
            print(f"   Stats: {stats}")
        else:
            print(f"   Error: {response.text}")
    
        # Test logs page
        print("\n5. Testing logs page")
        response = requests.get("http://localhost:8001/logs", timeout=5)
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            print("   ✅ Logs page accessible")
        else:
            print(f"   Error: {response.text}")
            
    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to UI server (http://localhost:8001)")
        print("   Make sure the UI server is running with: gleitzeit ui --port 8001")
    except Exception as e:
        print(f"❌ Error: {e}")

def test_ui_page():
    """Test if the logs UI page loads"""
    try:
        response = requests.get("http://localhost:8001/logs", timeout=5)
        if response.status_code == 200:
            content = response.text
            if "System Logs" in content and "logs-container" in content:
                print("✅ UI logs page loads correctly with expected content")
                return True
            else:
                print("⚠️  UI logs page loads but missing expected content")
                return False
        else:
            print(f"❌ UI logs page failed to load: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error loading UI page: {e}")
        return False

if __name__ == "__main__":
    print("Testing UI Logs Implementation")
    print("=" * 50)
    
    # Test the UI page first
    test_ui_page()
    
    # Test the API endpoints  
    test_logs_endpoints()
    
    print("\n" + "=" * 50)
    print("Test complete!")