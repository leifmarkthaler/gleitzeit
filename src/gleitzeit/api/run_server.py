"""
Gleitzeit API Server Runner
"""

import logging
import sys
import os
from typing import Optional

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def run_server(
    host: str = "0.0.0.0",
    port: int = 8000,
    reload: bool = False,
    workers: int = 1,
    log_level: str = "info"
):
    """
    Run the Gleitzeit API server using Uvicorn

    Args:
        host: Host to bind to
        port: Port to bind to
        reload: Enable auto-reload for development
        workers: Number of worker processes (ignored if reload=True)
        log_level: Logging level
    """
    try:
        import uvicorn
    except ImportError:
        logger.error("Uvicorn not installed. Install with: pip install uvicorn[standard]")
        sys.exit(1)

    logger.info(f"Starting Gleitzeit API server on {host}:{port}")

    # Configure uvicorn
    config = {
        "app": "gleitzeit.api.main:app",
        "host": host,
        "port": port,
        "log_level": log_level,
        "access_log": True,
        "reload": reload
    }

    # Add workers only if not in reload mode
    if not reload and workers > 1:
        config["workers"] = workers

    # Run server
    uvicorn.run(**config)


def main():
    """Main entry point for CLI"""
    import argparse

    parser = argparse.ArgumentParser(description="Run Gleitzeit API Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--workers", type=int, default=1, help="Number of workers")
    parser.add_argument("--log-level", default="info", help="Log level")

    args = parser.parse_args()

    run_server(
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers,
        log_level=args.log_level
    )


if __name__ == "__main__":
    main()