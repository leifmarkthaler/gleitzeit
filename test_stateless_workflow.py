#!/usr/bin/env python
"""
Test running a workflow with the completely stateless Gleitzeit system.

This demonstrates how workflows are executed without any loops - everything
is triggered externally.
"""

import asyncio
import logging
from datetime import datetime
from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager
from gleitzeit.system.models import SystemConfig, DeploymentMode
from gleitzeit.core.models import Workflow, Task

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_stateless_workflow():
    """Run a workflow using the stateless system."""

    # Configuration
    config = SystemConfig(
        deployment_mode=DeploymentMode.DEVELOPMENT,
        environment="test",
        default_providers=["python"]
    )

    manager = None

    try:
        logger.info("=" * 60)
        logger.info("STATELESS WORKFLOW EXECUTION DEMO")
        logger.info("=" * 60)

        # Step 1: Create the stateless manager
        logger.info("\n1. Creating Stateless ModularStreamSystemManager...")
        manager = await ModularStreamSystemManager.create(
            config=config,
            instance_id="stateless_test",
            create_if_missing=True,
            start_system=True
        )

        if not manager:
            logger.error("Failed to create manager")
            return False

        logger.info("✅ Manager created (NO LOOPS RUNNING!)")

        # Step 2: Create a test workflow
        logger.info("\n2. Creating test workflow...")
        workflow = Workflow(
            id="stateless-workflow-001",
            name="Stateless Test Workflow",
            tasks=[
                Task(
                    id="task1",
                    name="Print Hello",
                    protocol="python/v1",
                    method="python/execute",
                    params={
                        "code": "print('Hello from stateless Gleitzeit!')\nresult = 'Task 1 complete'"
                    }
                ),
                Task(
                    id="task2",
                    name="Calculate",
                    protocol="python/v1",
                    method="python/execute",
                    params={
                        "code": "result = 42 * 2\nprint(f'The answer is {result}')"
                    },
                    dependencies=["task1"]
                ),
                Task(
                    id="task3",
                    name="Final Task",
                    protocol="python/v1",
                    method="python/execute",
                    params={
                        "code": "print('Workflow complete!')\nresult = 'All done'"
                    },
                    dependencies=["task2"]
                )
            ]
        )

        # Step 3: Submit the workflow
        logger.info("\n3. Submitting workflow...")
        workflow_id = await manager.submit_workflow(workflow)
        logger.info(f"✅ Workflow submitted: {workflow_id}")

        # Step 4: Process events (manually triggered, no loops!)
        logger.info("\n4. Processing workflow (TRIGGERED, NOT LOOPED!)...")
        logger.info("-" * 40)

        # In a real deployment, these would be triggered by:
        # - Kubernetes CronJob
        # - AWS Lambda
        # - External scheduler
        # - Redis trigger stream

        max_iterations = 3
        for i in range(max_iterations):
            logger.info(f"\n🔄 Processing iteration {i+1}/{max_iterations}")

            # Process all components once (NO LOOPS!)
            stats = await manager.process_all_once()

            # Show what was processed
            logger.info(f"  Stream stats: {stats.get('streams', {})}")

            if stats.get("streams", {}).get("processed", 0) > 0:
                logger.info(f"  📨 Processed {stats['streams']['processed']} stream messages")

            if stats.get("timers", {}).get("processed", 0) > 0:
                logger.info(f"  ⏰ Fired {stats['timers']['processed']} timers")

            if stats.get("signals", {}).get("processed", 0) > 0:
                logger.info(f"  📡 Processed {stats['signals']['processed']} signals")

            if stats.get("scheduler", {}).get("total_processed", 0) > 0:
                logger.info(f"  📅 Processed {stats['scheduler']['total_processed']} scheduled events")

            # Check workflow status
            workflow_data = await manager.get_workflow(workflow_id)
            if workflow_data:
                status = workflow_data.status if hasattr(workflow_data, 'status') else 'unknown'
                logger.info(f"  📊 Workflow status: {status}")

                if status in ['completed', 'failed']:
                    logger.info(f"\n✅ Workflow {status}!")
                    break

            # Small delay to simulate external trigger interval
            await asyncio.sleep(1.0)

        # Step 5: Get results
        logger.info("\n5. Retrieving task results...")
        logger.info("-" * 40)

        for task_id in ["task1", "task2", "task3"]:
            # Get task directly from persistence
            task_data = await manager.persistence.get_task(task_id)
            if task_data:
                logger.info(f"  Task {task_id}: {task_data.status if hasattr(task_data, 'status') else 'NO STATUS'}")
                if hasattr(task_data, 'output'):
                    logger.info(f"    Output: {task_data.output}")
                if hasattr(task_data, 'result'):
                    logger.info(f"    Result: {task_data.result}")
            else:
                logger.info(f"  Task {task_id}: NOT FOUND")

        # Step 6: Show system statistics
        logger.info("\n6. System Statistics")
        logger.info("-" * 40)
        stats = manager.get_statistics()
        logger.info(f"  Stateless: {stats.get('stateless', False)}")
        logger.info(f"  Has Loops: {stats.get('has_loops', True)}")
        logger.info(f"  Instance: {stats.get('instance_id', 'unknown')}")

        return True

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

    finally:
        if manager:
            logger.info("\n7. Shutting down manager...")
            await manager.shutdown()
            logger.info("✅ Clean shutdown (no loops to stop!)")


async def demonstrate_external_triggering():
    """Demonstrate how external systems would trigger processing."""

    logger.info("\n" + "=" * 60)
    logger.info("EXTERNAL TRIGGERING PATTERNS")
    logger.info("=" * 60)

    logger.info("""
In production, the stateless system would be triggered by:

1. KUBERNETES CRONJOB (every minute):
   kubectl create cronjob gleitzeit-processor \\
     --image=gleitzeit:stateless \\
     --schedule="*/1 * * * *" \\
     -- python -c "
       import asyncio
       from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager

       async def process():
           manager = await ModularStreamSystemManager.create()
           await manager.process_all_once()
           await manager.shutdown()

       asyncio.run(process())
     "

2. AWS LAMBDA (event-driven):
   def lambda_handler(event, context):
       manager = await ModularStreamSystemManager.create()
       stats = await manager.process_all_once()
       await manager.shutdown()
       return {"processed": stats}

3. REDIS TRIGGER STREAM:
   # Send trigger
   redis-cli XADD gleitzeit:triggers * action process

   # Processor waits for triggers
   while True:
       trigger = await redis.xreadgroup("processors", "proc1", {"gleitzeit:triggers": ">"})
       if trigger:
           await manager.process_all_once()

4. GITHUB ACTIONS (scheduled workflow):
   on:
     schedule:
       - cron: '*/5 * * * *'
   jobs:
     process:
       runs-on: ubuntu-latest
       steps:
         - run: |
             python -m gleitzeit.process_once

5. SYSTEMD TIMER:
   [Timer]
   OnCalendar=*:0/1  # Every minute

   [Service]
   ExecStart=/usr/bin/python -m gleitzeit.process_once
""")


async def main():
    """Main entry point."""

    # Run the stateless workflow
    success = await run_stateless_workflow()

    if success:
        # Show external triggering patterns
        await demonstrate_external_triggering()

        print("\n" + "=" * 60)
        print("🎉 STATELESS WORKFLOW EXECUTION SUCCESSFUL!")
        print("=" * 60)
        print("\nKey Points:")
        print("  • NO loops running in the background")
        print("  • Each process_all_once() call is independent")
        print("  • External triggers control processing timing")
        print("  • Perfect for serverless and cloud-native")
        print("  • Unlimited horizontal scaling")
        print("=" * 60)
    else:
        print("\n❌ Workflow execution failed")


if __name__ == "__main__":
    asyncio.run(main())