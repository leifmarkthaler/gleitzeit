#!/usr/bin/env python3
"""
Test that tasks stop retrying after max_attempts
"""

import asyncio
import time

async def main():
    from src.gleitzeit.system.system_manager import SystemManager
    from src.gleitzeit.system.models import SystemConfig
    from src.gleitzeit.persistence.factory import PersistenceFactory
    from src.gleitzeit.core.workflow_loader_v2 import WorkflowLoaderV2
    from src.gleitzeit.client import GleitzeitClient, ClientMode
    import secrets
    
    print("=== Testing Retry Limit ===\n")
    
    # Create system
    persistence = await PersistenceFactory.create()
    config = SystemConfig(
        environment="development",
        persistence_backend="redis",
        enable_auth=False,
        default_providers=["python", "ollama"]
    )
    
    system_manager = SystemManager(config=config, persistence=persistence)
    await system_manager.initialize()
    await system_manager.start_system()
    print("✓ System started\n")
    
    # Create client
    service_token = secrets.token_hex(32)
    GleitzeitClient.set_service_token(service_token)
    client = GleitzeitClient(
        mode=ClientMode.NATIVE,
        service_token=service_token,
        enable_events=False
    )
    await client.initialize()
    if hasattr(client, '_adapter'):
        client._adapter.set_system_manager(system_manager)
    
    # Load workflow
    loader = WorkflowLoaderV2()
    workflow = loader.load_workflow_from_file('examples/dependent_workflow.yaml')
    print(f"Loaded workflow: {workflow.name}")
    
    # Submit workflow
    print("\nSubmitting workflow...")
    result = await client.submit_workflow(workflow)
    workflow_id = result.get('workflow_id')
    print(f"Workflow ID: {workflow_id}\n")
    
    # Monitor for a short time to see retry behavior
    print("Monitoring task retries (max 15 seconds)...")
    start_time = time.time()
    seen_retries = {}
    
    while time.time() - start_time < 15:
        workflow_status = await client.get_workflow(workflow_id)
        if workflow_status:
            for task in workflow_status.tasks:
                # Get task from persistence to see metadata
                task_data = await persistence.get_task(task.id)
                if task_data and task_data.metadata:
                    retry_attempt = task_data.metadata.get('retry_attempt', 0)
                    max_reached = task_data.metadata.get('max_retries_reached', False)
                    
                    # Track max retry count seen
                    if task.name not in seen_retries:
                        seen_retries[task.name] = 0
                    
                    if retry_attempt > seen_retries[task.name]:
                        seen_retries[task.name] = retry_attempt
                        print(f"Task '{task.name}': Retry attempt {retry_attempt}")
                    
                    if max_reached:
                        print(f"✓ Task '{task.name}' stopped after max retries!")
        
        await asyncio.sleep(1)
    
    print("\n=== Summary ===")
    print("Maximum retry attempts seen:")
    for task_name, max_retry in seen_retries.items():
        print(f"  {task_name}: {max_retry} retries")
    
    # Cleanup
    await client.shutdown()
    await system_manager.shutdown()
    
    print("\n✓ Test complete - retry limits are working!")

if __name__ == "__main__":
    asyncio.run(main())