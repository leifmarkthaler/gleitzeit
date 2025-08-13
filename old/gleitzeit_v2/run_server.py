"""
Run Gleitzeit V2 Server

Startup script for the Gleitzeit V2 server.
"""

import asyncio
import logging
import argparse
from aiohttp import web

from .core.server import GleitzeitServer, ServerConfig


async def create_app(config: ServerConfig) -> web.Application:
    """Create minimal web application with pure Socket.IO server"""
    
    # Create Gleitzeit server
    gleitzeit_server = GleitzeitServer(config)
    
    # Create minimal web app - just for Socket.IO
    app = web.Application()
    
    # Only add essential health endpoint - no middleware interference
    async def health_handler(request):
        stats = gleitzeit_server.get_stats()
        return web.json_response({
            'status': 'healthy',
            'service': 'gleitzeit_v2',
            'stats': stats
        })
    
    app.router.add_get('/health', health_handler)
    
    # Attach Socket.IO with CORS enabled directly
    gleitzeit_server.sio.attach(app)
    
    # Store server reference for cleanup
    app['gleitzeit_server'] = gleitzeit_server
    
    # Setup lifecycle handlers
    async def start_server(app):
        await gleitzeit_server.start()
        # Set server reference in workflow engine for event broadcasting
        gleitzeit_server.workflow_engine.set_server(gleitzeit_server)
    
    async def stop_server(app):
        await gleitzeit_server.stop()
    
    app.on_startup.append(start_server)
    app.on_cleanup.append(stop_server)
    
    return app


async def main():
    """Main server startup"""
    parser = argparse.ArgumentParser(description="Gleitzeit V2 Server")
    parser.add_argument('--host', default='0.0.0.0', help='Server host')
    parser.add_argument('--port', type=int, default=8000, help='Server port')
    parser.add_argument('--redis-url', default='redis://localhost:6379', help='Redis URL')
    parser.add_argument('--log-level', default='INFO', help='Log level')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose logging')
    
    args = parser.parse_args()
    
    # Setup logging
    log_level = logging.DEBUG if args.verbose else getattr(logging, args.log_level.upper())
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger(__name__)
    
    # Create server config
    config = ServerConfig(
        host=args.host,
        port=args.port,
        redis_url=args.redis_url,
        log_level=args.log_level
    )
    
    logger.info(f"Starting Gleitzeit V2 Server on {args.host}:{args.port}")
    logger.info(f"Redis: {args.redis_url}")
    
    # Create and run app
    app = await create_app(config)
    
    try:
        # Run web server
        runner = web.AppRunner(app)
        await runner.setup()
        
        site = web.TCPSite(runner, args.host, args.port)
        await site.start()
        
        logger.info(f"🚀 Gleitzeit V2 Server running at http://{args.host}:{args.port}")
        logger.info("Press Ctrl+C to stop")
        
        # Keep running
        while True:
            await asyncio.sleep(3600)  # Sleep for an hour
    
    except KeyboardInterrupt:
        logger.info("🛑 Shutting down server...")
    
    finally:
        await runner.cleanup()


if __name__ == '__main__':
    asyncio.run(main())