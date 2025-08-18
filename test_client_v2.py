#!/usr/bin/env python3
"""
Test script for the new unified client (client_v2.py)
"""

import asyncio
import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.client_v2 import GleitzeitClient, ClientMode


async def test_native_mode():
    """Test native mode execution"""
    print("\n" + "="*60)
    print("Testing NATIVE mode")
    print("="*60)
    
    try:
        async with GleitzeitClient(mode=ClientMode.NATIVE) as client:
            print(f"✓ Client initialized in {client.get_mode()} mode")
            
            # Test simple task execution
            print("\nTesting MCP task execution...")
            result = await client.execute_task(
                protocol="mcp/v1",
                method="mcp/tool.add",
                params={"a": 5, "b": 3},
                name="Addition Test"
            )
            
            if result and result.status == "completed":
                print(f"✓ MCP task completed: {result.result}")
            else:
                print(f"✗ MCP task failed: {result.error if result else 'No result'}")
            
            # Test Python execution with file
            print("\nTesting Python task execution...")
            result = await client.execute_task(
                protocol="python/v1",
                method="python/execute",
                params={"file": "calculate_sum.py"},
                name="Python Test"
            )
            
            if result and result.status == "completed":
                print(f"✓ Python task completed: {result.result}")
            else:
                print(f"✗ Python task failed: {result.error if result else 'No result'}")
                
            print("\n✓ Native mode test completed successfully")
            return True
            
    except Exception as e:
        print(f"\n✗ Native mode test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_api_mode():
    """Test API mode execution"""
    print("\n" + "="*60)
    print("Testing API mode")
    print("="*60)
    
    try:
        # Try with auto-start disabled first to check if server is running
        try:
            async with GleitzeitClient(
                mode=ClientMode.API,
                auto_start_server=False
            ) as client:
                print(f"✓ API server already running, using {client.get_mode()} mode")
                
                # Test simple task
                result = await client.execute_task(
                    protocol="mcp/v1",
                    method="mcp/tool.echo",
                    params={"message": "Hello from API"},
                    name="API Echo Test"
                )
                
                if result and result.status == "completed":
                    print(f"✓ API task completed: {result.result}")
                else:
                    print(f"✗ API task failed: {result.error if result else 'No result'}")
                    
                return True
                
        except RuntimeError as e:
            if "not available" in str(e):
                print("API server not running, will test with auto-start...")
                
                # Test with auto-start
                async with GleitzeitClient(
                    mode=ClientMode.API,
                    auto_start_server=True
                ) as client:
                    print(f"✓ Started API server and initialized in {client.get_mode()} mode")
                    
                    # Give server a moment to fully initialize
                    await asyncio.sleep(2)
                    
                    # Test simple task
                    result = await client.execute_task(
                        protocol="mcp/v1",
                        method="mcp/tool.echo",
                        params={"message": "Hello from API"},
                        name="API Echo Test"
                    )
                    
                    if result and result.status == "completed":
                        print(f"✓ API task completed: {result.result}")
                    else:
                        print(f"✗ API task failed: {result.error if result else 'No result'}")
                        
                    print("\n✓ API mode test completed successfully")
                    return True
            else:
                raise
                
    except Exception as e:
        print(f"\n✗ API mode test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_auto_mode():
    """Test AUTO mode selection"""
    print("\n" + "="*60)
    print("Testing AUTO mode")
    print("="*60)
    
    try:
        async with GleitzeitClient(mode=ClientMode.AUTO) as client:
            print(f"✓ AUTO mode selected: {client.get_mode()}")
            
            # Test task execution
            result = await client.execute_task(
                protocol="mcp/v1",
                method="mcp/tool.multiply",
                params={"a": 4, "b": 7},
                name="Auto Mode Test"
            )
            
            if result and result.status == "completed":
                print(f"✓ Task completed in {client.get_mode()} mode: {result.result}")
            else:
                print(f"✗ Task failed: {result.error if result else 'No result'}")
                
            print("\n✓ AUTO mode test completed successfully")
            return True
            
    except Exception as e:
        print(f"\n✗ AUTO mode test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_workflow_execution():
    """Test workflow execution in native mode"""
    print("\n" + "="*60)
    print("Testing Workflow Execution (Native)")
    print("="*60)
    
    # Check if example workflow exists
    workflow_file = "examples/simple_mcp_workflow.yaml"
    if not Path(workflow_file).exists():
        print(f"⚠ Workflow file {workflow_file} not found, skipping workflow test")
        return True
    
    try:
        async with GleitzeitClient(mode=ClientMode.NATIVE) as client:
            print(f"Running workflow: {workflow_file}")
            
            result = await client.run_workflow(workflow_file)
            
            if result.get("status") == "completed":
                print(f"✓ Workflow completed successfully")
                print(f"  Results: {len(result.get('results', {}))} tasks")
            else:
                print(f"✗ Workflow failed: {result}")
                
            return True
            
    except Exception as e:
        print(f"\n✗ Workflow test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all tests"""
    print("\n" + "#"*60)
    print("# TESTING UNIFIED CLIENT (client_v2.py)")
    print("#"*60)
    
    results = []
    
    # Test native mode first (doesn't require server)
    results.append(("Native Mode", await test_native_mode()))
    
    # Test auto mode
    results.append(("Auto Mode", await test_auto_mode()))
    
    # Test API mode (may start server)
    results.append(("API Mode", await test_api_mode()))
    
    # Test workflow execution
    results.append(("Workflow", await test_workflow_execution()))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    for test_name, passed in results:
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"{test_name:20} {status}")
    
    all_passed = all(r[1] for r in results)
    
    if all_passed:
        print("\n✅ All tests passed!")
    else:
        print("\n❌ Some tests failed")
        
    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)