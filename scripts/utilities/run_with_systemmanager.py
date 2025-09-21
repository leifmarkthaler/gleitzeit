#!/usr/bin/env python3
"""
Run a workflow with properly initialized SystemManager.
"""

import asyncio
import yaml
from pathlib import Path

async def main():
    # Import required modules
    from src.gleitzeit.system.system_manager import SystemManager
    from src.gleitzeit.system.models import SystemConfig
    from src.gleitzeit.client import GleitzeitClient, ClientMode
    from src.gleitzeit.core.models import Workflow
    from src.gleitzeit.persistence.factory import PersistenceFactory
    
    print("=== Starting Gleitzeit with SystemManager ===")
    
    # Create persistence
    print("1. Creating persistence backend...")
    persistence = await PersistenceFactory.create()
    
    # Create system config
    print("2. Creating system configuration...")
    config = SystemConfig(
        environment="development",
        persistence_backend="redis",
        enable_auth=False,
        default_providers=["python", "ollama"]
    )
    
    # Create and initialize SystemManager
    print("3. Initializing SystemManager...")
    system_manager = SystemManager(config=config, persistence=persistence)
    await system_manager.initialize()
    
    # Start the system
    print("4. Starting system components...")
    await system_manager.start_system()
    print("✓ SystemManager started successfully")
    
    # Create client using NATIVE mode with direct SystemManager access
    print("\n5. Creating client...")
    from src.gleitzeit.client import GleitzeitClient
    
    # Set service token for NATIVE mode
    import secrets
    service_token = secrets.token_hex(32)
    GleitzeitClient.set_service_token(service_token)
    
    client = GleitzeitClient(
        mode=ClientMode.NATIVE,
        service_token=service_token,
        enable_events=False
    )
    await client.initialize()
    
    # Connect client to SystemManager
    if hasattr(client, '_adapter'):
        client._adapter.set_system_manager(system_manager)
    
    print("✓ Client initialized with SystemManager")
    
    # Load and submit workflow
    print("\n6. Loading workflow...")
    from src.gleitzeit.core.workflow_loader_v2 import WorkflowLoaderV2
    
    # Get registry from SystemManager if available
    registry = system_manager.registry if hasattr(system_manager, 'registry') else None
    loader = WorkflowLoaderV2(registry=registry)
    workflow = loader.load_workflow_from_file('examples/dependent_workflow.yaml')
    print(f"✓ Loaded workflow: {workflow.name}")
    
    print("\n7. Submitting workflow...")
    result = await client.submit_workflow(workflow)
    print(f"✓ Workflow submitted: {result}")
    
    # Wait a bit for execution to start
    print("\n8. Waiting for execution...")
    await asyncio.sleep(5)
    
    # Check workflow status
    print("\n9. Checking workflow status...")
    workflow_status = await client.get_workflow(workflow.id)
    if workflow_status:
        print(f"Workflow status: {workflow_status.status}")
        print(f"Tasks: {len(workflow_status.tasks)}")
        
        # Check task statuses
        for task in workflow_status.tasks:
            print(f"  - Task '{task.name}': {task.status}")
    
    # Clean shutdown
    print("\n10. Shutting down...")
    await client.shutdown()
    await system_manager.shutdown_system()
    await system_manager.shutdown()
    print("✓ Clean shutdown complete")

if __name__ == "__main__":
    asyncio.run(main())