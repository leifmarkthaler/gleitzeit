#!/usr/bin/env python3
"""
Trace the source of "Task not found" error by monkeypatching
"""

import sys
import traceback

# Store original functions
_original_print = print
_original_stderr_write = sys.stderr.write

def traced_print(*args, **kwargs):
    """Traced version of print that shows stack trace for 'not found' messages"""
    output = ' '.join(str(arg) for arg in args)
    if 'not found' in output.lower() and 'task' in output.lower():
        print("=== FOUND 'Task not found' print ===", file=sys.__stderr__)
        traceback.print_stack(file=sys.__stderr__)
        print("===================================", file=sys.__stderr__)
    return _original_print(*args, **kwargs)

def traced_stderr_write(text):
    """Traced version of stderr.write"""
    if 'not found' in text.lower() and 'task' in text.lower():
        sys.__stderr__.write("=== FOUND 'Task not found' in stderr ===\n")
        traceback.print_stack(file=sys.__stderr__)
        sys.__stderr__.write("===================================\n")
    return _original_stderr_write(text)

# Monkey patch
print = traced_print
sys.stderr.write = traced_stderr_write

# Now run the actual test
import asyncio
from src.gleitzeit.system.system_manager import SystemManager
from src.gleitzeit.system.models import SystemConfig
from src.gleitzeit.persistence.factory import PersistenceFactory
from src.gleitzeit.core.workflow_loader_v2 import WorkflowLoaderV2
from src.gleitzeit.client import GleitzeitClient, ClientMode
import secrets

async def main():
    print("Starting traced test...")
    
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
    
    # Submit workflow
    result = await client.submit_workflow(workflow)
    workflow_id = result.get('workflow_id')
    print(f"Workflow ID: {workflow_id}")
    
    # Wait a moment for errors to appear
    await asyncio.sleep(3)
    
    await client.shutdown()
    await system_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(main())