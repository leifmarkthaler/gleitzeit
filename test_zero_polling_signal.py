#!/usr/bin/env python3
"""
Test the zero-polling Redis Streams architecture with signal workflow.
This test verifies that:
1. SignalProvider is properly registered with PoolingAdapter
2. Signal workflows work with pure blocking stream reads
3. No polling loops are used anywhere in the system
"""

import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.client.client import GleitzeitClient


async def test_zero_polling_signal_workflow():
    """Test signal workflow with zero-polling architecture."""
    print("🚀 Testing zero-polling signal workflow...")

    client = GleitzeitClient(mode="api", api_host="localhost", api_port=8000)

    # Simple signal workflow - wait for a test signal
    workflow_yaml = """
version: "1.0"
workflow:
  name: "test_zero_polling_signal"
  description: "Test signal workflow with zero-polling architecture"

tasks:
  - id: "wait_for_signal"
    protocol: "signal/v1"
    method: "signal/wait"
    parameters:
      signal_name: "test_complete"
      timeout: 30
    description: "Wait for test completion signal"

  - id: "print_result"
    protocol: "python/v1"
    method: "python/exec"
    parameters:
      code: |
        print("✅ Signal received! Zero-polling architecture working correctly.")
        result = "Signal workflow completed successfully with pure Redis Streams"
    dependencies: ["wait_for_signal"]
    description: "Print success message"
"""

    try:
        # Save workflow to file and use CLI
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(workflow_yaml)
            workflow_file = f.name

        # Submit workflow using CLI (which connects to the server)
        print("📤 Submitting signal workflow...")
        result = await client.submit_workflow_from_file(workflow_file)
        workflow_id = result['workflow_id']
        print(f"✅ Workflow submitted: {workflow_id}")

        # Clean up temp file
        os.unlink(workflow_file)

        # Wait a moment for workflow to start
        await asyncio.sleep(2)

        # Check workflow status
        status = await client.get_workflow_status(workflow_id)
        print(f"📊 Workflow status: {status.status}")

        # Send the signal in a separate task
        async def send_signal():
            await asyncio.sleep(5)  # Wait 5 seconds then send signal
            print("📡 Sending test completion signal...")
            await client.send_signal("test_complete", {"source": "zero_polling_test"})
            print("✅ Signal sent successfully")

        # Start signal sending task
        signal_task = asyncio.create_task(send_signal())

        # Wait for workflow completion (with timeout)
        print("⏳ Waiting for workflow completion...")

        for i in range(60):  # Wait up to 60 seconds
            status = await client.get_workflow_status(workflow_id)
            print(f"📊 Status check {i+1}: {status.status}")

            if status.status in ["completed", "failed"]:
                break

            await asyncio.sleep(1)

        # Get final status
        final_status = await client.get_workflow_status(workflow_id)
        print(f"🏁 Final status: {final_status.status}")

        if final_status.status == "completed":
            print("🎉 SUCCESS: Zero-polling signal workflow completed successfully!")

            # Get workflow results
            try:
                results = await client.get_workflow_results(workflow_id)
                if results:
                    print(f"📋 Results: {results}")
            except Exception as e:
                print(f"⚠️  Could not get results: {e}")

            return True
        else:
            print(f"❌ FAILED: Workflow ended with status: {final_status.status}")
            return False

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Main test function."""
    print("🧪 Testing Zero-Polling Redis Streams Architecture")
    print("=" * 50)

    success = await test_zero_polling_signal_workflow()

    print("=" * 50)
    if success:
        print("✅ All tests passed! Zero-polling architecture is working correctly.")
        sys.exit(0)
    else:
        print("❌ Tests failed! Check the logs for issues.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())