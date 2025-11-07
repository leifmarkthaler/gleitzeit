#!/usr/bin/env python
"""Test script using ComponentOrchestrator to manage workers"""

import asyncio
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.orchestrator.component_orchestrator import ComponentOrchestrator, WorkerSpec
from gleitzeit.cli.main import workflow_submit
import redis.asyncio as aioredis

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_with_orchestrator():
    """Test using the ComponentOrchestrator to manage workers"""
    print("\n🚀 Starting Gleitzeit 0.0.7 with Component Orchestrator\n")

    # Create orchestrator with configuration
    config = {
        'num_shards': 16,
        'workers': [
            {
                'worker_type': 'workflow_loader',
                'worker_class': 'gleitzeit.workers.workflow_loader_worker.WorkflowLoaderWorker',
                'count': 2,  # 2 loader workers
                'auto_scale': False
            },
            {
                'worker_type': 'dependency',
                'worker_class': 'gleitzeit.workers.dependency_worker.DependencyWorker',
                'count': 3,  # 3 dependency workers
                'auto_scale': True,
                'max_replicas': 10
            },
            {
                'worker_type': 'task_execution',
                'worker_class': 'gleitzeit.workers.task_execution_worker.TaskExecutionWorker',
                'count': 5,  # 5 execution workers
                'auto_scale': True,
                'max_replicas': 20
            }
        ]
    }

    orchestrator = ComponentOrchestrator(
        redis_url='redis://localhost:6379',
        config=config
    )

    # Initialize orchestrator
    await orchestrator.initialize()
    print("✅ ComponentOrchestrator initialized")

    # The orchestrator will automatically assign shards to workers!
    # For example:
    # - Worker 0: shards [0, 5, 10, 15]
    # - Worker 1: shards [1, 6, 11]
    # - Worker 2: shards [2, 7, 12]
    # etc.

    # Start workers (simulated - in real deployment they'd be separate processes)
    print("\n📋 Worker Configuration:")
    for worker_type, spec in orchestrator.worker_specs.items():
        print(f"  {worker_type}: {spec.count} workers")

    print("\n🎯 Shard Assignments (automatic round-robin):")
    for i in range(3):  # Show first 3 workers of each type
        for worker_type in orchestrator.worker_specs.keys():
            worker_id = f"{worker_type}-{i}"
            shards = orchestrator.assign_shards_to_worker(worker_id, worker_type)
            if shards:
                print(f"  {worker_id}: shards {shards}")

    # Submit a workflow
    print("\n📝 Submitting test workflow...")
    redis = await aioredis.from_url('redis://localhost:6379')

    # Submit directly
    import uuid
    workflow_id = f"workflow_{uuid.uuid4().hex[:12]}"
    from gleitzeit.core.sharding import default_sharding
    shard = default_sharding.get_shard(workflow_id)

    await redis.xadd(
        f"workflow:load:{shard}".encode(),
        {
            b"workflow_id": workflow_id.encode(),
            b"path": b"example_workflow.yaml",
            b"format": b"yaml"
        }
    )

    print(f"✅ Workflow {workflow_id} submitted to shard {shard}")

    # In a real deployment, the orchestrator would:
    # 1. Start actual worker processes
    # 2. Monitor their health
    # 3. Auto-scale based on load
    # 4. Handle failures and restarts

    print("\n📊 Orchestrator would manage:")
    print("  - Worker lifecycle (start/stop/restart)")
    print("  - Health monitoring")
    print("  - Auto-scaling based on queue depth")
    print("  - Shard rebalancing")
    print("  - Service discovery")

    await redis.aclose()
    print("\n✅ Demo complete!")

if __name__ == "__main__":
    asyncio.run(test_with_orchestrator())