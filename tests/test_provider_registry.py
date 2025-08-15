#!/usr/bin/env python3
"""
Test Provider Registry and Load Balancing
"""

import asyncio
import sys
import os
from typing import Dict, Any
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from gleitzeit.registry import ProtocolProviderRegistry, ProviderInfo, ProviderStatus
from gleitzeit.core.protocol import ProtocolSpec, MethodSpec, ParameterSpec, ParameterType

class TestProvider:
    """Test provider implementation"""
    
    def __init__(self, provider_id: str):
        self.provider_id = provider_id
        self.call_count = 0
        self.is_healthy = True
        self._initialized = False
    
    def get_supported_methods(self):
        return ["test/echo", "test/ping"]
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Handle incoming request"""
        self.call_count += 1
        if method == "test/echo":
            return {"echo": params.get("message", ""), "provider": self.provider_id}
        elif method == "test/ping":
            return {"pong": True, "provider": self.provider_id}
        else:
            raise ValueError(f"Unknown method: {method}")
    
    async def initialize(self) -> None:
        """Initialize provider"""
        self._initialized = True
    
    async def cleanup(self) -> None:
        """Cleanup provider"""
        self._initialized = False
    
    async def health_check(self) -> Dict[str, Any]:
        """Check health"""
        return {
            "status": "healthy" if self.is_healthy else "unhealthy",
            "provider_id": self.provider_id,
            "initialized": self._initialized
        }

async def test_provider_registration():
    """Test provider registration"""
    registry = ProtocolProviderRegistry()
    
    # First register a protocol
    protocol = ProtocolSpec(
        name="test",
        version="v1",
        methods={
            "test/echo": MethodSpec(
                name="test/echo",
                params_schema={
                    "message": ParameterSpec(type=ParameterType.STRING, required=False)
                }
            ),
            "test/ping": MethodSpec(
                name="test/ping",
                params_schema={}
            )
        }
    )
    registry.register_protocol(protocol)
    
    # Register provider using the registry's method
    provider = TestProvider("test-provider-1")
    registry.register_provider(
        provider_id="test-provider-1",
        protocol_id="test/v1",
        provider_instance=provider,
        supported_methods={"test/echo", "test/ping"}
    )
    
    # Check provider is registered
    providers = registry.get_providers_for_protocol("test/v1")
    assert len(providers) == 1
    assert providers[0].provider_id == "test-provider-1"
    print("✅ Provider registration test passed")

async def test_multiple_providers():
    """Test multiple provider registration"""
    registry = ProtocolProviderRegistry()
    
    # First register a protocol
    protocol = ProtocolSpec(
        name="test",
        version="v1",
        methods={
            "test/echo": MethodSpec(
                name="test/echo",
                params_schema={
                    "message": ParameterSpec(type=ParameterType.STRING, required=False)
                }
            ),
            "test/ping": MethodSpec(
                name="test/ping",
                params_schema={}
            )
        }
    )
    registry.register_protocol(protocol)
    
    # Register multiple providers
    for i in range(1, 4):
        provider = TestProvider(f"provider-{i}")
        registry.register_provider(
            provider_id=f"provider-{i}",
            protocol_id="test/v1",
            provider_instance=provider,
            supported_methods={"test/echo", "test/ping"}
        )
    
    providers = registry.get_providers_for_protocol("test/v1")
    assert len(providers) == 3
    
    # Check all providers are registered
    provider_ids = {p.provider_id for p in providers}
    assert provider_ids == {"provider-1", "provider-2", "provider-3"}
    print("✅ Multiple providers test passed")

async def test_provider_selection():
    """Test provider selection for method"""
    registry = ProtocolProviderRegistry()
    
    # First register a protocol
    protocol = ProtocolSpec(
        name="test",
        version="v1",
        methods={
            "test/echo": MethodSpec(
                name="test/echo",
                params_schema={
                    "message": ParameterSpec(type=ParameterType.STRING, required=False)
                }
            ),
            "test/ping": MethodSpec(
                name="test/ping",
                params_schema={}
            )
        }
    )
    registry.register_protocol(protocol)
    
    # Register providers
    for i in range(1, 3):
        provider = TestProvider(f"provider-{i}")
        registry.register_provider(
            provider_id=f"provider-{i}",
            protocol_id="test/v1",
            provider_instance=provider,
            supported_methods={"test/echo", "test/ping"}
        )
    
    # Get provider for method
    provider = registry.select_provider("test/v1", "test/echo")
    assert provider is not None
    assert provider.provider_id in ["provider-1", "provider-2"]
    
    # Test load balancing - should alternate between providers
    selected_providers = set()
    for _ in range(10):
        provider = registry.select_provider("test/v1", "test/echo")
        if provider:
            selected_providers.add(provider.provider_id)
    
    # Should have selected at least one provider
    assert len(selected_providers) >= 1
    print("✅ Provider selection test passed")

async def test_provider_status():
    """Test provider status management"""
    registry = ProtocolProviderRegistry()
    
    # First register a protocol
    protocol = ProtocolSpec(
        name="test",
        version="v1",
        methods={
            "test/echo": MethodSpec(
                name="test/echo",
                params_schema={
                    "message": ParameterSpec(type=ParameterType.STRING, required=False)
                }
            )
        }
    )
    registry.register_protocol(protocol)
    
    # Register healthy provider
    provider1 = TestProvider("healthy-provider")
    provider1.is_healthy = True
    registry.register_provider(
        provider_id="healthy-provider",
        protocol_id="test/v1",
        provider_instance=provider1,
        supported_methods={"test/echo"}
    )
    
    # Register unhealthy provider
    provider2 = TestProvider("unhealthy-provider")
    provider2.is_healthy = False
    registry.register_provider(
        provider_id="unhealthy-provider",
        protocol_id="test/v1",
        provider_instance=provider2,
        supported_methods={"test/echo"}
    )
    
    # Manually mark the second provider as unhealthy
    registry.providers["unhealthy-provider"].status = ProviderStatus.UNHEALTHY
    
    # Get all providers (without health filtering)
    all_providers = list(registry.providers.values())
    assert len(all_providers) == 2
    
    # Only healthy provider should be selected for method
    provider = registry.select_provider("test/v1", "test/echo")
    assert provider is not None
    assert provider.provider_id == "healthy-provider"
    print("✅ Provider status test passed")

async def main():
    """Run all tests"""
    print("🧪 Testing Provider Registry & Load Balancing")
    print("=" * 50)
    
    try:
        await test_provider_registration()
        await test_multiple_providers()
        await test_provider_selection()
        await test_provider_status()
        
        print("\n✅ All provider registry tests PASSED")
        return 0
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))