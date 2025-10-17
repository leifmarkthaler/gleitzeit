"""
Worker runner for Gleitzeit 0.0.7

Entry point for running individual workers as separate processes.
"""

import asyncio
import argparse
import logging
import sys
import json
from typing import Type
import importlib
import redis.asyncio as aioredis

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
    redis = None
    try:
        # Initialize instance identity from environment variable
        # This is passed from the main process via GLEITZEIT_INSTANCE_ID
        import os
        from ..core.instance import initialize_instance, get_current_instance

        instance_id = os.environ.get('GLEITZEIT_INSTANCE_ID')
        if instance_id and not get_current_instance():
            initialize_instance(instance_name=instance_id)
            logger.info(f"Initialized worker instance identity: {instance_id}")

        # Connect to Redis
        redis_url = args.redis_url or 'redis://localhost:6379'
        redis = await aioredis.from_url(
            redis_url,
            decode_responses=False
        )

        if args.config_key:
            # Load configuration from Redis
            logger.info(f"Loading configuration from Redis key: {args.config_key}")
            config_data = await redis.get(args.config_key.encode())

            if not config_data:
                logger.error(f"Configuration not found in Redis: {args.config_key}")
                sys.exit(1)

            config_dict = json.loads(config_data)
            logger.info(f"Loaded config for worker {config_dict.get('worker_id')}")

            # Import worker class
            worker_class = import_worker_class(config_dict['worker_class'])

            # Create WorkerConfig with all settings including handler configs
            config = WorkerConfig(
                worker_type=config_dict['worker_type'],
                worker_id=config_dict['worker_id'],
                consumer_group=config_dict.get('consumer_group', f"{config_dict['worker_type']}-group"),
                redis_url=config_dict.get('redis_url', redis_url),
                assigned_shards=config_dict.get('assigned_shards', []),
                max_concurrent=config_dict.get('max_concurrent', 10),
                batch_size=config_dict.get('batch_size', 10),
                block_timeout=config_dict.get('block_timeout', 5000),
                heartbeat_interval=config_dict.get('heartbeat_interval', 30),
                handler_configs=config_dict.get('handler_configs', {}),
                enabled_task_types=config_dict.get('enabled_task_types', ['all']),
                extra=config_dict.get('extra', {})
            )

            logger.info(f"Worker {config.worker_id} handler configs: {list(config.handler_configs.keys())}")

        else:
            # Fallback to CLI arguments (for backward compatibility)
            if not args.worker_class:
                logger.error("Either --config-key or --worker-class must be provided")
                sys.exit(1)

            worker_class = import_worker_class(args.worker_class)

            # Parse shards
            shards = []
            if args.shards:
                shards = [int(s) for s in args.shards.split(',')]

            # Create worker config from CLI args (no handler configs available this way)
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

        logger.info(f"Worker {config.worker_id} started successfully")
        if config.handler_configs:
            logger.info(f"Handler configurations loaded for: {list(config.handler_configs.keys())}")

        # Run worker
        await worker.run()

    except KeyboardInterrupt:
        logger.info("Worker interrupted by user")
    except Exception as e:
        logger.error(f"Worker failed: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if redis:
            await redis.aclose()


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Run a Gleitzeit worker')

    # Add config-key option for Redis-based configuration
    parser.add_argument(
        '--config-key',
        help='Redis key containing worker configuration'
    )

    parser.add_argument(
        '--worker-class',
        help='Python path to worker class (required if not using --config-key)'
    )

    parser.add_argument(
        '--worker-id',
        help='Unique worker identifier (required if not using --config-key)'
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

    # Validate arguments
    if not args.config_key:
        if not args.worker_class:
            parser.error("Either --config-key or --worker-class must be provided")
        if not args.worker_id:
            parser.error("--worker-id is required when not using --config-key")

    # Run worker
    asyncio.run(run_worker(args))


if __name__ == '__main__':
    main()