"""
Hybrid Extension + MCP Demo

This example demonstrates the unified approach combining both native Gleitzeit 
extensions and MCP (Model Context Protocol) servers in a single system.
"""

import asyncio
import os
from pathlib import Path

from gleitzeit_extensions import (
    UnifiedProviderManager, 
    create_unified_manager,
    setup_standard_llm_providers,
    is_mcp_available
)
from gleitzeit_cluster.core.cluster import GleitzeitCluster


async def basic_unified_demo():
    """Basic demonstration of unified provider management"""
    print("🔧 Unified Provider Manager Demo")
    print("=" * 40)
    
    # Create unified manager
    manager = create_unified_manager()
    
    print(f"MCP Available: {is_mcp_available()}")
    
    # Discover native extensions
    print("\n📦 Discovering native extensions...")
    extensions = manager.discover_extensions(["examples/extensions"])
    print(f"Found native extensions: {extensions}")
    
    # Set up standard LLM providers via MCP (if available)
    print("\n📡 Setting up MCP servers...")
    if is_mcp_available():
        setup_standard_llm_providers(manager)
        
        # Add custom MCP server configuration
        manager.add_mcp_server(
            name="custom-llm",
            command="python",
            args=["examples/custom_mcp_server.py"],
            models=["custom-model-1", "custom-model-2"],
            capabilities=["text", "custom_processing"],
            description="Custom MCP server example"
        )
    else:
        print("⚠️ MCP not available, skipping MCP server setup")
    
    # Show all discovered providers
    print("\n🌐 All Available Providers:")
    providers = manager.get_all_providers()
    for name, provider in providers.items():
        status = "🟢 connected" if provider.connected else "⚫ available"
        print(f"  - {name} ({provider.type}) - {status}")
        print(f"    {provider.description}")
        print(f"    Models: {', '.join(provider.models) if provider.models else 'none'}")
        print(f"    Capabilities: {', '.join(provider.capabilities)}")
        print()
    
    # Model routing examples
    print("🎯 Model Routing Examples:")
    models_to_test = ["gpt-4", "claude-3-opus", "llama3", "custom-model-1"]
    for model in models_to_test:
        provider_info = manager.find_provider_for_model(model)
        if provider_info:
            print(f"  {model} → {provider_info['name']} ({provider_info['type']})")
        else:
            print(f"  {model} → No provider found")
    
    # Capability-based discovery
    print("\n🔍 Providers by Capability:")
    capabilities_to_test = ["text", "vision", "streaming", "function_calling"]
    for capability in capabilities_to_test:
        providers_list = manager.find_providers_by_capability(capability)
        provider_names = [p['name'] for p in providers_list]
        print(f"  {capability}: {', '.join(provider_names) if provider_names else 'none'}")
    
    print("\n✅ Basic unified demo completed")


async def integrated_cluster_demo():
    """Demonstration with integrated cluster"""
    print("\n🚀 Integrated Cluster with Unified Providers")
    print("=" * 40)
    
    # Create cluster
    cluster = GleitzeitCluster(
        enable_real_execution=False,
        auto_start_services=False
    )
    
    # Create unified provider manager
    manager = create_unified_manager()
    
    # Attach to cluster
    cluster.set_unified_provider_manager(manager)
    
    # Discover and set up providers
    manager.discover_extensions(["examples/extensions"])
    
    if is_mcp_available():
        setup_standard_llm_providers(manager)
    
    print(f"\nCluster provider manager: {type(cluster.get_unified_provider_manager())}")
    
    # Test model routing through cluster
    print("\n🎯 Model Routing via Cluster:")
    models_to_test = ["gpt-4", "claude-3-opus", "openai-model"]
    
    for model in models_to_test:
        try:
            provider = await cluster.find_provider_for_model(model)
            print(f"  {model} → {provider}")
        except Exception as e:
            print(f"  {model} → Error: {e}")
    
    # Get available models through cluster
    try:
        available_models = await cluster.get_available_extension_models()
        print(f"\n📋 Available Models via Cluster: {len(available_models)}")
        for model_name, model_info in list(available_models.items())[:5]:  # Show first 5
            print(f"  - {model_name} (via {model_info.get('provider', 'unknown')})")
        if len(available_models) > 5:
            print(f"  ... and {len(available_models) - 5} more")
    except Exception as e:
        print(f"Error getting available models: {e}")
    
    print("\n✅ Integrated cluster demo completed")


async def mcp_configuration_demo():
    """Demonstrate MCP server configuration options"""
    print("\n📡 MCP Configuration Demo")
    print("=" * 40)
    
    if not is_mcp_available():
        print("⚠️ MCP not available, skipping MCP configuration demo")
        return
    
    manager = create_unified_manager()
    
    # Method 1: Programmatic configuration
    print("📝 Method 1: Programmatic Configuration")
    manager.add_mcp_server(
        name="programmatic-openai",
        command="mcp-server-openai",
        env={"OPENAI_API_KEY": "demo-key"},
        models=["gpt-4", "gpt-3.5-turbo"],
        capabilities=["text", "vision"],
        description="OpenAI configured programmatically"
    )
    
    # Method 2: Configuration file
    print("📝 Method 2: Configuration from File")
    config_file = Path("examples/mcp_servers.json")
    if config_file.exists():
        try:
            manager.load_mcp_servers_from_file(str(config_file))
            print(f"✅ Loaded MCP servers from {config_file}")
        except Exception as e:
            print(f"❌ Failed to load MCP config: {e}")
    else:
        print(f"⚠️ Configuration file not found: {config_file}")
    
    # Show configured servers
    if manager.mcp_manager:
        print(f"\n📊 Configured MCP Servers: {len(manager.mcp_manager.servers)}")
        for name, config in manager.mcp_manager.servers.items():
            print(f"  - {name}: {config.command}")
            print(f"    Models: {', '.join(config.models) if config.models else 'none'}")
            print(f"    Description: {config.description}")
        
        # Get summary
        summary = manager.mcp_manager.get_summary()
        print(f"\n📈 MCP Summary:")
        print(f"  Total servers: {summary['total_servers']}")
        print(f"  Connected servers: {summary['connected_servers']}")
        print(f"  Available models: {summary['available_models']}")
    
    print("\n✅ MCP configuration demo completed")


async def lifecycle_demo():
    """Demonstrate provider lifecycle management"""
    print("\n🔄 Provider Lifecycle Demo")
    print("=" * 40)
    
    manager = create_unified_manager()
    
    # Set up providers
    manager.discover_extensions(["examples/extensions"])
    if is_mcp_available():
        setup_standard_llm_providers(manager)
    
    print("🚀 Starting all providers...")
    try:
        # This will attempt to start extensions and connect MCP servers
        results = await manager.start_all_providers()
        
        print("📊 Startup Results:")
        for provider_name, success in results.items():
            status = "✅ started" if success else "❌ failed"
            print(f"  - {provider_name}: {status}")
        
        # Show running providers
        providers = manager.get_all_providers()
        running_count = sum(1 for p in providers.values() if p.connected)
        print(f"\n🏃 Running providers: {running_count}/{len(providers)}")
        
        # Wait a moment
        await asyncio.sleep(1)
        
    except Exception as e:
        print(f"❌ Error during startup: {e}")
    
    finally:
        print("\n🛑 Stopping all providers...")
        try:
            await manager.stop_all_providers()
            print("✅ All providers stopped")
        except Exception as e:
            print(f"⚠️ Error during shutdown: {e}")
    
    print("\n✅ Lifecycle demo completed")


async def comparison_demo():
    """Compare native extensions vs MCP servers"""
    print("\n⚖️  Native Extensions vs MCP Servers Comparison")
    print("=" * 40)
    
    manager = create_unified_manager()
    manager.discover_extensions(["examples/extensions"])
    
    if is_mcp_available():
        setup_standard_llm_providers(manager)
    
    providers = manager.get_all_providers()
    
    native_extensions = [p for p in providers.values() if p.type == "extension"]
    mcp_servers = [p for p in providers.values() if p.type == "mcp"]
    
    print(f"📦 Native Extensions ({len(native_extensions)}):")
    for ext in native_extensions:
        print(f"  - {ext.name}: {ext.description}")
        print(f"    Models: {', '.join(ext.models) if ext.models else 'none'}")
        print(f"    Pros: Direct Python integration, fast, shared state")
        print(f"    Cons: Same process, language-specific")
        print()
    
    print(f"📡 MCP Servers ({len(mcp_servers)}):")  
    for server in mcp_servers:
        print(f"  - {server.name}: {server.description}")
        print(f"    Models: {', '.join(server.models) if server.models else 'none'}")
        print(f"    Pros: Process isolation, language agnostic, standard protocol")
        print(f"    Cons: IPC overhead, more complex setup")
        print()
    
    print("💡 Best Practices:")
    print("  - Use MCP for: LLM providers, external tools, standard integrations")
    print("  - Use Native Extensions for: Gleitzeit-specific logic, performance-critical code")
    print("  - Unified Manager provides seamless access to both")
    
    print("\n✅ Comparison demo completed")


async def main():
    """Run all hybrid demos"""
    print("🎯 Gleitzeit Hybrid Extension + MCP Demo")
    print("=" * 50)
    
    try:
        await basic_unified_demo()
        await integrated_cluster_demo() 
        await mcp_configuration_demo()
        await lifecycle_demo()
        await comparison_demo()
        
        print("\n🎉 All hybrid demos completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())