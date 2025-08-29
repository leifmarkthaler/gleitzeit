#!/usr/bin/env python3
"""Start Gleitzeit API server with event persistence enabled."""

import asyncio
import uvicorn
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from gleitzeit.api.main import app, app_state

async def start_with_events():
    """Start the server with event persistence enabled."""
    print("Starting Gleitzeit API server with event persistence...")
    
    # Configure the app state with event persistence
    app_state.config = {
        'persist_events': True,
        'persistence_type': 'memory'
    }
    
    # Run the server
    config = uvicorn.Config(
        app=app,
        host="localhost", 
        port=8000,
        log_level="info"
    )
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(start_with_events())