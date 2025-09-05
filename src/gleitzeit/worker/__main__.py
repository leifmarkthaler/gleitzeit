"""
Worker service entry point

Run with: python -m gleitzeit.worker
"""

import asyncio
import sys
import logging
from .service import main

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Worker service stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Worker service failed: {e}")
        sys.exit(1)