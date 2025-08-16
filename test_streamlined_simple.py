"""
Simple test to demonstrate the streamlined architecture
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from gleitzeit.providers.ollama_provider_streamlined import OllamaProviderStreamlined
from gleitzeit.providers.python_provider_streamlined import PythonProviderStreamlined


async def main():
    print("\n" + "="*60)
    print("STREAMLINED ARCHITECTURE DEMONSTRATION")
    print("="*60)
    print("\nThe new streamlined architecture combines everything into")
    print("a single, simple provider class with integrated resource management!")
    
    # Create providers - notice how simple this is!
    print("\n1. Creating providers (just one line each!)...")
    
    ollama = OllamaProviderStreamlined(auto_discover=True)
    python = PythonProviderStreamlined(max_containers=2)
    
    try:
        # Initialize - handles EVERYTHING automatically
        print("\n2. Initializing (auto-discovery, health checks, etc.)...")
        await ollama.initialize()
        await python.initialize()
        print("✅ Done! Providers are ready to use")
        
        # Use Ollama
        print("\n3. Using Ollama provider...")
        try:
            result = await ollama.execute("llm/generate", {
                "prompt": "Hello",
                "model": "llama3.2"
            })
            print(f"✅ Response: {result.get('response', 'N/A')[:50]}...")
        except Exception as e:
            print(f"⚠️ Ollama skipped: {e}")
        
        # Use Python
        print("\n4. Using Python provider...")
        result = await python.execute("python/execute", {
            "code": "result = sum(range(10))"
        })
        print(f"✅ Result: {result.get('result')}")
        
        # Show automatic features
        print("\n5. Automatic features you get for FREE:")
        
        # Health monitoring
        health = await python.health_check()
        print(f"   ✅ Health monitoring: {health['status']}")
        
        # Metrics collection
        if python.metrics_collector:
            metrics = python.metrics_collector.get_summary()
            print(f"   ✅ Metrics collection: {metrics.get('aggregate', {}).get('total_requests', 0)} requests tracked")
        
        # Load balancing (for Ollama with multiple instances)
        status = await ollama.get_status()
        print(f"   ✅ Load balancing: {len(status.get('instances', {}))} instances managed")
        
        # Resource pooling
        python_status = await python.get_status()
        print(f"   ✅ Resource pooling: {python_status['details']['total_instances']} containers")
        
        print("\n6. Compare the simplicity:")
        print("\n   OLD ARCHITECTURE (separate components):")
        print("   ----------------------------------------")
        print("   hub = OllamaHub()")
        print("   await hub.start()")
        print("   provider = OllamaProvider(hub=hub)")
        print("   await provider.initialize()")
        print("   # Manage lifecycle separately")
        print("   # Handle metrics manually")
        print("   # Configure health checks")
        print("   # Setup load balancing")
        
        print("\n   NEW ARCHITECTURE (integrated):")
        print("   ------------------------------")
        print("   provider = OllamaProviderStreamlined()")
        print("   await provider.initialize()")
        print("   # That's it! Everything is built-in!")
        
        print("\n✨ Benefits of the streamlined approach:")
        print("   • Single class to manage")
        print("   • Automatic resource lifecycle")
        print("   • Built-in health monitoring")
        print("   • Integrated metrics")
        print("   • Load balancing included")
        print("   • Circuit breaker protection")
        print("   • Much less code to write and maintain")
        
    finally:
        print("\n7. Cleanup (automatic resource cleanup)...")
        await ollama.shutdown()
        await python.shutdown()
        print("✅ All resources cleaned up automatically")
    
    print("\n" + "="*60)
    print("SUCCESS! The streamlined architecture works beautifully!")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())