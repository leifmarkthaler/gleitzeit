#!/usr/bin/env python3
"""Start server with debug logging for event persistence."""

import asyncio
import sys
import os
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

async def start_server():
    """Start server with event persistence."""
    os.environ["GLEITZEIT_PERSIST_EVENTS"] = "true"
    
    from gleitzeit.api.main import app, app_state
    import uvicorn
    
    print("\n" + "="*60)
    print("STARTING SERVER WITH EVENT PERSISTENCE")
    print("="*60)
    
    # Start server
    config = uvicorn.Config(app=app, host="localhost", port=8000, log_level="info")
    server = uvicorn.Server(config)
    
    # Run server
    await server.serve()

if __name__ == "__main__":
    asyncio.run(start_server())