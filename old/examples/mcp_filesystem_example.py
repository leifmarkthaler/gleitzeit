#!/usr/bin/env python3
"""
Example: Integrating MCP Filesystem Server with Gleitzeit V4

This example shows how to integrate an external MCP server (filesystem)
with Gleitzeit V4 to create workflows that can interact with files.
"""

import asyncio
import logging
import json
import os
import tempfile
from pathlib import Path

from gleitzeit_v4.core import Task, Workflow, Priority, ExecutionEngine, ExecutionMode
from gleitzeit_v4.core.workflow_manager import WorkflowManager
from gleitzeit_v4.registry import ProtocolProviderRegistry
from gleitzeit_v4.queue import QueueManager, DependencyResolver
from gleitzeit_v4.integrations.mcp_integration import create_mcp_integration, get_common_mcp_config

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def setup_gleitzeit_with_mcp():
    """Setup Gleitzeit V4 system with MCP filesystem integration"""
    
    # Initialize core Gleitzeit components
    registry = ProtocolProviderRegistry()
    queue_manager = QueueManager()
    dependency_resolver = DependencyResolver()
    execution_engine = ExecutionEngine(registry, queue_manager, dependency_resolver)
    workflow_manager = WorkflowManager(execution_engine, dependency_resolver)
    
    # Create temporary directory for demo
    temp_dir = tempfile.mkdtemp(prefix="gleitzeit-mcp-demo-")
    logger.info(f"Created demo directory: {temp_dir}")
    
    # Setup some demo files
    demo_files = {
        "data.txt": "This is sample data for processing\nLine 2\nLine 3",
        "config.json": json.dumps({"setting1": "value1", "setting2": 42}, indent=2),
        "notes.md": "# Demo Notes\n\nThis is a markdown file for testing."
    }
    
    for filename, content in demo_files.items():
        with open(Path(temp_dir) / filename, "w") as f:
            f.write(content)
    
    # Create MCP integration
    mcp_integration = await create_mcp_integration(registry, [
        get_common_mcp_config("filesystem", 
                             provider_id="demo-filesystem",
                             args=[temp_dir])  # Allow access to our demo directory
    ])
    
    logger.info(f"✅ Gleitzeit V4 with MCP integration ready!")
    logger.info(f"Demo files available in: {temp_dir}")
    
    return {
        "execution_engine": execution_engine,
        "workflow_manager": workflow_manager,
        "mcp_integration": mcp_integration,
        "temp_dir": temp_dir
    }


async def demo_mcp_filesystem_operations(system):
    """Demonstrate MCP filesystem operations via Gleitzeit tasks"""
    logger.info("\n🗂️ === Demo: MCP Filesystem Operations ===")
    
    execution_engine = system["execution_engine"]
    temp_dir = system["temp_dir"]
    
    # Task 1: List files in directory
    list_task = Task(
        id="list-files",
        name="List Files",
        protocol="filesystem/v1",
        method="tool.list_directory", 
        params={
            "arguments": {
                "path": temp_dir
            }
        },
        priority=Priority.HIGH
    )
    
    await execution_engine.submit_task(list_task)
    list_result = await execution_engine._execute_single_task()
    
    logger.info(f"📁 Files found: {list_result.result}")
    
    # Task 2: Read a file
    read_task = Task(
        id="read-config",
        name="Read Config File",
        protocol="filesystem/v1", 
        method="tool.read_file",
        params={
            "arguments": {
                "path": os.path.join(temp_dir, "config.json")
            }
        },
        priority=Priority.NORMAL
    )
    
    await execution_engine.submit_task(read_task)
    read_result = await execution_engine._execute_single_task()
    
    logger.info(f"📄 Config file content: {read_result.result}")
    
    # Task 3: Create a new file
    new_content = "This file was created by Gleitzeit V4 via MCP!\nTimestamp: " + str(asyncio.get_event_loop().time())
    
    write_task = Task(
        id="write-file", 
        name="Create New File",
        protocol="filesystem/v1",
        method="tool.write_file",
        params={
            "arguments": {
                "path": os.path.join(temp_dir, "gleitzeit_created.txt"),
                "content": new_content
            }
        },
        priority=Priority.NORMAL
    )
    
    await execution_engine.submit_task(write_task)
    write_result = await execution_engine._execute_single_task()
    
    logger.info(f"✍️ File created: {write_result.result}")
    
    return True


async def demo_mcp_workflow_integration(system):
    """Demonstrate MCP integration in complex workflows"""
    logger.info("\n🔄 === Demo: MCP in Workflow Context ===")
    
    workflow_manager = system["workflow_manager"]
    execution_engine = system["execution_engine"]
    temp_dir = system["temp_dir"]
    
    # Create a workflow that processes files using MCP
    workflow_id = "file-processing-workflow"
    
    tasks = [
        # Step 1: List all files
        Task(
            id="scan-directory",
            name="Scan Directory for Files",
            protocol="filesystem/v1",
            method="tool.list_directory",
            params={
                "arguments": {
                    "path": temp_dir
                }
            },
            workflow_id=workflow_id,
            priority=Priority.HIGH
        ),
        
        # Step 2: Read data file
        Task(
            id="read-data-file",
            name="Read Data File",
            protocol="filesystem/v1", 
            method="tool.read_file",
            params={
                "arguments": {
                    "path": os.path.join(temp_dir, "data.txt")
                }
            },
            workflow_id=workflow_id,
            priority=Priority.NORMAL,
            dependencies=["scan-directory"]  # Wait for scan to complete
        ),
        
        # Step 3: Process and write summary
        # Note: This would need parameter substitution to work fully
        Task(
            id="create-summary",
            name="Create File Summary",
            protocol="filesystem/v1",
            method="tool.write_file", 
            params={
                "arguments": {
                    "path": os.path.join(temp_dir, "summary.txt"),
                    "content": f"File Processing Summary\n" +
                              f"Directory: {temp_dir}\n" +
                              f"Processed by: Gleitzeit V4 + MCP\n" +
                              f"Files found: [files would be substituted here]\n" +
                              f"Data content: [data would be substituted here]"
                }
            },
            workflow_id=workflow_id,
            priority=Priority.NORMAL,
            dependencies=["scan-directory", "read-data-file"]
        )
    ]
    
    workflow = Workflow(
        id=workflow_id,
        name="File Processing with MCP",
        description="Demonstrate file operations using MCP filesystem server",
        tasks=tasks
    )
    
    # Start execution engine in event-driven mode
    engine_task = asyncio.create_task(execution_engine.start(ExecutionMode.EVENT_DRIVEN))
    
    try:
        # Execute workflow
        execution = await workflow_manager.execute_workflow(workflow)
        logger.info(f"Started workflow execution: {execution.execution_id}")
        
        # Wait for completion
        max_wait = 30
        waited = 0
        while execution.execution_id in workflow_manager.active_executions and waited < max_wait:
            await asyncio.sleep(1)
            waited += 1
            
            status = workflow_manager.get_execution_status(execution.execution_id)
            if status:
                logger.info(f"Workflow progress: {status['completed_tasks']}/{status['total_tasks']} tasks completed")
        
        # Check results
        final_status = workflow_manager.get_execution_status(execution.execution_id)
        if final_status and final_status["status"] == "completed":
            logger.info("✅ Workflow completed successfully!")
            
            # Show results for each task
            for task in workflow.tasks:
                result = execution_engine.get_task_result(task.id)
                if result and result.status.value == "completed":
                    logger.info(f"Task '{task.name}' completed successfully")
                    logger.info(f"Result preview: {str(result.result)[:200]}...")
        else:
            logger.error(f"❌ Workflow failed: {final_status}")
            
    finally:
        # Stop execution engine
        await execution_engine.stop()
        engine_task.cancel()
        try:
            await engine_task
        except asyncio.CancelledError:
            pass
    
    return True


async def demo_mcp_server_management(system):
    """Demonstrate MCP server management capabilities"""
    logger.info("\n⚙️ === Demo: MCP Server Management ===")
    
    mcp_integration = system["mcp_integration"]
    
    # List all MCP servers
    servers = await mcp_integration.list_mcp_servers()
    logger.info(f"🖥️ Active MCP servers: {len(servers)}")
    
    for server in servers:
        logger.info(f"  • {server['name']} ({server['provider_id']})")
        logger.info(f"    Status: {server['status']}")
        logger.info(f"    Tools: {len(server['tools'])} - {server['tools']}")
        logger.info(f"    Resources: {len(server['resources'])}")
        logger.info(f"    Prompts: {len(server['prompts'])}")
    
    # Get detailed server information
    if servers:
        server = servers[0]
        execution_engine = system["execution_engine"]
        
        info_task = Task(
            id="server-info",
            name="Get MCP Server Info",
            protocol=server["protocol_id"],
            method="server_info",
            params={},
            priority=Priority.NORMAL
        )
        
        await execution_engine.submit_task(info_task)
        info_result = await execution_engine._execute_single_task()
        
        logger.info(f"📊 Server details: {json.dumps(info_result.result, indent=2)}")
    
    return True


async def cleanup_demo(system):
    """Cleanup demo resources"""
    logger.info("\n🧹 === Cleanup ===")
    
    # Shutdown MCP integration
    await system["mcp_integration"].shutdown_all()
    
    # Remove demo directory
    import shutil
    shutil.rmtree(system["temp_dir"])
    logger.info(f"Removed demo directory: {system['temp_dir']}")


async def main():
    """Main demo function"""
    logger.info("🚀 Gleitzeit V4 + MCP Integration Demo")
    
    # Check if Node.js is available (required for MCP filesystem server)
    try:
        result = await asyncio.create_subprocess_exec(
            "node", "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await result.communicate()
        
        if result.returncode != 0:
            logger.error("❌ Node.js is required but not found. Please install Node.js to run this demo.")
            return
        
        node_version = stdout.decode().strip()
        logger.info(f"✅ Node.js detected: {node_version}")
        
    except FileNotFoundError:
        logger.error("❌ Node.js is required but not found. Please install Node.js to run this demo.")
        return
    
    try:
        # Setup system
        logger.info("Setting up Gleitzeit V4 with MCP filesystem integration...")
        system = await setup_gleitzeit_with_mcp()
        
        # Run demos
        await demo_mcp_filesystem_operations(system)
        await demo_mcp_workflow_integration(system)
        await demo_mcp_server_management(system)
        
        logger.info("\n🎉 Demo completed successfully!")
        logger.info("\nKey Features Demonstrated:")
        logger.info("✅ MCP server integration with Gleitzeit V4")
        logger.info("✅ File system operations via MCP tools")
        logger.info("✅ MCP tools as Gleitzeit tasks")
        logger.info("✅ Workflow orchestration with MCP providers")
        logger.info("✅ MCP server management and monitoring")
        
        # Wait a moment before cleanup
        await asyncio.sleep(1)
        
    except Exception as e:
        logger.error(f"❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # Always cleanup
        if 'system' in locals():
            await cleanup_demo(system)


if __name__ == "__main__":
    asyncio.run(main())