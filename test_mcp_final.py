#!/usr/bin/env python3
"""
MCP Integration Test - Final Version

Demonstrates the working MCP integration in Gleitzeit.
"""
import asyncio
import logging
import sys
import yaml
import tempfile
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


async def test_simple_mcp_workflow():
    """Test SimpleMCPProvider with a workflow"""
    logger.info("\n" + "="*60)
    logger.info("TEST: SimpleMCPProvider via Workflow")
    logger.info("="*60)
    
    from gleitzeit import GleitzeitClient
    
    # Create a workflow using MCP tools
    workflow = {
        "name": "Simple MCP Test",
        "tasks": [
            {
                "id": "echo",
                "method": "mcp/tool.echo",
                "parameters": {"message": "Hello, MCP!"}
            },
            {
                "id": "add",
                "method": "mcp/tool.add",
                "parameters": {"a": 10, "b": 20}
            },
            {
                "id": "multiply",
                "method": "mcp/tool.multiply",
                "parameters": {"a": 5, "b": 6}
            },
            {
                "id": "concat",
                "method": "mcp/tool.concat",
                "parameters": {"strings": ["Hello", " ", "World"]}
            }
        ]
    }
    
    # Save workflow to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(workflow, f)
        workflow_file = f.name
    
    try:
        async with GleitzeitClient(mode="native") as client:
            logger.info("\nExecuting MCP workflow...")
            results = await client.run_workflow(workflow_file)
            
            logger.info("\n✅ Results:")
            for task_id in ["echo", "add", "multiply", "concat"]:
                if task_id in results:
                    result = results[task_id]
                    if hasattr(result, 'result'):
                        logger.info(f"  {task_id}: {result.result}")
                    else:
                        logger.info(f"  {task_id}: {result}")
            
            return True
            
    except Exception as e:
        logger.error(f"\n❌ Test failed: {e}")
        return False
    finally:
        import os
        os.unlink(workflow_file)


async def test_mcp_hub_config():
    """Test MCPHub with configuration"""
    logger.info("\n" + "="*60)
    logger.info("TEST: MCPHub with Test Server")
    logger.info("="*60)
    
    from gleitzeit import GleitzeitClient
    
    # Configuration for external MCP server
    config = {
        "mcp": {
            "servers": [
                {
                    "name": "test-server",
                    "connection_type": "stdio",
                    "command": ["python", "test_mcp_server.py"],
                    "working_dir": str(Path(__file__).parent),
                    "auto_start": True,
                    "tool_prefix": "test."
                }
            ]
        }
    }
    
    # Create workflow using external server tools
    workflow = {
        "name": "External MCP Test",
        "tasks": [
            {
                "id": "test_echo",
                "method": "mcp/tool.test.echo",
                "parameters": {"message": "External MCP works!"}
            },
            {
                "id": "test_reverse",
                "method": "mcp/tool.test.reverse",
                "parameters": {"text": "Hello"}
            },
            {
                "id": "test_uppercase",
                "method": "mcp/tool.test.uppercase",
                "parameters": {"text": "make me big"}
            }
        ]
    }
    
    # Save workflow
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(workflow, f)
        workflow_file = f.name
    
    try:
        async with GleitzeitClient(mode="native", native_config=config) as client:
            logger.info("\nExecuting workflow with external MCP server...")
            
            # Give server time to start
            await asyncio.sleep(2)
            
            results = await client.run_workflow(workflow_file)
            
            logger.info("\n✅ Results from external server:")
            for task_id in ["test_echo", "test_reverse", "test_uppercase"]:
                if task_id in results:
                    result = results[task_id]
                    if hasattr(result, 'result'):
                        logger.info(f"  {task_id}: {result.result}")
                    else:
                        logger.info(f"  {task_id}: {result}")
            
            return True
            
    except Exception as e:
        logger.error(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        import os
        os.unlink(workflow_file)


async def test_direct_mcp_hub():
    """Test MCPHub directly"""
    logger.info("\n" + "="*60)
    logger.info("TEST: Direct MCPHub Usage")
    logger.info("="*60)
    
    from gleitzeit.hub.mcp_hub import MCPHub
    from gleitzeit.providers.mcp_hub_provider import MCPHubProvider
    
    # Create hub
    hub = MCPHub(auto_discover=False)
    
    try:
        await hub.initialize()
        logger.info(f"Hub initialized")
        
        # Create provider
        provider = MCPHubProvider(hub=hub)
        await provider.initialize()
        
        # Test built-in SimpleMCPProvider is used as fallback
        methods = provider.get_supported_methods()
        logger.info(f"\nAvailable methods: {len(methods)}")
        
        # List tools
        result = await provider.handle_request("mcp/tools/list", {})
        logger.info(f"Tools available: {result.get('count', 0)}")
        
        logger.info("\n✅ Direct hub test passed!")
        return True
        
    except Exception as e:
        logger.error(f"\n❌ Direct hub test failed: {e}")
        return False
    finally:
        await hub.cleanup()


async def main():
    """Run all tests"""
    logger.info("\n" + "="*70)
    logger.info(" MCP INTEGRATION TEST SUITE - FINAL")
    logger.info("="*70)
    
    results = []
    
    # Test 1: Simple MCP Provider via workflow
    logger.info("\n[1/3] Testing SimpleMCPProvider...")
    results.append(await test_simple_mcp_workflow())
    
    # Test 2: MCP Hub with external server (optional)
    if Path("test_mcp_server.py").exists():
        logger.info("\n[2/3] Testing MCPHub with external server...")
        results.append(await test_mcp_hub_config())
    else:
        logger.info("\n[2/3] Skipping external server test (test_mcp_server.py not found)")
        results.append(None)
    
    # Test 3: Direct hub usage
    logger.info("\n[3/3] Testing direct MCPHub usage...")
    results.append(await test_direct_mcp_hub())
    
    # Summary
    logger.info("\n" + "="*70)
    logger.info(" SUMMARY")
    logger.info("="*70)
    
    test_names = [
        "SimpleMCPProvider (Workflow)",
        "MCPHub (External Server)",
        "Direct MCPHub"
    ]
    
    passed = 0
    total = 0
    for name, result in zip(test_names, results):
        if result is not None:
            total += 1
            if result:
                passed += 1
                logger.info(f"✅ {name}: PASSED")
            else:
                logger.info(f"❌ {name}: FAILED")
        else:
            logger.info(f"⏭️  {name}: SKIPPED")
    
    logger.info(f"\nResults: {passed}/{total} tests passed")
    
    if passed == total and total > 0:
        logger.info("\n🎉 All tests passed successfully!")
        return 0
    else:
        logger.info(f"\n⚠️  Some tests failed or were skipped")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)