#!/usr/bin/env python
"""Debug agent protocol registration"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.core.protocol import ProtocolSpec, MethodSpec, ParameterSpec, ParameterType
from gleitzeit.hub.resource_manager import ResourceManager
from gleitzeit.providers.agent_provider import AgentProvider


async def test_registration():
    """Test agent protocol registration"""
    
    print("=== Testing Agent Protocol Registration ===\n")
    
    # Create registry
    registry = ProtocolProviderRegistry()
    print("✓ Created registry")
    
    # Create agent protocol
    agent_protocol = ProtocolSpec(
        protocol_id="agent/v1",
        name="agent-protocol",
        version="v1.0",
        description="Protocol for agent-based task execution",
        methods={
            "chat": MethodSpec(
                name="chat",
                description="Chat with context",
                parameters={
                    "message": ParameterSpec(type=ParameterType.STRING, required=True),
                    "session_id": ParameterSpec(type=ParameterType.STRING, required=False),
                }
            ),
        }
    )
    print(f"✓ Created protocol spec: {agent_protocol.protocol_id}")
    
    # Register protocol
    try:
        registry.register_protocol(agent_protocol)
        print("✓ Registered protocol")
    except Exception as e:
        print(f"✗ Failed to register protocol: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Check if protocol is registered
    protocols = registry.protocol_registry.protocols
    print(f"\nRegistered protocols: {list(protocols.keys())}")
    
    # Create resource manager and agent hub
    resource_manager = ResourceManager("test-manager")
    await resource_manager.start()
    print("✓ Resource manager started")
    
    agent_hub = await resource_manager.create_agent_hub(max_agents=5)
    print("✓ Agent hub created")
    
    # Create and register agent provider
    agent_provider = AgentProvider(agent_hub)
    registry.register_provider("agent", "agent/v1", agent_provider)
    print("✓ Agent provider registered")
    
    # Check provider registration
    print(f"\nProvider instances: {list(registry.provider_instances.keys())}")
    print(f"Protocol providers: {registry.protocol_providers}")
    
    # Test getting provider
    provider = await registry.get_provider_for_method("agent/v1", "chat")
    if provider:
        print(f"✓ Got provider for agent/v1::chat: {provider}")
    else:
        print("✗ Could not get provider for agent/v1::chat")
    
    # Cleanup
    await resource_manager.stop()
    print("\n✓ Test completed")


if __name__ == "__main__":
    asyncio.run(test_registration())