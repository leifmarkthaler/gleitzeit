"""
Extension Usage Demo

This example demonstrates how to use the Gleitzeit extension system
with both decorator-based and config-based extensions.
"""

import asyncio
import os
from gleitzeit_extensions import ExtensionManager
from gleitzeit_extensions.helpers import (
    create_cluster_with_extensions, 
    start_cluster_with_extensions,
    stop_cluster_with_extensions,
    get_available_models,
    create_extension_summary_report
)


async def basic_extension_usage():
    """Basic extension manager usage"""
    print("🔧 Basic Extension Manager Demo")
    print("=" * 40)
    
    # Create extension manager
    manager = ExtensionManager()
    
    # Discover extensions in examples directory
    discovered = manager.discover_extensions(["examples/extensions"])
    print(f"Discovered extensions: {discovered}")
    
    # List available extensions
    available = manager.list_available()
    print(f"Available: {list(available.keys())}")
    
    # Load OpenAI extension (decorator-based) with configuration
    if "openai" in available:
        try:
            openai_ext = manager.load_extension(
                "openai",
                api_key="demo-key",  # In real usage, use environment variable
                timeout=30
            )
            print(f"✅ Loaded OpenAI extension: {type(openai_ext)}")
        except Exception as e:
            print(f"❌ Failed to load OpenAI: {e}")
    
    # Load Claude extension (config-based) with configuration  
    if "claude" in available:
        try:
            claude_ext = manager.load_extension(
                "claude",
                api_key="demo-key",  # In real usage, use environment variable
                timeout=45
            )
            print(f"✅ Loaded Claude extension: {type(claude_ext)}")
        except Exception as e:
            print(f"❌ Failed to load Claude: {e}")
    
    # List loaded extensions
    loaded = manager.list_loaded()
    print(f"Loaded: {list(loaded.keys())}")
    
    # Start extensions
    await manager.start_all_extensions()
    
    # Get extension information
    for name in loaded:
        info = manager.get_extension_info(name)
        print(f"\n📦 {name}:")
        print(f"   Type: {info.get('type')}")
        print(f"   Models: {[m.get('name') for m in info.get('models', [])]}")
        print(f"   Health: {info.get('health', {}).get('healthy', 'Unknown')}")
    
    # Find extension for specific models
    print(f"\nModel routing:")
    print(f"gpt-4 → {manager.find_extension_for_model('gpt-4')}")
    print(f"claude-3-opus → {manager.find_extension_for_model('claude-3-opus')}")
    
    # Get available models
    models = get_available_models(manager)
    print(f"\nAvailable models: {list(models.keys())}")
    
    # Stop extensions
    await manager.stop_all_extensions()
    
    print("\n✅ Basic demo completed\n")


async def integrated_cluster_usage():
    """Using extensions with Gleitzeit cluster"""
    print("🚀 Integrated Cluster Demo")  
    print("=" * 40)
    
    # Create cluster with extensions
    cluster, ext_manager = create_cluster_with_extensions(
        search_paths=["examples/extensions"],
        extensions=["openai", "claude"],  # Load these extensions
        extension_configs={
            "openai": {"api_key": "demo-openai-key", "timeout": 30},
            "claude": {"api_key": "demo-claude-key", "timeout": 60}
        },
        # Cluster configuration
        enable_real_execution=False,  # Safe mode for demo
        auto_start_services=False     # Don't auto-start for demo
    )
    
    # Start cluster and extensions
    await start_cluster_with_extensions(cluster, ext_manager)
    
    # Check extension integration
    extension_models = await cluster.get_available_extension_models()
    print(f"Models available through extensions: {list(extension_models.keys())}")
    
    # Test model routing
    openai_provider = await cluster.find_provider_for_model("gpt-4")
    claude_provider = await cluster.find_provider_for_model("claude-3-opus")
    print(f"gpt-4 provider: {openai_provider}")
    print(f"claude-3-opus provider: {claude_provider}")
    
    # Get extension manager from cluster
    manager = cluster.get_extension_manager()
    print(f"Extension manager via cluster: {type(manager)}")
    
    # Generate extension report
    report = create_extension_summary_report(ext_manager)
    print("\n" + report)
    
    # Stop everything gracefully
    await stop_cluster_with_extensions(cluster, ext_manager)
    
    print("✅ Integrated demo completed\n")


async def environment_configuration_demo():
    """Demo using environment variables for configuration"""
    print("🌍 Environment Configuration Demo")
    print("=" * 40)
    
    # Set up demo environment variables
    os.environ["OPENAI_API_KEY"] = "demo-env-openai-key"
    os.environ["ANTHROPIC_API_KEY"] = "demo-env-claude-key"
    
    try:
        manager = ExtensionManager()
        manager.discover_extensions(["examples/extensions"])
        
        # Load extensions - they will automatically pick up environment variables
        if manager.registry.has_extension("openai"):
            openai_ext = manager.load_extension("openai")  # Uses OPENAI_API_KEY from env
            print("✅ Loaded OpenAI with environment API key")
        
        if manager.registry.has_extension("claude"):
            claude_ext = manager.load_extension("claude")  # Uses ANTHROPIC_API_KEY from env  
            print("✅ Loaded Claude with environment API key")
        
        # Show loaded extensions with their configurations
        for name in manager.list_loaded():
            info = manager.get_extension_info(name)
            print(f"{name}: {info.get('description', 'No description')}")
    
    finally:
        # Clean up environment
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)
    
    print("✅ Environment demo completed\n")


async def dependency_validation_demo():
    """Demo extension dependency validation"""
    print("🔍 Dependency Validation Demo")
    print("=" * 40)
    
    from gleitzeit_extensions.helpers import validate_all_dependencies
    
    manager = ExtensionManager()
    manager.discover_extensions(["examples/extensions"])
    
    # Validate all extension dependencies
    results = validate_all_dependencies(manager)
    
    for ext_name, result in results.items():
        status = "✅" if result['valid'] else "❌"
        print(f"{status} {ext_name}: {result}")
        
        if not result['valid'] and 'missing' in result:
            print(f"   Missing packages: {', '.join(result['missing'])}")
    
    print("\n✅ Dependency validation completed")


async def main():
    """Run all demos"""
    print("🎯 Gleitzeit Extensions Demo")
    print("=" * 50)
    
    try:
        await basic_extension_usage()
        await integrated_cluster_usage() 
        await environment_configuration_demo()
        await dependency_validation_demo()
        
        print("\n🎉 All demos completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())