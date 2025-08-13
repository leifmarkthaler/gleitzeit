#!/usr/bin/env python3
"""
Start Gleitzeit with Configuration-Based Providers

This example shows how to automatically start providers from a config file
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

from gleitzeit_cluster.core.cluster import GleitzeitCluster
from gleitzeit_extensions.socketio_provider_manager import SocketIOProviderManager
from gleitzeit_extensions.provider_config import get_provider_manager, start_configured_providers
from gleitzeit_cluster.communication.socketio_server import SocketIOServer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def start_gleitzeit_with_config():
    """Start Gleitzeit cluster with config-based providers"""
    
    print("🚀 Starting Gleitzeit with Configuration-Based Providers")
    print("=" * 60)
    
    # 1. Load provider configuration
    print("1. Loading provider configuration...")
    try:
        provider_manager_config = get_provider_manager("config/providers.yaml")
        enabled_providers = provider_manager_config.get_enabled_providers()
        print(f"   Found {len(enabled_providers)} enabled providers:")
        for provider_config in enabled_providers:
            print(f"   - {provider_config.name}: {provider_config.description}")
    except Exception as e:
        print(f"   ❌ Failed to load config: {e}")
        return
    
    # 2. Start Socket.IO server with provider manager
    print("\n2. Starting Socket.IO server...")
    server = SocketIOServer(
        host="0.0.0.0", 
        port=8000,
        cors_allowed_origins="*"
    )
    
    # Create and attach provider manager
    socketio_provider_manager = SocketIOProviderManager()
    socketio_provider_manager.attach_to_server(server.sio)
    
    # Start server
    await server.start()
    
    # Start health monitoring
    health_task = asyncio.create_task(socketio_provider_manager.monitor_health())
    
    try:
        # 3. Start configured providers
        print("\n3. Starting configured providers...")
        started_providers = await start_configured_providers("config/providers.yaml")
        
        if started_providers:
            print(f"   ✅ Started {len(started_providers)} providers:")
            for name, provider in started_providers.items():
                print(f"   - {name}: {provider.__class__.__name__}")
        else:
            print("   ❌ No providers started")
        
        # Wait for providers to connect
        await asyncio.sleep(3)
        
        # 4. Create and start Gleitzeit cluster
        print("\n4. Starting Gleitzeit cluster...")
        cluster = GleitzeitCluster(enable_real_execution=False)
        cluster.set_socketio_provider_manager(socketio_provider_manager)
        
        # Start cluster (this will use existing server)
        try:
            await cluster.start()
            print("   ✅ Cluster started successfully")
        except Exception as e:
            if "address already in use" in str(e):
                print("   ✅ Cluster connected to existing server")
            else:
                raise
        
        # 5. Test the integration
        print("\n5. Testing provider integration...")
        
        # Check available models
        available_models = await cluster.get_available_extension_models()
        print(f"   Available models: {list(available_models.keys())}")
        
        # Test model routing
        if available_models:
            test_model = list(available_models.keys())[0]
            provider = await cluster.find_provider_for_model(test_model)
            print(f"   Model '{test_model}' routes to provider: {provider}")
        
        # 6. Example workflow
        if available_models:
            print("\n6. Running example workflow...")
            
            workflow = cluster.create_workflow("config_test_workflow")
            
            # Use the first available model
            test_model = list(available_models.keys())[0]
            provider_name = await cluster.find_provider_for_model(test_model)
            
            task = workflow.add_llm_task(
                name="test_task",
                prompt="What is 2+2? Answer in one sentence.",
                model=test_model,
                provider=provider_name
            )
            
            print(f"   Created workflow with task using {test_model}")
            
            # Execute workflow
            result = await cluster.execute_workflow(workflow)
            print(f"   Workflow result: {result.status}")
            
            if result.results and task.id in result.results:
                print(f"   Task result: {result.results[task.id]}")
        
        print(f"\n🎉 Gleitzeit is running with {len(started_providers)} configured providers!")
        print("🔧 Configuration file: config/providers.yaml")
        print("📡 Socket.IO server: http://localhost:8000")
        print("💡 Use 'gleitzeit providers list' to see active providers")
        print("\nPress Ctrl+C to stop...")
        
        # Keep running
        await asyncio.Event().wait()
        
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        
    finally:
        # Cleanup
        print("🧹 Cleaning up...")
        
        # Stop configured providers
        try:
            from gleitzeit_extensions.provider_config import stop_configured_providers
            await stop_configured_providers()
            print("   ✅ Providers stopped")
        except Exception as e:
            print(f"   ❌ Error stopping providers: {e}")
        
        # Stop health monitoring
        health_task.cancel()
        
        # Stop server
        await server.stop()
        print("   ✅ Server stopped")
        
        print("👋 Goodbye!")

async def main():
    """Main entry point"""
    try:
        await start_gleitzeit_with_config()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())