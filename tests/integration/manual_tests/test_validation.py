#!/usr/bin/env python3
"""
Test provider validation at workflow submission time.
"""

import asyncio
import sys
from pathlib import Path

async def main():
    # Import required modules
    from src.gleitzeit.system.system_manager import SystemManager
    from src.gleitzeit.system.models import SystemConfig
    from src.gleitzeit.client import GleitzeitClient, ClientMode
    from src.gleitzeit.persistence.factory import PersistenceFactory
    
    print("=== Testing Provider Validation ===")
    
    try:
        # Create persistence
        print("1. Creating persistence backend...")
        persistence = await PersistenceFactory.create()
        
        # Create system config
        print("2. Creating system configuration...")
        config = SystemConfig(
            environment="development",
            persistence_backend="redis",
            enable_auth=False,
            default_providers=["python", "ollama"]
        )
        
        # Create and initialize SystemManager
        print("3. Initializing SystemManager...")
        system_manager = SystemManager(config=config, persistence=persistence)
        await system_manager.initialize()
        
        # Start the system
        print("4. Starting system components...")
        await system_manager.start_system()
        print("✓ SystemManager started successfully")
        
        # Check if validation is working
        print("\n5. Testing provider validation...")
        
        # Check registry
        if system_manager.registry:
            print("Registry is available")
            
            # Test validation for llm/v1
            is_available, error_msg = await system_manager.registry.validate_provider_availability("llm/v1")
            if is_available:
                print(f"✓ Provider 'llm/v1' is available")
            else:
                print(f"✗ Provider 'llm/v1' is NOT available: {error_msg}")
                print("This is expected if Ollama is not running")
        
        # Create client
        print("\n6. Creating client...")
        import secrets
        service_token = secrets.token_hex(32)
        GleitzeitClient.set_service_token(service_token)
        
        client = GleitzeitClient(
            mode=ClientMode.NATIVE,
            service_token=service_token,
            enable_events=False
        )
        await client.initialize()
        
        # Connect client to SystemManager
        if hasattr(client, '_adapter'):
            client._adapter.set_system_manager(system_manager)
        
        print("✓ Client initialized")
        
        # Load workflow
        print("\n7. Loading workflow...")
        from src.gleitzeit.core.workflow_loader_v2 import WorkflowLoaderV2
        
        registry = system_manager.registry if hasattr(system_manager, 'registry') else None
        loader = WorkflowLoaderV2(registry=registry)
        workflow = loader.load_workflow_from_file('examples/dependent_workflow.yaml')
        print(f"✓ Loaded workflow: {workflow.name}")
        
        # Try to submit workflow - this should fail validation
        print("\n8. Attempting to submit workflow (should fail if Ollama not running)...")
        try:
            result = await client.submit_workflow(workflow)
            print(f"✗ Workflow was submitted: {result}")
            print("This means validation did NOT work properly!")
        except Exception as e:
            print(f"✓ Workflow submission failed as expected: {e}")
            if "not available" in str(e).lower():
                print("✓ Validation is working correctly!")
            else:
                print("✗ Failed for different reason than expected")
    
    finally:
        # Clean shutdown
        print("\n9. Shutting down...")
        if 'client' in locals():
            await client.shutdown()
        if 'system_manager' in locals():
            await system_manager.shutdown_system()
            await system_manager.shutdown()
        print("✓ Clean shutdown complete")

if __name__ == "__main__":
    asyncio.run(main())