#!/usr/bin/env python3
"""Test script to debug API server issues"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.api.main import app, setup_system, cleanup_system, app_state

async def test_setup():
    """Test the API server setup"""
    try:
        print("Starting API setup...")
        await setup_system()
        print("✓ Setup completed successfully")
        
        # Check providers
        print(f"\nRegistered providers:")
        if app_state.registry:
            for provider_id in app_state.registry.provider_instances:
                print(f"  - {provider_id}")
        else:
            print("  No registry!")
            
        # Check execution engine
        if app_state.execution_engine:
            print(f"✓ Execution engine initialized")
            print(f"  Running: {app_state.execution_engine.running}")
        else:
            print("✗ No execution engine!")
            
    except Exception as e:
        print(f"✗ Setup failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\nCleaning up...")
        await cleanup_system()

if __name__ == "__main__":
    asyncio.run(test_setup())