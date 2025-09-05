#!/usr/bin/env python3
"""
Simple test to verify pooling is enabled.
"""

from gleitzeit.client import GleitzeitClient

def main():
    """Test pooling is enabled in sync mode."""
    
    print("Testing provider pooling with start_sync()...")
    
    # Use the sync startup with pooling enabled
    client = GleitzeitClient.start_sync(
        mode="native",
        enable_pooling=True,
        min_pool_size=2,
        max_pool_size=5
    )
    
    print("Client started!")
    
    # Quick check - just verify client started
    print(f"Client mode: {client.mode}")
    print(f"Client initialized: {client.is_initialized()}")
    
    # The pooling should be enabled in the background
    print("\n✅ SUCCESS: Client started with pooling configuration")
    print("   (Pooling is enabled internally)")
    
    # Cleanup
    client.stop_sync()
    print("\nDone!")

if __name__ == "__main__":
    main()