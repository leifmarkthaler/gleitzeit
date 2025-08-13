#!/usr/bin/env python3
"""
Simple Non-LLM Debug

Just test if the pooling adapter can handle non-LLM providers at all.
"""

import asyncio
import sys
from pathlib import Path
from typing import Dict, Any

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from gleitzeit_v4.pooling.adapter import PoolingAdapter
from gleitzeit_v4.registry import ProtocolProviderRegistry
from gleitzeit_v4.providers.base import ProtocolProvider
import logging

logging.basicConfig(level=logging.INFO)

class SimpleProvider(ProtocolProvider):
    def __init__(self, provider_id: str, **kwargs):
        super().__init__(provider_id=provider_id, protocol_id="test/v1")
    
    async def initialize(self):
        print(f"Init: {self.provider_id}")
    
    async def shutdown(self):
        print(f"Shutdown: {self.provider_id}")
    
    async def health_check(self):
        return True
    
    def get_supported_methods(self):
        return ["test"]
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        print(f"Handling: {method}")
        return {"message": "hello", "method": method}

async def main():
    print("Testing pooling adapter with simple provider...")
    
    try:
        registry = ProtocolProviderRegistry()
        adapter = PoolingAdapter(registry=registry)
        await adapter.start()
        
        print("Registering provider...")
        await adapter.register_provider(
            protocol_id="test/v1",
            provider_class=SimpleProvider,
            provider_config={"provider_id": "test"},
            min_workers=1, max_workers=1
        )
        print("Provider registered!")
        
        await adapter.stop()
        print("Success!")
        return True
        
    except Exception as e:
        print(f"Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)