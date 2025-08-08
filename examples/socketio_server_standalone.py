#!/usr/bin/env python3
"""
Standalone Socket.IO server for Gleitzeit Cluster

This runs the Socket.IO server independently for real-time coordination
between cluster components.

Requirements:
- Redis server running on localhost:6379
- Available ports: 8000 (default)

Usage:
    python examples/socketio_server_standalone.py
    python examples/socketio_server_standalone.py --port 8080
"""

import asyncio
import argparse
import signal
import sys
from pathlib import Path

# Add package to path for import
sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster.communication.socketio_server import SocketIOServer


class GracefulServer:
    """Wrapper for graceful server shutdown"""
    
    def __init__(self, server: SocketIOServer):
        self.server = server
        self.shutdown_event = asyncio.Event()
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        print(f"\n🔄 Received signal {signum}, shutting down gracefully...")
        self.shutdown_event.set()
    
    async def run(self):
        """Run server with graceful shutdown"""
        # Setup signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        try:
            # Start server
            await self.server.start()
            
            print("🎯 Server ready for connections!")
            print("   Endpoints:")
            print(f"   • Socket.IO: ws://{self.server.host}:{self.server.port}/socket.io/")
            print(f"   • Health:    http://{self.server.host}:{self.server.port}/health")
            print(f"   • Metrics:   http://{self.server.host}:{self.server.port}/metrics")
            print("\n💡 Press Ctrl+C to stop")
            
            # Wait for shutdown signal
            await self.shutdown_event.wait()
            
        except KeyboardInterrupt:
            print("\n🔄 Keyboard interrupt received")
        except Exception as e:
            print(f"\n❌ Server error: {e}")
        finally:
            # Stop server
            await self.server.stop()
            print("👋 Server stopped gracefully")


async def main():
    """Main server entry point"""
    parser = argparse.ArgumentParser(description="Gleitzeit Cluster Socket.IO Server")
    parser.add_argument("--host", default="0.0.0.0", help="Server host address")
    parser.add_argument("--port", type=int, default=8000, help="Server port")
    parser.add_argument("--redis-url", default="redis://localhost:6379", 
                       help="Redis connection URL")
    parser.add_argument("--cors", default="*", 
                       help="CORS allowed origins (comma-separated or *)")
    parser.add_argument("--auth", action="store_true", 
                       help="Enable authentication")
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug logging")
    
    args = parser.parse_args()
    
    print("🚀 Starting Gleitzeit Cluster Socket.IO Server")
    print("=" * 50)
    print(f"   Host: {args.host}")
    print(f"   Port: {args.port}")
    print(f"   Redis: {args.redis_url}")
    print(f"   CORS: {args.cors}")
    print(f"   Auth: {'Enabled' if args.auth else 'Disabled'}")
    print()
    
    # Create server
    server = SocketIOServer(
        host=args.host,
        port=args.port,
        redis_url=args.redis_url,
        cors_allowed_origins=args.cors,
        auth_enabled=args.auth
    )
    
    # Run with graceful shutdown
    graceful_server = GracefulServer(server)
    await graceful_server.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"\n💥 Fatal error: {e}")
        sys.exit(1)