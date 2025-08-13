#!/usr/bin/env python3
"""
Debug Pooling Hang

Figure out why pooling adapter execute_task is hanging.
"""

import asyncio
import sys
from pathlib import Path
from typing import Dict, Any

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from gleitzeit_v4.pooling.adapter import PoolingAdapter
from gleitzeit_v4.core.models import Task, Priority
from gleitzeit_v4.registry import ProtocolProviderRegistry
from gleitzeit_v4.providers.base import ProtocolProvider
import uuid
import logging

# Enable detailed logging
logging.basicConfig(level=logging.DEBUG)

class DebugProvider(ProtocolProvider):
    """Debug provider with lots of logging"""
    
    def __init__(self, provider_id: str, **kwargs):
        super().__init__(provider_id=provider_id, protocol_id="debug/v1")
        print(f"🔍 DebugProvider created: {provider_id}")
    
    async def initialize(self):
        print(f"🔍 DebugProvider.initialize() called")
    
    async def shutdown(self):
        print(f"🔍 DebugProvider.shutdown() called")
    
    async def health_check(self):
        print(f"🔍 DebugProvider.health_check() called")
        return True
    
    def get_supported_methods(self):
        """Return list of supported methods"""
        return ["test"]
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        print(f"🔍 DebugProvider.handle_request() called")
        print(f"🔍   Method: {method}")
        print(f"🔍   Params: {params}")
        
        if method == "test":
            result = {"status": "ok", "provider": self.provider_id}
            print(f"🔍 DebugProvider returning: {result}")
            return result
        else:
            raise ValueError(f"Unknown method: {method}")

async def debug_pooling_hang():
    """Debug why pooling hangs"""
    
    print("🔍 DEBUGGING: Pooling Hang Issue")
    print("=" * 50)
    
    try:
        print("🔍 Step 1: Creating registry and adapter...")
        registry = ProtocolProviderRegistry()
        adapter = PoolingAdapter(registry=registry)
        
        print("🔍 Step 2: Starting adapter...")
        await adapter.start()
        
        print("🔍 Step 3: Registering provider...")
        await adapter.register_provider(
            protocol_id="debug/v1",
            provider_class=DebugProvider,
            provider_config={"provider_id": "debug-test"},
            min_workers=1, max_workers=1
        )
        print("🔍 Step 3: Provider registered")
        
        print("🔍 Step 4: Creating task...")
        task = Task(
            id=f"debug-{uuid.uuid4().hex[:6]}",
            name="Debug Test",
            method="test",
            protocol="debug/v1", 
            params={"test": "value"},
            priority=Priority.HIGH
        )
        print(f"🔍 Step 4: Task created: {task.id}")
        
        print("🔍 Step 5: Executing task (this is where it might hang)...")
        
        # Add timeout to prevent infinite hang
        try:
            task_result = await asyncio.wait_for(
                adapter.execute_task(task),
                timeout=10.0  # 10 second timeout
            )
            print(f"🔍 Step 5: Task completed!")
            print(f"🔍   Status: {task_result.status}")
            print(f"🔍   Result: {task_result.result}")
            return True
            
        except asyncio.TimeoutError:
            print("🔍 Step 5: TIMEOUT! execute_task() is hanging")
            print("🔍   This tells us where the issue is")
            return False
            
    except Exception as e:
        print(f"🔍 EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        print("🔍 Cleanup: Stopping adapter...")
        if 'adapter' in locals():
            await adapter.stop()
        print("🔍 Cleanup: Done")

if __name__ == "__main__":
    success = asyncio.run(debug_pooling_hang())
    print(f"\n{'🎉 POOLING WORKS' if success else '❌ POOLING HANGS'}")
    exit(0 if success else 1)