#!/usr/bin/env python3
"""Minimal test for event persistence initialization."""

import asyncio
from gleitzeit.client import GleitzeitClient

async def test_minimal():
    """Test just the initialization and event store setup."""
    
    print("Minimal Event Persistence Test")
    print("=" * 40)
    
    config = {
        'persistence_type': 'memory',
        'persist_events': True
    }
    
    print("\n1. Creating client...")
    client = GleitzeitClient(mode='native', **config)
    
    print("\n2. Initializing (with timeout)...")
    try:
        # Add timeout to prevent hanging
        await asyncio.wait_for(client.initialize(), timeout=5.0)
        print("   ✓ Client initialized")
        
        # Check components
        print("\n3. Checking components...")
        if hasattr(client._adapter, 'persistence'):
            print("   ✓ Persistence created")
        
        if hasattr(client._adapter, 'event_bus'):
            print("   ✓ EventBus created")
            if hasattr(client._adapter.event_bus, 'event_store'):
                if client._adapter.event_bus.event_store:
                    print("   ✓ EventStore attached")
                else:
                    print("   ✗ EventStore NOT attached")
        
        if hasattr(client._adapter, 'event_store'):
            if client._adapter.event_store:
                print("   ✓ Adapter has EventStore")
        
        print("\n✓ Basic initialization successful!")
        
    except asyncio.TimeoutError:
        print("   ✗ Initialization timed out!")
        print("   This suggests a blocking operation during init")
    except Exception as e:
        print(f"   ✗ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n4. Shutting down...")
        try:
            await asyncio.wait_for(client.shutdown(), timeout=5.0)
            print("   ✓ Shutdown complete")
        except:
            print("   ✗ Shutdown failed or timed out")

if __name__ == "__main__":
    asyncio.run(test_minimal())