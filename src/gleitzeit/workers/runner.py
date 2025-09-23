"""
Worker runner for Gleitzeit 0.0.7

Entry point for running individual workers as separate processes.
"""

import asyncio
import argparse
import logging
import sys
from typing import Type
import importlib

from .base import BaseWorker, WorkerConfig

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def import_worker_class(class_path: str) -> Type[BaseWorker]:
    """Import worker class from module path"""
    module_path, class_name = class_path.rsplit('.', 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


async def run_worker(args):
    """Run a worker instance"""
    # Import worker class
    worker_class = import_worker_class(args.worker_class)

    # Parse shards
    shards = []
    if args.shards:
        shards = [int(s) for s in args.shards.split(',')]

    # Create worker config
    worker_type = args.worker_type or worker_class.__name__
    config = WorkerConfig(
        worker_type=worker_type,
        worker_id=args.worker_id,
        consumer_group=args.consumer_group or f"{worker_type}-group",
        redis_url=args.redis_url,
        assigned_shards=shards,
        max_concurrent=args.max_concurrent,
        batch_size=args.batch_size,
        block_timeout=args.block_timeout,
        heartbeat_interval=args.heartbeat_interval
    )

    # Create and initialize worker
    worker = worker_class(config)
    await worker.initialize()

    logger.info(f"Worker {args.worker_id} started with config: {config}")

    # Run worker
    try:
        await worker.run()
    except KeyboardInterrupt:
        logger.info("Worker interrupted by user")
    except Exception as e:
        logger.error(f"Worker failed: {e}", exc_info=True)
        sys.exit(1)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Run a Gleitzeit worker')

    parser.add_argument(
        '--worker-class',
        required=True,
        help='Python path to worker class (e.g., gleitzeit.workers.task_execution_worker.TaskExecutionWorker)'
    )

    parser.add_argument(
        '--worker-id',
        required=True,
        help='Unique worker identifier'
    )

    parser.add_argument(
        '--worker-type',
        help='Worker type (defaults to class name)'
    )

    parser.add_argument(
        '--redis-url',
        default='redis://localhost:6379',
        help='Redis connection URL'
    )

    parser.add_argument(
        '--shards',
        help='Comma-separated list of shard numbers (e.g., 0,1,2,3)'
    )

    parser.add_argument(
        '--consumer-group',
        help='Redis consumer group name'
    )

    parser.add_argument(
        '--max-concurrent',
        type=int,
        default=10,
        help='Maximum concurrent message processing'
    )

    parser.add_argument(
        '--batch-size',
        type=int,
        default=10,
        help='Batch size for reading from streams'
    )

    parser.add_argument(
        '--block-timeout',
        type=int,
        default=5000,
        help='Block timeout in milliseconds'
    )

    parser.add_argument(
        '--heartbeat-interval',
        type=int,
        default=30,
        help='Heartbeat interval in seconds'
    )

    args = parser.parse_args()

    # Run worker
    asyncio.run(run_worker(args))


if __name__ == '__main__':
    main()