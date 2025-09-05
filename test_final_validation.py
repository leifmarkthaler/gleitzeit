#!/usr/bin/env python3
"""
Final test: Workflow submission should fail instantly when Ollama not available.
"""

import asyncio
import sys

async def main():
    from src.gleitzeit.system.system_manager import SystemManager
    from src.gleitzeit.system.models import SystemConfig
    from src.gleitzeit.persistence.factory import PersistenceFactory
    from src.gleitzeit.core.workflow_loader_v2 import WorkflowLoaderV2
    
    print("=== VALIDATION TEST ===\n")
    
    # Create system
    persistence = await PersistenceFactory.create()
    config = SystemConfig(
        environment="development",
        persistence_backend="redis",
        enable_auth=False,
        default_providers=["python", "ollama"]
    )
    
    system_manager = SystemManager(config=config, persistence=persistence)
    await system_manager.initialize()
    await system_manager.start_system()
    print("✓ System started\n")
    
    # Check if Ollama provider can allocate resources
    pooling_adapter = system_manager.pooling_adapter
    if pooling_adapter:
        is_available, error = await pooling_adapter.validate_provider_availability("llm/v1")
        print(f"Ollama (llm/v1) availability check:")
        print(f"  Available: {is_available}")
        if not is_available:
            print(f"  Reason: {error}")
        print()
    
    # Load workflow  
    loader = WorkflowLoaderV2()
    workflow = loader.load_workflow_from_file('examples/dependent_workflow.yaml')
    print(f"Loaded workflow: {workflow.name}\n")
    
    # Submit workflow through workflow manager
    print("Submitting workflow...")
    try:
        result = await system_manager.workflow_manager.execute_workflow(workflow)
        print(f"❌ ERROR: Workflow was accepted! ID: {result}")
        print("Validation is NOT working!")
        sys.exit(1)
    except Exception as e:
        error_str = str(e)
        print(f"✓ Workflow rejected: {error_str}")
        
        # Check if it failed for the right reason
        if "not available" in error_str.lower():
            print("✓✓ SUCCESS: Validation working correctly!")
            print("   Workflow was rejected because Ollama is not available")
            sys.exit(0)
        else:
            print(f"❌ Failed for unexpected reason")
            sys.exit(1)
    finally:
        await system_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(main())