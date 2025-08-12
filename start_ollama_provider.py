#!/usr/bin/env python3
"""
Start Ollama Provider for Gleitzeit
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from my_local_llm_provider import OllamaProvider

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def main():
    """Run the Ollama provider"""
    print("🚀 Starting Ollama Provider")
    print("=" * 50)
    
    # Create and run Ollama provider
    provider = OllamaProvider(
        ollama_url="http://localhost:11434",
        server_url="http://localhost:8000"
    )
    
    print(f"Provider: {provider.name}")
    print(f"Models: {len(provider.models)} available")
    print(f"Connecting to: {provider.server_url}")
    print()
    
    try:
        await provider.run()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())