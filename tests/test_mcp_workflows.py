#!/usr/bin/env python3
"""
Test MCP workflows
"""

import asyncio
import sys
import os
sys.path.insert(0, 'src')

from gleitzeit.cli.gleitzeit_cli import GleitzeitCLI

async def test_mcp_workflows():
    """Test all MCP workflow files"""
    
    workflows = [
        "examples/simple_mcp_workflow.yaml",
        "examples/mcp_workflow.yaml",
        "tests/mcp_test_workflow.yaml"
    ]
    
    results = []
    
    for workflow_file in workflows:
        print(f"\n{'='*60}")
        print(f"Testing: {workflow_file}")
        print('='*60)
        
        try:
            cli = GleitzeitCLI()
            success = await cli.run(workflow_file)
            
            if success:
                print(f"✅ {workflow_file} - PASSED")
                results.append((workflow_file, True))
            else:
                print(f"❌ {workflow_file} - FAILED")
                results.append((workflow_file, False))
                
        except Exception as e:
            print(f"❌ {workflow_file} - ERROR: {e}")
            results.append((workflow_file, False))
    
    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print('='*60)
    
    passed = sum(1 for _, result in results if result)
    failed = len(results) - passed
    
    for workflow, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{workflow}: {status}")
    
    print(f"\nTotal: {passed} passed, {failed} failed out of {len(results)} workflows")
    
    return failed == 0

if __name__ == "__main__":
    success = asyncio.run(test_mcp_workflows())
    sys.exit(0 if success else 1)