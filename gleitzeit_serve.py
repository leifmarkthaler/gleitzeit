#!/usr/bin/env python3
"""
Gleitzeit Serve - Complete cluster service with Ollama integration
"""

import asyncio
import sys
import os
import signal
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from gleitzeit_socketio_service import GleitzeitSocketIOService
from my_local_llm_provider import OllamaProvider

async def main():
    """Start Gleitzeit with all services including Ollama provider"""
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Get configuration from environment or defaults
    host = os.getenv('GLEITZEIT_HOST', '0.0.0.0')
    port = int(os.getenv('GLEITZEIT_PORT', '8000'))
    redis_url = os.getenv('GLEITZEIT_REDIS_URL', 'redis://localhost:6379')
    ollama_url = os.getenv('OLLAMA_URL', 'http://localhost:11434')
    
    print("🚀 Starting Gleitzeit Cluster with Ollama Integration")
    print("=" * 50)
    print(f"   Host: {host}")
    print(f"   Port: {port}")
    print(f"   Redis: {redis_url}")
    print(f"   Ollama: {ollama_url}")
    print()
    
    # Create the central Socket.IO service
    service = GleitzeitSocketIOService(
        host=host,
        port=port,
        redis_url=redis_url
    )
    
    # Setup signal handlers for graceful shutdown
    def signal_handler():
        print("\nReceived shutdown signal")
        asyncio.create_task(shutdown(service, ollama_provider))
    
    if sys.platform != 'win32':
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, signal_handler)
    
    try:
        # Start the central service
        await service.start()
        
        # Wait a bit for service to stabilize
        await asyncio.sleep(2)
        
        # Start Ollama provider
        print("\n📦 Starting Ollama Provider...")
        ollama_provider = OllamaProvider(
            ollama_url=ollama_url,
            server_url=f"http://localhost:{port}"  # SocketIOProviderClient expects server_url
        )
        
        # Run provider in background
        provider_task = asyncio.create_task(ollama_provider.run())
        
        # Wait for provider to register
        await asyncio.sleep(2)
        print("✅ Ollama provider connected and running")
        
        print("\n" + "=" * 50)
        print("✅ All services started successfully!")
        print("\nAvailable at:")
        print(f"   Socket.IO: http://localhost:{port}")
        print(f"   Namespace: /cluster")
        print(f"   Providers: /providers")
        print("\nOllama models available for LLM tasks")
        print("\nPress Ctrl+C to stop all services")
        print("=" * 50)
        
        # Wait for shutdown
        await service.wait_for_shutdown()
        
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        if 'provider_task' in locals():
            provider_task.cancel()
            try:
                await provider_task
            except asyncio.CancelledError:
                pass
        await service.stop()

async def shutdown(service, provider):
    """Graceful shutdown"""
    try:
        if provider:
            await provider.disconnect()
    except:
        pass
    await service.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)