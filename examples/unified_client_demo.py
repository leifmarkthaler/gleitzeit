#!/usr/bin/env python3
"""
Demo of the unified Gleitzeit client that works in both API and Native modes

This demonstrates how the same code can work with:
1. A REST API server (production/distributed)
2. Direct native execution (development/testing)
"""

import asyncio
import logging
from pathlib import Path

# Add parent directory to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from gleitzeit.client_v2 import GleitzeitClient, ClientMode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def demo_auto_mode():
    """
    Demonstrate AUTO mode - automatically chooses between API and Native
    """
    print("\n" + "="*60)
    print("AUTO MODE DEMO - Automatically selects best mode")
    print("="*60)
    
    async with GleitzeitClient(mode=ClientMode.AUTO) as client:
        print(f"Client initialized in {client.get_mode()} mode")
        
        # This works the same regardless of whether API or Native mode is used
        result = await client.chat("What is 2+2?")
        print(f"Chat response: {result}")
        
        # Run a workflow (if exists)
        workflow_file = "examples/simple_python_workflow.yaml"
        if Path(workflow_file).exists():
            print(f"\nRunning workflow: {workflow_file}")
            workflow_result = await client.run_workflow(workflow_file)
            print(f"Workflow completed with status: {workflow_result.get('status')}")
        
        # Execute a task
        print("\nExecuting MCP task...")
        task_result = await client.execute_task(
            protocol="mcp/v1",
            method="mcp/tool.add",
            params={"a": 10, "b": 20},
            name="Addition Test"
        )
        print(f"Task result: {task_result.result if task_result else 'Failed'}")


async def demo_native_mode():
    """
    Demonstrate NATIVE mode - forces direct execution (good for development)
    """
    print("\n" + "="*60)
    print("NATIVE MODE DEMO - Direct execution without API")
    print("="*60)
    
    async with GleitzeitClient(mode=ClientMode.NATIVE) as client:
        print(f"Client forced to {client.get_mode()} mode")
        
        # Everything works the same, but uses direct execution
        result = await client.chat("Explain native mode in one sentence")
        print(f"Chat response: {result}")
        
        # Native mode is great for development - no server needed!
        print("\nNative mode benefits:")
        print("- No server process needed")
        print("- Direct access to execution engine")
        print("- Faster for single-user development")
        print("- Easier debugging")


async def demo_api_mode():
    """
    Demonstrate API mode - forces REST API usage (good for production)
    """
    print("\n" + "="*60)
    print("API MODE DEMO - Forces REST API usage")
    print("="*60)
    
    # This will auto-start the server if not running
    async with GleitzeitClient(
        mode=ClientMode.API,
        api_host="localhost",
        api_port=8000,
        auto_start_server=True
    ) as client:
        print(f"Client forced to {client.get_mode()} mode")
        
        # Everything works the same, but goes through the API
        result = await client.chat("Explain API mode in one sentence")
        print(f"Chat response: {result}")
        
        print("\nAPI mode benefits:")
        print("- Centralized execution")
        print("- Multiple clients can connect")
        print("- Persistence across client restarts")
        print("- Production-ready architecture")


async def demo_development_workflow():
    """
    Show a typical development workflow
    """
    print("\n" + "="*60)
    print("DEVELOPMENT WORKFLOW - Start native, switch to API")
    print("="*60)
    
    # During development, start with native mode for fast iteration
    print("\n1. Development phase - using native mode:")
    async with GleitzeitClient(mode=ClientMode.NATIVE) as client:
        # Test your workflow logic quickly
        result = await client.execute_task(
            protocol="python/v1",
            method="python/execute",
            params={"file": "calculate_sum.py"},
            name="Dev Test"
        )
        print(f"   Development test: {'✓ Passed' if result and result.status == 'completed' else '✗ Failed'}")
    
    # When ready for integration testing, switch to API mode
    print("\n2. Integration phase - using API mode:")
    async with GleitzeitClient(mode=ClientMode.API, auto_start_server=True) as client:
        # Same code, now going through API
        result = await client.execute_task(
            protocol="python/v1",
            method="python/execute",
            params={"file": "calculate_sum.py"},
            name="Integration Test"
        )
        print(f"   Integration test: {'✓ Passed' if result and result.status == 'completed' else '✗ Failed'}")
    
    # In production, use AUTO mode for flexibility
    print("\n3. Production phase - using AUTO mode:")
    async with GleitzeitClient(mode=ClientMode.AUTO) as client:
        print(f"   Auto-selected: {client.get_mode()} mode")


async def demo_batch_processing():
    """
    Demonstrate batch processing in both modes
    """
    print("\n" + "="*60)
    print("BATCH PROCESSING - Works in both modes")
    print("="*60)
    
    # Create some test files
    import tempfile
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Create test files
        for i in range(3):
            (temp_path / f"test{i}.txt").write_text(f"This is test file {i}")
        
        # Process batch - client auto-selects mode
        async with GleitzeitClient() as client:
            print(f"Processing batch in {client.get_mode()} mode")
            
            result = await client.batch_process(
                directory=str(temp_path),
                pattern="*.txt",
                prompt="Count the words in this file",
                max_concurrent=2
            )
            
            print(f"Processed {result['total_files']} files")
            print(f"Successful: {result['successful']}")
            print(f"Failed: {result['failed']}")


async def main():
    """Run all demos"""
    print("\n" + "#"*60)
    print("# GLEITZEIT UNIFIED CLIENT DEMONSTRATION")
    print("#"*60)
    
    try:
        # Show AUTO mode - the recommended default
        await demo_auto_mode()
        
        # Show forced NATIVE mode - great for development
        await demo_native_mode()
        
        # Show forced API mode - for production
        # Note: This might fail if server can't start
        try:
            await demo_api_mode()
        except Exception as e:
            print(f"API mode demo skipped: {e}")
        
        # Show typical development workflow
        await demo_development_workflow()
        
        # Show batch processing
        await demo_batch_processing()
        
    except KeyboardInterrupt:
        print("\n\nDemo interrupted by user")
    except Exception as e:
        print(f"\nError in demo: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "#"*60)
    print("# DEMO COMPLETE")
    print("#"*60)
    print("\nKey takeaways:")
    print("1. Same client code works in both API and Native modes")
    print("2. AUTO mode (default) intelligently selects the best option")
    print("3. Native mode is perfect for development and testing")
    print("4. API mode provides production-ready distributed execution")
    print("5. Easy to switch modes based on your needs")


if __name__ == "__main__":
    asyncio.run(main())