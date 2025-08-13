#!/usr/bin/env python3
"""
Gleitzeit Central Socket.IO Service

This is the central Socket.IO server that all Gleitzeit components connect to.
It should be started once and kept running, similar to Redis or a database.

Usage:
    python gleitzeit_socketio_service.py
    
Environment Variables:
    GLEITZEIT_SOCKETIO_HOST - Server host (default: 0.0.0.0)
    GLEITZEIT_SOCKETIO_PORT - Server port (default: 8000) 
    GLEITZEIT_REDIS_URL - Redis URL for persistence
    GLEITZEIT_LOG_LEVEL - Log level (default: INFO)
"""

import asyncio
import os
import signal
import sys
from pathlib import Path
import logging

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

from gleitzeit_cluster.communication.socketio_server import SocketIOServer
from gleitzeit_cluster.communication.service_discovery import register_socketio_service
from gleitzeit_extensions.socketio_provider_manager import SocketIOProviderManager
from gleitzeit_cluster.core.cluster import GleitzeitCluster

# Configure logging
log_level = os.getenv('GLEITZEIT_LOG_LEVEL', 'INFO')
logging.basicConfig(
    level=getattr(logging, log_level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class GleitzeitSocketIOService:
    """
    Central Socket.IO service for Gleitzeit
    
    This is the single source of truth for Socket.IO coordination.
    All other components connect to this service.
    """
    
    def __init__(
        self,
        host: str = None,
        port: int = None,
        redis_url: str = None
    ):
        """
        Initialize the central Socket.IO service
        
        Args:
            host: Server host (default from env or 0.0.0.0)
            port: Server port (default from env or 8000)
            redis_url: Redis URL (default from env or redis://localhost:6379)
        """
        self.host = host or os.getenv('GLEITZEIT_SOCKETIO_HOST', '0.0.0.0')
        self.port = int(port or os.getenv('GLEITZEIT_SOCKETIO_PORT', '8000'))
        self.redis_url = redis_url or os.getenv('GLEITZEIT_REDIS_URL', 'redis://localhost:6379')
        
        # Create full Gleitzeit cluster with execution capabilities
        self.cluster = GleitzeitCluster(
            redis_url=self.redis_url,
            socketio_url=f"http://{self.host}:{self.port}",
            socketio_host=self.host,
            socketio_port=self.port,
            enable_redis=True,
            enable_socketio=True,
            enable_real_execution=True,  # Enable workflow execution
            auto_start_services=False,   # Disable auto-start services
            auto_start_python_executor=False,  # Don't start Python executor
            auto_start_internal_llm_service=False,  # Don't start internal LLM service
            auto_start_providers=False,  # Don't auto-start providers
            auto_recovery=True
        )
        
        # Service state
        self.running = False
        self._shutdown_event = asyncio.Event()
        
        logger.info(f"Gleitzeit Socket.IO Service initialized")
        logger.info(f"  Host: {self.host}")
        logger.info(f"  Port: {self.port}")
        logger.info(f"  Redis: {self.redis_url}")
    
    async def start(self):
        """Start the Socket.IO service"""
        if self.running:
            logger.warning("Service is already running")
            return
        
        logger.info("🚀 Starting Gleitzeit Socket.IO Service")
        
        try:
            # Start the full cluster (includes Socket.IO server and execution)
            await self.cluster.start()
            self.running = True
            
            # Register service for discovery
            register_socketio_service(
                self.get_url(),
                {
                    'namespaces': ['/cluster', '/providers'],
                    'provider_manager': True,
                    'started_at': asyncio.get_event_loop().time()
                }
            )
            
            logger.info("✅ Gleitzeit Socket.IO Service is running")
            logger.info(f"   Server URL: http://{self.host}:{self.port}")
            logger.info(f"   Cluster namespace: /cluster")  
            logger.info(f"   Provider namespace: /providers")
            logger.info("")
            logger.info("Components can now connect:")
            logger.info(f"   Cluster: GleitzeitCluster(socketio_url='http://localhost:{self.port}')")
            logger.info(f"   Providers: connect to http://localhost:{self.port}")
            logger.info(f"   CLI: --socketio-url http://localhost:{self.port}")
            logger.info("")
            logger.info("Press Ctrl+C to stop")
            
        except Exception as e:
            logger.error(f"Failed to start service: {e}")
            raise
    
    async def stop(self):
        """Stop the Socket.IO service"""
        if not self.running:
            return
        
        logger.info("🛑 Stopping Gleitzeit Socket.IO Service")
        
        try:
            await self.cluster.stop()
            self.running = False
            self._shutdown_event.set()
            logger.info("✅ Gleitzeit Socket.IO Service stopped")
            
        except Exception as e:
            logger.error(f"Error stopping service: {e}")
    
    async def wait_for_shutdown(self):
        """Wait for shutdown signal"""
        await self._shutdown_event.wait()
    
    def get_url(self) -> str:
        """Get the service URL"""
        return f"http://{self.host}:{self.port}"
    
    def get_connection_info(self) -> dict:
        """Get connection information for clients"""
        return {
            'url': self.get_url(),
            'host': self.host,
            'port': self.port,
            'namespaces': ['/cluster', '/providers'],
            'running': self.running
        }


async def main():
    """Main entry point"""
    
    # Create service
    service = GleitzeitSocketIOService()
    
    # Setup signal handlers for graceful shutdown
    def signal_handler():
        logger.info("Received shutdown signal")
        asyncio.create_task(service.stop())
    
    # Register signal handlers
    if sys.platform != 'win32':
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, signal_handler)
    
    try:
        # Start the service
        await service.start()
        
        # Wait for shutdown
        await service.wait_for_shutdown()
        
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        await service.stop()
    except Exception as e:
        logger.error(f"Service error: {e}")
        await service.stop()
        sys.exit(1)


if __name__ == "__main__":
    # Print banner
    print("🌐 Gleitzeit Socket.IO Service")
    print("=" * 50)
    print("Central Socket.IO server for Gleitzeit cluster coordination")
    print("")
    
    # Run the service
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)