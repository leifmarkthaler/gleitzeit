#!/usr/bin/env python
"""
Test the HTTP workflow example
"""

import asyncio
import logging
import sys
import os
import redis.asyncio as aioredis
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.workers.workflow_loader_worker_v2 import WorkflowLoaderWorkerV2
from gleitzeit.workers.dependency_worker import DependencyWorker
from gleitzeit.workers.task_execution_worker import TaskExecutionWorker
from gleitzeit.workers.base import WorkerConfig

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def start_workers():
    """Start all necessary workers"""
    workers = []

    # Create worker configs
    loader_config = WorkerConfig(
        worker_type="workflow_loader",
        worker_id="loader-1",
        consumer_group="loader-group"
    )

    dependency_config = WorkerConfig(
        worker_type="dependency",
        worker_id="dep-1",
        consumer_group="dependency-group"
    )

    execution_config = WorkerConfig(
        worker_type="task_execution",
        worker_id="exec-1",
        consumer_group="execution-group"
    )

    # Create workers
    loader_worker = WorkflowLoaderWorkerV2(loader_config)
    dependency_worker = DependencyWorker(dependency_config)
    execution_worker = TaskExecutionWorker(execution_config)

    # Initialize workers
    await loader_worker.initialize()
    await dependency_worker.initialize()
    await execution_worker.initialize()

    workers.extend([loader_worker, dependency_worker, execution_worker])

    # Start workers
    tasks = []
    for worker in workers:
        task = asyncio.create_task(worker.run())
        tasks.append(task)

    logger.info(f"Started {len(workers)} workers")

    return workers, tasks


async def submit_workflow():
    """Submit the HTTP example workflow"""
    redis = await aioredis.from_url("redis://localhost:6379")

    # Load workflow
    import yaml
    with open("examples/http_workflow.yaml", "r") as f:
        workflow_data = yaml.safe_load(f)

    # Submit to loader stream
    await redis.xadd(
        b"{shard:0}:workflow:load",
        {
            b"workflow_id": b"http-test-1",
            b"workflow": yaml.dump(workflow_data).encode()
        }
    )

    logger.info("Submitted HTTP workflow")
    await redis.close()


async def monitor_workflow():
    """Monitor workflow status"""
    redis = await aioredis.from_url("redis://localhost:6379")

    workflow_id = "http-test-1"
    start_time = asyncio.get_event_loop().time()
    timeout = 60  # 60 seconds timeout

    while True:
        # Check workflow status
        status_key = f"{{shard:0}}:workflow:status:{workflow_id}".encode()
        status = await redis.hget(status_key, b"status")

        if status:
            status = status.decode()
            logger.info(f"Workflow status: {status}")

            if status in ["completed", "failed"]:
                # Get final status
                all_fields = await redis.hgetall(status_key)
                logger.info(f"Final workflow state: {all_fields}")

                # Get task statuses
                pattern = f"{{shard:*}}:task:status:*"
                cursor = b"0"
                task_keys = []

                while True:
                    cursor, keys = await redis.scan(
                        cursor,
                        match=pattern.encode(),
                        count=100
                    )
                    task_keys.extend(keys)
                    if cursor == b"0":
                        break

                logger.info(f"Found {len(task_keys)} task keys")

                for key in task_keys:
                    if workflow_id.encode() in key:
                        task_data = await redis.hgetall(key)
                        task_id = key.split(b":")[-1]
                        status = task_data.get(b"status", b"unknown").decode()
                        logger.info(f"Task {task_id.decode()}: {status}")

                        if status == "failed":
                            error = task_data.get(b"error", b"").decode()
                            logger.error(f"  Error: {error}")
                        elif status == "completed":
                            result = task_data.get(b"result", b"").decode()[:100]
                            logger.info(f"  Result preview: {result}")

                break

        # Check timeout
        if asyncio.get_event_loop().time() - start_time > timeout:
            logger.error("Workflow execution timed out")
            break

        await asyncio.sleep(2)

    await redis.close()


async def main():
    """Main test function"""
    logger.info("Starting HTTP workflow test")

    # Start workers
    workers, tasks = await start_workers()

    # Give workers time to initialize
    await asyncio.sleep(2)

    # Submit workflow
    await submit_workflow()

    # Monitor execution
    await monitor_workflow()

    # Shutdown workers
    logger.info("Shutting down workers")
    for worker in workers:
        worker._running = False

    # Cancel tasks
    for task in tasks:
        task.cancel()

    # Wait for cleanup
    await asyncio.gather(*tasks, return_exceptions=True)

    logger.info("Test complete")


if __name__ == "__main__":
    asyncio.run(main())