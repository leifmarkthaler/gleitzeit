#!/usr/bin/env python
"""
Test agent workflow using Gleitzeit's workflow execution
"""

import asyncio
import yaml
import logging
from pathlib import Path

from gleitzeit.core.workflow_loader import WorkflowLoader
from gleitzeit.core.execution_engine import ExecutionEngine
from gleitzeit.hub.resource_manager import ResourceManager
from gleitzeit.registry import get_provider_registry
from gleitzeit.persistence.unified_adapter import UnifiedPersistenceAdapter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_agent_workflow():
    """Test agent workflow execution"""
    
    print("\n" + "="*60)
    print("TESTING AGENT WORKFLOW WITH GLEITZEIT")
    print("="*60)
    
    # Create a simple agent workflow
    workflow_yaml = """
name: "Test Agent Workflow"
description: "Test agent capabilities"

tasks:
  - id: "chat_test"
    name: "Chat with agent"
    protocol: "agent"
    method: "chat"
    params:
      message: "What is 2 + 2?"
      session_id: "test_session"
    
  - id: "analyze_test"
    name: "Analyze response"
    protocol: "agent"
    method: "analyze"
    dependencies: ["chat_test"]
    params:
      content: "${chat_test.response}"
      question: "Is this answer correct?"
"""
    
    try:
        # Initialize persistence
        logger.info("Initializing persistence...")
        persistence = UnifiedPersistenceAdapter()
        await persistence.initialize()
        
        # Initialize resource manager
        logger.info("Initializing resource manager...")
        resource_manager = ResourceManager("test-manager")
        await resource_manager.start()
        
        # Create Ollama hub (will auto-discover)
        logger.info("Creating Ollama hub...")
        ollama_hub = await resource_manager.create_ollama_hub(
            hub_id="ollama",
            auto_discover=True
        )
        
        # Create Agent hub
        logger.info("Creating Agent hub...")
        agent_hub = await resource_manager.create_agent_hub(
            hub_id="agent",
            max_agents=3
        )
        
        # Initialize execution engine
        logger.info("Initializing execution engine...")
        engine = ExecutionEngine(
            engine_id="test-engine",
            persistence=persistence,
            resource_manager=resource_manager
        )
        
        # Load workflow
        logger.info("Loading workflow...")
        loader = WorkflowLoader()
        workflow_dict = yaml.safe_load(workflow_yaml)
        workflow = loader.load_from_dict(workflow_dict)
        
        print(f"\n📋 Workflow: {workflow.name}")
        print(f"   Tasks: {len(workflow.tasks)}")
        for task in workflow.tasks:
            print(f"   - {task.id}: {task.name}")
        
        # Execute workflow
        print("\n🚀 Executing workflow...")
        execution = await engine.execute_workflow(workflow)
        
        print(f"\n✅ Workflow execution completed!")
        print(f"   Status: {execution.status}")
        print(f"   Duration: {execution.duration_seconds:.2f}s")
        
        # Check task results
        print("\n📊 Task Results:")
        for task_id, result in execution.task_results.items():
            print(f"\n   {task_id}:")
            print(f"   - Status: {result.status}")
            if result.result:
                result_str = str(result.result)[:200]
                print(f"   - Result: {result_str}...")
            if result.error:
                print(f"   - Error: {result.error}")
        
        return execution
        
    except Exception as e:
        logger.error(f"Workflow execution failed: {e}", exc_info=True)
        raise
    
    finally:
        # Cleanup
        if 'engine' in locals():
            await engine.stop()
        if 'resource_manager' in locals():
            await resource_manager.stop()
        if 'persistence' in locals():
            await persistence.cleanup()


async def test_direct_agent_execution():
    """Test direct agent execution without workflow"""
    
    print("\n" + "="*60)
    print("TESTING DIRECT AGENT EXECUTION")
    print("="*60)
    
    try:
        # Initialize resource manager
        resource_manager = ResourceManager("direct-test")
        await resource_manager.start()
        
        # Create hubs
        ollama_hub = await resource_manager.create_ollama_hub()
        agent_hub = await resource_manager.create_agent_hub()
        
        # Execute agent task directly
        print("\n🤖 Testing chat agent...")
        result = await agent_hub.execute_agent_task(
            method="chat",
            parameters={
                "message": "Hello, how are you?"
            }
        )
        
        print(f"\n💬 Response received:")
        print(f"   {result.get('response', 'No response')[:200]}...")
        
        # Test research agent
        print("\n🔬 Testing research agent...")
        research = await agent_hub.execute_agent_task(
            method="research",
            parameters={
                "topic": "Benefits of Python",
                "max_steps": 2
            }
        )
        
        print(f"\n📚 Research completed:")
        print(f"   Steps: {research.get('steps_executed', 0)}")
        print(f"   Success: {research.get('success', False)}")
        if research.get('report'):
            print(f"   Report preview: {research['report'][:200]}...")
        
        return True
        
    except Exception as e:
        logger.error(f"Direct execution failed: {e}", exc_info=True)
        return False
    
    finally:
        if 'resource_manager' in locals():
            await resource_manager.stop()


async def main():
    """Main test runner"""
    
    print("\n🧪 GLEITZEIT AGENT WORKFLOW TEST")
    print("="*60)
    print("\nThis test will:")
    print("1. Test direct agent execution")
    print("2. Test agent workflow execution")
    print("\nGleitzeit will handle Ollama availability automatically.")
    print("="*60)
    
    # Test 1: Direct execution
    print("\n[TEST 1] Direct Agent Execution")
    direct_success = await test_direct_agent_execution()
    
    # Test 2: Workflow execution
    print("\n[TEST 2] Workflow Execution")
    try:
        workflow_result = await test_agent_workflow()
        workflow_success = workflow_result is not None
    except Exception as e:
        print(f"❌ Workflow test failed: {e}")
        workflow_success = False
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print(f"✅ Direct execution: {'PASSED' if direct_success else 'FAILED'}")
    print(f"✅ Workflow execution: {'PASSED' if workflow_success else 'FAILED'}")
    
    if direct_success and workflow_success:
        print("\n🎉 All tests passed!")
    else:
        print("\n⚠️ Some tests failed")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nTest interrupted")
    except Exception as e:
        print(f"\n\nTest failed: {e}")
        import traceback
        traceback.print_exc()