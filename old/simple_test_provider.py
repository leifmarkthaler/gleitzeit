#!/usr/bin/env python3
"""
Simple Test Provider - Minimal Implementation

Let's see what's really needed to create a basic working provider.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from gleitzeit_v4.core.execution_engine import ExecutionEngine, ExecutionMode
from gleitzeit_v4.core.models import Task, TaskStatus, Priority
from gleitzeit_v4.queue.task_queue import QueueManager
from gleitzeit_v4.queue.dependency_resolver import DependencyResolver
from gleitzeit_v4.registry import ProtocolProviderRegistry
from gleitzeit_v4.persistence.base import InMemoryBackend
from gleitzeit_v4.providers.base import ProtocolProvider
import uuid
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)


class MinimalProvider(ProtocolProvider):
    """Absolute minimal provider"""
    
    async def initialize(self):
        print(f"Initializing {self.provider_id}")
    
    async def shutdown(self):
        print(f"Shutting down {self.provider_id}")
    
    async def health_check(self):
        return True
    
    async def handle_request(self, request):
        print(f"Handling request: {request.method} with params: {request.params}")
        
        # Just return a simple response
        return {
            "success": True,
            "method": request.method,
            "echo_params": request.params,
            "provider": self.provider_id
        }


async def test_minimal_provider():
    """Test the minimal provider setup"""
    
    print("🔬 Testing Minimal Provider Setup")
    print("=" * 40)
    
    try:
        # Basic setup
        registry = ProtocolProviderRegistry()
        queue_manager = QueueManager()
        await queue_manager.get_default_queue().initialize()
        dependency_resolver = DependencyResolver()
        persistence = InMemoryBackend()
        
        # Create minimal provider
        provider = MinimalProvider(
            provider_id="minimal-test",
            protocol_id="simple/v1"
        )
        await provider.initialize()
        print("✓ Minimal provider created")
        
        # Let's see what happens when we try to register it
        try:
            registry.register_provider(
                provider_id="minimal-test",
                protocol_id="simple/v1",
                provider_instance=provider
            )
            print("✓ Provider registered successfully")
        except Exception as e:
            print(f"❌ Provider registration failed: {e}")
            print(f"   This tells us what's missing in our system!")
            
            # Let's check what protocols exist
            print(f"   Available protocols: {list(registry.protocol_registry.protocols.keys())}")
            
            # This is the core issue - we need to understand:
            # 1. How should protocol registration work?
            # 2. Should it be automatic?
            # 3. What's the minimal path?
            
        return False
        
    except Exception as e:
        print(f"💥 Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_minimal_provider())
    
    print(f"\n🤔 ANALYSIS:")
    print(f"{'✅ SUCCESS' if success else '❌ FAILED'}")
    
    if not success:
        print("\n💡 INSIGHTS:")
        print("- Provider registration requires pre-registered protocols")
        print("- The system assumes complex protocol specs")
        print("- There's no 'quick start' path for simple providers")
        print("- This suggests we need a simpler provider registration API")
        
    exit(0 if success else 1)