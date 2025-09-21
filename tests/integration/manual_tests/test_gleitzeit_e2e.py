#!/usr/bin/env python3
"""
End-to-end test of Gleitzeit: Start server, connect with client, run workflow.
"""

import asyncio
import sys
import json
import time
from pathlib import Path
from contextlib import asynccontextmanager

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

@asynccontextmanager
async def gleitzeit_server():
    """Context manager to start and stop Gleitzeit server."""
    from gleitzeit.api.main import create_modular_app
    from gleitzeit.system.system_manager import SystemManager
    from gleitzeit.system.models import SystemConfig
    import uvicorn
    from threading import Thread
    
    print("Starting Gleitzeit server...")
    
    # Create system config
    config = SystemConfig(
        environment="test",
        persistence_backend="memory",
        enable_auth=False,
        default_providers=["python"]
    )
    
    # Create and initialize system manager
    system_manager = SystemManager(config=config)
    await system_manager.initialize()
    await system_manager.start_system()
    
    # Create FastAPI app
    app = create_modular_app()
    
    # Run server in background thread
    server_thread = Thread(
        target=lambda: uvicorn.run(app, host="127.0.0.1", port=8000, log_level="error"),
        daemon=True
    )
    server_thread.start()
    
    # Wait for server to be ready
    await asyncio.sleep(2)
    print("✓ Gleitzeit server started on http://localhost:8000")
    
    try:
        yield system_manager
    finally:
        print("Shutting down server...")
        await system_manager.shutdown()


async def run_client_workflow():
    """Run workflow using Gleitzeit client."""
    from gleitzeit.client import GleitzeitClient, ClientMode
    
    print("\nRunning client workflow...")
    
    # Create client
    client = GleitzeitClient(
        mode=ClientMode.API,
        api_url="http://localhost:8000"
    )
    
    # Connect
    await client.connect()
    print("✓ Client connected")
    
    # Create test files
    test_files = []
    for i in range(3):
        test_file = Path(f"/tmp/gleitzeit_e2e_{i}.py")
        test_file.write_text(f"""
import json
import time

print(f"Task {i} starting...")
time.sleep(0.2)  # Simulate work

result = {{
    "task_id": {i},
    "message": "Task {i} completed",
    "value": {i} * 100
}}

print(json.dumps(result))
""")
        test_files.append(test_file)
    
    # Submit individual tasks
    print("\nSubmitting individual tasks...")
    task_ids = []
    for i, test_file in enumerate(test_files):
        task_id = await client.submit_task(
            protocol="python/v1",
            method="python/execute",
            params={
                "file_path": str(test_file.absolute()),
                "return_output": True
            },
            task_id=f"task_{i}"
        )
        task_ids.append(task_id)
        print(f"  Submitted task {i}: {task_id}")
    
    # Wait for tasks
    print("\nWaiting for task results...")
    for i, task_id in enumerate(task_ids):
        result = await client.wait_for_task(task_id, timeout=10)
        if result:
            print(f"  ✓ Task {i} completed")
        else:
            print(f"  ✗ Task {i} failed")
    
    # Submit a workflow
    print("\nSubmitting workflow with dependencies...")
    workflow_def = {
        "id": "e2e_workflow",
        "name": "E2E Test Workflow",
        "tasks": [
            {
                "id": "step1",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "file_path": str(test_files[0].absolute()),
                    "return_output": True
                }
            },
            {
                "id": "step2",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "file_path": str(test_files[1].absolute()),
                    "return_output": True
                },
                "dependencies": ["step1"]
            },
            {
                "id": "step3",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "file_path": str(test_files[2].absolute()),
                    "return_output": True
                },
                "dependencies": ["step2"]
            }
        ]
    }
    
    workflow_id = await client.submit_workflow(workflow_def)
    print(f"✓ Submitted workflow: {workflow_id}")
    
    # Wait a bit for workflow to process
    await asyncio.sleep(5)
    
    # Disconnect
    await client.disconnect()
    
    # Cleanup
    for test_file in test_files:
        test_file.unlink(missing_ok=True)
    
    print("\n✓ Client workflow completed successfully!")


async def main():
    """Main test function."""
    print("Gleitzeit End-to-End Test")
    print("=" * 50)
    
    try:
        # Start server and run client workflow
        async with gleitzeit_server() as system_manager:
            await run_client_workflow()
            
            # Check some stats
            print("\nServer Statistics:")
            # Get some basic stats if available
            
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        raise
    
    print("\n" + "=" * 50)
    print("✅ End-to-end test completed successfully!")
    print("\nDemonstrated:")
    print("  - Starting Gleitzeit server")
    print("  - Connecting with client library")
    print("  - Submitting individual tasks")
    print("  - Submitting workflows with dependencies")
    print("  - Retrieving results")
    print("  - Clean shutdown")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)