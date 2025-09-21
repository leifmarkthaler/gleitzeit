#!/usr/bin/env python3
"""
Test to investigate why GleitzeitClient hangs during initialization.
"""

import sys
import asyncio
import signal
sys.path.insert(0, 'src')

from gleitzeit.client import GleitzeitClient, ClientMode

# Set timeout handler
def timeout_handler(signum, frame):
    print("\n⏰ TIMEOUT: Client initialization took too long!")
    print("The client appears to be stuck.")
    sys.exit(1)

async def test_client_init():
    """Test client initialization to find where it hangs."""
    print("\n=== Testing Client Initialization ===\n")
    
    # Set a 10-second timeout
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(10)
    
    try:
        print("1. Creating GleitzeitClient with API mode...")
        client = GleitzeitClient(
            mode=ClientMode.API, 
            base_url="http://localhost:8000",
            enable_events=False  # Try without events first
        )
        print("   ✓ Client created")
        
        print("\n2. Calling client.initialize()...")
        await client.initialize()
        print("   ✓ Client initialized")
        
        print("\n3. Testing basic operation...")
        auth_info = await client.get_auth_info()
        print(f"   ✓ Auth info: {auth_info}")
        
        print("\n4. Shutting down...")
        await client.shutdown()
        print("   ✓ Client shutdown")
        
        # Cancel timeout
        signal.alarm(0)
        
        print("\n✅ Client initialization successful!")
        
    except Exception as e:
        signal.alarm(0)
        print(f"\n❌ Error during initialization: {e}")
        import traceback
        traceback.print_exc()

async def test_client_with_events():
    """Test client with events enabled."""
    print("\n=== Testing Client with Events ===\n")
    
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(10)
    
    try:
        print("1. Creating GleitzeitClient with events enabled...")
        client = GleitzeitClient(
            mode=ClientMode.API, 
            base_url="http://localhost:8000",
            enable_events=True  # Enable events
        )
        print("   ✓ Client created")
        
        print("\n2. Calling client.initialize()...")
        await client.initialize()
        print("   ✓ Client initialized with events")
        
        print("\n3. Shutting down...")
        await client.shutdown()
        print("   ✓ Client shutdown")
        
        signal.alarm(0)
        print("\n✅ Client with events successful!")
        
    except Exception as e:
        signal.alarm(0)
        print(f"\n❌ Error with events: {e}")
        import traceback
        traceback.print_exc()

async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("CLIENT HANG INVESTIGATION")
    print("="*60)
    
    # Test without events
    await test_client_init()
    
    # Test with events
    await test_client_with_events()
    
    print("\n" + "="*60)
    print("INVESTIGATION COMPLETE")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(main())