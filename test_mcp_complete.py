#!/usr/bin/env python3
"""
Complete MCP Integration Test

Tests both SimpleMCPProvider and MCPHub with external servers.
"""
import asyncio
import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_simple_mcp_provider():
    """Test the built-in SimpleMCPProvider"""
    logger.info("\n" + "="*60)
    logger.info("TEST 1: SimpleMCPProvider (Built-in Tools)")
    logger.info("="*60)
    
    from gleitzeit import GleitzeitClient
    
    try:
        async with GleitzeitClient(mode="native") as client:
            logger.info("Client initialized with SimpleMCPProvider")
            
            # Test echo tool
            logger.info("\nTesting echo tool...")
            task = {
                "id": "echo_test",
                "name": "Echo Test",
                "protocol": "mcp/v1",
                "method": "mcp/tool.echo",
                "parameters": {"message": "Hello, MCP!"}
            }
            
            from gleitzeit.core.models import Task
            task_obj = Task(**task)
            result = await client.engine.execute_task(task_obj)
            logger.info(f"Echo result: {result}")
            
            # Test add tool
            logger.info("\nTesting add tool...")
            task = {
                "id": "add_test",
                "name": "Add Test",
                "protocol": "mcp/v1",
                "method": "mcp/tool.add",
                "parameters": {"a": 10, "b": 20}
            }
            task_obj = Task(**task)
            result = await client.engine.execute_task(task_obj)
            logger.info(f"Add result: {result}")
            
            # Test multiply tool
            logger.info("\nTesting multiply tool...")
            task = {
                "id": "multiply_test",
                "name": "Multiply Test",
                "protocol": "mcp/v1",
                "method": "mcp/tool.multiply",
                "parameters": {"a": 5, "b": 7}
            }
            task_obj = Task(**task)
            result = await client.engine.execute_task(task_obj)
            logger.info(f"Multiply result: {result}")
            
            logger.info("\n✅ SimpleMCPProvider tests passed!")
            return True
            
    except Exception as e:
        logger.error(f"❌ SimpleMCPProvider test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_mcp_hub_with_external():
    """Test MCPHub with external test server"""
    logger.info("\n" + "="*60)
    logger.info("TEST 2: MCPHub with External Server")
    logger.info("="*60)
    
    from gleitzeit import GleitzeitClient
    from gleitzeit.core.models import Task
    
    # Configuration with test MCP server
    config = {
        "mcp": {
            "auto_discover": True,
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
    
    try:
        async with GleitzeitClient(mode="native", native_config=config) as client:
            logger.info("Client initialized with MCPHub")
            
            # Give server time to start
            await asyncio.sleep(1)
            
            # Check if MCPHub is being used
            provider = client.engine.registry.get_provider_for_method("mcp/v1", "tool.test.echo")
            logger.info(f"Provider type: {type(provider).__name__}")
            
            # Test echo tool from external server
            logger.info("\nTesting external echo tool...")
            task = {
                "id": "ext_echo_test",
                "name": "External Echo Test",
                "protocol": "mcp/v1",
                "method": "mcp/tool.test.echo",
                "parameters": {"message": "Hello from external MCP!"}
            }
            task_obj = Task(**task)
            result = await client.engine.execute_task(task_obj)
            logger.info(f"External echo result: {result}")
            
            # Test reverse tool
            logger.info("\nTesting external reverse tool...")
            task = {
                "id": "ext_reverse_test",
                "name": "External Reverse Test",
                "protocol": "mcp/v1",
                "method": "mcp/tool.test.reverse",
                "parameters": {"text": "Hello World"}
            }
            task_obj = Task(**task)
            result = await client.engine.execute_task(task_obj)
            logger.info(f"External reverse result: {result}")
            
            # Test uppercase tool
            logger.info("\nTesting external uppercase tool...")
            task = {
                "id": "ext_uppercase_test",
                "name": "External Uppercase Test",
                "protocol": "mcp/v1",
                "method": "mcp/tool.test.uppercase",
                "parameters": {"text": "make me uppercase"}
            }
            task_obj = Task(**task)
            result = await client.engine.execute_task(task_obj)
            logger.info(f"External uppercase result: {result}")
            
            logger.info("\n✅ MCPHub with external server tests passed!")
            return True
            
    except Exception as e:
        logger.error(f"❌ MCPHub test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_mcp_workflow():
    """Test a workflow using MCP tools"""
    logger.info("\n" + "="*60)
    logger.info("TEST 3: Workflow with MCP Tools")
    logger.info("="*60)
    
    from gleitzeit import GleitzeitClient
    
    workflow = {
        "name": "MCP Test Workflow",
        "tasks": [
            {
                "id": "step1",
                "method": "mcp/tool.echo",
                "parameters": {
                    "message": "Starting workflow"
                }
            },
            {
                "id": "step2",
                "method": "mcp/tool.add",
                "parameters": {
                    "a": 100,
                    "b": 200
                }
            },
            {
                "id": "step3",
                "method": "mcp/tool.multiply",
                "dependencies": ["step2"],
                "parameters": {
                    "a": 3,
                    "b": 4
                }
            }
        ]
    }
    
    try:
        async with GleitzeitClient(mode="native") as client:
            logger.info("Running MCP workflow...")
            
            # Save workflow to temp file
            import tempfile
            import yaml
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
                yaml.dump(workflow, f)
                workflow_file = f.name
            
            try:
                results = await client.run_workflow(workflow_file)
            finally:
                import os
                os.unlink(workflow_file)
            
            logger.info("\nWorkflow Results:")
            for task_id, result in results.items():
                if hasattr(result, 'result'):
                    logger.info(f"  {task_id}: {result.result}")
                else:
                    logger.info(f"  {task_id}: {result}")
            
            logger.info("\n✅ MCP workflow test passed!")
            return True
            
    except Exception as e:
        logger.error(f"❌ MCP workflow test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_mcp_hub_direct():
    """Test using MCPHub directly"""
    logger.info("\n" + "="*60)
    logger.info("TEST 4: Direct MCPHub Usage")
    logger.info("="*60)
    
    from gleitzeit.hub.mcp_hub import MCPHub
    from gleitzeit.providers.mcp_hub_provider import MCPHubProvider
    
    # Create hub with test server
    config = {
        "servers": [
            {
                "name": "test-direct",
                "connection_type": "stdio",
                "command": ["python", "test_mcp_server.py"],
                "working_dir": str(Path(__file__).parent),
                "auto_start": True,
                "tool_prefix": "direct."
            }
        ]
    }
    
    hub = MCPHub(config_data=config)
    
    try:
        await hub.initialize()
        logger.info(f"Hub initialized with {len(hub.instances)} servers")
        logger.info(f"Available tools: {list(hub.tool_registry.keys())}")
        
        # Test tool call
        if hub.tool_registry:
            tool_name = list(hub.tool_registry.keys())[0]
            logger.info(f"\nCalling tool: {tool_name}")
            
            result = await hub.call_tool(
                tool_name,
                {"message": "Direct hub test"} if "echo" in tool_name else {"text": "test"}
            )
            logger.info(f"Result: {result}")
        
        # Test with provider
        provider = MCPHubProvider(hub=hub)
        await provider.initialize()
        
        # List servers
        servers_result = await provider.handle_request("mcp/servers", {})
        logger.info(f"\nServers: {servers_result}")
        
        logger.info("\n✅ Direct MCPHub test passed!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Direct MCPHub test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await hub.cleanup()


async def main():
    """Run all tests"""
    logger.info("\n" + "="*60)
    logger.info("MCP INTEGRATION TEST SUITE")
    logger.info("="*60)
    
    results = []
    
    # Test 1: SimpleMCPProvider
    results.append(await test_simple_mcp_provider())
    
    # Test 2: MCPHub with external server
    results.append(await test_mcp_hub_with_external())
    
    # Test 3: Workflow with MCP tools
    results.append(await test_mcp_workflow())
    
    # Test 4: Direct hub usage
    results.append(await test_mcp_hub_direct())
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("TEST SUMMARY")
    logger.info("="*60)
    
    test_names = [
        "SimpleMCPProvider",
        "MCPHub with External",
        "MCP Workflow",
        "Direct MCPHub"
    ]
    
    for i, (name, passed) in enumerate(zip(test_names, results)):
        status = "✅ PASSED" if passed else "❌ FAILED"
        logger.info(f"{i+1}. {name}: {status}")
    
    total = len(results)
    passed = sum(results)
    logger.info(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("\n🎉 All tests passed!")
        return 0
    else:
        logger.info(f"\n⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)