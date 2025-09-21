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
    
    # Monitor task retries for 30 seconds
    print("Monitoring task retries (should stop after 3 attempts)...")
    start_time = time.time()
    last_status = {}
    
    while time.time() - start_time < 30:
        # Get workflow status
        workflow_status = await client.get_workflow(workflow_id)
        if workflow_status:
            for task in workflow_status.tasks:
                task_key = task.name
                current = f"{task.status}"
                
                # Check task metadata for retry count
                task_data = await persistence.get_task(task.id)
                if task_data and task_data.metadata:
                    retry_attempt = task_data.metadata.get('retry_attempt', 0)
                    current += f" (attempt {retry_attempt})"
                    
                    # Check if marked as max_retries_reached
                    if task_data.metadata.get('max_retries_reached'):
                        current += " - MAX RETRIES REACHED"
                
                # Only print if status changed
                if last_status.get(task_key) != current:
                    elapsed = int(time.time() - start_time)
                    print(f"[{elapsed:3d}s] Task '{task.name}': {current}")
                    last_status[task_key] = current
                    
                    # Check if permanently failed
                    if "MAX RETRIES REACHED" in current:
                        print(f"       ✓ Task correctly stopped after max retries!")
        
        await asyncio.sleep(2)
    
    print("\n=== Final Status ===")
    workflow_status = await client.get_workflow(workflow_id)
    if workflow_status:
        for task in workflow_status.tasks:
            task_data = await persistence.get_task(task.id)
            retry_info = ""
            if task_data and task_data.metadata:
                retry_attempt = task_data.metadata.get('retry_attempt', 0)
                max_reached = task_data.metadata.get('max_retries_reached', False)
                retry_info = f" (attempts: {retry_attempt}, max_reached: {max_reached})"
            print(f"Task '{task.name}': {task.status}{retry_info}")
    
    # Cleanup
    await client.shutdown()
    await system_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(main())