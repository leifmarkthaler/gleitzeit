#!/usr/bin/env python3
"""
Start the Gleitzeit V3 Central Server

This script starts the central Socket.IO server that coordinates
providers and workflow engines.
"""

import asyncio
import logging
import sys
from gleitzeit_v3.server.central_server import CentralServer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

async def main():
    """Start the central server"""
    try:
        # Create and start server
        server = CentralServer(host="localhost", port=8000)
        logger.info("Starting Gleitzeit V3 Central Server...")
        logger.info("Press Ctrl+C to stop")
        
        await server.start()
        
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())