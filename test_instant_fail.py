#!/usr/bin/env python3
"""
Test that workflow submission fails instantly when Ollama is not available.
"""

import asyncio
import sys

async def main():
    from src.gleitzeit.system.system_manager import SystemManager
    from src.gleitzeit.system.models import SystemConfig
    from src.gleitzeit.persistence.factory import PersistenceFactory
    from src.gleitzeit.core.workflow_loader_v2 import WorkflowLoaderV2
    
    print("=== Test Instant Validation Failure ===\n")
    
    # Create minimal system
    persistence = await PersistenceFactory.create()
    config = SystemConfig(
        environment="development",
        persistence_backend="redis",
        enable_auth=False,
        default_providers=["python", "ollama"]  # Include ollama
    )
    
    system_manager = SystemManager(config=config, persistence=persistence)
    await system_manager.initialize()
    await system_manager.start_system()
    
    print("System started with Ollama provider registered\n")
    
    # Check provider availability
    if system_manager.registry:
        is_available, error = await system_manager.registry.validate_provider_availability("llm/v1")
        print(f"Provider 'llm/v1' availability: {is_available}")
        if not is_available:
            print(f"Reason: {error}\n")
    
    # Load workflow
    loader = WorkflowLoaderV2(registry=system_manager.registry)
    workflow = loader.load_workflow_from_file('examples/dependent_workflow.yaml')
    print(f"Loaded workflow: {workflow.name}")
    
    # Try to submit - should fail instantly
    print("\nSubmitting workflow (should fail immediately)...")
    try:
        # Get the workflow manager
        wf_mgr = system_manager.workflow_manager
        result = await wf_mgr.execute_workflow(workflow)
        print(f"ERROR: Workflow was accepted! ID: {result}")
        print("❌ VALIDATION DID NOT WORK!")
        sys.exit(1)
    except Exception as e:
        print(f"✓ Workflow rejected: {e}")
        if "not available" in str(e).lower() or "not registered" in str(e).lower():
            print("✓ VALIDATION WORKING CORRECTLY!")
            sys.exit(0)
        else:
            print(f"❌ Unexpected error: {e}")
            sys.exit(1)
    finally:
        await system_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(main())