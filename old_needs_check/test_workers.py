#!/usr/bin/env python
"""Test script to run workers and process the workflow"""

import asyncio
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.workers.workflow_loader_worker import WorkflowLoaderWorker
from gleitzeit.workers.dependency_worker import DependencyWorker
from gleitzeit.workers.task_execution_worker import TaskExecutionWorker
from gleitzeit.workers.base import WorkerConfig

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def run_workers():
    """Run all workers for a short time to process the workflow"""
    print("\n🚀 Starting Gleitzeit 0.0.7 Workers Demo\n")

    # Create workers for ALL shards (0-15) to handle any workflow
    workers = []
    all_shards = list(range(16))

    # Workflow Loader
    loader_config = WorkerConfig(
        worker_type="workflow_loader",
        worker_id="loader-1",
        consumer_group="loader-group",
        redis_url="redis://localhost:6379",
        assigned_shards=all_shards,
        block_timeout=1000  # 1 second for faster demo
    )
    loader = WorkflowLoaderWorker(loader_config)
    await loader.initialize()
    print("✅ WorkflowLoaderWorker initialized")
    workers.append(loader)

    # Dependency Worker
    dep_config = WorkerConfig(
        worker_type="dependency",
        worker_id="dep-1",
        consumer_group="dep-group",
        redis_url="redis://localhost:6379",
        assigned_shards=[10],
        block_timeout=1000
    )
    dep = DependencyWorker(dep_config)
    await dep.initialize()
    print("✅ DependencyWorker initialized")
    workers.append(dep)

    # Task Execution Worker
    exec_config = WorkerConfig(
        worker_type="task_execution",
        worker_id="exec-1",
        consumer_group="exec-group",
        redis_url="redis://localhost:6379",
        assigned_shards=[10],
        block_timeout=1000
    )
    exec_worker = TaskExecutionWorker(exec_config)
    await exec_worker.initialize()
    print("✅ TaskExecutionWorker initialized")
    workers.append(exec_worker)

    print("\n📋 Running workers for 5 seconds...\n")

    # Create tasks for all workers
    tasks = []
    for worker in workers:
        task = asyncio.create_task(worker.run())
        tasks.append(task)

    # Let them run
    await asyncio.sleep(5)

    print("\n🛑 Stopping workers...")

    # Stop all workers
    for worker in workers:
        worker._running = False

    # Wait for graceful shutdown
    await asyncio.sleep(1)

    # Cancel tasks
    for task in tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    print("\n📊 Worker Statistics:")
    for worker in workers:
        print(f"  {worker.config.worker_id}: {worker.messages_processed} processed, {worker.messages_failed} failed")

    print("\n✅ Demo complete!")

if __name__ == "__main__":
    asyncio.run(run_workers())