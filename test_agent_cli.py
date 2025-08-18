#!/usr/bin/env python
"""Test agent workflow execution via CLI"""

import asyncio
import sys
import json
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.core.workflow_loader import load_workflow_from_file
from gleitzeit.core.execution_engine import ExecutionEngine
from gleitzeit.hub.resource_manager import ResourceManager
from gleitzeit.persistence.unified_persistence import UnifiedPersistenceAdapter
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.providers.agent_provider import AgentProvider


async def test_agent_cli():
    """Test agent workflow execution"""
    
    print("\n=== Testing Agent Workflow via CLI ===\n")
    
    # Initialize persistence
    persistence = UnifiedPersistenceAdapter()
    await persistence.initialize()
    print("✓ Persistence initialized")
    
    # Initialize resource manager
    resource_manager = ResourceManager("test-cli-manager")
    await resource_manager.start()
    print("✓ Resource manager started")
    
    # Try to create Ollama hub (will fail if Ollama not running)
    try:
        ollama_hub = await resource_manager.create_ollama_hub()
        print("✓ Ollama hub created (real LLM available)")
    except Exception as e:
        print(f"⚠ Ollama hub failed: {e}")
        print("  Using mock LLM responses")
    
    # Create agent hub
    agent_hub = await resource_manager.create_agent_hub(max_agents=5)
    print("✓ Agent hub created")
    
    # Initialize registry and add agent provider
    registry = ProtocolProviderRegistry()
    agent_provider = AgentProvider(agent_hub=agent_hub)
    await registry.register_provider("agent", agent_provider)
    print("✓ Agent provider registered")
    
    # Create execution engine
    engine = ExecutionEngine(
        persistence=persistence,
        registry=registry,
        resource_manager=resource_manager
    )
    print("✓ Execution engine created")
    
    # Load workflow
    workflow_file = Path(__file__).parent / "test_agent_cli.yaml"
    print(f"\nLoading workflow: {workflow_file}")
    workflow = load_workflow_from_file(str(workflow_file))
    print(f"✓ Workflow loaded: {workflow.name}")
    print(f"  Tasks: {len(workflow.tasks)}")
    for task in workflow.tasks:
        print(f"    - {task.id}: {task.name} ({task.method})")
    
    # Execute workflow
    print("\n--- Executing Workflow ---\n")
    try:
        execution = await engine.execute_workflow(workflow)
        
        print(f"\n✓ Workflow completed!")
        print(f"  Status: {execution.status}")
        print(f"  Tasks executed: {len(execution.task_results)}")
        
        # Show results
        print("\n--- Task Results ---\n")
        for task_id, result in execution.task_results.items():
            print(f"Task: {task_id}")
            if "response" in result:
                print(f"  Response: {result['response'][:200]}...")
            elif "report" in result:
                print(f"  Report: {result['report'][:200]}...")
            elif "analysis" in result:
                print(f"  Analysis: {result['analysis'][:200]}...")
            elif "code" in result:
                print(f"  Code generated: {len(result['code'])} chars")
            print()
        
        # Check for errors
        if execution.error:
            print(f"⚠ Workflow had errors: {execution.error}")
        
    except Exception as e:
        print(f"✗ Workflow execution failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Get agent status
    print("\n--- Agent Hub Status ---")
    status = await agent_hub.get_agent_status()
    print(f"Total agents: {status['total_agents']}/{status['max_agents']}")
    for agent in status['agents']:
        print(f"  - {agent['id']}: {agent['type']} (sessions: {agent['sessions']})")
        if agent['metrics']:
            print(f"    Requests: {agent['metrics']['total_requests']}")
    
    # Cleanup
    print("\n--- Cleanup ---")
    await engine.stop()
    await resource_manager.stop()
    await persistence.cleanup()
    print("✓ All resources cleaned up")


if __name__ == "__main__":
    asyncio.run(test_agent_cli())